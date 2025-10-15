from flask import Flask, request, jsonify
import requests, os, time
from functools import lru_cache

app = Flask(__name__)

# Use environment variable for token (do NOT hardcode tokens)
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
if not ACCESS_TOKEN:
    print("WARNING: ACCESS_TOKEN not set. Set ACCESS_TOKEN environment variable in Vercel.")

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"

# Simple in-memory cache (fallback). For production, configure REDIS and update code.
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
    try:
        # naive extraction: last non-empty path segment
        from urllib.parse import urlparse
        p = urlparse(insta_url).path
        parts = [x for x in p.split('/') if x]
        if not parts:
            return None
        return parts[-1]
    except:
        return None

def get_pages_for_token():
    url = f"{GRAPH_API_BASE}/me/accounts"
    params = {"access_token": ACCESS_TOKEN}
    r = requests.get(url, params=params, timeout=10)
    return r.json()

def get_instagram_business_id_from_page(page_id):
    url = f"{GRAPH_API_BASE}/{page_id}"
    params = {"fields": "instagram_business_account", "access_token": ACCESS_TOKEN}
    r = requests.get(url, params=params, timeout=10)
    return r.json()

def fetch_media_for_ig(ig_id, limit=50):
    url = f"{GRAPH_API_BASE}/{ig_id}/media"
    params = {"fields": "id,permalink,media_type,media_url,thumbnail_url,caption", "access_token": ACCESS_TOKEN, "limit": limit}
    r = requests.get(url, params=params, timeout=10)
    return r.json()

@app.route('/')
def home():
    return jsonify({"status":"ok","message":"Instagram Graph API downloader - set ACCESS_TOKEN in env"}), 200

@app.route('/download')
def download():
    url = request.args.get('url','').strip()
    if not url:
        return jsonify({"success": False, "error": "Missing url parameter"}), 400

    shortcode = extract_shortcode(url)
    if not shortcode:
        return jsonify({"success": False, "error": "Could not extract shortcode from URL"}), 400

    cache_key = f"video:{shortcode}"
    cached = cache_get(cache_key)
    if cached:
        return jsonify({"success": True, "cached": True, "video_url": cached}), 200

    if not ACCESS_TOKEN:
        return jsonify({"success": False, "error": "Server misconfigured: ACCESS_TOKEN missing"}), 500

    # 1) get pages linked to this token
    pages = get_pages_for_token()
    if not pages or "data" not in pages or len(pages["data"])==0:
        return jsonify({"success": False, "error": "No Facebook pages linked to this token or token invalid"}), 400

    # 2) iterate pages -> find instagram_business_account -> fetch media -> match shortcode
    for page in pages.get("data", []):
        page_id = page.get("id")
        if not page_id:
            continue
        ig_info = get_instagram_business_id_from_page(page_id)
        ig_account = ig_info.get("instagram_business_account")
        if not ig_account:
            continue
        ig_id = ig_account.get("id")
        if not ig_id:
            continue

        # page through media (single page here; for more, implement pagination)
        media_resp = fetch_media_for_ig(ig_id, limit=50)
        for item in media_resp.get("data", []):
            permalink = item.get("permalink","")
            if shortcode in permalink:
                # found
                if item.get("media_type","").upper() != "VIDEO":
                    return jsonify({"success": False, "error": "Found post but it is not a video", "media_type": item.get("media_type")}), 400
                video_url = item.get("media_url") or item.get("thumbnail_url")
                if video_url:
                    cache_set(cache_key, video_url)
                    return jsonify({"success": True, "cached": False, "video_url": video_url}), 200

    # fallback: try oEmbed (may require review for some apps)
    oembed_url = f"{GRAPH_API_BASE}/instagram_oembed"
    params = {"url": url, "access_token": ACCESS_TOKEN}
    try:
        r = requests.get(oembed_url, params=params, timeout=8)
        oembed = r.json()
        if isinstance(oembed, dict) and ("thumbnail_url" in oembed or "author_name" in oembed):
            # oEmbed provides data but may not include direct media_url for video in all cases
            # We'll try to return thumbnail if available
            video = oembed.get("thumbnail_url") or oembed.get("html")
            cache_set(cache_key, video)
            return jsonify({"success": True, "cached": False, "video_url": video, "oembed": True}), 200
    except Exception as e:
        pass

    return jsonify({"success": False, "error": "Media not found on connected Instagram accounts. For other users' public media, oEmbed (review) or scraping required."}), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", "5000")))
