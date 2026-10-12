"""
Quick-slot consumables for the EXP tracker. Nothing in this file needs a GUI.

* Finds the quick-slot panel (it sits at a fixed offset from the bottom-centre of the game window),
  recognises the item in each slot from its colours, and reads the stack count beside it.
* Tracks the value of the stacks you hold: price x (count at the start of the session - count now). Buying or
  looting a stack therefore nets out against the mesos you gained, and using one costs its price.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

import exp_core as ec
from exp_items_seeds import DIGIT_SEEDS, ICON_SEEDS

# NPC buy prices (mesos).
PRICES: Dict[str, int] = {
    "Red Potion": 50, "Orange Potion": 150, "White Potion": 350, "Blue Potion": 220,
    "Warrior Potion": 500, "Sniper Potion": 500, "Magic Potion": 500, "Speed Potion": 500,
    "Apple": 20, "Egg": 30, "Meat": 80, "Orange": 50, "Lemon": 150, "Pet Food": 35,
}

# --------------------------------------------------------------------------- #
# Where the slots are
# --------------------------------------------------------------------------- #
# Measured on a 1366x768 window. The panel is attached to the right end of the status bar, so offsets are
# taken from the window's bottom-centre like the EXP box. The panel has up to three rows (the top one, hotkeys 1-4,
# only when it is expanded); the two bottom rows are always there.
SLOT = 28                                  # slot width in pixels (the height incl. its shading is 29)
SLOT_PITCH = 35
COL_DX = (259, 294, 329, 364)              # slot left edges, right of the window centre
ROW_DY = (171, 137, 103)                   # slot top edges (top row, middle row, bottom row), above the window bottom
MARGIN_X, MARGIN_Y = 7, 2                  # extra pixels grabbed around the panel, so its exact position can be found
STRIP_DX, STRIP_W, STRIP_H = COL_DX[0] - MARGIN_X, 148, 104
N_SLOTS = 12
SLOT_KEYS = ("1", "2", "3", "4", "Shift", "Ins", "Hm", "PgUp", "Ctrl", "Del", "End", "PgDn")
DIGIT_PITCH, DIGIT_CELL_W, DIGIT_ROWS, MAX_DIGITS = 8, 8, (17, 29), 4
DIGIT_ADVANCE = {"1": 5}   # the font is proportional: a 1 is 5 px wide, every other digit 8
DIGIT_X0 = -2          # a digit cell starts at the slot's left edge minus 2 (its black outline)
DIGITS_VERSION = 3      # bumped when the way digits are stored changed (older taught shapes are ignored)
MIN_ART, MAX_ART = 25, 360                 # saturated pixels for "has an icon" (a plain pink slot has far more)


def strip_region(win: dict) -> Optional[dict]:
    """Screen rectangle of the quick-slot strip, or None if it falls outside the window."""
    W, H = int(win["width"]), int(win["height"])
    left = int(win["left"]) + W // 2 + STRIP_DX
    top = int(win["top"]) + H - ROW_DY[0] - MARGIN_Y
    if left < win["left"] or top < win["top"] or left + STRIP_W > win["left"] + W or top + STRIP_H > win["top"] + H:
        return None
    return {"left": left, "top": top, "width": STRIP_W, "height": STRIP_H}


def slot_origin(i: int, dx: int = 0, dy: int = 0) -> Tuple[int, int]:
    """(x, y) of slot i's top-left corner inside the strip (dx, dy: the panel's measured offset)."""
    r, c = divmod(i, 4)
    return COL_DX[c] - STRIP_DX + dx, MARGIN_Y + ROW_DY[0] - ROW_DY[r] + dy


def slot_picture(strip: np.ndarray, i: int, dx: int = 0, dy: int = 0, left: int = 6) -> np.ndarray:
    """The slot with `left` extra pixels on its left, so the start of its number is not cut off."""
    x, y = slot_origin(i, dx, dy)
    x0 = max(0, x - left)
    return strip[y:y + SLOT + 2, x0:x + SLOT]


def slot_crop(strip: np.ndarray, i: int, dx: int = 0, dy: int = 0) -> np.ndarray:
    x, y = slot_origin(i, dx, dy)
    return strip[y:y + SLOT, x:x + SLOT]


def _dark(rgb: np.ndarray) -> np.ndarray:
    return rgb.max(axis=-1) < 90


def _alignment_score(strip: np.ndarray, dx: int, dy: int) -> Tuple[float, float]:
    """(horizontal, vertical) evidence that the panel sits at this offset: the dark gaps between the slots, and
    the dark bottom border under the lowest row of slots (those two rows are always on screen)."""
    gaps, borders = [], []
    for i in range(4, 12):
        x, y = slot_origin(i, dx, dy)
        if i % 4 < 3:
            gaps.append(_dark(strip[y + 3:y + 21, x + 30:x + 33]).mean())
        if i >= 8:
            borders.append(_dark(strip[y + 29, x + 2:x + 26]).mean())
    return float(np.mean(gaps)), float(np.mean(borders))


def calibrate(strip: np.ndarray) -> Tuple[int, int, float]:
    """(dx, dy, quality): where the panel really is, relative to where it should be, from its frame. The window
    can sit a pixel or two differently from the one this was measured on."""
    best_h, best_v = (-1.0, 0), (-1.0, 0)
    for d in sorted(range(-(MARGIN_X - 2), MARGIN_X - 1), key=abs):      # (a digit cell reaches 2 px left of a slot)
        h = _alignment_score(strip, d, 0)[0]
        if h > best_h[0] + 1e-9:
            best_h = (h, d)
    for d in sorted(range(-MARGIN_Y, MARGIN_Y + 1), key=abs):
        v = _alignment_score(strip, best_h[1], d)[1]
        if v > best_v[0] + 1e-9:
            best_v = (v, d)
    return best_h[1], best_v[1], min(best_h[0], best_v[0])


def _row_slots_seen(strip: np.ndarray, row: int, dx: int, dy: int) -> int:
    seen = 0
    for c in range(4):
        x, y = slot_origin(row * 4 + c, dx, dy)
        line = strip[y + 29, x + 2:x + 26]
        if line.size and (line.max(axis=1) < 110).mean() >= 0.8:
            seen += 1
    return seen


def panel_visible(strip: np.ndarray, dx: int = 0, dy: int = 0) -> bool:
    """The slots' dark bottom borders are a fixed pattern; most of those in the two bottom rows must be there."""
    return _row_slots_seen(strip, 1, dx, dy) + _row_slots_seen(strip, 2, dx, dy) >= 5


