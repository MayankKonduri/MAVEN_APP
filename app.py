#!/usr/bin/env python3
"""
MAVEN Companion App
Run: python3 app.py
Then open http://localhost:8080 on your phone or browser.

Runs on a local machine separate from the Pi.
The Pi runs camera_server.py on port 8081.
"""

import asyncio, aiohttp, socket, threading, time, json
from flask import Flask, jsonify, render_template_string, request

PI_PORT    = 5000
CAM_PORT   = 8081   # camera_server.py on the Pi
APP_PORT   = 8080
SCAN_EVERY = 3

# ── network scanning ──────────────────────────────────────────────────────────
def get_subnet():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    finally:
        s.close()
    base = ".".join(ip.split(".")[:3])
    return base, ip

async def probe(session, ip):
    try:
        async with session.get(
            f"http://{ip}:{PI_PORT}/api/discover",
            timeout=aiohttp.ClientTimeout(total=0.6)
        ) as r:
            if r.status == 200:
                d = await r.json()
                if d.get("ok"):
                    return ip, d
    except Exception:
        pass
    return None

async def scan_once(base, my_ip):
    targets = [f"{base}.{i}" for i in range(1, 255) if f"{base}.{i}" != my_ip]
    connector = aiohttp.TCPConnector(limit=80)
    async with aiohttp.ClientSession(connector=connector) as session:
        results = await asyncio.gather(*[probe(session, ip) for ip in targets])
    return [r for r in results if r]

# ── shared state ──────────────────────────────────────────────────────────────
devices = {}
lock    = threading.Lock()

def scanner_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    base, my_ip = get_subnet()
    print(f"  Scanning {base}.1–254 every {SCAN_EVERY}s")
    while True:
        t0 = time.time()
        found = loop.run_until_complete(scan_once(base, my_ip))
        now = time.time()
        with lock:
            for ip, d in found:
                devices[ip] = {
                    "ip":      ip,
                    "name":    d.get("name", "MAVEN"),
                    "pairing": d.get("pairing", False),
                    "seen":    now,
                }
            for ip in list(devices):
                if now - devices[ip]["seen"] > SCAN_EVERY * 2.5:
                    del devices[ip]
        time.sleep(max(0, SCAN_EVERY - (time.time() - t0)))

# ── Flask ─────────────────────────────────────────────────────────────────────
app = Flask(__name__)

@app.route("/api/devices")
def api_devices():
    with lock:
        return jsonify(list(devices.values()))

# proxy all Pi API calls so the browser never touches the Pi directly
import requests as req

@app.route("/proxy/confirm-pair", methods=["POST"])
def proxy_pair():
    ip = request.json.get("ip")
    try:
        r = req.post(f"http://{ip}:{PI_PORT}/api/confirm-pair", timeout=6)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502

@app.route("/proxy/codes")
def proxy_codes():
    ip    = request.args.get("ip")
    token = request.headers.get("X-Maven-Token", "")
    try:
        r = req.get(f"http://{ip}:{PI_PORT}/api/codes",
                    headers={"X-Maven-Token": token}, timeout=5)
        return (r.text, r.status_code, {"Content-Type": "application/json"})
    except Exception as e:
        return jsonify({"error": str(e)}), 502

