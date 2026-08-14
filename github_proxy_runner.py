#!/usr/bin/env python3
"""
GitHub Action Proxy Runner
Proxies requests from the local API Hub through GitHub Actions datacenter IP.
Features special handling for OpenCode Zen API to mimic the official OpenCode desktop app:
  - HTTP/2 with connection pooling (keep-alive)
  - Official OpenCode app headers (HTTP-Referer, X-Title, X-Source, User-Agent)
  - Bearer public auth default when no key is set
  - Natural request spacing (at least 2.0s gap between requests to OpenCode)
  - Automatic 429 exponential backoff
"""

import os
import sys
import time
import threading
from flask import Flask, request, Response, jsonify

app = Flask(__name__)
START_TIME = time.time()

# Excluded headers that leak IP or break proxy framing
EXCLUDED_HEADERS = {
    "content-encoding", "content-length", "transfer-encoding", "connection",
    "host", "x-target-url", "x-opencode-pacing",
    "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-forwarded-port",
    "x-real-ip", "x-client-ip", "true-client-ip", "forwarded", "via",
    "cf-ray", "cf-connecting-ip", "cf-visitor", "cf-ipcountry", "cf-device-type",
    "cdn-loop"
}

# OpenCode official app headers
OPENCODE_APP_HEADERS = {
    "HTTP-Referer": "https://opencode.ai/",
    "X-Title": "opencode",
    "X-Source": "opencode",
    "User-Agent": "opencode/1.0",
}

# OpenCode pacing lock: at least 2.0s between requests to prevent burst 429
_opencode_runner_lock = threading.Lock()
_last_opencode_runner_time = 0.0
MIN_OPENCODE_GAP = 2.0

# HTTP/2 Client Connection Pool with keep-alive
_httpx_client = None
try:
    import httpx
    _httpx_client = httpx.Client(
        http2=True,
        timeout=httpx.Timeout(180.0, connect=30.0),
        limits=httpx.Limits(
            max_connections=20,
            max_keepalive_connections=20,
            keepalive_expiry=60.0,
        ),
        headers={"User-Agent": "opencode/1.0"},
    )
    print("[runner] HTTP/2 client initialized with connection pooling.", flush=True)
except Exception as e:
    print(f"[runner] httpx not available or HTTP/2 init failed: {e}. Falling back to requests.Session.", flush=True)
    import requests
    _requests_session = requests.Session()


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "uptime": int(time.time() - START_TIME),
        "message": "GitHub Action Proxy Runner is active",
        "http2_enabled": _httpx_client is not None
    }), 200


@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def proxy_handler(path):
    global _last_opencode_runner_time

    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    target_url = request.headers.get("X-Target-Url") or request.headers.get("x-target-url")
    if not target_url:
        return jsonify({"error": "Missing X-Target-Url header"}), 400

    is_opencode = "opencode.ai" in target_url
    pacing_hdr = request.headers.get("X-Opencode-Pacing") or request.headers.get("x-opencode-pacing") or "1"
    pacing_enabled = pacing_hdr not in ("0", "false", "False")

    # Natural pacing for OpenCode: mimic app's natural spacing to prevent 429 (if enabled)
    if is_opencode and pacing_enabled:
        with _opencode_runner_lock:
            now = time.time()
            elapsed = now - _last_opencode_runner_time
            if elapsed < MIN_OPENCODE_GAP:
                time.sleep(MIN_OPENCODE_GAP - elapsed)
            _last_opencode_runner_time = time.time()

    print(f"[runner] Proxying {request.method} -> {target_url} (is_opencode={is_opencode})", flush=True)

    fwd_headers = {}
    for k, v in request.headers.items():
        if k.lower() not in EXCLUDED_HEADERS:
            fwd_headers[k] = v

    if is_opencode:
        # Inject official OpenCode desktop app headers
        for hk, hv in OPENCODE_APP_HEADERS.items():
            fwd_headers[hk] = hv
        if not fwd_headers.get("Authorization"):
            fwd_headers["Authorization"] = "Bearer public"
    else:
        ua = fwd_headers.get("User-Agent") or fwd_headers.get("user-agent") or ""
        if not ua or "python" in ua.lower() or "axios" in ua.lower():
            fwd_headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"

    body = request.get_data()
    params = request.args

    backoff = [3, 6, 15]
    last_error = None

    for attempt in range(4):
        try:
            if _httpx_client is not None:
                resp = _httpx_client.request(
                    method=request.method,
                    url=target_url,
                    headers=fwd_headers,
                    content=body,
                    params=params,
                )
                status_code = resp.status_code
                resp_headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in EXCLUDED_HEADERS]

                if status_code == 429 and attempt < len(backoff):
                    wait = backoff[attempt]
                    print(f"[runner] 429 rate limit received, backing off {wait}s (attempt {attempt+1})", flush=True)
                    time.sleep(wait)
                    continue

                return Response(
                    resp.content,
                    status=status_code,
                    headers=resp_headers,
                    direct_passthrough=True
                )
            else:
                import requests
                upstream_resp = requests.request(
                    method=request.method,
                    url=target_url,
                    headers=fwd_headers,
                    data=body,
                    params=params,
                    allow_redirects=False,
                    stream=True,
                    timeout=180
                )
                status_code = upstream_resp.status_code

                if status_code == 429 and attempt < len(backoff):
                    wait = backoff[attempt]
                    print(f"[runner] 429 rate limit received, backing off {wait}s (attempt {attempt+1})", flush=True)
                    time.sleep(wait)
                    continue

                resp_headers = [(k, v) for k, v in upstream_resp.headers.items() if k.lower() not in EXCLUDED_HEADERS]

                def generate_chunks():
                    try:
                        for chunk in upstream_resp.iter_content(chunk_size=4096):
                            if chunk:
                                yield chunk
                    except Exception:
                        pass

                return Response(
                    generate_chunks(),
                    status=status_code,
                    headers=resp_headers,
                    direct_passthrough=True
                )

        except Exception as exc:
            last_error = exc
            print(f"[runner] Upstream error (attempt {attempt+1}): {exc}", flush=True)
            time.sleep(1.5)

    return jsonify({"error": f"Upstream proxy error after retries: {str(last_error)}"}), 502


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"[*] Starting GitHub Proxy Runner server on port {port}...", flush=True)
    app.run(host="0.0.0.0", port=port, threaded=True)
