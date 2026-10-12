#!/usr/bin/env python3
import io
import time
import itertools
import subprocess
import numpy as np
from PIL import Image

X0, Y0 = 41, 731
BOARD_W = 1138.0
BOARD_H = 1138.0
CW = BOARD_W / 8.0
CH = BOARD_H / 8.0
TOUCH_OFFSET_Y = 190

def capture_screen():
    proc = subprocess.run(['adb', 'exec-out', 'screencap', '-p'], stdout=subprocess.PIPE, check=True)
    return np.array(Image.open(io.BytesIO(proc.stdout)))

def analyze_board(arr):
    board = np.zeros((8, 8), dtype=int)
    gems = np.zeros((8, 8), dtype=int)
    for r in range(8):
        for c in range(8):
            cx = int(X0 + (c + 0.5) * CW)
            cy = int(Y0 + (r + 0.5) * CH)
            patch = arr[cy-10:cy+10, cx-10:cx+10, :3]
            mean_rgb = patch.mean(axis=(0, 1))
            is_block = (mean_rgb[0] > 80 or mean_rgb[1] > 100 or (mean_rgb[2] > 200 and mean_rgb[1] > 150))
            if is_block:
                board[r, c] = 1
                # check gem in center of cell
                center_mean = patch[7:13, 7:13].mean(axis=(0, 1))
                # Green gem, purple gem, or orange gem
                if (center_mean[1] > 180 and center_mean[0] < 120) or \
                   (center_mean[0] > 200 and center_mean[2] > 200 and center_mean[1] < 120) or \
                   (center_mean[0] > 220 and 130 < center_mean[1] < 210 and center_mean[2] < 70):
                    gems[r, c] = 1
    return board, gems

