"""
Core logic for the MapleStory EXP tracker. Nothing in this file needs a GUI.

* Finds the game window and the EXP text inside it (fixed offsets from the window's
  bottom-center), grabs those few pixels and reads them with a built-in pixel font.
* Knows the EXP required per level, works out your level, and tracks gains.
* Session handling: start / pause / idle time-out / auto-restart, mesos, rates.
"""
from __future__ import annotations

import bisect
import ctypes
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

# --------------------------------------------------------------------------- #
# Paths and configuration
# --------------------------------------------------------------------------- #


def data_dir() -> Path:
    env = os.environ.get("EXP_TRACKER_DATA")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):  # PyInstaller build
        return Path(sys.executable).resolve().parent / "exp_tracker_data"
    return Path(__file__).resolve().parent / "exp_tracker_data"


DEFAULT_CONFIG = {
    "window_title": "MapleStory",   # the game window's title must contain this text
    "window_mode": "auto",          # "auto": find the game window; "screen": use the whole primary screen
    # Where the EXP text is, relative to the game window's client area (see compute_region):
    #   dx: pixels right of the window's horizontal center to the left edge of the box
    #   dy: pixels above the window's bottom edge to the top of the box
    "exp_region": {"dx": 63, "dy": 32, "w": 100, "h": 13},
    "threshold": 160,               # brightness cut-off (0-255) for "this pixel is text"
    "max_glyph_dist": 0.15,         # how different a character may look from a known one (0 = identical)
    "interval": 1.0,                # seconds between screen reads
    "timeout_seconds": 15,          # pause the clock after this long without EXP gain (0 = never)
    "auto_start": True,             # AUTO: start / restart the clock when EXP is gained. MANUAL: only the play button
    "level_override": 0,            # 0 = work the level out automatically
    "opacity": 1.0,                 # overlay background opacity, 0.6-1.0 (text is always solid)
    "read_mesos": True,             # read the mesos from the inventory window whenever it is open
    "read_quickslots": True,        # count the consumables in the quick slots (potion cost)
    "overlay": {"x": 60, "y": 60, "placed": False},   # placed: docked once next to the game's status bar
}


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(data_dir() / "config.json", "r", encoding="utf-8") as f:
            user = json.load(f)
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            elif k in cfg:
                cfg[k] = v
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, OSError, AttributeError) as e:
        print(f"Warning: could not read config.json ({e}); using defaults.")
    return cfg


def _atomic_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)


def save_config(cfg: dict) -> None:
    _atomic_write_json(data_dir() / "config.json", cfg)


# --------------------------------------------------------------------------- #
# Reading pixels: binarize -> split into characters -> match against known shapes
# --------------------------------------------------------------------------- #

# The game's HUD font (5x7 pixels), taken from real screenshots. Learned characters the user
# adds are stored next to these in glyphs.json.
SEED_GLYPHS = {
    '%': ['0100001', '1010010', '0100100', '0001000', '0010010', '0100101', '1000010'],
    ',': ['01', '10'],
    '.': ['1'],
    '0': ['01110', '10001', '10001', '10001', '10001', '10001', '01110'],
    '1': ['01', '11', '01', '01', '01', '01', '01'],
    '2': ['01110', '10001', '00001', '00010', '00100', '01000', '11111'],
    '3': ['01110', '10001', '00001', '00110', '00001', '10001', '01110'],
    '4': ['00010', '00110', '01010', '10010', '11111', '00010', '00010'],
    '5': ['11111', '10000', '10000', '01110', '00001', '10001', '01110'],
    '6': ['01110', '10001', '10000', '11110', '10001', '10001', '01110'],
    '7': ['11111', '00001', '00001', '00001', '00010', '00100', '00100'],
    '8': ['01110', '10001', '10001', '01110', '10001', '10001', '01110'],
    '9': ['01110', '10001', '10001', '01111', '00001', '10001', '01110'],
    '[': ['11', '10', '10', '10', '10', '10', '11'],
    ']': ['11', '01', '01', '01', '01', '01', '11'],
}


@dataclass
class Glyph:
    x0: int
    x1: int  # exclusive
    y0: int
    y1: int  # exclusive
    bitmap: np.ndarray  # bool (h, w), tight bounding box


@dataclass
class FrameRead:
    mask: np.ndarray
    glyphs: List[Glyph]
    text: str            # recognised text, '?' for unknown glyphs, ' ' for wide gaps
    unknown: List[int]   # indexes into glyphs


def binarize(rgb: np.ndarray, threshold: int) -> np.ndarray:
    """True where a pixel is text (bright). The HUD text is white; the [ ] brackets are green."""
    mask = rgb.max(axis=2) >= threshold
    h, w = mask.shape
    if h and w:
        mask[mask.mean(axis=1) > 0.9, :] = False  # frame lines spanning the whole crop
        for x in list(range(min(2, w))) + list(range(max(w - 2, 0), w)):
            if mask[:, x].mean() > 0.9:
                mask[:, x] = False
    return mask


