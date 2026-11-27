# Deploy — Cloudflare Pages (LIVE 2026-11-27)

Deployed 2026-11-27 ~16:08 Asia/Dhaka via the native Cloudflare
connector (account "Smabdulmueid97@gmail.com's Account"; Cloudflare
user smabdulmueid97@gmail.com). The Cloudflare account ID is not
recorded here — find it in the Cloudflare dashboard and export it as
CLOUDFLARE_ACCOUNT_ID before re-running `deploy_pages.py`.

- Project: `nevo-youtube-uploader`
- Home: https://nevo-youtube-uploader.pages.dev/
- Privacy: https://nevo-youtube-uploader.pages.dev/privacy.html
  (Cloudflare serves it at /privacy too — /privacy.html 308-redirects
  to /privacy; both work.)
- Deployment id: 9c0561ad-b135-42e8-b49c-9ec2568d1def, environment production.
- Files deployed: `index.html` + `privacy.html` (comments updated to the
  real pages.dev URLs; no YOUR-DOMAIN-HERE placeholder left anywhere).
- Verified live with curl: home 200 "Nevo YouTube Uploader", privacy 200
  "Privacy Policy — Nevo YouTube Uploader".

## How it was deployed (Direct Upload flow)

1. `POST /accounts/{id}/pages/projects` {name, production_branch: "main"}.
2. `GET .../pages/projects/{project}/upload-token` -> short-lived JWT.
3. `POST /pages/assets/upload` with the JWT as Bearer + base64 files
   (MD5 hex as asset keys). **Must run from this VM with curl, not
   through the connector's `execute` sandbox: the sandbox replaces the
   Authorization header with the session token, so the JWT-only assets
   endpoints 403 there. The JWT is short-lived (~30 min) and scoped to
   this project; fetch a fresh one per deploy, keep it in /tmp mode 600,
   shred it after.**
4. `POST .../pages/projects/{project}/deployments` with a FormData
   manifest {"/index.html": md5, "/privacy.html": md5} via `execute`
   (session auth works for this account-scoped call).
- Helper: `deploy_pages.py` builds the execute arguments (hashes + base64).
- No owned domain is needed: the pages.dev URLs satisfy Google's
  home-page + privacy-policy fields for Publishing the OAuth app. The
  user's own domain can be attached later in Cloudflare if wanted.

## Next

The OAuth app is **Published — In production** since 2026-11-27
(see below). Branding now points at the custom domain, not pages.dev:
home https://superuploadermcp.nemonit.com/ and privacy
https://superuploadermcp.nemonit.com/privacy.html (app name also
renamed to YouTube-SuperUploaderMCP by the owner during publishing).
Refresh tokens no longer expire after 7 days. Google shows a
"requires verification" banner; the app has NOT been submitted for
verification — fine while only the owner uses it.

Custom domains on the Pages project (both live, verified 200):
- https://superuploadermcp.nemonit.com/ (canonical, matches Branding)
- https://youtube-superuploadermcp.nemonit.com/
- https://nevo-youtube-uploader.pages.dev/ (fallback)
The Pages project name stays `nevo-youtube-uploader` (not renamed).
Attaching a custom domain did NOT create DNS by itself: add a proxied
CNAME for each subdomain pointing at `nevo-youtube-uploader.pages.dev`
or the domain will not resolve (curl 000 until the records exist;
brief 522s while the cert settles are normal).
