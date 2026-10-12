import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="exp_items_test_")
os.environ["EXP_TRACKER_DATA"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

import exp_items as ei  # noqa: E402
from exp_items_seeds import ICON_SEEDS  # noqa: E402

RED, YELLOW, BLUE, GREEN = (220, 40, 40), (240, 220, 30), (40, 70, 220), (40, 190, 60)
WIN = {"left": 0, "top": 0, "width": 1366, "height": 768}
# slot numbers: top row 0-3 (hotkeys 1-4), middle row 4-7 (Shift Ins Hm PgUp), bottom row 8-11 (Ctrl Del End PgDn)
SHIFT, INS, HM, PGUP, CTRL, DEL, END, PGDN = range(4, 12)


def digit_pattern(ch: str) -> np.ndarray:
    """A made-up but distinct 'glyph' per digit (the real font is built in). Like the real font a 1 is narrower."""
    width = 4 if ch == "1" else 6
    rng = np.random.RandomState(ord(ch))
    while True:
        bm = rng.rand(8, width) > 0.4
        if bm.sum() >= (20 if ch == "1" else 26):
            return bm


def render_quickslots(slots: dict, expanded: bool = False, digit_shift: int = 0) -> np.ndarray:
    """A quick-slot strip: white slots with dark bottom borders. slots = {index: (icon rgb or None, count or None)}.
    Icons are a coloured blob; the count is drawn as white digit shapes on black cells, 8 px apart (5 for a 1).
    The top row (0-3) is only drawn when `expanded` or when a slot in it is used (otherwise it shows game scene)."""
    img = np.full((ei.STRIP_H, ei.STRIP_W, 3), 30, dtype=np.uint8)
    top = expanded or any(k < 4 for k in slots)
    if not top:
        img[:ei.slot_origin(0)[1] + 34] = 140                      # game scene where the top row would be
    for i in range(ei.N_SLOTS):
        if i < 4 and not top:
            continue
        x, y = ei.slot_origin(i)
        img[y:y + 28, x:x + 28] = 250
        img[y + 28:y + 30, x:x + 28] = 20
        icon, count = slots.get(i, (None, None))
        if icon is not None:
            img[y + 4:y + 16, x + 6:x + 22] = icon
        pos = 0
        for ch in "" if count is None else str(count):
            cx = x + ei.DIGIT_X0 + digit_shift + pos
            cell = img[y + ei.DIGIT_ROWS[0]:y + ei.DIGIT_ROWS[1], cx:cx + ei.advance(ch)]
            cell[:] = 0
            pattern = digit_pattern(ch)
            cell[2:10, 1:1 + pattern.shape[1]][pattern] = 255
            pos += ei.advance(ch)
    return img


def fresh_lib() -> ei.ItemLibrary:
    return ei.ItemLibrary(path=Path(tempfile.mkdtemp(dir=_TMP)) / "consumables.json")


# Real, uncompressed crops of the quick-slot panel: where slot 8 (Ctrl) sits in each picture
TESTDATA = Path(__file__).resolve().parent / "testdata"
RAW = {1: (TESTDATA / "quickslots_raw.png", 18, 83),
       2: (TESTDATA / "quickslots_raw2.png", 23, 82)}


def live_strip() -> np.ndarray:
    """A strip captured live by the tracker itself (a different layout of the author's quick slots)."""
    from PIL import Image
    return np.asarray(Image.open(TESTDATA / "quickslots_live_strip.png").convert("RGB"))


def raw_strip(which: int = 1, ox: int = 0, oy: int = 0) -> np.ndarray:
    """The strip cut from a real screenshot, `ox`, `oy` pixels away from where it should be."""
    from PIL import Image
    path, cx, cy = RAW[which]
    a = np.asarray(Image.open(path).convert("RGB"))
    left, top = cx - ei.slot_origin(CTRL)[0] + ox, cy - ei.slot_origin(CTRL)[1] + oy
    return a[top:top + ei.STRIP_H, left:left + ei.STRIP_W]


def taught_lib(count_text="0123456789") -> ei.ItemLibrary:
    """A library that knows the colours RED and YELLOW (as 'Red Potion' / 'Lemon') and every digit of its own
    synthetic font (so no built-in seed is used: the synthetic digits differ from the real ones)."""
    lib = fresh_lib()
    lib.digits.seeds = []
    strip = render_quickslots({INS: (RED, count_text), DEL: (YELLOW, None)})
    lib.add_item("Red Potion", 50, ei.icon_signature(ei.slot_crop(strip, INS)))
    lib.add_item("Lemon", 150, ei.icon_signature(ei.slot_crop(strip, DEL)))
    for chunk in (count_text[:4], count_text[4:8], count_text[8:]):
        if chunk:
            lib.digits.teach_slot(render_quickslots({INS: (RED, chunk)}), INS, chunk)
    return lib


class GeometryTests(unittest.TestCase):
    def test_strip_and_slot_positions(self):
        self.assertEqual(ei.strip_region(WIN), {"left": 935, "top": 595, "width": 148, "height": 104})
        self.assertEqual([ei.slot_origin(i) for i in (0, 3, 4, 8, 11)],
                         [(7, 2), (112, 2), (7, 36), (7, 70), (112, 70)])
        self.assertIsNone(ei.strip_region({"left": 0, "top": 0, "width": 200, "height": 100}))

    def test_panel_visibility(self):
        self.assertTrue(ei.panel_visible(render_quickslots({})))
        self.assertFalse(ei.panel_visible(np.full((ei.STRIP_H, ei.STRIP_W, 3), 120, dtype=np.uint8)))
        noise = np.random.RandomState(1).randint(0, 255, (ei.STRIP_H, ei.STRIP_W, 3)).astype(np.uint8)
        self.assertFalse(ei.panel_visible(noise))

    def test_top_row_only_when_the_panel_is_expanded(self):
        self.assertTrue(ei.top_row_present(render_quickslots({}, expanded=True)))
        self.assertFalse(ei.top_row_present(render_quickslots({})))
        self.assertFalse(ei.top_row_present(np.full((ei.STRIP_H, ei.STRIP_W, 3), 140, dtype=np.uint8)))


class RecognitionTests(unittest.TestCase):
    def test_seed_icons_recognise_themselves_and_not_each_other(self):
        lib = fresh_lib()
        for name, instances in ICON_SEEDS.items():
            for rows in instances:
                self.assertEqual(lib.identify(ei._sig_from_rows(rows))[0], name)

    def test_unknown_and_ambiguous_icons_are_not_guessed(self):
        lib = taught_lib()
        green = ei.icon_signature(ei.slot_crop(render_quickslots({INS: (GREEN, None)}), INS))
        self.assertIsNone(lib.identify(green)[0])
        blank = ei.icon_signature(ei.slot_crop(render_quickslots({}), INS))
        self.assertIsNone(lib.identify(blank)[0])

    def test_digits_must_be_taught_then_read_anywhere(self):
        lib = fresh_lib()
        lib.digits.seeds = []
        strip = render_quickslots({INS: (RED, 281)})
        self.assertEqual(lib.digits.read_slot(strip, INS), ("unreadable", None))
        with self.assertRaises(ValueError):
            lib.digits.teach_slot(strip, INS, "28")                        # three digits shown, two typed
        with self.assertRaises(ValueError):
            lib.digits.teach_slot(strip, INS, "2815")                      # only three shown
        self.assertEqual(lib.digits.teach_slot(strip, INS, "281"), 3)
        for slot in range(4, 12):                                          # same shapes, any slot, any number of them
            for count in (281, 8, 128, 1, 182, 111, 2):
                s = render_quickslots({slot: (RED, count)})
                self.assertEqual(lib.digits.read_slot(s, slot), ("ok", count), (slot, count))
        s = render_quickslots({INS: (RED, 380)})                           # '3' and '0' were never taught
        self.assertEqual(lib.digits.read_slot(s, INS), ("unreadable", None))
        self.assertEqual(lib.digits.read_slot(render_quickslots({INS: (RED, None)}), INS), ("none", None))

    def test_a_number_pushed_against_the_left_edge_is_still_read(self):
        lib = taught_lib()
        for shift in (0, -1, -2, -3, 1):
            for slot in (SHIFT, INS, CTRL, END, PGDN):
                for count in (37, 15, 1, 607, 4):
                    strip = render_quickslots({slot: (RED, count)}, digit_shift=shift)
                    self.assertEqual(lib.digits.read_slot(strip, slot), ("ok", count), (shift, slot, count))
        # and a bare slot or a skill icon never turns into a number because of the wider look
        for slot in range(4, 12):
            strip = render_quickslots({slot: (BLUE, None)})
            self.assertEqual(lib.digits.read_slot(strip, slot), ("none", None))

    def test_icon_art_next_to_a_short_number_does_not_make_it_unreadable(self):
        # A single digit with the dark-outlined artwork (a bone, a bottle edge) in the next cell: the number is the digit
        lib = taught_lib()
        for count in (5, 4, 7, 15, 25):
            strip = render_quickslots({DEL: (RED, count)})
            x, y = ei.slot_origin(DEL)
            pos = sum(ei.advance(ch) for ch in str(count))
            art = np.random.RandomState(7).rand(12, 8) > 0.45            # black outline strokes with some light between
            cell = strip[y + ei.DIGIT_ROWS[0]:y + ei.DIGIT_ROWS[1], x + ei.DIGIT_X0 + pos:x + ei.DIGIT_X0 + pos + 8]
            cell[:] = np.where(art[:, :, None], 0, 235)
            self.assertEqual(lib.digits.read_slot(strip, DEL), ("ok", count), count)

    def test_a_one_is_narrower_so_the_next_digit_comes_sooner(self):
        self.assertEqual((ei.advance("1"), ei.advance("0"), ei.advance("7")), (5, 8, 8))
        lib = taught_lib()
        for count in (15, 10, 1, 11, 1234, 4321, 1111):
            self.assertEqual(lib.digits.read_slot(render_quickslots({INS: (RED, count)}), INS), ("ok", count), count)

    def test_wrong_teaching_does_not_poison_reading(self):
        lib = fresh_lib()
        lib.digits.seeds = []
        strip = render_quickslots({INS: (RED, 38)})
        lib.digits.teach_slot(strip, INS, "38")
        again = lib.digits.teach_slot(strip, INS, "38")                    # teaching the same thing twice adds nothing
        self.assertEqual(again, 0)
        self.assertEqual(lib.digits.read_slot(strip, INS), ("ok", 38))

    def test_scan_reports_known_unknown_and_skills(self):
        lib = taught_lib()
        strip = render_quickslots({INS: (RED, 281), HM: (GREEN, 40), DEL: (YELLOW, 606), PGUP: (BLUE, None)})
        scan = ei.scan_strip(strip, lib)
        self.assertTrue(scan.visible)
        self.assertEqual([(s.key, s.name, s.count) for s in scan.known], [("Ins", "Red Potion", 281), ("Del", "Lemon", 606)])
        self.assertEqual([s.key for s in scan.unknown], ["Hm"])           # an icon it doesn't know, with a quantity
        self.assertEqual(scan.counts(), {"Red Potion": 281, "Lemon": 606})
        self.assertEqual(scan.unreadable, [])
        self.assertNotIn("PgUp", [s.key for s in scan.unknown])           # no quantity: a skill, nothing to add

    def test_the_top_row_is_scanned_when_it_is_there(self):
        lib = taught_lib()
        scan = ei.scan_strip(render_quickslots({0: (RED, 50), INS: (RED, 281)}, expanded=True), lib)
        self.assertEqual(scan.counts(), {"Red Potion": 50, "Red Potion #2": 281})
        collapsed = ei.scan_strip(render_quickslots({INS: (RED, 281)}), lib)
        self.assertEqual(collapsed.counts(), {"Red Potion": 281})

    def test_one_item_in_two_slots(self):
        lib = taught_lib()
        # different counts: two stacks (say a tradeable one and a quest one) -> both counted, named apart
        two = ei.scan_strip(render_quickslots({1: (RED, 50), INS: (RED, 281), DEL: (YELLOW, 7)}, expanded=True), lib)
        self.assertEqual(two.counts(), {"Red Potion": 50, "Red Potion #2": 281, "Lemon": 7})
        self.assertEqual(ei.base_name("Red Potion #2"), "Red Potion")
        # the same count twice: one stack shown in two slots, counted once
        same = ei.scan_strip(render_quickslots({1: (RED, 50), INS: (RED, 50)}, expanded=True), lib)
        self.assertEqual(same.counts(), {"Red Potion": 50})

    def test_known_item_with_unreadable_count_is_flagged(self):
        lib = taught_lib("12345")
        scan = ei.scan_strip(render_quickslots({SHIFT: (RED, 6)}), lib)    # '6' was never taught
        self.assertEqual([s.key for s in scan.unreadable], ["Shift"])
        self.assertEqual(scan.counts(), {})

    def test_a_plain_filled_slot_is_not_an_icon(self):
        strip = render_quickslots({})
        x, y = ei.slot_origin(CTRL)
        strip[y:y + 28, x:x + 28] = (190, 130, 150)                       # the pink "Ctrl / ATTACK" style slot
        info = ei.scan_strip(strip, fresh_lib()).slots[CTRL]
        self.assertFalse(info.has_art)


class RealScreenshotTests(unittest.TestCase):
    """testdata/ holds uncompressed crops of the real quick-slot panel (two layouts):
    1: Pet Food 38, Orange Potion 607, Speed Potion 4, Warrior Potion 7, plus skills.
    2: the same plus a top row (Red Potion 281, Red Potion 50, Meat 25, Blue Potion 40) and a Pure Water 19."""
    WANT1 = {"Pet Food": 38, "Orange Potion": 607, "Speed Potion": 4, "Warrior Potion": 7}
    WANT2 = {"Red Potion": 281, "Red Potion #2": 50, "Meat": 25, "Blue Potion": 40,
             "Orange Potion": 607, "Speed Potion": 4, "Warrior Potion": 7}

    def test_reads_the_real_panels_out_of_the_box(self):
        scan = ei.scan_strip(raw_strip(1), fresh_lib())
        self.assertTrue(scan.visible)
        self.assertEqual(scan.counts(), self.WANT1)
        self.assertEqual(scan.unknown, [])                                # the skill icons are not offered as items
        scan = ei.scan_strip(raw_strip(2), fresh_lib())
        self.assertEqual(scan.counts(), self.WANT2)
        self.assertEqual([(s.key, s.count) for s in scan.unknown], [("Ins", 19)])   # a white bottle it hasn't met
        self.assertEqual(scan.unreadable, [])

    def test_a_few_pixels_of_offset_make_no_difference(self):
        for which, want in ((1, self.WANT1), (2, self.WANT2)):
            lib = fresh_lib()
            for ox in range(-5, 6):
                for oy in range(-2, 3):
                    scan = ei.scan_strip(raw_strip(which, ox, oy), lib)
                    self.assertEqual((scan.dx, scan.dy), (-ox, -oy), (which, ox, oy))
                    self.assertEqual(scan.counts(), want, (which, ox, oy))

    def test_all_ten_digits_come_built_in(self):
        self.assertEqual(fresh_lib().digits.known(), "0123456789")

    def test_a_strip_captured_live_reads_every_stack(self):
        scan = ei.scan_strip(live_strip(), fresh_lib())
        self.assertEqual((scan.dx, scan.dy), (0, 0))
        self.assertEqual(scan.counts(), {"Warrior Potion": 7, "Magic Potion": 15, "Sniper Potion": 1, "Speed Potion": 4,
                                         "Red Potion": 50, "Orange Potion": 607, "Blue Potion": 40,
                                         "Blue Potion #2": 10, "Red Potion #2": 282, "Meat": 25, "Lemon": 606,
                                         "Pet Food": 37})
        self.assertEqual(scan.unknown, [])
        self.assertEqual(scan.unreadable, [])

    def test_digits_taught_by_an_older_version_are_ignored(self):
        lib = fresh_lib()
        lib.save()
        data = json.loads(lib.path.read_text())
        data.pop("digits_version", None)
        data["digits"] = [{"ch": "1", "rows": ["10101010"] * 12}]
        data["items"] = [{"name": "Old Item", "price": 7, "rows": None}]
        lib.path.write_text(json.dumps(data))
        again = ei.ItemLibrary(path=lib.path).load()
        self.assertEqual(again.digits.cells, [])
        self.assertEqual(again.price("Old Item"), 7)                      # items and prices are kept

    def test_calibration_on_a_blank_or_odd_strip_does_not_crash(self):
        for strip in (np.zeros((ei.STRIP_H, ei.STRIP_W, 3), dtype=np.uint8),
                      np.full((ei.STRIP_H, ei.STRIP_W, 3), 255, dtype=np.uint8)):
            dx, dy, _ = ei.calibrate(strip)
            self.assertEqual((dx, dy), (0, 0))


class DigitSlipTests(unittest.TestCase):
    def test_what_counts_as_a_lost_or_gained_digit(self):
        for old, new in ((37, 3), (37, 7), (15, 1), (150, 15), (150, 50), (7, 70), (7, 37), (4, 14), (281, 1), (281, 28)):
            self.assertTrue(ei.digit_slip(old, new), (old, new))
        for old, new in ((37, 36), (150, 149), (100, 90), (7, 6), (30, 3 * 5), (37, 37), (606, 600), (25, 52)):
            self.assertFalse(ei.digit_slip(old, new), (old, new))


class LibraryTests(unittest.TestCase):
    def test_items_prices_and_digits_survive_a_restart(self):
        lib = taught_lib()
        lib.add_item("Lemon", 175, ei.icon_signature(ei.slot_crop(render_quickslots({INS: (YELLOW, None)}), INS)))
        lib.save()
        again = ei.ItemLibrary(path=lib.path).load()
        again.digits.seeds = []
        self.assertEqual(again.price("Lemon"), 175)
        self.assertEqual(again.price("Red Potion"), 50)
        self.assertEqual(again.price("Meat"), 80)                         # built-in price list
        strip = render_quickslots({PGUP: (RED, 4096)})
        self.assertEqual(ei.scan_strip(strip, again).counts(), {"Red Potion": 4096})
        again.forget_user()
        self.assertEqual(again.price("Lemon"), 150)

    def test_price_list(self):
        lib = fresh_lib()
        for name, price in (("Red Potion", 50), ("Orange Potion", 150), ("White Potion", 350), ("Blue Potion", 220),
                            ("Warrior Potion", 500), ("Sniper Potion", 500), ("Magic Potion", 500), ("Meat", 80),
                            ("Lemon", 150), ("Pet Food", 35), ("Apple", 20), ("Egg", 30), ("Orange", 50)):
            self.assertEqual(lib.price(name), price, name)


class StockTests(unittest.TestCase):
    PRICES = {"Red Potion": 50, "Meat": 80}

    def stock(self, **start):
        st = ei.StockTracker()
        st.update(start, self.PRICES, counting=False)
        st.begin()
        return st

    def test_using_items_costs_their_price(self):
        st = self.stock(**{"Red Potion": 100, "Meat": 20})
        st.update({"Red Potion": 90, "Meat": 20}, self.PRICES, True)
        self.assertEqual(st.cost(), 10 * 50)
        st.update({"Red Potion": 90, "Meat": 15}, self.PRICES, True)
        self.assertEqual(st.cost(), 500 + 5 * 80)

    def test_restocking_or_looting_nets_out(self):
        st = self.stock(**{"Red Potion": 100})
        st.update({"Red Potion": 60}, self.PRICES, True)               # used 40
        st.update({"Red Potion": 260}, self.PRICES, True)              # bought 200 (mesos paid show in Mesos gained)
        self.assertEqual(st.cost(), (100 - 260) * 50)
        st.update({"Red Potion": 259}, self.PRICES, True)
        self.assertEqual(st.cost(), (100 - 259) * 50)

    def test_changes_while_stopped_are_not_counted(self):
        st = self.stock(**{"Red Potion": 100})
        st.update({"Red Potion": 70}, self.PRICES, False)              # paused: drank 30
        self.assertEqual(st.cost(), 0)
        st.update({"Red Potion": 69}, self.PRICES, True)
        self.assertEqual(st.cost(), 50)

    def test_new_items_start_from_their_first_count_and_missing_ones_freeze(self):
        st = self.stock(**{"Red Potion": 100})
        st.update({"Red Potion": 95, "Meat": 30}, self.PRICES, True)   # meat first seen mid-session: baseline 30
        self.assertEqual(st.cost(), 5 * 50)
        st.update({"Red Potion": 95}, self.PRICES, True)               # meat leaves the slots: keeps its last count
        self.assertEqual(st.cost(), 5 * 50)
        st.update({"Red Potion": 95, "Meat": 28}, self.PRICES, True)   # and is counted again when it returns
        self.assertEqual(st.cost(), 5 * 50 + 2 * 80)

    def test_nothing_tracked_before_a_session_and_reset(self):
        st = ei.StockTracker()
        st.update({"Red Potion": 100}, self.PRICES, False)
        self.assertFalse(st.tracked())
        st.begin()
        self.assertTrue(st.tracked())
        st.update({"Red Potion": 99}, self.PRICES, True)
        self.assertEqual(st.cost(), 50)
        st.reset()
        self.assertFalse(st.tracked())
        self.assertEqual(st.cost(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=1)
