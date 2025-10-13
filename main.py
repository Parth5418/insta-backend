# main.py
import os
import time
import json
import re
from typing import Optional, Dict, Any, List

from flask import Flask, request, jsonify
import requests

# Optional libs
try:
    import redis
except Exception:
    redis = None

# Rate limiter (optional, installed via requirements)
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
except Exception:
    Limiter = None

app = Flask(__name__)

# ===== Configuration via ENV =====
CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "3600"))   # default 1 hour
REDIS_URL = os.getenv("REDIS_URL", "").strip()           # set this in Vercel if you want persistent cache
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "10"))

# Simple UA rotation (add more if you like)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
]

# ===== Cache backend: Redis if provided else in-memory =====
USE_REDIS = False
redis_client = None
if REDIS_URL and redis:
    try:
        redis_client = redis.from_url(REDIS_URL)
        # quick test
        redis_client.ping()
        USE_REDIS = True
    except Exception as e:
        print("Redis init failed, falling back to in-memory cache:", e)
        USE_REDIS = False

# In-memory cache structure: {key: (value, timestamp)}
MEMCACHE: Dict[str, Dict[str, Any]] = {}

# Rate limiter setup (best-effort)
if Limiter:
    limiter = Limiter(app, key_func=get_remote_address, default_limits=["60/minute"])
else:
    limiter = None

# ===== Utilities: caching helpers =====
def cache_get(key: str) -> Optional[str]:
    if USE_REDIS and redis_client:
        try:
            val = redis_client.get(key)
            if val:
                return val.decode("utf-8")
            return None
        except Exception:
            return None
    else:
        entry = MEMCACHE.get(key)
        if entry and (time.time() - entry["ts"]) < CACHE_TTL:
            return entry["value"]
        return None

def cache_set(key: str, value: str) -> None:
    if USE_REDIS and redis_client:
        try:
            redis_client.setex(key, CACHE_TTL, value)
        except Exception:
            # fallback to memcache if redis fails unexpectedly
            MEMCACHE[key] = {"value": value, "ts": time.time()}
    else:
        MEMCACHE[key] = {"value": value, "ts": time.time()}

# ===== HTML parsing helpers: try multiple strategies =====
def try_extract_from_video_versions(html: str) -> Optional[str]:
    # pattern: "video_versions":[{...,"url":"..."}]
    m = re.search(r'"video_versions":\s*\[(.*?)\]', html, flags=re.S)
    if not m:
        return None
    part = m.group(1)
    urls = re.findall(r'"url":"([^"]+)"', part)
    if urls:
        # choose highest-quality URL (first is usually highest)
        return urls[0].replace("\\u0026", "&")
    return None

def try_ld_json(html: str) -> Optional[str]:
    # <script type="application/ld+json"> ... </script>
    matches = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, flags=re.S)
    for block in matches:
        try:
            data = json.loads(block)
            # ld+json can be a dict or list
            if isinstance(data, dict):
                # try common paths
                v = data.get("video") or data.get("mainEntityOfPage") or {}
                if isinstance(v, dict):
                    content = v.get("contentUrl") or v.get("url")
                    if content:
                        return content
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        v = item.get("video", {})
                        if isinstance(v, dict) and v.get("contentUrl"):
                            return v.get("contentUrl")
        except Exception:
            continue
    return None

def try_shared_data(html: str) -> Optional[str]:
    # window._sharedData = {...};
    m = re.search(r'window\._sharedData\s*=\s*({.*?});', html, flags=re.S)
    if not m:
        # Instagram sometimes uses other variable names, try search for "shortcode_media"
        m2 = re.search(r'({"config":.*"shortcode_media".*})', html, flags=re.S)
        if not m2:
            return None
        json_text = m2.group(1)
    else:
        json_text = m.group(1)
    try:
        data = json.loads(json_text)
    except Exception:
        # try to sanitize some escaped quotes
        try:
            json_text = json_text.replace('\\/', '/')
            data = json.loads(json_text)
        except Exception:
            return None

    # navigate to shortcode_media in known shapes
    candidates = []
    # typical path: entry_data->PostPage->[0]->graphql->shortcode_media
    def dig(dct, keys: List[str]):
        cur = dct
        for k in keys:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                return None
        return cur

    sc = dig(data, ["entry_data", "PostPage", 0, "graphql", "shortcode_media"]) or \
         dig(data, ["entry_data", "PostPage", 0, "media"]) or \
         dig(data, ["graphql", "shortcode_media"]) or \
         None

    # If sc found, try video_url or video_versions or edge_media_to_children
    if sc and isinstance(sc, dict):
        # single video
        if sc.get("video_url"):
            return sc.get("video_url")
        # graphql sometimes uses "video_versions"
        v = sc.get("video_versions")
        if v and isinstance(v, list) and len(v) > 0:
            url = v[0].get("url")
            if url:
                return url
        # sidecar (multiple media)
        if sc.get("edge_sidecar_to_children"):
            edges = sc["edge_sidecar_to_children"].get("edges", [])
            for edge in edges:
                node = edge.get("node", {})
                # prefer video nodes
                if node.get("is_video") and node.get("video_url"):
                    return node.get("video_url")
                if node.get("is_video") and node.get("video_versions"):
                    vv = node.get("video_versions")
                    if isinstance(vv, list) and len(vv) > 0:
                        return vv[0].get("url")
    return None

