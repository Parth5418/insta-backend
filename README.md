# Secure Instagram Downloader (Flask + yt-dlp fallback)

This project is a secured Instagram downloader backend you can deploy to Vercel.
It protects access using a secret API key and supports yt-dlp fallback for public media.

## Security (do not commit secrets)
- Set the following environment variables in Vercel (Project → Settings → Environment Variables):
  - ACCESS_TOKEN = <your long-lived Instagram Graph API token> (optional)
  - SECRET_KEY = 2yZ9EV0F_E9D8cBWVv2MkVmUU2AjCGVsZ3Y7DbiuCyk
  - CACHE_TTL_SECONDS = 3600

## Deploy
1. Upload this project to GitHub or import to Vercel directly.
2. In Vercel, set the environment variables listed above (particularly SECRET_KEY and ACCESS_TOKEN if you have one).
3. Deploy and call the endpoint:
   https://<your-vercel-domain>/download?url=<insta-url>&key=<SECRET_KEY>

## Notes
- yt-dlp is used as a fallback for fetching direct media URLs. Use responsibly.
- Keep your ACCESS_TOKEN and SECRET_KEY secret. Use Vercel environment variables.
