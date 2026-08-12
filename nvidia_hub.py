from flask import Flask, request, Response, jsonify
import requests
import threading
import json
import os
import sys
import random
import secrets
import string
import uuid
import time
import logging

class WerkzeugFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        return "/health" not in msg and "/usage" not in msg

logging.getLogger("werkzeug").addFilter(WerkzeugFilter())

app = Flask(__name__)

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.environ.get("HUB_CONFIG_PATH") or os.path.join(BASE_DIR, "config.json")
DATA_DIR = os.environ.get("HUB_DATA_DIR") or BASE_DIR

DEFAULT_PROVIDERS = {
    "nvidia": {
        "label": "NVIDIA NIM",
        "base_url": "https://integrate.api.nvidia.com",
        "keys": [],
    },
    "opencode": {
        "label": "OpenCode Zen",
        "base_url": "https://opencode.ai/zen",
        "keys": [],
    },
    "kilo": {
        "label": "Kilo Code",
        "base_url": "https://api.kilo.ai/api/gateway",
        "keys": [],
    },
}

# Providers whose free tier works with NO API key (auth header is then omitted).
KEYLESS_PROVIDERS = {"kilo"}

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}

# Exact headers never forwarded in anonymous mode (device / client identity surface)
IDENTITY_HEADERS = {
    "cookie", "cookie2", "set-cookie", "set-cookie2",
    "authorization", "proxy-authorization",
    "user-agent", "referer", "origin", "from", "dnt",
    "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-forwarded-port",
    "x-real-ip", "x-client-ip", "true-client-ip", "forwarded", "via",
    "cf-connecting-ip", "cf-ipcountry", "cf-ray", "cf-visitor", "cf-device-type",
    "fastly-client-ip", "x-cluster-client-ip", "x-original-forwarded-for",
    # Device / install / hardware identity (some clients wrongly send these)
    "x-device-id", "x-device-uuid", "x-device-token", "x-device-fingerprint",
    "x-machine-id", "x-machine-name", "x-hardware-id", "x-hardware-uuid",
    "x-mac-address", "x-mac", "mac-address", "device-mac",
    "x-serial-number", "x-board-serial", "x-system-uuid", "x-bios-uuid",
    "x-install-id", "x-installation-id", "x-instance-id", "x-node-id",
    "x-fingerprint", "x-client-fingerprint", "x-browser-fingerprint",
    "x-session-id", "x-session", "x-visitor-id", "x-anonymous-id",
    "x-user-id", "x-uid", "x-aid", "x-gid", "x-cid",
    "x-client-id", "x-client-name", "x-client-version", "x-client-info",
    "x-client-platform", "x-client-os", "x-client-arch", "x-client-locale",
    "x-app-id", "x-app-name", "x-app-version", "x-app-build", "x-app-bundle",
    "x-sdk-name", "x-sdk-version", "x-sdk-platform",
    "x-request-id", "x-correlation-id", "x-trace-id", "x-span-id",
    "x-amzn-trace-id", "x-cloud-trace-context", "traceparent", "tracestate", "baggage",
    "x-b3-traceid", "x-b3-spanid", "x-b3-parentspanid", "x-b3-sampled",
    "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
    "sec-ch-ua-full-version", "sec-ch-ua-full-version-list",
    "sec-ch-ua-platform-version", "sec-ch-ua-arch", "sec-ch-ua-bitness",
    "sec-ch-ua-model", "sec-ch-ua-wow64", "sec-ch-prefers-color-scheme",
    "sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest", "sec-fetch-user", "sec-gpc",
    "device-memory", "viewport-width", "downlink", "ect", "rtt", "save-data",
    "priority", "purpose", "x-purpose", "x-moz",
    "openai-organization", "openai-project", "openai-beta",
    "anthropic-version", "anthropic-beta", "anthropic-dangerous-direct-browser-access",
    "x-api-key", "x-title", "http-referer", "x-stainless-lang",
    "x-stainless-package-version", "x-stainless-os", "x-stainless-arch",
    "x-stainless-runtime", "x-stainless-runtime-version", "x-stainless-retry-count",
    "x-stainless-async", "x-stainless-helper-method", "x-stainless-timeout",
    "x-stainless-poll-helper", "x-stainless-raw-response",
    "x-goog-api-client", "grpc-timeout", "grpc-encoding",
    "x-ms-client-request-id", "x-ms-useragent", "x-azure-ref",
}

# Substrings in header names that mark identity-bearing client data
IDENTITY_HEADER_TOKENS = (
    "device", "machine", "hardware", "fingerprint", "install", "serial",
    "mac-address", "macaddr", "mac_address", "session", "visitor", "anonymous-id",
    "client-id", "client_id", "user-id", "user_id", "userid", "machine-id",
    "machine_id", "device-id", "device_id", "uuid", "guid", "imei", "imsi",
    "android-id", "idfa", "idfv", "gaid", "adid", "advertising", "tracking",
    "stainless", "sentry", "bugsnag", "amplitude", "segment", "mixpanel",
    "telemetry", "analytics", "correlation", "trace", "span", "baggage",
    "forwarded", "real-ip", "client-ip", "true-client", "cf-", "fastly",
    "sec-ch-", "sec-fetch", "x-app-", "x-sdk-", "x-client-", "x-device-",
    "x-machine-", "x-hardware-", "x-install-", "x-session-", "x-visitor-",
    "x-fingerprint", "x-request-id", "x-correlation", "browser-id", "canvas",
    "webgl", "timezone", "screen-", "display-", "gpu", "renderer", "vendor-id",
    "product-id", "bundle-id", "package-name", "hostname", "computer-name",
    "username", "login", "email", "phone", "wifi", "bluetooth", "ssid",
    "bssid", "latitude", "longitude", "geolocation", "locale-id",
)

# JSON body keys (any nesting) that identify a device/session/user — stripped or randomized
IDENTITY_BODY_KEYS = {
    "user", "user_id", "userid", "userId", "uid", "account_id", "accountId",
    "session", "session_id", "sessionId", "sid",
    "client_id", "clientId", "client_name", "clientName", "client_version",
    "device", "device_id", "deviceId", "device_uuid", "deviceUUID", "device_token",
    "device_fingerprint", "deviceFingerprint", "device_info", "deviceInfo",
    "machine_id", "machineId", "machine_name", "hardware_id", "hardwareId",
    "mac", "mac_address", "macAddress", "mac_addr", "bssid", "ssid",
    "serial", "serial_number", "serialNumber", "board_serial", "system_uuid",
    "bios_uuid", "motherboard_id", "disk_id", "volume_serial", "cpu_id",
    "install_id", "installation_id", "instance_id", "node_id", "host_id",
    "fingerprint", "browser_fingerprint", "canvas_fingerprint", "webgl_fingerprint",
    "audio_fingerprint", "font_fingerprint", "visitor_id", "anonymous_id",
    "distinct_id", "aid", "gid", "cid", "ga_client_id", "fbp", "fbc",
    "idfa", "idfv", "gaid", "adid", "advertising_id", "android_id", "imei", "imsi",
    "timezone", "time_zone", "tz", "locale", "language", "languages",
    "screen", "screen_resolution", "viewport", "platform", "os", "os_version",
    "arch", "architecture", "hostname", "computer_name", "username",
    "ip", "local_ip", "public_ip", "latitude", "longitude", "geo", "location",
    "metadata", "safety_identifier", "safetyIdentifier", "end_user_id",
    "endUserId", "customer_id", "customerId", "org_id", "organization_id",
    "project_id", "workspace_id", "tenant_id", "app_id", "bundle_id",
    "package_name", "sdk", "sdk_version", "app_version", "build_number",
    "trace_id", "span_id", "request_id", "correlation_id",
}

