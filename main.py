from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import requests
import re
import json
import time

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

CACHE = {}
CACHE_TTL = 3600  # 1 hour


@app.get("/")
def home():
    return {"message": "🚀 Instagram Downloader API Updated (2025 Ready)"}


@app.get("/download")
def get_instagram_video(url: str = Query(...)):
    # 1️⃣ Check Cache
    if url in CACHE and time.time() - CACHE[url]["timestamp"] < CACHE_TTL:
        return {"success": True, "cached": True, "video_url": CACHE[url]["video_url"]}

    # 2️⃣ Fetch HTML
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
        html = requests.get(url, headers=headers, timeout=10).text

        # 3️⃣ Try to extract video URL from GraphQL data
        match = re.search(r'"video_versions":\[(.*?)\]', html)
        if match:
            json_part = "{" + match.group(0) + "}"
            urls = re.findall(r'"url":"(.*?)"', json_part)
            if urls:
                video_url = urls[0].replace("\\u0026", "&")
                CACHE[url] = {"video_url": video_url, "timestamp": time.time()}
                return {"success": True, "cached": False, "video_url": video_url}

        # 4️⃣ Try to extract from ld+json script (fallback)
        match_ld = re.search(r'<script type="application/ld\+json">(.*?)</script>', html)
        if match_ld:
            data = json.loads(match_ld.group(1))
            video_url = data.get("video", {}).get("contentUrl")
            if video_url:
                CACHE[url] = {"video_url": video_url, "timestamp": time.time()}
                return {"success": True, "cached": False, "video_url": video_url}

        return {"success": False, "error": "Video not found. May be private or new format."}

    except Exception as e:
        return {"success": False, "error": str(e)}
