"""
installer.py — game download logic with portable-git fallback.

Portable Git (Windows-only) is downloaded on demand from the official
GitHub release and extracted into  <script_dir>/vendor/git/  so the
user never has to install anything manually.
"""

import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

# ── Portable Git source ───────────────────────────────────────────────────────
# PortableGit-<version>-64-bit.7z.exe is a self-extracting archive;
# the plain .zip build is easier to unpack without 7-zip.
# MinGit is the minimal subset (no GUI, no bash extras) — perfect for scripting.
MINGIT_URL = (
    "https://github.com/git-for-windows/git/releases/download/"
    "v2.45.2.windows.1/MinGit-2.45.2-64-bit.zip"
)
MINGIT_SHA256 = "7ed2a3ce5bbbf8eea976488de5416894ca3e6a0347cee195a7d768ac146d5290"

# ── Paths ─────────────────────────────────────────────────────────────────────
_SCRIPT_DIR  = Path(os.path.dirname(os.path.abspath(__file__)))
_VENDOR_DIR  = _SCRIPT_DIR / "vendor"
_GIT_DIR     = _VENDOR_DIR / "git"
_GIT_EXE     = _GIT_DIR / "cmd" / "git.exe"   # MinGit layout on Windows
_GIT_INSTALL_URL = "https://git-scm.com/install/"

# ── Game definitions ──────────────────────────────────────────────────────────
GAMES = {
    "kanto": {
        "label":    "Pokémon Infinite Fusion 1",
        "subtitle": "Kanto",
        "repo":     "https://github.com/infinitefusion/infinitefusion-e18.git",
        "branch":   "releases",
        "folder":   "InfiniteFusion",
    },
    "hoenn": {
        "label":    "Pokémon Infinite Fusion 2",
        "subtitle": "Hoenn",
        "repo":     "https://github.com/infinitefusion/infinitefusion-hoenn-public.git",
        "branch":   "releases",
        "folder":   "InfiniteFusion2",
    },
}


# ── Git resolution ────────────────────────────────────────────────────────────

def _system_git() -> str | None:
    """Return the path to a system-installed git, or None."""
    return shutil.which("git")


def _bundled_git() -> str | None:
    """Return the path to the bundled MinGit executable, or None if not extracted."""
    if _GIT_EXE.is_file():
        return str(_GIT_EXE)
    return None


def git_available() -> bool:
    """True if any git (system or bundled) is usable right now."""
    return bool(_system_git() or _bundled_git())


