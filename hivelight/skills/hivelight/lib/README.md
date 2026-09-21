# Hivelight skill — Python module

This is the engineer-facing reference. **End users should follow `INSTALL.md` at the plugin root** — it covers the same flow with less jargon.

## Installation

The skill folder is self-contained but the Python module has three runtime dependencies (plus Playwright for first-run only):

```bash
pip install requests keyring playwright
playwright install chromium
```

Playwright + Chromium together are ~150 MB. After first-run setup, only `requests` and `keyring` are needed for normal operation.

## First-time setup

From this `lib/` directory:

```bash
python setup.py --sandbox-workspace "Your Workspace Name"
```

The command opens a browser. Log in to Hivelight. The script then:
1. Reads `localStorage.token` (broad JWT) from the page after login.
2. Navigates to a workspace dashboard to harvest the workspace-scoped JWT from `sessionStorage`.
3. Calls `POST /v1/api/keys` to create a permanent API key labelled "Hivelight Skill (auto-generated)".
4. Stores the API key, broad JWT, and scoped JWT in your OS keychain.
5. Writes a small config file at `~/.config/hivelight-skill/config.json` (just the default workspace id and your user id — no secrets).

## Using the client from Python

```python
from hivelight import HivelightClient
c = HivelightClient()                    # picks up default workspace from config
# or: HivelightClient(workspace_id="...")  to override

matters = c.matters.list()
print(matters)
```

## Using from Claude Code

Claude can invoke the client via Bash:

```bash
python -c "from hivelight import HivelightClient; c = HivelightClient(); import json; print(json.dumps(c.matters.list(), indent=2))"
```

For multi-step scripts, write a temp file and execute it. Always import from the module path, not relative paths.

## Re-running setup

The JWTs in keychain expire every 3 days. If you see `HivelightAuthExpired`, the exception message includes the absolute path to `setup.py` on this machine. Or just run from this directory:

```bash
python setup.py
```

The API key persists across re-runs — only the JWT is refreshed. Your default workspace and user-id config are also preserved.

## Revoking access

To revoke the API key the skill is using:

1. Open Hivelight → Settings → Integrations → API.
2. Find the key labelled "Hivelight Skill (auto-generated)".
3. Click Suspend or Delete.

After revocation, all skill operations using the public API will fail. The next setup run will create a fresh key.

## Listing what's stored

The script doesn't currently include a "show me what's in keychain" command — use your OS keychain UI:

- **macOS**: Keychain Access → search "hivelight.skill"
- **Windows**: Credential Manager → Windows Credentials → "hivelight.skill"
- **Linux**: `secret-tool search service hivelight.skill` (libsecret) or `gnome-keyring` UI

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `HivelightAuthMissing` | No credentials in keychain. Run `python setup.py` from this directory. |
| `HivelightAuthExpired` | JWT aged out (3 days). Re-run setup. |
| `HivelightAuthError` with 403 | API key was revoked, or you're hitting an endpoint your user lacks permission for. Re-run setup if you don't see the key in Integrations any more. |
| `HivelightValidationError` (422) | Request body shape is wrong. The exception's `.body` attribute carries the server's error message. |
| Browser closes immediately during setup | Another Chrome instance is using the same user-data-dir. Close all Chromes and retry. |
| `keyring` errors on Linux | Install `libsecret-tools` and a keyring daemon, or set the file backend explicitly. |
