# Review this plugin before you install it

Someone sent you this zip. **You don't have to take their word that it's safe** — your own Claude Code can read every file and tell you exactly what it does *before* anything runs on your machine. This page walks you through that, then through installing.

Nothing here installs or runs anything until you choose to. Reviewing takes a couple of minutes; installing takes ~10 (mostly a one-time download).

---

## Step 1 — Have Claude review the contents first

1. Unzip this package somewhere.
2. Open **Claude Code** in that folder.
3. Paste this prompt:

```
Review every file in this folder. This is a Claude Code plugin someone sent me
and I have NOT installed it yet. Tell me plainly:
  1. What does it actually do?
  2. What does it connect to over the network — list every domain/URL.
  3. Where does it store my credentials, and does it ever store or log my password?
  4. What does the installer run on my machine (commands, downloads, package installs)?
  5. Is there anything obfuscated, unsafe, or that phones home anywhere unexpected?
Don't install or run anything yet — just review the code and report back.
```

Claude will read the code and summarise it. So you know what a *normal* result looks like, here's what an honest review should find:

- **What it does:** lets you operate your Hivelight workspace by talking to Claude — create matters, build and apply roadmaps, shift deadlines, manage tasks, and import matters from Clio, Actionstep, or Smokeball.
- **Network:** it only talks to `app.hivelight.com` and `api.hivelight.com` (plus Claude itself, as part of normal Claude Code use). Nothing else.
- **Your password:** you log in once through a **real browser on Hivelight's own login page**. The plugin never captures, stores, or logs your password.
- **Credentials:** it stores a Hivelight API key and session token in your operating system's **secure keychain** (Windows Credential Manager / macOS Keychain / Linux libsecret) — not in any plugin file, and not in logs.
- **What the installer does (expected — not alarming):** registers the plugin with your Claude Code, installs three Python packages (`requests`, `keyring`, `playwright`), downloads a headless Chromium browser (~150 MB — the slow step, used only for the one-time login), then opens a browser so you can log in. It also puts a "Hivelight Refresh" shortcut on your Desktop for later.
- **No telemetry / no phone-home** beyond Hivelight.

If Claude's review matches the above and you're comfortable, continue to Step 2. **If anything looks different, stop and ask the sender.**

---

## Step 2 — Install it (only once you're satisfied)

The full step-by-step, with troubleshooting, is in **`INSTALL.md`** (same folder).

**Option A — let Claude walk you through it transparently** (each step shown before it runs, instead of a black-box installer). Paste:

```
I've reviewed this plugin and I'm happy to install it. Walk me through installing
it step by step using INSTALL.md — run each command, and show me what it does
before you run it. When it reaches the one-time Hivelight login, hand it to me so
I can log in myself.
```

**Option B — run the installer** for your operating system:

- Windows: double-click `install.bat`
- macOS: double-click `install.command`
- Linux: run `bash install.sh`

Both paths do the same thing. After it finishes, **restart Claude Code** and try asking it: *"List my Hivelight matters."*

---

## What you'll need

- Claude Code, installed and signed in
- Python 3.10 or later
- A Hivelight login (your normal email + password for `app.hivelight.com`)
- ~200 MB free disk space (for the one-time browser download)

You stay in control the whole way — nothing runs until you've seen what it does.
