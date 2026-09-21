"""Hivelight HTTP client with dual-tier auth.

The Hivelight backend exposes two API surfaces:

* ``api.hivelight.com/v1/*`` — public, x-api-key auth, durable credential.
* ``app.hivelight.com/v1/*`` — internal (used by the web UI), JWT Bearer auth,
  3-day expiry, reCAPTCHA-gated login.

This client transparently routes requests to the appropriate surface based on
the explicit ``host`` argument, and surfaces typed exceptions on error. It does
NOT attempt password login (reCAPTCHA blocks programmatic flows) — instead it
relies on credentials previously stashed in OS keychain by ``setup.py``.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

import requests

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class HivelightError(Exception):
    """Base for all hivelight errors."""

    def __init__(self, message: str, *, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class HivelightAuthMissing(HivelightError):
    """No credentials configured. User must run ``setup.py`` first."""


class HivelightAuthExpired(HivelightError):
    """The stored JWT is expired and silent refresh failed. User must re-run setup."""


class HivelightAuthError(HivelightError):
    """The server rejected our credentials (401/403). Likely revoked or wrong scope."""


class HivelightNotFound(HivelightError):
    """404 from the API."""


class HivelightValidationError(HivelightError):
    """422 from the API — request body or query params didn't validate."""


class HivelightServerError(HivelightError):
    """5xx from the API."""


# ---------------------------------------------------------------------------
# Credential store
# ---------------------------------------------------------------------------


KEYRING_SERVICE = "hivelight.skill"
ACCOUNT_API_KEY = "api_key"
ACCOUNT_JWT_BROAD = "jwt_broad"
ACCOUNT_JWT_SCOPED_PREFIX = "jwt_scoped:"  # full account name is "jwt_scoped:<workspaceId>"

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "hivelight-skill" / "config.json"

# Absolute path to setup.py so error messages can tell the user exactly what
# to run on this machine. This module sits in the same directory as setup.py.
_SETUP_SCRIPT_PATH = str(Path(__file__).resolve().parent / "setup.py")
_SETUP_HINT = f'python "{_SETUP_SCRIPT_PATH}"'


@dataclass
class Credentials:
    api_key: Optional[str] = None
    jwt_broad: Optional[str] = None
    jwt_scoped: dict[str, str] = field(default_factory=dict)  # workspaceId -> JWT


def _decode_jwt_payload(token: str) -> dict:
    """Decode the JWT payload (no signature verification — we only need the claims)."""
    try:
        _header, payload, _sig = token.split(".")
        padded = payload + "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception as e:  # noqa: BLE001
        raise HivelightError(f"Failed to decode JWT: {e}") from e


def _jwt_is_expired(token: str, *, leeway_seconds: int = 60) -> bool:
    """True if the JWT is past its ``exp`` claim (or within ``leeway_seconds`` of it)."""
    payload = _decode_jwt_payload(token)
    exp = payload.get("exp")
    if not exp:
        return False  # no exp claim — assume valid
    return time.time() + leeway_seconds >= exp


def _load_credentials() -> Credentials:
    """Load creds from OS keychain. Quietly returns blanks if nothing is stored."""
    try:
        import keyring  # noqa: PLC0415  (deferred import — keyring is optional at import-time)
    except ImportError as e:
        raise HivelightAuthMissing(
            "The `keyring` package is required. Install with: pip install keyring"
        ) from e

    creds = Credentials()
    creds.api_key = keyring.get_password(KEYRING_SERVICE, ACCOUNT_API_KEY)
    creds.jwt_broad = keyring.get_password(KEYRING_SERVICE, ACCOUNT_JWT_BROAD)

    # Workspace-scoped JWTs are stored under "jwt_scoped:<workspaceId>" — we have
    # no enumeration API in keyring, so we read them lazily via load_scoped_jwt().
    return creds


def _save_credential(account: str, value: str) -> None:
    import keyring  # noqa: PLC0415

    keyring.set_password(KEYRING_SERVICE, account, value)


def _delete_credential(account: str) -> None:
    import keyring  # noqa: PLC0415

    try:
        keyring.delete_password(KEYRING_SERVICE, account)
    except Exception:  # noqa: BLE001
        pass  # already absent — fine


def load_scoped_jwt(workspace_id: str) -> Optional[str]:
    import keyring  # noqa: PLC0415

    return keyring.get_password(KEYRING_SERVICE, f"{ACCOUNT_JWT_SCOPED_PREFIX}{workspace_id}")


def save_scoped_jwt(workspace_id: str, jwt: str) -> None:
    _save_credential(f"{ACCOUNT_JWT_SCOPED_PREFIX}{workspace_id}", jwt)


# ---------------------------------------------------------------------------
# Config file (non-secret data: default workspace, sandbox workspace, etc.)
# ---------------------------------------------------------------------------


def _load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text("utf-8"))


