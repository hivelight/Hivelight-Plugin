"""Mint a workspace-scoped JWT for an additional workspace, using the persisted login.

Usage:  python add_workspace_jwt.py <workspaceId>
"""
from __future__ import annotations
import sys
import time
from playwright.sync_api import sync_playwright

from setup import PROFILE_DIR
from hivelight import save_scoped_jwt


def main(workspace_id: str) -> None:
    switch_url = (
        f"https://app.hivelight.com/identity/switch/workspace?"
        f"workspaceId={workspace_id}&then=/w/{workspace_id}/dashboard"
    )
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1400, "height": 900},
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(switch_url, wait_until="load", timeout=60_000)
            print(f"Loaded: {page.url}")
            # Poll for token in either sessionStorage or localStorage, up to 5 minutes
            scoped = None
            deadline = time.time() + 300
            seen_login_prompt = False
            while time.time() < deadline:
                try:
                    s_tok = page.evaluate("() => sessionStorage.getItem('token')")
                    l_tok = page.evaluate("() => localStorage.getItem('token')")
                except Exception as e:
                    print(f"eval error: {e}")
                    time.sleep(2)
                    continue
                # We want a token whose payload includes workspaceId == target
                cand = s_tok or l_tok
                if cand and len(cand) > 20:
                    import base64, json
                    parts = cand.split(".")
                    if len(parts) >= 2:
                        pad = "=" * (-len(parts[1]) % 4)
                        try:
                            payload = json.loads(base64.urlsafe_b64decode(parts[1] + pad).decode("utf-8", errors="replace"))
                        except Exception:
                            payload = {}
                    else:
                        payload = {}
                    wid = payload.get("workspaceId")
                    if wid == workspace_id:
                        scoped = cand
                        print(f"Got scoped JWT for workspace {wid} (from {'session' if s_tok and s_tok==cand else 'local'}Storage).")
                        break
                    elif wid is None and l_tok:
                        # Broad token; not what we want yet
                        pass
                if "login" in page.url.lower() and not seen_login_prompt:
                    print("Login page detected — please log in in the browser window. Waiting...")
                    seen_login_prompt = True
                time.sleep(2)

            if not scoped:
                print(f"Timed out waiting for scoped JWT for {workspace_id}. Final URL: {page.url}")
                # dump diagnostics
                s_tok = page.evaluate("() => sessionStorage.getItem('token')")
                l_tok = page.evaluate("() => localStorage.getItem('token')")
                print(f"sessionStorage.token present: {bool(s_tok)}  localStorage.token present: {bool(l_tok)}")
                return

            save_scoped_jwt(workspace_id, scoped)
            print(f"Saved scoped JWT for {workspace_id}.")
        finally:
            context.close()


if __name__ == "__main__":
    main(sys.argv[1])
