# Hivelight Plugin for Claude Code

Operate your [Hivelight](https://hivelight.com) workspace by talking to Claude — create matters,
build and apply roadmaps, manage tasks and milestones, shift deadlines, and import matters from a
connected practice-management system.

Hivelight is a product of Hivelight Pty Ltd. This repository is the source of truth for the plugin
and its distributable package.

---

## What's in here

| Path | What it is |
| --- | --- |
| `.claude-plugin/marketplace.json` | Marketplace manifest — makes this repo installable directly by Claude Code |
| `hivelight/` | The plugin itself (skill, docs, Python library) |
| `install.bat` / `install.command` / `install.sh` / `installer.py` | One-time setup for people who receive the zip |
| `INSTALL.md` | Full install instructions and troubleshooting |
| `REVIEW-AND-INSTALL.md` | Review-before-you-install guide for external recipients |
| `README.txt` | Plain-text README that ships inside the zip |
| `dist/` | Packaged zip for external distribution |

---

## Install

### Option A — from this repo (recommended)

```
/plugin marketplace add hivelight/Hivelight-Plugin
/plugin install hivelight@hivelight-plugin
```

Then run the one-time credential setup so the plugin can reach your workspace:

```
python hivelight/skills/hivelight/lib/setup.py
```

### Option B — from the zip (for external recipients)

Send them `dist/hivelight-plugin-0.1.0-external.zip`. They unzip it and double-click the installer
that matches their machine (`install.bat` on Windows, `install.command` on macOS, `bash install.sh`
on Linux). The installer registers a local marketplace, installs the plugin, installs the Python
dependencies, and opens a browser for the one-time login.

Point external recipients at **[REVIEW-AND-INSTALL.md](REVIEW-AND-INSTALL.md)** first — it walks
them through having their own Claude Code audit every file before anything runs.

---

## Requirements

- Claude Code CLI
- Python 3.9+
- Python packages `requests`, `keyring`, `playwright` (the installer handles these)
- A headless Chromium download (~150 MB, one time, used only for the initial login)

## Credentials

You log in once through a real browser on Hivelight's own login page. The plugin never captures,
stores, or logs your password. It stores a Hivelight API key and session token in your operating
system's secure keychain — Windows Credential Manager, macOS Keychain, or Linux libsecret — not in
any plugin file and not in logs.

Session tokens last three days; the plugin detects expiry and prompts you to re-authenticate. A
"Hivelight Refresh" shortcut (`hivelight/refresh.*`) is installed for that.

## Network

The plugin talks only to `app.hivelight.com` and `api.hivelight.com`. No telemetry, no other
outbound calls.

---

## Version

`0.1.0` — see [`hivelight/.claude-plugin/plugin.json`](hivelight/.claude-plugin/plugin.json).
