# Deploy — Cloudflare Pages

The two files in this folder (`index.html` home page +
`privacy.html` privacy policy) are the public URLs Google's OAuth
Branding page requires before the app can be Published (see the README,
Step 2). Any static host works; this guide uses Cloudflare Pages
Direct Upload.

## Deploy

1. Create a Pages project in the Cloudflare dashboard (any name, e.g.
   `my-youtube-uploader`), production branch `main`.
2. Export your Cloudflare account ID (find it in the dashboard,
   Account Home) and the project name:

   ```bash
   export CLOUDFLARE_ACCOUNT_ID="<account id>"
   export CLOUDFLARE_PAGES_PROJECT="<project name>"
   ```

   The account ID is never stored in this repo.
3. From the repo root, build the deploy arguments, then run them through
   the Cloudflare connector's `execute` (or any runner that can call the
   Cloudflare API with your credentials):

   ```bash
   python3 deploy_pages.py   # writes /tmp/pages-deploy-args.json
   ```

## How it works (Direct Upload flow)

1. `POST /accounts/{id}/pages/projects` {name, production_branch: "main"}.
2. `GET .../pages/projects/{project}/upload-token` → short-lived JWT
   (~30 min).
3. `POST /pages/assets/upload` with the JWT as Bearer + base64 files
   (MD5 hex as asset keys). **Run the asset upload from a machine with
   curl, not through a sandboxed `execute` that rewrites the
   Authorization header — the JWT-only assets endpoints 403 there. The
   JWT is short-lived and scoped to this project; fetch a fresh one per
   deploy, keep it in /tmp mode 600, shred it after.**
4. `POST .../pages/projects/{project}/deployments` with a FormData
   manifest {"/index.html": md5, "/privacy.html": md5}.

`deploy_pages.py` builds the execute arguments (hashes + base64) for
steps 2–4.

## After deploy

- Home: `https://<project>.pages.dev/`
- Privacy: `https://<project>.pages.dev/privacy.html`
  (Cloudflare also serves it at `/privacy`; both work.)
- No owned domain is needed: the `pages.dev` URLs satisfy Google's
  home-page + privacy-policy fields. A custom domain can be attached
  later in Cloudflare if wanted — note that attaching a domain does
  NOT create DNS by itself: add a proxied CNAME for the subdomain
  pointing at `<project>.pages.dev`, or the domain will not resolve.
  Brief 522s while the certificate settles are normal.
- Put the two URLs in the OAuth app's Branding page, add your domain to
  Authorized domains, and Publish the app (README Step 2).
