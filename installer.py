#!/usr/bin/env python3
"""Hivelight plugin installer (cross-platform).

Run from the unzipped distribution directory. The OS-specific wrappers
(install.bat / install.command / install.sh) just check Python and hand off.

Steps:
  1. Check Claude Code CLI is available
  2. Clean up any pre-marketplace flat install
  3. Register the local marketplace via `claude plugin marketplace add`
  4. Install the plugin via `claude plugin install hivelight@hivelight-plugin`
  5. Discover the install path from ~/.claude/plugins/installed_plugins.json
  6. pip install runtime deps (requests, keyring, playwright)
  7. playwright install chromium
  8. Run setup.py for one-time Hivelight login
  9. Drop a Desktop "Hivelight Refresh" shortcut pointing at the new path
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# claude CLI emits UTF-8 (✔, ❯). On Windows the default console encoding is
# cp1252 and would crash on those bytes. Force stdout/stderr to UTF-8 with
# replacement so the installer never dies from a checkmark character.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

PLUGIN_NAME = "hivelight"
MARKETPLACE_NAME = "hivelight-plugin"
PLUGIN_KEY = f"{PLUGIN_NAME}@{MARKETPLACE_NAME}"
HOME = Path.home()
STATE_FILE = HOME / ".claude" / "plugins" / "installed_plugins.json"
LEGACY_FLAT_INSTALL = HOME / ".claude" / "plugins" / PLUGIN_NAME


def info(msg: str) -> None:
    print(msg)


def step(msg: str) -> None:
    print()
    print(f"=== {msg} ===")


def fail(msg: str, code: int = 1) -> "NoReturn":
    print()
    print(f"[error] {msg}", file=sys.stderr)
    sys.exit(code)


def run(cmd: list[str], *, allow_fail: bool = False, capture: bool = False) -> subprocess.CompletedProcess:
    info(f"  $ {' '.join(cmd)}")
    # Force UTF-8 with replacement on decode errors — claude CLI emits UTF-8
    # symbols (✔, ❯) that cp1252 on Windows can't decode.
    proc = subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if capture and proc.stdout:
        info(proc.stdout.rstrip())
    if proc.returncode != 0 and not allow_fail:
        if capture and proc.stderr:
            print(proc.stderr.rstrip(), file=sys.stderr)
        fail(f"command failed (exit {proc.returncode}): {' '.join(cmd)}", code=proc.returncode)
    return proc


def find_claude_cli() -> str:
    candidate = shutil.which("claude")
    if candidate:
        return candidate
    # Common npm global install location on Windows
    win_npm = HOME / "AppData" / "Roaming" / "npm" / "claude.cmd"
    if win_npm.is_file():
        return str(win_npm)
    fail(
        "the 'claude' CLI was not found on PATH.\n"
        "        Install Claude Code from https://claude.com/claude-code,\n"
        "        re-open your terminal, then re-run this installer."
    )


def remove_legacy_flat_install() -> None:
    if LEGACY_FLAT_INSTALL.is_dir() and (LEGACY_FLAT_INSTALL / "plugin.json").is_file():
        info(f"[upgrade] Removing pre-marketplace install at: {LEGACY_FLAT_INSTALL}")
        shutil.rmtree(LEGACY_FLAT_INSTALL)
        info("[upgrade] Cleaned. Continuing with the marketplace-based install.")


def marketplace_is_registered(claude: str) -> bool:
    proc = run([claude, "plugin", "marketplace", "list"], allow_fail=True, capture=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    return MARKETPLACE_NAME in out


def plugin_is_installed(claude: str) -> bool:
    proc = run([claude, "plugin", "list"], allow_fail=True, capture=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    return PLUGIN_KEY in out or f" {PLUGIN_NAME} " in out


def register_marketplace(claude: str, marketplace_dir: Path) -> None:
    if marketplace_is_registered(claude):
        info(f"[ok] Marketplace '{MARKETPLACE_NAME}' is already registered; refreshing the source path.")
        run([claude, "plugin", "marketplace", "remove", MARKETPLACE_NAME], allow_fail=True, capture=True)
    info(f"Registering marketplace from: {marketplace_dir}")
    run([claude, "plugin", "marketplace", "add", str(marketplace_dir), "--scope", "user"], capture=True)


def install_plugin(claude: str) -> None:
    if plugin_is_installed(claude):
        info(f"[ok] Plugin '{PLUGIN_KEY}' is already installed; reinstalling for a clean state.")
        run([claude, "plugin", "uninstall", PLUGIN_KEY], allow_fail=True, capture=True)
    info(f"Installing plugin '{PLUGIN_KEY}'...")
    run([claude, "plugin", "install", PLUGIN_KEY, "--scope", "user"], capture=True)


def resolve_install_path() -> Path:
    if not STATE_FILE.is_file():
        fail(f"expected state file not found: {STATE_FILE}")
    data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    entries = (data.get("plugins") or {}).get(PLUGIN_KEY) or []
    if not entries:
        fail(f"plugin {PLUGIN_KEY} not recorded in {STATE_FILE} after install")
    path = Path(entries[-1]["installPath"])
    if not path.is_dir():
        fail(f"recorded installPath does not exist on disk: {path}")
    return path


def pip_install_runtime_deps() -> None:
    info("Installing Python packages: requests, keyring, playwright...")
    run([sys.executable, "-m", "pip", "install", "--quiet",
         "--disable-pip-version-check", "requests", "keyring", "playwright"])
    info("[ok] Python packages installed.")


def install_chromium() -> None:
    info("Downloading Chromium for the login flow (~150 MB, can take a few minutes)...")
    run([sys.executable, "-m", "playwright", "install", "chromium"])
    info("[ok] Chromium ready.")


def run_setup(install_path: Path) -> None:
    setup_py = install_path / "skills" / "hivelight" / "lib" / "setup.py"
    if not setup_py.is_file():
        fail(f"setup.py not found at expected location: {setup_py}")
    info("")
    info("============================================================")
    info("  One-time Hivelight login")
    info("============================================================")
    info("A browser window will open at app.hivelight.com.")
    info("Log in with your normal credentials. After you reach the dashboard,")
    info("this installer will finish automatically.")
    info("")
    try:
        input("Press Enter when you're ready... ")
    except EOFError:
        # Non-interactive shells (CI etc.) — proceed without waiting.
        pass
    run([sys.executable, str(setup_py)])


def write_desktop_shortcut(install_path: Path) -> None:
    desktop = HOME / "Desktop"
    if not desktop.is_dir():
        info(f"[note] No Desktop folder found; manual refresh path is {install_path}")
        return
    system = platform.system()
    try:
        if system == "Windows":
            shortcut = desktop / "Hivelight Refresh.bat"
            target = install_path / "refresh.bat"
            shortcut.write_text(
                f"@echo off\r\ncall \"{target}\"\r\n",
                encoding="utf-8",
            )
        elif system == "Darwin":
            shortcut = desktop / "Hivelight Refresh.command"
            target = install_path / "refresh.command"
            shortcut.write_text(
                f"#!/usr/bin/env bash\nexec \"{target}\"\n",
                encoding="utf-8",
            )
            shortcut.chmod(0o755)
        else:
            shortcut = desktop / "Hivelight Refresh.sh"
            target = install_path / "refresh.sh"
            shortcut.write_text(
                f"#!/usr/bin/env bash\nexec \"{target}\"\n",
                encoding="utf-8",
            )
            shortcut.chmod(0o755)
        info(f"[ok] Created Desktop shortcut: {shortcut.name}")
    except OSError as e:
        info(f"[note] Could not create Desktop shortcut: {e}")
        info(f"       Manual refresh: {install_path}/refresh.*")


def main() -> int:
    if len(sys.argv) != 2:
        fail("usage: installer.py <unzipped-distribution-dir>")
    marketplace_dir = Path(sys.argv[1]).resolve()
    if not (marketplace_dir / ".claude-plugin" / "marketplace.json").is_file():
        fail(
            f"expected {marketplace_dir}/.claude-plugin/marketplace.json — was the\n"
            "        distribution fully unzipped? Re-extract the archive and try again."
        )

    step("Checking Claude Code CLI")
    claude = find_claude_cli()
    info(f"[ok] claude CLI: {claude}")

    step("Cleaning up any old install")
    remove_legacy_flat_install()

    step("Registering Hivelight marketplace")
    register_marketplace(claude, marketplace_dir)

    step("Installing Hivelight plugin")
    install_plugin(claude)

    install_path = resolve_install_path()
    info(f"[ok] Plugin installed at: {install_path}")

    step("Installing Python dependencies")
    pip_install_runtime_deps()

    step("Downloading Chromium")
    install_chromium()

    step("First-time Hivelight login")
    run_setup(install_path)

    step("Creating Desktop refresh shortcut")
    write_desktop_shortcut(install_path)

    print()
    print("============================================================")
    print("  Installation complete!")
    print("============================================================")
    print()
    print("Restart Claude Code, then try asking it:")
    print('  "List my Hivelight matters"')
    print()
    print("If you see 'Hivelight session expired' later, double-click")
    print("'Hivelight Refresh' on your Desktop.")
    print()
    print(f"Install location: {install_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
