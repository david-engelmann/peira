#!/usr/bin/env python3
"""Deploy a dist directory to the peira-leaderboard Cloudflare Pages
project via the direct upload API. Usage: deploy_pages.py <dist_dir>"""
import sys, os, json, base64, io, mimetypes
sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import add_surrogate_to_request, read_json_response
import urllib.request
from blake3 import blake3

ACCOUNT_ID = os.environ["CLOUDFLARE_ACCOUNT_ID"]  # supplied by the operator environment, never stored in the repo
PROJECT = "peira-leaderboard"
DIST_DIR = os.path.abspath(sys.argv[1])

def cf_api(method, path, data=None):
    url = f"https://api.cloudflare.com/client/v4{path}"
    h = {}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    add_surrogate_to_request(req, "custom.cloudflare", allowed_hosts=["api.cloudflare.com"])
    return read_json_response(urllib.request.urlopen(req))

def pages_api(method, path, jwt, data=None):
    url = f"https://api.cloudflare.com/client/v4{path}"
    h = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    return json.loads(urllib.request.urlopen(req).read().decode())

def hash_file(content, ext):
    b64 = base64.b64encode(content).decode()
    return blake3((b64 + ext).encode()).hexdigest()[:32]

def main():
    result = cf_api("GET", f"/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT}/upload-token")
    jwt = result["result"]["jwt"]
    files, manifest = {}, {}
    for root, _, filenames in os.walk(DIST_DIR):
        for fn in filenames:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, DIST_DIR)
            content = open(full, "rb").read()
            ext = os.path.splitext(fn)[1][1:]
            h = hash_file(content, ext)
            manifest["/" + rel] = h
            files[h] = ("/" + rel, content)
    print(f"Hashed {len(files)} files from {DIST_DIR}")
    missing = pages_api("POST", "/pages/assets/check-missing", jwt, {"hashes": list(files.keys())})["result"]
    print(f"Missing: {len(missing)}")
    for h in missing:
        web_path, content = files[h]
        ctype = mimetypes.guess_type(web_path)[0] or "application/octet-stream"
        pages_api("POST", "/pages/assets/upload", jwt, [{
            "key": h, "value": base64.b64encode(content).decode(),
            "metadata": {"contentType": ctype}, "base64": True}])
        print(f"  uploaded {web_path}")
    pages_api("POST", "/pages/assets/upsert-hashes", jwt, {"hashes": list(files.keys())})
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    body = io.BytesIO()
    body.write(f"--{boundary}\r\n".encode())
    body.write(b'Content-Disposition: form-data; name="manifest"\r\n\r\n')
    body.write(json.dumps(manifest).encode())
    body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT}/deployments"
    req = urllib.request.Request(url, data=body.getvalue(), method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    add_surrogate_to_request(req, "custom.cloudflare", allowed_hosts=["api.cloudflare.com"])
    result = read_json_response(urllib.request.urlopen(req))
    if result.get("success"):
        dep = result["result"]
        print("DEPLOYED:", dep.get("url"), "id:", dep.get("id"))
    else:
        print(f"Failed: {result}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