def top_row_present(strip: np.ndarray, dx: int = 0, dy: int = 0) -> bool:
    """The expanded panel has a third row on top. When it is collapsed that spot shows the game scene, so the row
    needs both its slot borders and the dark gaps between its slots."""
    if _row_slots_seen(strip, 0, dx, dy) < 3:
        return False
    gaps = [_dark(strip[slot_origin(c, dx, dy)[1] + 3:slot_origin(c, dx, dy)[1] + 21,
                        slot_origin(c, dx, dy)[0] + 30:slot_origin(c, dx, dy)[0] + 33]).mean() for c in range(3)]
    return float(np.mean(gaps)) >= 0.8


# --------------------------------------------------------------------------- #
# Recognising the item: a map of which (saturated) hue each pixel has
# --------------------------------------------------------------------------- #

def icon_signature(rgb: np.ndarray, chroma: int = 55, bins: int = 12) -> np.ndarray:
    """0 where a pixel is grey / white / black (slot background, hotkey label, count digits), else 1..bins by hue.
    The overlays on top of an icon are all unsaturated, so the same item gives the same map in any slot."""
    c = rgb.astype(int)
    mx, mn = c.max(axis=2), c.min(axis=2)
    ch = mx - mn
    r, g, b = c[:, :, 0].astype(float), c[:, :, 1].astype(float), c[:, :, 2].astype(float)
    safe = np.maximum(ch, 1)
    rc, gc, bc = (mx - r) / safe, (mx - g) / safe, (mx - b) / safe
    h = np.where(mx == r, bc - gc, np.where(mx == g, 2 + rc - bc, 4 + gc - rc))
    out = np.floor(((h / 6.0) % 1.0) * bins).astype(np.int8) + 1
    out[ch < chroma] = 0
    return out


