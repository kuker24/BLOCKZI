#!/usr/bin/env python3
"""
Blockzi AI Solver Engine for Co-Pilot
Analyzes board, detects dock pieces adaptively, and computes optimal 3-step sequence.
"""

import itertools
import time
import numpy as np

# Geometry for Xiaomi 1220x2712
X0, Y0 = 41, 731
BOARD_W = 1138.0
BOARD_H = 1138.0
CW = BOARD_W / 8.0
CH = BOARD_H / 8.0

def analyze_board(arr, fw, fh):
    fx = fw / 1220.0
    fy = fh / 2712.0
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

def detect_dock_pieces(arr, fw, fh):
    fx = fw / 1220.0
    fy = fh / 2712.0
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

        pieces.append({
            'slot': idx,
            'slot_name': ['Slot 1 (Kiri)', 'Slot 2 (Tengah)', 'Slot 3 (Kanan)'][idx],
            'shape': shape.tolist(),
            'rows': rows,
            'cols': cols,
            'box': [int(xs.min() + x1), int(ys.min() + dock_y1), int(w), int(h)]
        })
    return pieces

def simulate_step(b, g, p, r0, c0):
    shape = np.array(p['shape'])
    rows, cols = p['rows'], p['cols']
    if r0 + rows > 8 or c0 + cols > 8:
        return None, None, 0, [], [], 0, []
    for dr in range(rows):
        for dc in range(cols):
            if shape[dr, dc] == 1 and b[r0 + dr, c0 + dc] == 1:
                return None, None, 0, [], [], 0, []
    nb = b.copy()
    ng = g.copy()
    placed_cells = []
    for dr in range(rows):
        for dc in range(cols):
            if shape[dr, dc] == 1:
                nb[r0 + dr, c0 + dc] = 1
                placed_cells.append([int(r0 + dr), int(c0 + dc)])
    full_rows = [int(r) for r in range(8) if nb[r].sum() == 8]
    full_cols = [int(c) for c in range(8) if nb[:, c].sum() == 8]
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
    return nb, ng, clears, full_rows, full_cols, gems_collected, placed_cells

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

