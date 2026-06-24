# MAVEN Architecture

This document describes the current companion app architecture as implemented in `app.py`.

## System Overview

MAVEN has two runtime sides:

1. Companion app host: a laptop, desktop, or local server running this Flask app.
2. MAVEN hardware device: a Pi-like device on the same LAN running the MAVEN API, camera service, and microphone service.

The browser talks to the Flask app. The Flask app discovers and proxies requests to the MAVEN hardware services.

```text
Browser
  |
  | HTTP :8080
  v
Flask companion app
  |-- scans LAN for http://<ip>:5000/api/discover
  |-- proxies MAVEN API requests to http://<device-ip>:5000
  |-- proxies camera requests to http://<device-ip>:8081
  `-- proxies microphone requests to http://<device-ip>:8082
```

## Runtime Components

### Flask App

`app.py` creates the Flask application and serves:

- `GET /` for the mobile-first web UI.
- `GET /api/devices` for discovered MAVEN devices.
- `GET /health` for operational health checks.
- `/proxy/*` routes for MAVEN API, camera, and microphone requests.

The app listens on port `8080` when started with:

```powershell
python app.py
```

### LAN Scanner

The scanner derives the host subnet using a UDP socket and probes addresses from `.1` through `.254`, excluding the host IP. It checks:

```text
http://<candidate-ip>:5000/api/discover
```

Successful discoveries are stored in the in-memory `devices` dictionary with:

- IP address
- device name
- pairing state
- last seen timestamp

The scanner interval is controlled by `SCAN_EVERY`, currently `3` seconds.

### Proxy API

The browser uses Flask proxy routes instead of calling device services directly.

MAVEN API proxy routes:

- `POST /proxy/confirm-pair`
- `GET /proxy/codes`
- `POST /proxy/learn/<name>`
- `POST /proxy/clear/<name>`
- `POST /proxy/send/<name>`

Camera proxy routes:

- `GET /proxy/camera/status`
- `GET /proxy/camera/frame.jpg`
- `GET /proxy/camera/video`

Microphone proxy routes:

- `GET /proxy/mic/status`
- `GET /proxy/mic/level`

### Frontend

The UI is embedded as an inline HTML string in `app.py`. It provides:

- Device discovery and pairing.
- Command learning, clearing, testing, and progress.
- Sensor tab for camera preview and microphone levels.
- Full camera view with MJPEG support and still-frame fallback.

Persistent browser state is stored in `localStorage`:

- `maven_ip`
- `maven_token`
- per-device display names

## Health Model

`GET /health` builds a structured report from scanner state and live device service checks.

Overall status is calculated as:

- `healthy`: scanner is fresh, at least one device is discovered, and all checked services are healthy.
- `degraded`: scanner is fresh, at least one device is discovered, and some services are healthy while others are unhealthy.
- `unhealthy`: scanner is stale or not running, no devices are discovered, or no checked services are healthy.

The endpoint returns HTTP `200` for `healthy` and `degraded`, and HTTP `503` for `unhealthy`.

## Important Operational Notes

- Device discovery is in-memory. Restarting the companion app clears discovered devices until the next scan.
- Running under Gunicorn with the current `Procfile` imports `app:app`, but does not execute the `if __name__ == "__main__"` block. That means the scanner does not start in that path without a lifecycle change.
- Multiple Gunicorn workers would each have separate in-memory device state. A production deployment should use a single scanner process or shared state.
- The scanner assumes a `/24` LAN and may not work on more complex networks without configuration.

## Security Considerations

- Proxy routes currently accept a caller-provided `ip` query/body value. Production deployments should restrict proxy targets to discovered/paired device IPs.
- Tokens are stored in browser `localStorage`; this is simple but vulnerable to XSS.
- The frontend uses dynamic HTML insertion in several places. Values from devices should be sanitized before rendering.
- The companion app is designed for trusted local networks, not direct public internet exposure.

## Recommended Next Steps

1. Split `app.py` into backend routes, scanner service, templates, and static assets.
2. Move configuration to environment variables.
3. Start the scanner through an explicit app lifecycle hook for Gunicorn deployments.
4. Add tests for health reporting, proxy validation, and scanner state.
5. Restrict proxy requests to known MAVEN device IPs.
6. Add documentation or code for the Pi-side MAVEN services.
