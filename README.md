<div align="center">

# 📱 MAVEN Companion App

### Mobile-First Web Control Panel for MAVEN Hardware

<p>
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/Flask-Server-000000?style=for-the-badge&logo=flask&logoColor=white" alt="Flask" />
  <img src="https://img.shields.io/badge/aiohttp-LAN_Scanner-2C5BB4?style=for-the-badge&logo=aiohttp&logoColor=white" alt="aiohttp" />
  <img src="https://img.shields.io/badge/Gunicorn-Deploy-499848?style=for-the-badge&logo=gunicorn&logoColor=white" alt="Gunicorn" />
</p>

<p>
  <img src="https://img.shields.io/badge/discovery-254_hosts_%2F_3s-blue?style=flat-square" alt="Discovery" />
  <img src="https://img.shields.io/badge/UI-mobile_first-ff69b4?style=flat-square" alt="Mobile" />
  <img src="https://img.shields.io/badge/tests-unittest_suite-brightgreen?style=flat-square" alt="Tests" />
  <img src="https://img.shields.io/badge/health-%2Fhealth_endpoint-yellow?style=flat-square" alt="Health" />
</p>

</div>

---

## 📖 Overview

MAVEN is a local companion web app for pairing with a MAVEN hardware device on the same WiFi network. It discovers MAVEN devices on the LAN, pairs with a device in pairing mode, learns and sends TV remote IR commands, and shows camera and microphone status from companion services running on the device.