def segment(mask: np.ndarray) -> List[Glyph]:
    """Split a binary text line into glyphs using empty pixel columns as separators."""
    cols = mask.any(axis=0)
    glyphs: List[Glyph] = []
    w = len(cols)
    x = 0
    while x < w:
        if not cols[x]:
            x += 1
            continue
        start = x
        while x < w and cols[x]:
            x += 1
        sub = mask[:, start:x]
        rows = np.where(sub.any(axis=1))[0]
        y0, y1 = int(rows[0]), int(rows[-1]) + 1
        glyphs.append(Glyph(start, x, y0, y1, sub[y0:y1].copy()))
    return glyphs


def glyph_distance(a: np.ndarray, b: np.ndarray) -> float:
    """1 - IoU of two tight-cropped bitmaps (top-left aligned). 1.0 if sizes differ by more than 1px."""
    ha, wa = a.shape
    hb, wb = b.shape
    if abs(ha - hb) > 1 or abs(wa - wb) > 1:
        return 1.0
    h, w = max(ha, hb), max(wa, wb)
    pa = np.zeros((h, w), dtype=bool)
    pb = np.zeros((h, w), dtype=bool)
    pa[:ha, :wa] = a
    pb[:hb, :wb] = b
    union = int(np.logical_or(pa, pb).sum())
    if union == 0:
        return 1.0
    return 1.0 - int(np.logical_and(pa, pb).sum()) / union


def _bitmap_to_rows(bm: np.ndarray) -> List[str]:
    return ["".join("1" if v else "0" for v in row) for row in bm]


def _rows_to_bitmap(rows: List[str]) -> np.ndarray:
    return np.array([[c == "1" for c in r] for r in rows], dtype=bool)


class GlyphLibrary:
    """Known characters: the built-in seeds plus anything the user taught it."""

    def __init__(self, path: Optional[Path] = None, use_seeds: bool = True, seeds: Optional[dict] = None):
        self.path = Path(path) if path else data_dir() / "glyphs.json"
        self.use_seeds = use_seeds
        self.seeds = SEED_GLYPHS if seeds is None else seeds
        self.items: List[Tuple[str, np.ndarray]] = []
        self.user_items: List[Tuple[str, np.ndarray]] = []
        self._rebuild()

    def _rebuild(self) -> None:
        seeds = [(l, _rows_to_bitmap(r)) for l, r in self.seeds.items()] if self.use_seeds else []
        self.items = seeds + list(self.user_items)

    def load(self) -> "GlyphLibrary":
        self.user_items = []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.user_items = [(g["label"], _rows_to_bitmap(g["rows"])) for g in data.get("glyphs", [])]
        except FileNotFoundError:
            pass
        except (json.JSONDecodeError, KeyError, TypeError, OSError) as e:
            print(f"Warning: could not read {self.path} ({e}); ignoring learned characters.")
        self._rebuild()
        return self

    def save(self) -> None:
        data = {"version": 2, "glyphs": [{"label": l, "rows": _bitmap_to_rows(b)} for l, b in self.user_items]}
        _atomic_write_json(self.path, data)

    def clear_user(self) -> None:
        self.user_items = []
        self._rebuild()

    def labels(self) -> List[str]:
        return sorted({l for l, _ in self.items})

    def add(self, label: str, bitmap: np.ndarray) -> None:
        for l, b in self.items:
            if l == label and b.shape == bitmap.shape and np.array_equal(b, bitmap):
                return
        self.user_items.append((label, bitmap.copy()))
        self._rebuild()

    def match(self, bitmap: np.ndarray, max_dist: float) -> Optional[str]:
        """The character for this bitmap, or None if unknown or ambiguous."""
        best: Dict[str, float] = {}
        for label, bm in self.items:
            d = glyph_distance(bitmap, bm)
            if label not in best or d < best[label]:
                best[label] = d
        if not best:
            return None
        ordered = sorted(best.items(), key=lambda kv: kv[1])
        label, d = ordered[0]
        if d <= 0.02:
            return label
        if d > max_dist:
            return None
        if len(ordered) > 1 and ordered[1][1] - d < 0.05:
            return None
        return label


def read_text(rgb: np.ndarray, threshold: int, lib: GlyphLibrary, max_dist: float,
              space_gap: int = 6) -> FrameRead:
    mask = binarize(rgb, threshold)
    glyphs = segment(mask)
    chars: List[str] = []
    unknown: List[int] = []
    prev_end = None
    for i, g in enumerate(glyphs):
        if prev_end is not None and g.x0 - prev_end >= space_gap:
            chars.append(" ")
        prev_end = g.x1
        label = lib.match(g.bitmap, max_dist)
        if label is None:
            chars.append("?")
            unknown.append(i)
        else:
            chars.append(label)
    return FrameRead(mask, glyphs, "".join(chars), unknown)


