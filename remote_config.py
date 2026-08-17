import ssl
import json
import time
import urllib.error
import urllib.request

_cache: dict | None = None
REMOTE_CONFIG_URL = "https://download.infinitefusion.net/launcher_links.json"
REMOTE_CONFIG_ATTEMPTS = 3


def fetch_remote_config() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    req = urllib.request.Request(
        REMOTE_CONFIG_URL,
        headers={"User-Agent": "PokemonInfiniteFusion-Launcher/1.0"},
    )
    for attempt in range(REMOTE_CONFIG_ATTEMPTS):
        try:
            with urllib.request.urlopen(
                req, context=ssl.create_default_context(), timeout=5
            ) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("remote configuration must be a JSON object")
                _cache = payload
                return _cache
        except (OSError, ssl.SSLError, urllib.error.URLError, ValueError) as exc:
            if attempt + 1 < REMOTE_CONFIG_ATTEMPTS:
                time.sleep(0.5 * (2**attempt))
                continue
            print(
                f"fetch_remote_config failed after {REMOTE_CONFIG_ATTEMPTS} "
                f"attempts: {exc}"
            )

    _cache = {}
    return _cache


def fetch_social_links() -> list[dict]:
    return fetch_remote_config().get("social_links", [])


def fetch_games() -> dict:
    return fetch_remote_config().get("games", {})