This repository contains **only the Flask companion app**. The Raspberry Pi services it talks to — `pi_server.py`, `camera_server.py`, and `microphone_server.py` — live in the [MAVEN device repository](https://github.com/MayankKonduri/MAVEN) and run separately on the hardware.

<table>
<tr>
<td width="55"><h3 align="center">🔍</h3></td>
<td><b>Zero-config discovery</b><br>Sweeps all 254 hosts on your <code>/24</code> subnet every 3 seconds. No IP entry required.</td>
</tr>
<tr>
<td width="55"><h3 align="center">🔐</h3></td>
<td><b>Server-side sessions</b><br>The paired token and IP live on the host, not the browser. Survives DHCP changes.</td>
</tr>
<tr>
<td width="55"><h3 align="center">🛰️</h3></td>
<td><b>Full proxy layer</b><br>The browser never touches the Pi directly — every call routes through Flask.</td>
</tr>
<tr>
<td width="55"><h3 align="center">📊</h3></td>
<td><b>Structured health</b><br><code>/health</code> reports per-service latency, errors, and scanner liveness.</td>
</tr>
</table>

---

## ✨ Features

- LAN discovery of MAVEN devices via `GET /api/discover` on port `5000`
- Pairing flow through `POST /api/confirm-pair`
- IR command management for power, volume, channel, and navigation buttons
- Camera status, MJPEG video, and still-frame fallback through the local Flask proxy
- Microphone status and live RMS level display
- `/health` endpoint for deployment and local diagnostics
- Server-side paired sessions with automatic IP rebinding after DHCP or router changes
- Live connection status on the home screen driven by `/health`
- Mobile-first browser UI served from the Flask application
- Structured JSON request logging with `X-Request-ID` correlation

---

## 🏗️ Architecture

MAVEN has two runtime sides: the **companion host** (your laptop or a local server) and the **hardware device** on the same LAN. The browser only ever talks to Flask; Flask does all the reaching out.

```
   ┌──────────────────────┐
   │       Browser        │   phone or desktop
   │   mobile-first UI    │   localStorage: token + IP hint
   └──────────┬───────────┘
              │ HTTP :8080
              ▼
   ┌──────────────────────────────────────────────┐
   │        Flask Companion App  (app.py)         │
   │                                              │
   │  ┌────────────────┐   ┌───────────────────┐  │
   │  │  LAN Scanner   │   │  Paired Session   │  │
   │  │  aiohttp, 3s   │──►│ token + ip + name │  │
   │  │  .1 → .254     │   │  auto-rebind      │  │
   │  └────────────────┘   └───────────────────┘  │
   │                                              │
   │  /proxy/*  ·  /health  ·  /api/devices       │
   └──────────┬───────────┬───────────┬───────────┘
              │ :5000     │ :8081     │ :8082
              ▼           ▼           ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │  MAVEN   │ │  Camera  │ │   Mic    │
        │  IR API  │ │  Service │ │  Service │
        └──────────┘ └──────────┘ └──────────┘
              └────── MAVEN Device (Pi) ──────┘
```

> [!NOTE]
> The scanner autostarts on **module import**, not just under `__main__` — so it runs under Gunicorn too. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the deeper walkthrough.

---

## 📂 Repository Layout

```text
.
├── app.py                          # Flask server, LAN scanner, proxy API, and inline UI
├── test_app.py                     # unittest suite — health, pairing, rebind, proxy auth
├── requirements.txt                # Python runtime dependencies
├── Procfile                        # Gunicorn process definition
├── models/                         # ONNX model assets kept with the app
│   ├── yolov8n.onnx
│   ├── hand_yolov8n.onnx
│   └── handpose_estimation.onnx
├── debug_camera_assistant.jpg      # camera/debug reference images
├── debug_camera_assistant_stable.jpg
└── docs/
    └── ARCHITECTURE.md             # runtime architecture and operational notes
```

---

## 📋 Requirements

- Python 3.10 or newer
- A computer on the same WiFi network as the MAVEN device
- A MAVEN/Pi device running the expected local services:

<div align="center">

| Service | Port | Provided by |
| :--- | :---: | :--- |
| MAVEN IR API | `5000` | `pi_server.py` |
| Camera service | `8081` | `camera_server.py` |
| Microphone service | `8082` | `microphone_server.py` |

</div>

**Dependencies** (`requirements.txt`): `flask` · `requests` · `aiohttp` · `gunicorn`

---

## 🚀 Local Setup

<details open>
<summary><b>Windows / PowerShell</b></summary>

<br>

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

</details>

<details>
<summary><b>macOS / Linux</b></summary>

<br>

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

</details>

Open the app on the same machine:

```text
http://localhost:8080
```

To use it from a phone, connect the phone to the same WiFi network and open:

```text
http://<this-computer-ip>:8080
```

> [!TIP]
> Find your host IP with `ipconfig` (Windows) or `ipconfig getifaddr en0` (macOS). If the phone can't reach the app, your OS firewall is almost certainly blocking inbound `8080`.

---

## 🔧 Hardware Setup Expectations

The companion app is not the firmware or Pi service bundle. Before pairing from the browser:

1. Power on the MAVEN device
2. Confirm the Pi/device is on the same WiFi network as the companion app host
3. Start the MAVEN API service on port `5000`
4. Start the camera service on port `8081` *(if camera features are needed)*
5. Start the microphone service on port `8082` *(if microphone features are needed)*
6. **Hold the MAVEN hardware button for 5 seconds** to enter pairing mode

> [!IMPORTANT]
> `pi_server.py` mints a fresh session token every time it restarts. If the device reboots, the browser's stored token goes stale and proxy calls return `403` — the UI detects this, shows "Session expired," and returns you to the scan screen.

---

## 🎛️ Remote Buttons

Thirteen buttons in four groups, matching the IR codes stored on the device.

<div align="center">

| Group | Buttons |
| :--- | :--- |
| ⏻ **Power** | `power_toggle` |
| 🔊 **Volume** | `vol_up` · `vol_down` · `mute` |
| 📺 **Channels** | `channel_up` · `channel_down` |
| 🕹️ **Navigation** | `home` · `left` · `up` · `right` · `down` · `enter` · `return` |

</div>

Each button can be **learned** (capture a pulse train from your physical remote), **tested** (fire it at the TV), or **cleared**.

---

## 🌐 API Reference

<details open>
<summary><b>App routes</b></summary>

<br>

| Method | Route | Purpose |
| :--- | :--- | :--- |
| `GET` | `/` | Mobile-first web UI |
| `GET` | `/api/devices` | Currently discovered MAVEN devices |
| `GET` | `/api/paired` | Authoritative paired IP; restores session from a token |
| `POST` | `/api/disconnect` | Clear the in-memory paired session |
| `GET` | `/health` | Structured health report |

</details>

<details>
<summary><b>Proxy routes</b></summary>

<br>

**MAVEN IR API** → `:5000`

| Method | Route | Auth |
| :--- | :--- | :---: |
| `POST` | `/proxy/confirm-pair` | unpaired OK |
| `GET` | `/proxy/codes` | unpaired OK |
| `POST` | `/proxy/learn/<name>` | paired |
| `POST` | `/proxy/clear/<name>` | paired |
| `POST` | `/proxy/send/<name>` | paired |

**Camera** → `:8081`

| Method | Route |
| :--- | :--- |
| `GET` | `/proxy/camera/status` |
| `GET` | `/proxy/camera/frame.jpg` |
| `GET` | `/proxy/camera/video` |

**Microphone** → `:8082`

| Method | Route |
| :--- | :--- |
| `GET` | `/proxy/mic/status` |
| `GET` | `/proxy/mic/level` |

</details>

---

## 🩺 Health Check

```text
GET /health
```

The response includes:

- Overall status: `healthy`, `degraded`, or `unhealthy`
- Scanner status: whether the LAN scanner thread is running and when it last succeeded
- Service checks for `camera`, `microphone`, and `ir`
- Each service status, latency in milliseconds, and nullable error

**Example:**

```json
{
  "status": "degraded",
  "scanner": {
    "status": "healthy",
    "running": true,
    "last_scan_at": 1710000000.0,
    "last_success_at": 1710000000.0,
    "error": null
  },
  "services": {
    "camera":     { "status": "healthy",   "latency_ms": 12.3,   "error": null },
    "microphone": { "status": "unhealthy", "latency_ms": 1001.8, "error": "HTTPConnectionPool timeout" },
    "ir":         { "status": "healthy",   "latency_ms": 9.4,    "error": null }
  }
}
```

<div align="center">

| Status | Meaning | HTTP |
| :--- | :--- | :---: |
| 🟢 `healthy` | All three services healthy | `200` |
| 🟡 `degraded` | At least one healthy **and** at least one unhealthy | `200` |
| 🔴 `unhealthy` | No services healthy, no target device, or scanner stopped | `503` |

</div>

Each service check uses a **1-second timeout**. The home screen polls this endpoint every 10 seconds and renders *Connected*, *Connected · some sensors offline*, or *Device unreachable*.

---

## 🧪 Running Tests

```bash
python -m unittest test_app -v
```

The suite covers health schema stability, scanner idempotency, paired-session restore, IP rebinding when the token moves, and — importantly — that `/proxy/send` uses the **server's** paired IP rather than a client-supplied query parameter.

> [!TIP]
> Tests set `MAVEN_SCANNER_AUTOSTART=0` so the background scanner doesn't fire during test runs.

---

## 🚢 Deployment

The included `Procfile` defines:

```text
web: gunicorn --workers 1 --bind 0.0.0.0:${PORT:-8080} app:app
```

Gunicorn imports `app:app`, which autostarts the LAN scanner in the same process.

> [!WARNING]
> **Use exactly one worker.** Discovery state and paired sessions are in-memory. With multiple workers, each keeps its own device list and paired session — a request landing on the wrong worker will report "no paired device" at random.

Set `MAVEN_SCANNER_AUTOSTART=0` only for tests or custom process layouts.

For local development and hardware testing:

```powershell
python app.py
```

---

## 🧯 Troubleshooting

<details>
<summary><b>No devices found</b></summary>

<br>

Confirm the host and MAVEN device are on the same subnet and that the device API is listening on port `5000`. Verify manually:

```bash
curl http://<device-ip>:5000/api/discover
```

The scanner assumes a flat `/24` network. Guest networks, VLANs, and client-isolation settings on the router will all break discovery silently.

</details>

<details>
<summary><b>Pairing fails</b></summary>

<br>

Hold the hardware button for 5 seconds, then retry **while the device is in pairing mode**. The window closes after ~15 seconds. The scan screen shows a pairing badge on devices currently accepting a pair request.

</details>

<details>
<summary><b>Camera or microphone unavailable</b></summary>

<br>

Confirm each service is reachable directly:

```bash
curl http://<device-ip>:8081/status   # camera
curl http://<device-ip>:8082/status   # microphone
```

Only one process can own the Pi camera. If `camera_server.py` is running as a service, a second manual launch fails.

</details>

<details>
<summary><b><code>/health</code> reports <code>scanner.running: false</code></b></summary>

<br>

Confirm Gunicorn is using one worker and `MAVEN_SCANNER_AUTOSTART` is not disabled.

</details>

<details>
<summary><b>Everything worked, now every action 403s</b></summary>

<br>

The device restarted and issued a new session token. Disconnect and re-pair from the scan screen.

</details>

---

## 🛠️ Development Notes

- The frontend is currently embedded in `app.py` with `render_template_string` — the file is ~73 KB, most of which is HTML/CSS/JS.
- The browser stores the MAVEN token and a reconnect hint IP in `localStorage`. The companion app stores the authoritative paired session **in memory** and rebinds the Pi IP during LAN scans.
- The Flask server proxies browser requests to the MAVEN device so the browser does not need to call the Pi services directly.
- Every request gets an `X-Request-ID` (honored from the client or generated), echoed on the response and attached to structured JSON logs.
- See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for a deeper architecture overview.

---

## ⚠️ Known Issues

> [!WARNING]
> **`NameError` in the scanner's exception handler.** In `scanner_thread()`, `now = time.time()` is assigned *inside* the `try` block after `scan_once()` returns, but the `except` block reads `now`. If the first scan raises, `now` is unbound and the handler itself throws — killing the scanner thread. Move the assignment above the `try`, or call `time.time()` directly in the handler.

> [!WARNING]
> **`NameError` in `rebind_paired_ip_if_needed()`.** `old_ip` is only assigned inside `if paired_session and paired_session["token"] == token:`, but `log_event(...)` reads it unconditionally afterward. If the session is cleared mid-rebind, the log call raises. Initialize `old_ip = current_ip` before the lock.

> [!NOTE]
> **~29 MB of unused assets.** `models/*.onnx` and the two `debug_camera_assistant*.jpg` files are never referenced anywhere in `app.py` — they're inference assets belonging to the device repo. Removing them shrinks the clone by roughly 95%.

> [!NOTE]
> **`hi.py` is an empty file** committed at the repo root. Safe to delete.

> [!NOTE]
> **`requirements.txt` has no version pins.** A future Flask or aiohttp major release can break the build with no code change on your side. Consider `pip freeze` or pinning minimums.

> [!CAUTION]
> **`/proxy/codes` accepts a caller-supplied IP when unpaired.** This is intentional for reconnect, but it means an unpaired caller can make the companion host issue requests to any address on the LAN. Fine on a trusted home network — not something to expose publicly.

---

<div align="center">

<sub>Local network only · No cloud dependencies · Companion to the <a href="https://github.com/MayankKonduri/MAVEN">MAVEN device</a></sub>

</div>