def _save_config(data: dict, path: Path = DEFAULT_CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def _to_unix_ms(value: Union[int, float, dt.datetime, dt.date, None]) -> Optional[int]:
    """Coerce a date-ish value to Unix milliseconds.

    Accepts: int/float (assumed seconds if < 1e12, else ms), datetime, date, or None.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 1e12 else int(value * 1000)
    if isinstance(value, dt.datetime):
        return int(value.timestamp() * 1000)
    if isinstance(value, dt.date):
        return int(dt.datetime(value.year, value.month, value.day).timestamp() * 1000)
    raise TypeError(f"Cannot convert {type(value).__name__} to Unix ms")


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------


PUBLIC_HOST = "https://api.hivelight.com"
INTERNAL_HOST = "https://app.hivelight.com"


class HivelightClient:
    """Auth-aware HTTP client for Hivelight.

    Typical usage::

        c = HivelightClient(workspace_id="abc123")
        matters = c.matters.list()
        c.workflows.apply(workflow_id="xyz", matter_id="abc")
        c.milestones.shift(milestone_id="m1", offset_days=14, cascade=True)

    For arbitrary endpoints not covered by the ergonomic helpers, use the
    generic call wrappers::

        c.public_call("GET", "/v1/matters/{id}", path_params={"id": "..."})
        c.internal_call("POST", "/v1/workflows/{wfId}/apply",
                        path_params={"wfId": "..."},
                        query={"matterId": "...", "startDate": <ms>})
    """

    def __init__(
        self,
        workspace_id: Optional[str] = None,
        *,
        session: Optional[requests.Session] = None,
        timeout_seconds: int = 30,
    ):
        self._session = session or requests.Session()
        self._timeout = timeout_seconds
        self._creds = _load_credentials()
        self._config = _load_config()
        self._workspace_id = workspace_id or self._config.get("default_workspace_id")

        # Resource group helpers (lazy)
        self.matters = _Matters(self)
        self.workflows = _Workflows(self)
        self.milestones = _Milestones(self)
        self.tasks = _Tasks(self)
        self.api_keys = _ApiKeys(self)
        self.imports = _Imports(self)

        # Reentrancy guard — the refresh path itself MUST NOT loop into _get_jwt.
        # refresh_scoped_jwt uses Playwright (no JWT involved), so this is purely
        # defensive in case future refresh impls add API calls.
        self._refresh_in_progress: bool = False

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def workspace_id(self) -> Optional[str]:
        return self._workspace_id

    def use_workspace(self, workspace_id: str) -> None:
        """Set the active workspace. Subsequent JWT calls use the scoped token for this workspace."""
        self._workspace_id = workspace_id

    # ------------------------------------------------------------------
    # Generic call wrappers
    # ------------------------------------------------------------------

    def public_call(
        self,
        method: str,
        path: str,
        *,
        path_params: Optional[dict] = None,
        query: Optional[dict] = None,
        json_body: Optional[Any] = None,
    ) -> Any:
        """Call the public API at api.hivelight.com using the stored x-api-key."""
        if not self._creds.api_key:
            raise HivelightAuthMissing(
                f"No API key stored. Run setup: {_SETUP_HINT}"
            )
        url = self._build_url(PUBLIC_HOST, path, path_params)
        headers = {"x-api-key": self._creds.api_key}
        return self._request(method, url, headers=headers, params=query, json_body=json_body)

    def internal_call(
        self,
        method: str,
        path: str,
        *,
        path_params: Optional[dict] = None,
        query: Optional[dict] = None,
        json_body: Optional[Any] = None,
        requires_workspace: bool = True,
    ) -> Any:
        """Call the internal API at app.hivelight.com using the appropriate JWT.

        ``requires_workspace=True`` (default) uses the workspace-scoped JWT.
        Set False for endpoints that don't need a workspace context (e.g. whoami).
        """
        jwt = self._get_jwt(requires_workspace=requires_workspace)
        url = self._build_url(INTERNAL_HOST, path, path_params)
        headers = {"Authorization": f"Bearer {jwt}"}
        return self._request(method, url, headers=headers, params=query, json_body=json_body)

    # Alias used by some ergonomic methods
    def call(self, method: str, path: str, **kwargs) -> Any:
        """Shorthand: defaults to internal_call. Pass ``public=True`` for public_call."""
        public = kwargs.pop("public", False)
        if public:
            return self.public_call(method, path, **kwargs)
        return self.internal_call(method, path, **kwargs)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_url(self, host: str, path: str, path_params: Optional[dict]) -> str:
        if path_params:
            for k, v in path_params.items():
                path = path.replace("{" + k + "}", str(v))
        return host + path

    def _get_jwt(self, *, requires_workspace: bool) -> str:
        if requires_workspace:
            if not self._workspace_id:
                raise HivelightError(
                    "This operation requires a workspace context. "
                    "Set one with `client.use_workspace(<id>)` or pass workspace_id to the constructor."
                )
            jwt = self._creds.jwt_scoped.get(self._workspace_id) or load_scoped_jwt(self._workspace_id)
            if jwt and not _jwt_is_expired(jwt):
                self._creds.jwt_scoped[self._workspace_id] = jwt
                return jwt
            # Stored scoped JWT missing or expired — try a silent headless refresh
            # before bothering the user. Takes ~3-5 seconds when the 30-day login
            # cookie is still valid.
            if not self._refresh_in_progress:
                refreshed = self._try_silent_refresh()
                if refreshed:
                    self._creds.jwt_scoped[self._workspace_id] = refreshed
                    return refreshed
            raise HivelightAuthExpired(
                f"No valid workspace-scoped JWT for workspace {self._workspace_id}. "
                f"Silent refresh failed — the 30-day Hivelight login cookie has "
                f"likely expired. Double-click 'Hivelight Refresh' on your Desktop, "
                f"or re-run setup: {_SETUP_HINT}"
            )
        # Broad JWT (no workspace claim)
        if self._creds.jwt_broad and not _jwt_is_expired(self._creds.jwt_broad):
            return self._creds.jwt_broad
        raise HivelightAuthExpired(
            f"No valid broad JWT. Re-run setup: {_SETUP_HINT}"
        )

    def _try_silent_refresh(self) -> Optional[str]:
        """Attempt a headless workspace-JWT refresh using the persistent browser
        profile. Returns the new JWT on success, None on failure.

        Failure causes (all non-fatal at this layer — caller raises ``HivelightAuthExpired``):
        - Playwright not installed
        - 30-day login cookie has expired (lands on login page, can't auto-log-in)
        - Network down
        - setup.py not importable (e.g. plugin moved)
        """
        if not self._workspace_id:
            return None
        self._refresh_in_progress = True
        try:
            try:
                # Lazy import — keeps Playwright off HivelightClient's import path.
                from setup import refresh_scoped_jwt  # type: ignore
            except ImportError:
                logging.getLogger(__name__).debug(
                    "Silent refresh unavailable: cannot import setup.refresh_scoped_jwt"
                )
                return None
            try:
                return refresh_scoped_jwt(self._workspace_id, timeout_seconds=30)
            except Exception as e:
                logging.getLogger(__name__).info(
                    "Silent JWT refresh failed: %s: %s", type(e).__name__, e
                )
                return None
        finally:
            self._refresh_in_progress = False

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict,
        params: Optional[dict] = None,
        json_body: Optional[Any] = None,
    ) -> Any:
        # Strip None query params (otherwise they go through as "None")
        if params:
            params = {k: v for k, v in params.items() if v is not None}
        # IMPORTANT (per inventory common-mistakes): never send Content-Type on GET/DELETE
        if json_body is not None and method.upper() in ("POST", "PUT", "PATCH"):
            headers = {**headers, "Content-Type": "application/json"}
        try:
            resp = self._session.request(
                method.upper(),
                url,
                headers=headers,
                params=params,
                data=json.dumps(json_body) if json_body is not None else None,
                timeout=self._timeout,
            )
        except requests.RequestException as e:
            raise HivelightError(f"Network error calling {url}: {e}") from e

        return self._handle_response(resp, method=method, url=url)

    def _handle_response(self, resp: requests.Response, *, method: str, url: str) -> Any:
        status = resp.status_code
        # Try to parse body as JSON; fall back to text
        body: Any
        try:
            body = resp.json()
        except ValueError:
            body = resp.text

        if 200 <= status < 300:
            # Quirk: app.hivelight.com returns 200 + the SPA HTML for unrecognised
            # /v1/* paths (the API gateway falls through to the React shell).
            # Detect this and raise rather than silently returning HTML.
            content_type = resp.headers.get("content-type", "")
            if "text/html" in content_type or (isinstance(body, str) and body.lstrip().startswith("<")):
                raise HivelightNotFound(
                    f"{method.upper()} {url} -> 200 but server returned HTML "
                    "(path likely doesn't exist on the API gateway)",
                    status=status,
                    body=body[:200] if isinstance(body, str) else body,
                )
            return body

        msg = f"{method.upper()} {url} -> {status}"
        if status == 401:
            raise HivelightAuthError(msg, status=status, body=body)
        if status == 403:
            raise HivelightAuthError(msg, status=status, body=body)
        if status == 404:
            raise HivelightNotFound(msg, status=status, body=body)
        if status == 422:
            raise HivelightValidationError(msg, status=status, body=body)
        if status >= 500:
            raise HivelightServerError(msg, status=status, body=body)
        raise HivelightError(msg, status=status, body=body)


# ---------------------------------------------------------------------------
# Ergonomic resource groups
# ---------------------------------------------------------------------------


class _Matters:
    def __init__(self, client: HivelightClient):
        self._c = client

    def list(self) -> list[dict]:
        """List all matters in the active workspace. Public API."""
        return self._c.public_call("GET", "/v1/matters")

    def get(self, matter_id: str) -> dict:
        """Get a single matter."""
        return self._c.public_call("GET", "/v1/matters/{id}", path_params={"id": matter_id})

    def create(
        self,
        *,
        name: str,
        owner_user_id: str,
        types: Optional[list[str]] = None,
        jurisdictions: Optional[list[str]] = None,
    ) -> dict:
        """Create a new matter. Uses internal API.

        Note: Hivelight will auto-prefix ``name`` with a sequential id (e.g. ``"250006 - <name>"``).
        Do not pre-add such a prefix yourself.
        """
        body = {
            "jsonapi": {"version": "1.0"},
            "data": {
                "type": "matter",
                "attributes": {
                    "name": name,
                    "types": types or [],
                    "jurisdictions": jurisdictions or [],
                    "roles": {"OWNER": [owner_user_id]},
                },
            },
        }
        return self._c.internal_call("POST", "/v1/matters", json_body=body)

    def archive(self, matter_id: str) -> dict:
        return self._c.internal_call(
            "POST", "/v1/matters/{id}/archive", path_params={"id": matter_id}
        )

    def unarchive(self, matter_id: str) -> dict:
        return self._c.internal_call(
            "DELETE", "/v1/matters/{id}/archive", path_params={"id": matter_id}
        )

    def delete(self, matter_id: str) -> dict:
        """Delete a matter. NOTE: matter must be archived first; otherwise returns 403."""
        return self._c.internal_call(
            "DELETE", "/v1/matters/{id}", path_params={"id": matter_id}
        )

    def assign_to_role(
        self,
        *,
        matter_id: Union[str, list[str]],
        role: str,
        user_id: str,
        action: str = "ADD",
    ) -> dict:
        """Assign a user to a role on one or more matters.

        ``role`` is one of the workspace's defined roles (see workspace config
        ``matterRoles``): ``PRINCIPAL``, ``BUSINESS_1``, ``ADVOCATE_1``,
        ``CONSULTANT_1``, ``LEGAL_1``, ``LEGAL_2``, ``LEGAL_3``,
        ``ADMINISTRATIVE_1``, ``ADMINISTRATIVE_2``. Also ``OWNER`` and ``LEAD``
        (these are matter-level functional roles, typically one user each).

        ``action``: ``ADD`` (add alongside others), ``REPLACE`` (replace all
        holders), or use ``remove_from_role`` for removal.
        """
        ids = matter_id if isinstance(matter_id, list) else [matter_id]
        return self._c.internal_call(
            "POST",
            "/v1/matters/{ids}/roles/{role}",
            path_params={"ids": ",".join(ids), "role": role},
            query={"userId": user_id, "action": action},
        )

    def remove_from_role(
        self,
        *,
        matter_id: str,
        role: str,
        user_id: str,
    ) -> dict:
        """Remove a user from a role on a matter."""
        return self._c.internal_call(
            "DELETE",
            "/v1/matters/{id}/roles/{role}",
            path_params={"id": matter_id, "role": role},
            query={"userId": user_id},
        )

    def set_team(self, *, matter_id: str, roles: dict[str, list[str]]) -> dict:
        """Set the full team on a matter in one call.

        ``roles`` is a mapping like ``{"OWNER": ["userId1"], "LEAD": ["userId2"],
        "LEGAL_2": ["userId3", "userId4"]}``. Replaces all existing role assignments.
        """
        return self._c.internal_call(
            "POST",
            "/v1/matters/{id}/roles",
            path_params={"id": matter_id},
            json_body={"meta": {"roles": roles}},
        )


def _extract_tasks_from_response(resp: dict) -> list[dict]:
    """Pull a list of task records out of a milestone-tasks endpoint response.

    The endpoint returns one of two shapes depending on path:
      * ``{data: [<task>, ...]}`` (list form)
      * ``{data: {type, id, attributes: {tasks: [...]}}}`` (JSON:API single-resource form)
    """
    data = resp.get("data") if isinstance(resp, dict) else None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return (data.get("attributes") or {}).get("tasks") or []
    return []


class _Workflows:
    def __init__(self, client: HivelightClient):
        self._c = client

    def list(self, *, type: Optional[str] = None, audience: Optional[list[str]] = None) -> dict:
        """List workflows. ``type`` is ROADMAP or TASK_LIST. ``audience`` filters visibility."""
        filt: dict = {}
        if type:
            filt["type"] = type
        if audience:
            filt["audience"] = audience
        return self._c.internal_call(
            "GET",
            "/v1/workflows",
            query={"filter": json.dumps(filt), "from": 0, "query": ""},
        )

    def get(self, workflow_id: str) -> dict:
        return self._c.internal_call(
            "GET", "/v1/workflows/{id}", path_params={"id": workflow_id}
        )

    def create(
        self, *, name: str, description_html: str = "", type: str = "ROADMAP"
    ) -> dict:
        """Create a workflow (returns a ``:DRAFT``-suffixed id)."""
        body = {
            "jsonapi": {"version": "1.0"},
            "data": {
                "type": "workflow",
                "attributes": {
                    "name": name,
                    "description-as-html": description_html,
                    "type": type,
                },
            },
        }
        return self._c.internal_call("POST", "/v1/workflows", json_body=body)

    def add_milestone(
        self,
        *,
        workflow_draft_id: str,
        name: str,
        description_html: str = "",
        due_days_from_start: int = 0,
        target_minus_days_from_due: int = 0,
    ) -> dict:
        """Add a milestone to a roadmap draft.

        ``due_days_from_start``: due date is N days after ROADMAP_START_DATE.
        ``target_minus_days_from_due``: target date is M days BEFORE the due date.
        """
        body = {
            "name": name,
            "descriptionAsHtml": description_html,
            "dueDate": {"relativeTo": "ROADMAP_START_DATE", "plus": int(due_days_from_start)},
            "targetDate": {
                "relativeTo": "MILESTONE_DUE_DATE",
                "minus": int(target_minus_days_from_due),
            },
        }
        return self._c.internal_call(
            "POST",
            "/v1/workflows/{id}/milestones",
            path_params={"id": workflow_draft_id},
            json_body=body,
        )

    def add_task(
        self,
        *,
        workflow_draft_id: str,
        milestone_id: str,
        name: str,
        description_html: str = "",
        due_minus_days_from_target: int = 0,
        assignee_role: Optional[str] = None,
        reviewer_role: Optional[str] = None,
    ) -> dict:
        """Add a task to a milestone in a draft. For task lists, pass ``milestone_id="TASK_LIST"``.

        ``assignee_role`` and ``reviewer_role`` are functional-role enum values
        (see ``matterFunctionRoles`` in workspace config). Typical values:
        ``OWNER``, ``LEAD``, ``PRINCIPAL``, ``LEGAL_1`` (Senior Lawyer),
        ``LEGAL_2`` (Junior Lawyer), ``LEGAL_3`` (Law Clerk/Paralegal),
        ``ADMINISTRATIVE_1`` (Senior LA), ``ADMINISTRATIVE_2`` (Junior LA).

        The ``add_task`` endpoint accepts only name/description/dueDate/estimates;
        roles are set in a follow-up edit call (we do that automatically here if
        either role is provided).
        """
        if milestone_id == "TASK_LIST":
            due = {"relativeTo": "CURRENT_DATE", "plus": int(due_minus_days_from_target)}
        else:
            due = {
                "relativeTo": "MILESTONE_TARGET_DATE",
                "minus": int(due_minus_days_from_target),
            }
        body = {
            "name": name,
            "descriptionAsHtml": description_html,
            "dueDate": due,
            "estimates": {"unitValue": 0},
        }
        resp = self._c.internal_call(
            "POST",
            "/v1/workflows/{id}/milestones/{mid}/tasks",
            path_params={"id": workflow_draft_id, "mid": milestone_id},
            json_body=body,
        )

        # If roles were specified, fire a follow-up edit to set them.
        if assignee_role or reviewer_role:
            task_id = resp["data"]["attributes"]["task-id"]
            self._set_task_roles(
                workflow_draft_id=workflow_draft_id,
                milestone_id=milestone_id,
                task_id=task_id,
                assignee_role=assignee_role,
                reviewer_role=reviewer_role,
                # Preserve what was just created
                current_attrs=resp["data"]["attributes"],
            )

        return resp

    def _set_task_roles(
        self,
        *,
        workflow_draft_id: str,
        milestone_id: str,
        task_id: str,
        assignee_role: Optional[str],
        reviewer_role: Optional[str],
        current_attrs: dict,
    ) -> dict:
        """Set assignee-role and/or reviewer-role on a template task.

        The edit endpoint requires the full task body. We pass through the current
        attrs from the create response, normalising kebab-case keys to camelCase.
        """
        due = current_attrs.get("due-date") or {}
        body: dict = {
            "name": current_attrs.get("name", ""),
            "descriptionAsHtml": current_attrs.get("description-as-html") or "",
            "dueDate": {
                "relativeTo": due.get("relative-to") or due.get("relativeTo"),
                **({"plus": due["plus"]} if "plus" in due else {}),
                **({"minus": due["minus"]} if "minus" in due else {}),
            },
            "estimates": {
                "unitValue": (current_attrs.get("estimates") or {}).get("unit-value", 0)
            },
        }
        if assignee_role:
            body["assigneeRole"] = assignee_role
        if reviewer_role:
            body["reviewerRole"] = reviewer_role
        return self._c.internal_call(
            "POST",
            "/v1/workflows/{id}/milestones/{mid}/tasks/{tid}",
            path_params={
                "id": workflow_draft_id,
                "mid": milestone_id,
                "tid": task_id,
            },
            json_body=body,
        )

    def link_tasks(
        self,
        *,
        workflow_draft_id: str,
        milestone_id: str,
        from_task_id: str,
        to_task_id: str,
        type: str = "REQUIRES",
        allow_inverted_dates: bool = False,
    ) -> dict:
        """Create a relationship between two tasks in the SAME milestone.

        ``type`` is one of ``REQUIRES`` (linked task is a prerequisite of this one),
        ``REQUIRED_BY`` (this task is a prerequisite of the linked task), or
        ``RELATED_TO`` (neither prerequisite). Hivelight constraint: both tasks
        must be in the same milestone.

        Chronological guardrail: by default this method refuses to create a
        REQUIRES / REQUIRED_BY link where the prerequisite is due AFTER the
        dependent (which would mean the dependent can never be ready to start
        by its own due date). Pass ``allow_inverted_dates=True`` only when you
        intentionally need that arrangement.
        """
        if type in ("REQUIRES", "REQUIRED_BY") and not allow_inverted_dates:
            self._validate_link_chronology(
                workflow_draft_id=workflow_draft_id,
                milestone_id=milestone_id,
                from_task_id=from_task_id,
                to_task_id=to_task_id,
                type=type,
            )
        return self._c.internal_call(
            "POST",
            "/v1/workflows/{id}/milestones/{mid}/tasks/{tid}/links",
            path_params={
                "id": workflow_draft_id,
                "mid": milestone_id,
                "tid": from_task_id,
            },
            json_body={"taskId": to_task_id, "type": type},
        )

    def _validate_link_chronology(
        self,
        *,
        workflow_draft_id: str,
        milestone_id: str,
        from_task_id: str,
        to_task_id: str,
        type: str,
    ) -> None:
        """Raise HivelightValidationError if the link would invert task due dates.

        For REQUIRES (from depends on to): require ``to.due >= from.due`` is
        actually the wrong direction — what we need is ``to`` (the prerequisite)
        due NO LATER than ``from`` (the dependent). In template terms with
        ``due_minus`` (days before milestone target), prerequisite must have
        a HIGHER OR EQUAL ``due_minus``.

        For REQUIRED_BY (from is prerequisite of to): the inverse — ``from``
        must have a HIGHER OR EQUAL ``due_minus`` than ``to``.
        """
        # Fetch both tasks and compare their due_minus offsets.
        try:
            tasks_resp = self._c.internal_call(
                "GET",
                "/v1/workflows/{id}/milestones/{mid}/tasks",
                path_params={"id": workflow_draft_id, "mid": milestone_id},
            )
        except HivelightError:
            # If we can't read the milestone, fall back to letting the server
            # decide rather than blocking the caller.
            return

        tasks = _extract_tasks_from_response(tasks_resp)

        def _due_minus_for(task_id: str) -> Optional[int]:
            for t in tasks:
                attrs = t.get("attributes") or t
                tid = attrs.get("task-id") or attrs.get("taskId") or t.get("id")
                if tid != task_id:
                    continue
                due = attrs.get("due-date") or attrs.get("dueDate") or {}
                if "minus" in due:
                    return int(due["minus"])
                if "plus" in due:
                    return -int(due["plus"])
            return None

        from_due_minus = _due_minus_for(from_task_id)
        to_due_minus = _due_minus_for(to_task_id)
        if from_due_minus is None or to_due_minus is None:
            # Insufficient data to validate; let the server decide.
            return

        # Identify prerequisite vs dependent based on link direction.
        if type == "REQUIRES":
            prereq_minus, dep_minus = to_due_minus, from_due_minus
            prereq_id, dep_id = to_task_id, from_task_id
        else:  # REQUIRED_BY
            prereq_minus, dep_minus = from_due_minus, to_due_minus
            prereq_id, dep_id = from_task_id, to_task_id

        # Inversion: prereq is due LATER than the dependent.
        # In due_minus terms: prereq's minus < dep's minus.
        if prereq_minus < dep_minus:
            raise HivelightValidationError(
                f"Refusing to create {type} link: prerequisite task {prereq_id} "
                f"(due_minus={prereq_minus}) is due AFTER dependent task {dep_id} "
                f"(due_minus={dep_minus}). The dependent could never be ready to "
                f"start by its own due date. Reorder due dates, drop the link, "
                f"or pass allow_inverted_dates=True if this is intentional."
            )

    def move_task(
        self,
        *,
        workflow_draft_id: str,
        milestone_id: str,
        task_id: str,
        before_rank: Optional[str] = None,
        after_rank: Optional[str] = None,
    ) -> dict:
        """Reorder a task within its milestone in a draft workflow.

        Tasks have a Lexorank-style ``rank`` attribute; the editor sorts by that
        string ascending. The move endpoint accepts a reference RANK (not a task
        id) and assigns the moved task a new rank that's lexicographically less
        than or greater than the reference.

        Pass exactly one of:
          * ``before_rank=<rank_str>`` — new rank will be < ``rank_str`` (task displays before)
          * ``after_rank=<rank_str>``  — new rank will be > ``rank_str`` (task displays after)

        For the ergonomic "move A before/after task B" pattern, use
        :meth:`move_task_relative_to` which looks up B's current rank for you.

        Backs the arrow-button reorder UI in the roadmap editor. Must be called
        on a ``:DRAFT`` workflow.
        """
        if (before_rank is None) == (after_rank is None):
            raise HivelightError(
                "move_task requires exactly one of before_rank=<str> or after_rank=<str>"
            )
        body: dict = {}
        if before_rank is not None:
            body["before"] = before_rank
        if after_rank is not None:
            body["after"] = after_rank
        return self._c.internal_call(
            "POST",
            "/v1/workflows/{id}/milestones/{mid}/tasks/{tid}",
            path_params={
                "id": workflow_draft_id,
                "mid": milestone_id,
                "tid": task_id,
            },
            query={"action": "move"},
            json_body=body,
        )

    def _list_milestone_tasks(self, workflow_draft_id: str, milestone_id: str) -> list[dict]:
        """Internal helper — fetch all template tasks for a milestone."""
        resp = self._c.internal_call(
            "GET",
            "/v1/workflows/{id}/milestones/{mid}/tasks",
            path_params={"id": workflow_draft_id, "mid": milestone_id},
        )
        return _extract_tasks_from_response(resp)

    def move_task_relative_to(
        self,
        *,
        workflow_draft_id: str,
        milestone_id: str,
        task_id: str,
        before_task_id: Optional[str] = None,
        after_task_id: Optional[str] = None,
    ) -> dict:
        """Ergonomic wrapper: move ``task_id`` to be before/after another task by id.

        Looks up the reference task's current ``rank`` and calls :meth:`move_task`
        with the appropriate ``before_rank`` / ``after_rank``.
        """
        if (before_task_id is None) == (after_task_id is None):
            raise HivelightError(
                "move_task_relative_to requires exactly one of before_task_id or after_task_id"
            )
        ref_id = before_task_id or after_task_id
        tasks = self._list_milestone_tasks(workflow_draft_id, milestone_id)
        ref_rank = None
        for t in tasks:
            attrs = t.get("attributes") or t
            tid = attrs.get("task-id") or attrs.get("taskId") or t.get("id")
            if tid == ref_id:
                ref_rank = attrs.get("rank")
                break
        if ref_rank is None:
            raise HivelightError(f"Reference task {ref_id} not found in milestone {milestone_id}")
        kwargs: dict = {}
        if before_task_id is not None:
            kwargs["before_rank"] = ref_rank
        else:
            kwargs["after_rank"] = ref_rank
        return self.move_task(
            workflow_draft_id=workflow_draft_id,
            milestone_id=milestone_id,
            task_id=task_id,
            **kwargs,
        )

    def reorder_tasks_chronologically(
        self,
        *,
        workflow_draft_id: str,
        milestone_id: str,
    ) -> list[dict]:
        """Reorder all tasks in a milestone so the editor displays them in execution order.

        Ordering rule: prerequisites first, then non-prerequisites by due date.
        Concretely, we do a topological sort over the REQUIRES graph (so a task's
        prerequisites always come before it) with ``due_minus`` DESC as the
        tiebreaker (highest minus = earliest in the milestone).

        Returns the desired execution-order task list (each entry is the original
        task record).
        """
        import heapq

        tasks = self._list_milestone_tasks(workflow_draft_id, milestone_id)

        def _attrs(t):
            return t.get("attributes") or t

        def _due_minus_of(t: dict) -> int:
            due = _attrs(t).get("due-date") or _attrs(t).get("dueDate") or {}
            if "minus" in due:
                return int(due["minus"])
            if "plus" in due:
                return -int(due["plus"])
            return 0

        def _id_of(t: dict) -> str:
            a = _attrs(t)
            return a.get("task-id") or a.get("taskId") or t.get("id")

        # Build the REQUIRES graph: prereq_of[X] = set of tasks Y such that Y REQUIRES X
        # (i.e. X must come before Y). And indegree[Y] counts how many prereqs Y has.
        ids = [_id_of(t) for t in tasks]
        task_by_id = {tid: t for tid, t in zip(ids, tasks)}
        prereq_of: dict[str, set[str]] = {tid: set() for tid in ids}
        indegree: dict[str, int] = {tid: 0 for tid in ids}

        for t in tasks:
            a = _attrs(t)
            t_id = _id_of(t)
            for rel in (a.get("relationships") or []):
                rel_type = rel.get("type")
                other_id = rel.get("task-id") or rel.get("taskId")
                if not other_id or other_id not in task_by_id:
                    continue
                if rel_type == "REQUIRES":
                    # t requires other. other must come first.
                    if t_id not in prereq_of[other_id]:
                        prereq_of[other_id].add(t_id)
                        indegree[t_id] += 1
                elif rel_type == "REQUIRED_BY":
                    # t is required by other. t must come first.
                    if other_id not in prereq_of[t_id]:
                        prereq_of[t_id].add(other_id)
                        indegree[other_id] += 1

        # Kahn's algorithm with a priority queue keyed by (-due_minus, task_id).
        # -due_minus so highest due_minus (earliest) is popped first.
        # task_id as a stable secondary so the iteration is deterministic.
        ready: list[tuple[int, str]] = []
        for tid in ids:
            if indegree[tid] == 0:
                heapq.heappush(ready, (-_due_minus_of(task_by_id[tid]), tid))

        ordered: list[dict] = []
        while ready:
            _, tid = heapq.heappop(ready)
            ordered.append(task_by_id[tid])
            for dependent in prereq_of[tid]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    heapq.heappush(
                        ready,
                        (-_due_minus_of(task_by_id[dependent]), dependent),
                    )

        # Cycle-safety: if topo sort didn't cover every task (shouldn't happen
        # since Hivelight prevents same-milestone cycles), append the rest in
        # plain due_minus DESC order.
        if len(ordered) < len(tasks):
            seen = {_id_of(t) for t in ordered}
            leftovers = [t for t in tasks if _id_of(t) not in seen]
            leftovers.sort(key=lambda t: -_due_minus_of(t))
            ordered.extend(leftovers)

        # Walk forward. For each task at position i >= 1, move it to be AFTER the
        # task at position i-1. After each move, re-read ranks so we use the moved
        # task's NEW rank in the next iteration.
        rank_by_id: dict[str, str] = {_id_of(t): _attrs(t).get("rank") for t in tasks}

        for i in range(1, len(ordered)):
            prev_id = _id_of(ordered[i - 1])
            curr_id = _id_of(ordered[i])
            prev_rank = rank_by_id.get(prev_id)
            if not prev_rank:
                continue  # missing rank info; skip rather than corrupt order
            self.move_task(
                workflow_draft_id=workflow_draft_id,
                milestone_id=milestone_id,
                task_id=curr_id,
                after_rank=prev_rank,
            )
            # Refresh ranks (curr_id's rank just changed)
            refreshed = self._list_milestone_tasks(workflow_draft_id, milestone_id)
            rank_by_id = {_id_of(t): _attrs(t).get("rank") for t in refreshed}

        return ordered

    def unlink_tasks(
        self,
        *,
        workflow_draft_id: str,
        milestone_id: str,
        from_task_id: str,
        link_id: str,
    ) -> dict:
        return self._c.internal_call(
            "DELETE",
            "/v1/workflows/{id}/milestones/{mid}/tasks/{tid}/links/{lid}",
            path_params={
                "id": workflow_draft_id,
                "mid": milestone_id,
                "tid": from_task_id,
                "lid": link_id,
            },
        )

    def edit_milestone(
        self,
        *,
        workflow_draft_id: str,
        milestone_id: str,
        name: Optional[str] = None,
        description_html: Optional[str] = None,
        due_days_from_start: Optional[int] = None,
        target_minus_days_from_due: Optional[int] = None,
    ) -> dict:
        """Edit an existing milestone in a draft. Pass only the fields you want to change.

        NOTE: must be called on a ``:DRAFT`` workflow id, not a published one. To edit a
        published workflow, first create a draft via ``create_draft(workflow_id)``.
        """
        body: dict = {}
        if name is not None:
            body["name"] = name
        if description_html is not None:
            body["descriptionAsHtml"] = description_html
        if due_days_from_start is not None:
            body["dueDate"] = {"relativeTo": "ROADMAP_START_DATE", "plus": int(due_days_from_start)}
        if target_minus_days_from_due is not None:
            body["targetDate"] = {
                "relativeTo": "MILESTONE_DUE_DATE",
                "minus": int(target_minus_days_from_due),
            }
        return self._c.internal_call(
            "POST",
            "/v1/workflows/{id}/milestones/{mid}",
            path_params={"id": workflow_draft_id, "mid": milestone_id},
            json_body=body,
        )

    def edit_task(
        self,
        *,
        workflow_draft_id: str,
        milestone_id: str,
        task_id: str,
        name: Optional[str] = None,
        description_html: Optional[str] = None,
        due_minus_days_from_target: Optional[int] = None,
    ) -> dict:
        """Edit a task in a roadmap draft.

        The server requires a FULL task body — partial updates trigger a DynamoDB
        "REMOVE section can only be used once" error. We fetch the task's current
        state, merge in the requested changes, and POST the result.
        """
        # Fetch current state by listing the milestone's tasks
        tasks_resp = self._c.internal_call(
            "GET",
            "/v1/workflows/{id}/milestones/{mid}/tasks",
            path_params={"id": workflow_draft_id, "mid": milestone_id},
        )
        current = None
        for t in tasks_resp.get("data", []) or []:
            attrs = t.get("attributes", {})
            if attrs.get("task-id") == task_id:
                current = attrs
                break
        if current is None:
            raise HivelightNotFound(
                f"Task {task_id} not found in workflow {workflow_draft_id} milestone {milestone_id}"
            )

        # Server returns kebab-case keys; the POST endpoint expects camelCase
        body: dict = {
            "name": current.get("name", ""),
            "descriptionAsHtml": current.get("description-as-html") or "",
            "dueDate": current.get("due-date"),
            "estimates": current.get("estimates")
            or {"unitValue": 0},
        }
        # Normalise dueDate keys from kebab-case (server) to camelCase (request)
        if isinstance(body["dueDate"], dict):
            body["dueDate"] = {
                "relativeTo": body["dueDate"].get("relative-to")
                or body["dueDate"].get("relativeTo"),
                **({"plus": body["dueDate"]["plus"]} if "plus" in body["dueDate"] else {}),
                **(
                    {"minus": body["dueDate"]["minus"]} if "minus" in body["dueDate"] else {}
                ),
            }
        # Normalise estimates
        if isinstance(body["estimates"], dict) and "unit-value" in body["estimates"]:
            body["estimates"] = {"unitValue": body["estimates"]["unit-value"]}

        # Apply user-supplied overrides
        if name is not None:
            body["name"] = name
        if description_html is not None:
            body["descriptionAsHtml"] = description_html
        if due_minus_days_from_target is not None:
            relative_to = "CURRENT_DATE" if milestone_id == "TASK_LIST" else "MILESTONE_TARGET_DATE"
            if relative_to == "CURRENT_DATE":
                body["dueDate"] = {"relativeTo": "CURRENT_DATE", "plus": int(due_minus_days_from_target)}
            else:
                body["dueDate"] = {"relativeTo": "MILESTONE_TARGET_DATE", "minus": int(due_minus_days_from_target)}

        return self._c.internal_call(
            "POST",
            "/v1/workflows/{id}/milestones/{mid}/tasks/{tid}",
            path_params={
                "id": workflow_draft_id,
                "mid": milestone_id,
                "tid": task_id,
            },
            json_body=body,
        )

    def delete_milestone(self, *, workflow_draft_id: str, milestone_id: str) -> dict:
        return self._c.internal_call(
            "DELETE",
            "/v1/workflows/{id}/milestones/{mid}",
            path_params={"id": workflow_draft_id, "mid": milestone_id},
        )

    def delete_task(self, *, workflow_draft_id: str, milestone_id: str, task_id: str) -> dict:
        return self._c.internal_call(
            "DELETE",
            "/v1/workflows/{id}/milestones/{mid}/tasks/{tid}",
            path_params={
                "id": workflow_draft_id,
                "mid": milestone_id,
                "tid": task_id,
            },
        )

    def create_draft(self, workflow_id: str) -> dict:
        """Create a draft on a published workflow (for editing). Returns the draft.

        Use this before calling edit_milestone / edit_task / add_milestone / add_task on
        a published workflow. The new draft id will be ``"<workflow_id>:DRAFT"``.
        """
        return self._c.internal_call(
            "POST",
            "/v1/workflows/{id}/draft",
            path_params={"id": workflow_id},
        )

    def publish(self, workflow_draft_id: str, *, audience: str = "WORKSPACE") -> dict:
        """Publish a draft. ``audience`` is WORKSPACE | ORGANIZATION | PUBLIC.

        Also used to UNPUBLISH by passing audience=``"NONE"``.
        """
        return self._c.internal_call(
            "POST",
            "/v1/workflows/{id}/publish",
            path_params={"id": workflow_draft_id},
            json_body={"audience": audience},
        )

    def unpublish(self, workflow_id: str) -> dict:
        """Set audience to NONE (a precondition for deletion)."""
        return self.publish(workflow_id, audience="NONE")

    def delete(self, workflow_id: str) -> dict:
        """Delete a workflow. Must be unpublished first if currently published."""
        return self._c.internal_call(
            "DELETE", "/v1/workflows/{id}", path_params={"id": workflow_id}
        )

    def discard_draft(self, workflow_draft_id: str) -> dict:
        """Discard an unpublished draft (e.g. ``"abc:DRAFT"``)."""
        return self._c.internal_call(
            "DELETE",
            "/v1/workflows/{id}/draft",
            path_params={"id": workflow_draft_id},
        )

    def apply(
        self,
        *,
        workflow_id: str,
        matter_id: str,
        start_date: Union[int, float, dt.datetime, dt.date, None] = None,
        milestone_id: str = "",
    ) -> dict:
        """Apply a workflow to a matter. Internal API only.

        ``start_date`` defaults to now. ``milestone_id`` for task-list workflows
        only — leave empty for roadmaps.
        """
        if start_date is None:
            start_date = int(time.time() * 1000)
        return self._c.internal_call(
            "POST",
            "/v1/workflows/{id}/apply",
            path_params={"id": workflow_id},
            query={
                "startDate": _to_unix_ms(start_date),
                "matterId": matter_id,
                "milestoneId": milestone_id,
            },
        )


class _Milestones:
    def __init__(self, client: HivelightClient):
        self._c = client

    def list(self, matter_id: str) -> dict:
        return self._c.internal_call(
            "GET", "/v1/milestones", query={"matterId": matter_id}
        )

    def set_dates(
        self,
        *,
        milestone_id: str,
        matter_id: str,
        due_date: Union[int, dt.datetime, dt.date],
        target_date: Union[int, dt.datetime, dt.date],
        is_key_date: bool = False,
    ) -> dict:
        """Set absolute due/target dates on a single milestone (no cascade)."""
        body = {
            "data": {
                "type": "milestone",
                "id": milestone_id,
                "attributes": {
                    "id": milestone_id,
                    "dueDate": _to_unix_ms(due_date),
                    "targetDate": _to_unix_ms(target_date),
                    "isKeyDate": is_key_date,
                },
                "relationships": {
                    "matter": {"data": {"type": "matter", "id": matter_id}}
                },
            }
        }
        return self._c.internal_call(
            "POST",
            "/v1/milestones/{id}/date",
            path_params={"id": milestone_id},
            json_body=body,
        )

    def shift(
        self,
        *,
        milestone_id: str,
        matter_id: str,
        new_due_date: Union[int, dt.datetime, dt.date],
        new_target_date: Union[int, dt.datetime, dt.date],
        offset_days: Optional[float] = None,
        offset_ms: Optional[int] = None,
        include_following: bool = True,
        shift_tasks: bool = True,
        is_key_date: bool = False,
    ) -> dict:
        """Shift this milestone (using new absolute dates in the body) and optionally
        cascade the offset to subsequent milestones and/or their tasks.

        **Important — corrected 2026-05-19**: the server expects the ``offset`` query
        param in *milliseconds*, not days. The prior "verified empirically" note in
        api-inventory was wrong (the empirical test used such small values that the
        difference between days and ms was invisible). Captured from a live UI edit:
        an actual UI shift sends ``offset=<delta_ms>``, e.g. ``offset=206641521`` for
        a ~2.39-day shift.

        Pass ``offset_days`` (auto-converted to ms) or ``offset_ms`` directly. They
        are mutually exclusive.
        """
        if offset_days is not None and offset_ms is not None:
            raise ValueError("Pass offset_days OR offset_ms, not both.")
        if offset_days is None and offset_ms is None:
            raise ValueError("One of offset_days or offset_ms is required.")
        if offset_ms is None:
            offset_ms = int(round(offset_days * 86_400_000))
        body = {
            "data": {
                "type": "milestone",
                "id": milestone_id,
                "attributes": {
                    "id": milestone_id,
                    "dueDate": _to_unix_ms(new_due_date),
                    "targetDate": _to_unix_ms(new_target_date),
                    "isKeyDate": is_key_date,
                },
                "relationships": {
                    "matter": {"data": {"type": "matter", "id": matter_id}}
                },
            }
        }
        query = {"offset": offset_ms}
        if include_following:
            query["include"] = "following"
        if shift_tasks:
            query["shiftTasks"] = "true"
        return self._c.internal_call(
            "POST",
            "/v1/milestones/{id}/date",
            path_params={"id": milestone_id},
            query=query,
            json_body=body,
        )

    def delete(self, milestone_id: str, *, include_following: bool = False) -> dict:
        """Delete a milestone. ``include_following=True`` also deletes subsequent milestones."""
        query = {"include": "following"} if include_following else None
        return self._c.internal_call(
            "DELETE",
            "/v1/milestones/{id}",
            path_params={"id": milestone_id},
            query=query,
        )

    def complete(self, milestone_id: str, *, mark_previous_as_completed: bool = False) -> dict:
        query = {"include": "previous"} if mark_previous_as_completed else None
        return self._c.internal_call(
            "POST",
            "/v1/milestones/{id}/complete",
            path_params={"id": milestone_id},
            query=query,
        )


class _Tasks:
    def __init__(self, client: HivelightClient):
        self._c = client

    def list(
        self,
        *,
        matter_id: Optional[str] = None,
        milestone_id: Optional[str] = None,
        assignees: Optional[list[str]] = None,
        reviewers: Optional[list[str]] = None,
        status: Optional[list[str]] = None,
        priority_only: bool = False,
        size: int = 100,
        tz: str = "Australia/Sydney",
    ) -> dict:
        return self._c.internal_call(
            "GET",
            "/v1/tasks",
            query={
                "matterId": matter_id or "",
                "milestoneId": milestone_id or "",
                "assignees": ",".join(assignees) if assignees else "",
                "reviewers": ",".join(reviewers) if reviewers else "",
                "status": ",".join(status) if status else "",
                "priorityOnly": "true" if priority_only else "",
                "readyOnly": "",
                "size": size,
                "sort": "",
                "tags": "",
                "tz": tz,
                "dateFrom": "",
                "dateInterval": "",
                "dateTo": "",
                "from": "",
                "workspaceId": "",
            },
        )

    def get(self, task_id: str) -> dict:
        return self._c.internal_call(
            "GET", "/v1/tasks/{id}", path_params={"id": task_id}
        )

    def create(
        self,
        *,
        name: str,
        matter_id: str,
        milestone_id: str,
        due_date: Union[int, dt.datetime, dt.date, None] = None,
        description_html: str = "",
        assignees: Optional[list[str]] = None,
        reviewers: Optional[list[str]] = None,
        is_priority: bool = False,
    ) -> dict:
        """Create an ad-hoc task in a matter. Internal API only."""
        if due_date is None:
            # Default to milestone target date — let the server figure it out
            due_ms = None
        else:
            due_ms = _to_unix_ms(due_date)
        body: dict = {
            "jsonapi": {"version": "1.0"},
            "data": {
                "type": "task",
                "attributes": {
                    "name": name,
                    "description-as-html": description_html,
                    "matter-id": matter_id,
                    "milestone-id": milestone_id,
                    "assignees": assignees or [],
                    "reviewers": reviewers or [],
                    "is-priority": is_priority,
                },
            },
        }
        if due_ms is not None:
            body["data"]["attributes"]["due-date"] = due_ms
        return self._c.internal_call("POST", "/v1/tasks", json_body=body)

    def update(self, task_id: str, *, attributes: dict) -> dict:
        """Update a task. The internal API requires the FULL task body — fetch it
        first via ``get(task_id)``, merge in changes, then call this.
        """
        # Fetch current state
        current = self.get(task_id)
        task_obj = current.get("data", {})
        merged_attrs = {**task_obj.get("attributes", {}), **attributes}
        body = {
            "jsonapi": {"version": "1.0"},
            "data": {
                "type": "task",
                "id": task_id,
                "attributes": merged_attrs,
            },
        }
        return self._c.internal_call(
            "POST", "/v1/tasks/{id}", path_params={"id": task_id}, json_body=body
        )

    def set_status(self, task_id: str, *, status: str) -> dict:
        """Status values: TODO | INPROGRESS | INREVIEW | DONE."""
        return self._c.internal_call(
            "POST",
            "/v1/tasks/{id}/status",
            path_params={"id": task_id},
            json_body={"data": {"type": "task", "id": task_id, "attributes": {"status": status}}},
        )

    def set_priority(self, task_id: str, *, is_priority: bool) -> dict:
        method = "POST" if is_priority else "DELETE"
        return self._c.internal_call(
            method,
            "/v1/tasks/{id}/priority",
            path_params={"id": task_id},
        )

    def delete(self, task_ids: Union[str, list[str]]) -> dict:
        """Delete one or many tasks. Pass a list for bulk."""
        ids = [task_ids] if isinstance(task_ids, str) else task_ids
        return self._c.internal_call(
            "DELETE", "/v1/tasks/{ids}", path_params={"ids": ",".join(ids)}
        )


class _ApiKeys:
    def __init__(self, client: HivelightClient):
        self._c = client

    def list(self) -> dict:
        return self._c.internal_call("GET", "/v1/api/keys")

    def create(self, *, label: str, user_id: str) -> dict:
        """Create a new API key. The full key is in ``data.attributes.value`` —
        shown ONLY in this one response. Store it immediately.
        """
        return self._c.internal_call(
            "POST",
            "/v1/api/keys",
            json_body={"meta": {"label": label, "userId": user_id}},
        )

    def suspend(self, key_id: str) -> dict:
        return self._c.internal_call(
            "POST", "/v1/api/keys/{id}/suspend", path_params={"id": key_id}
        )

    def unsuspend(self, key_id: str) -> dict:
        return self._c.internal_call(
            "DELETE", "/v1/api/keys/{id}/suspend", path_params={"id": key_id}
        )

    def delete(self, key_id: str) -> dict:
        return self._c.internal_call(
            "DELETE", "/v1/api/keys/{id}", path_params={"id": key_id}
        )


class _Imports:
    """Practice-management import sessions.

    Each Hivelight workspace with a connected PMS (Clio, Actionstep, or
    Smokeball) has one import-session object. The session tracks every
    item available to import from that PMS — matters, contacts, tasks, users —
    and their status (NORMALIZED -> COMPLETE / IGNORED).

    Importing through this API preserves the link to the PMS record, so name,
    contacts, and tasks continue to sync. Creating a matter via
    ``c.matters.create()`` does NOT establish that link — use these methods
    instead when the source is a connected PMS.
    """

    def __init__(self, client: "HivelightClient"):
        self._c = client

    def list_integrations(self) -> list[dict]:
        """List the practice-management integrations configured on the active workspace.

        Each entry has ``source`` (e.g. ``"clio"``, ``"actionstep"``), ``enabled``,
        ``status``, and ``importId`` — the import session id used by the other
        methods on this resource.

        There is no ``GET /v1/imports`` listing endpoint; integrations are exposed
        via the workspace object instead.
        """
        ws_id = self._c.workspace_id
        if not ws_id:
            raise HivelightError("Set a workspace first: c.use_workspace(<id>)")
        resp = self._c.internal_call(
            "GET", "/v1/workspaces/{id}", path_params={"id": ws_id}
        )
        return resp.get("data", {}).get("attributes", {}).get("integrations", []) or []

    def get_session(self, session_id: str) -> dict:
        """Get a single import session. Useful attributes: ``source`` (the PMS name),
        ``progress`` (per-type counters), ``status``, ``options``.
        """
        return self._c.internal_call(
            "GET", "/v1/imports/{id}", path_params={"id": session_id}
        )

    def default_session_id(self, *, source: Optional[str] = None) -> str:
        """Find the import-session id for the active workspace.

        If exactly one PMS is connected, returns its ``importId``.
        If multiple are connected, pass ``source`` (e.g. ``"clio"``) to disambiguate.

        Raises ``HivelightError`` if no enabled integration is found.
        """
        integrations = [i for i in self.list_integrations() if i.get("enabled")]
        if source:
            integrations = [i for i in integrations if i.get("source") == source]
        if not integrations:
            raise HivelightError(
                "No enabled PMS integration found on this workspace. Connect one in "
                "Hivelight Settings > Integrations first."
            )
        if len(integrations) > 1:
            sources = [i.get("source") for i in integrations]
            raise HivelightError(
                f"Multiple enabled integrations ({sources}); pass source=<name> to "
                f"disambiguate."
            )
        return integrations[0]["importId"]

    def list_items(
        self,
        session_id: str,
        *,
        item_type: str = "matter",
        query: str = "",
        include_complete: bool = False,
        include_ignored: bool = False,
        next_cursor: str = "",
    ) -> dict:
        """List items in an import session.

        ``item_type`` is one of: ``matter``, ``contact``, ``task``, ``user``.

        Filtering:
        - ``query`` — free-text search against the item's ``searchable`` field
          (name + description + number + external id + jurisdiction).
        - ``include_complete`` — include already-imported items (default False).
        - ``include_ignored`` — include items the user has skipped (default False).

        Pagination via ``next_cursor`` (read from the previous response's pagination
        envelope). For client-side filtering by attributes that aren't indexed —
        e.g. ``raw.practice_area`` or ``raw.status`` — list everything then filter
        in Python.
        """
        filters = json.dumps({
            "complete": include_complete,
            "ignored": include_ignored,
            "query": query,
        })
        return self._c.internal_call(
            "GET",
            "/v1/imports/{id}/items",
            path_params={"id": session_id},
            query={"type": item_type, "next": next_cursor, "filters": filters},
        )

    def set_item_meta(
        self,
        session_id: str,
        item_id: Union[str, int],
        *,
        team_id: Optional[str] = None,
        item_type: str = "matter",
    ) -> dict:
        """Set per-item import options before triggering the import. The
        common use is overriding the default ``team_id`` for this matter.

        Returns the updated item meta envelope. NOTE: there is no GET counterpart
        for arbitrary items — to read current item state (incl. ``destinationId``,
        default team, raw PMS data), use ``list_items`` and find the entry whose
        ``meta.id`` matches your ``item_id``.
        """
        meta: dict = {}
        if team_id is not None:
            meta["teamId"] = team_id
        return self._c.internal_call(
            "POST",
            "/v1/imports/{id}/meta",
            path_params={"id": session_id},
            query={"type": item_type, "itemIds": str(item_id)},
            json_body={"meta": meta},
        )

    def import_item(
        self,
        session_id: str,
        item_id: Union[str, int],
        *,
        team_id: Optional[str] = None,
        item_type: str = "matter",
    ) -> dict:
        """Import a single item from the connected PMS into Hivelight.

        If ``team_id`` is provided, it is set via ``set_item_meta`` before the
        import is triggered (mirrors the UI's "choose a team" step).

        The import is async server-side — this returns the import-session object
        (with global progress counters), NOT the new Hivelight resource. To find
        the destination id, call ``get_item_meta(session_id, item_id)`` after
        this and read ``data.items[0].destinationId``.

        Roadmap application during import is not yet supported via this method —
        apply roadmaps as a follow-up step via ``c.workflows.apply(workflow_id, matter_id)``.
        """
        if team_id is not None:
            self.set_item_meta(
                session_id=session_id,
                item_id=item_id,
                team_id=team_id,
                item_type=item_type,
            )
        return self._c.internal_call(
            "POST",
            "/v1/imports/{id}/import",
            path_params={"id": session_id},
            query={"type": item_type, "itemIds": str(item_id)},
        )

    def destination_id(
        self,
        session_id: str,
        item_id: Union[str, int],
        *,
        item_type: str = "matter",
    ) -> Optional[str]:
        """Convenience: look up the Hivelight resource id (e.g. matter id) that
        an imported PMS item maps to. Searches both completed and pending items.
        Returns None if not found.
        """
        # destinationId is exposed on every list_items entry — search across both
        # the still-pending side and the already-imported side.
        for kwargs in (
            {"include_complete": False, "include_ignored": False},
            {"include_complete": True, "include_ignored": True},
        ):
            resp = self.list_items(session_id, item_type=item_type, **kwargs)
            for it in (resp.get("meta", {}).get("items") or []):
                if str((it.get("meta") or {}).get("id")) == str(item_id):
                    return it.get("destinationId")
        return None
