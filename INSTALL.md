# Installing the Hivelight Claude Code plugin

This plugin lets Claude operate Hivelight on your behalf — create matters, build and apply workflow roadmaps, shift dates, manage tasks. After a one-time setup, you can ask Claude things like *"Build me a conveyancing roadmap"* or *"Set up a new family-law matter for Jane Smith and apply the intake workflow"*.

This guide walks through installing on a single laptop. Total time: ~10 minutes, of which ~5 minutes is dependency downloads.

## What you need before you start

1. **Claude Code** — installed and signed in. If you don't have it yet, get it from [claude.com/claude-code](https://claude.com/claude-code).
2. **Python 3.10 or later** — check by running `python --version` in a terminal. If it says "not found", install from [python.org](https://www.python.org/downloads/) and re-open your terminal.
3. **A Hivelight login** — your normal email + password for `app.hivelight.com`.
4. **About 200 MB of disk space** for Python dependencies (Playwright + a headless browser).

> **Windows tip:** open "Terminal" or "PowerShell" — not "Command Prompt". The commands below assume PowerShell or a Unix-style shell.

## Easy mode — double-click the installer

After unzipping the package, you'll see:

```
hivelight-plugin/
├── install.bat       <-- Windows: double-click this
├── install.command   <-- macOS:   double-click this
├── install.sh        <-- Linux:   run `bash install.sh`
└── hivelight/        <-- the actual plugin (don't run this directly)
```

Double-click the installer for your operating system. It does **the whole installation in one go**:
1. Checks the Claude Code CLI and Python 3.10+ are installed (if not, tells you how to get them)
2. Registers a local "Hivelight" marketplace with Claude Code, then installs the plugin from it (this is what makes Claude Code actually load the plugin — just copying files isn't enough)
3. Installs the three Python packages it needs
4. Downloads a headless Chromium browser (~150 MB, the slow step — 3-5 min)
5. Opens Hivelight in a browser so you can log in once. After you reach the dashboard, the installer finishes automatically.

When it's done, **restart Claude Code** and you can ask things like *"List my Hivelight matters"*.

**macOS gatekeeper warning:** on the first double-click of `install.command`, macOS may complain that the file is from an "unidentified developer". Right-click the file → **Open** → **Open** in the confirmation dialog. After approving once, future double-clicks work normally.

If anything goes wrong, the installer leaves the window open with a clear error message and the command you can run to retry that step — read it before closing.

---

## Manual mode (if you prefer to know what's happening)

Claude Code only loads plugins it knows about — dropping files into `~/.claude/plugins/` is **not enough**. You need to register the unzipped package as a local "marketplace" and then install the plugin from it. Two commands:

```bash
# From the directory you unzipped this package into:
claude plugin marketplace add "$PWD" --scope user
claude plugin install hivelight@hivelight-plugin --scope user
```

After this, the plugin lives at:

| OS | Install path (managed by Claude Code) |
|---|---|
| Windows | `%USERPROFILE%\.claude\plugins\cache\hivelight-plugin\hivelight\<version>\` |
| macOS / Linux | `~/.claude/plugins/cache/hivelight-plugin/hivelight/<version>/` |

You shouldn't need to touch that directory directly — `claude plugin update`, `claude plugin uninstall`, etc. manage it for you.

## Step 2 — Install Python dependencies

Open a terminal and run:

```bash
pip install requests keyring playwright
python -m playwright install chromium
```

The second command downloads a headless Chrome (~150 MB). It's only used for the first-time login flow — normal day-to-day operation doesn't need it.

If `pip` isn't recognised, try `python -m pip install ...` instead.

## Step 3 — One-time login

This is where you sign into Hivelight once. The script will open a browser, you log in, and it captures the credentials it needs into your operating system's secure keychain (Windows Credential Manager / macOS Keychain / Linux libsecret).

```bash
# Replace <version> with the installed version (e.g. 0.1.0).
cd ~/.claude/plugins/cache/hivelight-plugin/hivelight/<version>/skills/hivelight/lib
python setup.py
```

> Adjust the `cd` path if you put the plugin somewhere else.

You'll see:

```
============================================================
Hivelight Skill -- First-Run Setup
============================================================
>>> A browser window is opening. Please log in to Hivelight there.
>>> Waiting for login to complete... (timeout: 10 minutes)
```

A Chromium window opens at the Hivelight login page. **Log in with your normal Hivelight credentials.** Once you reach the dashboard, control returns to the terminal:

```
[ok] Captured broad JWT.
[ok] Logged in as user ...
[ok] Found N workspace(s).

Available workspaces:
  1. <your firm>
  2. <other workspace>
  ...
Pick a workspace to use as default [1]:
```

Pick the workspace you mostly work in (just press Enter to take the first). The script then:

- Switches to that workspace and grabs a workspace-scoped session token
- Creates a permanent API key labelled "Hivelight Skill (auto-generated)"
- Stores everything in your OS keychain
- Writes a tiny config file to `~/.config/hivelight-skill/config.json`

Final output:

```
[ok] Stored credentials in OS keychain.
[ok] Wrote config to ~/.config/hivelight-skill/config.json
Setup complete. You can close the browser window if it's still open.
The skill is ready to use.
```

You can close the browser. Setup is done.

## Step 4 — Test it works

Restart Claude Code so it picks up the new plugin. Then in a Claude Code session, ask:

> *"List my Hivelight matters."*

Claude should respond with your matters (the most recent first). If it errors with `HivelightAuthMissing` or similar, see [Troubleshooting](#troubleshooting) below.

## Day-to-day use

Once installed, you don't think about the plumbing. Just talk to Claude in natural language:

- *"Build me an intake roadmap for personal injury in NSW"* — Claude drafts a roadmap, shows it for confirmation, publishes it.
- *"Create a new matter for John Smith, family law, and apply the Texas intake roadmap starting next Monday"*
- *"Shift the 'Discovery' milestone on the Acme matter by 2 weeks and cascade to the following milestones"*
- *"Mark the 'Send engagement letter' task on matter X as complete"*

Claude reads `SKILL.md` and the supporting docs and figures out the right API calls.

## Refreshing credentials

**Most of the time, the plugin handles this for you.**

Hivelight session tokens expire after **3 days**. When you make a Claude request after that, the plugin notices the expiry, **silently launches a headless browser**, refreshes the token using your persisted login, and retries the request. You see nothing except a slightly slower response (~5 seconds the first time after expiry). This happens about twice a week and is invisible.

**About once a month** (specifically: every 30 days, when Hivelight's own login cookie expires), the silent refresh can't auto-log-in for you. When that happens, Claude will say something like *"Your Hivelight session has expired."* To fix it:

1. **Double-click "Hivelight Refresh" on your Desktop.**
2. A browser opens. Log in (usually just one click, since Hivelight remembers your email).
3. Close the window and try Claude again.

The installer puts that shortcut on your Desktop for you. If you can't find it, you can also run the refresh manually from the plugin folder (replace `<version>` with what `claude plugin list` shows):

```
Windows:  %USERPROFILE%\.claude\plugins\cache\hivelight-plugin\hivelight\<version>\refresh.bat
macOS:    ~/.claude/plugins/cache/hivelight-plugin/hivelight/<version>/refresh.command
Linux:    bash ~/.claude/plugins/cache/hivelight-plugin/hivelight/<version>/refresh.sh
```

The API key itself never expires — only the short-lived session token.

## Revoking access

If you want to revoke the plugin's access:

1. Open Hivelight in your browser → **Settings → Integrations → API**
2. Find the key labelled **"Hivelight Skill (auto-generated)"**
3. Click **Suspend** (reversible) or **Delete** (permanent)

After revocation, the plugin's calls will fail until you re-run `setup.py` to create a fresh key.

## Troubleshooting

| What you see | What it means / what to do |
|---|---|
| `python: command not found` | Python isn't installed or isn't on PATH. Install from [python.org](https://www.python.org/downloads/), re-open your terminal. |
| `pip: command not found` | Use `python -m pip install ...` instead. |
| `ModuleNotFoundError: No module named 'playwright'` | Skipped step 2. Run `pip install playwright && python -m playwright install chromium`. |
| `HivelightAuthMissing` in Claude output | Step 3 didn't complete. Re-run `python setup.py`. |
| `HivelightAuthExpired` in Claude output | Session token aged out (3 days). Re-run `python setup.py`. |
| Browser opens but reCAPTCHA refuses you | Hivelight's bot-detection occasionally flags the automated browser. Wait 30 seconds and reload the page inside it. If it persists, contact Hivelight support. |
| Multiple workspaces and you picked the wrong one | Re-run setup with `--sandbox-workspace "<exact-or-partial-name>"` to override the default. |
| Plugin doesn't appear in Claude Code | Run `claude plugin list` — `hivelight@hivelight-plugin` should appear and be enabled. If not, re-run the installer; if `claude plugin marketplace list` doesn't show `hivelight-plugin`, the marketplace registration step failed. Restart Claude Code after fixing. |
| "Could not find a default workspace" errors | Edit `~/.config/hivelight-skill/config.json` and check `default_workspace_id`. Or re-run setup to reset it. |

If you hit something not covered here, the engineer-facing reference is at `skills/hivelight/lib/README.md` — share that with whoever's helping you debug.

## Where things live (for the curious)

| Where | What's there |
|---|---|
| `~/.claude/plugins/cache/hivelight-plugin/hivelight/<version>/` | Plugin code and docs (managed by Claude Code) |
| `~/.claude/plugins/installed_plugins.json` | Claude Code's record of which plugins are installed |
| `~/.claude/settings.json` (`enabledPlugins`) | Claude Code's record of which plugins are enabled |
| `~/.config/hivelight-skill/config.json` | Default workspace + user id (not secret) |
| `~/.config/hivelight-skill/playwright-profile/` | Browser session for setup (saves you re-logging) |
| OS keychain (service: `hivelight.skill`) | API key + session tokens (secret) |

Nothing is stored anywhere else.

## What this plugin does NOT do (yet)

- MFA-protected accounts (not implemented)
- SSO/Cognito accounts (only password-auth users for v0.1)
- Webhook handling

If your firm requires any of the above, let us know — they're on the roadmap.
