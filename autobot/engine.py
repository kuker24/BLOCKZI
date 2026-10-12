#!/usr/bin/env python3
"""
Blockzi Autonomous Engine v5

Separate from copilot/. Imports the solver, does not modify it.

Touch model, measured on this Xiaomi 1220x2712 (not a per-slot constant):
    piece = grab + (finger - grab) * SCALE
    piece_y is then lifted by LIFT so the block floats above the finger
    SCALE = 1.298, LIFT = 191
Grab is the dock bounding-box center. Releasing inside the dock Y band is
fine as long as the ghost sits on the target cells. A hard Y clamp at 1885
was collapsing every bottom-row target onto the same point.
"""

import io
import itertools
import logging
import subprocess
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import sys
sys.path.append("/home/fahmi/Downloads/UNF/shop/copilot")
from solver import (  # noqa: E402
    analyze_board,
    detect_dock_pieces,
    solve_full_sequence,
    check_game_state,
    simulate_step,
)

X0, Y0 = 41, 731
BOARD_W = 1138.0
BOARD_H = 1138.0
CW = BOARD_W / 8.0
CH = BOARD_H / 8.0

SCALE = 1.298
LIFT = 191.0
TARGET_LEVEL = 90
LOG_FILE = "/home/fahmi/Downloads/UNF/shop/autobot/autobot.log"
FONT_PATH = "/usr/share/fonts/extra/Dinreg_Regular.ttf"
NEXT_BUTTON = (600, 2127)
CANCEL_TAP = (1069, 195)
WARUNG_BACK = (92, 172)
REVIVE_SCROLL_S = 33
BOOST_TAP = {
    "extra": (245, 2492),
    "bomb": (609, 2492),
    "remove": (940, 2480),
}
BOOST_FONT = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"
PLUS = ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1))

log = logging.getLogger("autobot")
log.setLevel(logging.INFO)
log.handlers.clear()
log.propagate = False
_handler = logging.FileHandler(LOG_FILE, mode="a")
_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
log.addHandler(_handler)


def adb_shell(script, timeout=12):
    return subprocess.run(
        ["adb", "shell", script],
        check=True,
        timeout=timeout,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


# 1x is the measured-accurate timing. Higher speeds only shorten animation waits.
# Screencap + adb still set a floor, so 5x is not literally five times the move rate.
SPEEDS = {
    "min":      {"steps": 8, "move": 0.016, "down": 0.05, "hold": 0.10, "wait": 0.55, "clear": 1.70, "recheck": 0.65, "popup": 3.2},
    "max":      {"steps": 4, "move": 0.002, "down": 0.01, "hold": 0.02, "wait": 0.03, "clear": 0.15, "recheck": 0.08, "popup": 0.5},
    "adaptive": {"steps": 4, "move": 0.002, "down": 0.01, "hold": 0.02, "wait": 0.03, "clear": 0.15, "recheck": 0.08, "popup": 0.5},
}

ADAPTIVE_DRAG_SLOW = {"steps": 6, "move": 0.006, "down": 0.03, "hold": 0.05, "wait": 0.08, "clear": 0.30, "recheck": 0.15, "popup": 0.8}
def speed_profile(name):
    return SPEEDS.get(str(name), SPEEDS["adaptive"])


def adaptive_solver_budget(board):
    """Return solver timeout ms based on board fill level."""
    filled = int(board.sum())
    if filled < 13:
        return 800
    elif filled < 26:
        return 1500
    elif filled < 39:
        return 3000
    elif filled < 52:
        return 5000
    else:
        return 8000


def adaptive_profile(board):
    """Return drag profile for adaptive mode based on board density."""
    filled = int(board.sum())
    if filled < 26:
        return SPEEDS["adaptive"]
    else:
        return ADAPTIVE_DRAG_SLOW


def execute_drag(dx, dy, fx, fy, steps=8, move_sleep=0.016, down_sleep=0.05, hold=0.10):
    dx, dy, fx, fy = int(dx), int(dy), int(fx), int(fy)
    cmds = [f"input motionevent DOWN {dx} {dy}", f"sleep {down_sleep:.3f}"]
    for i in range(1, steps + 1):
        x = int(dx + (fx - dx) * i / steps)
        y = int(dy + (fy - dy) * i / steps)
        cmds.append(f"input motionevent MOVE {x} {y}")
        cmds.append(f"sleep {move_sleep:.3f}")
    cmds.append(f"sleep {hold:.3f}")
    cmds.append(f"input motionevent UP {fx} {fy}")
    adb_shell("; ".join(cmds))


def tap(x, y):
    adb_shell(f"input tap {int(x)} {int(y)}")


def swipe(x1, y1, x2, y2, ms=420):
    adb_shell(
        f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(ms)}",
        timeout=8,
    )


def _yellow_button(arr):
    if arr.shape[0] < 2400:
        return None
    sub = arr[1900:2400]
    red, green, blue = [sub[:, :, i].astype(int) for i in range(3)]
    yellow = (red > 210) & (green > 170) & (blue < 110) & (green > blue + 70)
    ys, xs = np.where(yellow)
    if len(xs) < 8000:
        return None
    return int(xs.min()), int(ys.min() + 1900), int(xs.max()), int(ys.max() + 1900)


def warung_open(arr):
    """Shopee Warung reward page, or the white sheet while it is sliding in."""
    if arr.shape[0] < 2200:
        return False
    top = arr[90:230, 180:1040]
    red, green, blue = [top[:, :, i].astype(int) for i in range(3)]
    orange = (red > 170) & (green > 60) & (green < 200) & (blue < 130) & (red > blue + 40)
    if int(orange.sum()) > 20000:
        return True
    right = arr[400:2200, 500:]
    light = (right[:, :, 0] > 235) & (right[:, :, 1] > 235) & (right[:, :, 2] > 235)
    return float(light.mean()) > 0.85