def solve_full_sequence(board, gems, pieces, max_ms=0):
    """Brute-force best placement sequence.  max_ms>0 enables early exit."""
    n = len(pieces)
    if n == 0:
        return [], 0, 0
    best_score = -1e9
    best_seq = []
    t0 = time.time()
    deadline = t0 + max_ms / 1000.0 if max_ms > 0 else 0
    _check_ctr = 0

    def _expired():
        nonlocal _check_ctr
        if not deadline:
            return False
        _check_ctr += 1
        if _check_ctr & 63:
            return False
        return time.time() > deadline

    def _mk(p, r, c, cl, fr, fc, gm, pc, b_after, step_n):
        return {'step': step_n, 'slot': p['slot'], 'slot_name': p['slot_name'],
                'r': r, 'c': c, 'shape': p['shape'], 'clears': cl,
                'full_rows': fr, 'full_cols': fc, 'cells': pc,
                'board_after': b_after.tolist()}

    if n == 3:
        for perm in itertools.permutations(range(3)):
            if _expired():
                break
            p0 = pieces[perm[0]]
            for r0 in range(9 - p0['rows']):
                if _expired():
                    break
                for c0 in range(9 - p0['cols']):
                    b1, g1, cl0, fr0, fc0, gm0, pc0 = simulate_step(board, gems, p0, r0, c0)
                    if b1 is None: continue
                    p1 = pieces[perm[1]]
                    for r1 in range(9 - p1['rows']):
                        if _expired():
                            break
                        for c1 in range(9 - p1['cols']):
                            b2, g2, cl1, fr1, fc1, gm1, pc1 = simulate_step(b1, g1, p1, r1, c1)
                            if b2 is None: continue
                            p2 = pieces[perm[2]]
                            for r2 in range(9 - p2['rows']):
                                for c2 in range(9 - p2['cols']):
                                    b3, g3, cl2, fr2, fc2, gm2, pc2 = simulate_step(b2, g2, p2, r2, c2)
                                    if b3 is None: continue
                                    total_clears = cl0 + cl1 + cl2
                                    total_gems = gm0 + gm1 + gm2
                                    score = total_clears * 1500 + total_gems * 400 - b3.sum() * 15 - count_isolated_holes(b3) * 35
                                    if score > best_score:
                                        best_score = score
                                        best_seq = [
                                            _mk(p0, r0, c0, cl0, fr0, fc0, gm0, pc0, b1, 1),
                                            _mk(p1, r1, c1, cl1, fr1, fc1, gm1, pc1, b2, 2),
                                            _mk(p2, r2, c2, cl2, fr2, fc2, gm2, pc2, b3, 3),
                                        ]
    elif n == 2:
        for perm in itertools.permutations(range(2)):
            if _expired():
                break
            p0 = pieces[perm[0]]
            for r0 in range(9 - p0['rows']):
                if _expired():
                    break
                for c0 in range(9 - p0['cols']):
                    b1, g1, cl0, fr0, fc0, gm0, pc0 = simulate_step(board, gems, p0, r0, c0)
                    if b1 is None: continue
                    p1 = pieces[perm[1]]
                    for r1 in range(9 - p1['rows']):
                        if _expired():
                            break
                        for c1 in range(9 - p1['cols']):
                            b2, g2, cl1, fr1, fc1, gm1, pc1 = simulate_step(b1, g1, p1, r1, c1)
                            if b2 is None: continue
                            score = (cl0 + cl1) * 1500 + (gm0 + gm1) * 400 - b2.sum() * 15 - count_isolated_holes(b2) * 35
                            if score > best_score:
                                best_score = score
                                best_seq = [
                                    _mk(p0, r0, c0, cl0, fr0, fc0, gm0, pc0, b1, 1),
                                    _mk(p1, r1, c1, cl1, fr1, fc1, gm1, pc1, b2, 2),
                                ]
    elif n == 1:
        p0 = pieces[0]
        for r0 in range(9 - p0['rows']):
            for c0 in range(9 - p0['cols']):
                b1, g1, cl0, fr0, fc0, gm0, pc0 = simulate_step(board, gems, p0, r0, c0)
                if b1 is None: continue
                score = cl0 * 1500 + gm0 * 400 - b1.sum() * 15 - count_isolated_holes(b1) * 35
                if score > best_score:
                    best_score = score
                    best_seq = [_mk(p0, r0, c0, cl0, fr0, fc0, gm0, pc0, b1, 1)]

    if not best_seq and n > 0:
        for p0 in pieces:
            for r0 in range(9 - p0['rows']):
                for c0 in range(9 - p0['cols']):
                    b1, g1, cl0, fr0, fc0, gm0, pc0 = simulate_step(board, gems, p0, r0, c0)
                    if b1 is not None:
                        score = cl0 * 1500 + gm0 * 400 - b1.sum() * 15
                        if score > best_score:
                            best_score = score
                            best_seq = [_mk(p0, r0, c0, cl0, fr0, fc0, gm0, pc0, b1, 1)]

    dt = (time.time() - t0) * 1000
    return best_seq, best_score, dt

def check_game_state(arr, fw, fh):
    # 1. Victory check: golden stars > 2000 in top 15%..25%
    y1, y2 = int(fh * 0.15), int(fh * 0.25)
    stars = (arr[y1:y2, :, 0] > 220) & (arr[y1:y2, :, 1] > 180) & (arr[y1:y2, :, 2] < 50)
    if stars.sum() > 2000:
        return 'VICTORY'

    # 2. Defeat check: cream card + yellow button
    fy = fh / 2712.0
    fx = fw / 1220.0
    sub = arr[int(2050*fy):int(2250*fy), int(200*fx):int(1000*fx), :3]
    yellow = (sub[:, :, 0] > 200) & (sub[:, :, 1] > 180) & (sub[:, :, 2] < 100)
    center = arr[int(900*fy):int(1200*fy), int(200*fx):int(1000*fx), :3]
    cream = (center[:, :, 0] > 240) & (center[:, :, 1] > 230) & (center[:, :, 2] > 200)
    if yellow.sum() > 1000 and cream.sum() > 500:
        return 'DEFEAT'

    return 'PLAYING'
