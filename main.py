# main.py
import os
import time
import json
from typing import Optional, Dict, Any
from urllib.parse import urlparse

import requests
from flask import Flask, request, jsonify

# Optional redis support
try:
    import redis
except Exception:
    redis = None

app = Flask(__name__)

# ===== Configuration via environment variables =====
IG_USER_ID = os.getenv("IG_USER_ID", "").strip()            # required: your Instagram Business Account ID
IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN", "").strip()  # required: long-lived user access token
CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "3600"))     # seconds
REDIS_URL = os.getenv("REDIS_URL", "").strip()              # optional; e.g. redis://:pwd@host:port/0
PAGE_SIZE = int(os.getenv("GRAPH_PAGE_SIZE", "50"))         # how many media per page to request
MAX_PAGES = int(os.getenv("MAX_PAGES", "6"))                # how many pages to paginate (50*6 = 300 items)

# ===== Basic validation =====
if not IG_USER_ID or not IG_ACCESS_TOKEN:
    print("WARNING: IG_USER_ID and IG_ACCESS_TOKEN must be set in env. Backend will still start but API calls will fail until set.")

# ===== Redis init (optional) =====
USE_REDIS = False
redis_client = None
if REDIS_URL and redis:
    try:
        redis_client = redis.from_url(REDIS_URL)
        redis_client.ping()
        USE_REDIS = True
        print("Using Redis for cache.")
    except Exception as e:
        print("Redis init failed — falling back to in-memory cache:", e)
        USE_REDIS = False

# In-memory cache fallback: {key: (value, ts)}
MEMCACHE: Dict[str, Dict[str, Any]] = {}

def cache_get(key: str) -> Optional[str]:
    try:
        if USE_REDIS and redis_client:
            val = redis_client.get(key)
            return val.decode("utf-8") if val else None
        else:
            e = MEMCACHE.get(key)
            if e and (time.time() - e["ts"]) < CACHE_TTL:
                return e["value"]
        return None
    except Exception:
        return None

def cache_set(key: str, value: str) -> None:
    try:
        if USE_REDIS and redis_client:
            redis_client.setex(key, CACHE_TTL, value)
        else:
            MEMCACHE[key] = {"value": value, "ts": time.time()}
    except Exception:
        pass

# ===== Helpers =====
def extract_shortcode_from_url(url: str) -> Optional[str]:
    if not url:
        return None
    # remove query params
    parsed = urlparse(url)
    path = parsed.path  # e.g. /reel/DPclazvkWlc/
    parts = [p for p in path.split("/") if p]
    if not parts:
        return None
    # shortcode is usually last part (post/reel) -> e.g. ['reel', 'DPclazvkWlc']
    return parts[-1]

def fetch_media_pages(ig_user_id: str, page_size: int = PAGE_SIZE, max_pages: int = MAX_PAGES):
    """Generator yielding pages of media items (dicts) from IG user via Graph API."""
    base = f"https://graph.facebook.com/v18.0/{ig_user_id}/media"
    params = {
        "fields": "id,permalink,media_type,media_url,thumbnail_url,timestamp,caption",
        "access_token": IG_ACCESS_TOKEN,
        "limit": page_size
    }
    url = base
    for page in range(max_pages):
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            # yield error dict to caller
            yield {"__error__": resp.json()}
            return
        data = resp.json()
        items = data.get("data", [])
        yield {"data": items}
        # pagination
        paging = data.get("paging", {})
        next_url = paging.get("next")
        if not next_url:
            return
        url = next_url
        # after first page, subsequent requests should not pass params again
        params = {}

# ===== Flask routes =====
@app.route("/")
def index():
    return jsonify({"status": "ok", "message": "Instagram Graph API Downloader (media-scan version)"}), 200

@app.route("/download", methods=["GET"])
def download():
    req_url = request.args.get("url", "").strip()
    if not req_url:
        return jsonify({"success": False, "error": "Missing 'url' parameter"}), 400

    shortcode = extract_shortcode_from_url(req_url)
    if not shortcode:
        return jsonify({"success": False, "error": "Could not parse shortcode from URL"}), 400

    cache_key = f"video:{shortcode}"
    cached = cache_get(cache_key)
    if cached:
        return jsonify({"success": True, "video_url": cached, "cached": True}), 200

    if not IG_USER_ID or not IG_ACCESS_TOKEN:
        return jsonify({"success": False, "error": "Server misconfigured: IG_USER_ID or IG_ACCESS_TOKEN missing"}), 500

    # Iterate pages of the IG user's media and search for matching shortcode/permalink
    try:
        for page in fetch_media_pages(IG_USER_ID):
            if "__error__" in page:
                return jsonify({"success": False, "error": "Graph API error", "details": page["__error__"]}), 502
            items = page.get("data", [])
            for m in items:
                permalink = m.get("permalink", "") or ""
                # permalink may contain shortcode; compare
                if shortcode in permalink:
                    # ensure it's a video
                    if m.get("media_type", "").upper() not in ("VIDEO",):
                        return jsonify({"success": False, "error": "Found post but it is not a video", "media_type": m.get("media_type")}), 400
                    video_url = m.get("media_url") or m.get("thumbnail_url")
                    if not video_url:
                        return jsonify({"success": False, "error": "media_url missing in Graph response for matched item"}), 502
                    # cache and return
                    cache_set(cache_key, video_url)
                    return jsonify({"success": True, "video_url": video_url, "cached": False}), 200
        # if loop finishes, not found
        return jsonify({
            "success": False,
            "error": "Media not found in this IG account's recent media. Note: Graph API media endpoint only returns media for the IG account you control (IG_USER_ID).",
            "hint": "If you want media from other public users, use oEmbed (requires app review) or scraping."
        }), 404

    except Exception as e:
        return jsonify({"success": False, "error": "Exception during processing", "details": str(e)}), 500

@app.route("/healthz")
def health():
    return jsonify({"ok": True, "redis": bool(USE_REDIS)}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