def label_from_text(lib: GlyphLibrary, glyphs: List[Glyph], typed: str, max_dist: float) -> int:
    """Teach the library: the typed text (spaces ignored) needs one character per glyph."""
    chars = [c for c in typed if not c.isspace()]
    if len(chars) != len(glyphs):
        raise ValueError(f"I see {len(glyphs)} characters but you typed {len(chars)}. "
                         "Type one character for each glyph in the picture (spaces are ignored).")
    if "?" in chars:
        raise ValueError("Replace every '?' with the real character first.")
    added = 0
    for g, c in zip(glyphs, chars):
        if lib.match(g.bitmap, max_dist) != c:
            lib.add(c, g.bitmap)
            added += 1
    return added


# --------------------------------------------------------------------------- #
# Parsing "6,340[89.93%]"
# --------------------------------------------------------------------------- #

_NUM = re.compile(r"^[^0-9?]*((?:\d{1,3}(?:,\d{3})+)|\d+)(.*)$")
_PCT = re.compile(r"^[\[(](\d{1,3}\.\d{1,2})%")


def parse_exp_text(text: str) -> Optional[Tuple[int, Optional[float]]]:
    """(exp, percent or None). The percent is optional (it can be clipped or unreadable).
    Returns None unless the EXP number itself is a clean, correctly comma-grouped number."""
    if not text:
        return None
    t = re.sub(r"\s+", "", text)
    m = _NUM.match(t)
    if not m:
        return None
    num, rest = m.group(1), m.group(2)
    if rest and rest[0] not in "[(%":
        return None  # something odd follows the number (e.g. "6,34" or "6,3?0")
    exp = int(num.replace(",", ""))
    pct = None
    pm = _PCT.match(rest)
    if pm:
        v = float(pm.group(1))
        if 0.0 <= v <= 100.0:
            pct = v
    return exp, pct


@dataclass
class ExpReading:
    exp: Optional[int]
    pct: Optional[float]
    text: str
    glyphs: int
    unknown: int


def read_exp(rgb: np.ndarray, cfg: dict, lib: GlyphLibrary) -> Tuple[ExpReading, FrameRead]:
    fr = read_text(rgb, cfg["threshold"], lib, cfg["max_glyph_dist"])
    parsed = parse_exp_text(fr.text)
    exp, pct = parsed if parsed else (None, None)
    return ExpReading(exp, pct, fr.text, len(fr.glyphs), len(fr.unknown)), fr


# --------------------------------------------------------------------------- #
# Finding the game window and the EXP region inside it
# --------------------------------------------------------------------------- #


def compute_region(win: dict, spec: dict) -> Optional[dict]:
    """Screen rectangle of the EXP text. `win` is the game window's client area
    ({'left','top','width','height'}); the HUD sits at a fixed offset from its bottom-center."""
    W, H = int(win["width"]), int(win["height"])
    left = int(win["left"]) + W // 2 + int(spec["dx"])
    top = int(win["top"]) + H - int(spec["dy"])
    w, h = int(spec["w"]), int(spec["h"])
    if w < 4 or h < 4:
        return None
    if left < win["left"] or top < win["top"] or left + w > win["left"] + W or top + h > win["top"] + H:
        return None
    return {"left": left, "top": top, "width": w, "height": h}


def _find_window_windows(title_sub: str) -> Optional[dict]:
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    needle = title_sub.lower()
    # other programs often mention the game in their title (a browser tab, a chat window...)
    not_game = ("google chrome", "microsoft edge", "mozilla firefox", "opera", "brave", "discord", "visual studio",
                "notepad", "explorer", "exp tracker")
    found: List[Tuple[Tuple[int, int], dict]] = []

    def cb(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            title = buf.value
            low = title.lower()
            if needle not in low or any(bad in low for bad in not_game):
                return True
            rc = wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(rc))
            pt = wintypes.POINT(0, 0)
            user32.ClientToScreen(hwnd, ctypes.byref(pt))
            w, h = rc.right - rc.left, rc.bottom - rc.top
            if w >= 640 and h >= 480:
                rank = 2 if low == needle else (1 if low.startswith(needle) else 0)
                found.append(((rank, w * h), {"left": pt.x, "top": pt.y, "width": w, "height": h, "title": title}))
        except Exception:
            pass
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    if not found:
        return None
    return max(found, key=lambda t: t[0])[1]


def find_game_window(cfg: dict) -> Optional[dict]:
    """Client area of the game window in screen pixels, or None if it can't be found."""
    if cfg.get("window_mode") == "screen":
        import mss
        with mss.mss() as sct:
            m = sct.monitors[1]
            return {"left": m["left"], "top": m["top"], "width": m["width"], "height": m["height"],
                    "title": "(primary screen)"}
    if sys.platform == "win32":
        return _find_window_windows(cfg.get("window_title") or "MapleStory")
    return None


class Capturer:
    def __init__(self):
        import mss
        self._mss = mss
        self.sct = mss.mss()

    def grab(self, region: dict) -> np.ndarray:
        shot = self.sct.grab({"left": int(region["left"]), "top": int(region["top"]),
                              "width": int(region["width"]), "height": int(region["height"])})
        arr = np.asarray(shot)  # BGRA
        return np.ascontiguousarray(arr[:, :, 2::-1])  # RGB


