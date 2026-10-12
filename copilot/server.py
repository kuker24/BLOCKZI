#!/usr/bin/env python3
"""
Blockzi Co-Pilot Web Server
Flask backend serving the interactive visual assistant.
"""

import base64
import hmac
import io
import os
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path
from flask import Flask, jsonify, render_template, request
from PIL import Image
import numpy as np

# Add repo root and autobot to sys.path
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))
if str(_repo_root / "autobot") not in sys.path:
    sys.path.insert(0, str(_repo_root / "autobot"))

import blockzi_config as cfg
from solver import analyze_board, detect_dock_pieces, solve_full_sequence, check_game_state
from engine import Pilot, SPEEDS, read_level  # noqa: E402

app = Flask(__name__, template_folder='templates', static_folder='static')

FALLBACK_IMAGE = str(cfg.SCREEN_DIR / 'current_screen.png')


def check_auth():
    """Verify BLOCKZI_TOKEN if configured via Authorization or X-Blockzi-Token header."""
    if not cfg.TOKEN:
        return True
    token = ""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    elif "X-Blockzi-Token" in request.headers:
        token = request.headers.get("X-Blockzi-Token", "").strip()
    return hmac.compare_digest(token, cfg.TOKEN)


def check_csrf():
    """Ensure Origin / Referer matches host if present on state-mutating requests."""
    origin = request.headers.get("Origin")
    if origin:
        parsed = urllib.parse.urlparse(origin)
        if parsed.netloc and parsed.netloc != request.host:
            return False
    referer = request.headers.get("Referer")
    if referer and not origin:
        parsed = urllib.parse.urlparse(referer)
        if parsed.netloc and parsed.netloc != request.host:
            return False
    return True


def is_device_connected():
    try:
        res = subprocess.run(['adb', 'devices'], stdout=subprocess.PIPE, text=True, timeout=2)
        lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        for l in lines[1:]:
            parts = l.split()
            if len(parts) >= 2 and parts[1] == 'device':
                return True
        return False
    except Exception:
        return False


def capture_screenshot():
    latest_path = str(cfg.SCREEN_DIR / 'latest_copilot_screen.png')
    if is_device_connected():
        try:
            res = subprocess.run(['adb', 'exec-out', 'screencap', '-p'], stdout=subprocess.PIPE, timeout=4)
            if len(res.stdout) > 10000:
                im = Image.open(io.BytesIO(res.stdout))
                im.save(latest_path)
                return im, True
        except Exception:
            pass

    # Fallback to existing screen files
    for p in [latest_path, FALLBACK_IMAGE, str(cfg.SCREEN_DIR / 'current_check.png')]:
        if os.path.exists(p):
            try:
                return Image.open(p), False
            except Exception:
                pass

    # Offline/test fallback: return a blank 1220x2712 canvas
    dummy = Image.new('RGB', (1220, 2712), color=(20, 20, 30))
    dummy.save(latest_path)
    return dummy, False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def status():
    connected = is_device_connected()
    return jsonify({
        'device_connected': connected
    })

def encode_preview(im):
    fw, fh = im.size
    preview_im = im.resize((610, int(610 * fh / fw)), Image.Resampling.BILINEAR)
    if preview_im.mode in ("RGBA", "P", "LA"):
        preview_im = preview_im.convert("RGB")
    buf = io.BytesIO()
    preview_im.save(buf, format="JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")


