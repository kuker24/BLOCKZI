#!/usr/bin/env python3
import io
import time
import subprocess
import numpy as np
from PIL import Image

def capture_screen():
    proc = subprocess.run(['adb', 'exec-out', 'screencap', '-p'], stdout=subprocess.PIPE, check=True)
    return np.array(Image.open(io.BytesIO(proc.stdout)))

def analyze_board(arr):
    x0, y0 = 41, 731
    cw = 1138 / 8.0
    ch = 1138 / 8.0
    
    board = np.zeros((8, 8), dtype=int)
    for r in range(8):
        for c in range(8):
            cx = int(x0 + (c + 0.5) * cw)
            cy = int(y0 + (r + 0.5) * ch)
            patch = arr[cy-10:cy+10, cx-10:cx+10, :3]
            mean_rgb = patch.mean(axis=(0, 1))
            is_block = (mean_rgb[0] > 80 or mean_rgb[1] > 100 or (mean_rgb[2] > 200 and mean_rgb[1] > 150))
            if is_block:
                board[r, c] = 1
    return board

def detect_dock_pieces(arr):
    # 3 dock slots
    slots = [(50, 420), (420, 800), (800, 1170)]
    dock_y1, dock_y2 = 1930, 2180
    pieces = []
    
    for idx, (x1, x2) in enumerate(slots):
        sub = arr[dock_y1:dock_y2, x1:x2, :3]
        mask = (sub[:, :, 0] > 70) | (sub[:, :, 1] > 70) | (sub[:, :, 2] > 180)
        ys, xs = np.where(mask)
        if len(ys) < 80: # empty slot
            continue
            
        bx1, bx2 = xs.min() + x1, xs.max() + x1
        by1, by2 = ys.min() + dock_y1, ys.max() + dock_y1
        w = bx2 - bx1 + 1
        h = by2 - by1 + 1
        
        # Estimate grid cols and rows based on dock unit block size (~65px)
        cols = max(1, int(round(w / 65.0)))
        rows = max(1, int(round(h / 65.0)))
        
        cw = w / float(cols)
        rh = h / float(rows)
        
        shape = np.zeros((rows, cols), dtype=int)
        for r in range(rows):
            for c in range(cols):
                cx = int(bx1 + (c + 0.5) * cw)
                cy = int(by1 + (r + 0.5) * rh)
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
            'cols': cols,
            'w_px': w,
            'h_px': h
        })
    return pieces

if __name__ == '__main__':
    t0 = time.time()
    arr = capture_screen()
    t1 = time.time()
    board = analyze_board(arr)
    pieces = detect_dock_pieces(arr)
    t2 = time.time()
    
    print(f'Capture time: {t1-t0:.3f}s, Analysis time: {t2-t1:.3f}s')
    print('Board state:')
    for r in range(8):
        print(' '.join('#' if board[r, c] else '.' for c in range(8)))
    print(f'Detected {len(pieces)} pieces in dock:')
    for p in pieces:
        print(f"Slot {p['slot']+1} ({p['rows']}x{p['cols']}) center={p['dock_center']}:")
        for r in range(p['rows']):
            print('  ' + ' '.join('#' if p['shape'][r, c] else '.' for c in range(p['cols'])))
