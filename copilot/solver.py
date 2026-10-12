#!/usr/bin/env python3
"""
Blockzi AI Solver Engine for Co-Pilot
Analyzes board, detects dock pieces adaptively, and computes optimal 3-step sequence.
Powered by a 64-bit bitboard search engine with anytime deadline enforcement.
"""

import itertools
import os
import sys
import time
from pathlib import Path
import numpy as np

# Ensure blockzi_config can be loaded
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

try:
    import blockzi_config as cfg
except ImportError:
    class _DefaultCfg:
        SOLVER_MAX_MS = 200
        EVAL_MODE = "v1"
    cfg = _DefaultCfg()

# Geometry for Xiaomi 1220x2712
X0, Y0 = 41, 731
BOARD_W = 1138.0
BOARD_H = 1138.0
CW = BOARD_W / 8.0
CH = BOARD_H / 8.0

# Bitboard full row and column masks (64-bit int, bit 8*r + c)
FULLR = [0xFF << (8 * r) for r in range(8)]
FULLC = [sum(1 << (8 * r + c) for r in range(8)) for c in range(8)]

# Precomputed masks for 3x3 and 1x5/5x1 placement (for v2 evaluation)
MASKS_3X3 = []
for _r in range(6):
    for _c in range(6):
        _m = 0
        for _dr in range(3):
            for _dc in range(3):
                _m |= 1 << (8 * (_r + _dr) + (_c + _dc))
        MASKS_3X3.append(_m)

MASKS_1X5 = []
for _r in range(8):
    for _c in range(4):
        _m = 0
        for _dc in range(5):
            _m |= 1 << (8 * _r + (_c + _dc))
        MASKS_1X5.append(_m)
for _r in range(4):
    for _c in range(8):
        _m = 0
        for _dr in range(5):
            _m |= 1 << (8 * (_r + _dr) + _c)
        MASKS_1X5.append(_m)


class StepList(list):
    """List of steps with .timed_out attribute."""

    def __init__(self, items, timed_out=False):
        super().__init__(items)
        self.timed_out = timed_out


class SolverResult(tuple):
    """3-tuple subclass (seq, score, solve_ms) that also exposes .timed_out."""

    def __new__(cls, seq, score, solve_ms, timed_out=False):
        step_list = StepList(seq, timed_out=timed_out)
        obj = super().__new__(cls, (step_list, score, solve_ms))
        obj.seq = step_list
        obj.score = score
        obj.solve_ms = solve_ms
        obj.timed_out = timed_out
        return obj


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


def get_dim_count(dim, fx=1.0):
    """Map pixel extent to grid cell count (1..5).

    Dock cell size is approx 65px at fx=1.0.
    Midpoints between classes:
      1 vs 2: (65 + 130) / 2 = 97.5 -> 95 * fx
      2 vs 3: (130 + 195) / 2 = 162.5 -> 160 * fx
      3 vs 4: (195 + 260) / 2 = 227.5 -> 228 * fx
      4 vs 5: (260 + 325) / 2 = 292.5 -> 295 * fx
    """
    if dim > 295 * fx:
        return 5
    elif dim > 228 * fx:
        return 4
    elif dim > 160 * fx:
        return 3
    elif dim > 95 * fx:
        return 2
    else:
        return 1


def detect_dock_pieces(arr, fw, fh):
    fx = fw / 1220.0
    fy = fh / 2712.0
    slots = [(int(50*fx), int(420*fx)), (int(420*fx), int(800*fx)), (int(800*fx), int(1170*fx))]
    dock_y1 = int(1930 * fy)
    dock_y2 = int(2180 * fy)
    pieces = []

    for idx, (x1, x2) in enumerate(slots):
        sub = arr[dock_y1:dock_y2, x1:x2, :3]
        mask = (sub[:, :, 0] > 70) | (sub[:, :, 1] > 70) | (sub[:, :, 2] > 180)
        ys, xs = np.where(mask)
        if len(ys) < 40:
            continue
        w = xs.max() - xs.min() + 1
        h = ys.max() - ys.min() + 1
        cols = get_dim_count(w, fx)
        rows = get_dim_count(h, fx)
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


# ---------------------------------------------------------------------------
# Bitboard core operations
# ---------------------------------------------------------------------------

def count_isolated_holes(board):
    """NumPy implementation of isolated hole counter for backwards-compatibility."""
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


