"""First-run auth bootstrap for the Hivelight skill.

Run from this directory:

    python setup.py                                       # interactive workspace picker
    python setup.py --sandbox-workspace "Your Workspace Name"  # skip prompt by name match

Flow:
1. Open headed Playwright browser at app.hivelight.com login.
2. User logs in manually (reCAPTCHA solves itself in a real browser).
3. After redirect to /, harvest ``localStorage.token`` (broad JWT).
4. Pick a workspace -> trigger workspace switch -> harvest ``sessionStorage.token`` (scoped JWT).
5. Auto-create an API key labelled "Hivelight Skill (auto-generated)".
6. Store everything in OS keychain via ``keyring``.

The user only does the login step. Everything else is automated.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

# Local module path
sys.path.insert(0, str(Path(__file__).parent))

from hivelight import (  # noqa: E402  (sys.path tweak above)
    ACCOUNT_API_KEY,
    ACCOUNT_JWT_BROAD,
    DEFAULT_CONFIG_PATH,
    HivelightError,
    _decode_jwt_payload,
    _load_config,
    _save_config,
    _save_credential,
    save_scoped_jwt,
)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print(
        "ERROR: Playwright is not installed. Install it with:\n"
        "    pip install playwright\n"
        "    playwright install chromium",
        file=sys.stderr,
    )
    sys.exit(1)


LOGIN_URL = "https://app.hivelight.com/identity/login"

# Persistent Playwright profile so the user doesn't have to re-login on every
# setup re-run. Stored alongside the config.
PROFILE_DIR = Path.home() / ".config" / "hivelight-skill" / "playwright-profile"


# ---------------------------------------------------------------------------
# Silent refresh (used by HivelightClient when the scoped JWT expires)
# ---------------------------------------------------------------------------

class HivelightRefreshFailed(HivelightError):
    """Raised when a silent JWT refresh cannot complete — usually because the
    Hivelight login cookie has aged out (~30 days) and a real interactive
    login is needed. Caller should surface a "double-click refresh" message."""


def refresh_scoped_jwt(workspace_id: str, *, timeout_seconds: int = 30) -> str:
    """Headlessly mint a fresh workspace-scoped JWT using the persistent browser
    profile. Returns the new JWT (also saved to the OS keychain).

    The persistent profile carries Hivelight's ~30-day login cookie, so this
    succeeds without user interaction. If the cookie has expired, the browser
    lands on the login page — we detect that and raise ``HivelightRefreshFailed``
    so the caller can prompt for a manual ``setup.py`` re-run.

    Designed to be called from inside the lib when an API call raises
    ``HivelightAuthExpired``. Takes ~3-5 seconds end-to-end.
    """
    switch_url = (
        f"https://app.hivelight.com/identity/switch/workspace?"
        f"workspaceId={workspace_id}&then=/w/{workspace_id}/dashboard"
    )
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=True,
            viewport={"width": 1280, "height": 800},
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(switch_url, wait_until="domcontentloaded", timeout=20_000)
            except Exception as e:
                raise HivelightRefreshFailed(
                    f"Could not load the workspace-switch URL ({e}). "
                    "Network down, or run the manual refresh."
                )

            deadline = time.time() + timeout_seconds
            while time.time() < deadline:
                # Cookie-expired check: if the SPA bounced us to a login page,
                # the persistent cookie has aged out (~30 days) — fail fast.
                cur_url = (page.url or "").lower()
                if "/login" in cur_url or "auth-" in cur_url or "cognito" in cur_url:
                    raise HivelightRefreshFailed(
                        "Hivelight's persistent login cookie has expired "
                        "(~30 days). Double-click 'Hivelight Refresh' on your "
                        "Desktop (or re-run setup.py) to log in again."
                    )
                try:
                    token = page.evaluate("() => sessionStorage.getItem('token')")
                except Exception:
                    token = None
                if token and len(token) > 20:
                    payload = _decode_jwt_payload(token)
                    if payload.get("workspaceId") == workspace_id:
                        save_scoped_jwt(workspace_id, token)
                        return token
                time.sleep(0.4)

            raise HivelightRefreshFailed(
                f"Refresh timed out after {timeout_seconds}s — JWT did not "
                "appear in sessionStorage. Try the manual refresh."
            )
        finally:
            ctx.close()


def _wait_for_login(page, *, max_wait_seconds: int = 600) -> str:
    """Block until the user finishes login. Returns the harvested broad JWT."""
    print(">>> A browser window is opening. Please log in to Hivelight there.")
    print(">>> Waiting for login to complete... (timeout: 10 minutes)")
    deadline = time.time() + max_wait_seconds
    while time.time() < deadline:
        # Look for localStorage.token -- set after successful login
        token = page.evaluate("() => localStorage.getItem('token')")
        if token and len(token) > 20:
            return token
        # Also exit if the page closed or navigated away
        time.sleep(1)
    raise HivelightError("Login timed out after 10 minutes")


def _trigger_workspace_switch(page, workspace_id: str) -> str:
    """Navigate to a workspace context to mint the scoped JWT, then read sessionStorage.token.

    Hivelight's documented switch endpoint is ``GET /identity/switch/workspace?workspaceId=<id>&then=<path>``;
    it server-side re-binds the session and redirects. We use ``wait_until="load"``
    rather than ``networkidle`` because the SPA keeps polling and never reaches idle.
    """
    switch_url = (
        f"https://app.hivelight.com/identity/switch/workspace?"
        f"workspaceId={workspace_id}&then=/w/{workspace_id}/dashboard"
    )
    try:
        page.goto(switch_url, wait_until="load", timeout=60_000)
    except Exception:
        # Fall back to the direct dashboard URL if the switch endpoint changes
        page.goto(
            f"https://app.hivelight.com/w/{workspace_id}/dashboard",
            wait_until="load",
            timeout=60_000,
        )

    # Wait until the SPA writes the scoped JWT into sessionStorage.
    page.wait_for_function(
        "() => sessionStorage.getItem('token') && sessionStorage.getItem('token').length > 20",
        timeout=60_000,
    )
    return page.evaluate("() => sessionStorage.getItem('token')")


def _harvest_workspaces(page, broad_jwt: str) -> list[dict]:
    """Fetch the user's workspaces from the API using the broad JWT.

    We used to scrape ``localStorage.getItem('workspaces')``, but Hivelight no
    longer stashes the list there. ``GET /v1/workspaces`` is the documented
    endpoint that backs the workspace picker in the UI.
    """
    import requests

    resp = requests.get(
        "https://app.hivelight.com/v1/workspaces",
        headers={"Authorization": f"Bearer {broad_jwt}"},
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()

    # Response shape: JSON:API style -- {data: [{type:"workspace", id, attributes:{name, ...}}, ...]}
    data = body.get("data") or []
    out: list[dict] = []
    for w in data:
        if isinstance(w, dict):
            attrs = w.get("attributes") or {}
            wid = w.get("id") or attrs.get("workspace-id") or attrs.get("workspaceId")
            name = attrs.get("name") or attrs.get("workspace-name") or wid
            if wid:
                out.append({"id": wid, "name": name, "raw": w})
    return out


def _create_api_key(scoped_jwt: str, user_id: str, *, label: str) -> str:
    """Call POST /v1/api/keys via the page's fetch (so it goes through the right origin)."""
    import requests

    resp = requests.post(
        "https://app.hivelight.com/v1/api/keys",
        headers={
            "Authorization": f"Bearer {scoped_jwt}",
            "Content-Type": "application/json",
        },
        data=json.dumps({"meta": {"label": label, "userId": user_id}}),
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    value = body.get("data", {}).get("attributes", {}).get("value")
    if not value:
        raise HivelightError(f"Unexpected create-key response shape: {body}")
    return value


def run_setup(*, sandbox_workspace_label: Optional[str] = None) -> None:
    """Run the full first-run setup flow."""
    print("=" * 60)
    print("Hivelight Skill -- First-Run Setup")
    print("=" * 60)

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        # Persistent profile = cookies + localStorage survive between runs, so a
        # user who already logged in once doesn't have to log in again (until
        # Hivelight's own 30-day cookie expires).
        context = pw.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1400, "height": 900},
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(LOGIN_URL)

            # 1. User login
            broad_jwt = _wait_for_login(page)
            print("[ok] Captured broad JWT.")

            # 2. Decode userId
            payload = _decode_jwt_payload(broad_jwt)
            user_id = payload.get("userId")
            if not user_id:
                raise HivelightError(f"Broad JWT has no userId claim: {payload}")
            print(f"[ok] Logged in as user {user_id}.")

            # 3. Read workspaces (API call, not localStorage)
            workspaces = _harvest_workspaces(page, broad_jwt)
            if not workspaces:
                raise HivelightError(
                    "GET /v1/workspaces returned no workspaces. Check the broad JWT or your account."
                )
            print(f"[ok] Found {len(workspaces)} workspace(s).")

            # 4. Pick the workspace to use as default + sandbox
            chosen = _choose_workspace(workspaces, sandbox_workspace_label)
            print(f"[ok] Using workspace: {chosen['name']} ({chosen['id']})")

            # 5. Trigger workspace switch -> harvest scoped JWT
            scoped_jwt = _trigger_workspace_switch(page, chosen["id"])
            print("[ok] Captured workspace-scoped JWT.")

            # 6. Create the API key
            label = "Hivelight Skill (auto-generated)"
            api_key = _create_api_key(scoped_jwt, user_id, label=label)
            print(f"[ok] Created API key labelled '{label}'.")

            # 7. Persist to keychain + config
            _save_credential(ACCOUNT_API_KEY, api_key)
            _save_credential(ACCOUNT_JWT_BROAD, broad_jwt)
            save_scoped_jwt(chosen["id"], scoped_jwt)
            print("[ok] Stored credentials in OS keychain.")

            config = _load_config()
            config["default_workspace_id"] = chosen["id"]
            config["default_workspace_name"] = chosen["name"]
            config["user_id"] = user_id
            if sandbox_workspace_label:
                config["sandbox_workspace_label"] = sandbox_workspace_label
            _save_config(config)
            print(f"[ok] Wrote config to {DEFAULT_CONFIG_PATH}")

            print()
            print("Setup complete. You can close the browser window if it's still open.")
            print("The skill is ready to use.")
            print()
            print("To revoke this key later: Settings -> Integrations -> API in the Hivelight UI.")
        finally:
            context.close()