def warung_ready(arr):
    top = arr[90:230, 180:1040]
    red, green, blue = [top[:, :, i].astype(int) for i in range(3)]
    orange = (red > 170) & (green > 60) & (green < 200) & (blue < 130) & (red > blue + 40)
    return int(orange.sum()) > 20000


def revive_button(arr):
    """Ruang Penuh countdown. None on Main Lagi, Warung, or normal play."""
    if warung_open(arr):
        return None
    box = _yellow_button(arr)
    if box is None or box[1] >= 2025:
        return None
    xzone = arr[2240:2420, 520:720]
    close = (xzone[:, :, 0] > 210) & (xzone[:, :, 1] > 210) & (xzone[:, :, 2] > 210)
    if int(close.sum()) > 400:
        return None
    ring = arr[1050:1750, 300:920]
    white = (ring[:, :, 0] > 230) & (ring[:, :, 1] > 230) & (ring[:, :, 2] > 230)
    if int(white.sum()) < 15000:
        return None
    return (box[0] + box[2]) // 2, (box[1] + box[3]) // 2


def main_lagi_button(arr):
    if warung_open(arr):
        return None
    xzone = arr[2240:2420, 520:720]
    close = (xzone[:, :, 0] > 210) & (xzone[:, :, 1] > 210) & (xzone[:, :, 2] > 210)
    if int(close.sum()) < 800:
        return None
    box = _yellow_button(arr)
    if box is None:
        return (609, 2149)
    return (box[0] + box[2]) // 2, (box[1] + box[3]) // 2


def scroll_warung(seconds=REVIVE_SCROLL_S):
    """Alternate down/up swipes so the 30s Warung timer keeps running."""
    log.info("Warung scroll start, %ss", seconds)
    t0 = time.time()
    down = True
    n = 0
    while time.time() - t0 < seconds:
        if down:
            swipe(610, 2000, 610, 750, 420)
        else:
            swipe(610, 850, 610, 2050, 420)
        down = not down
        n += 1
        time.sleep(0.15)
        if n % 8 == 0:
            shot = np.array(take_screencap())
            if not warung_open(shot):
                log.warning("Left Warung during scroll. Back once.")
                adb_shell("input keyevent 4")
                time.sleep(0.7)
            elif n % 16 == 0:
                log.info("Warung scroll %ss", round(time.time() - t0))
    log.info("Warung scroll done, %s swipes", n)


def exit_warung():
    tap(*WARUNG_BACK)
    time.sleep(1.0)
    im = take_screencap()
    if not warung_open(np.array(im)):
        return im
    log.warning("Warung back missed. Tapping again.")
    tap(*WARUNG_BACK)
    time.sleep(1.0)
    im = take_screencap()
    if not warung_open(np.array(im)):
        return im
    log.warning("Warung still open. Android back.")
    adb_shell("input keyevent 4")
    time.sleep(1.0)
    return take_screencap()


def take_screencap():
    res = subprocess.run(
        ["adb", "exec-out", "screencap", "-p"],
        stdout=subprocess.PIPE,
        check=True,
        timeout=8,
    )
    return Image.open(io.BytesIO(res.stdout))


def grab_point(arr, piece):
    """Touch the dock bbox center. If that pixel is a hole, nudge onto ink."""
    bx, by, bw, bh = piece["box"]
    gx = int(round(bx + bw / 2.0))
    gy = int(round(by + bh / 2.0))
    h, w = arr.shape[:2]
    gx = min(max(gx, 0), w - 1)
    gy = min(max(gy, 0), h - 1)
    pix = arr[gy, gx, :3]
    if int(pix.max()) > 80:
        return gx, gy
    shape = np.array(piece["shape"])
    rows, cols = shape.shape
    best = (gx, gy)
    best_d = 1e9
    for r in range(rows):
        for c in range(cols):
            if shape[r, c] != 1:
                continue
            x = int(round(bx + (c + 0.5) * bw / cols))
            y = int(round(by + (r + 0.5) * bh / rows))
            d = (x - gx) ** 2 + (y - gy) ** 2
            if d < best_d:
                best_d = d
                best = (x, y)
    return best


def calc_finger_target(grab, rows, cols, r, c):
    board_cx = X0 + (c + cols / 2.0) * CW
    board_cy = Y0 + (r + rows / 2.0) * CH
    gx, gy = grab
    fx = gx + (board_cx - gx) / SCALE
    fy = gy + (board_cy + LIFT - gy) / SCALE
    fx = max(20.0, min(1200.0, fx))
    fy = max(980.0, min(2120.0, fy))
    return int(round(fx)), int(round(fy)), board_cx, board_cy


def piece_still_there(pieces, slot, shape):
    return any(p["slot"] == slot and p["shape"] == shape for p in pieces)


def choose_move(board, gems, pieces, failed, max_ms=0):
    """Return (step, seq, score, solve_ms).

    ``max_ms`` is forwarded to ``solve_full_sequence`` so the solver can
    bail out early at MAX speed.
    """
    seq, score, dt = solve_full_sequence(board, gems, pieces, max_ms=max_ms)
    if seq:
        step = seq[0]
        if failed.get((step["slot"], step["r"], step["c"]), 0) < 2:
            return step, seq, score, dt

    best = None
    best_score = -1e18
    for p in pieces:
        for r in range(9 - p["rows"]):
            for c in range(9 - p["cols"]):
                key = (p["slot"], r, c)
                if failed.get(key, 0) >= 2:
                    continue
                nb, ng, clears, fr, fc, gems_got, cells = simulate_step(board, gems, p, r, c)
                if nb is None:
                    continue
                sc = clears * 1500 + gems_got * 400 - int(nb.sum()) * 15
                if sc > best_score:
                    best_score = sc
                    best = {
                        "step": 1,
                        "slot": p["slot"],
                        "slot_name": p["slot_name"],
                        "r": r,
                        "c": c,
                        "shape": p["shape"],
                        "clears": clears,
                        "cells": cells,
                    }
    if best is None and seq:
        failed.clear()
        return seq[0], seq, score, dt
    return best, seq, score, dt