def count_isolated_holes_bb(b_bits):
    """Fast bitboard isolated holes counter. Identical results to count_isolated_holes."""
    e = ~b_bits & ((1 << 64) - 1)
    h = 0
    while e:
        i = (e & -e).bit_length() - 1
        e &= e - 1
        r, c = divmod(i, 8)
        n = 0
        if r > 0 and (b_bits >> (i - 8) & 1): n += 1
        if r < 7 and (b_bits >> (i + 8) & 1): n += 1
        if c > 0 and (b_bits >> (i - 1) & 1): n += 1
        if c < 7 and (b_bits >> (i + 1) & 1): n += 1
        if n >= 3: h += 1
    return h


def can_fit_3x3_bb(b_bits):
    """Check if any 3x3 placement is open on the bitboard."""
    for m in MASKS_3X3:
        if (b_bits & m) == 0:
            return True
    return False


def can_fit_1x5_bb(b_bits):
    """Check if any 1x5 or 5x1 placement is open on the bitboard."""
    for m in MASKS_1X5:
        if (b_bits & m) == 0:
            return True
    return False


def simulate_step(b, g, p, r0, c0):
    """NumPy simulation step for backwards-compatibility."""
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


def step_bb(b_bits, g_bits, mask):
    """Apply a piece mask to the bitboard. Returns (nb, ng, clears, fr, fc, gems)."""
    if b_bits & mask:
        return None, None, 0, [], [], 0
    nb = b_bits | mask
    clr = 0
    fr = []
    fc = []
    for r in range(8):
        f = FULLR[r]
        if (nb & f) == f:
            clr |= f
            fr.append(r)
    for c in range(8):
        f = FULLC[c]
        if (nb & f) == f:
            clr |= f
            fc.append(c)
    clears = len(fr) + len(fc)
    gems_collected = (g_bits & clr).bit_count()
    ng = g_bits & ~clr
    nb &= ~clr
    return nb, ng, clears, fr, fc, gems_collected


def precompute_piece_masks(pieces):
    """Precompute placement bitmasks and coordinates for each piece."""
    M = []
    for p in pieces:
        p_masks = []
        shape = p['shape']
        rows = p['rows']
        cols = p['cols']
        for r in range(9 - rows):
            for c in range(9 - cols):
                m = 0
                pc = []
                for dr in range(rows):
                    for dc in range(cols):
                        if shape[dr][dc]:
                            m |= 1 << (8 * (r + dr) + (c + dc))
                            pc.append([r + dr, c + dc])
                p_masks.append((r, c, m, pc))
        M.append(p_masks)
    return M


def bits_to_board_list(b_bits):
    """Convert 64-bit int board representation into an 8x8 Python list of 0s and 1s."""
    return [[(b_bits >> (8 * r + c)) & 1 for c in range(8)] for r in range(8)]


def evaluate_board(b_bits, total_clears, total_gems, eval_mode="v1"):
    """Evaluate leaf board score with v1 or v2 heuristic."""
    base_score = total_clears * 1500 + total_gems * 400 - b_bits.bit_count() * 15
    holes = count_isolated_holes_bb(b_bits)
    if eval_mode == "v2":
        score = base_score - holes * 40
        if can_fit_3x3_bb(b_bits):
            score += 120
        if can_fit_1x5_bb(b_bits):
            score += 60
        return score
    return base_score - holes * 35


# ---------------------------------------------------------------------------
# Sequence Solver
# ---------------------------------------------------------------------------