# Query-string params that should not leak device identity
IDENTITY_QUERY_KEYS = IDENTITY_BODY_KEYS | {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "msclkid", "ref", "referrer", "source",
}

# Browser TLS/HTTP2 impersonation pool (curl_cffi)
IMPERSONATE_POOL = [
    "chrome120",
    "chrome123",
    "chrome124",
    "chrome131",
    "chrome133a",
    "chrome136",
    "chrome142",
    "chrome145",
    "chrome146",
    "chrome99_android",
    "chrome131_android",
    "edge99",
    "edge101",
    "firefox133",
    "firefox135",
    "firefox144",
    "firefox147",
    "safari170",
    "safari180",
    "safari184",
    "safari260",
    "safari172_ios",
    "safari180_ios",
    "safari184_ios",
    "safari260_ios",
    "tor145",
]

ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9",
    "en-GB,en;q=0.9",
    "en-US,en;q=0.8,es;q=0.6",
    "en-US,en;q=0.9,fr;q=0.7",
    "de-DE,de;q=0.9,en;q=0.7",
    "fr-FR,fr;q=0.9,en;q=0.8",
    "es-ES,es;q=0.9,en;q=0.7",
    "pt-BR,pt;q=0.9,en;q=0.8",
    "ja-JP,ja;q=0.9,en;q=0.7",
    "ko-KR,ko;q=0.9,en;q=0.8",
    "zh-CN,zh;q=0.9,en;q=0.6",
    "nl-NL,nl;q=0.9,en;q=0.8",
    "it-IT,it;q=0.9,en;q=0.7",
    "pl-PL,pl;q=0.9,en;q=0.7",
    "sv-SE,sv;q=0.9,en;q=0.8",
]

CHROME_VERSIONS = [
    "120.0.6099.224",
    "123.0.6312.122",
    "124.0.6367.207",
    "131.0.6778.204",
    "133.0.6943.141",
    "136.0.7103.113",
    "142.0.7444.60",
    "145.0.7632.76",
    "146.0.7680.80",
]

FIREFOX_VERSIONS = ["133.0", "135.0", "144.0", "147.0"]
SAFARI_VERSIONS = ["17.0", "17.2", "18.0", "18.4", "26.0"]
EDGE_VERSIONS = ["99.0.1150.55", "101.0.1210.53", "131.0.2903.112"]

# Match User-Agent loosely to impersonate target family
UA_TEMPLATES = {
    "chrome": (
        "Mozilla/5.0 ({os}) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/{ver} Safari/537.36"
    ),
    "edge": (
        "Mozilla/5.0 ({os}) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/{ver} Safari/537.36 Edg/{edge}"
    ),
    "firefox": (
        "Mozilla/5.0 ({os}; rv:{ver}) Gecko/20100101 Firefox/{ver}"
    ),
    "safari": (
        "Mozilla/5.0 ({os}) AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/{ver} Safari/605.1.15"
    ),
}

OS_DESKTOP = [
    "Windows NT 10.0; Win64; x64",
    "Windows NT 11.0; Win64; x64",
    "Macintosh; Intel Mac OS X 10_15_7",
    "Macintosh; Intel Mac OS X 13_6_7",
    "Macintosh; Intel Mac OS X 14_5",
    "X11; Linux x86_64",
    "X11; Ubuntu; Linux x86_64",
]

OS_ANDROID = [
    "Linux; Android 13; Pixel 7",
    "Linux; Android 14; SM-S918B",
    "Linux; Android 12; Pixel 6",
    "Linux; Android 14; Pixel 8 Pro",
]

OS_IOS = [
    "iPhone; CPU iPhone OS 17_2 like Mac OS X",
    "iPhone; CPU iPhone OS 18_0 like Mac OS X",
    "iPhone; CPU iPhone OS 18_4 like Mac OS X",
    "iPad; CPU OS 17_0 like Mac OS X",
]

config_lock = threading.Lock()
counter_lock = threading.Lock()
usage_lock = threading.Lock()
key_indices = {}  # provider_id -> next key index
config_cache = None
config_mtime = 0
from requests.adapters import HTTPAdapter

def _create_session(proxy_url=None):
    sess = requests.Session()
    adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100)
    sess.mount('http://', adapter)
    sess.mount('https://', adapter)
    if proxy_url:
        sess.proxies = {"http": proxy_url, "https": proxy_url}
        sess.trust_env = False
    return sess

session = _create_session()
session_proxy_sig = None

_cf_requests = None
_cf_extra_fp_cls = None

USAGE_PATH = os.path.join(DATA_DIR, "usage_stats.json")
MAX_RECENT_EVENTS = 80
SESSION_STARTED_AT = None
usage_state = None


def _empty_bucket():
    return {
        "requests": 0,
        "success": 0,
        "errors": 0,
        "rate_limits": 0,
        "stream_requests": 0,
        "non_stream_requests": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "bytes_in": 0,
        "bytes_out": 0,
        "latency_ms_sum": 0,
        "latency_ms_count": 0,
        "by_provider": {},
        "by_model": {},
        "by_path": {},
        "by_status": {},
    }


def _empty_usage_state():
    return {
        "session": {
            "started_at": None,
            **_empty_bucket(),
            "recent": [],
        },
        "all_time": {
            "started_at": None,
            "updated_at": None,
            **_empty_bucket(),
        },
    }


def _ensure_bucket_shape(bucket):
    base = _empty_bucket()
    for k, v in base.items():
        if k not in bucket:
            bucket[k] = v if not isinstance(v, dict) else {}
        elif isinstance(v, dict) and not isinstance(bucket[k], dict):
            bucket[k] = {}
    if "recent" in bucket and not isinstance(bucket["recent"], list):
        bucket["recent"] = []
    return bucket


def _load_usage_state():
    global usage_state, SESSION_STARTED_AT
    if usage_state is not None:
        return usage_state

    state = _empty_usage_state()
    try:
        if os.path.exists(USAGE_PATH):
            with open(USAGE_PATH, "r", encoding="utf-8-sig") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                if isinstance(raw.get("all_time"), dict):
                    state["all_time"].update(raw["all_time"])
                # Do not restore previous process session as current session
                if isinstance(raw.get("session"), dict):
                    # Fold last session into all_time already stored; keep all_time only
                    pass
    except Exception:
        pass

    _ensure_bucket_shape(state["all_time"])
    _ensure_bucket_shape(state["session"])
    if not state["all_time"].get("started_at"):
        state["all_time"]["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    SESSION_STARTED_AT = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state["session"] = {
        "started_at": SESSION_STARTED_AT,
        **_empty_bucket(),
        "recent": [],
    }
    usage_state = state
    return usage_state


