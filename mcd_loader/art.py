"""Game artwork for the launcher, downloaded from Steam's public store CDN and cached locally."""
import json
import logging
import os
import time
import urllib.request

STEAM_APPS = {"mcd": 1672970, "rv": 3949040}
APPDETAILS = "https://store.steampowered.com/api/appdetails?appids={app}&l=russian"
CDN_HOSTS = ("https://shared.akamai.steamstatic.com/store_item_assets/steam/apps",
             "https://cdn.cloudflare.steamstatic.com/steam/apps")
MAX_AGE = 14 * 24 * 3600
KINDS = ("hero", "card")  # hero: wide banner, card: library capsule


def _get(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 SecretGear"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def candidate_urls(app_id, details=None):
    """Possible image URLs per kind, best first."""
    urls = {"hero": [], "card": []}
    if details:
        shots = [s.get("path_full") for s in details.get("screenshots") or [] if s.get("path_full")]
        header = details.get("header_image")
        urls["hero"] += shots[:1] + [details.get("background_raw"), details.get("background")]
        if header:
            base = header.split("?")[0].rsplit("/", 1)[0]
            urls["card"] += [f"{base}/capsule_616x353.jpg", header]
        urls["card"] += shots[1:2]
    for host in CDN_HOSTS:
        urls["hero"] += [f"{host}/{app_id}/library_hero.jpg", f"{host}/{app_id}/page_bg_raw.jpg"]
        urls["card"] += [f"{host}/{app_id}/capsule_616x353.jpg", f"{host}/{app_id}/header.jpg"]
    return {k: [u for u in v if u] for k, v in urls.items()}


def _looks_like_image(data):
    return data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n" or data[:4] == b"RIFF"


def fetch_game_art(game_id, cache_dir, fetch=_get):
    """Return {kind: path} of cached art for a game, downloading what is missing or stale."""
    app_id = STEAM_APPS.get(game_id)
    if not app_id:
        return {}
    os.makedirs(cache_dir, exist_ok=True)
    paths = {k: os.path.join(cache_dir, f"{app_id}_{k}.jpg") for k in KINDS}
    fresh = {k: p for k, p in paths.items() if os.path.exists(p) and time.time() - os.path.getmtime(p) < MAX_AGE}
    if len(fresh) == len(KINDS):
        return fresh
    details = None
    try:
        payload = json.loads(fetch(APPDETAILS.format(app=app_id)).decode("utf-8"))
        entry = payload.get(str(app_id)) or {}
        if entry.get("success"):
            details = entry.get("data") or {}
    except Exception as e:  # offline or blocked: fall back to direct CDN paths
        logging.info("appdetails %s failed: %s", app_id, e)
    result = dict(fresh)
    for kind, urls in candidate_urls(app_id, details).items():
        if kind in result:
            continue
        for url in urls:
            try:
                data = fetch(url)
            except Exception:
                continue
            if _looks_like_image(data):
                tmp = paths[kind] + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, paths[kind])
                result[kind] = paths[kind]
                break
        if kind not in result and os.path.exists(paths[kind]):
            result[kind] = paths[kind]  # stale copy is better than nothing
    logging.info("art for %s: %s", game_id, sorted(result))
    return result


def cached_game_art(game_id, cache_dir):
    app_id = STEAM_APPS.get(game_id)
    if not app_id:
        return {}
    out = {}
    for kind in KINDS:
        p = os.path.join(cache_dir, f"{app_id}_{kind}.jpg")
        if os.path.exists(p):
            out[kind] = p
    return out
