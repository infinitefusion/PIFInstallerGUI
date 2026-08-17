import json
import os
import sys
from pathlib import Path

FOLDER_NAME = "infinitefusion_common"


def app_data_dir() -> Path:
    """Return the per-user data directory used by the launcher."""
    override = os.environ.get("PIF_LAUNCHER_DATA_DIR")
    if override:
        return Path(override).expanduser()

    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / FOLDER_NAME


def _config_path() -> Path:
    return app_data_dir() / "launcher_config.json"


def load_config() -> dict:
    try:
        return json.loads(_config_path().read_text())
    except Exception:
        return {}


def save_config(data: dict):
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_config()
    existing.update(data)
    path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
