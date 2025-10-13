from flask import Flask, request, jsonify
import requests, re, time

app = Flask(__name__)

# Simple in-memory cache {url: {"video_url": str, "time": int}}
CACHE = {}
CACHE_TTL = 60 * 60  # 1 hour

def get_from_cache(url):
    data = CACHE.get(url)
    if data and (time.time() - data["time"]) < CACHE_TTL:
        return data["video_url"]
    return None

def save_to_cache(url, video_url):
    CACHE[url] = {"video_url": video_url, "time": time.time()}

@app.route('/')
def home():
    return jsonify({"status": "OK", "message": "Instagram Downloader API Active 🚀"})

@app.route('/download', methods=['GET'])
def download():
    try:
        ig_url = request.args.get('url')
        if not ig_url:
            return jsonify({"success": False, "error": "Missing URL"})

        # Check cache first
        cached = get_from_cache(ig_url)
        if cached:
            return jsonify({"success": True, "video_url": cached, "cached": True})

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }

        # Normalize URL (remove query params)
        if "?" in ig_url:
            ig_url = ig_url.split("?")[0]

        if not ig_url.endswith("/"):
            ig_url += "/"

        # Fetch the HTML content
        r = requests.get(ig_url, headers=headers, timeout=10)
        if r.status_code != 200:
            return jsonify({"success": False, "error": f"Failed to fetch page: {r.status_code}"})

        html = r.text

        # Search for video link in HTML (2025 format)
        # Instagram now serves JSON-LD script containing "video_url"
        match = re.search(r'"video_url":"([^"]+)"', html)
        if not match:
            return jsonify({"success": False, "error": "No video found or private account."})

        video_url = match.group(1).replace("\\u0026", "&")

        # Save to cache
        save_to_cache(ig_url, video_url)

        return jsonify({"success": True, "video_url": video_url, "cached": False})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

if __name__ == '__main__':
    app.run()
