"""Managed Wine runtime support for the macOS launcher.

The launcher reuses a system Wine installation when it matches the pinned
version. Otherwise it reuses/downloads the launcher's private runtime.
"""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable

from config import app_data_dir


WINE_VERSION = "11.0"
WINE_RELEASE_TAG = "11.0_1"
WINE_ARCHIVE = "wine-stable-11.0_1-osx64.tar.xz"
WINE_URL = (
    "https://github.com/Gcenx/macOS_Wine_builds/releases/download/"
    f"{WINE_RELEASE_TAG}/{WINE_ARCHIVE}"
)
WINE_SHA256 = "b50dc50ec7f41d58b115a6b685d4d1315ba3c797bd3aa0f49213f2703cb82388"

LogFn = Callable[[str, bool], None]
MIB = 1024 * 1024
DOWNLOAD_SPACE_FALLBACK = 1024 * MIB
DOWNLOAD_SPACE_MARGIN = 128 * MIB
EXTRACT_SPACE_MARGIN = 256 * MIB

try:
    import fcntl
except ImportError:  # pragma: no cover - only used by the macOS code path
    fcntl = None


class WineRuntimeError(RuntimeError):
    """An actionable Wine setup or launch failure."""


@dataclass(frozen=True)
class WineSelection:
    binary: Path
    version: str
    source: str


def _log(log_fn: LogFn, message: str, replace: bool = False) -> None:
    log_fn(message, replace)