def signature_score(a: np.ndarray, b: np.ndarray, bins: int = 12) -> float:
    """How alike two signatures are (1 = same pixels, same hues). A hue one bin off counts for 60%."""
    union = (a > 0) | (b > 0)
    if not union.any():
        return 0.0
    diff = np.abs(a.astype(int) - b.astype(int))
    diff = np.minimum(diff, bins - diff)
    both = (a > 0) & (b > 0)
    return float(((both & (diff == 0)).sum() + 0.6 * (both & (diff == 1)).sum()) / union.sum())


def _sig_to_rows(sig: np.ndarray) -> List[str]:
    return ["".join("0123456789abc"[v] for v in row) for row in sig]


def _sig_from_rows(rows: List[str]) -> np.ndarray:
    return np.array([["0123456789abc".index(ch) for ch in r] for r in rows], dtype=np.int8)


# --------------------------------------------------------------------------- #
# Reading the count: the digits are white with a black outline, so the outline is what is compared
# --------------------------------------------------------------------------- #
# The number sits at the slot's bottom-left. The font is proportional (a 1 is narrower), so digits are read one after
# another: classify the cell at the current position, then step on by that digit's width.

def advance(ch: str) -> int:
    return DIGIT_ADVANCE.get(ch, DIGIT_PITCH)


def ink_pixels(rgb: np.ndarray) -> int:
    """White pixels with a black neighbour: the digits are white with a black outline."""
    white = rgb.min(axis=2) >= 185
    dark = rgb.max(axis=2) < 95
    d = np.pad(dark, 1)
    near = np.zeros_like(dark)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                near |= d[1 + dy:1 + dy + dark.shape[0], 1 + dx:1 + dx + dark.shape[1]]
    return int((white & near).sum())


def digit_like(rgb: np.ndarray, first: bool = False) -> bool:
    """Does this cell look like it holds a digit at all? Icon art has plenty of white and black too, but not as
    much of both. (Used to tell 'a digit I can't read' from 'icon art' or 'the end of the number'.)"""
    dark = int((rgb.max(axis=2) < 95).sum())
    ink = ink_pixels(rgb)
    if first:
        return dark >= 32 and ink >= 18
    return (dark >= 45 and ink >= 8) or (dark >= 30 and ink >= 20)


def outline(rgb: np.ndarray) -> np.ndarray:
    """1 where a pixel is black: the digit's outline, whatever icon sits behind it."""
    return (rgb.max(axis=2) < 95).astype(float)


def _ncc(a: np.ndarray, b: np.ndarray) -> float:
    a = a.ravel() - a.mean()
    b = b.ravel() - b.mean()
    d = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float(a @ b) / d if d > 1e-6 else 0.0


def base_name(stack: str) -> str:
    """"Red Potion #2" -> "Red Potion"."""
    return stack.split(" #")[0]


def digit_slip(old: int, new: int) -> bool:
    """A change that looks like a digit was lost or gained in reading (37 -> 3 or 7, 15 -> 150): one number's digits
    are the start or the end of the other's."""
    a, b = str(old), str(new)
    if a == b:
        return False
    short, long_ = sorted((a, b), key=len)
    return len(short) < len(long_) and (long_.startswith(short) or long_.endswith(short))


def _map_to_rows(m: np.ndarray) -> List[str]:
    return ["".join("1" if v > 0.5 else "0" for v in row) for row in m]


def _map_from_rows(rows: List[str]) -> np.ndarray:
    return np.array([[float(c) for c in row] for row in rows])


def _digit_cell(strip: np.ndarray, i: int, pos: int, dx: int, dy: int) -> Optional[np.ndarray]:
    x, y = slot_origin(i, dx, dy)
    x0 = x + DIGIT_X0 + pos
    cell = strip[y + DIGIT_ROWS[0]:y + DIGIT_ROWS[1], x0:x0 + DIGIT_CELL_W]
    return cell if x0 >= 0 and cell.shape[:2] == (DIGIT_ROWS[1] - DIGIT_ROWS[0], DIGIT_CELL_W) else None