def _templates():
    if not Path(FONT_PATH).exists():
        return None
    font = ImageFont.truetype(FONT_PATH, 64)
    out = {}
    for ch in "0123456789":
        canvas = Image.new("L", (140, 140), 0)
        ImageDraw.Draw(canvas).text((10, 10), ch, font=font, fill=255)
        ink = np.array(canvas) > 128
        ys, xs = np.where(ink)
        if len(ys) == 0:
            return None
        out[ch] = ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return out


_DIGIT_TEMPLATES = _templates()


def _iou(template, glyph):
    resized = Image.fromarray((template.astype(np.uint8) * 255)).resize(
        (glyph.shape[1], glyph.shape[0]), Image.BILINEAR
    )
    pred = np.array(resized) > 100
    inter = np.logical_and(pred, glyph).sum()
    union = np.logical_or(pred, glyph).sum()
    return inter / max(1, union)


def _hole_count(glyph):
    h, w = glyph.shape
    bg = ~glyph
    seen = np.zeros_like(bg, dtype=bool)
    stack = []
    for x in range(w):
        if bg[0, x]:
            stack.append((0, x))
        if bg[h - 1, x]:
            stack.append((h - 1, x))
    for y in range(h):
        if bg[y, 0]:
            stack.append((y, 0))
        if bg[y, w - 1]:
            stack.append((y, w - 1))
    while stack:
        y, x = stack.pop()
        if y < 0 or x < 0 or y >= h or x >= w or seen[y, x] or not bg[y, x]:
            continue
        seen[y, x] = True
        stack.extend(((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)))
    holes = 0
    for y in range(h):
        for x in range(w):
            if not bg[y, x] or seen[y, x]:
                continue
            holes += 1
            stack = [(y, x)]
            seen[y, x] = True
            while stack:
                yy, xx = stack.pop()
                for ny, nx in ((yy - 1, xx), (yy + 1, xx), (yy, xx - 1), (yy, xx + 1)):
                    if 0 <= ny < h and 0 <= nx < w and bg[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
    return holes


def read_level(arr):
    """Read the 'Level N' header. Returns int or None. Validated on levels 29-31."""
    if _DIGIT_TEMPLATES is None:
        return None
    sub = arr[180:270, 430:860, :3]
    white = (sub[:, :, 0] > 215) & (sub[:, :, 1] > 215) & (sub[:, :, 2] > 215)
    cols = white.sum(axis=0)
    runs = []
    start = None
    for i, value in enumerate(cols):
        if value > 2 and start is None:
            start = i
        elif value <= 2 and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(cols) - 1))

    glyphs = []
    for a, b in runs:
        mask = white[:, a:b + 1]
        ys = np.where(mask.any(axis=1))[0]
        if len(ys) < 8:
            continue
        glyphs.append(mask[ys.min():ys.max() + 1])

    digit_at = None
    for i, glyph in enumerate(glyphs):
        if glyph.shape[1] <= 10 and glyph.shape[0] >= 30:
            digit_at = i + 1
    if digit_at is None or digit_at >= len(glyphs):
        return None

    chars = []
    for glyph in glyphs[digit_at:]:
        holes = _hole_count(glyph)
        aspect = glyph.shape[1] / max(1, glyph.shape[0])
        ranked = sorted(
            ((_iou(_DIGIT_TEMPLATES[ch], glyph), ch) for ch in "0123456789"),
            reverse=True,
        )
        if holes >= 2:
            pick = "8"
        elif aspect < 0.42 and holes == 0:
            pick = "1"
        else:
            allowed = set("0469") if holes == 1 else set("2357")
            pick = next((ch for score, ch in ranked if ch in allowed), None)
            if pick is None or ranked[0][0] < 0.40:
                return None
        chars.append(pick)
    if not chars or len(chars) > 3:
        return None
    return int("".join(chars))


def accept_level(previous, reading):
    """Ignore a wild OCR jump. A real level only stays or increments by 1."""
    if reading is None:
        return previous
    if previous is None or reading == previous or reading == previous + 1:
        return reading
    return previous


def _badge_templates():
    if not Path(BOOST_FONT).exists():
        return None
    font = ImageFont.truetype(BOOST_FONT, 72)
    out = {}
    for ch in "0123456789+":
        canvas = Image.new("L", (140, 140), 0)
        ImageDraw.Draw(canvas).text((12, 8), ch, font=font, fill=255)
        ink = np.array(canvas) > 128
        ys, xs = np.where(ink)
        if len(ys) == 0:
            return None
        out[ch] = ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return out


_BADGE_TEMPLATES = _badge_templates()


def booster_selecting(arr):
    """True while Batalkan is on screen. Measured: ~3100 white px vs ~700 idle."""
    pill = arr[160:240, 960:1180, :3]
    white = (pill[:, :, 0] > 200) & (pill[:, :, 1] > 200) & (pill[:, :, 2] > 200)
    return int(white.sum()) > 1500


def cancel_booster():
    tap(*CANCEL_TAP)


def _largest_white(mask):
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    best = None
    for y in range(h):
        for x in range(w):
            if not mask[y, x] or seen[y, x]:
                continue
            stack = [(y, x)]
            seen[y, x] = True
            cells = []
            while stack:
                yy, xx = stack.pop()
                cells.append((yy, xx))
                for ny, nx in ((yy - 1, xx), (yy + 1, xx), (yy, xx - 1), (yy, xx + 1)):
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            if best is None or len(cells) > len(best):
                best = cells
    if not best or len(best) < 20:
        return None
    ys = [y for y, _x in best]
    xs = [x for _y, x in best]
    glyph = np.zeros((max(ys) - min(ys) + 1, max(xs) - min(xs) + 1), dtype=bool)
    for y, x in best:
        glyph[y - min(ys), x - min(xs)] = True
    return glyph


