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
- Scanner freshness and last error.
- Number of discovered devices.
- Per-device checks for MAVEN API, camera, and microphone services.

Example:

```json
{
  "status": "degraded",
  "summary": {
    "devices_found": 1,
    "services_checked": 3,
    "services_healthy": 2,
    "services_unhealthy": 1
  }
}
```

The endpoint returns HTTP `200` for `healthy` or `degraded`, and HTTP `503` for `unhealthy`.

## Deployment

The included `Procfile` defines:

```text
web: gunicorn app:app
```

That is suitable for platforms that run Gunicorn, but note that the current LAN scanner is started inside the `if __name__ == "__main__"` block when running `python app.py`. If deploying through Gunicorn, move scanner startup into the process lifecycle before relying on `/api/devices` or `/health` for discovery.

For local development and hardware testing, prefer:

```powershell
python app.py
```

## Troubleshooting

- No devices found: confirm the host and MAVEN device are on the same subnet and that the device API is listening on port `5000`.
- Pairing fails: hold the hardware button for 5 seconds, then retry while the device is in pairing mode.
- Camera unavailable: confirm the camera service is reachable at `http://<device-ip>:8081/status`.
- Microphone unavailable: confirm the microphone service is reachable at `http://<device-ip>:8082/status`.
- `/health` is unhealthy after starting with Gunicorn: use `python app.py` locally or update scanner startup for the deployment path.

## Development Notes

- The frontend is currently embedded in `app.py` with `render_template_string`.
- The browser stores the MAVEN IP, auth token, and device name in `localStorage`.
- The Flask server proxies browser requests to the MAVEN device so the browser does not need to call the Pi services directly.
- See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for a deeper architecture overview.