class DigitLibrary:
    """Digit outlines (8 x 12): the built-in ones, plus any you taught it."""
    MIN_SCORE, MIN_MARGIN = 0.65, 0.12
    NUDGES = (0, -1, 1)          # a digit may sit a pixel off the position the previous one implies
    FIRST_EXTRA = (-2, -3)       # the first digit may also sit this far left (the slot's frame is right there);
    FIRST_EXTRA_SCORE = 0.85     # ...but only a very clear match is believed that far out
    ART_SCORE = 0.5              # after a digit, a cell scoring below this is icon art, not another digit

    def __init__(self):
        self.cells: List[Tuple[str, np.ndarray]] = []          # taught by you (saved)
        self.seeds: List[Tuple[str, np.ndarray]] = [(ch, _map_from_rows(rows))
                                                    for ch, instances in DIGIT_SEEDS.items() for rows in instances]

    def known(self) -> str:
        return "".join(sorted({ch for ch, _ in self.seeds + self.cells}))

    def add(self, ch: str, rgb_cell: np.ndarray) -> bool:
        """Remember this cell as `ch` unless a stored one already matches it. True if it was new."""
        m, w = outline(rgb_cell), advance(ch)
        if any(c == ch and _ncc(m[:, :w], t[:, :w]) > 0.97 for c, t in self.seeds + self.cells):
            return False
        self.cells.append((ch, m))
        return True

    def scores(self, rgb_cell: np.ndarray) -> List[Tuple[str, float]]:
        """Every digit with its best similarity to this cell, best first (a digit is compared over its own width)."""
        m = outline(rgb_cell)
        best: Dict[str, float] = {}
        for ch, t in self.seeds + self.cells:
            w = advance(ch)
            best[ch] = max(best.get(ch, -1.0), _ncc(m[:, :w], t[:, :w]))
        return sorted(best.items(), key=lambda kv: -kv[1])

    def confident(self, order: List[Tuple[str, float]]) -> Optional[str]:
        if not order or order[0][1] < self.MIN_SCORE:
            return None
        if len(order) > 1 and order[0][1] - order[1][1] < self.MIN_MARGIN:
            return None
        return order[0][0]

    def read_slot(self, strip: np.ndarray, i: int, dx: int = 0, dy: int = 0) -> Tuple[str, Optional[int]]:
        """(status, count): 'none' (no number there), 'ok', or 'unreadable' (a digit it can't tell)."""
        pos, digits = 0, ""
        for k in range(MAX_DIGITS):
            best = None
            for nudge in self.NUDGES:
                cell = _digit_cell(strip, i, pos + nudge, dx, dy)
                if cell is None:
                    continue
                order = self.scores(cell)
                if best is None or (order and (not best[0] or order[0][1] > best[0][0][1])):
                    best = (order, nudge)
            if k == 0:                                         # a digit pushed against the slot's left edge
                for nudge in self.FIRST_EXTRA:
                    cell = _digit_cell(strip, i, pos + nudge, dx, dy)
                    order = self.scores(cell) if cell is not None else []
                    if order and order[0][1] >= self.FIRST_EXTRA_SCORE and (
                            best is None or not best[0] or order[0][1] > best[0][0][1] + 0.05):
                        best = (order, nudge)
            if best is None:
                break
            order, nudge = best
            ch = self.confident(order)
            if ch is None:
                here = _digit_cell(strip, i, pos, dx, dy)
                like = here is not None and digit_like(here, first=(k == 0))
                if k == 0:
                    return ("unreadable" if like else "none"), None
                if like and order and order[0][1] >= self.ART_SCORE:
                    return "unreadable", None                  # it resembles a digit but can't be told apart
                break                                          # art (a bone, a bottle's edge) or empty space: it ended
            digits += ch
            pos += nudge + advance(ch)
        return ("ok", int(digits)) if digits else ("none", None)

    def teach_slot(self, strip: np.ndarray, i: int, typed: str, dx: int = 0, dy: int = 0) -> int:
        """Learn from the number you typed (spacing follows the digits you typed). Returns how many new digit
        shapes were stored; raises ValueError if the picture doesn't show that many digits."""
        typed = typed.replace(",", "").strip()
        if not typed.isdigit() or len(typed) > MAX_DIGITS:
            raise ValueError("Type the number shown on the icon (digits only).")
        cells, pos = [], 0
        for k, ch in enumerate(typed):
            options = [c for c in (_digit_cell(strip, i, pos + n, dx, dy) for n in self.NUDGES) if c is not None]
            if not options or not digit_like(options[0], first=(k == 0)):
                raise ValueError(f"I only see {k} digit(s) there but you typed {len(typed)}.")
            # prefer the nudge that agrees with what is already known about this digit
            same = [(t, advance(ch)) for c, t in self.seeds + self.cells if c == ch]
            if same:
                options.sort(key=lambda c: -max(_ncc(outline(c)[:, :w], t[:, :w]) for t, w in same))
            cells.append(options[0])
            pos += advance(ch)
        last = _digit_cell(strip, i, pos, dx, dy)
        if len(typed) < MAX_DIGITS and last is not None and digit_like(last):
            raise ValueError(f"I see more than the {len(typed)} digit(s) you typed.")
        return sum(1 for ch, cell in zip(typed, cells) if self.add(ch, cell))