class AutoController:
    """Background player for the web dashboard. One ADB owner at a time."""

    def __init__(self):
        self._state = threading.Lock()
        self._adb = threading.Lock()
        self.enabled = False
        self.speed = "adaptive"
        self.use_boosters = True
        self.use_revive = True
        self.snapshot = {
            "enabled": False,
            "speed": "adaptive",
            "boosters": True,
            "revive": True,
            "revives": 0,
            "boost_counts": {"extra": None, "bomb": None, "remove": None},
            "level": None,
            "ok": 0,
            "fail": 0,
            "moves": 0,
            "message": "Manual. Tekan Mulai Auto untuk main sendiri.",
            "event": "idle",
            "done": False,
            "solution": None,
        }
        self._pilot = Pilot()
        self._thread = threading.Thread(target=self._loop, name="blockzi-auto", daemon=True)
        self._thread.start()

    def status(self):
        with self._state:
            return dict(self.snapshot)

    def configure(self, enabled=None, speed=None, boosters=None, revive=None):
        with self._state:
            if speed is not None:
                key = str(speed).lower()
                if key not in SPEEDS:
                    raise ValueError(f"Kecepatan tidak dikenal: {speed}")
                self.speed = key
            if boosters is not None:
                self.use_boosters = bool(boosters)
                self._pilot.use_boosters = self.use_boosters
            if revive is not None:
                self.use_revive = bool(revive)
                self._pilot.use_revive = self.use_revive
            if enabled is not None:
                self.enabled = bool(enabled)
                if self.enabled:
                    self._pilot.done = False
                    self.snapshot["message"] = "Auto berjalan."
            self.snapshot["enabled"] = self.enabled
            self.snapshot["speed"] = self.speed
            self.snapshot["boosters"] = self.use_boosters
            self.snapshot["revive"] = self.use_revive
            if not self.enabled:
                self.snapshot["message"] = "Auto berhenti. Mode manual."
            return dict(self.snapshot)

    def _publish(self, result):
        im = result.get("image")
        solution = None
        if im is not None:
            solution = {
                "status": "ok",
                "device_connected": True,
                "game_state": result.get("game_state"),
                "board": result.get("board"),
                "gems": result.get("gems"),
                "pieces": result.get("pieces") or [],
                "sequence": result.get("sequence") or [],
                "best_score": result.get("best_score") or 0,
                "solve_time_ms": result.get("solve_time_ms") or 0,
                "total_time_ms": result.get("solve_time_ms") or 0,
                "image_b64": encode_preview(im),
                "screen_dims": result.get("screen_dims"),
                "level": result.get("level"),
            }
        with self._state:
            self.snapshot.update({
                "enabled": self.enabled,
                "speed": self.speed,
                "level": result.get("level"),
                "ok": result.get("ok", 0),
                "fail": result.get("fail", 0),
                "moves": result.get("moves", 0),
                "message": result.get("message") or "",
                "boosters": self.use_boosters,
                "revive": self.use_revive,
                "revives": result.get("revives", 0),
                "boost_counts": result.get("boost_counts") or self.snapshot.get("boost_counts"),
                "event": result.get("event") or "idle",
                "done": bool(result.get("done")),
                "solution": sanitize_json(solution) if solution else self.snapshot.get("solution"),
            })
            if result.get("done"):
                self.enabled = False
                self.snapshot["enabled"] = False

    def _loop(self):
        while True:
            with self._state:
                enabled = self.enabled
                speed = self.speed
                use_boosters = self.use_boosters
                use_revive = self.use_revive
            if not enabled:
                time.sleep(0.25)
                continue
            try:
                self._pilot.use_boosters = use_boosters
                self._pilot.use_revive = use_revive
                with self._adb:
                    result = self._pilot.tick(speed)
                self._publish(result)
            except Exception as exc:
                with self._state:
                    self.snapshot["message"] = f"Error: {exc}"
                    self.snapshot["event"] = "error"
                time.sleep(1.0)


auto = AutoController()


