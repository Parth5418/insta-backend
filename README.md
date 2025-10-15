# Insta-backend (Vercel-ready)

This repository contains a small Flask backend that:
- Uses the Instagram Graph API (via a Facebook Page access token)
- Scans Instagram Business accounts connected to the Page(s) in the token
- Returns direct `media_url` for matched reel/post shortcodes
- Has a simple in-memory cache (use Redis for production if you prefer)

## Setup

1. Create a GitHub repository and upload these files (or use Vercel direct import).
2. In Vercel Dashboard -> Project Settings -> Environment Variables add:
   - `ACCESS_TOKEN`: Your Facebook Page access token (long-lived recommended)
   - `CACHE_TTL_SECONDS` (optional, default 3600)
3. Deploy the project on Vercel (Vercel will auto-detect Python and use `main.py`).
4. Test the endpoint:
   ```
   GET https://<your-vercel-domain>/download?url=https://www.instagram.com/reel/<SHORTCODE>/
   ```

## Notes
- This backend only reliably returns media for Instagram Business accounts connected to the pages your access token has access to.
- To access other users' public media you need oEmbed access (requires App Review) or scraping (not recommended).
- Keep your access token secure. Do not commit it directly to the repo.
