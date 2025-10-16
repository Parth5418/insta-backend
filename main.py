from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
import os, time, requests, subprocess, tempfile

app = Flask(__name__)
CORS(app)

# -------------------------------
# Configuration from env
# -------------------------------
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")  # set this in Vercel env (optional)
SECRET_KEY = os.getenv("SECRET_KEY")      # set this in Vercel env (do NOT hardcode)
CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "3600"))
GRAPH_API_BASE = "https://graph.facebook.com/v21.0"

if not SECRET_KEY:
    print("⚠ WARNING: SECRET_KEY not set. Set SECRET_KEY environment variable in Vercel.")

# Simple in-memory cache
CACHE = {}

limiter = Limiter(get_remote_address, app=app, default_limits=["10 per minute"])

# Security middleware
@app.before_request
def verify_access():
    if request.path == "/download":
        api_key = request.args.get("key")
        if not api_key or api_key != SECRET_KEY:
            return jsonify({"success": False, "error": "Unauthorized: invalid API key"}), 403

def cache_get(key):
    e = CACHE.get(key)
    if e and (time.time() - e['ts']) < CACHE_TTL:
        return e['val']
    return None

def cache_set(key, val):
    CACHE[key] = {'val': val, 'ts': time.time()}

def extract_shortcode(insta_url: str):
    from urllib.parse import urlparse
    p = urlparse(insta_url).path
    parts = [x for x in p.split('/') if x]
    return parts[-1] if parts else None

def fetch_oembed(url):
    try:
        r = requests.get(f"{GRAPH_API_BASE}/instagram_oembed", params={"url": url, "access_token": ACCESS_TOKEN}, timeout=10)
        return r.json()
    except Exception as e:
        print("oEmbed fetch error:", e)
        return None

def fetch_graph_media_for_token(shortcode):
    try:
        pages = requests.get(f"{GRAPH_API_BASE}/me/accounts", params={"access_token": ACCESS_TOKEN}, timeout=10).json()
        for page in pages.get("data", []):
            page_id = page.get("id")
            if not page_id:
                continue
            ig_info = requests.get(f"{GRAPH_API_BASE}/{page_id}", params={"fields": "instagram_business_account", "access_token": ACCESS_TOKEN}, timeout=10).json()
            ig_account = ig_info.get("instagram_business_account")
            if not ig_account:
                continue
            ig_id = ig_account.get("id")
            if not ig_id:
                continue
            media = requests.get(f"{GRAPH_API_BASE}/{ig_id}/media", params={"fields": "id,permalink,media_type,media_url,thumbnail_url,caption", "access_token": ACCESS_TOKEN, "limit": 50}, timeout=10).json()
            for item in media.get("data", []):
                if shortcode in item.get("permalink", ""):
                    return item
    except Exception as e:
        print("Graph fetch error:", e)
    return None

def scrape_with_ytdlp(url):
    try:
        cmd = ["yt-dlp", "-g", url]
        out = subprocess.check_output(cmd, text=True).strip()
        for line in out.splitlines():
            line = line.strip()
            if line:
                return line
    except Exception as e:
        print("yt-dlp error:", e)
    return None

@app.route("/")
def home():
    return jsonify({"status": "restricted"}), 403

@app.route("/download")
@limiter.limit("10/minute")
def download():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"success": False, "error": "Missing url parameter"}), 400
    shortcode = extract_shortcode(url)
    if not shortcode:
        return jsonify({"success": False, "error": "Invalid Instagram URL"}), 400

    cache_key = f"video:{shortcode}"
    cached = cache_get(cache_key)
    if cached:
        return jsonify({"success": True, "cached": True, "video_url": cached}), 200

    # Try Graph API
    if ACCESS_TOKEN:
        item = fetch_graph_media_for_token(shortcode)
        if item and item.get("media_type","").upper() == "VIDEO":
            video_url = item.get("media_url") or item.get("thumbnail_url")
            if video_url:
                cache_set(cache_key, video_url)
                return jsonify({"success": True, "video_url": video_url, "source": "graph"}), 200

    # Try oEmbed
    oembed = fetch_oembed(url) if ACCESS_TOKEN else None
    if oembed and "thumbnail_url" in oembed:
        cache_set(cache_key, oembed.get("thumbnail_url"))
        return jsonify({"success": True, "video_url": oembed.get("thumbnail_url"), "source": "oembed"}), 200

    # Fallback yt-dlp
    video = scrape_with_ytdlp(url)
    if video:
        cache_set(cache_key, video)
        return jsonify({"success": True, "video_url": video, "source": "yt-dlp"}), 200

    return jsonify({"success": False, "error": "Failed to fetch media"}), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","5000")))