def sanitize_json(obj):
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (np.integer, int)):
        return int(obj)
    elif isinstance(obj, (np.floating, float)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {k: sanitize_json(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [sanitize_json(x) for x in obj]
    return obj

@app.route('/api/auto', methods=['GET', 'POST'])
def auto_route():
    if request.method == 'POST':
        if not check_csrf():
            return jsonify({'status': 'error', 'message': 'Forbidden: Origin mismatch'}), 403
        if not check_auth():
            return jsonify({'status': 'error', 'message': 'Unauthorized: invalid token'}), 401
        if not request.is_json:
            return jsonify({'status': 'error', 'message': 'Content-Type must be application/json'}), 415

        data = request.json or {}
        try:
            snap = auto.configure(
                enabled=data.get('enabled') if 'enabled' in data else None,
                speed=data.get('speed') if 'speed' in data else None,
                boosters=data.get('boosters') if 'boosters' in data else None,
                revive=data.get('revive') if 'revive' in data else None,
            )
        except ValueError as exc:
            return jsonify({'status': 'error', 'message': str(exc)}), 400
        return jsonify({'status': 'ok', **{k: v for k, v in snap.items() if k != 'solution'}, 'speeds': list(SPEEDS)})
    snap = auto.status()
    return jsonify(sanitize_json({'status': 'ok', 'speeds': list(SPEEDS), **snap}))


@app.route('/api/solve')
def solve():
    t_start = time.time()
    if auto.enabled:
        snap = auto.status()
        cached = snap.get('solution')
        if cached:
            return jsonify(cached)
    try:
        with auto._adb:
            im, connected = capture_screenshot()
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e),
            'device_connected': False
        }), 500

    fw, fh = im.size
    arr = np.array(im)

    game_state = check_game_state(arr, fw, fh)
    board, gems = analyze_board(arr, fw, fh)
    pieces = detect_dock_pieces(arr, fw, fh)

    sequence, score, solve_ms = solve_full_sequence(board, gems, pieces, max_ms=cfg.SOLVER_MAX_MS)

    img_b64 = encode_preview(im)
    level = read_level(arr) if game_state == 'PLAYING' else None

    total_ms = (time.time() - t_start) * 1000

    resp = {
        'status': 'ok',
        'device_connected': connected,
        'game_state': game_state,
        'board': board.tolist(),
        'gems': gems.tolist(),
        'pieces': pieces,
        'sequence': sequence,
        'best_score': score,
        'solve_time_ms': round(solve_ms, 1),
        'total_time_ms': round(total_ms, 1),
        'image_b64': img_b64,
        'screen_dims': {'w': fw, 'h': fh},
        'level': level,
    }
    return jsonify(sanitize_json(resp))

@app.route('/api/action', methods=['POST'])
def action():
    if not check_csrf():
        return jsonify({'status': 'error', 'message': 'Forbidden: Origin mismatch'}), 403
    if not check_auth():
        return jsonify({'status': 'error', 'message': 'Unauthorized: invalid token'}), 401
    if not request.is_json:
        return jsonify({'status': 'error', 'message': 'Content-Type must be application/json'}), 415

    data = request.json or {}
    act = data.get('action')
    if not is_device_connected():
        return jsonify({'status': 'error', 'message': 'Device not connected'}), 400

    try:
        with auto._adb:
            if act in ('retry', 'next'):
                # Tap (600, 2127) for both Main Lagi and Level Selanjutnya
                subprocess.run(['adb', 'shell', 'input', 'tap', '600', '2127'], timeout=3)
                return jsonify({'status': 'ok', 'action': act})
            elif act == 'tap':
                try:
                    x = int(data.get('x', 600))
                    y = int(data.get('y', 2127))
                except (ValueError, TypeError):
                    return jsonify({'status': 'error', 'message': 'Invalid integer coordinates'}), 400
                if x < 0 or x > 1220 or y < 0 or y > 2712:
                    return jsonify({'status': 'error', 'message': 'Coordinates out of bounds'}), 400
                subprocess.run(['adb', 'shell', 'input', 'tap', str(x), str(y)], timeout=3)
                return jsonify({'status': 'ok', 'action': 'tap', 'x': x, 'y': y})
            return jsonify({'status': 'error', 'message': f'Unknown action {act}'}), 400
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    host = cfg.HOST
    port = cfg.PORT
    if host not in ('127.0.0.1', 'localhost', '::1') and not cfg.TOKEN:
        print("=" * 72)
        print("⚠️  WARNING: Server bound to non-loopback host without BLOCKZI_TOKEN!")
        print("   Anyone on the local network can control the connected device.")
        print("=" * 72)
    print(f"🚀 Blockzi Co-Pilot Running on http://{host}:{port}")
    app.run(host=host, port=port, debug=False, threaded=True)