def _wine_version(binary: Path) -> str | None:
    try:
        result = subprocess.run(
            [str(binary), "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    match = re.search(r"wine-([0-9]+(?:\.[0-9]+){1,2})", result.stdout, re.IGNORECASE)
    return match.group(1) if match else None


def _same_supported_version(version: str | None) -> bool:
    if not version:
        return False
    return version == WINE_VERSION or version.startswith(f"{WINE_VERSION}.")


def _dedupe_existing(paths: Iterable[Path]) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        expanded = path.expanduser()
        if not expanded.is_file() or not os.access(expanded, os.X_OK):
            continue
        try:
            key = str(expanded.resolve())
        except OSError:
            key = str(expanded)
        if key not in seen:
            seen.add(key)
            found.append(expanded)
    return found


def system_wine_candidates() -> list[Path]:
    """Find user-managed Wine binaries, including paths invisible to GUI apps."""
    candidates: list[Path] = []
    override = os.environ.get("PIF_WINE_BINARY")
    if override:
        candidates.append(Path(override))

    on_path = shutil.which("wine")
    if on_path:
        candidates.append(Path(on_path))

    candidates.extend(
        Path(path)
        for path in (
            "/Applications/Wine Stable.app/Contents/Resources/wine/bin/wine",
            "/Applications/Wine Staging.app/Contents/Resources/wine/bin/wine",
            "/Applications/Wine Devel.app/Contents/Resources/wine/bin/wine",
            "/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine",
            "/opt/homebrew/bin/wine",
            "/usr/local/bin/wine",
            "~/Applications/Wine Stable.app/Contents/Resources/wine/bin/wine",
            "~/Applications/Wine Staging.app/Contents/Resources/wine/bin/wine",
            "~/Applications/Wine Devel.app/Contents/Resources/wine/bin/wine",
        )
    )
    return _dedupe_existing(candidates)


def find_system_wine(require_supported: bool = False) -> WineSelection | None:
    selections: list[WineSelection] = []
    for binary in system_wine_candidates():
        version = _wine_version(binary)
        if version:
            selections.append(WineSelection(binary, version, "installed Wine"))

    compatible = next(
        (item for item in selections if _same_supported_version(item.version)), None
    )
    if compatible:
        return compatible
    if require_supported:
        return None
    return selections[0] if selections else None


def _managed_root() -> Path:
    return app_data_dir() / "runtimes" / f"wine-{WINE_VERSION}"


def _bundled_roots() -> list[Path]:
    roots: list[Path] = []
    override = os.environ.get("PIF_BUNDLED_WINE")
    if override:
        roots.append(Path(override))

    if getattr(sys, "frozen", False):
        roots.append(Path(sys._MEIPASS) / "wine")
    else:
        roots.append(Path(__file__).resolve().parent / "vendor" / "wine")
    return roots


def _find_wine_in(root: Path) -> Path | None:
    direct = (
        root / "Wine Stable.app" / "Contents" / "Resources" / "wine" / "bin" / "wine",
        root / "bin" / "wine",
    )
    for path in direct:
        if path.is_file() and os.access(path, os.X_OK):
            return path

    if root.is_dir():
        for path in root.glob("Wine*.app/Contents/Resources/wine/bin/wine"):
            if path.is_file() and os.access(path, os.X_OK):
                return path
    return None


def _selection_from_root(root: Path, source: str) -> WineSelection | None:
    binary = _find_wine_in(root)
    if not binary:
        return None
    version = _wine_version(binary)
    if not _same_supported_version(version):
        return None
    return WineSelection(binary, version or WINE_VERSION, source)


def _require_free_space(path: Path, required: int, operation: str) -> None:
    """Fail early with an actionable message when a large operation will not fit."""
    free = shutil.disk_usage(path).free
    if free < required:
        raise WineRuntimeError(
            f"Not enough free disk space to {operation} Wine {WINE_VERSION}. "
            f"At least {required / MIB:.0f} MB is required, but only "
            f"{free / MIB:.0f} MB is available."
        )


@contextmanager
def _managed_install_lock(parent: Path):
    """Serialize managed-runtime installs from multiple launcher processes."""
    lock_path = parent / ".wine-runtime-install.lock"
    with lock_path.open("a+b") as handle:
        try:
            os.chmod(lock_path, 0o600)
        except OSError:
            pass
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _download_archive(destination: Path, log_fn: LogFn) -> None:
    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    temporary = destination.with_name(f"{destination.name}.part")
    temporary.unlink(missing_ok=True)
    request = urllib.request.Request(
        WINE_URL,
        headers={"User-Agent": "PokemonInfiniteFusion-Launcher/1.0"},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            total = int(response.headers.get("Content-Length", "0"))
            required = (total or DOWNLOAD_SPACE_FALLBACK) + DOWNLOAD_SPACE_MARGIN
            _require_free_space(destination.parent, required, "download")

            downloaded = 0
            last_progress = -1
            with temporary.open("xb") as out:
                os.chmod(temporary, 0o600)
                while True:
                    chunk = response.read(MIB)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    progress = (
                        min(100, downloaded * 100 // total)
                        if total
                        else downloaded // (5 * MIB)
                    )
                    if progress != last_progress:
                        last_progress = progress
                        detail = (
                            f"{progress}%" if total else f"{downloaded / MIB:.0f} MB"
                        )
                        _log(
                            log_fn,
                            f"Downloading Wine {WINE_VERSION}... {detail}",
                            True,
                        )
                out.flush()
                os.fsync(out.fileno())

        if downloaded <= 0:
            raise WineRuntimeError("The Wine download was empty.")
        if total and downloaded != total:
            raise WineRuntimeError(
                f"The Wine download was incomplete: expected {total} bytes, "
                f"received {downloaded}."
            )
        if not temporary.is_file() or not os.access(temporary, os.R_OK):
            raise WineRuntimeError("The downloaded Wine archive is not readable.")

        temporary.replace(destination)
        elapsed = max(time.monotonic() - started, 0.001)
        _log(
            log_fn,
            f"Downloaded {downloaded / MIB:.1f} MB in {elapsed:.1f} seconds.",
        )
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        if isinstance(exc, WineRuntimeError):
            raise
        raise WineRuntimeError(
            f"Could not download the managed Wine runtime: {exc}"
        ) from exc


def _verify_archive(archive: Path) -> None:
    digest = hashlib.sha256()
    with archive.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != WINE_SHA256:
        raise WineRuntimeError(
            "Wine download checksum mismatch. The download was removed; please try again. "
            f"Expected {WINE_SHA256}, got {actual}."
        )


def _resolved_inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except (OSError, ValueError):
        return False


def _validate_archive_member(member: tarfile.TarInfo, destination: Path) -> None:
    """Reject archive entries that could write outside the staging directory."""
    member_path = PurePosixPath(member.name)
    if member_path.is_absolute() or ".." in member_path.parts:
        raise WineRuntimeError(f"Unsafe path in Wine archive: {member.name!r}")

    output_path = destination.joinpath(*member_path.parts)
    if not _resolved_inside(destination, output_path):
        raise WineRuntimeError(f"Unsafe path in Wine archive: {member.name!r}")

    if member.issym() or member.islnk():
        link_path = PurePosixPath(member.linkname)
        if link_path.is_absolute():
            raise WineRuntimeError(
                f"Unsafe link in Wine archive: {member.name!r} -> {member.linkname!r}"
            )
        link_base = output_path.parent if member.issym() else destination
        link_target = link_base.joinpath(*link_path.parts)
        if not _resolved_inside(destination, link_target):
            raise WineRuntimeError(
                f"Unsafe link in Wine archive: {member.name!r} -> {member.linkname!r}"
            )

    if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
        raise WineRuntimeError(
            f"Unsupported special file in Wine archive: {member.name!r}"
        )


def _extract_archive(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, mode=0o700, exist_ok=True)
    try:
        with tarfile.open(archive, "r:xz") as bundle:
            members = bundle.getmembers()
            names: set[str] = set()
            for member in members:
                _validate_archive_member(member, destination)
                normalized_name = str(PurePosixPath(member.name))
                if normalized_name in names:
                    raise WineRuntimeError(
                        f"Duplicate path in Wine archive: {member.name!r}"
                    )
                names.add(normalized_name)

            extracted_size = sum(member.size for member in members if member.isfile())
            _require_free_space(
                destination, extracted_size + EXTRACT_SPACE_MARGIN, "extract"
            )

            directories: list[tuple[Path, tarfile.TarInfo]] = []
            for member in members:
                # Validate again immediately before each write so a previously
                # extracted symlink cannot redirect a later archive member.
                _validate_archive_member(member, destination)
                relative = PurePosixPath(member.name)
                output = destination.joinpath(*relative.parts)

                if member.isdir():
                    output.mkdir(parents=True, exist_ok=True)
                    directories.append((output, member))
                    continue

                output.parent.mkdir(parents=True, exist_ok=True)
                if output.exists() or output.is_symlink():
                    raise WineRuntimeError(
                        f"Archive entry would overwrite another path: {member.name!r}"
                    )

                if member.issym():
                    os.symlink(member.linkname, output)
                    continue

                source = bundle.extractfile(member)
                if source is None:
                    raise WineRuntimeError(
                        f"Could not read file from Wine archive: {member.name!r}"
                    )
                with source, output.open("xb") as target:
                    shutil.copyfileobj(source, target, length=MIB)
                    target.flush()
                    os.fsync(target.fileno())
                os.chmod(output, member.mode & 0o777)
                os.utime(
                    output,
                    (member.mtime, member.mtime),
                    follow_symlinks=False,
                )

            # Apply directory metadata after their contents have been written;
            # read-only directory modes would otherwise block extraction.
            for directory, member in reversed(directories):
                os.chmod(directory, member.mode & 0o777)
                os.utime(
                    directory,
                    (member.mtime, member.mtime),
                    follow_symlinks=False,
                )
    except WineRuntimeError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise WineRuntimeError(
            f"Could not extract the managed Wine runtime: {exc}"
        ) from exc


def install_managed_wine(log_fn: LogFn) -> WineSelection:
    root = _managed_root()
    existing = _selection_from_root(root, "managed Wine")
    if existing:
        return existing

    parent = root.parent
    archive = parent / WINE_ARCHIVE
    staging = parent / f".{root.name}.installing"
    parent.mkdir(parents=True, mode=0o700, exist_ok=True)

    with _managed_install_lock(parent):
        # Another launcher may have completed the install while this process
        # waited for the exclusive lock.
        existing = _selection_from_root(root, "managed Wine")
        if existing:
            return existing

        if staging.exists():
            shutil.rmtree(staging)
        archive.unlink(missing_ok=True)

        _log(
            log_fn,
            f"No compatible Wine installation found; preparing Wine {WINE_VERSION}...",
        )
        try:
            _download_archive(archive, log_fn)
            if (
                not archive.is_file()
                or archive.stat().st_size <= 0
                or not os.access(archive, os.R_OK)
            ):
                raise WineRuntimeError(
                    "The managed Wine archive is missing or unreadable after download."
                )
            _log(log_fn, "Verifying Wine download...")
            _verify_archive(archive)
            _log(log_fn, "Installing the managed Wine runtime...")
            _extract_archive(archive, staging)

            selection = _selection_from_root(staging, "managed Wine")
            if not selection:
                raise WineRuntimeError(
                    "Wine was extracted, but its executable was not found or had the wrong version."
                )

            if root.exists():
                shutil.rmtree(root)
            staging.rename(root)
            installed = _selection_from_root(root, "managed Wine")
            if not installed:
                raise WineRuntimeError(
                    "The managed Wine runtime could not be activated after extraction."
                )
            return installed
        finally:
            archive.unlink(missing_ok=True)
            archive.with_name(f"{archive.name}.part").unlink(missing_ok=True)
            if staging.exists():
                shutil.rmtree(staging)


def select_wine(log_fn: LogFn) -> WineSelection:
    """Reuse compatible installed Wine, otherwise provide the pinned runtime."""
    compatible = find_system_wine(require_supported=True)
    if compatible:
        _log(
            log_fn,
            f"Using compatible installed Wine {compatible.version}; no download needed.",
        )
        return compatible

    for root in _bundled_roots():
        bundled = _selection_from_root(root, "bundled Wine")
        if bundled:
            _log(log_fn, f"Using bundled Wine {bundled.version}.")
            return bundled

    managed = _selection_from_root(_managed_root(), "managed Wine")
    if managed:
        _log(log_fn, f"Using managed Wine {managed.version}.")
        return managed

    return install_managed_wine(log_fn)


def _wine_environment(
    selection: WineSelection, game_key: str
) -> tuple[dict[str, str], Path]:
    prefix = app_data_dir() / "wineprefixes" / game_key
    prefix.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["WINEPREFIX"] = str(prefix)
    env.setdefault("WINEDEBUG", "-all")
    env["PATH"] = str(selection.binary.parent) + os.pathsep + env.get("PATH", "")
    return env, prefix


def _check_macos_host() -> None:
    if sys.platform != "darwin":
        raise WineRuntimeError("The managed Wine launcher is only available on macOS.")
    version = platform.mac_ver()[0]
    if version:
        parts = tuple(int(part) for part in version.split(".")[:2])
        if parts[0] < 10 or (parts[0] == 10 and len(parts) > 1 and parts[1] < 15):
            raise WineRuntimeError("Wine requires macOS Catalina or newer.")


def launch_game(exe_path: Path, game_key: str, log_fn: LogFn) -> WineSelection:
    """Prepare a Wine prefix and start a Windows game without blocking on it."""
    _check_macos_host()
    selection = select_wine(log_fn)
    if not Path("/Library/Frameworks/GStreamer.framework").is_dir():
        _log(
            log_fn,
            "Warning: GStreamer.framework is not installed; Wine multimedia features may be unavailable.",
        )
    env, prefix = _wine_environment(selection, game_key)

    if not (prefix / "system.reg").is_file():
        _log(
            log_fn,
            f"Creating the {game_key.title()} Wine environment (first launch only)...",
        )
        result = subprocess.run(
            [str(selection.binary), "wineboot", "--init"],
            cwd=str(exe_path.parent),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            details = result.stdout.strip().splitlines()
            detail = details[-1] if details else f"exit code {result.returncode}"
            raise WineRuntimeError(
                f"Wine could not create the game environment: {detail}"
            )

    logs = app_data_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / f"{game_key}-wine.log"
    with log_path.open("ab") as game_log:
        subprocess.Popen(
            [str(selection.binary), str(exe_path)],
            cwd=str(exe_path.parent),
            env=env,
            stdout=game_log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    _log(log_fn, f"Game started with {selection.source} {selection.version}.")
    return selection