def try_graphql_in_html(html: str) -> Optional[str]:
    # Sometimes Instagram embeds a big JSON block containing "shortcode_media"
    # Try to locate "shortcode_media" object and parse a nearest json substring
    m = re.search(r'(?P<json>\{.*"shortcode_media".*?\}\s*\})', html, flags=re.S)
    if not m:
        # Try looser extraction: find "shortcode_media":{...}
        m2 = re.search(r'"shortcode_media":\s*({.*?})\s*,\s*"', html, flags=re.S)
        if not m2:
            return None
        try:
            block = "{" + m2.group(1) + "}"
            data = json.loads(block)
            if data.get("video_url"):
                return data["video_url"]
        except Exception:
            return None
    else:
        try:
            data = json.loads(m.group("json"))
            # reuse shared_data extractor
            if isinstance(data, dict):
                # dive to find video_url
                def scan_dict_for_key(d, key="video_url"):
                    if isinstance(d, dict):
                        if key in d:
                            return d[key]
                        for v in d.values():
                            res = scan_dict_for_key(v, key)
                            if res:
                                return res
                    elif isinstance(d, list):
                        for item in d:
                            res = scan_dict_for_key(item, key)
                            if res:
                                return res
                    return None
                return scan_dict_for_key(data, "video_url")
        except Exception:
            return None
    return None

def try_display_url(html: str) -> Optional[str]:
    # fallback: sometimes only a display_url (image) exists — not a video
    m = re.search(r'"display_url":"([^"]+)"', html)
    if m:
        return m.group(1).replace("\\u0026", "&")
    return None

def extract_video_url(html: str) -> Optional[str]:
    # Try multiple extractors in order of reliability
    extractors = [
        try_extract_from_video_versions,
        try_shared_data,
        try_graphql_in_html,
        try_ld_json,
        try_display_url  # last resort (may be image)
    ]
    for fn in extractors:
        try:
            url = fn(html)
            if url:
                return url
        except Exception:
            continue
    return None

# ===== Fetch page with UA rotation and retries =====
def fetch_instagram_page(url: str, allow_proxies: bool = False) -> Optional[str]:
    session = requests.Session()
    session.headers.update({
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.instagram.com/",
        "Sec-Fetch-Dest": "document"
    })
    last_exc = None
    for attempt in range(MAX_RETRIES + 1):
        ua = USER_AGENTS[attempt % len(USER_AGENTS)]
        session.headers["User-Agent"] = ua
        try:
            proxy = os.getenv("HTTP_PROXY", "") if allow_proxies else ""
            if proxy:
                resp = session.get(url, timeout=REQUEST_TIMEOUT, proxies={"http": proxy, "https": proxy})
            else:
                resp = session.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp.text
            else:
                last_exc = Exception(f"HTTP {resp.status_code}")
        except Exception as e:
            last_exc = e
            time.sleep(0.5 + attempt * 0.5)
    # if all tries fail, raise last exception message
    if last_exc:
        raise last_exc
    return None

# ===== Flask routes =====
@app.route("/")
def index():
    return jsonify({"status": "ok", "message": "Instagram downloader (production)"}), 200

# Apply rate-limit decoration dynamically if limiter available
def rate_limited_route(func):
    if limiter:
        return limiter.limit("30/minute")(func)
    return func

@app.route("/download", methods=["GET"])
@rate_limited_route
def download_endpoint():
    ig_url = request.args.get("url", "").strip()
    if not ig_url:
        return jsonify({"success": False, "error": "Missing 'url' parameter"}), 400

    # normalize
    ig_url = ig_url.split("?")[0]
    if not ig_url.endswith("/"):
        ig_url = ig_url + "/"

    # check cache
    cache_key = f"video:{ig_url}"
    cached = cache_get(cache_key)
    if cached:
        return jsonify({"success": True, "video_url": cached, "cached": True}), 200

    # fetch page and extract
    try:
        html = fetch_instagram_page(ig_url)
    except Exception as e:
        return jsonify({"success": False, "error": f"Failed to fetch page: {str(e)}"}), 502

    try:
        video_url = extract_video_url(html)
    except Exception as e:
        video_url = None

    if not video_url:
        # second attempt: try with a differently encoded URL (mobile)
        mobile_url = ig_url.replace("www.instagram.com", "i.instagram.com")
        try:
            html2 = fetch_instagram_page(mobile_url)
            video_url = extract_video_url(html2)
        except Exception:
            video_url = None

    if not video_url:
        return jsonify({"success": False, "error": "No video found or private account."}), 404

    # store cache
    try:
        cache_set(cache_key, video_url)
    except Exception:
        pass

    return jsonify({"success": True, "video_url": video_url, "cached": False}), 200

# Health endpoint
@app.route("/healthz")
def health():
    info = {"ok": True, "redis": bool(USE_REDIS)}
    return jsonify(info), 200

# Run (Vercel will use this file)
if __name__ == "__main__":
    # For local debugging
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
