import json
import os
from pathlib import Path

FOLDER_NAME = "infinitefusion_common"
def _config_path() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home()))
    return base / FOLDER_NAME / "launcher_config.json"

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
    path.write_text(json.dumps(existing, indent=2))