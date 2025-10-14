from flask import Flask, request, jsonify
import requests
import time

app = Flask(__name__)

# In-memory cache (you can switch to Redis in production)
CACHE = {}

# ===============================
# 🔧 CONFIGURATION
# ===============================
ACCESS_TOKEN = EAATj0Q4ULKsBPhasIcu4P9ZC5WZBeEko7Jqt0SZBAkoALzHYn2L69kDeSYOaRGfUtvxFiGvH3Ea6JiBgEhHexDZAl42EvsReFWtNmlC4L5W5jaBqpybQbMhMM9yyToDiAIc0UIv8M03LsI408NV1I46khxFhrZBEYrZAltlN5ZB5Qx0f4pYgQcJ5ND9jWyBAKrYZAeexFi1lzW8Kxlyo
GRAPH_URL = "https://graph.facebook.com/v21.0"

# ===============================
# ⚡ Helper: Cached GET request
# ===============================
def cached_get(url, expire=600):
    if url in CACHE and (time.time() - CACHE[url]["time"]) < expire:
        return CACHE[url]["data"]
    r = requests.get(url)
    data = r.json()
    CACHE[url] = {"data": data, "time": time.time()}
    return data

# ===============================
# ⚙️ Helper: Get Instagram Business ID from Page ID
# ===============================
def get_instagram_id_from_page(page_id):
    url = f"{GRAPH_URL}/{page_id}?fields=instagram_business_account&access_token={ACCESS_TOKEN}"
    data = cached_get(url)
    ig_data = data.get("instagram_business_account")
    return ig_data["id"] if ig_data else None

# ===============================
# ⚙️ Helper: Extract Reel shortcode from URL
# ===============================
def extract_shortcode(insta_url: str):
    try:
        parts = insta_url.split("/")
        for p in parts:
            if len(p) >= 8 and p.isalnum():
                return p
        return None
    except:
        return None

# ===============================
# 📲 Main Download Endpoint
# ===============================
@app.route("/download", methods=["GET"])
def download():
    reel_url = request.args.get("url")
    if not reel_url:
        return jsonify({"success": False, "error": "URL missing"}), 400

    try:
        shortcode = extract_shortcode(reel_url)
        if not shortcode:
            return jsonify({"success": False, "error": "Invalid URL"}), 400

        cache_key = f"reel_{shortcode}"
        if cache_key in CACHE and (time.time() - CACHE[cache_key]["time"]) < 86400:
            return jsonify({"success": True, "cached": True, "data": CACHE[cache_key]["data"]})

        # -----------------------------
        # Step 1️⃣ - Get all pages (linked to the token)
        pages = cached_get(f"{GRAPH_URL}/me/accounts?access_token={ACCESS_TOKEN}")
        if "data" not in pages or len(pages["data"]) == 0:
            return jsonify({"success": False, "error": "No pages linked to this token"}), 400

        for page in pages["data"]:
            page_id = page["id"]
            ig_id = get_instagram_id_from_page(page_id)
            if not ig_id:
                continue

            # Step 2️⃣ - Fetch all media for this IG account
            media_url = f"{GRAPH_URL}/{ig_id}/media?fields=id,media_type,media_url,permalink,thumbnail_url,caption&access_token={ACCESS_TOKEN}"
            media_data = cached_get(media_url)
            if "data" not in media_data:
                continue

            # Step 3️⃣ - Try to match shortcode
            for m in media_data["data"]:
                if shortcode in m.get("permalink", ""):
                    CACHE[cache_key] = {"data": m, "time": time.time()}
                    return jsonify({"success": True, "data": m})

        # Step 4️⃣ - Fallback → oEmbed (for public reels)
        oembed_url = f"https://graph.facebook.com/v21.0/instagram_oembed?url={reel_url}&access_token={ACCESS_TOKEN}"
        oembed_data = requests.get(oembed_url).json()

        if "thumbnail_url" in oembed_data or "author_name" in oembed_data:
            CACHE[cache_key] = {"data": oembed_data, "time": time.time()}
            return jsonify({"success": True, "data": oembed_data})

        return jsonify({"success": False, "error": "No video found or private account."})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ===============================
# 🧠 Root route
# ===============================
@app.route("/")
def home():
    return jsonify({"message": "✅ Insta Downloader Backend Running!", "status": "ok"})

if __name__ == "__main__":
    app.run(debug=True)
