from flask import Flask, request, jsonify
import requests, os, time
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
if not ACCESS_TOKEN:
    print("⚠️ WARNING: ACCESS_TOKEN not set. Set it in .env or Vercel dashboard!")

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"

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
    try:
        p = urlparse(insta_url).path
        parts = [x for x in p.split('/') if x]
        return parts[-1] if parts else None
    except:
        return None

@app.route('/')
def home():
    return jsonify({"status": "ok", "message": "✅ Instagram Graph API downloader running fine!"}), 200

@app.route('/download')
def download():
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({"success": False, "error": "Missing url parameter"}), 400

    shortcode = extract_shortcode(url)
    if not shortcode:
        return jsonify({"success": False, "error": "Invalid Instagram URL"}), 400

    cache_key = f"video:{shortcode}"
    cached = cache_get(cache_key)
    if cached:
        return jsonify({"success": True, "cached": True, "video_url": cached}), 200

    if not ACCESS_TOKEN:
        return jsonify({"success": False, "error": "Server misconfigured: ACCESS_TOKEN missing"}), 500

    oembed_url = f"{GRAPH_API_BASE}/instagram_oembed"
    params = {"url": url, "access_token": ACCESS_TOKEN}
    try:
        r = requests.get(oembed_url, params=params, timeout=8)
        oembed = r.json()
        if isinstance(oembed, dict) and "thumbnail_url" in oembed:
            video = oembed["thumbnail_url"]
            cache_set(cache_key, video)
            return jsonify({"success": True, "video_url": video, "oembed": True}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    return jsonify({"success": False, "error": "Media not found"}), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", "5000")))