def _choose_workspace(workspaces: list[dict], preferred_label: Optional[str]) -> dict:
    """Pick a workspace, preferring one whose name matches ``preferred_label`` if given.

    The workspaces list from localStorage has objects with keys 'organizationId',
    'workspaceId' (or 'id'), and 'name' -- schema varies. Be defensive.
    """
    normalized = []
    for w in workspaces:
        wid = w.get("id") or w.get("workspaceId")
        name = w.get("name") or w.get("workspaceName") or wid
        if wid:
            normalized.append({"id": wid, "name": name, "raw": w})

    if not normalized:
        raise HivelightError(f"Could not parse any workspaces from {workspaces}")

    if preferred_label:
        for w in normalized:
            if preferred_label.lower() in (w["name"] or "").lower():
                return w
        print(
            f"[warn] No workspace named '{preferred_label}' -- falling back to first available."
        )

    if len(normalized) == 1:
        return normalized[0]

    # Interactive picker
    print("\nAvailable workspaces:")
    for i, w in enumerate(normalized, 1):
        print(f"  {i}. {w['name']} ({w['id']})")
    while True:
        choice = input("Pick a workspace to use as default [1]: ").strip() or "1"
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(normalized):
                return normalized[idx]
        except ValueError:
            pass
        print("  (invalid choice -- try again)")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="First-run setup for the Hivelight skill")
    parser.add_argument(
        "--sandbox-workspace",
        help="Workspace name (or substring) to prefer as the default sandbox",
    )
    args = parser.parse_args()
    try:
        run_setup(sandbox_workspace_label=args.sandbox_workspace)
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        sys.exit(130)
    except HivelightError as e:
        print(f"\nSetup failed: {e}", file=sys.stderr)
        sys.exit(1)