def solve_full_sequence(board, gems, pieces, max_ms=0):
    """Compute optimal placement sequence with 64-bit bitboard and anytime search.

    max_ms > 0 enforces an early exit deadline using time.perf_counter().
    Returns SolverResult(seq, score, dt, timed_out=bool).
    """
    n = len(pieces)
    if n == 0:
        return SolverResult([], 0, 0.0, timed_out=False)

    t0 = time.perf_counter()
    deadline = t0 + (max_ms / 1000.0) if max_ms > 0 else 0.0
    eval_mode = os.environ.get("BLOCKZI_EVAL", cfg.EVAL_MODE).lower()

    # Convert NumPy boards to 64-bit integers
    b0 = sum(int(board[r, c]) << (8 * r + c) for r in range(8) for c in range(8))
    g0 = sum(int(gems[r, c]) << (8 * r + c) for r in range(8) for c in range(8))

    M = precompute_piece_masks(pieces)

    best_score = -1e18
    best_seq = []
    best_2_score = -1e18
    best_2_seq = []
    best_1_score = -1e18
    best_1_seq = []

    timed_out = False
    _check_counter = 0

    def check_deadline():
        nonlocal timed_out, _check_counter
        if deadline <= 0:
            return False
        _check_counter += 1
        if (_check_counter & 63) == 0:
            if time.perf_counter() >= deadline:
                timed_out = True
                return True
        return False

    def mk_step(p, r, c, cl, fr, fc, gm, pc, b_after, step_n):
        return {
            'step': step_n,
            'slot': p['slot'],
            'slot_name': p['slot_name'],
            'r': r,
            'c': c,
            'shape': p['shape'],
            'clears': cl,
            'full_rows': fr,
            'full_cols': fc,
            'cells': pc,
            'board_after': bits_to_board_list(b_after),
        }

    # Transposition cache for pruning equivalent board states
    # Key: (b_bits, g_bits, tuple(sorted_remaining_piece_indices))
    transposition_table = {}

    if n == 3:
        seen_perms = set()
        for perm in itertools.permutations(range(3)):
            if timed_out:
                break
            # Deduplicate permutations of identical shapes
            shape_key = tuple(str(pieces[i]['shape']) for i in perm)
            if shape_key in seen_perms:
                continue
            seen_perms.add(shape_key)

            p0 = pieces[perm[0]]
            p1 = pieces[perm[1]]
            p2 = pieces[perm[2]]
            m0_list = M[perm[0]]
            m1_list = M[perm[1]]
            m2_list = M[perm[2]]

            # Move ordering on first piece when deadline is active
            if deadline > 0:
                # Prioritize placements that clear lines
                valid_m0 = []
                for item in m0_list:
                    if not (b0 & item[2]):
                        valid_m0.append(item)
                valid_m0.sort(key=lambda item: ((b0 | item[2]).bit_count()), reverse=False)
                active_m0 = valid_m0
            else:
                active_m0 = m0_list

            for r0, c0, m0, pc0 in active_m0:
                if timed_out or (deadline > 0 and time.perf_counter() >= deadline):
                    timed_out = True
                    break
                b1, g1, cl0, fr0, fc0, gm0 = step_bb(b0, g0, m0)
                if b1 is None:
                    continue

                # Record best 1-step candidate for fallback
                sc1 = evaluate_board(b1, cl0, gm0, eval_mode)
                if sc1 > best_1_score:
                    best_1_score = sc1
                    best_1_seq = [mk_step(p0, r0, c0, cl0, fr0, fc0, gm0, pc0, b1, 1)]

                for r1, c1, m1, pc1 in m1_list:
                    if timed_out or (deadline > 0 and time.perf_counter() >= deadline):
                        timed_out = True
                        break
                    b2, g2, cl1, fr1, fc1, gm1 = step_bb(b1, g1, m1)
                    if b2 is None:
                        continue

                    # Record best 2-step candidate for fallback
                    sc2 = evaluate_board(b2, cl0 + cl1, gm0 + gm1, eval_mode)
                    if sc2 > best_2_score:
                        best_2_score = sc2
                        best_2_seq = [
                            mk_step(p0, r0, c0, cl0, fr0, fc0, gm0, pc0, b1, 1),
                            mk_step(p1, r1, c1, cl1, fr1, fc1, gm1, pc1, b2, 2),
                        ]

                    # Transposition check before innermost loop
                    tt_key = (b2, g2, perm[2])
                    if tt_key in transposition_table and transposition_table[tt_key] >= (cl0 + cl1):
                        continue
                    transposition_table[tt_key] = cl0 + cl1

                    for r2, c2, m2, pc2 in m2_list:
                        if check_deadline():
                            break
                        b3, g3, cl2, fr2, fc2, gm2 = step_bb(b2, g2, m2)
                        if b3 is None:
                            continue

                        tot_cl = cl0 + cl1 + cl2
                        tot_gm = gm0 + gm1 + gm2
                        score = evaluate_board(b3, tot_cl, tot_gm, eval_mode)

                        if score > best_score:
                            best_score = score
                            best_seq = [
                                mk_step(p0, r0, c0, cl0, fr0, fc0, gm0, pc0, b1, 1),
                                mk_step(p1, r1, c1, cl1, fr1, fc1, gm1, pc1, b2, 2),
                                mk_step(p2, r2, c2, cl2, fr2, fc2, gm2, pc2, b3, 3),
                            ]

    elif n == 2:
        seen_perms = set()
        for perm in itertools.permutations(range(2)):
            if timed_out:
                break
            shape_key = tuple(str(pieces[i]['shape']) for i in perm)
            if shape_key in seen_perms:
                continue
            seen_perms.add(shape_key)

            p0 = pieces[perm[0]]
            p1 = pieces[perm[1]]
            m0_list = M[perm[0]]
            m1_list = M[perm[1]]

            for r0, c0, m0, pc0 in m0_list:
                if timed_out or (deadline > 0 and time.perf_counter() >= deadline):
                    timed_out = True
                    break
                b1, g1, cl0, fr0, fc0, gm0 = step_bb(b0, g0, m0)
                if b1 is None:
                    continue

                sc1 = evaluate_board(b1, cl0, gm0, eval_mode)
                if sc1 > best_1_score:
                    best_1_score = sc1
                    best_1_seq = [mk_step(p0, r0, c0, cl0, fr0, fc0, gm0, pc0, b1, 1)]

                for r1, c1, m1, pc1 in m1_list:
                    if check_deadline():
                        break
                    b2, g2, cl1, fr1, fc1, gm1 = step_bb(b1, g1, m1)
                    if b2 is None:
                        continue

                    tot_cl = cl0 + cl1
                    tot_gm = gm0 + gm1
                    score = evaluate_board(b2, tot_cl, tot_gm, eval_mode)
                    if score > best_score:
                        best_score = score
                        best_seq = [
                            mk_step(p0, r0, c0, cl0, fr0, fc0, gm0, pc0, b1, 1),
                            mk_step(p1, r1, c1, cl1, fr1, fc1, gm1, pc1, b2, 2),
                        ]

    elif n == 1:
        p0 = pieces[0]
        for r0, c0, m0, pc0 in M[0]:
            if check_deadline():
                break
            b1, g1, cl0, fr0, fc0, gm0 = step_bb(b0, g0, m0)
            if b1 is None:
                continue
            score = evaluate_board(b1, cl0, gm0, eval_mode)
            if score > best_score:
                best_score = score
                best_seq = [mk_step(p0, r0, c0, cl0, fr0, fc0, gm0, pc0, b1, 1)]

    # Anytime Fallback:
    # If full sequence was not found (or timed out before complete search):
    if not best_seq and best_2_seq:
        best_seq = best_2_seq
        best_score = best_2_score
    elif not best_seq and best_1_seq:
        best_seq = best_1_seq
        best_score = best_1_score
    elif not best_seq and n > 0:
        # Ultimate 1-step safety fallback
        for idx, p in enumerate(pieces):
            for r0, c0, m0, pc0 in M[idx]:
                b1, g1, cl0, fr0, fc0, gm0 = step_bb(b0, g0, m0)
                if b1 is not None:
                    sc = evaluate_board(b1, cl0, gm0, eval_mode)
                    if sc > best_score:
                        best_score = sc
                        best_seq = [mk_step(p, r0, c0, cl0, fr0, fc0, gm0, pc0, b1, 1)]

    dt = (time.perf_counter() - t0) * 1000.0

    # Attach timed_out indicator to seq and return SolverResult
    for step in best_seq:
        step['timed_out'] = timed_out

    return SolverResult(best_seq, best_score, dt, timed_out=timed_out)


def check_game_state(arr, fw, fh):
    # 1. Victory check: golden stars > 2000 in top 15%..25%
    y1, y2 = int(fh * 0.15), int(fh * 0.25)
    stars = (arr[y1:y2, :, 0] > 220) & (arr[y1:y2, :, 1] > 180) & (arr[y1:y2, :, 2] < 50)
    if stars.sum() > 2000:
        return 'VICTORY'

    # 2. Defeat check: red cross or 'Main Lagi' popup button
    h_btn1, h_btn2 = int(fh * 0.75), int(fh * 0.85)
    w_btn1, w_btn2 = int(fw * 0.25), int(fw * 0.75)
    btn_area = arr[h_btn1:h_btn2, w_btn1:w_btn2, :3]
    orange_btn = (btn_area[:, :, 0] > 220) & (btn_area[:, :, 1] > 100) & (btn_area[:, :, 2] < 70)
    if orange_btn.sum() > 4000:
        return 'DEFEAT'

    return 'PLAYING'
