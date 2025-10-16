Insta downloader backend (no secret key)

Deploy steps:
1. Upload contents of this package to a GitHub repo or import into Vercel.
2. (Optional) Set ACCESS_TOKEN in Vercel environment variables to enable Graph API features.
3. Deploy and call /download?url=<instagram_url>

Notes:
- This package includes yt-dlp fallback which may be blocked by some hosting providers.
- Keep monitoring for abuse and adjust rate limits.