# --------------------------------------------------------------------------- #
# Mesos from the inventory window
# --------------------------------------------------------------------------- #
# The "ITEM INVENTORY" title text looks the same in every tab, and the mesos box sits a fixed number of
# pixels below it, so: find the title in a screenshot of the game window, then read the box.

# '#' = dark text pixel, '.' = plain white title bar, ' ' = don't care. 86x13 px, taken from a real screenshot.
INV_TITLE = [
    "......................................................................................",
    "............................................................... ......................",
    "............. ..... ................................ .................................",
    "              .   ..     .     .           .                       .   ...............",
    "##### ##### #   # .. # #   # # . # ##### #   # #####  ###  ####  #   # ...............",
    "  #   #     ## ## .. # ##  # # . # #     ##  #   #   #   # #   #  # #  . .............",
    ". # . ####  # # # .. # # # # #   # ####  # # # . # . # . # ####    #  ... ............",
    ". # . #     #   # .. # #  ##  # #  #     #  ## . # . #   # #   # . # ... .............",
    ". #   ##### # . # .. # #   #   #   ##### #   # . # .  ###  # . # . # .................",
    ".   .         .   ..     .   .   .         .   .   ..        .   .   .................",
    "......................................................................................",
    "......................................................................................",
    "......................................................................................",
]
INV_MESO_BOX = {"dx": 14, "dy": 263, "w": 142, "h": 13}   # relative to the title template's top-left corner

# The inventory's digit font (8 px tall), taken from real screenshots.
MESO_GLYPHS = {
    ',': ['01', '01', '01', '10'],
    '0': ['01110', '10001', '10001', '10001', '10001', '10001', '10001', '01110'],
    '1': ['010', '110', '010', '010', '010', '010', '010', '111'],
    '2': ['01110', '10001', '00001', '00010', '00100', '01000', '10000', '11111'],
    '3': ['01110', '10001', '00001', '00110', '00001', '00001', '10001', '01110'],
    '4': ['00010', '00110', '01010', '10010', '11111', '00010', '00010', '00010'],
    '5': ['11111', '10000', '10000', '11110', '00001', '00001', '10001', '01110'],
    '6': ['00110', '01000', '10000', '11110', '10001', '10001', '10001', '01110'],
    '7': ['11111', '00001', '00010', '00010', '00100', '00100', '01000', '01000'],
    '8': ['01110', '10001', '10001', '01110', '10001', '10001', '10001', '01110'],
    '9': ['01110', '10001', '10001', '10001', '01111', '00001', '00010', '01100'],
}
_MESO_RE = re.compile(r"^\d{1,3}(,\d{3})*$")
_INV_DARK, _INV_WHITE = 110, 225   # gray levels that count as "text" / "title bar"


def _inv_keys(ch: str) -> Tuple[np.ndarray, np.ndarray]:
    pts = [(y, x) for y, row in enumerate(INV_TITLE) for x, c in enumerate(row) if c == ch]
    return np.array([p[0] for p in pts]), np.array([p[1] for p in pts])


def find_inventory_title(gray: np.ndarray) -> Optional[Tuple[int, int]]:
    """Top-left (x, y) of the inventory title in a grayscale screenshot, or None."""
    th, tw = len(INV_TITLE), len(INV_TITLE[0])
    H, W = gray.shape
    if H < th or W < tw:
        return None
    dy, dx = _inv_keys("#")
    wy, wx = _inv_keys(".")
    ny, nx = H - th + 1, W - tw + 1
    sel = np.linspace(0, len(dy) - 1, 14).astype(int)
    wsel = np.linspace(0, len(wy) - 1, 14).astype(int)
    cnt = np.zeros((ny, nx), dtype=np.uint8)
    for i in sel:
        cnt += gray[dy[i]:dy[i] + ny, dx[i]:dx[i] + nx] < _INV_DARK
    for i in wsel:
        cnt += gray[wy[i]:wy[i] + ny, wx[i]:wx[i] + nx] > _INV_WHITE
    cy, cx = np.nonzero(cnt >= len(sel) + len(wsel) - 2)
    if len(cy) == 0:
        return None
    cy, cx = cy[:2000], cx[:2000]
    dark = (gray[cy[:, None] + dy[None, :], cx[:, None] + dx[None, :]] < _INV_DARK).mean(axis=1)
    white = (gray[cy[:, None] + wy[None, :], cx[:, None] + wx[None, :]] > _INV_WHITE).mean(axis=1)
    i = int((dark + white).argmax())
    if dark[i] >= 0.9 and white[i] >= 0.95:
        return int(cx[i]), int(cy[i])
    return None


def inventory_title_matches(gray: np.ndarray) -> bool:
    if gray.shape[0] < len(INV_TITLE) or gray.shape[1] < len(INV_TITLE[0]):
        return False
    dy, dx = _inv_keys("#")
    wy, wx = _inv_keys(".")
    return bool((gray[dy, dx] < _INV_DARK).mean() >= 0.9 and (gray[wy, wx] > _INV_WHITE).mean() >= 0.95)


