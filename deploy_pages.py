"""Build the Cloudflare `execute` arguments for deploying the two website
files to the nevo-youtube-uploader Pages project (Direct Upload flow).

Writes /tmp/pages-deploy-args.json with the JS code that:
  1. GETs the Pages upload token (JWT).
  2. POSTs /pages/assets/check-missing with the MD5 hashes.
  3. POSTs /pages/assets/upload with the base64 file contents.
  4. POSTs the deployment with a manifest mapping paths -> hashes.
Returns the deployment URL + id.
"""
import base64
import hashlib
import json
import os
from pathlib import Path

# Cloudflare account ID is NOT stored in this repo. Export it before
# deploying (find it in the Cloudflare dashboard, Account Home):
#   export CLOUDFLARE_ACCOUNT_ID="<account id>"
ACCOUNT_ID = os.environ["CLOUDFLARE_ACCOUNT_ID"]
PROJECT = "nevo-youtube-uploader"
WEBSITE = Path.home() / "workspace" / "youtube-uploader" / "website"

files = {}
for name in ("index.html", "privacy.html"):
    data = (WEBSITE / name).read_bytes()
    files["/" + name] = {
        "md5": hashlib.md5(data).hexdigest(),
        "b64": base64.b64encode(data).decode("ascii"),
    }

js = """
async () => {
  const project = "nevo-youtube-uploader";
  const files = __FILES__;
  const hashes = Object.values(files).map(f => f.md5);
  const tokenRes = await cloudflare.request({method: "GET", path: `/accounts/${accountId}/pages/projects/${project}/upload-token`});
  const jwt = typeof tokenRes.result === "string" ? tokenRes.result : tokenRes.result.jwt;
  const auth = {Authorization: "Bearer " + jwt, "Content-Type": "application/json"};
  async function assetsCall(path, body) {
    // Try the connector request first (with an explicit auth header);
    // fall back to a raw fetch carrying the JWT if that fails.
    try {
      const r = await cloudflare.request({method: "POST", path, body, headers: auth});
      return {via: "cloudflare.request", result: r.result};
    } catch (e) {
      const resp = await fetch("https://api.cloudflare.com/client/v4" + path, {method: "POST", headers: auth, body: JSON.stringify(body)});
      const j = await resp.json();
      if (!j.success) throw new Error("fetch " + path + " failed: " + JSON.stringify(j.errors));
      return {via: "fetch", result: j.result};
    }
  }
  const missingRes = await assetsCall("/pages/assets/check-missing", {hashes});
  const missing = missingRes.result;
  const toUpload = Object.entries(files).filter(([p, f]) => missing.includes(f.md5)).map(([p, f]) => ({key: f.md5, value: f.b64, base64: true, metadata: {contentType: "text/html"}}));
  let uploaded = [];
  if (toUpload.length > 0) {
    const upRes = await assetsCall("/pages/assets/upload", toUpload);
    uploaded = upRes.result;
  }
  const manifest = {};
  for (const [p, f] of Object.entries(files)) manifest[p] = f.md5;
  const form = new FormData();
  form.append("manifest", JSON.stringify(manifest));
  const depRes = await cloudflare.request({method: "POST", path: `/accounts/${accountId}/pages/projects/${project}/deployments`, body: form});
  const d = depRes.result;
  return {deployment_id: d.id, url: d.url, env: d.environment, latest_stage: d.latest_stage && d.latest_stage.name, assets_via: missingRes.via, missing_were: missing, uploaded_count: toUpload.length};
}
""".replace("__FILES__", json.dumps(files))

args = {"account_id": ACCOUNT_ID, "code": js}
Path("/tmp/pages-deploy-args.json").write_text(json.dumps(args))
print("wrote /tmp/pages-deploy-args.json")
print("files:", {k: v["md5"] for k, v in files.items()})