# --------------------------------------------------------------------------- #
# Library: known items and taught digits
# --------------------------------------------------------------------------- #

class ItemLibrary:
    """Known consumables. Seeds come with the program; items you add (and their prices) are saved."""
    MIN_SCORE, MIN_MARGIN = 0.62, 0.12

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else ec.data_dir() / "consumables.json"
        self.sigs: List[Tuple[str, np.ndarray]] = [(n, _sig_from_rows(rows))
                                                   for n, instances in ICON_SEEDS.items() for rows in instances]
        self.user_sigs: List[Tuple[str, np.ndarray]] = []
        self.prices: Dict[str, int] = dict(PRICES)
        self.digits = DigitLibrary()

    # persistence
    def load(self) -> "ItemLibrary":
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for it in data.get("items", []):
                self.prices[it["name"]] = int(it["price"])
                if it.get("rows"):
                    self.user_sigs.append((it["name"], _sig_from_rows(it["rows"])))
            if data.get("digits_version") == DIGITS_VERSION:     # older shapes were stored differently: re-teach
                for d in data.get("digits", []):
                    self.digits.cells.append((d["ch"], _map_from_rows(d["rows"])))
        except FileNotFoundError:
            pass
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, OSError) as e:
            print(f"Warning: could not read {self.path} ({e}); ignoring saved consumables.")
        return self

    def save(self) -> None:
        names = {n for n, _ in self.user_sigs} | {n for n, p in self.prices.items() if PRICES.get(n) != p}
        items = []
        for n in sorted(names):
            rows = [_sig_to_rows(s) for m, s in self.user_sigs if m == n]
            for r in rows or [None]:
                items.append({"name": n, "price": self.prices.get(n, 0), "rows": r})
        digits = [{"ch": ch, "rows": _map_to_rows(m)} for ch, m in self.digits.cells]
        ec._atomic_write_json(self.path, {"version": 1, "digits_version": DIGITS_VERSION, "items": items,
                                          "digits": digits})

    # items
    def names(self) -> List[str]:
        return sorted(self.prices)

    def price(self, name: str) -> int:
        return int(self.prices.get(name, 0))

    def add_item(self, name: str, price: int, sig: np.ndarray) -> None:
        self.prices[name] = int(price)
        if not any(n == name and signature_score(sig, s) > 0.97 for n, s in self.sigs + self.user_sigs):
            self.user_sigs.append((name, sig.copy()))

    def forget_user(self) -> None:
        self.user_sigs = []
        self.digits.cells = []
        self.prices = dict(PRICES)

    def identify(self, sig: np.ndarray) -> Tuple[Optional[str], float]:
        """(name, score) of the best match, or (None, score) if nothing is close enough or it's ambiguous."""
        best: Dict[str, float] = {}
        for n, s in self.sigs + self.user_sigs:
            best[n] = max(best.get(n, 0.0), signature_score(sig, s))
        if not best:
            return None, 0.0
        order = sorted(best.items(), key=lambda kv: -kv[1])
        name, score = order[0]
        if score < self.MIN_SCORE or (len(order) > 1 and score - order[1][1] < self.MIN_MARGIN):
            return None, score
        return name, score


