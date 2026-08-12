import os
import sys
import time
import requests
from flask import Flask, request, Response, jsonify

app = Flask(__name__)
START_TIME = time.time()

# Exclude hop-by-hop headers and tunnel-specific headers
EXCLUDED_HEADERS = {
    "content-encoding", "content-length", "transfer-encoding", "connection",
    "host", "x-target-url", "cf-ray", "cf-connecting-ip", "cf-visitor", "cf-ipcountry"
}

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "uptime": int(time.time() - START_TIME),
        "message": "GitHub Action Proxy Runner is active"
    }), 200

@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def proxy_handler(path):
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    target_url = request.headers.get("X-Target-Url") or request.headers.get("x-target-url")
    if not target_url:
        return jsonify({"error": "Missing X-Target-Url header"}), 400

    print(f"[runner] Proxying {request.method} -> {target_url}", flush=True)

    fwd_headers = {}
    for k, v in request.headers.items():
        if k.lower() not in EXCLUDED_HEADERS:
            fwd_headers[k] = v

    body = request.get_data()
    params = request.args

    try:
        upstream_resp = requests.request(
            method=request.method,
            url=target_url,
            headers=fwd_headers,
            data=body,
            params=params,
            allow_redirects=False,
            stream=True,
            timeout=300
        )
    except Exception as exc:
        return jsonify({"error": f"Upstream proxy error: {str(exc)}"}), 502

    resp_headers = []
    for k, v in upstream_resp.headers.items():
        if k.lower() not in EXCLUDED_HEADERS:
            resp_headers.append((k, v))

    def generate_chunks():
        try:
            for chunk in upstream_resp.iter_content(chunk_size=4096):
                if chunk:
                    yield chunk
        except Exception:
            pass

    return Response(
        generate_chunks(),
        status=upstream_resp.status_code,
        headers=resp_headers,
        direct_passthrough=True
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"[*] Starting GitHub Proxy Runner server on port {port}...", flush=True)
    app.run(host="0.0.0.0", port=port, threaded=True)
