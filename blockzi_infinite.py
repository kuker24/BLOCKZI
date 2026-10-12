#!/usr/bin/env python3
"""
Blockzi Infinite Autonomous Engine (Level 15 -> Level 90)
High-speed autonomous solver using Scrcpy protocol & lookahead heuristic AI.
Calibrated for Xiaomi 2306EPN60G (1220x2712).
"""

import base64
import io
import json
import logging
import os
import subprocess
import time
import itertools
import numpy as np
from PIL import Image

# Coordinates on Xiaomi (1220x2712)
X0, Y0 = 41, 731
BOARD_W = 1138.0
BOARD_H = 1138.0
CW = BOARD_W / 8.0
CH = BOARD_H / 8.0

TARGET_LEVEL = 90
LOG_FILE = "/home/fahmi/Downloads/UNF/shop/blockzi_run.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="a"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("blockzi")

class ScrcpyClient:
    def __init__(self):
        self.proc = None
        self.req_id = 1
        self.start()

    def start(self):
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass
        self.proc = subprocess.Popen(
            ['node', '/home/fahmi/.npm/_npx/d2b21a18eddad784/node_modules/scrcpy-mcp/dist/index.js'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        self.req_id = 1
        self._init_mcp()

    def _send_notify(self, msg):
        self.proc.stdin.write(json.dumps(msg) + '\n')
        self.proc.stdin.flush()

    def _send_req(self, msg):
        self.proc.stdin.write(json.dumps(msg) + '\n')
        self.proc.stdin.flush()
        res = self.proc.stdout.readline()
        if not res:
            raise ConnectionError("Scrcpy process stdout closed")
        return json.loads(res)

    def _init_mcp(self):
        self._send_req({
            "jsonrpc": "2.0",
            "id": self.req_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "blockzi-infinite", "version": "3.3"}
            }
        })
        self.req_id += 1
        self._send_notify({"jsonrpc": "2.0", "method": "notifications/initialized"})
        res = self._send_req({
            "jsonrpc": "2.0",
            "id": self.req_id,
            "method": "tools/call",
            "params": {"name": "start_session", "arguments": {}}
        })
        self.req_id += 1
        log.info("[Scrcpy] Active session initialized successfully.")

    def screenshot(self):
        try:
            res = self._send_req({
                "jsonrpc": "2.0",
                "id": self.req_id,
                "method": "tools/call",
                "params": {"name": "screenshot", "arguments": {}}
            })
            self.req_id += 1
            b64 = res['result']['content'][0]['data']
            img_bytes = base64.b64decode(b64)
            return Image.open(io.BytesIO(img_bytes))
        except Exception as e:
            log.warning(f"[Scrcpy] Screenshot error: {e}. Reconnecting...")
            self.start()
            return self.screenshot()

    def swipe(self, x1, y1, x2, y2, duration=280):
        try:
            res = self._send_req({
                "jsonrpc": "2.0",
                "id": self.req_id,
                "method": "tools/call",
                "params": {
                    "name": "swipe",
                    "arguments": {"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2), "duration": duration}
                }
            })
            self.req_id += 1
            return res
        except Exception as e:
            log.warning(f"[Scrcpy] Swipe error: {e}. Reconnecting...")
            self.start()
            return self.swipe(x1, y1, x2, y2, duration)

    def tap(self, x, y):
        try:
            res = self._send_req({
                "jsonrpc": "2.0",
                "id": self.req_id,
                "method": "tools/call",
                "params": {
                    "name": "tap",
                    "arguments": {"x": int(x), "y": int(y)}
                }
            })
            self.req_id += 1
            return res
        except Exception as e:
            log.warning(f"[Scrcpy] Tap error: {e}. Reconnecting...")
            self.start()
            return self.tap(x, y)

    def close(self):
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass


def analyze_board(arr, frame_w, frame_h):
    fx = frame_w / 1220.0
    fy = frame_h / 2712.0
    bx0 = X0 * fx
    by0 = Y0 * fy
    bcw = CW * fx
    bch = CH * fy

    board = np.zeros((8, 8), dtype=int)
    gems = np.zeros((8, 8), dtype=int)
    for r in range(8):
        for c in range(8):
            cx = int(bx0 + (c + 0.5) * bcw)
            cy = int(by0 + (r + 0.5) * bch)
            patch = arr[cy-3:cy+3, cx-3:cx+3, :3]
            mean_rgb = patch.mean(axis=(0, 1))
            # Block detection
            is_block = (mean_rgb[0] > 75 or mean_rgb[1] > 95 or (mean_rgb[2] > 190 and mean_rgb[1] > 140))
            if is_block:
                board[r, c] = 1
                # Gem detection
                g_green = (mean_rgb[1] > 170 and mean_rgb[0] < 120)
                g_purple = (mean_rgb[0] > 190 and mean_rgb[2] > 190 and mean_rgb[1] < 130)
                g_orange = (mean_rgb[0] > 200 and 120 < mean_rgb[1] < 200 and mean_rgb[2] < 70)
                if g_green or g_purple or g_orange:
                    gems[r, c] = 1
    return board, gems


def detect_dock_pieces(arr, frame_w, frame_h):
    fx = frame_w / 1220.0
    fy = frame_h / 2712.0
    slots = [(int(50*fx), int(420*fx)), (int(420*fx), int(800*fx)), (int(800*fx), int(1170*fx))]
    dock_y1 = int(1930 * fy)
    dock_y2 = int(2180 * fy)
    pieces = []

    def get_dim_count(dim):
        if dim > 230 * fx: return 5
        elif dim > 160 * fx: return 3
        elif dim > 95 * fx: return 2
        else: return 1

    for idx, (x1, x2) in enumerate(slots):
        sub = arr[dock_y1:dock_y2, x1:x2, :3]
        mask = (sub[:, :, 0] > 70) | (sub[:, :, 1] > 70) | (sub[:, :, 2] > 180)
        ys, xs = np.where(mask)
        if len(ys) < 40:
            continue

        w = xs.max() - xs.min() + 1
        h = ys.max() - ys.min() + 1
        cols = get_dim_count(w)
        rows = get_dim_count(h)

        cw_d = w / float(cols)
        rh_d = h / float(rows)

        shape = np.zeros((rows, cols), dtype=int)
        for r in range(rows):
            for c in range(cols):
                cx = int(xs.min() + (c + 0.5) * cw_d)
                cy = int(ys.min() + (r + 0.5) * rh_d)
                patch = sub[cy-2:cy+2, cx-2:cx+2, :3]
                mean_rgb = patch.mean(axis=(0, 1))
                if (mean_rgb[0] > 70 or mean_rgb[1] > 70 or mean_rgb[2] > 180):
                    shape[r, c] = 1

        cx_frame = (xs.min() + xs.max()) // 2 + x1
        cy_frame = (ys.min() + ys.max()) // 2 + dock_y1
        native_cx = int(round(cx_frame / fx))
        native_cy = int(round(cy_frame / fy))

        pieces.append({
            'slot': idx,
            'shape': shape,
            'dock_center': (native_cx, native_cy),
            'rows': rows,
            'cols': cols
        })
    return pieces


def simulate_placement(b, g, p, r0, c0):
    if r0 + p['rows'] > 8 or c0 + p['cols'] > 8:
        return None, None, 0, 0
    for dr in range(p['rows']):
        for dc in range(p['cols']):
            if p['shape'][dr, dc] == 1 and b[r0 + dr, c0 + dc] == 1:
                return None, None, 0, 0
    nb = b.copy()
    ng = g.copy()
    for dr in range(p['rows']):
        for dc in range(p['cols']):
            if p['shape'][dr, dc] == 1:
                nb[r0 + dr, c0 + dc] = 1
    full_rows = [r for r in range(8) if nb[r].sum() == 8]
    full_cols = [c for c in range(8) if nb[:, c].sum() == 8]
    clears = len(full_rows) + len(full_cols)
    gems_collected = 0
    for r in full_rows:
        gems_collected += int(ng[r, :].sum())
        nb[r, :] = 0
        ng[r, :] = 0
    for c in full_cols:
        gems_collected += int(ng[:, c].sum())
        nb[:, c] = 0
        ng[:, c] = 0
    return nb, ng, clears, gems_collected


def count_isolated_holes(board):
    holes = 0
    for r in range(8):
        for c in range(8):
            if board[r, c] == 0:
                neighbors = 0
                if r > 0 and board[r-1, c] == 1: neighbors += 1
                if r < 7 and board[r+1, c] == 1: neighbors += 1
                if c > 0 and board[r, c-1] == 1: neighbors += 1
                if c < 7 and board[r, c+1] == 1: neighbors += 1
                if neighbors >= 3:
                    holes += 1
    return holes


def solve_candidate_moves(board, gems, pieces):
    candidates = []
    n_pieces = len(pieces)
    if n_pieces == 0:
        return candidates

    for perm in itertools.permutations(range(n_pieces)):
        p0 = pieces[perm[0]]
        for r0 in range(8):
            for c0 in range(8):
                b1, g1, cl0, gm0 = simulate_placement(board, gems, p0, r0, c0)
                if b1 is None: continue

                if n_pieces == 1:
                    score = cl0 * 1500 + gm0 * 400 - b1.sum() * 15 - count_isolated_holes(b1) * 35
                    candidates.append((score, perm[0], r0, c0, cl0))
                    continue

                p1 = pieces[perm[1]]
                for r1 in range(8):
                    for c1 in range(8):
                        b2, g2, cl1, gm1 = simulate_placement(b1, g1, p1, r1, c1)
                        if b2 is None: continue

                        if n_pieces == 2:
                            score = (cl0 + cl1) * 1500 + (gm0 + gm1) * 400 - b2.sum() * 15 - count_isolated_holes(b2) * 35
                            candidates.append((score, perm[0], r0, c0, cl0))
                            continue

                        p2 = pieces[perm[2]]
                        for r2 in range(8):
                            for c2 in range(8):
                                b3, g3, cl2, gm2 = simulate_placement(b2, g2, p2, r2, c2)
                                if b3 is None: continue

                                score = (cl0 + cl1 + cl2) * 1500 + (gm0 + gm1 + gm2) * 400 - b3.sum() * 15 - count_isolated_holes(b3) * 35
                                candidates.append((score, perm[0], r0, c0, cl0))

    if not candidates:
        for p_idx, p in enumerate(pieces):
            for r in range(8):
                for c in range(8):
                    b1, g1, cl, gm = simulate_placement(board, gems, p, r, c)
                    if b1 is not None:
                        score = cl * 1500 + gm * 400 - b1.sum() * 15 - count_isolated_holes(b1) * 35
                        candidates.append((score, p_idx, r, c, cl))

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates


def calc_finger_target(p, r, c):
    board_cx = X0 + (c + p['cols'] / 2.0) * CW
    board_cy = Y0 + (r + p['rows'] / 2.0) * CH
    dock_cx = p['dock_center'][0]

    # Exact slot offset calibrated empirically
    if dock_cx < 420:
        offset_x = -142.0
    elif dock_cx > 800:
        offset_x = 110.0
    else:
        offset_x = 0.0

    finger_x = board_cx + offset_x
    finger_y = board_cy + 322.0
    return int(round(finger_x)), int(round(finger_y))


def check_victory(arr, fw, fh):
    """Golden stars appear ONLY on the Victory screen (never in gameplay or defeat)."""
    y1, y2 = int(fh * 0.15), int(fh * 0.25)
    stars = (arr[y1:y2, :, 0] > 220) & (arr[y1:y2, :, 1] > 180) & (arr[y1:y2, :, 2] < 50)
    return stars.sum() > 2000


def check_defeat(arr, fw, fh):
    """Defeat modal has 'Main Lagi' yellow button & cream card, but zero golden stars."""
    if check_victory(arr, fw, fh):
        return False
    fy = fh / 2712.0
    fx = fw / 1220.0
    sub = arr[int(2050*fy):int(2250*fy), int(200*fx):int(1000*fx), :3]
    yellow = (sub[:, :, 0] > 200) & (sub[:, :, 1] > 180) & (sub[:, :, 2] < 100)
    center = arr[int(900*fy):int(1200*fy), int(200*fx):int(1000*fx), :3]
    cream = (center[:, :, 0] > 240) & (center[:, :, 1] > 230) & (center[:, :, 2] > 200)
    return yellow.sum() > 1000 and cream.sum() > 500


def run_infinite():
    current_level = 15
    log.info(f"=== BLOCKZI AUTONOMOUS SPEEDRUN STARTED (TARGET: LEVEL {TARGET_LEVEL}) ===")

    client = ScrcpyClient()
    time.sleep(0.5)

    failed_attempts = {}
    consecutive_empty_dock = 0
    level_moves = 0
    level_start_time = time.time()

    try:
        while current_level <= TARGET_LEVEL:
            im = client.screenshot()
            arr = np.array(im)
            fw, fh = im.size

            # 1. Check Victory Screen (Golden stars)
            if check_victory(arr, fw, fh):
                duration = time.time() - level_start_time
                log.info(f">>> [LEVEL {current_level} CLEARED!] in {level_moves} moves ({duration:.1f}s)")
                im.save(f"/tmp/antigravity/level_{current_level}_cleared.png")

                # Tap 'Level Selanjutnya'
                client.tap(600, 2127)
                time.sleep(3.0)

                current_level += 1
                level_moves = 0
                failed_attempts.clear()
                consecutive_empty_dock = 0
                level_start_time = time.time()

                if current_level > TARGET_LEVEL:
                    log.info(f">>> CONGRATULATIONS! REACHED TARGET LEVEL {TARGET_LEVEL}!")
                    break

                log.info(f"\n==========================================")
                log.info(f"          STARTING LEVEL {current_level}")
                log.info(f"==========================================")
                continue

            # 2. Check Defeat Screen
            if check_defeat(arr, fw, fh):
                log.warning(f"[LEVEL {current_level} DEFEAT DETECTED] Retrying level...")
                client.tap(600, 2127)  # Tap 'Main Lagi'
                time.sleep(3.0)
                failed_attempts.clear()
                level_moves = 0
                continue

            # 3. Detect Board & Dock
            board, gems = analyze_board(arr, fw, fh)
            pieces = detect_dock_pieces(arr, fw, fh)

            if len(pieces) == 0:
                consecutive_empty_dock += 1
                if consecutive_empty_dock >= 4:
                    log.warning("[Engine] Dock empty for multiple frames. Waiting...")
                    time.sleep(0.8)
                    consecutive_empty_dock = 0
                else:
                    time.sleep(0.4)
                continue
            else:
                consecutive_empty_dock = 0

            # 4. Lookahead Solver
            candidates = solve_candidate_moves(board, gems, pieces)
            if not candidates:
                log.warning(f"[Engine] No valid moves on board ({board.sum()}/64 blocks). Waiting...")
                time.sleep(0.8)
                continue

            # Pick best candidate that hasn't failed repeatedly
            chosen = None
            for cand in candidates:
                key = (cand[1], cand[2], cand[3])
                if failed_attempts.get(key, 0) < 2:
                    chosen = cand
                    break

            if chosen is None:
                failed_attempts.clear()
                chosen = candidates[0]

            score, p_idx, r, c, clears = chosen
            p = pieces[p_idx]
            fx_t, fy_t = calc_finger_target(p, r, c)
            dx, dy = p['dock_center']

            key = (p_idx, r, c)
            fails = failed_attempts.get(key, 0)
            if fails == 1:
                # Slight micro-jitter if first attempt was slightly off
                fx_t -= 6
                fy_t += 6

            level_moves += 1
            t0 = time.time()
            client.swipe(dx, dy, fx_t, fy_t, duration=280)
            t_swipe = (time.time() - t0) * 1000

            log.info(f"[Lvl {current_level} | Move {level_moves}] Slot {p['slot']+1} ({p['rows']}x{p['cols']}) -> (r{r}, c{c}) [cl:{clears}, sc:{score:.0f}] ({t_swipe:.0f}ms)")

            # Outcome validation (crucial: wait longer if line clears so board finish dissolving!)
            wait_time = 1.25 if clears > 0 else 0.45
            time.sleep(wait_time)

            im_after = client.screenshot()
            arr_after = np.array(im_after)
            pieces_after = detect_dock_pieces(arr_after, fw, fh)

            if len(pieces_after) >= len(pieces):
                failed_attempts[key] = fails + 1
            else:
                failed_attempts.clear()

    except KeyboardInterrupt:
        log.info("[Engine] Stopped by user.")
    except Exception as e:
        log.error(f"[Engine] Unexpected exception: {e}", exc_info=True)
    finally:
        client.close()
        log.info("[Engine] Session closed.")

if __name__ == '__main__':
    run_infinite()