# --------------------------------------------------------------------------- #
# Scanning the panel
# --------------------------------------------------------------------------- #

@dataclass
class SlotInfo:
    index: int
    key: str
    has_art: bool = False
    name: Optional[str] = None
    has_count: bool = False
    status: str = "none"             # count status: none / ok / unreadable
    count: Optional[int] = None


@dataclass
class Scan:
    visible: bool = False
    slots: List[SlotInfo] = field(default_factory=list)
    dx: int = 0                      # where the panel really sits (found from its frame)
    dy: int = 0

    @property
    def known(self) -> List[SlotInfo]:
        return [s for s in self.slots if s.name]

    @property
    def unknown(self) -> List[SlotInfo]:
        """Icons it doesn't know that show a quantity (candidates for 'Add custom')."""
        return [s for s in self.slots if s.has_art and not s.name and s.has_count]

    @property
    def unreadable(self) -> List[SlotInfo]:
        return [s for s in self.known if s.status != "ok"]

    def counts(self) -> Dict[str, int]:
        """stack -> count for every readable known slot. An item in two slots with different counts is two stacks
        (say, a tradeable one and a quest one): "Red Potion" and "Red Potion #2". The same count twice is taken to
        be one stack shown in two slots."""
        out: Dict[str, int] = {}
        seen: Dict[str, List[int]] = {}
        for s in self.known:
            if s.status != "ok" or s.count in seen.setdefault(s.name, []):
                continue
            seen[s.name].append(s.count)
            n = len(seen[s.name])
            out[s.name if n == 1 else f"{s.name} #{n}"] = s.count
        return out


def scan_strip(strip: np.ndarray, lib: ItemLibrary) -> Scan:
    dx, dy, _ = calibrate(strip)
    scan = Scan(visible=panel_visible(strip, dx, dy), dx=dx, dy=dy)
    top = scan.visible and top_row_present(strip, dx, dy)
    for i in range(N_SLOTS):
        info = SlotInfo(i, SLOT_KEYS[i])
        if i >= 4 or top:
            sig = icon_signature(slot_crop(strip, i, dx, dy))
            info.has_art = MIN_ART <= int((sig > 0).sum()) <= MAX_ART
            if info.has_art:
                info.name, _ = lib.identify(sig)
                info.status, info.count = lib.digits.read_slot(strip, i, dx, dy)
                info.has_count = info.status != "none"
        scan.slots.append(info)
    scan.visible = scan.visible or bool(scan.known)
    return scan


# --------------------------------------------------------------------------- #
# What the stacks you hold are worth
# --------------------------------------------------------------------------- #

class StockTracker:
    """Cost of the consumables used = sum of price x (count at the start - count now).

    The start counts are those seen when the session begins. An item first seen later starts from its first
    count. Changes while the clock is stopped are absorbed into the start, so only what happens while tracking
    counts. An item that disappears from the slots keeps its last count until it comes back."""

    def __init__(self):
        self.items: Dict[str, dict] = {}
        self.started = False

    def reset(self) -> None:
        self.started = False
        for it in self.items.values():
            it["start"] = None

    def begin(self) -> None:
        self.started = True
        for it in self.items.values():
            it["start"] = it["last"]

    def update(self, counts: Dict[str, int], prices: Dict[str, int], counting: bool) -> None:
        for name, c in counts.items():
            it = self.items.get(name)
            if it is None:
                self.items[name] = {"last": c, "start": c if self.started else None, "price": prices.get(name, 0)}
                continue
            it["price"] = prices.get(name, it["price"])
            if not counting and it["start"] is not None:
                it["start"] += c - it["last"]
            it["last"] = c

    def tracked(self) -> bool:
        return any(it["start"] is not None for it in self.items.values())

    def cost(self) -> int:
        """Net mesos worth of stock used (negative if you now hold more than you started with)."""
        return int(sum(it["price"] * (it["start"] - it["last"]) for it in self.items.values()
                       if it["start"] is not None))
