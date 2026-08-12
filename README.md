# NVIDIA Hub — Premium Desktop Control Center

Ultra-premium Electron desktop app for managing your local **NVIDIA NIM API proxy hub**.

## Features

- **Dark** & **Premium** themes with glass panels, ambient glow, and refined chrome
- **NVIDIA NIM** + **OpenCode Zen** multi-provider proxy (separate key pools)
- Start / stop / restart the Flask proxy from the UI
- Live health monitoring and activity feed
- API key pool management (add, bulk import, reveal, copy, remove)
- **Anonymous mode** — per-request TLS fingerprint (JA3/HTTP2), User-Agent, header, and cookie rotation via `curl_cffi` (IP unchanged; use Proxy for that)
- Server settings (host, port, timeout, base URLs, default provider)
- SOCKS5 / HTTP proxy configuration
- Process logs console
- Frameless custom title bar

## Requirements

- **Node.js** 18+ (for Electron)
- **Python** 3.10+ with packages from `requirements.txt`

```bash
pip install -r requirements.txt
npm install
```

## Run

```bash
npm start
```

Or double-click **Nvidia Hub.bat**.

## Endpoints

When the hub is running:

| Path | Target |
|------|--------|
| `http://127.0.0.1:59714/v1` | Default provider |
| `http://127.0.0.1:59714/nvidia/v1` | NVIDIA NIM |
| `http://127.0.0.1:59714/opencode/v1` | OpenCode Zen |

Any Bearer token is accepted — the hub injects rotating keys from that provider’s pool.

## Anonymous mode

Enable under **Settings → Anonymous mode**. Each upstream request then:

1. Picks a random browser TLS profile (Chrome / Firefox / Safari / Edge / mobile)
2. Randomizes User-Agent, Accept-Language, sec-ch-ua, and related headers
3. Strips cookies and client identity headers (no session reuse)
4. Scrubs identity fields from JSON bodies when present

Requires `curl_cffi` (`pip install -r requirements.txt`). IP is **not** rotated — use the Proxy page for that.

## Config

Settings are stored in `config.json` next to the app. Prefer editing them through the UI.
