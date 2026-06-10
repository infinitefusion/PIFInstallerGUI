import ssl
import json
import urllib.request

_cache: dict | None = None

def fetch_remote_config() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    try:
        url = "https://download.infinitefusion.net/launcher_links.json"
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            _cache = json.loads(resp.read().decode())
            return _cache
    except Exception as e:
        print(f"fetch_remote_config failed: {e}")
        _cache = {}
        return {}

def fetch_social_links() -> list[dict]:
    return fetch_remote_config().get("social_links", [])

def fetch_games() -> dict:
    return fetch_remote_config().get("games", {})