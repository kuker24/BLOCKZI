#!/usr/bin/env python3
import base64
import io
import json
import subprocess
import time
import itertools
import numpy as np
from PIL import Image

X0, Y0 = 41, 731
BOARD_W = 1138.0
BOARD_H = 1138.0
CW = BOARD_W / 8.0
CH = BOARD_H / 8.0

class ScrcpyClient:
    def __init__(self):
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
        return json.loads(res)

    def _init_mcp(self):
        self._send_req({
            "jsonrpc": "2.0",
            "id": self.req_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "blockzi-v2", "version": "2.0"}
            }
        })
        self.req_id += 1
        self._send_notify({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._send_req({
            "jsonrpc": "2.0",
            "id": self.req_id,
            "method": "tools/call",
            "params": {"name": "start_session", "arguments": {}}
        })
        self.req_id += 1
        print("[scrcpy] Active session initialized!")

    def screenshot(self):
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

    def swipe(self, x1, y1, x2, y2, duration=280):
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

    def tap(self, x, y):
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

    def close(self):
        self.proc.terminate()

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
            is_block = (mean_rgb[0] > 75 or mean_rgb[1] > 95 or (mean_rgb[2] > 190 and mean_rgb[1] > 140))
            if is_block:
                board[r, c] = 1
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

    for idx, (x1, x2) in enumerate(slots):
        sub = arr[dock_y1:dock_y2, x1:x2, :3]
        mask = (sub[:, :, 0] > 70) | (sub[:, :, 1] > 70) | (sub[:, :, 2] > 180)
        ys, xs = np.where(mask)
        if len(ys) < 30:
            continue

        w = xs.max() - xs.min() + 1
        h = ys.max() - ys.min() + 1
        cols = max(1, int(round(w / (65.0 * fx))))
        rows = max(1, int(round(h / (65.0 * fy))))

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
                    score = cl0 * 800 + gm0 * 200 - b1.sum() * 5
                    candidates.append((score, perm[0], r0, c0, cl0))
                    continue

                p1 = pieces[perm[1]]
                for r1 in range(8):
                    for c1 in range(8):
                        b2, g2, cl1, gm1 = simulate_placement(b1, g1, p1, r1, c1)
                        if b2 is None: continue

                        if n_pieces == 2:
                            score = (cl0 + cl1) * 800 + (gm0 + gm1) * 200 - b2.sum() * 5
                            candidates.append((score, perm[0], r0, c0, cl0))
                            continue

                        p2 = pieces[perm[2]]
                        for r2 in range(8):
                            for c2 in range(8):
                                b3, g3, cl2, gm2 = simulate_placement(b2, g2, p2, r2, c2)
                                if b3 is None: continue

                                score = (cl0 + cl1 + cl2) * 800 + (gm0 + gm1 + gm2) * 200 - b3.sum() * 5
                                candidates.append((score, perm[0], r0, c0, cl0))

    if not candidates:
        for p_idx, p in enumerate(pieces):
            for r in range(8):
                for c in range(8):
                    b1, g1, cl, gm = simulate_placement(board, gems, p, r, c)
                    if b1 is not None:
                        score = cl * 800 + gm * 200 - b1.sum() * 5
                        candidates.append((score, p_idx, r, c, cl))

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates

def calc_finger_target(p, r, c):
    board_cx = X0 + (c + p['cols'] / 2.0) * CW
    board_cy = Y0 + (r + p['rows'] / 2.0) * CH

    finger_x = board_cx - 0.14 * (board_cx - 610.0)
    finger_y = 1250 + (board_cy - 873) * 0.762
    return int(round(finger_x)), int(round(finger_y))

def run_loop(max_moves=50):
    client = ScrcpyClient()
    time.sleep(0.5)

    failed_attempts = {}

    try:
        step = 0
        while step < max_moves:
            step += 1
            im = client.screenshot()
            arr = np.array(im)
            fw, fh = im.size

            # Check if victory yellow button is present
            fy = fh / 2712.0
            fx = fw / 1220.0
            y_btn_min, y_btn_max = int(2050 * fy), int(2200 * fy)
            x_btn_min, x_btn_max = int(300 * fx), int(900 * fx)
            sub_btn = arr[y_btn_min:y_btn_max, x_btn_min:x_btn_max, :3]
            mask_yellow = (sub_btn[:, :, 0] > 200) & (sub_btn[:, :, 1] > 180) & (sub_btn[:, :, 2] < 80)
            if mask_yellow.sum() > 400:
                print(">>> [VICTORY DETECTED!] Tapping 'Level Selanjutnya' (600, 2127)...")
                client.tap(600, 2127)
                time.sleep(3.0)
                failed_attempts.clear()
                continue

            board, gems = analyze_board(arr, fw, fh)
            pieces = detect_dock_pieces(arr, fw, fh)

            print(f"\n[Move {step}] Board: {board.sum()}/64, Gems: {gems.sum()}, Dock pieces: {len(pieces)}")
            if len(pieces) == 0:
                print("Dock empty or waiting for animation...")
                time.sleep(0.8)
                continue

            candidates = solve_candidate_moves(board, gems, pieces)
            if not candidates:
                print("No moves found! Waiting...")
                time.sleep(1.0)
                continue

            # Pick top candidate that hasn't failed repeatedly
            chosen = None
            for cand in candidates:
                key = (cand[1], cand[2], cand[3])
                if failed_attempts.get(key, 0) < 2:
                    chosen = cand
                    break

            if chosen is None:
                # Reset failure cache and take top candidate
                failed_attempts.clear()
                chosen = candidates[0]

            score, p_idx, r, c, clears = chosen
            p = pieces[p_idx]
            fx_t, fy_t = calc_finger_target(p, r, c)
            dx, dy = p['dock_center']

            key = (p_idx, r, c)
            fails = failed_attempts.get(key, 0)
            if fails == 1:
                # Jitter by -15px to help snapping
                fx_t -= 15
                fy_t += 10

            print(f"Action: Slot {p['slot']+1} ({p['rows']}x{p['cols']}) -> Row {r}, Col {c} [clears: {clears}, score: {score}]")
            t_action_0 = time.time()
            client.swipe(dx, dy, fx_t, fy_t, duration=280)
            t_action_1 = time.time()
            print(f"Swipe completed in {(t_action_1 - t_action_0)*1000:.1f} ms")

            # Check outcome after move
            time.sleep(0.5 if clears > 0 else 0.25)
            im_after = client.screenshot()
            arr_after = np.array(im_after)
            pieces_after = detect_dock_pieces(arr_after, fw, fh)

            if len(pieces_after) >= len(pieces):
                print(f"Notice: piece {p_idx} not placed, recording failed attempt.")
                failed_attempts[key] = fails + 1
            else:
                failed_attempts.clear()

    finally:
        client.close()

if __name__ == '__main__':
    print("=== STARTING AUTONOMOUS SCRCPY ENGINE (OPSI 2) ===")
    run_loop(max_moves=30)