@app.route("/proxy/learn/<name>", methods=["POST"])
def proxy_learn(name):
    ip    = request.args.get("ip")
    token = request.headers.get("X-Maven-Token", "")
    try:
        r = req.post(f"http://{ip}:{PI_PORT}/api/learn/{name}",
                     headers={"X-Maven-Token": token}, timeout=5)
        return (r.text, r.status_code, {"Content-Type": "application/json"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502

@app.route("/proxy/clear/<name>", methods=["POST"])
def proxy_clear(name):
    ip    = request.args.get("ip")
    token = request.headers.get("X-Maven-Token", "")
    try:
        r = req.post(f"http://{ip}:{PI_PORT}/api/clear/{name}",
                     headers={"X-Maven-Token": token}, timeout=5)
        return (r.text, r.status_code, {"Content-Type": "application/json"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502

@app.route("/proxy/send/<name>", methods=["POST"])
def proxy_send(name):
    ip    = request.args.get("ip")
    token = request.headers.get("X-Maven-Token", "")
    try:
        r = req.post(f"http://{ip}:{PI_PORT}/api/send/{name}",
                     headers={"X-Maven-Token": token}, timeout=5)
        return (r.text, r.status_code, {"Content-Type": "application/json"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502

# ── Camera proxy ──────────────────────────────────────────────────────────────
# The browser can't directly reach the Pi's camera on port 8081 if on a
# different subnet or if CORS blocks it. These routes proxy through this server.

@app.route("/proxy/camera/status")
def proxy_camera_status():
    ip = request.args.get("ip")
    try:
        r = req.get(f"http://{ip}:{CAM_PORT}/status", timeout=3)
        return (r.text, r.status_code, {"Content-Type": "application/json"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502

@app.route("/proxy/camera/frame.jpg")
def proxy_camera_frame():
    ip = request.args.get("ip")
    try:
        r = req.get(f"http://{ip}:{CAM_PORT}/frame.jpg", timeout=3, stream=True)
        if r.status_code != 200:
            return "Frame not available", r.status_code
        return (
            r.raw.read(),
            200,
            {
                "Content-Type": "image/jpeg",
                "Cache-Control": "no-store",
                "Access-Control-Allow-Origin": "*",
            }
        )
    except Exception as e:
        return str(e), 502

@app.route("/proxy/camera/video")
def proxy_camera_video():
    """
    Proxies the MJPEG stream from the Pi's camera_server.
    The browser hits this endpoint; this server forwards frames from the Pi.
    This avoids any cross-origin or port issues on the client side.
    """
    ip = request.args.get("ip")

    def generate():
        try:
            with req.get(
                f"http://{ip}:{CAM_PORT}/video",
                stream=True,
                timeout=10
            ) as r:
                for chunk in r.iter_content(chunk_size=4096):
                    if chunk:
                        yield chunk
        except Exception:
            return

    try:
        # Quick reachability check before opening stream
        req.get(f"http://{ip}:{CAM_PORT}/status", timeout=2)
    except Exception:
        return "Camera not reachable", 502

    return app.response_class(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )

@app.route("/")
def index():
    return render_template_string(HTML)

# ── HTML ──────────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#06060f">
<title>MAVEN</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
:root{
  --bg:#06060f;--bg1:#0c0c1a;--bg2:#121224;--bg3:#1a1a30;--bg4:#22223a;
  --border:rgba(255,255,255,0.06);--border2:rgba(255,255,255,0.11);
  --text:#eeeeff;--text2:#a0a0c0;--text3:#606080;
  --accent:#7c6fff;--accent2:#5a50d4;--accent3:#3d36a0;
  --green:#00e5a0;--green2:#00b87a;--red:#ff4f6a;
  --r:18px;--r-sm:11px;
  --safe-t:env(safe-area-inset-top,0px);--safe-b:env(safe-area-inset-bottom,0px);
}
html,body{height:100%;background:var(--bg);color:var(--text);font-family:'DM Sans',system-ui,sans-serif;font-size:15px;overscroll-behavior:none;-webkit-font-smoothing:antialiased}
.screen{display:none;flex-direction:column;height:100vh;overflow:hidden}
.screen.active{display:flex}

/* ── SCAN SCREEN ── */
#screen-scan{align-items:center;justify-content:center;padding:calc(var(--safe-t)+20px) 28px calc(20px + var(--safe-b));background:radial-gradient(ellipse at 50% 20%,#150f35 0%,var(--bg) 65%);overflow-y:auto}
.logo{font-family:'DM Mono',monospace;font-size:20px;font-weight:500;letter-spacing:5px;text-transform:uppercase;color:var(--text3);margin-bottom:32px;align-self:center}
.radar-wrap{position:relative;width:200px;height:200px;display:flex;align-items:center;justify-content:center;margin-bottom:44px;flex-shrink:0;align-self:center}
.radar-ring{position:absolute;border-radius:50%;border:1px solid rgba(124,111,255,0.18);animation:radar-expand 3s ease-out infinite;opacity:0}
.radar-ring:nth-child(1){width:90px;height:90px;animation-delay:0s}
.radar-ring:nth-child(2){width:130px;height:130px;animation-delay:1s}
.radar-ring:nth-child(3){width:170px;height:170px;animation-delay:2s}
@keyframes radar-expand{0%{opacity:0;transform:scale(0.8)}25%{opacity:1}100%{opacity:0;transform:scale(1)}}
.radar-ring.active{animation-duration:1.6s;border-color:rgba(124,111,255,0.35)}
.radar-ring.pairing{animation-duration:1s;border-color:rgba(0,229,160,0.5)!important}
.orb-core{width:84px;height:84px;border-radius:50%;background:conic-gradient(from 180deg,var(--accent3),var(--accent2),var(--accent),var(--accent2),var(--accent3));display:flex;align-items:center;justify-content:center;position:relative;z-index:2;box-shadow:0 0 0 1px rgba(124,111,255,0.3),0 0 40px rgba(124,111,255,0.25);animation:orb-rotate 8s linear infinite}
.orb-core.pairing{background:conic-gradient(from 180deg,#007a54,var(--green2),var(--green),var(--green2),#007a54);box-shadow:0 0 0 1px rgba(0,229,160,0.4),0 0 50px rgba(0,229,160,0.35)}
@keyframes orb-rotate{to{filter:hue-rotate(40deg)}}
.orb-core::before{content:'';position:absolute;inset:3px;border-radius:50%;background:var(--bg1)}
.orb-core svg{width:32px;height:32px;fill:none;stroke:#fff;stroke-width:1.6;stroke-linecap:round;position:relative;z-index:1}
.scan-heading{font-size:24px;font-weight:600;letter-spacing:-0.4px;text-align:center;margin-bottom:8px}
.scan-sub{font-size:13px;color:var(--text2);text-align:center;line-height:1.65;margin-bottom:36px;max-width:270px;align-self:center}
.scan-status{display:flex;align-items:center;gap:10px;font-size:12px;color:var(--text3);font-family:'DM Mono',monospace;margin-bottom:28px;align-self:center}
.scan-dot{width:6px;height:6px;border-radius:50%;background:var(--text3);animation:scan-blink 1.4s ease-in-out infinite}
.scan-dot.scanning{background:var(--accent);animation-duration:0.7s}
.scan-dot.pairing{background:var(--green);animation-duration:0.5s}
@keyframes scan-blink{0%,100%{opacity:1}50%{opacity:0.3}}
.devices-wrap{width:100%;max-width:360px;display:flex;flex-direction:column;gap:10px;align-self:center;min-height:60px}
.device-card{background:var(--bg2);border:1px solid var(--border2);border-radius:var(--r);padding:16px 18px;display:flex;align-items:center;gap:14px;cursor:pointer;transition:border-color 0.2s,background 0.2s,transform 0.1s;animation:card-in 0.35s cubic-bezier(0.4,0,0.2,1) both}
@keyframes card-in{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
.device-card:active{transform:scale(0.98);opacity:0.85}
.device-card.ready{border-color:rgba(0,229,160,0.4);background:rgba(0,229,160,0.05)}
.device-card.not-ready{border-color:rgba(124,111,255,0.25);background:rgba(124,111,255,0.04)}
.device-icon{width:44px;height:44px;border-radius:12px;flex-shrink:0;background:var(--bg3);display:flex;align-items:center;justify-content:center}
.device-card.ready .device-icon{background:rgba(0,229,160,0.12)}
.device-card.not-ready .device-icon{background:rgba(124,111,255,0.1)}
.device-icon svg{width:20px;height:20px;fill:none;stroke:var(--text3);stroke-width:1.8;stroke-linecap:round}
.device-card.ready .device-icon svg{stroke:var(--green)}
.device-card.not-ready .device-icon svg{stroke:var(--accent)}
.device-info{flex:1;min-width:0}
.device-name{font-size:15px;font-weight:500;color:var(--text)}
.device-meta{font-size:11px;color:var(--text3);margin-top:2px;font-family:'DM Mono',monospace}
.device-card.ready .device-meta{color:var(--green)}
.device-card.not-ready .device-meta{color:var(--accent)}
.device-badge{font-size:11px;font-weight:500;padding:4px 10px;border-radius:99px;flex-shrink:0}
.badge-ready{background:rgba(0,229,160,0.15);color:var(--green)}
.badge-found{background:rgba(124,111,255,0.12);color:var(--accent)}
.no-devices{text-align:center;color:var(--text3);font-size:13px;line-height:1.8;padding:20px 0;align-self:center}

/* ── HOME SCREEN ── */
#screen-home{background:var(--bg)}
.status-bar{padding:calc(var(--safe-t) + 22px) 20px 20px;display:flex;align-items:center;gap:10px;background:var(--bg1);border-bottom:1px solid var(--border);flex-shrink:0}
.status-icon{width:38px;height:38px;border-radius:11px;flex-shrink:0;background:linear-gradient(135deg,var(--accent),var(--accent2));display:flex;align-items:center;justify-content:center}
.status-icon svg{width:18px;height:18px;fill:none;stroke:#fff;stroke-width:2;stroke-linecap:round}
.status-info{flex:1;min-width:0}
.status-name{font-size:15px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:pointer}
.status-conn{font-size:11px;color:var(--green);display:flex;align-items:center;gap:5px;margin-top:3px;font-family:'DM Mono',monospace}
.status-conn::before{content:'';width:6px;height:6px;border-radius:50%;background:var(--green);display:inline-block;animation:conn-pulse 2s infinite}
@keyframes conn-pulse{0%,100%{opacity:1}50%{opacity:0.35}}
.btn-icon{background:none;border:1px solid var(--border2);color:var(--text2);width:36px;height:36px;border-radius:10px;display:flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0;transition:all 0.15s;padding:0}
.btn-icon:active{border-color:var(--accent);color:var(--accent)}
.btn-disconnect{background:none;border:1px solid var(--border2);color:var(--text3);padding:7px 13px;border-radius:9px;font-family:'DM Sans',sans-serif;font-size:12px;font-weight:500;cursor:pointer;transition:all 0.15s}
.btn-disconnect:active{border-color:var(--red);color:var(--red)}
.progress-wrap{padding:16px 20px 14px;background:var(--bg1);border-bottom:1px solid var(--border);flex-shrink:0}
.prog-row{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px}
.prog-label{font-size:11px;font-weight:500;letter-spacing:0.8px;text-transform:uppercase;color:var(--text3);font-family:'DM Mono',monospace}
.prog-count{font-size:13px;font-weight:600;color:var(--text)}
.prog-count span{color:var(--green)}
.track{height:3px;background:var(--bg3);border-radius:99px;overflow:hidden}
.fill{height:100%;border-radius:99px;background:linear-gradient(90deg,var(--accent),var(--green));transition:width 0.7s cubic-bezier(0.4,0,0.2,1);width:0%}
.cmd-scroll{flex:1;overflow-y:auto;padding:10px 14px calc(20px + var(--safe-b));-webkit-overflow-scrolling:touch}
.group-head{font-size:10px;font-weight:500;letter-spacing:1.5px;text-transform:uppercase;color:var(--text3);padding:16px 4px 8px;font-family:'DM Mono',monospace}
.cmd-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);margin-bottom:8px;overflow:hidden;transition:border-color 0.2s,transform 0.1s;cursor:pointer}
.cmd-card:active{opacity:0.85;transform:scale(0.99)}
.cmd-card.learned{border-color:rgba(0,229,160,0.18)}
.cmd-card.learning-active{border-color:var(--accent);animation:card-pulse 1s ease-in-out infinite}
@keyframes card-pulse{0%,100%{border-color:rgba(124,111,255,0.25)}50%{border-color:rgba(124,111,255,0.85)}}
.cmd-inner{display:flex;align-items:center;gap:14px;padding:14px 16px}
.cmd-bar{width:3px;align-self:stretch;border-radius:3px;background:var(--bg3);flex-shrink:0;margin:-14px -2px -14px -16px;transition:background 0.3s}
.cmd-card.learned .cmd-bar{background:var(--green)}
.cmd-card.learning-active .cmd-bar{background:var(--accent)}
.cmd-icon{width:42px;height:42px;border-radius:12px;background:var(--bg3);display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0;transition:background 0.2s}
.cmd-card.learned .cmd-icon{background:rgba(0,229,160,0.09)}
.cmd-card.learning-active .cmd-icon{background:rgba(124,111,255,0.14)}
.cmd-text{flex:1;min-width:0}
.cmd-label{font-size:14px;font-weight:500}
.cmd-state{font-size:12px;margin-top:2px;color:var(--text3)}
.cmd-card.learned .cmd-state{color:var(--green)}
.cmd-card.learning-active .cmd-state{color:var(--accent)}
.cmd-chev{color:var(--text3);font-size:18px;flex-shrink:0}

/* ── CAMERA SCREEN ── */
#screen-camera{background:var(--bg)}
.camera-status-bar{padding:calc(var(--safe-t) + 22px) 20px 20px;display:flex;align-items:center;gap:12px;background:var(--bg1);border-bottom:1px solid var(--border);flex-shrink:0}
.camera-body{flex:1;overflow-y:auto;padding:20px 16px calc(20px + var(--safe-b));-webkit-overflow-scrolling:touch}
.camera-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);overflow:hidden}
.camera-feed-wrap{position:relative;width:100%;aspect-ratio:4/3;background:var(--bg1);display:flex;align-items:center;justify-content:center;overflow:hidden}
.camera-feed-wrap img{width:100%;height:100%;object-fit:cover;display:none}
.camera-placeholder{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;color:var(--text3);font-size:13px;text-align:center;padding:20px;transition:opacity 0.3s}
.camera-placeholder svg{opacity:0.4}
.camera-placeholder.hidden{opacity:0;pointer-events:none}
.camera-hint{display:flex;align-items:flex-start;gap:8px;padding:14px 16px;font-size:12px;color:var(--text3);border-top:1px solid var(--border);line-height:1.6}
.camera-hint svg{flex-shrink:0;margin-top:1px;opacity:0.6}
.camera-err{display:flex;flex-direction:column;align-items:center;gap:10px;padding:36px 20px;text-align:center}
.camera-err-icon{font-size:36px;opacity:0.6}
.camera-err-title{font-size:15px;font-weight:500;color:var(--text)}
.camera-err-msg{font-size:13px;color:var(--text3);line-height:1.65;max-width:260px}
.camera-err-retry{margin-top:6px;background:var(--bg3);border:1px solid var(--border2);color:var(--text2);padding:10px 22px;border-radius:10px;font-family:'DM Sans',sans-serif;font-size:14px;font-weight:500;cursor:pointer;transition:all 0.15s}
.camera-err-retry:active{opacity:0.7}
.live-badge{position:absolute;top:12px;left:12px;background:rgba(0,0,0,0.55);backdrop-filter:blur(6px);border:1px solid rgba(255,79,106,0.4);color:#fff;font-size:10px;font-weight:600;letter-spacing:1.5px;padding:4px 9px;border-radius:99px;display:flex;align-items:center;gap:5px;font-family:'DM Mono',monospace;opacity:0;transition:opacity 0.4s}
.live-badge.visible{opacity:1}
.live-dot{width:6px;height:6px;border-radius:50%;background:var(--red);animation:scan-blink 0.9s ease-in-out infinite}

/* ── SHEET ── */
.overlay{position:fixed;inset:0;background:rgba(0,0,0,0.72);backdrop-filter:blur(6px);opacity:0;pointer-events:none;transition:opacity 0.25s;z-index:100;display:flex;align-items:flex-end}
.overlay.open{opacity:1;pointer-events:all}
.sheet{width:100%;background:var(--bg2);border-radius:24px 24px 0 0;border-top:1px solid var(--border2);padding:0 0 calc(28px + var(--safe-b));transform:translateY(100%);transition:transform 0.32s cubic-bezier(0.4,0,0.2,1)}
.overlay.open .sheet{transform:translateY(0)}
.sheet-handle{width:36px;height:4px;background:var(--border2);border-radius:99px;margin:14px auto 0}
.sheet-hdr{padding:18px 20px 14px;border-bottom:1px solid var(--border)}
.sheet-title{font-size:17px;font-weight:600}
.sheet-sub{font-size:13px;color:var(--text2);margin-top:3px}
.l-orb-wrap{display:flex;flex-direction:column;align-items:center;padding:28px 20px 8px}
.l-orb{width:76px;height:76px;border-radius:50%;position:relative;background:conic-gradient(from 180deg,var(--accent3),var(--accent2),var(--accent),var(--accent2),var(--accent3));display:flex;align-items:center;justify-content:center;margin-bottom:16px;box-shadow:0 0 0 1px rgba(124,111,255,0.3);animation:orb-rotate 4s linear infinite}
.l-orb::before{content:'';position:absolute;inset:3px;border-radius:50%;background:var(--bg2)}
.l-orb svg{width:28px;height:28px;fill:none;stroke:#fff;stroke-width:2;stroke-linecap:round;position:relative;z-index:1}
.l-ring{position:absolute;border-radius:50%;border:1px solid rgba(124,111,255,0.28);animation:l-ring-pulse 1.2s ease-out infinite;opacity:0}
.l-ring:nth-child(1){width:96px;height:96px;animation-delay:0s}
.l-ring:nth-child(2){width:118px;height:118px;animation-delay:0.4s}
.l-ring:nth-child(3){width:140px;height:140px;animation-delay:0.8s}
@keyframes l-ring-pulse{0%{opacity:0;transform:scale(0.8)}30%{opacity:1}100%{opacity:0;transform:scale(1)}}
.l-msg{font-size:14px;color:var(--text2);text-align:center;line-height:1.65}
.l-msg b{color:var(--text);font-weight:600}
.result-icon{font-size:46px;text-align:center;padding:24px 0 8px}
.result-msg{font-size:14px;color:var(--text2);text-align:center;padding:0 20px 20px;line-height:1.65}
.sheet-actions{padding:10px 16px;display:flex;flex-direction:column;gap:8px}
.sbtn{width:100%;padding:15px;border-radius:var(--r);font-family:'DM Sans',sans-serif;font-size:15px;font-weight:500;border:none;cursor:pointer;transition:opacity 0.15s,transform 0.1s}
.sbtn:active{transform:scale(0.97);opacity:0.85}
.sbtn-primary{background:var(--accent);color:#fff}
.sbtn-ghost{background:var(--bg3);color:var(--text)}
.sbtn-danger{background:rgba(255,79,106,0.1);color:var(--red);border:1px solid rgba(255,79,106,0.2)}
.rename-wrap{padding:20px 16px 10px}
.rename-input{width:100%;background:var(--bg3);border:1px solid var(--border2);border-radius:var(--r-sm);padding:14px 16px;color:var(--text);font-family:'DM Sans',sans-serif;font-size:16px;outline:none;transition:border-color 0.2s}
.rename-input:focus{border-color:var(--accent)}
.notready-wrap{padding:24px 20px 8px;text-align:center}
.notready-icon{font-size:40px;margin-bottom:12px}
.notready-msg{font-size:14px;color:var(--text2);line-height:1.7}
.notready-msg b{color:var(--text);font-weight:500}
.toast{position:fixed;bottom:calc(32px + var(--safe-b));left:50%;transform:translateX(-50%) translateY(16px);background:var(--text);color:var(--bg);padding:11px 22px;border-radius:99px;font-size:13px;font-weight:600;opacity:0;pointer-events:none;transition:all 0.3s cubic-bezier(0.4,0,0.2,1);white-space:nowrap;z-index:999}
.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
.spinner{display:inline-block;width:13px;height:13px;border:2px solid rgba(255,255,255,0.25);border-top-color:#fff;border-radius:50%;animation:spin 0.6s linear infinite;vertical-align:middle;margin-right:6px}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>

<!-- SCAN SCREEN -->
<div id="screen-scan" class="screen active">
  <div class="logo">MAVEN</div>
  <div class="radar-wrap" id="radar-wrap">
    <div class="radar-ring"></div><div class="radar-ring"></div><div class="radar-ring"></div>
    <div class="orb-core" id="orb-core">
      <svg viewBox="0 0 24 24"><path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><circle cx="12" cy="20" r="1" fill="white" stroke="none"/></svg>
    </div>
  </div>
  <h1 class="scan-heading" id="scan-heading">Looking for devices</h1>
  <p class="scan-sub" id="scan-sub">Hold the button on your MAVEN for 5 seconds to make it appear here.</p>
  <div class="scan-status">
    <div class="scan-dot scanning" id="scan-dot"></div>
    <span id="scan-label">Scanning network…</span>
  </div>
  <div class="devices-wrap" id="devices-wrap"><div class="no-devices"></div></div>
</div>

<!-- HOME SCREEN -->
<div id="screen-home" class="screen">
  <div class="status-bar">
    <div class="status-icon">
      <svg viewBox="0 0 24 24"><path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><circle cx="12" cy="20" r="1" fill="white" stroke="none"/></svg>
    </div>
    <div class="status-info">
      <div class="status-name" id="device-name-display" onclick="openRename()">My MAVEN</div>
      <div class="status-conn">Connected</div>
    </div>
    <!-- Camera button -->
    <button class="btn-icon" onclick="openCamera()" title="Camera view">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg>
    </button>
    <button class="btn-disconnect" onclick="disconnect()">Disconnect</button>
  </div>
  <div class="progress-wrap">
    <div class="prog-row">
      <span class="prog-label">Commands learned</span>
      <span class="prog-count"><span id="prog-num">0</span> / 13</span>
    </div>
    <div class="track"><div class="fill" id="prog-fill"></div></div>
  </div>
  <div class="cmd-scroll" id="cmd-scroll"></div>
</div>

<!-- CAMERA SCREEN -->
<div id="screen-camera" class="screen">
  <div class="camera-status-bar">
    <button class="btn-icon" onclick="closeCamera()">
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5"/><path d="M12 19l-7-7 7-7"/></svg>
    </button>
    <div class="status-info">
      <div class="status-name">Camera View</div>
      <div class="status-conn" id="camera-conn-label">Connecting…</div>
    </div>
  </div>
  <div class="camera-body">
    <div class="camera-card" id="camera-card">
      <div class="camera-feed-wrap" id="camera-feed-wrap">
        <img id="camera-img" alt="MAVEN camera feed">
        <div class="live-badge" id="live-badge"><div class="live-dot"></div>LIVE</div>
        <div class="camera-placeholder" id="camera-placeholder">
          <svg viewBox="0 0 24 24" width="38" height="38" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg>
          <span id="camera-status-msg">Connecting to camera…</span>
        </div>
      </div>
      <div class="camera-hint">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><path d="M12 8v4l3 3"/></svg>
        Use this view to check your MAVEN's angle and adjust its mounting position on the TV.
      </div>
    </div>
  </div>
</div>

<!-- ACTION SHEET -->
<div class="overlay" id="sheet-overlay" onclick="closeSheet(event)">
  <div class="sheet">
    <div class="sheet-handle"></div>
    <div class="sheet-hdr"><div class="sheet-title" id="sheet-title">—</div><div class="sheet-sub" id="sheet-sub">—</div></div>
    <div id="sheet-body"></div>
  </div>
</div>

<!-- RENAME SHEET -->
<div class="overlay" id="rename-overlay" onclick="closeRename(event)">
  <div class="sheet">
    <div class="sheet-handle"></div>
    <div class="sheet-hdr"><div class="sheet-title">Name this device</div><div class="sheet-sub">Saved on your phone only</div></div>
    <div class="rename-wrap"><input class="rename-input" id="rename-input" placeholder="e.g. Living room TV" maxlength="32" onkeydown="if(event.key==='Enter')saveRename()"></div>
    <div class="sheet-actions">
      <button class="sbtn sbtn-primary" onclick="saveRename()">Save</button>
      <button class="sbtn sbtn-ghost" onclick="document.getElementById('rename-overlay').classList.remove('open')">Cancel</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const BUTTON_META = {
  power_toggle:{label:"Power",icon:'<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 2v6"/><path d="M6.5 5a9 9 0 1 0 11 0"/></svg>',group:"Power"},
  vol_up:{label:"Volume up",icon:"🔊",group:"Volume"},
  vol_down:{label:"Volume down",icon:"🔉",group:"Volume"},
  mute:{label:"Mute",icon:"🔇",group:"Volume"},
  channel_up:{label:"Channel up",icon:"⬆",group:"Channels"},
  channel_down:{label:"Channel down",icon:"⬇",group:"Channels"},
  home:{label:"Home",icon:"⌂",group:"Navigation"},
  left:{label:"Left",icon:"◀",group:"Navigation"},
  up:{label:"Up",icon:"▲",group:"Navigation"},
  right:{label:"Right",icon:"▶",group:"Navigation"},
  down:{label:"Down",icon:"▼",group:"Navigation"},
  enter:{label:"OK / Enter",icon:"✓",group:"Navigation"},
  return:{label:"Back",icon:"↩",group:"Navigation"},
};
const GROUP_ORDER = ["Power","Volume","Channels","Navigation"];

let piIP       = localStorage.getItem("maven_ip")    || "";
let mavenToken = localStorage.getItem("maven_token") || "";
let deviceName = localStorage.getItem(`maven_name_${piIP}`) || localStorage.getItem("maven_name") || "My MAVEN";
let codes=[], activeSheet=null, learningFor=null, pollTimer=null, scanTimer=null, connecting=false;

// ── Camera state ──────────────────────────────────────────────────────────────
let cameraActive    = false;
let stillPollTimer  = null;
let cameraMode      = null; // "mjpeg" | "poll" | "error"

applyName();
if (piIP && mavenToken) silentReconnect(); else startScanning();

// ── Helpers ───────────────────────────────────────────────────────────────────
function api(path, opts={}) {
  const headers = {"Content-Type":"application/json"};
  if (mavenToken) headers["X-Maven-Token"] = mavenToken;
  const proxyPath = path.replace("/api/","/proxy/");
  const sep = proxyPath.includes("?")?"&":"?";
  return fetch(`${proxyPath}${sep}ip=${piIP}`, {...opts, headers:{...headers,...(opts.headers||{})}});
}

function showScreen(id) {
  document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
  document.getElementById(id).classList.add("active");
}
function toast(msg,ms=2600){const el=document.getElementById("toast");el.textContent=msg;el.classList.add("show");clearTimeout(el._t);el._t=setTimeout(()=>el.classList.remove("show"),ms)}
function applyName(){const el=document.getElementById("device-name-display");if(el)el.textContent=deviceName}

// ── Reconnect / Scan ──────────────────────────────────────────────────────────
async function silentReconnect() {
  try {
    const r = await fetch(`/proxy/codes?ip=${piIP}`,{headers:{"X-Maven-Token":mavenToken}});
    if (r.ok){enterHome();return;}
  } catch(e){}
  mavenToken="";localStorage.removeItem("maven_token");startScanning();
}

function startScanning() {
  showScreen("screen-scan");setScanStatus("scanning");
  clearInterval(scanTimer);
  pollDevices();
  scanTimer = setInterval(pollDevices, 3000);
}

async function pollDevices() {
  try {
    const r = await fetch("/api/devices");
    const list = await r.json();
    const anyPairing = list.some(d=>d.pairing);
    const anyFound   = list.length > 0;
    setScanStatus(anyPairing?"pairing":anyFound?"found":"idle");
    renderDevices(list);
  } catch(e){}
}

function setScanStatus(state) {
  const dot=document.getElementById("scan-dot"),label=document.getElementById("scan-label");
  const rings=document.querySelectorAll(".radar-ring"),orb=document.getElementById("orb-core");
  const head=document.getElementById("scan-heading"),sub=document.getElementById("scan-sub");
  rings.forEach(r=>{r.classList.remove("active","pairing")});orb.classList.remove("pairing");
  if (state==="pairing"){
    dot.className="scan-dot pairing";label.textContent="Device ready — tap to connect!";
    rings.forEach(r=>r.classList.add("pairing"));orb.classList.add("pairing");
    head.textContent="MAVEN found";sub.textContent="Tap the card below to connect.";
  } else if (state==="found"){
    dot.className="scan-dot scanning";label.textContent="Device found — hold button 5s";
    rings.forEach(r=>r.classList.add("active"));
    head.textContent="Device found";sub.textContent="Press and hold the button on your MAVEN for 5 seconds.";
  } else if (state==="scanning"){
    dot.className="scan-dot scanning";label.textContent="Scanning network…";
    rings.forEach(r=>r.classList.add("active"));
    head.textContent="Looking for devices";sub.textContent="Hold the button on your MAVEN for 5 seconds to make it appear here.";
  } else {
    dot.className="scan-dot";label.textContent="No devices found";
    head.textContent="Looking for devices";sub.textContent="Make sure your MAVEN is powered on and on the same WiFi.";
  }
}

function renderDevices(devices) {
  const wrap=document.getElementById("devices-wrap");
  if (!devices.length){wrap.innerHTML='<div class="no-devices"></div>';return}
  wrap.innerHTML="";
  devices.sort((a,b)=>b.pairing-a.pairing);
  devices.forEach(d=>{
    const card=document.createElement("div");
    card.className="device-card "+(d.pairing?"ready":"not-ready");
    card.innerHTML=`
      <div class="device-icon"><svg viewBox="0 0 24 24"><path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><circle cx="12" cy="20" r="1" fill="currentColor" stroke="none"/></svg></div>
      <div class="device-info">
        <div class="device-name">${localStorage.getItem(`maven_name_${d.ip}`) || d.name}</div>
        <div class="device-meta">${d.ip} · ${d.pairing?"Ready — tap to connect":"Hold button 5s to pair"}</div>
      </div>
      <div class="device-badge ${d.pairing?"badge-ready":"badge-found"}">${d.pairing?"Connect":"Found"}</div>`;
    card.addEventListener("click",()=>{
      if (connecting) return;
      if (d.pairing) connectTo(d.ip, card);
      else {
        document.getElementById("sheet-title").textContent="Not ready yet";
        document.getElementById("sheet-sub").textContent="Hold button 5s to enter pairing mode";
        document.getElementById("sheet-body").innerHTML=`<div class="notready-wrap"><div class="notready-icon">📡</div><p class="notready-msg">Hold the button on your <b>MAVEN</b> for <b>5 seconds</b>.<br><br>The red LED will start blinking — that means it's ready.</p></div><div class="sheet-actions"><button class="sbtn sbtn-ghost" onclick="closeSheet()">Got it</button></div>`;
        document.getElementById("sheet-overlay").classList.add("open");
      }
    });
    wrap.appendChild(card);
  });
}

async function connectTo(ip, cardEl) {
  if (connecting) return;
  connecting=true;
  cardEl.innerHTML=`<div style="display:flex;align-items:center;gap:10px;padding:4px 0"><span class="spinner"></span><span style="font-size:14px;color:var(--text2)">Connecting…</span></div>`;
  piIP=ip;
  try {
    const r = await fetch("/proxy/confirm-pair",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({ip})});
    const d = await r.json();
    if (!d.ok){toast("Not in pairing mode — hold button 5s first");connecting=false;return}
    mavenToken=d.token;
    localStorage.setItem("maven_ip",ip);
    localStorage.setItem("maven_token",mavenToken);
    deviceName = localStorage.getItem(`maven_name_${ip}`) || "My MAVEN";
    clearInterval(scanTimer);connecting=false;
    enterHome();
  } catch(e){toast("Connection failed — try again");connecting=false;}
}

function enterHome(){showScreen("screen-home");applyName();fetchCodes();clearInterval(pollTimer);pollTimer=setInterval(()=>fetchCodes(true),3000)}
function disconnect(){clearInterval(pollTimer);stopCameraFeed();closeSheet();mavenToken="";localStorage.removeItem("maven_token");startScanning()}

// ── Commands ──────────────────────────────────────────────────────────────────
async function fetchCodes(silent=false){
  try {
    const r=await api("/api/codes");
    if(r.status===403){mavenToken="";localStorage.removeItem("maven_token");toast("Session expired");setTimeout(startScanning,1500);return}
    const data=await r.json();codes=data.codes;
    if(learningFor&&data.learn_result){
      const ok=data.learn_result==="ok";learningFor=null;
      clearInterval(pollTimer);pollTimer=setInterval(()=>fetchCodes(true),3000);
      if(activeSheet)updateSheetAfterLearn(ok);
    }
    renderCodes();
  } catch(e){if(!silent)toast("Lost connection")}
}

function renderCodes(){
  const learned=codes.filter(c=>c.learned).length;
  document.getElementById("prog-num").textContent=learned;
  document.getElementById("prog-fill").style.width=Math.round(learned/13*100)+"%";
  const grouped={};
  codes.forEach(c=>{const m=BUTTON_META[c.name]||{label:c.name,icon:"?",group:"Other"};if(!grouped[m.group])grouped[m.group]=[];grouped[m.group].push({...c,...m})});
  const scroll=document.getElementById("cmd-scroll");const top=scroll.scrollTop;scroll.innerHTML="";
  [...GROUP_ORDER,"Other"].forEach(g=>{
    const items=grouped[g];if(!items)return;
    const head=document.createElement("div");head.className="group-head";head.textContent=g;scroll.appendChild(head);
    items.forEach(item=>{
      const isLrn=item.name===learningFor;
      const card=document.createElement("div");
      card.className="cmd-card"+(item.learned?" learned":"")+(isLrn?" learning-active":"");
      card.innerHTML=`<div class="cmd-inner"><div class="cmd-bar"></div><div class="cmd-icon">${item.icon}</div><div class="cmd-text"><div class="cmd-label">${item.label}</div><div class="cmd-state">${isLrn?"Listening for signal…":item.learned?"Signal saved":"Not learned yet"}</div></div><div class="cmd-chev">›</div></div>`;
      card.onclick=()=>openSheet(item);scroll.appendChild(card);
    });
  });
  scroll.scrollTop=top;
}

function openSheet(item){
  activeSheet=item.name;
  document.getElementById("sheet-title").textContent=item.label;
  document.getElementById("sheet-sub").textContent=item.learned?"Signal saved · manage below":"Not learned yet";
  renderSheetIdle(item);document.getElementById("sheet-overlay").classList.add("open");
}
function renderSheetIdle(item){
  if(item.name===learningFor){renderSheetLearning();return}
  const div=document.createElement("div");div.className="sheet-actions";
  if(!item.learned){div.innerHTML=`<button class="sbtn sbtn-primary" onclick="startLearn('${item.name}')">Learn this button</button><button class="sbtn sbtn-ghost" onclick="closeSheet()">Cancel</button>`}
  else{div.innerHTML=`<button class="sbtn sbtn-ghost" style="background:rgba(0,229,160,0.1);color:var(--green);border:1px solid rgba(0,229,160,0.2)" onclick="testCommand('${item.name}')">Test command</button><button class="sbtn sbtn-primary" onclick="startLearn('${item.name}')">Re-learn</button><button class="sbtn sbtn-danger" onclick="clearOne('${item.name}')">Clear signal</button><button class="sbtn sbtn-ghost" onclick="closeSheet()">Done</button>`}
  const body=document.getElementById("sheet-body");body.innerHTML="";body.appendChild(div);
}
function renderSheetLearning(){
  document.getElementById("sheet-body").innerHTML=`<div class="l-orb-wrap"><div class="l-orb"><div class="l-ring"></div><div class="l-ring"></div><div class="l-ring"></div><svg viewBox="0 0 24 24"><path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><circle cx="12" cy="20" r="1" fill="white" stroke="none"/></svg></div><p class="l-msg">Point your remote at the device<br>and press <b>${BUTTON_META[activeSheet]?.label||activeSheet}</b></p></div><div class="sheet-actions"><button class="sbtn sbtn-ghost" onclick="closeSheet()">Cancel</button></div>`;
}
function updateSheetAfterLearn(ok){
  if(!document.getElementById("sheet-overlay").classList.contains("open"))return;
  if(ok){document.getElementById("sheet-body").innerHTML=`<div class="result-icon">✅</div><p class="result-msg">Signal saved! Green LED confirmed the capture.</p><div class="sheet-actions"><button class="sbtn sbtn-ghost" onclick="closeSheet()">Done</button></div>`;toast("Signal saved")}
  else{document.getElementById("sheet-body").innerHTML=`<div class="result-icon">⏱</div><p class="result-msg">No signal received. Point remote at sensor and try again.</p><div class="sheet-actions"><button class="sbtn sbtn-primary" onclick="startLearn('${activeSheet}')">Try again</button><button class="sbtn sbtn-ghost" onclick="closeSheet()">Cancel</button></div>`;toast("Timed out — try again")}
}
async function testCommand(name){
  try{
    const r=await api(`/api/send/${name}`,{method:"POST"});const d=await r.json();
    if(!d.ok){toast(d.error||"Couldn't send");return}
    toast("Command sent!")
  }catch{toast("Lost connection")}
}
function closeSheet(e){if(e&&e.target!==document.getElementById("sheet-overlay"))return;document.getElementById("sheet-overlay").classList.remove("open");activeSheet=null}

async function startLearn(name){
  try{
    const r=await api(`/api/learn/${name}`,{method:"POST"});const d=await r.json();
    if(!d.ok){toast(d.error||"Couldn't start");return}
    learningFor=name;renderSheetLearning();renderCodes();
    clearInterval(pollTimer);pollTimer=setInterval(()=>fetchCodes(true),800);
  }catch{toast("Lost connection")}
}
async function clearOne(name){
  if(!confirm(`Clear signal for "${BUTTON_META[name]?.label||name}"?`))return;
  try{await api(`/api/clear/${name}`,{method:"POST"});toast("Signal cleared");closeSheet();fetchCodes()}catch{toast("Couldn't reach device")}
}
function openRename(){document.getElementById("rename-input").value=deviceName;document.getElementById("rename-overlay").classList.add("open");setTimeout(()=>document.getElementById("rename-input").focus(),350)}
function closeRename(e){if(e&&e.target!==document.getElementById("rename-overlay"))return;document.getElementById("rename-overlay").classList.remove("open")}
function saveRename(){const v=document.getElementById("rename-input").value.trim();if(v){deviceName=v;localStorage.setItem(`maven_name_${piIP}`,v);localStorage.setItem("maven_name",v);applyName()}document.getElementById("rename-overlay").classList.remove("open");toast("Name saved")}

// ── Camera ────────────────────────────────────────────────────────────────────
function openCamera() {
  showScreen("screen-camera");
  startCameraFeed();
}

function closeCamera() {
  stopCameraFeed();
  showScreen("screen-home");
}

function setCameraConnLabel(text, live=false) {
  const el = document.getElementById("camera-conn-label");
  if (!el) return;
  el.textContent = text;
  // Reuse .status-conn green dot; override color for error state
  el.style.color = live ? "" : "var(--text3)";
}

function showLiveBadge(visible) {
  const el = document.getElementById("live-badge");
  if (el) el.classList.toggle("visible", visible);
}

function showCameraFeed(imgEl, placeholderEl) {
  imgEl.style.display = "block";
  placeholderEl.classList.add("hidden");
  showLiveBadge(true);
  setCameraConnLabel("Live feed", true);
}

function showCameraError(title, msg) {
  const card = document.getElementById("camera-card");
  const feedWrap = document.getElementById("camera-feed-wrap");
  feedWrap.innerHTML = `
    <div class="camera-err">
      <div class="camera-err-icon">📷</div>
      <div class="camera-err-title">${title}</div>
      <p class="camera-err-msg">${msg}</p>
      <button class="camera-err-retry" onclick="retryCameraFeed()">Try again</button>
    </div>`;
  showLiveBadge(false);
  setCameraConnLabel("Unavailable");
}

function retryCameraFeed() {
  // Rebuild the feed wrap markup then retry
  const feedWrap = document.getElementById("camera-feed-wrap");
  feedWrap.innerHTML = `
    <img id="camera-img" alt="MAVEN camera feed">
    <div class="live-badge" id="live-badge"><div class="live-dot"></div>LIVE</div>
    <div class="camera-placeholder" id="camera-placeholder">
      <svg viewBox="0 0 24 24" width="38" height="38" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg>
      <span id="camera-status-msg">Connecting to camera…</span>
    </div>`;
  cameraActive = false;
  cameraMode = null;
  clearTimeout(stillPollTimer);
  startCameraFeed();
}

async function startCameraFeed() {
  if (cameraActive) return;
  cameraActive = true;
  cameraMode = null;

  const img         = document.getElementById("camera-img");
  const placeholder = document.getElementById("camera-placeholder");
  const statusMsg   = document.getElementById("camera-status-msg");

  setCameraConnLabel("Connecting…");

  // All camera routes go through our Flask proxy, so no cross-origin issues.
  const statusUrl = `/proxy/camera/status?ip=${piIP}`;
  const streamUrl = `/proxy/camera/video?ip=${piIP}`;
  const frameUrl  = `/proxy/camera/frame.jpg?ip=${piIP}`;

  // 1. Check if camera_server is reachable and camera is OK
  let camOk = false;
  let camErr = "Camera not reachable — make sure camera_server.py is running on the Pi.";
  try {
    const r = await fetch(statusUrl, { signal: AbortSignal.timeout(4000) });
    if (r.ok) {
      const d = await r.json();
      camOk = d.ok;
      if (!camOk) camErr = d.error || "Camera not found on Pi.";
    }
  } catch (e) {
    camOk = false;
  }

  if (!cameraActive) return; // user already navigated away

  if (!camOk) {
    showCameraError("Camera unavailable", camErr);
    return;
  }

  if (statusMsg) statusMsg.textContent = "Starting stream…";

  // 2. Try MJPEG stream first — works on desktop & Android Chrome.
  //    iOS Safari silently refuses MJPEG in <img>; we detect that via a
  //    timeout: if the first frame doesn't arrive in 3s, fall back to polling.
  let mjpegResolved = false;
  const mjpegTimeout = setTimeout(() => {
    if (!mjpegResolved && cameraActive) {
      // MJPEG didn't fire onload — assume iOS/unsupported; switch to polling
      img.src = "";
      img.style.display = "none";
      pollStills(frameUrl, img, placeholder);
    }
  }, 3000);

  img.onload = () => {
    if (!cameraActive) return;
    mjpegResolved = true;
    clearTimeout(mjpegTimeout);
    cameraMode = "mjpeg";
    showCameraFeed(img, placeholder);
  };

  img.onerror = () => {
    if (!cameraActive) return;
    mjpegResolved = true;
    clearTimeout(mjpegTimeout);
    img.src = "";
    img.style.display = "none";
    // Fall back to still polling
    pollStills(frameUrl, img, placeholder);
  };

  img.src = streamUrl;
}

function pollStills(frameUrl, imgEl, placeholderEl) {
  if (!cameraActive) return;
  cameraMode = "poll";

  let firstFrame = true;

  function grab() {
    if (!cameraActive || cameraMode !== "poll") return;
    const tmp = new Image();
    tmp.onload = () => {
      if (!cameraActive) return;
      imgEl.src = tmp.src;
      if (firstFrame) {
        firstFrame = false;
        showCameraFeed(imgEl, placeholderEl);
      }
      // ~10 fps via polling
      stillPollTimer = setTimeout(grab, 100);
    };
    tmp.onerror = () => {
      if (!cameraActive) return;
      // Camera may have hiccuped — retry slower
      stillPollTimer = setTimeout(grab, 1000);
    };
    // Cache-bust so the browser doesn't serve a stale frame
    tmp.src = `${frameUrl}&t=${Date.now()}`;
  }

  grab();
}

function stopCameraFeed() {
  cameraActive = false;
  cameraMode   = null;
  clearTimeout(stillPollTimer);

  const img = document.getElementById("camera-img");
  if (img) {
    img.onload  = null;
    img.onerror = null;
    img.src     = "";
    img.style.display = "none";
  }
  showLiveBadge(false);

  const ph = document.getElementById("camera-placeholder");
  if (ph) ph.classList.remove("hidden");

  const msg = document.getElementById("camera-status-msg");
  if (msg) msg.textContent = "Connecting to camera…";

  setCameraConnLabel("Connecting…");
}
</script>
</body>
</html>"""

if __name__ == "__main__":
    try:
        import requests
    except ImportError:
        import subprocess, sys
        subprocess.check_call([sys.executable,"-m","pip","install","requests","-q"])
        import requests
    try:
        import aiohttp
    except ImportError:
        import subprocess, sys
        subprocess.check_call([sys.executable,"-m","pip","install","aiohttp","-q"])
        import aiohttp

    t = threading.Thread(target=scanner_thread, daemon=True)
    t.start()
    print("\n=== MAVEN Companion ===")
    print(f"Open in browser:  http://localhost:{APP_PORT}")
    print(f"Or on your phone: http://<this-computer-IP>:{APP_PORT}\n")
    app.run(host="0.0.0.0", port=APP_PORT, debug=False)