def parse_mesos(rgb: np.ndarray, lib: GlyphLibrary, max_dist: float = 0.15) -> Optional[int]:
    """The number in the inventory's mesos box (dark digits on white), or None if unreadable."""
    glyphs = segment(rgb.max(axis=2) < 140)
    if not glyphs:
        return None
    text = "".join(lib.match(g.bitmap, max_dist) or "?" for g in glyphs)
    return int(text.replace(",", "")) if _MESO_RE.match(text) else None


class InventoryReader:
    """Finds the open inventory window in the game and reads the mesos from it."""
    SEARCH_EVERY = 2.0     # seconds between full-window searches while the inventory isn't found

    def __init__(self, max_dist: float = 0.15):
        self.lib = GlyphLibrary(use_seeds=True, seeds=MESO_GLYPHS)
        self.max_dist = max_dist
        self.origin: Optional[Tuple[int, int]] = None   # title top-left, relative to the game window
        self.last_search = -1e9

    def poll(self, capture, win: dict, now: float) -> Optional[int]:
        """Mesos if the inventory is open and readable now, else None."""
        if self.origin is not None:
            region = {"left": win["left"] + self.origin[0], "top": win["top"] + self.origin[1],
                      "width": len(INV_TITLE[0]), "height": len(INV_TITLE)}
            if not inventory_title_matches(capture.grab(region).mean(axis=2)):
                self.origin = None
        if self.origin is None:
            if now - self.last_search < self.SEARCH_EVERY:
                return None
            self.last_search = now
            frame = capture.grab({"left": win["left"], "top": win["top"],
                                  "width": win["width"], "height": win["height"]})
            self.origin = find_inventory_title(frame.mean(axis=2))
            if self.origin is None:
                return None
        b = INV_MESO_BOX
        box = {"left": win["left"] + self.origin[0] + b["dx"], "top": win["top"] + self.origin[1] + b["dy"],
               "width": b["w"], "height": b["h"]}
        return parse_mesos(capture.grab(box), self.lib, self.max_dist)


# --------------------------------------------------------------------------- #
# EXP table
# --------------------------------------------------------------------------- #

# EXP needed to go from level N to N+1 (index 0 = level 1), from the official Classic World table.
EXP_TO_NEXT = [
    15, 34, 57, 92, 135, 372,
    560, 840, 1242, 1716, 2360, 3216,
    4200, 5460, 7050, 8840, 11040, 13716,
    16680, 20216, 24402, 28980, 34320, 40512,
    47216, 54900, 63666, 73080, 83720, 95700,
    108480, 122760, 138666, 155540, 174216, 194832,
    216600, 240500, 266682, 294216, 324240, 356916,
    391160, 428280, 468450, 510420, 555680, 604416,
    655200, 709716, 748608, 789631, 832902, 878545,
    926689, 977471, 1031036, 1087536, 1147132, 1209994,
    1276301, 1346242, 1420016, 1497832, 1579913, 1666492,
    1757815, 1854143, 1955750, 2062925, 2175973, 2295216,
    2420993, 2553663, 2693603, 2841212, 2996910, 3161140,
    3334370, 3517093, 3709829, 3913127, 4127566, 4353756,
    4592341, 4844001, 5109452, 5389449, 5684790, 11938059,
    25069923, 52646838, 110558359, 232172553, 487562361, 1023880958,
    2150150011, 4515315023, 9482161548,
]
MAX_LEVEL = len(EXP_TO_NEXT)  # 99: highest level with a known requirement


class ExpTable:
    """EXP needed to go from `level` to `level + 1`."""

    PCT_ROUND = 0.0105  # the on-screen percent is rounded to 2 decimals

    def total(self, level: int) -> Optional[float]:
        if 1 <= level <= MAX_LEVEL:
            return float(EXP_TO_NEXT[level - 1])
        return None

    def consistent(self, level: int, exp: int, pct: Optional[float]) -> bool:
        T = self.total(level)
        if T is None or exp < 0 or exp >= T:
            return False
        if pct is None:
            return True
        return abs(exp * 100.0 / T - pct) <= self.PCT_ROUND

    def candidates(self, exp: int, pct: float) -> List[int]:
        return [L for L in range(1, MAX_LEVEL + 1) if self.consistent(L, exp, pct)]


# --------------------------------------------------------------------------- #
# Rates
# --------------------------------------------------------------------------- #


def step_value(times: List[float], values: List[float], t: float) -> float:
    """Value of a step function that changes at `times` (sorted) and equals values[i] from times[i]."""
    if t <= 0:
        return 0.0  # cumulative gains are 0 at the start of the session by definition
    i = bisect.bisect_right(times, t) - 1
    return values[i] if i >= 0 else 0.0


