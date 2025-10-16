from flask import Flask, request, jsonify
import requests, os, time
from yt_dlp import YoutubeDL

app = Flask(__name__)

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")  # your long-lived token
GRAPH_API_BASE = "https://graph.facebook.com/v21.0"

# ---- Simple in-memory cache ----
CACHE = {}
CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "3600"))

def cache_get(key):
    entry = CACHE.get(key)
    if entry and (time.time() - entry['ts']) < CACHE_TTL:
        return entry['val']
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
        oembed_url = f"{GRAPH_API_BASE}/instagram_oembed"
        params = {"url": url, "access_token": ACCESS_TOKEN}
        r = requests.get(oembed_url, params=params, timeout=10)
        return r.json()
    except Exception:
        return None

def scrape_instagram_video(url):
    try:
        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "forceurl": True,
            "format": "best",
        }
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if "url" in info:
                return info["url"]
            elif "formats" in info and len(info["formats"]) > 0:
                return info["formats"][-1]["url"]
    except Exception as e:
        print("yt-dlp error:", e)
    return None

@app.route("/")
def home():
    return jsonify({
        "status": "ok",
        "message": "Instagram Downloader with yt-dlp fallback ready 🚀"
    }), 200

@app.route("/download")
def download():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"success": False, "error": "Missing url parameter"}), 400

    shortcode = extract_shortcode(url)
    if not shortcode:
        return jsonify({"success": False, "error": "Invalid Instagram URL"}), 400

    # check cache
    cached = cache_get(shortcode)
    if cached:
        return jsonify({"success": True, "cached": True, "video_url": cached}), 200

    # 1️⃣ Try Graph API (only works for your IG account)
    if ACCESS_TOKEN:
        try:
            oembed_data = fetch_oembed(url)
            if oembed_data and "thumbnail_url" in oembed_data:
                cache_set(shortcode, oembed_data["thumbnail_url"])
                return jsonify({"success": True, "video_url": oembed_data["thumbnail_url"], "method": "oEmbed"}), 200
        except Exception as e:
            print("oEmbed error:", e)

    # 2️⃣ Fallback — yt-dlp
    video_url = scrape_instagram_video(url)
    if video_url:
        cache_set(shortcode, video_url)
        return jsonify({"success": True, "video_url": video_url, "method": "yt-dlp"}), 200

    return jsonify({"success": False, "error": "Failed to fetch video"}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