def _resolve_git(log_fn, done_fn) -> str | None:
    """
    Return a usable git path, downloading MinGit first if needed.
    Calls done_fn(False, msg) and returns None on unrecoverable failure.
    Only downloads on Windows; on other platforms we give up if git is missing.
    """
    # 1. Prefer system git (fastest, works on all OSes)
    git = _system_git()
    if git:
        return git

    # 2. Already bundled from a previous run
    git = _bundled_git()
    if git:
        log_fn(f"Using bundled git: {git}")
        return git

    # 3. Download MinGit (Windows only)
    if sys.platform != "win32":
        done_fn(False, "git is not installed. Please install it and try again.")
        return None

    log_fn("git not found — downloading MinGit (one-time setup)…")
    zip_path = _VENDOR_DIR / "mingit.zip"

    try:
        _VENDOR_DIR.mkdir(parents=True, exist_ok=True)

        # Download with progress
        def _reporthook(count, block_size, total_size):
            if total_size > 0:
                pct = min(100, count * block_size * 100 // total_size)
                log_fn(f"  Downloading MinGit… {pct}%",True)

        urllib.request.urlretrieve(MINGIT_URL, zip_path, _reporthook)
        log_fn("  Download complete — verifying…", False)

        # Optional SHA-256 check
        import hashlib
        h = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        if MINGIT_SHA256 and h != MINGIT_SHA256:
            done_fn(False,
                    f"MinGit checksum mismatch — download may be corrupt.\n"
                    f"  expected: {MINGIT_SHA256}\n"
                    f"  got:      {h}")
            zip_path.unlink(missing_ok=True)
            return None

        log_fn("  Checksum OK — extracting…")
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(_GIT_DIR)
        zip_path.unlink(missing_ok=True)

        git = _bundled_git()
        if not git:
            done_fn(False, "MinGit extraction failed — git.exe not found after unzip.")
            return None

        log_fn(f"  MinGit ready: {git}")
        return git

    except Exception as exc:
        done_fn(False, f"Failed to download MinGit: {exc}\nPlease try downloading installing git manually instead.\n{_GIT_INSTALL_URL}")
        zip_path.unlink(missing_ok=True)
        return None


# ── Install logic ─────────────────────────────────────────────────────────────

def run_install(game_key: str, install_dir: str, log_fn, done_fn):
    game   = GAMES[game_key]
    install_path = Path(install_dir)
    if install_path.name == game["folder"]:
        target = install_path
    else:
        target = install_path / game["folder"]
    game_exe_name = "Game.exe"
    if game_key == "hoenn":
        game_exe_name = "InfiniteFusion2.exe"
    # Resolve git, downloading MinGit if necessary
    git_exe = _resolve_git(log_fn, done_fn)
    if git_exe is None:
        return   # done_fn already called by _resolve_git

    # Build a subprocess env that finds our bundled git's DLLs
    env = os.environ.copy()
    if git_exe == str(_GIT_EXE):
        git_bin = str(_GIT_EXE.parent)
        env["PATH"] = git_bin + os.pathsep + env.get("PATH", "")
        env["GIT_EXEC_PATH"] = str(_GIT_DIR / "mingw64" / "libexec" / "git-core")
        env["GIT_CONFIG_NOSYSTEM"] = "1"

    def run(cmd):
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        last_prefix = None
        for line in proc.stdout:
            line = line.rstrip()
            colon_pos = line.find(":")
            prefix = line[:colon_pos].strip() if colon_pos != -1 else None
            replace = (prefix is not None and prefix == last_prefix)
            log_fn(line, replace)
            last_prefix = prefix
        proc.wait()
        return proc.returncode

    try:
        if is_existing_folder(target,game):
            log_fn(f"Found existing repo at {target} — pulling latest…")
            rc = run([git_exe, "-C", str(target), "pull", "--recurse-submodules"])
            was_update = True
        else:
            target.mkdir(parents=True, exist_ok=True)
            log_fn(f"Cloning {game['label']} ({game['subtitle']})…")
            cmd = [git_exe, "clone","--progress", "-v", "--recurse-submodules", "--depth=1"]
            if game["branch"]:
                cmd += ["-b", game["branch"]]
            cmd += [game["repo"], str(target)]
            rc = run(cmd)
            was_update = False
        if rc == 0:
            action = "updated" if was_update else "installed"
            done_fn(True, f"Successfully {action}!\nLaunch the game with {game_exe_name}")
        else:
            action = "updating" if was_update else "installing"
            done_fn(False, f"Could not finish {action}.\nCheck the logs for details.")

    except Exception as exc:
        done_fn(False, f"Error: {exc}")


def verify_game_name(folder_path, game):
    ini_path = folder_path / "Game.ini"
    if not ini_path.is_file():
        return False

    expected_titles = {
        "InfiniteFusion":  "infinitefusion",
        "InfiniteFusion2": "infinitefusion-hoenn",
    }
    expected = expected_titles.get(game["folder"])
    if expected is None:
        return False

    import configparser
    config = configparser.ConfigParser()
    config.read(ini_path, encoding="utf-8")
    return config.get("Game", "Title", fallback="").strip() == expected


def is_existing_folder(folder_path, game):
    return (
        folder_path.exists()
        and (folder_path / ".git").exists()
        and verify_game_name(folder_path, game)
    )