def rolling_rate_series(times: List[float], gains: List[float], t_end: float, window: float = 300.0,
                        points: int = 90, min_span: float = 3.0) -> List[Tuple[float, float]]:
    """(t, gain per hour) for evenly spaced t in [0, t_end], each over the previous `window` seconds."""
    if t_end <= min_span or not times:
        return []
    out = []
    for i in range(points):
        t = t_end * (i + 1) / points
        t0 = max(0.0, t - window)
        span = t - t0
        if span < min_span:
            continue
        g = step_value(times, gains, t) - step_value(times, gains, t0)
        out.append((t, g / span * 3600.0))
    return out


# --------------------------------------------------------------------------- #
# Session tracker
# --------------------------------------------------------------------------- #

IDLE, RUNNING, PAUSED, TIMEOUT = "idle", "running", "paused", "timeout"


class SessionTracker:
    """
    Turns a stream of (exp, percent) readings into a tracked session.

    The level is worked out from the readings (EXP/percent only fit one level) or taken from
    `level_override`. After that the EXP table is used for level-ups, the percent gained and ETAs.
    A reading that doesn't fit the level is ignored (misread) until it repeats.
    """

    CONFIRM = 2          # consecutive readings to accept a level-up
    REBASE_CONFIRM = 3   # consecutive readings to accept "this is a different level/character now"
    BIG_DROP = 0.15      # an EXP drop above this share of the level can't be a death penalty
    LOST_AFTER = 8       # consecutive unusable readings before the level is re-detected

    def __init__(self, table: ExpTable, timeout: float = 60.0, auto_start: bool = True, level_override: int = 0):
        self.table = table
        self.timeout = float(timeout)
        self.auto_start = bool(auto_start)
        self.level_override = int(level_override or 0)
        self.level: Optional[int] = None
        self.last_exp: Optional[int] = None
        self.est_prev = None
        self.pending = None
        self.rejects = 0
        self.run_id = 0               # counts every start / resume of the clock
        self.session_id = 0           # counts the sessions begun (for things that keep their own baselines)
        self._reset_session()

    # -- session bookkeeping ---------------------------------------------------
    def _reset_session(self) -> None:
        self.state = IDLE
        self.want_start = False
        self.accum = 0.0
        self.run_start: Optional[float] = None
        self.last_gain_t: Optional[float] = None
        self.gained_exp = 0
        self.gained_pct = 0.0
        self.level_ups = 0
        self.start_info: Optional[dict] = None
        self.times: List[float] = []
        self.gains: List[float] = []
        self.exp_samples: List[list] = []   # [active_seconds, gained_exp, gained_pct]
        self.meso_samples: List[list] = []  # [active_seconds, mesos]
        self.pending_meso: Optional[int] = None
        self.meso_offset = 0                # mesos gained while the clock was stopped (not counted)
        self.meso_raw: Optional[int] = None
        self.meso_run: Optional[int] = None

    def has_session(self) -> bool:
        return self.start_info is not None

    def configure(self, timeout: float, auto_start: bool, level_override: int) -> None:
        self.timeout = float(timeout)
        self.auto_start = bool(auto_start)
        new_override = int(level_override or 0)
        if new_override != self.level_override:
            self.level_override = new_override
            self.level = None          # re-establish with the new setting
            self.est_prev = None
            self.pending = None

    def active(self, now: float) -> float:
        if self.state == RUNNING:
            return self.accum + (now - self.run_start)
        return self.accum

    elapsed = active

    def cur_pct(self) -> Optional[float]:
        if self.level is None or self.last_exp is None:
            return None
        T = self.table.total(self.level)
        return self.last_exp * 100.0 / T if T else None

    def level_total(self) -> Optional[float]:
        return self.table.total(self.level) if self.level is not None else None

    def _add_sample(self, t: float) -> None:
        self.times.append(t)
        self.gains.append(float(self.gained_exp))
        self.exp_samples.append([round(t, 2), self.gained_exp, round(self.gained_pct, 4)])

    def _begin_session(self, now: float) -> None:
        self.run_id += 1
        self.session_id += 1
        self.state = RUNNING
        self.accum = 0.0
        self.run_start = now
        self.last_gain_t = now
        self.gained_exp = 0
        self.gained_pct = 0.0
        self.level_ups = 0
        self.times, self.gains, self.exp_samples = [], [], []
        self.meso_samples = []
        self.meso_offset, self.meso_raw, self.meso_run = 0, None, None
        self.start_info = {"wall": datetime.now().isoformat(timespec="seconds"), "level": self.level,
                           "exp": self.last_exp, "pct": round(self.cur_pct() or 0.0, 2)}
        self._add_sample(0.0)
        if self.pending_meso is not None:
            self.meso_samples.append([0.0, int(self.pending_meso)])
            self.meso_raw, self.meso_run = int(self.pending_meso), self.run_id

    def start(self, now: float) -> None:
        """Start (from idle) or resume (from paused / timed out)."""
        if self.state == RUNNING:
            return
        if self.state == IDLE:
            if self.level is None or self.last_exp is None:
                self.want_start = True
            else:
                self._begin_session(now)
        else:
            self.state = RUNNING
            self.run_id += 1
            self.run_start = now
            self.last_gain_t = now

    def pause(self, now: float) -> None:
        if self.state == RUNNING:
            self.accum = self.active(now)
            self.state = PAUSED
            self.run_start = None
        self.want_start = False

    def toggle(self, now: float) -> None:
        if self.state == RUNNING:
            self.pause(now)
        else:
            self.start(now)

    def tick(self, now: float) -> Optional[str]:
        """Call regularly. Applies the idle time-out (AUTO mode only: in MANUAL the clock runs until you pause it)."""
        if self.state == RUNNING and self.auto_start and self.timeout > 0 and now - self.last_gain_t >= self.timeout:
            # The clock stops where it is when the time-out hits (it does not jump back); the EXP that follows
            # resumes the same session from there.
            self.accum += max(0.0, self.last_gain_t + self.timeout - self.run_start)
            self.state = TIMEOUT
            self.run_start = None
            return "timeout"
        return None

    def reset(self) -> None:
        """Throw the current session away (the level / EXP baseline is kept)."""
        self._reset_session()

    def set_meso(self, now: float, value: int) -> bool:
        """Record the mesos seen in the inventory. Ignored (False) while the clock is stopped: whatever happens
        then doesn't count, and the first reading after a resume re-baselines so it doesn't show up as a jump."""
        value = int(value)
        if not self.has_session():
            self.pending_meso = value          # becomes the start value when the session begins
            return True
        if self.state != RUNNING:
            return False
        if self.meso_run != self.run_id:
            if self.meso_samples and self.meso_raw is not None:
                self.meso_offset += value - self.meso_raw
            self.meso_run = self.run_id
        self.meso_raw = value
        t = self.active(now)
        adj = value - self.meso_offset
        if not (self.meso_samples and abs(self.meso_samples[-1][0] - t) < 0.5 and self.meso_samples[-1][1] == adj):
            self.meso_samples.append([round(t, 2), adj])
        return True

    # -- readings --------------------------------------------------------------
    def feed(self, now: float, exp: int, pct: Optional[float]) -> str:
        """Process one reading. Returns an event name: 'baseline', 'ok', 'levelup', 'pending',
        'rebased', 'rejected', 'lost', 'waiting', 'ambiguous', 'mismatch', 'need_pct'."""
        if exp < 0:
            return "rejected"
        if self.level is None:
            return self._establish(now, exp, pct)
        L, last = self.level, self.last_exp
        T = self.table.total(L)
        big_drop = T is not None and (last - exp) > self.BIG_DROP * T
        same_ok = self.table.consistent(L, exp, pct)
        next_ok = self._next_ok(exp, pct, big_drop)

        if next_ok and (big_drop or not same_ok):
            return self._confirm(now, "levelup", L + 1, exp)
        if same_ok:
            self.pending = None
            self.rejects = 0
            self._on_gain(now, exp - last, (exp - last) / T * 100.0, False)
            self.last_exp = exp
            return "ok"
        cands = [c for c in self.table.candidates(exp, pct) if c != L] if pct is not None else []
        if len(cands) == 1:
            return self._confirm(now, "rebase", cands[0], exp)
        self.rejects += 1
        if self.rejects >= self.LOST_AFTER:
            self.level = None
            self.est_prev = None
            self.pending = None
            self.rejects = 0
            return "lost"
        return "rejected"

    def _next_ok(self, exp: int, pct: Optional[float], big_drop: bool) -> bool:
        nxt = self.level + 1
        T2 = self.table.total(nxt)
        if T2 is None:
            return False
        if pct is None:
            return big_drop and exp < T2
        return self.table.consistent(nxt, exp, pct)

    def _confirm(self, now: float, kind: str, level: int, exp: int) -> str:
        p = self.pending
        if p and p["kind"] == kind and p["level"] == level:
            p["n"] += 1
        else:
            self.pending = p = {"kind": kind, "level": level, "n": 1}
        need = self.CONFIRM if kind == "levelup" else self.REBASE_CONFIRM
        if p["n"] < need:
            return "pending"
        self.pending = None
        self.rejects = 0
        if kind == "levelup":
            L, last = self.level, self.last_exp
            T, T2 = self.table.total(L), self.table.total(L + 1)
            to_top = max(0.0, T - last)
            d_exp = int(round(to_top + exp))
            d_pct = to_top / T * 100.0 + exp * 100.0 / T2
            self._on_gain(now, d_exp, d_pct, True)
            self.level = L + 1
            self.last_exp = exp
            return "levelup"
        self.level = level
        self.last_exp = exp
        return "rebased"

    def _on_gain(self, now: float, d_exp: int, d_pct: float, levelup: bool) -> None:
        if d_exp > 0:
            if self.state == IDLE and self.auto_start:
                self._begin_session(now)
            elif self.state in (TIMEOUT, PAUSED) and self.auto_start:     # AUTO follows the EXP, even after a manual pause
                self.state = RUNNING
                self.run_id += 1
                self.run_start = now
                self.last_gain_t = now
        if self.state != RUNNING:
            return
        self.gained_exp += d_exp
        self.gained_pct += d_pct
        if levelup:
            self.level_ups += 1
        if d_exp != 0 or levelup:
            self._add_sample(self.active(now))
        if d_exp > 0:
            self.last_gain_t = now

    def _establish(self, now: float, exp: int, pct: Optional[float]) -> str:
        ov = self.level_override
        if ov:
            if ov < 1 or ov > MAX_LEVEL:
                return "mismatch"
            if not self.table.consistent(ov, exp, pct):
                return "mismatch"
            cands = {ov}
        else:
            if pct is None:
                return "need_pct"
            cands = set(self.table.candidates(exp, pct))
            if not cands:
                self.est_prev = None
                return "rejected"
        prev = self.est_prev
        inter = (prev & cands) if prev else set()
        if not inter:
            self.est_prev = cands
            return "waiting"
        if len(inter) > 1:
            self.est_prev = inter
            return "ambiguous"
        self.level = next(iter(inter))
        self.last_exp = exp
        self.est_prev = None
        self.rejects = 0
        if self.want_start and self.state == IDLE:
            self.want_start = False
            self._begin_session(now)
        return "baseline"

    # -- statistics ------------------------------------------------------------
    def rate(self, now: float, window: Optional[float] = None) -> Optional[Tuple[float, float]]:
        """(exp per second, percent per second) over the last `window` active seconds
        (None = whole session). Available from the first second, so early numbers are rough."""
        if not self.has_session():
            return None
        a = self.active(now)
        if a <= 0:
            return None
        t0 = 0.0 if (window is None or a <= window) else a - window
        span = max(a - t0, 1.0)             # raw rate from the first second; it settles as the session grows
        g0 = step_value(self.times, self.gains, t0)
        d_exp = self.gained_exp - g0
        # percent rate: scale by the share of EXP (accurate within a level, close across level-ups)
        pct_samples = [s[2] for s in self.exp_samples]
        p0 = step_value(self.times, pct_samples, t0)
        return d_exp / span, (self.gained_pct - p0) / span

    def eta_seconds(self, now: float) -> Optional[float]:
        T = self.level_total()
        if T is None or self.last_exp is None:
            return None
        r = self.rate(now, 300) or self.rate(now)
        if not r or r[0] <= 0:
            return None
        return max(0.0, T - self.last_exp) / r[0]

    def rate_series(self, now: float, window: float = 300.0, points: int = 90) -> List[Tuple[float, float]]:
        if not self.has_session():
            return []
        return rolling_rate_series(self.times, self.gains, self.active(now), window, points)

    # mesos (read from the inventory window whenever it is open)
    def meso_gain(self) -> Optional[int]:
        if len(self.meso_samples) < 2:
            return None
        return self.meso_samples[-1][1] - self.meso_samples[0][1]

    def _meso_at(self, t: float) -> float:
        """Mesos at active-time t, interpolated between inventory readings."""
        ts = [m[0] for m in self.meso_samples]
        i = bisect.bisect_right(ts, t)
        if i == 0:
            return self.meso_samples[0][1]
        if i >= len(ts):
            return self.meso_samples[-1][1]
        (ta, va), (tb, vb) = self.meso_samples[i - 1], self.meso_samples[i]
        return va + (vb - va) * (t - ta) / (tb - ta) if tb > ta else vb

    def meso_rate(self, window: Optional[float] = None) -> Optional[float]:
        """Mesos per hour up to the latest inventory reading, over the last `window` active seconds
        (None = whole session). The readings are sparse, so this is only as fresh as the last sync."""
        if len(self.meso_samples) < 2:
            return None
        t1, v1 = self.meso_samples[-1]
        t0 = self.meso_samples[0][0] if window is None else max(self.meso_samples[0][0], t1 - window)
        span = max(t1 - t0, 1.0)
        return (v1 - self._meso_at(t0)) / span * 3600.0

    def meso_series(self) -> List[Tuple[float, float]]:
        """(t, running average mesos per hour since the first reading) for each later reading."""
        if len(self.meso_samples) < 2:
            return []
        t0, v0 = self.meso_samples[0]
        return [(t, (v - v0) / (t - t0) * 3600.0) for t, v in self.meso_samples[1:] if t - t0 >= 3]


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #


def fmt_int(n: float) -> str:
    return f"{int(round(n)):,}"


def fmt_clock(sec: float) -> str:
    sec = int(max(0, sec))
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def fmt_short(v: float) -> str:
    a = abs(v)
    if a >= 1e9:
        return f"{v / 1e9:.1f}B"
    if a >= 1e6:
        return f"{v / 1e6:.1f}M"
    if a >= 1e3:
        return f"{v / 1e3:.0f}k" if a >= 1e5 else f"{v / 1e3:.1f}k"
    return f"{v:.0f}"


def fmt_eta(sec: Optional[float]) -> str:
    if sec is None or sec != sec or sec == float("inf"):
        return "--"
    if sec < 60:
        return "<1m"
    m = int(sec // 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m"
