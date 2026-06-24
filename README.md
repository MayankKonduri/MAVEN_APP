# MAVEN Companion App

MAVEN is a local companion web app for pairing with a MAVEN hardware device on the same WiFi network. It discovers MAVEN devices on the LAN, pairs with a device in pairing mode, learns and sends TV remote IR commands, and shows camera and microphone status from companion services running on the device.

The current repository contains the Flask companion app and static model/debug assets. The Raspberry Pi services referenced by the app, including `camera_server.py`, `microphone_server.py`, and the MAVEN device API, are expected to run separately on the hardware.

## Features

- LAN discovery of MAVEN devices via `GET /api/discover` on port `5000`.
- Pairing flow through `POST /api/confirm-pair`.
- IR command management for power, volume, channel, and navigation buttons.
- Camera status, MJPEG video, and still-frame fallback through the local Flask proxy.
- Microphone status and live RMS level display.
- `/health` endpoint for deployment and local diagnostics.
- Server-side paired sessions with automatic IP rebinding after DHCP or router changes.
- Live connection status on the home screen driven by `/health`.
- Mobile-first browser UI served from the Flask application.

## Repository Layout

```text
.
|-- app.py                         # Flask server, LAN scanner, proxy API, and inline UI
|-- requirements.txt               # Python runtime dependencies
|-- Procfile                       # Gunicorn process definition
|-- models/                        # ONNX model assets kept with the app
|-- debug_camera_assistant*.jpg     # Camera/debug reference images
`-- docs/
    `-- ARCHITECTURE.md            # Runtime architecture and operational notes
```

## Requirements

- Python 3.10 or newer.
- A computer on the same WiFi network as the MAVEN device.
- A MAVEN/Pi device running the expected local services:
  - MAVEN API on port `5000`
  - Camera service on port `8081`
  - Microphone service on port `8082`

## Local Setup

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

Run the companion app:

```powershell
python app.py
```

Open the app on the same machine:

```text
http://localhost:8080
```

To use it from a phone, connect the phone to the same WiFi network and open:

```text
http://<this-computer-ip>:8080
```

## Hardware Setup Expectations

The companion app is not the firmware or Pi service bundle. Before pairing from the browser:

1. Power on the MAVEN device.
2. Confirm the Pi/device is on the same WiFi network as the companion app host.
3. Start the MAVEN API service on port `5000`.
4. Start the camera service on port `8081` if camera features are needed.
5. Start the microphone service on port `8082` if microphone features are needed.
6. Hold the MAVEN hardware button for 5 seconds to enter pairing mode.

## Health Check

The app exposes:

```text
GET /health
```

The response includes:

- Overall status: `healthy`, `degraded`, or `unhealthy`.
- Scanner status: whether the LAN scanner thread is running and when it last succeeded.
- Service checks for `camera`, `microphone`, and `ir`.
- Each service status, latency in milliseconds, and nullable error.

Example:

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
    "camera": {
      "status": "healthy",
      "latency_ms": 12.3,
      "error": null
    },
    "microphone": {
      "status": "unhealthy",
      "latency_ms": 1001.8,
      "error": "HTTPConnectionPool timeout"
    },
    "ir": {
      "status": "healthy",
      "latency_ms": 9.4,
      "error": null
    }
  }
}
```

Each service check uses a 1-second timeout. `healthy` means all three services are healthy, `degraded` means at least one service is healthy and at least one is unhealthy, and `unhealthy` means no services are healthy, no target device is available, or the LAN scanner is not running.

The endpoint returns HTTP `200` for `healthy` or `degraded`, and HTTP `503` for `unhealthy`.

## Deployment

The included `Procfile` defines:

```text
web: gunicorn --workers 1 --bind 0.0.0.0:${PORT:-8080} app:app
```

Gunicorn imports `app:app`, which autostarts the LAN scanner in the same process. Use a single worker so discovery and paired-session state are not split across processes. Set `MAVEN_SCANNER_AUTOSTART=0` only for tests or custom layouts.

For local development and hardware testing:

```powershell
python app.py
```

## Troubleshooting

- No devices found: confirm the host and MAVEN device are on the same subnet and that the device API is listening on port `5000`.
- Pairing fails: hold the hardware button for 5 seconds, then retry while the device is in pairing mode.
- Camera unavailable: confirm the camera service is reachable at `http://<device-ip>:8081/status`.
- Microphone unavailable: confirm the microphone service is reachable at `http://<device-ip>:8082/status`.
- `/health` reports `scanner.running: false`: confirm Gunicorn is using one worker and `MAVEN_SCANNER_AUTOSTART` is not disabled.

## Development Notes

- The frontend is currently embedded in `app.py` with `render_template_string`.
- The browser stores the MAVEN token and a reconnect hint IP in `localStorage`. The companion app stores the authoritative paired session in memory and rebinds the Pi IP during LAN scans.
- The Flask server proxies browser requests to the MAVEN device so the browser does not need to call the Pi services directly.
- See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for a deeper architecture overview.
