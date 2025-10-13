from flask import Flask, request, jsonify
import requests
import time
import os

app = Flask(__name__)

# ================= Configuration =================
ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN")  # Set in Vercel
CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", 3600))  # 1 hour

# In-memory cache
CACHE = {}

# ================= Utility Functions =================
def get_from_cache(post_id):
    entry = CACHE.get(post_id)
    if entry and (time.time() - entry["time"]) < CACHE_TTL:
        return entry["video_url"]
    return None

def save_to_cache(post_id, video_url):
    CACHE[post_id] = {"video_url": video_url, "time": time.time()}

# ================= Routes =================
@app.route("/")
def index():
    return jsonify({"status": "ok", "message": "Instagram Graph API Downloader"})

@app.route("/download", methods=["GET"])
def download():
    url = request.args.get("url")
    if not url:
        return jsonify({"success": False, "error": "Missing 'url' parameter"}), 400

    # Extract shortcode from URL
    try:
        shortcode = url.rstrip("/").split("/")[-1]
    except Exception:
        return jsonify({"success": False, "error": "Invalid URL"}), 400

    # Check cache
    cached = get_from_cache(shortcode)
    if cached:
        return jsonify({"success": True, "video_url": cached, "cached": True})

    # Call Instagram Graph API
    api_url = f"https://graph.facebook.com/v18.0/ig_shortcode/{shortcode}?fields=media_type,media_url,username&access_token={ACCESS_TOKEN}"
    try:
        resp = requests.get(api_url, timeout=10)
        data = resp.json()
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    if "error" in data:
        return jsonify({"success": False, "error": data["error"]["message"]}), 400

    if data.get("media_type") != "VIDEO":
        return jsonify({"success": False, "error": "Not a video post"}), 400

    video_url = data.get("media_url")
    if not video_url:
        return jsonify({"success": False, "error": "Video URL not found"}), 404

    # Save cache
    save_to_cache(shortcode, video_url)

    return jsonify({"success": True, "video_url": video_url, "cached": False})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