def _save_usage_state():
    if usage_state is None:
        return
    try:
        payload = {
            "all_time": usage_state["all_time"],
            # Persist last session snapshot so UI can show history context if needed
            "last_session": {
                k: v
                for k, v in usage_state["session"].items()
                if k != "recent"
            },
            "session_recent": usage_state["session"].get("recent", [])[:40],
        }
        usage_state["all_time"]["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        tmp = USAGE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, USAGE_PATH)
    except Exception as exc:
        print(f"[usage] Failed to save usage stats: {exc}", flush=True)


def _inc_map(m, key, amount=1):
    if not key:
        key = "unknown"
    key = str(key)[:120]
    m[key] = int(m.get(key, 0) or 0) + amount


def _apply_event_to_bucket(bucket, event):
    bucket["requests"] = int(bucket.get("requests", 0)) + 1
    if event.get("ok"):
        bucket["success"] = int(bucket.get("success", 0)) + 1
    else:
        bucket["errors"] = int(bucket.get("errors", 0)) + 1
    if event.get("status") == 429:
        bucket["rate_limits"] = int(bucket.get("rate_limits", 0)) + 1
    if event.get("stream"):
        bucket["stream_requests"] = int(bucket.get("stream_requests", 0)) + 1
    else:
        bucket["non_stream_requests"] = int(bucket.get("non_stream_requests", 0)) + 1

    pt = int(event.get("prompt_tokens") or 0)
    ct = int(event.get("completion_tokens") or 0)
    tt = int(event.get("total_tokens") or 0)
    if tt <= 0:
        tt = pt + ct
    bucket["prompt_tokens"] = int(bucket.get("prompt_tokens", 0)) + pt
    bucket["completion_tokens"] = int(bucket.get("completion_tokens", 0)) + ct
    bucket["total_tokens"] = int(bucket.get("total_tokens", 0)) + tt
    bucket["bytes_in"] = int(bucket.get("bytes_in", 0)) + int(event.get("bytes_in") or 0)
    bucket["bytes_out"] = int(bucket.get("bytes_out", 0)) + int(event.get("bytes_out") or 0)

    lat = event.get("latency_ms")
    if lat is not None:
        bucket["latency_ms_sum"] = int(bucket.get("latency_ms_sum", 0)) + int(lat)
        bucket["latency_ms_count"] = int(bucket.get("latency_ms_count", 0)) + 1

    if "by_provider" not in bucket or not isinstance(bucket["by_provider"], dict):
        bucket["by_provider"] = {}
    if "by_model" not in bucket or not isinstance(bucket["by_model"], dict):
        bucket["by_model"] = {}
    if "by_path" not in bucket or not isinstance(bucket["by_path"], dict):
        bucket["by_path"] = {}
    if "by_status" not in bucket or not isinstance(bucket["by_status"], dict):
        bucket["by_status"] = {}

    _inc_map(bucket["by_provider"], event.get("provider"))
    _inc_map(bucket["by_model"], event.get("model") or "unknown")
    _inc_map(bucket["by_path"], event.get("path") or "unknown")
    _inc_map(bucket["by_status"], str(event.get("status") or 0))

    return bucket


def _bucket_summary(bucket):
    b = _ensure_bucket_shape(dict(bucket))
    # Normalize by_provider if mixed
    by_provider = {}
    for k, v in (b.get("by_provider") or {}).items():
        if isinstance(v, dict):
            by_provider[k] = v
        else:
            by_provider[k] = {"requests": int(v or 0)}

    lat_count = int(b.get("latency_ms_count") or 0)
    avg_lat = int(b.get("latency_ms_sum") or 0) // lat_count if lat_count else 0
    return {
        "started_at": bucket.get("started_at"),
        "updated_at": bucket.get("updated_at"),
        "requests": int(b.get("requests") or 0),
        "success": int(b.get("success") or 0),
        "errors": int(b.get("errors") or 0),
        "rate_limits": int(b.get("rate_limits") or 0),
        "stream_requests": int(b.get("stream_requests") or 0),
        "non_stream_requests": int(b.get("non_stream_requests") or 0),
        "prompt_tokens": int(b.get("prompt_tokens") or 0),
        "completion_tokens": int(b.get("completion_tokens") or 0),
        "total_tokens": int(b.get("total_tokens") or 0),
        "bytes_in": int(b.get("bytes_in") or 0),
        "bytes_out": int(b.get("bytes_out") or 0),
        "avg_latency_ms": avg_lat,
        "by_provider": b.get("by_provider") or {},
        "by_model": b.get("by_model") or {},
        "by_path": b.get("by_path") or {},
        "by_status": b.get("by_status") or {},
        "recent": bucket.get("recent") if isinstance(bucket.get("recent"), list) else [],
    }


def record_usage_event(event):
    """Record one upstream API call into session + all-time stats."""
    state = _load_usage_state()
    with usage_lock:
        event = dict(event or {})
        event.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        _apply_event_to_bucket(state["session"], event)
        _apply_event_to_bucket(state["all_time"], event)

        recent = {
            "ts": event["ts"],
            "provider": event.get("provider"),
            "path": event.get("path"),
            "model": event.get("model"),
            "status": event.get("status"),
            "ok": bool(event.get("ok")),
            "stream": bool(event.get("stream")),
            "prompt_tokens": int(event.get("prompt_tokens") or 0),
            "completion_tokens": int(event.get("completion_tokens") or 0),
            "total_tokens": int(event.get("total_tokens") or 0),
            "latency_ms": event.get("latency_ms"),
            "bytes_in": int(event.get("bytes_in") or 0),
            "bytes_out": int(event.get("bytes_out") or 0),
        }
        state["session"].setdefault("recent", []).insert(0, recent)
        state["session"]["recent"] = state["session"]["recent"][:MAX_RECENT_EVENTS]
        _save_usage_state()


def get_usage_snapshot():
    state = _load_usage_state()
    with usage_lock:
        return {
            "session": _bucket_summary(state["session"]),
            "all_time": _bucket_summary(state["all_time"]),
        }


def reset_usage(scope="session"):
    state = _load_usage_state()
    with usage_lock:
        if scope == "all":
            state["all_time"] = {
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "updated_at": None,
                **_empty_bucket(),
            }
            state["session"] = {
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                **_empty_bucket(),
                "recent": [],
            }
        else:
            state["session"] = {
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                **_empty_bucket(),
                "recent": [],
            }
        _save_usage_state()
        return get_usage_snapshot()


def _parse_usage_object(usage):
    if not isinstance(usage, dict):
        return 0, 0, 0
    pt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    ct = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    tt = int(usage.get("total_tokens") or 0)
    if tt <= 0:
        tt = pt + ct
    return pt, ct, tt


def _extract_usage_from_json(data):
    if not isinstance(data, dict):
        return 0, 0, 0, None
    model = data.get("model")
    usage = data.get("usage")
    if usage is None and isinstance(data.get("response"), dict):
        usage = data["response"].get("usage")
        model = model or data["response"].get("model")
    pt, ct, tt = _parse_usage_object(usage or {})
    return pt, ct, tt, model


def _extract_usage_from_sse(raw_bytes):
    pt = ct = tt = 0
    model = None
    try:
        text = raw_bytes.decode("utf-8", errors="ignore")
    except Exception:
        return 0, 0, 0, None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
        except Exception:
            continue
        p, c, t, m = _extract_usage_from_json(obj)
        if m:
            model = m
        if p or c or t:
            pt, ct, tt = p, c, t
    return pt, ct, tt, model


def _peek_request_meta(body_bytes, content_type):
    model = None
    stream = False
    path_kind = "other"
    if body_bytes and content_type and "json" in (content_type or "").lower():
        try:
            data = json.loads(body_bytes)
            if isinstance(data, dict):
                model = data.get("model")
                stream = bool(data.get("stream"))
        except Exception:
            pass
    return model, stream


class BufferedStream:
    def __init__(self, resp):
        self.resp = resp
        self.headers = getattr(resp, "headers", {})
        self.status_code = getattr(resp, "status_code", 200)
        self.status = getattr(resp, "status", 200)
        self.iterator = None
        self.buffered_chunks = []
        self.has_content = False

        if hasattr(resp, "iter_content"):
            # Chunked framing (normal SSE) streams per network chunk even with
            # chunk_size=None. For any other framing (Content-Length or
            # connection-close delimited) http.client read(amt) blocks until
            # amt bytes or EOF — so chunk_size=None waits for the ENTIRE body
            # before the first yield. chunk_size=1 streams promptly in both
            # cases, so fall back to it whenever the response is not chunked.
            te = ""
            for hk, hv in (getattr(resp, "headers", {}) or {}).items():
                if hk.lower() == "transfer-encoding":
                    te = str(hv).lower()
                    break
            chunk_size = None if "chunked" in te else 1
            try:
                self.iterator = resp.iter_content(chunk_size=chunk_size)
            except TypeError:
                self.iterator = resp.iter_content()

    def iter_content(self, *args, **kwargs):
        return self

    def check_for_content(self):
        """
        Reads from iterator until we either find content, or the stream ends.
        Returns True if we found content, False if stream ended with no content.
        """
        if not self.iterator:
            content = getattr(self.resp, "content", b"") or b""
            if content:
                self.buffered_chunks.append(content)
                for line in content.split(b"\n"):
                    if self._line_has_content(line):
                        self.has_content = True
                        return True
            return self.has_content

        # Resumable newline scan: O(total bytes), not O(n^2) like a naive
        # line_buffer += chunk / split loop on 1-byte chunks. Important because
        # an empty (0-token) stream must be read to the end before we can
        # decide to retry, and that stream can be long.
        buf = bytearray()
        line_start = 0  # start index of the line being assembled
        scan = 0        # how much of buf has already been scanned for b"\n"
        for chunk in self.iterator:
            if not chunk:
                continue
            self.buffered_chunks.append(chunk)
            buf.extend(chunk)
            while True:
                nl = buf.find(b"\n", scan)
                if nl == -1:
                    scan = len(buf)
                    break
                line = bytes(buf[line_start:nl])
                line_start = scan = nl + 1
                if self._line_has_content(line):
                    self.has_content = True
                    return True
            # Drop decoded lines, keeping only the partial tail, to bound memory
            if line_start:
                del buf[:line_start]
                scan -= line_start
                line_start = 0

        if line_start < len(buf) and self._line_has_content(bytes(buf[line_start:])):
            self.has_content = True
            return True

        return False

    def _line_has_content(self, line_bytes):
        try:
            line = line_bytes.decode("utf-8", errors="ignore").strip()
            if line.startswith("data:"):
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    return False
                obj = json.loads(payload)
                if isinstance(obj, dict):
                    choices = obj.get("choices")
                    if isinstance(choices, list) and len(choices) > 0:
                        choice = choices[0]
                        if isinstance(choice, dict):
                            delta = choice.get("delta")
                            if isinstance(delta, dict):
                                # "The API wrote something" = ANY real output field.
                                # reasoning fields matter: reasoning models stream
                                # them for a long time before any final content, and
                                # that must count as an answer too. Kilo streams
                                # delta.reasoning / delta.reasoning_details; DeepSeek
                                # uses delta.reasoning_content. Empty deltas and
                                # role-only deltas stay "nothing written" so the
                                # 0-token retry keeps working.
                                if any(delta.get(k) for k in (
                                    "content", "reasoning", "reasoning_content",
                                    "reasoning_details", "tool_calls", "function_call",
                                )):
                                    return True
                            if choice.get("text"):
                                return True
        except Exception:
            pass
        return False

    def __iter__(self):
        if self.buffered_chunks:
            # Replay the peeked prefix as ONE chunk instead of byte-by-byte
            yield b"".join(self.buffered_chunks)
        if self.iterator:
            for chunk in self.iterator:
                if chunk:
                    yield chunk

    def close(self):
        try:
            if hasattr(self.resp, "close"):
                self.resp.close()
        except Exception:
            pass


def _check_non_stream_empty(resp):
    """
    Checks if a non-streaming response has 0 completion/output tokens.
    Returns True if empty (0 tokens), False otherwise.
    """
    try:
        content_type = str(resp.headers.get("content-type") or "").lower()
        if "json" in content_type:
            content = resp.content
            if content:
                data = json.loads(content)
                if isinstance(data, dict):
                    choices = data.get("choices")
                    if not isinstance(choices, list):
                        return False
                    if len(choices) == 0:
                        return True
                    choice = choices[0]
                    if isinstance(choice, dict):
                        msg = choice.get("message")
                        if isinstance(msg, dict):
                            # Kilo answers often carry content:"" with reasoning
                            # filled — that is NOT a 0-token response.
                            if msg.get("content") or msg.get("reasoning") or msg.get("reasoning_content") or msg.get("tool_calls") or msg.get("function_call"):
                                return False
                        text = choice.get("text")
                        if text:
                            return False
                    return True
    except Exception:
        pass
    return False




def _load_curl_cffi():
    global _cf_requests, _cf_extra_fp_cls
    if _cf_requests is not None:
        return _cf_requests
    try:
        from curl_cffi import requests as cf_requests
        from curl_cffi.requests import ExtraFingerprints

        _cf_requests = cf_requests
        _cf_extra_fp_cls = ExtraFingerprints
        return _cf_requests
    except ImportError:
        return None


import subprocess


def get_github_proxy_tunnel(cfg=None):
    """Fetch active GitHub Proxy tunnel URL from GitHub Issue #1."""
    if cfg is None:
        cfg = get_config()
    repo = cfg.get("github_repo") or "Amiro3D/api-hub"
    cached_url = cfg.get("github_proxy_url", "")
    try:
        cmd = ["gh", "issue", "view", "1", "--repo", repo, "--json", "title"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if res.returncode == 0 and res.stdout:
            data = json.loads(res.stdout)
            title = (data.get("title") or "").strip()
            if title.startswith("https://") and "trycloudflare.com" in title:
                return title
    except Exception as exc:
        print(f"[github-proxy] Error fetching tunnel URL: {exc}", flush=True)
    return cached_url


def get_github_proxy_status(cfg=None):
    """Query current status of GitHub Action Proxy runner."""
    if cfg is None:
        cfg = get_config()
    repo = cfg.get("github_repo") or "Amiro3D/api-hub"
    enabled = bool(cfg.get("github_proxy_enabled"))
    tunnel_url = get_github_proxy_tunnel(cfg)

    status = "stopped"
    if tunnel_url and tunnel_url.startswith("https://"):
        status = "running"
    else:
        try:
            cmd = ["gh", "run", "list", "--repo", repo, "--workflow", "proxy.yml", "--limit", "1", "--json", "status"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and res.stdout:
                runs = json.loads(res.stdout)
                if runs and runs[0].get("status") in ("in_progress", "queued", "requested"):
                    status = "starting"
        except Exception:
            pass

    return {
        "enabled": enabled,
        "status": status,
        "tunnel_url": tunnel_url if status == "running" else "",
        "repo": repo,
    }


def start_github_proxy_workflow(cfg=None):
    """Trigger GitHub Actions proxy workflow using gh CLI."""
    if cfg is None:
        cfg = get_config()
    repo = cfg.get("github_repo") or "Amiro3D/api-hub"
    try:
        cmd = ["gh", "workflow", "run", "proxy.yml", "--repo", repo]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        if res.returncode == 0:
            return True, "GitHub Action proxy workflow triggered successfully"
        return False, res.stderr or res.stdout or "Failed to trigger workflow"
    except Exception as exc:
        return False, str(exc)


def stop_github_proxy_workflow(cfg=None):
    """Cancel active GitHub Actions proxy workflow and set status to stopped."""
    if cfg is None:
        cfg = get_config()
    repo = cfg.get("github_repo") or "Amiro3D/api-hub"
    try:
        cmd_list = ["gh", "run", "list", "--repo", repo, "--workflow", "proxy.yml", "--json", "databaseId,status"]
        res = subprocess.run(cmd_list, capture_output=True, text=True, timeout=5)
        if res.returncode == 0 and res.stdout:
            runs = json.loads(res.stdout)
            for r in runs:
                if r.get("status") in ("in_progress", "queued", "requested"):
                    run_id = str(r.get("databaseId"))
                    subprocess.run(["gh", "run", "cancel", run_id, "--repo", repo], capture_output=True, timeout=5)
        subprocess.run(["gh", "issue", "edit", "1", "--repo", repo, "--title", "STOPPED", "--body", "Proxy stopped by user"], capture_output=True, timeout=5)
        return True, "GitHub Action proxy workflow stopped"
    except Exception as exc:
        return False, str(exc)


def normalize_config(raw):
    """Support legacy flat keys + multi-provider shape."""
    cfg = dict(raw or {})

    host = cfg.get("host", "127.0.0.1")
    port = int(cfg.get("port", 59714))
    timeout = int(cfg.get("timeout", 300))
    proxy_enabled = bool(cfg.get("proxy_enabled", False))
    proxy_type = str(cfg.get("proxy_type", "socks5")).lower()
    proxy_host = cfg.get("proxy_host", "127.0.0.1")
    proxy_port = int(cfg.get("proxy_port", 1080))
    anonymous_enabled = bool(cfg.get("anonymous_enabled", False))
    github_proxy_enabled = bool(cfg.get("github_proxy_enabled", False))
    github_repo = str(cfg.get("github_repo") or "Amiro3D/api-hub").strip()
    github_proxy_url = str(cfg.get("github_proxy_url") or "").strip()
    github_proxy_status = str(cfg.get("github_proxy_status") or "stopped").strip()

    providers = {}
    raw_providers = cfg.get("providers")

    if isinstance(raw_providers, dict) and raw_providers:
        for pid, pdata in raw_providers.items():
            if not isinstance(pdata, dict):
                continue
            defaults = DEFAULT_PROVIDERS.get(pid, {})
            base = pdata.get("base_url") or pdata.get("nim_base") or defaults.get("base_url", "")
            base = str(base).rstrip("/")
            if base.lower().endswith("/v1"):
                base = base[:-3].rstrip("/")
            providers[pid] = {
                "label": pdata.get("label") or defaults.get("label") or pid,
                "base_url": base,
                "keys": [k for k in (pdata.get("keys") or []) if k],
            }
    else:
        keys = [k for k in (cfg.get("keys") or []) if k]
        base = cfg.get("nim_base") or DEFAULT_PROVIDERS["nvidia"]["base_url"]
        base = str(base).rstrip("/")
        if base.lower().endswith("/v1"):
            base = base[:-3].rstrip("/")
        providers["nvidia"] = {
            "label": "NVIDIA NIM",
            "base_url": base,
            "keys": keys,
        }
        providers["opencode"] = {
            "label": "OpenCode Zen",
            "base_url": DEFAULT_PROVIDERS["opencode"]["base_url"],
            "keys": [],
        }

    for pid, defaults in DEFAULT_PROVIDERS.items():
        if pid not in providers:
            providers[pid] = {
                "label": defaults["label"],
                "base_url": defaults["base_url"],
                "keys": [],
            }

    default_provider = cfg.get("default_provider") or "nvidia"
    if default_provider not in providers:
        default_provider = next(iter(providers.keys()))

    return {
        "default_provider": default_provider,
        "providers": providers,
        "host": host,
        "port": port,
        "timeout": timeout,
        "proxy_enabled": proxy_enabled,
        "proxy_type": proxy_type,
        "proxy_host": proxy_host,
        "proxy_port": proxy_port,
        "anonymous_enabled": anonymous_enabled,
        "github_proxy_enabled": github_proxy_enabled,
        "github_repo": github_repo,
        "github_proxy_url": github_proxy_url,
        "github_proxy_status": github_proxy_status,
    }


def load_config_from_disk():
    with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
        return normalize_config(json.load(f))


def get_config(force=False):
    global config_cache, config_mtime, session_proxy_sig, session
    try:
        mtime = os.path.getmtime(CONFIG_PATH)
    except OSError:
        mtime = 0

    with config_lock:
        if force or config_cache is None or mtime != config_mtime:
            config_cache = load_config_from_disk()
            config_mtime = mtime

            proxy_sig = (
                config_cache["proxy_enabled"],
                config_cache["proxy_type"],
                config_cache["proxy_host"],
                config_cache["proxy_port"],
            )
            if proxy_sig != session_proxy_sig:
                proxy_url = None
                if config_cache["proxy_enabled"]:
                    scheme = (
                        "socks5h"
                        if config_cache["proxy_type"] == "socks5"
                        else config_cache["proxy_type"]
                    )
                    proxy_url = f"{scheme}://{config_cache['proxy_host']}:{config_cache['proxy_port']}"
                session = _create_session(proxy_url)
                session_proxy_sig = proxy_sig

            for pid in config_cache["providers"]:
                if pid not in key_indices:
                    key_indices[pid] = 0

        return config_cache


def next_key(provider_id, keys):
    if not keys:
        return None, None
    with counter_lock:
        idx = key_indices.get(provider_id, 0) % len(keys)
        key = keys[idx]
        key_indices[provider_id] = (idx + 1) % len(keys)
        return key, idx


def _is_identity_header_name(name):
    kl = str(name).lower().strip()
    if kl in HOP_BY_HOP or kl in IDENTITY_HEADERS:
        return True
    # Keep only essential API content headers from client
    if kl in ("content-type", "accept", "accept-encoding"):
        return False
    for token in IDENTITY_HEADER_TOKENS:
        if token in kl:
            return True
    return False


def _is_identity_key(key):
    k = str(key)
    kl = k.lower()
    if k in IDENTITY_BODY_KEYS or kl in IDENTITY_BODY_KEYS:
        return True
    # Fuzzy match nested identity fields
    for token in (
        "device", "machine", "hardware", "fingerprint", "mac_addr", "mac-addr",
        "serial", "install_id", "session_id", "visitor", "advertising",
        "android_id", "imei", "idfa", "idfv", "hostname", "computer",
        "motherboard", "bios", "volume_serial", "cpu_id", "disk_id",
        "latitude", "longitude", "geolocation", "timezone", "screen_res",
        "canvas", "webgl", "audio_fp", "local_ip", "client_ip",
    ):
        if token in kl:
            return True
    return False


def _scrub_json_value(value, depth=0):
    """Recursively strip/replace device & session identity from JSON payloads."""
    if depth > 12:
        return value
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if _is_identity_key(k):
                continue
            if k in ("extra_body", "stream_options", "service_tier"):
                continue
            out[k] = _scrub_json_value(v, depth + 1)
        return out
    if isinstance(value, list):
        return [_scrub_json_value(v, depth + 1) for v in value]
    return value


def sanitize_body(body, content_type, anonymous=False):
    if not body or not content_type or "json" not in content_type.lower():
        return body
    try:
        data = json.loads(body)
        data.pop("extra_body", None)
        data.pop("stream_options", None)
        data.pop("service_tier", None)
        if anonymous:
            data = _scrub_json_value(data)
        return json.dumps(data, separators=(",", ":")).encode("utf-8")
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return body


def sanitize_params(params, anonymous=False):
    """Drop identity-bearing query params from the client request."""
    if not anonymous or params is None:
        return params
    clean = []
    try:
        if hasattr(params, "lists"):
            # Werkzeug MultiDict
            for k, values in params.lists():
                if _is_identity_key(k) or str(k).lower() in IDENTITY_QUERY_KEYS:
                    continue
                for v in values:
                    clean.append((k, v))
        elif hasattr(params, "items"):
            for k, v in params.items():
                if _is_identity_key(k) or str(k).lower() in IDENTITY_QUERY_KEYS:
                    continue
                clean.append((k, v))
        else:
            return params
    except Exception:
        return params
    return clean


def generate_stream_chunks(resp, usage_ctx=None):
    collected = bytearray()
    bytes_out = 0
    try:
        iterator = None
        if hasattr(resp, "iter_content"):
            try:
                iterator = resp.iter_content(chunk_size=None)
            except TypeError:
                iterator = resp.iter_content()
        if iterator is not None:
            for chunk in iterator:
                if chunk:
                    bytes_out += len(chunk)
                    if usage_ctx is not None and len(collected) < 2_000_000:
                        collected.extend(chunk)
                    yield chunk
        else:
            content = getattr(resp, "content", b"") or b""
            if content:
                bytes_out += len(content)
                if usage_ctx is not None:
                    collected.extend(content)
                yield content
    except Exception as e:
        yield f'data: {{"error": "upstream connection error: {str(e)}"}}\n\n'.encode("utf-8")
    finally:
        if usage_ctx is not None:
            pt, ct, tt, model = _extract_usage_from_sse(bytes(collected))
            if model:
                usage_ctx["model"] = model
            usage_ctx["prompt_tokens"] = pt
            usage_ctx["completion_tokens"] = ct
            usage_ctx["total_tokens"] = tt
            usage_ctx["bytes_out"] = bytes_out
            usage_ctx["latency_ms"] = int((time.time() - usage_ctx.get("t0", time.time())) * 1000)
            usage_ctx["ok"] = 200 <= int(usage_ctx.get("status") or 0) < 400
            try:
                record_usage_event(usage_ctx)
            except Exception:
                pass
        try:
            resp.close()
        except Exception:
            pass


def _proxy_url(cfg):
    if not cfg.get("proxy_enabled"):
        return None
    scheme = "socks5h" if cfg.get("proxy_type") == "socks5" else cfg.get("proxy_type", "http")
    return f"{scheme}://{cfg['proxy_host']}:{cfg['proxy_port']}"


def _impersonate_family(name):
    n = name.lower()
    if "firefox" in n or n.startswith("tor"):
        return "firefox"
    if "safari" in n:
        return "safari"
    if "edge" in n:
        return "edge"
    return "chrome"


def _random_token(n=16):
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def _random_mac():
    """Synthetic MAC — never your real one; randomized every request if ever needed."""
    return ":".join(f"{secrets.randbelow(256):02x}" for _ in range(6))


def _random_uuid():
    return str(uuid.uuid4())


def _shuffle_header_order(headers):
    items = list(headers.items())
    random.shuffle(items)
    return dict(items)


def build_anonymous_identity():
    """
    Brand-new network + client persona per request.

    Note: real MAC / motherboard serials never travel over normal HTTPS APIs.
    Any client that embeds them in headers/body/query is stripped; we never
    forward your real device identifiers.
    """
    impersonate = random.choice(IMPERSONATE_POOL)
    family = _impersonate_family(impersonate)
    mobile = "android" in impersonate or "ios" in impersonate

    if "android" in impersonate:
        os_str = random.choice(OS_ANDROID)
        platform = '"Android"'
        mobile_token = "?1"
        platform_version = f'"{random.randint(12, 15)}.0.0"'
        arch = random.choice(['"arm"', '"arm64"'])
    elif "ios" in impersonate:
        os_str = random.choice(OS_IOS)
        platform = '"iOS"'
        mobile_token = "?1"
        platform_version = f'"{random.choice(["17.0", "17.2", "18.0", "18.4"])}"'
        arch = '"arm64"'
    else:
        os_str = random.choice(OS_DESKTOP)
        if "Windows" in os_str:
            platform = '"Windows"'
            platform_version = f'"{random.choice(["10.0.0", "15.0.0"])}"'
        elif "Mac" in os_str:
            platform = '"macOS"'
            platform_version = f'"{random.choice(["13.6.7", "14.5.0", "15.0.0"])}"'
        else:
            platform = '"Linux"'
            platform_version = f'"{random.choice(["6.5.0", "6.8.0"])}"'
        mobile_token = "?0"
        arch = random.choice(['"x86"', '"x86_64"'])

    headers = {
        "Accept": random.choice([
            "application/json, text/event-stream, text/plain, */*",
            "application/json, text/plain, */*",
            "*/*",
            "application/json",
        ]),
        "Accept-Language": random.choice(ACCEPT_LANGUAGES),
        "Accept-Encoding": random.choice(
            ["gzip, deflate, br", "gzip, deflate, br, zstd", "gzip, deflate", "br, gzip, deflate"]
        ),
        "Cache-Control": random.choice(["no-cache", "no-store", "max-age=0", "no-cache, no-store"]),
        "Pragma": "no-cache",
    }

    if family in ("chrome", "edge"):
        ver = random.choice(CHROME_VERSIONS)
        major = ver.split(".")[0]
        if family == "edge":
            edge_ver = random.choice(EDGE_VERSIONS)
            headers["User-Agent"] = UA_TEMPLATES["edge"].format(
                os=os_str, ver=ver, edge=edge_ver
            )
            brand = (
                f'"Microsoft Edge";v="{edge_ver.split(".")[0]}", '
                f'"Chromium";v="{major}", "Not_A Brand";v="{random.choice(["8", "24", "99"])}"'
            )
        else:
            headers["User-Agent"] = UA_TEMPLATES["chrome"].format(os=os_str, ver=ver)
            brand = (
                f'"Google Chrome";v="{major}", "Chromium";v="{major}", '
                f'"Not_A Brand";v="{random.choice(["8", "24", "99"])}"'
            )
        headers["sec-ch-ua"] = brand
        headers["sec-ch-ua-mobile"] = mobile_token
        headers["sec-ch-ua-platform"] = platform
        if random.random() < 0.55:
            headers["sec-ch-ua-full-version"] = f'"{ver}"'
            headers["sec-ch-ua-platform-version"] = platform_version
            headers["sec-ch-ua-arch"] = arch
            headers["sec-ch-ua-bitness"] = random.choice(['"64"', '"32"'])
            if mobile:
                headers["sec-ch-ua-model"] = f'"{_random_token(6)}"'
        headers["sec-fetch-site"] = random.choice(["none", "same-site", "cross-site"])
        headers["sec-fetch-mode"] = random.choice(["cors", "navigate", "no-cors"])
        headers["sec-fetch-dest"] = random.choice(["empty", "document"])
    elif family == "firefox":
        ver = random.choice(FIREFOX_VERSIONS)
        headers["User-Agent"] = UA_TEMPLATES["firefox"].format(os=os_str, ver=ver)
        if random.random() < 0.5:
            headers["Upgrade-Insecure-Requests"] = "1"
        if random.random() < 0.5:
            headers["TE"] = "trailers"
    else:
        ver = random.choice(SAFARI_VERSIONS)
        headers["User-Agent"] = UA_TEMPLATES["safari"].format(os=os_str, ver=ver)

    # One-time random request id — never reused across requests
    headers["X-Request-Id"] = _random_uuid()

    # Optional synthetic client label (randomized, not your real app identity)
    if random.random() < 0.4:
        client_names = [
            "openai-python", "openai-node", "langchain", "litellm",
            "curl", "postman", "insomnia", "httpx", "axios", "undici",
            "node-fetch", "got", "ky", "restsharp",
        ]
        headers["X-Title"] = (
            f"{random.choice(client_names)}/"
            f"{random.randint(1, 9)}.{random.randint(0, 30)}.{random.randint(0, 50)}"
        )

    # Occasionally add fully synthetic (fake) device-ish noise so no two
    # requests share a stable hardware fingerprint if a backend inspects them.
    # Values are random garbage — never derived from the real host.
    if random.random() < 0.25:
        headers["X-Device-Id"] = _random_uuid()
    if random.random() < 0.12:
        headers["X-Machine-Id"] = secrets.token_hex(16)
    if random.random() < 0.08:
        headers["X-Install-Id"] = _random_uuid()

    headers = _shuffle_header_order(headers)

    extra_fp = None
    if _cf_extra_fp_cls is not None:
        try:
            extra_fp = _cf_extra_fp_cls(
                tls_grease=random.choice([True, False]),
                tls_permute_extensions=True if random.random() < 0.7 else False,
                tls_cert_compression=random.choice(["zlib", "brotli"]),
                http2_stream_weight=random.choice([16, 32, 64, 128, 220, 256]),
                http2_stream_exclusive=random.choice([0, 1]),
                http2_no_priority=random.choice([True, False]),
            )
        except Exception:
            try:
                extra_fp = _cf_extra_fp_cls(
                    tls_grease=random.choice([True, False]),
                    tls_permute_extensions=random.choice([True, False]),
                    tls_cert_compression=random.choice(["zlib", "brotli"]),
                    http2_stream_weight=random.choice([16, 32, 64, 128, 256]),
                    http2_stream_exclusive=random.choice([0, 1]),
                )
            except Exception:
                extra_fp = None

    # Prefer HTTP/2 TLS; occasionally HTTP/1.1 for fingerprint diversity
    http_version = None
    if random.random() < 0.18:
        http_version = "v1"
    else:
        http_version = random.choice(["v2", "v2tls", None])

    return {
        "impersonate": impersonate,
        "headers": headers,
        "extra_fp": extra_fp,
        "family": family,
        "mobile": mobile,
        "http_version": http_version,
        "synthetic_mac": _random_mac(),  # not sent unless backend expects; audit only
        "persona_id": _random_uuid(),
    }


def scrub_client_headers(incoming):
    """Drop hop-by-hop + any device/client identity headers from the local client."""
    clean = {}
    for k, v in incoming.items():
        if _is_identity_header_name(k):
            continue
        clean[k] = v
    return clean


def do_upstream_request(cfg, method, url, headers, body, params, anonymous, identity=None):
    """Perform one upstream call. Anonymous uses curl_cffi with rotated TLS fingerprint."""
    proxy = _proxy_url(cfg)
    timeout = cfg["timeout"]

    gh_proxy_active = bool(cfg.get("github_proxy_enabled"))
    if gh_proxy_active:
        gh_tunnel = get_github_proxy_tunnel(cfg)
        if gh_tunnel:
            headers["X-Target-Url"] = url
            url = gh_tunnel

    if anonymous:
        # Tiny random jitter so request cadence is not a stable device signature
        try:
            import time as _time
            _time.sleep(random.uniform(0.0, 0.045))
        except Exception:
            pass

        cf = _load_curl_cffi()
        if cf is None:
            sess = requests.Session()
            sess.trust_env = False
            sess.cookies.clear()
            if proxy:
                sess.proxies = {"http": proxy, "https": proxy}
            return sess.request(
                method=method,
                url=url,
                headers=headers,
                data=body,
                params=params,
                cookies={},
                allow_redirects=False,
                timeout=timeout,
                stream=True,
            )

        kwargs = {
            "method": method,
            "url": url,
            "headers": headers,
            "data": body,
            "params": params,
            "timeout": timeout,
            "allow_redirects": False,
            "stream": True,
            "impersonate": identity["impersonate"] if identity else random.choice(IMPERSONATE_POOL),
            "default_headers": False,
            "discard_cookies": True,
            "verify": True,
        }
        if proxy:
            kwargs["proxy"] = proxy
        if identity and identity.get("extra_fp") is not None:
            kwargs["extra_fp"] = identity["extra_fp"]
        if identity and identity.get("http_version"):
            kwargs["http_version"] = identity["http_version"]

        try:
            return cf.request(**kwargs)
        except TypeError:
            kwargs.pop("extra_fp", None)
            kwargs.pop("discard_cookies", None)
            kwargs.pop("http_version", None)
            return cf.request(**kwargs)
        except Exception:
            s = cf.Session()
            try:
                return s.request(**kwargs)
            except TypeError:
                kwargs.pop("extra_fp", None)
                kwargs.pop("discard_cookies", None)
                kwargs.pop("http_version", None)
                return s.request(**kwargs)

    return session.request(
        method=method,
        url=url,
        headers=headers,
        data=body,
        params=params,
        cookies=request.cookies if not anonymous else {},
        allow_redirects=False,
        timeout=timeout,
        stream=True,
    )


def proxy_request(provider_id, path):
    cfg = get_config()
    providers = cfg["providers"]
    anonymous = bool(cfg.get("anonymous_enabled")) and provider_id == "opencode"
    t0 = time.time()
    raw_body = request.get_data()
    req_model, req_stream = _peek_request_meta(raw_body, request.content_type)

    if provider_id not in providers:
        return jsonify({"error": f"Unknown provider: {provider_id}"}), 404

    provider = providers[provider_id]
    keys = provider.get("keys") or []
    base = provider.get("base_url", "").rstrip("/")

    if not keys and provider_id not in KEYLESS_PROVIDERS:
        return jsonify({
            "error": f"No API keys configured for provider '{provider_id}'",
            "provider": provider_id,
        }), 503

    if not base:
        return jsonify({
            "error": f"No base_url configured for provider '{provider_id}'",
            "provider": provider_id,
        }), 503

    url = f"{base}/v1/{path}"
    body = sanitize_body(raw_body, request.content_type, anonymous=anonymous)
    # Prefer usage in streams when provider supports it (safe no-op if ignored)
    if req_stream and body and request.content_type and "json" in request.content_type.lower():
        try:
            data = json.loads(body)
            if isinstance(data, dict) and data.get("stream"):
                so = data.get("stream_options")
                if not isinstance(so, dict):
                    so = {}
                so = dict(so)
                so["include_usage"] = True
                data["stream_options"] = so
                body = json.dumps(data).encode("utf-8")
        except Exception:
            pass
    params = sanitize_params(request.args, anonymous=anonymous)
    bytes_in = len(body or b"")

    last_resp = None
    last_error = None
    last_identity = None
    tried = 0
    rate_limited = 0

    # Keyless providers (e.g. kilo free tier) get a single anonymous attempt
    # instead of a per-key rotation loop.
    attempts = list(keys) if keys else [None]

    while tried < len(attempts):
        if keys:
            key, _idx = next_key(provider_id, keys)
        else:
            key, _idx = None, -1

        if anonymous:
            identity = build_anonymous_identity()
            last_identity = identity
            # Start from synthetic persona only — never merge local client identity
            fwd_headers = dict(identity["headers"])
            # Keep content-type only (API JSON correctness). Never cookies / device headers.
            ct = request.headers.get("Content-Type") or request.headers.get("content-type")
            if ct and "boundary=" not in ct.lower():
                # Normalize content-type; drop charset quirks that fingerprint clients
                if "json" in ct.lower():
                    fwd_headers["Content-Type"] = "application/json"
                else:
                    fwd_headers["Content-Type"] = ct.split(";")[0].strip()
            elif ct:
                fwd_headers["Content-Type"] = ct
            if body:
                fwd_headers["Content-Length"] = str(len(body))
        else:
            identity = None
            fwd_headers = {k: v for k, v in request.headers if k.lower() not in HOP_BY_HOP}

        if key:
            fwd_headers["Authorization"] = f"Bearer {key}"
        elif "Authorization" in fwd_headers:
            # Keyless provider: never send auth (client headers are scrubbed anyway)
            fwd_headers.pop("Authorization", None)

        try:
            resp = do_upstream_request(
                cfg=cfg,
                method=request.method,
                url=url,
                headers=fwd_headers,
                body=body,
                params=params,
                anonymous=anonymous,
                identity=identity,
            )
        except Exception as e:
            last_error = e
            if last_resp is not None:
                try:
                    last_resp.close()
                except Exception:
                    pass
            tried += 1
            continue

        last_resp = resp
        status = getattr(resp, "status_code", None) or getattr(resp, "status", 0)

        if status == 429:
            rate_limited += 1
            tried += 1
            continue

        if status == 200 and "completions" in path:
            is_empty = False
            content_type = ""
            raw_headers = getattr(resp, "headers", {}) or {}
            for hk, hv in raw_headers.items():
                if hk.lower() == "content-type":
                    content_type = str(hv).lower()
                    break

            is_stream = req_stream or content_type.startswith("text/event-stream")

            if is_stream:
                buffered_stream = BufferedStream(resp)
                has_content = buffered_stream.check_for_content()
                if not has_content:
                    is_empty = True
                else:
                    resp = buffered_stream
                    last_resp = buffered_stream
            else:
                if _check_non_stream_empty(resp):
                    is_empty = True

            if is_empty:
                print(f"[proxy] Warning: Received empty response (0 tokens) with status 200 from key index {_idx}. Retrying next key...", flush=True)
                try:
                    if hasattr(resp, "close"):
                        resp.close()
                except Exception:
                    pass
                tried += 1
                last_resp = None
                last_error = "Empty response (0 tokens) from upstream"
                continue

        break

    if last_resp is None:
        try:
            record_usage_event({
                "provider": provider_id,
                "path": path,
                "model": req_model,
                "status": 502,
                "ok": False,
                "stream": req_stream,
                "bytes_in": bytes_in,
                "bytes_out": 0,
                "latency_ms": int((time.time() - t0) * 1000),
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            })
        except Exception:
            pass
        return jsonify({
            "error": f"All keys failed for provider '{provider_id}'",
            "detail": str(last_error) if last_error else "unknown",
            "provider": provider_id,
        }), 502

    excluded = {
        "content-encoding",
        "content-length",
        "transfer-encoding",
        "connection",
        "set-cookie",
        "set-cookie2",
    }
    raw_headers = getattr(last_resp, "headers", {}) or {}
    response_headers = {}
    for k, v in raw_headers.items():
        if k.lower() in excluded:
            continue
        response_headers[k] = v

    response_headers["X-Hub-Provider"] = provider_id
    if anonymous and last_identity:
        response_headers["X-Hub-Anonymous"] = "1"
        response_headers["X-Hub-Fingerprint"] = last_identity["impersonate"]
        response_headers["X-Hub-Persona"] = last_identity.get("persona_id", "")[:8]

    status = getattr(last_resp, "status_code", None) or getattr(last_resp, "status", 200)
    content_type = ""
    for hk, hv in raw_headers.items():
        if hk.lower() == "content-type":
            content_type = str(hv).lower()
            break

    usage_base = {
        "provider": provider_id,
        "path": path,
        "model": req_model,
        "status": status,
        "stream": req_stream or content_type.startswith("text/event-stream"),
        "bytes_in": bytes_in,
        "t0": t0,
    }

    if content_type.startswith("text/event-stream"):
        return Response(
            generate_stream_chunks(last_resp, usage_ctx=usage_base),
            status=status,
            headers=response_headers,
            direct_passthrough=True,
        )

    content = getattr(last_resp, "content", b"") or b""
    pt = ct = tt = 0
    model = req_model
    try:
        if content and "json" in content_type:
            data = json.loads(content)
            pt, ct, tt, m = _extract_usage_from_json(data)
            if m:
                model = m
    except Exception:
        pass

    try:
        record_usage_event({
            **usage_base,
            "model": model,
            "ok": 200 <= int(status) < 400,
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_tokens": tt,
            "bytes_out": len(content),
            "latency_ms": int((time.time() - t0) * 1000),
        })
    except Exception:
        pass

    return Response(content, status=status, headers=response_headers)


@app.route("/v1/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def proxy_default(path):
    cfg = get_config()
    return proxy_request(cfg["default_provider"], path)


@app.route("/<provider_id>/v1/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def proxy_named(provider_id, path):
    return proxy_request(provider_id, path)


@app.route("/health", methods=["GET"])
def health():
    cfg = get_config()
    providers_info = {}
    for pid, p in cfg["providers"].items():
        n = len(p.get("keys") or [])
        next_idx = 0
        if n:
            with counter_lock:
                next_idx = key_indices.get(pid, 0) % n
        providers_info[pid] = {
            "label": p.get("label", pid),
            "base_url": p.get("base_url"),
            "keys_loaded": n,
            "next_key_index": next_idx,
        }

    default = cfg["default_provider"]
    default_info = providers_info.get(default, {})
    cf_ok = _load_curl_cffi() is not None
    usage = get_usage_snapshot()

    return {
        "status": "ok",
        "default_provider": default,
        "keys_loaded": default_info.get("keys_loaded", 0),
        "next_key_index": default_info.get("next_key_index", 0),
        "providers": providers_info,
        "anonymous_enabled": bool(cfg.get("anonymous_enabled")),
        "anonymous_tls": "curl_cffi" if cf_ok else "fallback-headers-only",
        "usage": {
            "session_requests": usage["session"]["requests"],
            "session_tokens": usage["session"]["total_tokens"],
            "all_time_requests": usage["all_time"]["requests"],
            "all_time_tokens": usage["all_time"]["total_tokens"],
        },
    }


@app.route("/usage", methods=["GET"])
def usage_get():
    return get_usage_snapshot()


@app.route("/usage/reset", methods=["POST"])
def usage_reset():
    scope = "session"
    try:
        data = request.get_json(silent=True) or {}
        scope = (data.get("scope") or request.args.get("scope") or "session").lower()
    except Exception:
        scope = (request.args.get("scope") or "session").lower()
    if scope not in ("session", "all"):
        scope = "session"
    return reset_usage(scope)


@app.route("/github-proxy/status", methods=["GET"])
def github_proxy_status_route():
    cfg = get_config()
    st = get_github_proxy_status(cfg)
    return jsonify(st)


@app.route("/github-proxy/start", methods=["POST"])
def github_proxy_start_route():
    cfg = get_config()
    ok, msg = start_github_proxy_workflow(cfg)
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 500)


@app.route("/github-proxy/stop", methods=["POST"])
def github_proxy_stop_route():
    cfg = get_config()
    ok, msg = stop_github_proxy_workflow(cfg)
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 500)


@app.route("/", methods=["GET"])
def root():
    cfg = get_config()
    host = cfg["host"] if cfg["host"] != "0.0.0.0" else "127.0.0.1"
    port = cfg["port"]
    return {
        "name": "API Hub",
        "default_provider": cfg["default_provider"],
        "anonymous_enabled": bool(cfg.get("anonymous_enabled")),
        "endpoints": {
            "default": f"http://{host}:{port}/v1",
            **{
                pid: f"http://{host}:{port}/{pid}/v1"
                for pid in cfg["providers"]
            },
        },
        "health": f"http://{host}:{port}/health",
    }


if __name__ == "__main__":
    boot = get_config(force=True)
    cf_ok = _load_curl_cffi() is not None
    print(
        f"API Hub starting on {boot['host']}:{boot['port']} "
        f"(default={boot['default_provider']}, "
        f"providers={list(boot['providers'].keys())}, "
        f"anonymous={boot.get('anonymous_enabled')}, "
        f"tls={'curl_cffi' if cf_ok else 'fallback'})"
    )
    for pid, p in boot["providers"].items():
        print(f"  [{pid}] {p['base_url']}/v1  keys={len(p.get('keys') or [])}")
    if boot.get("anonymous_enabled") and not cf_ok:
        print(
            "WARNING: anonymous mode is ON but curl_cffi is not installed. "
            "Install with: pip install curl_cffi  (TLS fingerprint rotation requires it)"
        )
    app.run(host=boot["host"], port=boot["port"], threaded=True)
