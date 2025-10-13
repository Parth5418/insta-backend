from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import requests
import re
import time

app = FastAPI()

# ✅ Allow all origins for Android
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🧠 Simple in-memory cache (URL → {video_url, timestamp})
CACHE = {}
CACHE_TTL = 3600  # 1 hour cache time (seconds)


@app.get("/")
def home():
    return {"message": "🚀 Instagram Downloader API is Live!"}


@app.get("/download")
def get_instagram_video(url: str = Query(..., description="Instagram Reel/Post URL")):
    # 🔹 1. Check cache first
    if url in CACHE:
        data = CACHE[url]
        if time.time() - data["timestamp"] < CACHE_TTL:
            return {"success": True, "cached": True, "video_url": data["video_url"]}

    # 🔹 2. If not in cache, scrape Instagram page
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
        html = requests.get(url, headers=headers).text
        match = re.search(r'"video_url":"(.*?)"', html)

        if match:
            video_url = match.group(1).replace("\\u0026", "&")
            # 🔹 Save to cache
            CACHE[url] = {"video_url": video_url, "timestamp": time.time()}
            return {"success": True, "cached": False, "video_url": video_url}
        else:
            return {"success": False, "error": "No video found or private account."}

    except Exception as e:
        return {"success": False, "error": str(e)}