def _read_badge_value(glyph):
    if glyph is None or _BADGE_TEMPLATES is None:
        return None
    if glyph.shape[0] < 8 or glyph.shape[1] < 4:
        return None
    if glyph.shape[1] / glyph.shape[0] > 1.15:
        return None
    ranked = sorted(
        ((_iou(_BADGE_TEMPLATES[ch], glyph), ch) for ch in _BADGE_TEMPLATES),
        reverse=True,
    )
    score, ch = ranked[0]
    second = ranked[1][0]
    if ch == "+" or score < 0.55 or score - second < 0.08:
        return 0 if ch == "+" else None
    if ch == "0":
        return 0
    return int(ch)


def read_booster_counts(arr):
    """Pink count badges. None means unreadable, so that booster is not tapped."""
    counts = {"extra": None, "bomb": None, "remove": None}
    if arr.shape[0] < 2568:
        return counts
    band = arr[2488:2568]
    red = (
        (band[:, :, 0] > 200)
        & (band[:, :, 1] < 95)
        & (band[:, :, 2] < 130)
        & (band[:, :, 0] > band[:, :, 1] + 120)
    )
    cols = red.sum(axis=0)
    runs = []
    start = None
    for i, value in enumerate(cols):
        if value > 6 and start is None:
            start = i
        elif value <= 6 and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(cols) - 1))
    for a, b in runs:
        if b - a < 40:
            continue
        ys = np.where(red[:, a:b + 1].any(axis=1))[0]
        if len(ys) < 40:
            continue
        sub = band[ys.min():ys.max() + 1, a:b + 1]
        white = (sub[:, :, 0] > 215) & (sub[:, :, 1] > 215) & (sub[:, :, 2] > 215)
        value = _read_badge_value(_largest_white(white))
        cx = (a + b) // 2
        key = "extra" if cx < 450 else "bomb" if cx < 850 else "remove"
        counts[key] = value
    return counts


def cell_center(r, c):
    return int(round(X0 + (c + 0.5) * CW)), int(round(Y0 + (r + 0.5) * CH))


def legal_options(board, gems, piece):
    shape = np.array(piece["shape"])
    if int(shape.sum()) == 0:
        return []
    found = []
    for r in range(9 - piece["rows"]):
        for c in range(9 - piece["cols"]):
            nb, ng, clears, _fr, _fc, _gm, cells = simulate_step(board, gems, piece, r, c)
            if nb is not None:
                found.append((r, c, clears, nb, ng, cells))
    return found


def classify_threat(board, gems, pieces):
    """ok, hampir (a piece cannot be saved by placing the others), or buntu."""
    filled = int(board.sum())
    if filled < 25:
        return "ok", []
    legal = {p["slot"]: legal_options(board, gems, p) for p in pieces}
    unfit = [p for p in pieces if not legal[p["slot"]]]
    if not unfit:
        return "ok", []
    placeable = [p for p in pieces if legal[p["slot"]]]
    if not placeable:
        return "buntu", unfit

    def opens(order):
        def rec(b, g, rest):
            if not rest:
                return all(legal_options(b, g, p) for p in unfit)
            for _r, _c, _cl, nb, ng, _cells in legal_options(b, g, rest[0]):
                if rec(nb, ng, rest[1:]):
                    return True
            return False
        return rec(board, gems, list(order))

    for order in itertools.permutations(placeable):
        if opens(order):
            return "ok", []
    return "hampir", unfit


def extra_target(board, gems, must_fit, require_all=True):
    """Empty cell where a 1x1 completes a line and frees the stuck pieces."""
    if not must_fit:
        return None
    best = None
    for r in range(8):
        for c in range(8):
            if board[r, c]:
                continue
            nb = board.copy()
            ng = gems.copy()
            nb[r, c] = 1
            full_rows = [i for i in range(8) if nb[i].sum() == 8]
            full_cols = [i for i in range(8) if nb[:, i].sum() == 8]
            if not full_rows and not full_cols:
                continue
            for i in full_rows:
                nb[i, :] = 0
                ng[i, :] = 0
            for i in full_cols:
                nb[:, i] = 0
                ng[:, i] = 0
            opened = [p for p in must_fit if legal_options(nb, ng, p)]
            if require_all and len(opened) < len(must_fit):
                continue
            if not opened:
                continue
            score = (len(full_rows) + len(full_cols)) * 100 + len(opened)
            if best is None or score > best[0]:
                best = (score, r, c)
    if best is None:
        return None
    return best[1], best[2]


def bomb_target(board, gems, pieces):
    """Filled cell whose plus-clear (self + 4 neighbors) makes a piece placeable."""
    best = None
    for r in range(8):
        for c in range(8):
            if board[r, c] == 0:
                continue
            nb = board.copy()
            ng = gems.copy()
            cleared = 0
            for dr, dc in PLUS:
                rr, cc = r + dr, c + dc
                if 0 <= rr < 8 and 0 <= cc < 8 and nb[rr, cc]:
                    nb[rr, cc] = 0
                    ng[rr, cc] = 0
                    cleared += 1
            opened = sum(1 for p in pieces if legal_options(nb, ng, p))
            if opened == 0:
                continue
            score = opened * 100 + cleared
            if best is None or score > best[0]:
                best = (score, r, c)
    if best is None:
        return None
    return best[1], best[2]


