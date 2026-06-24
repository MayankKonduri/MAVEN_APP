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
- `GET /api/paired` for the server-authoritative paired device IP (supports session restore).
- `POST /api/disconnect` to clear the in-memory paired session.
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

The scanner starts automatically when the Flask app module is imported, including under Gunicorn. Set `MAVEN_SCANNER_AUTOSTART=0` to disable autostart (for tests or custom process layouts). Use a single Gunicorn worker so discovery state and paired sessions stay in one process.

### Proxy API

The browser uses Flask proxy routes instead of calling device services directly. After pairing, the companion app stores the session server-side and resolves the Pi IP from that session. The browser no longer supplies a trusted target IP for paired requests.

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

- `maven_ip` (display and reconnect hint only; server session is authoritative after pairing)
- `maven_token`
- per-device display names

The home screen polls `/health` every 10 seconds and shows `Connected`, `Connected · some sensors offline`, or `Device unreachable`.

## Paired Session Model

Pairing creates an in-memory session on the companion host:

- `token`
- current Pi `ip`
- device `name`

On each LAN scan, if the stored IP no longer accepts the token, the scanner probes discovered devices and rebinds the session automatically. `GET /api/paired` can also restore a session after companion restart by validating the token against a hint IP or discovered devices.

Proxy routes for paired traffic require an active server session. Unpaired routes (`POST /proxy/confirm-pair`, reconnect via `GET /proxy/codes`) still accept a caller-provided IP.

## Health Model

`GET /health` builds a structured report from live service checks for the selected MAVEN device. If an `ip` query parameter is provided, that device is checked. Otherwise, the paired session IP is used when available. If neither exists, the freshest discovered device is checked.

Overall status is calculated as:

- `healthy`: camera, microphone, and IR checks are all healthy.
- `degraded`: at least one service is healthy and at least one service is unhealthy.
- `unhealthy`: no services are healthy or no device is available to check.

Each service uses a 1-second HTTP timeout. The response body contains `status`, `scanner`, and `services`. Service keys are `camera`, `microphone`, and `ir`. The `scanner` block reports whether the LAN scanner thread is running and when it last found a MAVEN device.

The endpoint returns HTTP `200` for `healthy` and `degraded`, and HTTP `503` for `unhealthy`. If the scanner is not running, overall status is `unhealthy`.

## Important Operational Notes

- Device discovery is in-memory. Restarting the companion app clears discovered devices until the next scan.
- Paired sessions are in-memory. Restarting the companion app clears the session until the browser calls `GET /api/paired` with a valid token or the user re-pairs.
- Production deployments should run Gunicorn with a single worker (`Procfile` sets `--workers 1`) so the scanner and paired session state are not duplicated across processes.
- The scanner assumes a `/24` LAN and may not work on more complex networks without configuration.

## Security Considerations

- Proxy routes no longer trust caller-supplied IPs for paired traffic; the server session is authoritative.
- Tokens are stored in browser `localStorage`; this is simple but vulnerable to XSS.
- The frontend uses dynamic HTML insertion in several places. Values from devices should be sanitized before rendering.
- The companion app is designed for trusted local networks, not direct public internet exposure.

## Recommended Next Steps

1. Split `app.py` into backend routes, scanner service, templates, and static assets.
2. Move configuration to environment variables.
3. Persist paired sessions across companion restarts.
4. Add documentation or code for the Pi-side MAVEN services.