def detect_dock_pieces(arr):
    slots = [(50, 420), (420, 800), (800, 1170)]
    dock_y1, dock_y2 = 1930, 2180
    pieces = []
    
    for idx, (x1, x2) in enumerate(slots):
        sub = arr[dock_y1:dock_y2, x1:x2, :3]
        mask = (sub[:, :, 0] > 70) | (sub[:, :, 1] > 70) | (sub[:, :, 2] > 180)
        ys, xs = np.where(mask)
        if len(ys) < 80:
            continue
            
        bx1, bx2 = xs.min() + x1, xs.max() + x1
        by1, by2 = ys.min() + dock_y1, ys.max() + dock_y1
        w = bx2 - bx1 + 1
        h = by2 - by1 + 1
        
        cols = max(1, int(round(w / 65.0)))
        rows = max(1, int(round(h / 65.0)))
        
        cw_d = w / float(cols)
        rh_d = h / float(rows)
        
        shape = np.zeros((rows, cols), dtype=int)
        for r in range(rows):
            for c in range(cols):
                cx = int(bx1 + (c + 0.5) * cw_d)
                cy = int(by1 + (r + 0.5) * rh_d)
                patch = arr[cy-5:cy+5, cx-5:cx+5, :3]
                mean_rgb = patch.mean(axis=(0, 1))
                if (mean_rgb[0] > 70 or mean_rgb[1] > 70 or mean_rgb[2] > 180):
                    shape[r, c] = 1
                    
        center_x = (bx1 + bx2) // 2
        center_y = (by1 + by2) // 2
        pieces.append({
            'slot': idx,
            'shape': shape,
            'dock_center': (center_x, center_y),
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

def solve_best_sequence(board, gems, pieces):
    best_seq = None
    best_score = -999999
    
    n_pieces = len(pieces)
    if n_pieces == 0:
        return None
        
    for perm in itertools.permutations(range(n_pieces)):
        p0 = pieces[perm[0]]
        for r0 in range(8):
            for c0 in range(8):
                b1, g1, cl0, gm0 = simulate_placement(board, gems, p0, r0, c0)
                if b1 is None: continue
                
                if n_pieces == 1:
                    score = cl0 * 600 + gm0 * 150 - b1.sum() * 5
                    if score > best_score:
                        best_score = score
                        best_seq = [(perm[0], r0, c0, cl0)]
                    continue
                    
                p1 = pieces[perm[1]]
                for r1 in range(8):
                    for c1 in range(8):
                        b2, g2, cl1, gm1 = simulate_placement(b1, g1, p1, r1, c1)
                        if b2 is None: continue
                        
                        if n_pieces == 2:
                            total_cl = cl0 + cl1
                            total_gm = gm0 + gm1
                            score = total_cl * 600 + total_gm * 150 - b2.sum() * 5
                            if score > best_score:
                                best_score = score
                                best_seq = [
                                    (perm[0], r0, c0, cl0),
                                    (perm[1], r1, c1, cl1)
                                ]
                            continue
                            
                        p2 = pieces[perm[2]]
                        for r2 in range(8):
                            for c2 in range(8):
                                b3, g3, cl2, gm2 = simulate_placement(b2, g2, p2, r2, c2)
                                if b3 is None: continue
                                
                                total_cl = cl0 + cl1 + cl2
                                total_gm = gm0 + gm1 + gm2
                                score = total_cl * 600 + total_gm * 150 - b3.sum() * 5
                                if score > best_score:
                                    best_score = score
                                    best_seq = [
                                        (perm[0], r0, c0, cl0),
                                        (perm[1], r1, c1, cl1),
                                        (perm[2], r2, c2, cl2)
                                    ]
                                    
    # If no 3-piece full sequence fits, fallback to best single piece move
    if best_seq is None:
        for p_idx, p in enumerate(pieces):
            for r in range(8):
                for c in range(8):
                    b1, g1, cl, gm = simulate_placement(board, gems, p, r, c)
                    if b1 is not None:
                        score = cl * 600 + gm * 150 - b1.sum() * 5
                        if score > best_score:
                            best_score = score
                            best_seq = [(p_idx, r, c, cl)]
                            
    return best_seq

def drag_and_drop(x1, y1, x2, y2, steps=8, step_sleep=0.02):
    subprocess.run(['adb', 'shell', 'input', 'motionevent', 'DOWN', str(x1), str(y1)], check=False, timeout=5)
    time.sleep(0.06)
    for i in range(1, steps + 1):
        x = int(x1 + (x2 - x1) * i / steps)
        y = int(y1 + (y2 - y1) * i / steps)
        subprocess.run(['adb', 'shell', 'input', 'motionevent', 'MOVE', str(x), str(y)], check=False, timeout=5)
        time.sleep(step_sleep)
    time.sleep(0.18)
    subprocess.run(['adb', 'shell', 'input', 'motionevent', 'UP', str(x2), str(y2)], check=False, timeout=5)
    time.sleep(0.3)

def check_victory(arr):
    # Check if a level complete banner appears or 'Level Selesai' / 'Klaim' / 'Lanjut'
    # Victory banner usually appears around center y: 1200..1800
    # Let's inspect center button
    return False

def run_step():
    arr = capture_screen()
    board, gems = analyze_board(arr)
    pieces = detect_dock_pieces(arr)
    
    print(f'Board occupied: {board.sum()}/64 cells, gems: {gems.sum()}, pieces in dock: {len(pieces)}')
    if len(pieces) == 0:
        print('Dock is currently empty, waiting for new pieces...')
        time.sleep(1.0)
        return False
        
    seq = solve_best_sequence(board, gems, pieces)
    if not seq:
        print('No valid sequence found! Game may be stuck or over.')
        return False
        
    # Execute the first move of the sequence
    p_idx, r, c, clears = seq[0]
    p = pieces[p_idx]
    
    board_cx = X0 + (c + p['cols'] / 2.0) * CW
    board_cy = Y0 + (r + p['rows'] / 2.0) * CH
    finger_x = int(round(board_cx))
    finger_y = int(round(board_cy + TOUCH_OFFSET_Y))
    
    dock_x, dock_y = p['dock_center']
    print(f"Executing: Slot {p['slot']+1} ({p['rows']}x{p['cols']}) -> Row {r}, Col {c} (finger {finger_x}, {finger_y}) [Predicted clears: {clears}]")
    drag_and_drop(dock_x, dock_y, finger_x, finger_y)
    
    # If a clear happened, give an extra moment for animation
    if clears > 0:
        time.sleep(0.8)
    else:
        time.sleep(0.4)
    return True

if __name__ == '__main__':
    print('Starting Autonomous Blockzi Bot...')
    for step in range(30):
        print(f'--- Step {step + 1} ---')
        ok = run_step()
        if not ok:
            time.sleep(1.0)
