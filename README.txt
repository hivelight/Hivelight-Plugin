==============================================================
  HIVELIGHT PLUGIN FOR CLAUDE CODE
  Drive your Hivelight workspace by talking to Claude.
==============================================================

WHAT IS THIS?

This plugin lets Claude Code do real work in your Hivelight
workspace on your behalf -- create matters, build and apply
roadmaps, shift deadlines, import matters from your practice
management system, and more. After a 10-minute one-time setup,
you just talk to Claude in natural language. Claude figures out
which Hivelight API calls to make and confirms with you before
anything that changes data.


WANT TO VET IT FIRST?

Don't just trust that this is safe -- your own Claude Code can
read every file and tell you what it does before anything runs.
See REVIEW-AND-INSTALL.md (same folder) for a two-minute review
step you can run before installing.


HOW TO INSTALL (the short version)

You only need to do this once.

1. Unzip the package you received. Inside you'll see three
   files named "install":

       install.bat       <-- Windows: DOUBLE-CLICK THIS
       install.command   <-- macOS:   DOUBLE-CLICK THIS
       install.sh        <-- Linux:   run "bash install.sh"

   Plus a folder called "hivelight" -- DON'T touch that one,
   the installer copies it for you.

2. Double-click the installer that matches your computer.

3. A black/white text window opens. Press Enter to begin.
   The installer will:
       - Check Claude Code CLI + Python are installed
         (helps you get either one if missing)
       - Register a local "Hivelight" marketplace with Claude Code
         and install the plugin from it
       - Install three small Python packages (~30 sec)
       - Download a headless browser (~150 MB, 3-5 min)
       - Open Hivelight in a browser so you log in once

4. After you log in once, the window says "Installation
   complete!" Close it.

5. Restart Claude Code so it picks up the new plugin.

That's it. Full instructions, troubleshooting, and the macOS
"unidentified developer" warning workaround are in INSTALL.md
(in the same folder as this README).


WHAT CAN I ASK CLAUDE TO DO?

Just talk to it. Some real examples:

  Matter management
    "List my Hivelight matters."
    "Create a new matter for Jane Smith in family law."
    "Archive the test matter I created yesterday."

  Roadmaps & workflows
    "Apply the Personal Injury intake roadmap to the Smith
     matter starting next Monday."
    "Build me a new roadmap for conveyancing in NSW."

  Tasks & milestones
    "Add a task to call the client next Tuesday on the Smith
     matter."
    "Shift the Smith matter's roadmap back two weeks because
     the client is delayed."
    "Mark the 'Send engagement letter' task as complete."

  Importing from your PMS (Clio, Actionstep, or Smokeball)
    "Import the open Personal Injury matters from our PMS, use
     the Litigation team, and apply the PI Intake roadmap."
    "Show me the matters waiting to be imported."

  Reporting / housekeeping
    "Find every matter with an overdue milestone in the Smart
     Lawyers workspace."
    "Push every overdue date forward by 2-8 weeks at random,
     keeping the order of milestones intact."

Tip: for anything that changes data, Claude will show you what
it's about to do and wait for you to confirm.


SESSION EXPIRY (you don't have to do anything most of the time)

Hivelight session tokens last 3 days. The plugin notices when
yours expires and refreshes it silently in the background --
you'll just see a slightly slower first response that day.

Once a month, Hivelight's own login cookie expires and the
silent refresh can't auto-log-in for you. When that happens,
Claude will say "Your Hivelight session has expired." To fix:

  >>> DOUBLE-CLICK "Hivelight Refresh" ON YOUR DESKTOP <<<

The installer puts that shortcut on your Desktop. A browser
opens, log in (one click, your email is remembered), close
the window, try Claude again. Takes 30 seconds.


WHAT IF SOMETHING GOES WRONG?

The installer leaves its window open with a clear error message
when something fails. Read it before closing -- it tells you
the exact command to retry the broken step.

Common issues and fixes are in INSTALL.md under "Troubleshooting"
(same folder as this README). The big three:

  - "python: command not found" -- install Python 3.10+ from
    python.org and tick "Add to PATH". Re-run the installer.

  - macOS "unidentified developer" warning on install.command
    -- right-click the file, choose Open, then Open in the
    dialog. (One-time approval.)

  - "Plugin doesn't appear in Claude Code" -- run
    "claude plugin list" in a terminal. You should see
    "hivelight@hivelight-plugin" listed and enabled. If not,
    re-run the installer. After it finishes, fully restart
    Claude Code.


WHAT THIS PLUGIN DOES NOT DO (YET)

  - Hivelight accounts that require SSO (only password-auth
    works today)
  - Hivelight accounts with MFA enabled
  - Webhook event handling
  - Applying a roadmap during PMS import (known Hivelight-side
    bug -- Claude applies the roadmap as a separate step after
    import, which works the same way)

If you need any of the above, let your Hivelight contact know
-- they're on the roadmap.


PRIVACY & SECURITY

The plugin doesn't send your data anywhere except hivelight.com
(and Claude's API as part of normal Claude Code use). Your
Hivelight API key and session token are stored in your operating
system's secure keychain (Windows Credential Manager, macOS
Keychain, or Linux libsecret) -- NOT in any plugin file. To
revoke the plugin's access, go to Hivelight > Settings >
Integrations > API and delete the key labelled "Hivelight
Skill (auto-generated)".


WHERE THINGS LIVE (for the curious)

  ~/.claude/plugins/cache/hivelight-plugin/hivelight/<version>/
      plugin code + docs (managed by Claude Code)
  ~/.config/hivelight-skill/config.json
      default workspace
  ~/.config/hivelight-skill/playwright-profile/
      saved browser session (avoids re-login during refresh)
  OS keychain, service "hivelight.skill"
      secrets

Nothing is stored anywhere else.

==============================================================