def _shop_like(arr):
    center = arr[800:1600, 200:1000, :3]
    light = (center[:, :, 0] > 230) & (center[:, :, 1] > 220) & (center[:, :, 2] > 200)
    return int(light.sum()) > 8000


def arm_booster(name):
    tap(*BOOST_TAP[name])
    time.sleep(0.45)
    im = take_screencap()
    arr = np.array(im)
    if booster_selecting(arr):
        return im
    if _shop_like(arr):
        log.warning("Booster %s opened a shop popup. Backing out.", name)
        adb_shell("input keyevent 4")
        time.sleep(0.4)
        return "shop"
    else:
        log.warning("Booster %s did not enter select mode.", name)
    return None


def cells_filled(board, cells):
    if not cells:
        return False
    for r, c in cells:
        if r < 0 or c < 0 or r >= 8 or c >= 8 or board[r, c] != 1:
            return False
    return True


class Pilot:
    """One shared player. The CLI and the Co-Pilot web auto mode both call tick()."""

    def __init__(self):
        self.failed = {}
        self.level = None
        self.consecutive_empty = 0
        self.moves = 0
        self.ok = 0
        self.fail = 0
        self.last_success = time.time()
        self.last_recovery = 0.0
        self.message = "Siap"
        self.done = False
        self.use_boosters = True
        self.use_revive = True
        self.revives = 0
        self.boost_counts = {"extra": None, "bomb": None, "remove": None}
        self.removes_level = 0
        self.extras_level = 0
        self._boost_level = None
        self.boost_cooldown_until = 0.0
        self._shop_blocked = set()

    def snapshot_fields(self):
        return {
            "level": self.level,
            "ok": self.ok,
            "fail": self.fail,
            "moves": self.moves,
            "message": self.message,
            "done": self.done,
            "boosters": self.use_boosters,
            "revive": self.use_revive,
            "revives": self.revives,
            "boost_counts": self.boost_counts,
        }

    def _pick_booster(self, kind, unfit, board, gems, pieces):
        if kind == "ok" or time.time() < self.boost_cooldown_until:
            return None
        counts = self.boost_counts
        extra_n = counts.get("extra")
        bomb_n = counts.get("bomb")
        remove_n = counts.get("remove")
        if extra_n is not None and extra_n <= 0:
            extra_n = None
        if bomb_n is not None and bomb_n <= 0:
            bomb_n = None
        if remove_n is not None and remove_n <= 0:
            remove_n = None
        if "extra" in self._shop_blocked:
            extra_n = None
        if "bomb" in self._shop_blocked:
            bomb_n = None
        if "remove" in self._shop_blocked:
            remove_n = None

        def biggest(group):
            return max(group, key=lambda p: int(np.array(p["shape"]).sum()))

        if kind == "hampir":
            if extra_n is not None and extra_n > 1 and self.extras_level < 1:
                spot = extra_target(board, gems, unfit, require_all=True)
                if spot:
                    return ("extra", spot)
            if remove_n is not None and remove_n > 1 and self.removes_level < 2 and unfit:
                return ("remove", biggest(unfit))
            return None

        if extra_n and self.extras_level < 1:
            spot = extra_target(board, gems, pieces, require_all=False)
            if spot:
                return ("extra", spot)
        if remove_n and self.removes_level < 2 and unfit:
            return ("remove", biggest(unfit))
        if bomb_n:
            spot = bomb_target(board, gems, pieces)
            if spot:
                return ("bomb", spot)
        if remove_n and self.removes_level < 3 and unfit:
            return ("remove", biggest(unfit))
        return None

    def _confirm_threat(self, board, gems, pieces):
        kind, unfit = classify_threat(board, gems, pieces)
        if kind == "ok":
            return kind, unfit, board, gems, pieces, None
        im2 = take_screencap()
        arr2 = np.array(im2)
        if check_game_state(arr2, im2.size[0], im2.size[1]) != "PLAYING" or booster_selecting(arr2):
            return "ok", [], board, gems, pieces, None
        board2, gems2 = analyze_board(arr2, im2.size[0], im2.size[1])
        pieces2 = detect_dock_pieces(arr2, im2.size[0], im2.size[1])
        kind2, unfit2 = classify_threat(board2, gems2, pieces2)
        if kind2 == "ok" or not pieces2:
            return "ok", [], board2, gems2, pieces2, arr2
        self.boost_counts = read_booster_counts(arr2)
        return kind2, unfit2, board2, gems2, pieces2, arr2

    def _finish_select(self, x, y, still_bad):
        tap(x, y)
        time.sleep(1.05)
        im = take_screencap()
        arr = np.array(im)
        if booster_selecting(arr):
            cancel_booster()
            time.sleep(0.35)
            im = take_screencap()
            return im, False
        if still_bad(np.array(im)):
            return im, False
        return im, True

    def _maybe_boost(self, arr, board, gems, pieces, base):
        if not self.use_boosters:
            return None
        kind, unfit, board, gems, pieces, arr2 = self._confirm_threat(board, gems, pieces)
        if kind == "ok":
            return None
        if arr2 is not None:
            arr = arr2
            base["image"] = Image.fromarray(arr)
            base["board"] = board
            base["gems"] = gems
            base["pieces"] = pieces
        action = self._pick_booster(kind, unfit, board, gems, pieces)
        if action is None:
            if kind == "hampir":
                self.message = "Hampir buntu, stok cadangan disimpan."
                log.info(self.message)
            return None

        name = action[0]
        log.info("Booster %s on %s stock=%s", name, kind, self.boost_counts)
        if name == "remove":
            piece = action[1]
            gx, gy = grab_point(arr, piece)
            armed = arm_booster("remove")
            if armed is None or armed == "shop":
                self.boost_cooldown_until = time.time() + 30
                if armed == "shop":
                    self.boost_counts["remove"] = 0
                    self._shop_blocked.add("remove")
                    log.info("Remove permanently blocked (shop popup = 0 stock).")
                self.message = "Remove gagal masuk mode pilih."
                chk_im = take_screencap()
                chk_arr = np.array(chk_im)
                chk_offer = revive_button(chk_arr)
                if self.use_revive and chk_offer is not None:
                    fw, fh = chk_im.size
                    base_r = self._make_base(chk_im, chk_arr, fw, fh, base["speed"], "DEFEAT")
                    return self._handle_revive(chk_offer, base_r, speed_profile(base["speed"]))
                base["event"] = "wait"
                base["image"] = chk_im
                base.update(self.snapshot_fields())
                return base
            im, ok = self._finish_select(
                gx, gy,
                lambda after: piece_still_there(
                    detect_dock_pieces(after, after.shape[1], after.shape[0]),
                    piece["slot"], piece["shape"],
                ),
            )
            if ok:
                self.removes_level += 1
                if self.boost_counts.get("remove") is not None:
                    self.boost_counts["remove"] = max(0, self.boost_counts["remove"] - 1)
                self.message = f"Remove: buang {piece['slot_name']}"
                log.info(self.message)
            else:
                self.boost_cooldown_until = time.time() + 8
                self.message = f"Remove tidak menghapus {piece['slot_name']}."
                log.warning(self.message)
        elif name == "extra":
            r, c = action[1]
            x, y = cell_center(r, c)
            armed = arm_booster("extra")
            if armed is None or armed == "shop":
                self.boost_cooldown_until = time.time() + 30
                if armed == "shop":
                    self.boost_counts["extra"] = 0
                    self._shop_blocked.add("extra")
                    log.info("Extra permanently blocked (shop popup = 0 stock).")
                self.message = "Ekstra Balok gagal masuk mode pilih."
                chk_im = take_screencap()
                chk_arr = np.array(chk_im)
                chk_offer = revive_button(chk_arr)
                if self.use_revive and chk_offer is not None:
                    fw, fh = chk_im.size
                    base_r = self._make_base(chk_im, chk_arr, fw, fh, base["speed"], "DEFEAT")
                    return self._handle_revive(chk_offer, base_r, speed_profile(base["speed"]))
                base["event"] = "wait"
                base["image"] = chk_im
                base.update(self.snapshot_fields())
                return base
            im, ok = self._finish_select(x, y, lambda after: False)
            if ok:
                self.extras_level += 1
                if self.boost_counts.get("extra") is not None:
                    self.boost_counts["extra"] = max(0, self.boost_counts["extra"] - 1)
                self.message = f"Ekstra Balok di baris {r + 1}, kolom {c + 1}"
                log.info(self.message)
            else:
                self.boost_cooldown_until = time.time() + 8
                self.message = "Ekstra Balok dibatalkan."
                log.warning(self.message)
        else:
            r, c = action[1]
            x, y = cell_center(r, c)
            armed = arm_booster("bomb")
            if armed is None or armed == "shop":
                self.boost_cooldown_until = time.time() + 30
                if armed == "shop":
                    self.boost_counts["bomb"] = 0
                    self._shop_blocked.add("bomb")
                    log.info("Bomb permanently blocked (shop popup = 0 stock).")
                self.message = "Bom gagal masuk mode pilih."
                chk_im = take_screencap()
                chk_arr = np.array(chk_im)
                chk_offer = revive_button(chk_arr)
                if self.use_revive and chk_offer is not None:
                    fw, fh = chk_im.size
                    base_r = self._make_base(chk_im, chk_arr, fw, fh, base["speed"], "DEFEAT")
                    return self._handle_revive(chk_offer, base_r, speed_profile(base["speed"]))
                base["event"] = "wait"
                base["image"] = chk_im
                base.update(self.snapshot_fields())
                return base

            def bomb_missed(after):
                fw, fh = after.shape[1], after.shape[0]
                board_after, _gems = analyze_board(after, fw, fh)
                return board_after[r, c] == 1

            im, ok = self._finish_select(x, y, bomb_missed)
            if ok:
                if self.boost_counts.get("bomb") is not None:
                    self.boost_counts["bomb"] = max(0, self.boost_counts["bomb"] - 1)
                self.message = f"Bom di baris {r + 1}, kolom {c + 1}"
                log.info(self.message)
            else:
                self.boost_cooldown_until = time.time() + 12
                self.message = "Bom tidak meledak. Dibatalkan."
                log.warning(self.message)

        after = np.array(im)
        fw, fh = im.size
        base["image"] = im
        base["game_state"] = check_game_state(after, fw, fh)
        base["board"], base["gems"] = analyze_board(after, fw, fh)
        base["pieces"] = detect_dock_pieces(after, fw, fh)
        self.boost_counts = read_booster_counts(after)
        base["event"] = "boost"
        base.update(self.snapshot_fields())
        return base

    def _do_revive(self, spot):
        if spot is None:
            return False
        log.info("Revive tap %s", spot)
        tap(*spot)
        saw_warung = False
        playing_hits = 0
        for _ in range(14):
            time.sleep(0.35)
            im = take_screencap()
            frame = np.array(im)
            if warung_open(frame):
                saw_warung = True
                if warung_ready(frame):
                    break
                continue
            again = revive_button(frame)
            if again is not None:
                log.info("Revive still on screen. Tap again %s", again)
                tap(*again)
                playing_hits = 0
                continue
            if check_game_state(frame, im.size[0], im.size[1]) == "PLAYING":
                playing_hits += 1
                if playing_hits >= 2:
                    log.info("Revive instan, tanpa halaman iklan.")
                    return True
            else:
                playing_hits = 0
        if not saw_warung:
            log.warning("Halaman Warung tidak muncul.")
            return False
        wait_until = time.time() + 6
        while time.time() < wait_until:
            frame = np.array(take_screencap())
            if warung_ready(frame):
                break
            time.sleep(0.4)
        self.message = "Revive: scroll iklan 33 detik."
        log.info(self.message)
        scroll_warung(REVIVE_SCROLL_S)
        time.sleep(0.6)
        im = exit_warung()
        for _ in range(8):
            frame = np.array(im)
            if check_game_state(frame, im.size[0], im.size[1]) == "PLAYING" and not warung_open(frame):
                return True
            time.sleep(0.45)
            im = take_screencap()
        return False

    def _make_base(self, im, arr, fw, fh, speed_name, state):
        base = {
            "image": im,
            "game_state": state,
            "screen_dims": {"w": fw, "h": fh},
            "speed": str(speed_name),
            "sequence": [],
            "pieces": [],
            "board": None,
            "gems": None,
            "best_score": 0,
            "solve_time_ms": 0,
        }
        base.update(self.snapshot_fields())
        return base

    def _handle_revive(self, offer, base, profile):
        ok = self._do_revive(offer)
        if ok:
            self.revives += 1
            self.message = f"Revive #{self.revives} di level {self.level or '?'}. Lanjut."
            log.info(self.message)
            self.failed.clear()
            self.consecutive_empty = 0
            self.last_success = time.time()
            base["event"] = "revive"
            base["image"] = take_screencap()
            base["game_state"] = "PLAYING"
            base.update(self.snapshot_fields())
            return base
        log.warning("Revive gagal. Cek layar sebelum Main Lagi.")
        return self._handle_defeat(base, profile)

    def _handle_defeat(self, base, profile):
        for attempt in range(3):
            fresh = take_screencap()
            fresh_arr = np.array(fresh)
            offer2 = revive_button(fresh_arr)
            if self.use_revive and offer2 is not None:
                return self._handle_revive(offer2, base, profile)
            if warung_open(fresh_arr):
                exit_warung()
                self.revives += 1
                self.message = f"Revive #{self.revives} di level {self.level or '?'}. Lanjut."
                self.failed.clear()
                self.last_success = time.time()
                base["event"] = "revive"
                base["image"] = take_screencap()
                base.update(self.snapshot_fields())
                return base
            gs = check_game_state(fresh_arr, fresh.size[0], fresh.size[1])
            if gs == "PLAYING" and not warung_open(fresh_arr) and revive_button(fresh_arr) is None:
                self.message = f"Sudah kembali ke level {self.level or '?'}."
                self.failed.clear()
                self.last_success = time.time()
                base["event"] = "revive"
                base["image"] = fresh
                base.update(self.snapshot_fields())
                return base
            if gs == "DEFEAT":
                break
            if attempt < 2:
                time.sleep(0.6)
        again = main_lagi_button(fresh_arr) or NEXT_BUTTON
        self.message = f"Kalah di level {self.level or '?'}. Main lagi."
        log.warning(self.message)
        tap(*again)
        time.sleep(profile.get("popup", 1.0))
        self.failed.clear()
        self.moves = 0
        self.last_success = time.time()
        base.update(self.snapshot_fields())
        base["event"] = "defeat"
        self.removes_level = 0
        self.extras_level = 0
        return base

    def tick(self, speed_name="1"):
        profile = speed_profile(speed_name)
        im = take_screencap()
        arr = np.array(im)
        fw, fh = im.size

        offer = revive_button(arr)
        if offer is not None:
            base = self._make_base(im, arr, fw, fh, speed_name, "DEFEAT")
            if not self.use_revive:
                log.info("Revive dimatikan. Menunggu tombol Main Lagi.")
                time.sleep(6.2)
                offer = None
            if self.use_revive and offer is not None:
                return self._handle_revive(offer, base, profile)
            return self._handle_defeat(base, profile)

        state = check_game_state(arr, fw, fh)
        if state == "PLAYING":
            self.level = accept_level(self.level, read_level(arr))

        base = self._make_base(im, arr, fw, fh, speed_name, state)

        if self.level is not None and self.level > TARGET_LEVEL:
            self.done = True
            self.message = f"Level {self.level} lewat target {TARGET_LEVEL}."
            log.info(self.message)
            base.update(self.snapshot_fields())
            return base

        if state == "VICTORY":
            if self.level is not None and self.level >= TARGET_LEVEL:
                self.done = True
                self.message = f"Level {self.level} selesai. Target tercapai."
                log.info(self.message)
                base.update(self.snapshot_fields())
                return base
            self.message = f"Menang di level {self.level or '?'}. Lanjut."
            log.info(self.message)
            tap(*NEXT_BUTTON)
            time.sleep(profile["popup"])
            self.failed.clear()
            self.moves = 0
            self.last_success = time.time()
            if self.level is not None:
                self.level += 1
            base.update(self.snapshot_fields())
            base["event"] = "victory"
            return base

        if state == "DEFEAT":
            return self._handle_defeat(base, profile)

        if booster_selecting(arr):
            log.warning("Booster select leftover. Cancelling.")
            cancel_booster()
            time.sleep(0.45)
            self.message = "Mode booster dibatalkan."
            base["event"] = "wait"
            base["image"] = take_screencap()
            base.update(self.snapshot_fields())
            return base

        board, gems = analyze_board(arr, fw, fh)
        pieces = detect_dock_pieces(arr, fw, fh)
        base["board"] = board
        base["gems"] = gems
        base["pieces"] = pieces

        if not pieces:
            self.consecutive_empty += 1
            self.message = "Menunggu balok baru."
            if self.consecutive_empty >= 14 and time.time() - self.last_recovery > 20:
                self.message = "Dock kosong lama. Mencoba tombol lanjut."
                log.warning(self.message)
                tap(*NEXT_BUTTON)
                self.last_recovery = time.time()
                self.consecutive_empty = 0
            time.sleep(max(0.15, profile["wait"] * 0.6))
            base.update(self.snapshot_fields())
            base["event"] = "wait"
            return base
        self.consecutive_empty = 0

        if time.time() - self.last_success > 45 and self.failed:
            log.warning("No successful drop for 45s. Clearing failed-cell memory.")
            self.failed.clear()
            self.last_success = time.time()

        fresh_counts = read_booster_counts(arr)
        for bk in ("extra", "bomb", "remove"):
            if self.boost_counts.get(bk) == 0:
                pass
            elif fresh_counts.get(bk) is not None:
                self.boost_counts[bk] = fresh_counts[bk]
        if self.level != self._boost_level:
            self._boost_level = self.level
            self.removes_level = 0
            self.extras_level = 0
            self.boost_counts = {"extra": None, "bomb": None, "remove": None}
        boosted = self._maybe_boost(arr, board, gems, pieces, base)
        if boosted is not None:
            return boosted

        if speed_name == "adaptive":
            solver_budget = adaptive_solver_budget(board)
            profile = adaptive_profile(board)
        elif speed_name == "max":
            solver_budget = 800
        else:
            solver_budget = 0
        step, seq, score, solve_ms = choose_move(board, gems, pieces, self.failed, max_ms=solver_budget)
        base["sequence"] = seq
        base["best_score"] = score
        base["solve_time_ms"] = round(solve_ms, 1)
        if step is None:
            stock = self.boost_counts
            self.message = (
                f"Tidak ada letak legal ({int(board.sum())}/64). "
                f"Stok +{stock.get('extra')} bom {stock.get('bomb')} X {stock.get('remove')}."
            )
            log.warning(self.message)
            time.sleep(0.8)
            base.update(self.snapshot_fields())
            base["event"] = "idle"
            return base

        piece = next(p for p in pieces if p["slot"] == step["slot"])
        r, c = step["r"], step["c"]
        clears = step["clears"]
        key = (piece["slot"], r, c)
        gx, gy = grab_point(arr, piece)
        fx, fy, board_cx, board_cy = calc_finger_target((gx, gy), piece["rows"], piece["cols"], r, c)
        self.moves += 1
        self.message = f"{piece['slot_name']} → baris {r + 1}, kolom {c + 1}"
        log.info(
            "[%sx L%s M%s] %s %sx%s -> (r%s, c%s) clears=%s finger=(%s,%s)",
            speed_name,
            self.level if self.level is not None else "?",
            self.moves,
            piece["slot_name"],
            piece["rows"],
            piece["cols"],
            r + 1,
            c + 1,
            clears,
            fx,
            fy,
        )
        execute_drag(
            gx, gy, fx, fy,
            steps=profile["steps"],
            move_sleep=profile["move"],
            down_sleep=profile["down"],
            hold=profile["hold"],
        )
        time.sleep(profile["clear"] if clears else profile["wait"])

        after_im = take_screencap()
        after = np.array(after_im)
        pieces_after = detect_dock_pieces(after, fw, fh)
        board_after, gems_after = analyze_board(after, fw, fh)
        consumed = not piece_still_there(pieces_after, piece["slot"], piece["shape"])
        if not consumed:
            time.sleep(profile["recheck"])
            after_im = take_screencap()
            after = np.array(after_im)
            pieces_after = detect_dock_pieces(after, fw, fh)
            board_after, gems_after = analyze_board(after, fw, fh)
            consumed = not piece_still_there(pieces_after, piece["slot"], piece["shape"])

        landed = cells_filled(board_after, step.get("cells"))
        success = consumed or (landed and clears == 0)
        if success:
            self.failed.clear()
            self.ok += 1
            self.last_success = time.time()
            log.info("  drop ok dock=%s ok/fail=%s/%s", len(pieces_after), self.ok, self.fail)
            event = "drop"
        else:
            self.failed[key] = self.failed.get(key, 0) + 1
            self.fail += 1
            self.message = f"Meleset {piece['slot_name']} ({self.failed[key]}/2)"
            log.warning("  drop miss attempt %s/2 for %s", self.failed[key], key)
            event = "miss"

        offer_post = revive_button(after)
        if offer_post is not None:
            base_post = self._make_base(after_im, after, fw, fh, speed_name, "DEFEAT")
            if self.use_revive:
                return self._handle_revive(offer_post, base_post, profile)
            return self._handle_defeat(base_post, profile)

        if speed_name in ("max", "adaptive"):
            base.update({
                "image": after_im,
                "game_state": check_game_state(after, fw, fh),
                "sequence": [],
                "pieces": pieces_after,
                "board": board_after,
                "gems": gems_after,
                "best_score": 0,
                "solve_time_ms": 0,
                "event": event,
            })
        else:
            seq2, score2, solve_ms2 = solve_full_sequence(board_after, gems_after, pieces_after)
            base.update({
                "image": after_im,
                "game_state": check_game_state(after, fw, fh),
                "sequence": seq2,
                "pieces": pieces_after,
                "board": board_after,
                "gems": gems_after,
                "best_score": score2,
                "solve_time_ms": round(solve_ms2, 1),
                "event": event,
            })
        base.update(self.snapshot_fields())
        return base


def run_bot(speed="1"):
    log.info(
        "=== AUTOBOT v5 STARTED target=%s scale=%.3f lift=%.0f speed=%s ===",
        TARGET_LEVEL, SCALE, LIFT, speed,
    )
    pilot = Pilot()
    while not pilot.done:
        try:
            pilot.tick(speed)
        except subprocess.TimeoutExpired:
            log.error("adb timed out, retrying")
            time.sleep(1.0)
        except Exception as exc:
            log.error("engine error: %s", exc, exc_info=True)
            time.sleep(1.0)


if __name__ == "__main__":
    run_bot()
