import json
import math
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

_TMP = tempfile.mkdtemp(prefix="exp_core_test_")
os.environ["EXP_TRACKER_DATA"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parent))

import exp_core as ec  # noqa: E402

REAL = Path("/root/.claude/uploads/699127d0-2826-553b-b230-5cada80f3323/5e0a4df9-image.jpg")

# EXP needed per level 1-50 as listed by the Classic World table (fetched from meowdb.com)
KNOWN_1_50 = [15, 34, 57, 92, 135, 372, 560, 840, 1242, 1716, 2360, 3216, 4200, 5460, 7050, 8840, 11040, 13716,
              16680, 20216, 24402, 28980, 34320, 40512, 47216, 54900, 63666, 73080, 83720, 95700, 108480,
              122760, 138666, 155540, 174216, 194832, 216600, 240500, 266682, 294216, 324240, 356916, 391160,
              428280, 468450, 510420, 555680, 604416, 655200, 709716]


# ---------------------------------------------------------------------------
# helpers to build synthetic game frames
# ---------------------------------------------------------------------------
def render_hud_text(text, width=100, height=13, bg=(40, 48, 54)):
    """Draw text with the game's own glyphs (white digits, green brackets) into a crop."""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        img[y, :, :] = np.array(bg) + y * 2
    x = 1
    for ch in text:
        rows = ec.SEED_GLYPHS[ch]
        bm = ec._rows_to_bitmap(rows)
        h, w = bm.shape
        y0 = 2 + (7 - h)  # glyphs sit on a common baseline
        color = (153, 204, 51) if ch in "[]" else (255, 255, 255)
        if ch == ",":
            y0 = 2 + 6
        if ch == ".":
            y0 = 2 + 6
        for yy in range(h):
            for xx in range(w):
                if bm[yy, xx] and 0 <= y0 + yy < height and 0 <= x + xx < width:
                    img[y0 + yy, x + xx] = color
        x += w + (2 if ch in ",.[]" else 1) + (1 if ch in "[" else 0)
    return img


def frame_with_hud(text, W=1366, H=768, win=(0, 0)):
    """Full-screen frame (so the window can sit anywhere) with the HUD text at the real offsets."""
    frame = np.full((H + 100, W + 100, 3), 30, dtype=np.uint8)
    spec = ec.DEFAULT_CONFIG["exp_region"]
    region = ec.compute_region({"left": win[0], "top": win[1], "width": W, "height": H}, spec)
    crop = render_hud_text(text, region["width"], region["height"])
    frame[region["top"]:region["top"] + region["height"], region["left"]:region["left"] + region["width"]] = crop
    return frame, region


def fmt(exp, pct):
    return f"{exp:,}[{pct:.2f}%]"


def pct_of(level, exp, table):
    return round(exp * 100.0 / table.total(level), 2)


class RegionTests(unittest.TestCase):
    def test_offsets_for_the_measured_screenshot(self):
        r = ec.compute_region({"left": 0, "top": 0, "width": 1366, "height": 768}, ec.DEFAULT_CONFIG["exp_region"])
        self.assertEqual(r, {"left": 746, "top": 736, "width": 100, "height": 13})

    def test_window_position_and_other_sizes(self):
        spec = ec.DEFAULT_CONFIG["exp_region"]
        r = ec.compute_region({"left": 120, "top": 80, "width": 1366, "height": 768}, spec)
        self.assertEqual((r["left"], r["top"]), (120 + 746, 80 + 736))
        # a bigger window: the HUD stays centered at the bottom
        r = ec.compute_region({"left": 0, "top": 0, "width": 1920, "height": 1080}, spec)
        self.assertEqual((r["left"], r["top"]), (960 + 63, 1080 - 32))
        # too small: region would fall outside the window
        self.assertIsNone(ec.compute_region({"left": 0, "top": 0, "width": 100, "height": 100}, spec))

    def test_find_window_none_without_windows_api(self):
        if sys.platform != "win32":
            self.assertIsNone(ec.find_game_window({"window_mode": "auto", "window_title": "MapleStory"}))

    @unittest.skipUnless(REAL.exists(), "real screenshot not available")
    def test_real_screenshot_reads_6340(self):
        from PIL import Image
        arr = np.array(Image.open(REAL).convert("RGB"))
        self.assertEqual(arr.shape[:2], (768, 1366))
        r = ec.compute_region({"left": 0, "top": 0, "width": 1366, "height": 768}, ec.DEFAULT_CONFIG["exp_region"])
        crop = arr[r["top"]:r["top"] + r["height"], r["left"]:r["left"] + r["width"]]
        cfg = ec.load_config()
        lib = ec.GlyphLibrary(Path(_TMP) / "nope.json").load()
        # the screenshot is a JPEG (blurry), the game itself is crisp, so try a few thresholds
        ok = []
        for thr in (170, 190, 210):
            cfg["threshold"] = thr
            reading, fr = ec.read_exp(crop, cfg, lib)
            ok.append((thr, reading.text, reading.exp, reading.pct))
        self.assertTrue(any(e == 6340 and p == 89.93 for _, _, e, p in ok), ok)


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.cfg = ec.load_config()
        self.lib = ec.GlyphLibrary(Path(_TMP) / "g.json").load()

    def test_seeds_cover_everything_needed(self):
        for ch in "0123456789,.%[]":
            self.assertIn(ch, self.lib.labels())

    def test_roundtrip_random_values_through_the_whole_pipeline(self):
        rnd = random.Random(7)
        for i in range(150):
            exp = rnd.choice([rnd.randint(0, 999), rnd.randint(1000, 99999), rnd.randint(100000, 9999999)])
            pct = round(rnd.uniform(0, 99.99), 2)
            win = (rnd.randint(0, 80), rnd.randint(0, 60))
            frame, region = frame_with_hud(fmt(exp, pct), win=win)
            cap = frame[region["top"]:region["top"] + region["height"],
                        region["left"]:region["left"] + region["width"]]
            reading, _ = ec.read_exp(cap, self.cfg, self.lib)
            self.assertEqual((reading.exp, reading.pct), (exp, pct), reading.text)

    def test_one_pixel_region_error_still_reads(self):
        for shift in (-1, 0, 1):
            frame, region = frame_with_hud(fmt(7409, 11.64))
            l = region["left"] + shift
            cap = frame[region["top"]:region["top"] + region["height"], l:l + region["width"]]
            reading, _ = ec.read_exp(cap, self.cfg, self.lib)
            self.assertEqual(reading.exp, 7409, (shift, reading.text))

    def test_label_period_in_region_is_ignored(self):
        # if the box starts a pixel early, the period of "EXP." shows up in front of the number
        reading, _ = ec.read_exp(render_hud_text(".6,340[89.93%]"), self.cfg, self.lib)
        self.assertEqual((reading.exp, reading.pct), (6340, 89.93))

    def test_clipped_percent_still_gives_exp(self):
        for t in ("6,340[89.93%", "6,340[89.9", "6,340[", "6,340"):
            reading, _ = ec.read_exp(render_hud_text(t), self.cfg, self.lib)
            self.assertEqual(reading.exp, 6340, t)
        reading, _ = ec.read_exp(render_hud_text("6,340[89.93"), self.cfg, self.lib)
        self.assertIsNone(reading.pct)
        reading, _ = ec.read_exp(render_hud_text("6,340[89.93%]"), self.cfg, self.lib)
        self.assertEqual(reading.pct, 89.93)

    def test_blank_and_noise(self):
        blank = np.full((13, 100, 3), 40, dtype=np.uint8)
        reading, fr = ec.read_exp(blank, self.cfg, self.lib)
        self.assertIsNone(reading.exp)
        self.assertEqual(fr.glyphs, [])

    def test_unknown_glyph_blocks_and_teaching_fixes(self):
        lib = ec.GlyphLibrary(Path(_TMP) / "g2.json", use_seeds=False)
        crop = render_hud_text("6,340[89.93%]")
        fr = ec.read_text(crop, 160, lib, 0.15)
        self.assertEqual(len(fr.unknown), len(fr.glyphs))
        self.assertEqual(ec.label_from_text(lib, fr.glyphs, "6,340[89.93%]", 0.15), 11)
        lib.save()
        lib2 = ec.GlyphLibrary(Path(_TMP) / "g2.json", use_seeds=False).load()
        reading, _ = ec.read_exp(crop, self.cfg, lib2)
        self.assertEqual(reading.exp, 6340)
        with self.assertRaises(ValueError):
            ec.label_from_text(lib, fr.glyphs, "6,340", 0.15)
        with self.assertRaises(ValueError):
            ec.label_from_text(lib, fr.glyphs, "6,3?0[89.93%]", 0.15)


class ParseTests(unittest.TestCase):
    def test_good(self):
        self.assertEqual(ec.parse_exp_text("7,409[11.64%]"), (7409, 11.64))
        self.assertEqual(ec.parse_exp_text("7,409(11.64%)"), (7409, 11.64))
        self.assertEqual(ec.parse_exp_text(".6,340[89.93%]"), (6340, 89.93))
        self.assertEqual(ec.parse_exp_text("1,234,567[0.05%]"), (1234567, 0.05))
        self.assertEqual(ec.parse_exp_text("0[0.00%]"), (0, 0.0))
        self.assertEqual(ec.parse_exp_text("15[0.1%]"), (15, 0.1))
        self.assertEqual(ec.parse_exp_text("6,340"), (6340, None))
        self.assertEqual(ec.parse_exp_text("6,340[89.9"), (6340, None))
        self.assertEqual(ec.parse_exp_text("6,340[89.93%]garbage?"), (6340, 89.93))

    def test_bad(self):
        for t in ["", "?", "7,4?9[11.64%]", "?7,409[11.64%]", "7,40[11.64%]", "74,09[11.64%]", "7,4091[11.64%]",
                  "abc", "[11.64%]", "7,409x", "1,2345[1%]"]:
            self.assertIsNone(ec.parse_exp_text(t), t)

    def test_percent_out_of_range_is_dropped(self):
        self.assertEqual(ec.parse_exp_text("7,409[111.64%]"), (7409, None))


class TableTests(unittest.TestCase):
    def setUp(self):
        self.t = ec.ExpTable()

    def test_official_table(self):
        self.assertEqual(ec.MAX_LEVEL, 99)
        for lvl, want in enumerate(KNOWN_1_50, start=1):
            self.assertEqual(self.t.total(lvl), want, lvl)
        self.assertEqual(self.t.total(51), 748608)
        self.assertEqual(self.t.total(89), 5684790)
        self.assertEqual(self.t.total(90), 11938059)
        self.assertEqual(self.t.total(99), 9482161548)
        self.assertIsNone(self.t.total(0))
        self.assertIsNone(self.t.total(100))

    def test_accumulated_column_of_the_official_table(self):
        acc = {2: 15, 10: 3347, 15: 20299, 27: 328171, 50: 6851591, 51: 7561307, 60: 15980857, 70: 31545355,
               89: 97637974, 90: 103322764, 95: 535708496, 96: 1023270857, 99: 8712616849}
        for lvl, want in acc.items():
            self.assertEqual(sum(ec.EXP_TO_NEXT[:lvl - 1]), want, lvl)

    def test_formula_agrees_for_1_to_50(self):
        for lvl in range(1, 51):
            q = lvl * lvl // 3
            f = (lvl * lvl // 2 + 15) * lvl if lvl <= 5 else (q + 19) * q
            self.assertEqual(f, ec.EXP_TO_NEXT[lvl - 1], lvl)

    def test_screenshots_identify_the_level(self):
        self.assertEqual(self.t.candidates(6340, 89.93), [15])
        self.assertEqual(self.t.candidates(7409, 11.64), [27])

    def test_rounding_modes_all_accepted(self):
        for lvl in (3, 15, 27, 40, 49, 70, 95):
            T = self.t.total(lvl)
            for exp in (1, 7, int(T * 0.3333), int(T * 0.77), int(T) - 1):
                p = exp * 100 / T
                for shown in (math.floor(p * 100) / 100, round(p, 2), math.ceil(p * 100) / 100):
                    self.assertTrue(self.t.consistent(lvl, exp, shown), (lvl, exp, shown))

    def test_wrong_levels_rejected(self):
        self.assertFalse(self.t.consistent(14, 6340, 89.93))
        self.assertFalse(self.t.consistent(16, 6340, 89.93))
        self.assertFalse(self.t.consistent(15, 7050, 100.0))   # exp must be below the requirement


def make_tracker(level=15, **kw):
    tbl = ec.ExpTable()
    kw.setdefault("timeout", 0)
    kw.setdefault("auto_start", False)
    return ec.SessionTracker(tbl, **kw), tbl


def feed_seq(tr, tbl, level, start_exp, step, n, t0=0.0, dt=1.0):
    exp = start_exp
    evs = []
    for i in range(n):
        evs.append(tr.feed(t0 + i * dt, exp, pct_of(level, exp, tbl)))
        exp += step
    return evs, exp


class TrackerTests(unittest.TestCase):
    def test_idle_until_started_and_level_detected(self):
        tr, tbl = make_tracker()
        evs, _ = feed_seq(tr, tbl, 27, 7409, 100, 5)
        self.assertEqual(evs[:2], ["waiting", "baseline"])
        self.assertEqual(tr.level, 27)
        self.assertEqual(tr.state, ec.IDLE)
        self.assertEqual(tr.gained_exp, 0)
        self.assertFalse(tr.has_session())
        self.assertEqual(tr.elapsed(10.0), 0.0)

    def test_manual_start_counts_from_the_start_point(self):
        tr, tbl = make_tracker()
        evs, exp = feed_seq(tr, tbl, 27, 7409, 100, 10)
        tr.start(10.0)   # reading at t=9 had exp 8309... baseline is the latest reading
        self.assertEqual(tr.state, ec.RUNNING)
        self.assertEqual(tr.start_info["exp"], exp - 100)
        feed_seq(tr, tbl, 27, exp, 100, 61, t0=10.0)
        self.assertEqual(tr.gained_exp, 100 * 61)       # the first reading of the new run adds one more step
        r = tr.rate(70.0)
        self.assertAlmostEqual(r[0] * 3600, 100 * 3600, delta=3600 * 2.5)
        for w in (60, 300, 900):
            self.assertAlmostEqual(tr.rate(70.0, w)[0], 100.0, delta=2.5)
        self.assertAlmostEqual(tr.elapsed(70.0), 60.0, delta=0.01)

    def test_start_before_baseline_begins_when_baseline_known(self):
        tr, tbl = make_tracker()
        tr.start(0.0)
        self.assertEqual(tr.state, ec.IDLE)
        evs, _ = feed_seq(tr, tbl, 15, 6340, 10, 3, t0=1.0)
        self.assertEqual(tr.state, ec.RUNNING)
        self.assertTrue(tr.has_session())

    def test_percent_gained_and_eta(self):
        tr, tbl = make_tracker()
        _, exp = feed_seq(tr, tbl, 15, 1000, 0, 2)
        tr.start(2.0)
        feed_seq(tr, tbl, 15, 1000, 50, 101, t0=2.0)
        self.assertAlmostEqual(tr.gained_pct, 5000 / 7050 * 100, delta=0.05)
        eta = tr.eta_seconds(102.0)
        self.assertAlmostEqual(eta, (7050 - 6000) / 50, delta=3)
        self.assertAlmostEqual(tr.cur_pct(), 6000 / 7050 * 100, delta=0.01)

    def test_auto_start_on_first_gain(self):
        tr, tbl = make_tracker(auto_start=True)
        evs, exp = feed_seq(tr, tbl, 15, 3000, 0, 4)       # no gain: stays idle
        self.assertEqual(tr.state, ec.IDLE)
        tr.feed(10.0, 3040, pct_of(15, 3040, tbl))          # first gain starts the session
        self.assertEqual(tr.state, ec.RUNNING)
        self.assertEqual(tr.start_info["exp"], 3000)
        self.assertEqual(tr.gained_exp, 40)

    def test_idle_timeout_stops_the_clock_where_it_is_and_auto_resumes(self):
        tr, tbl = make_tracker(auto_start=True, timeout=60)
        _, exp = feed_seq(tr, tbl, 15, 1000, 0, 2)
        tr.start(2.0)
        # gain every second for 100 s
        t = 2.0
        for i in range(100):
            exp += 10
            tr.feed(t, exp, pct_of(15, exp, tbl)); t += 1
        last_gain_t = t - 1
        # nothing for 70 s
        while t < last_gain_t + 70:
            tr.feed(t, exp, pct_of(15, exp, tbl)); tr.tick(t); t += 1
        self.assertEqual(tr.state, ec.TIMEOUT)
        active_at_timeout = tr.elapsed(t)
        # the clock stopped when the time-out hit (60 s after the last gain) and never jumped back
        self.assertAlmostEqual(active_at_timeout, last_gain_t + 60 - 2.0, delta=0.01)
        t += 500                                                                   # long break, clock frozen
        self.assertAlmostEqual(tr.elapsed(t), active_at_timeout, delta=0.01)
        exp += 10
        self.assertEqual(tr.feed(t, exp, pct_of(15, exp, tbl)), "ok")             # gain -> auto restart
        self.assertEqual(tr.state, ec.RUNNING)
        self.assertEqual(tr.gained_exp, 1010)
        for i in range(30):
            t += 1; exp += 10
            tr.feed(t, exp, pct_of(15, exp, tbl))
        self.assertAlmostEqual(tr.elapsed(t), active_at_timeout + 30, delta=0.5)

    def test_manual_mode_never_auto_pauses(self):
        tr, tbl = make_tracker(auto_start=False, timeout=30)
        _, exp = feed_seq(tr, tbl, 15, 1000, 0, 2)
        tr.start(2.0)
        for t in range(2, 1000):                               # no EXP at all for a long time
            tr.tick(float(t))
        self.assertEqual(tr.state, ec.RUNNING)                 # MANUAL: it runs until you pause it
        self.assertAlmostEqual(tr.elapsed(999.0), 997.0, delta=0.01)
        tr.configure(30, True, 0)                              # switching to AUTO applies the idle rule from then on
        tr.tick(1000.0)
        self.assertEqual(tr.state, ec.TIMEOUT)
        tr.configure(30, False, 0)                             # (and back: the button is the only way to resume)
        tr.feed(1100.0, exp + 50, pct_of(15, exp + 50, tbl))
        self.assertEqual(tr.state, ec.TIMEOUT)
        tr.start(1101.0)
        self.assertEqual(tr.state, ec.RUNNING)

    def test_auto_restarts_after_a_manual_pause_but_manual_does_not(self):
        for auto in (True, False):
            tr, tbl = make_tracker(auto_start=auto, timeout=0)
            _, exp = feed_seq(tr, tbl, 15, 1000, 0, 2)
            tr.start(2.0)
            t = 2.0
            for i in range(30):
                t += 1; exp += 10; tr.feed(t, exp, pct_of(15, exp, tbl))
            tr.pause(t)
            before, paused_at = tr.gained_exp, t
            for i in range(20):                                   # EXP keeps coming while paused
                t += 1; exp += 10; tr.feed(t, exp, pct_of(15, exp, tbl))
            if auto:
                self.assertEqual(tr.state, ec.RUNNING)            # the first gain after the pause restarts the clock
                self.assertEqual(tr.gained_exp, before + 200)     # (that gain counts, and so does everything after it)
                self.assertAlmostEqual(tr.elapsed(t), 30 + 19, delta=0.01)   # the paused stretch is not counted
            else:
                self.assertEqual(tr.state, ec.PAUSED)
                self.assertEqual(tr.gained_exp, before)

    def test_the_clock_never_runs_backwards(self):
        import random
        rnd = random.Random(11)
        for trial in range(300):
            tr, tbl = make_tracker(auto_start=rnd.random() < 0.7, timeout=rnd.choice([0, 5, 15]))
            _, exp = feed_seq(tr, tbl, 15, 1000, 0, 2)
            t, last = 2.0, 0.0
            for step in range(150):
                t += 1
                r = rnd.random()
                if r < 0.04:
                    tr.toggle(t)
                elif r < 0.55:
                    exp += rnd.randint(1, 30)
                tr.feed(t, exp, pct_of(15, exp, tbl))
                tr.tick(t)
                self.assertGreaterEqual(tr.elapsed(t), last - 1e-6, (trial, step))
                last = tr.elapsed(t)

    def test_auto_resume_continues_the_same_session(self):
        for how in ("manual pause", "idle time-out"):
            tr, tbl = make_tracker(auto_start=True, timeout=10 if how == "idle time-out" else 0)
            _, exp = feed_seq(tr, tbl, 15, 1000, 0, 2)
            tr.start(2.0)
            t = 2.0
            for i in range(40):
                t += 1; exp += 10; tr.feed(t, exp, pct_of(15, exp, tbl)); tr.tick(t)
            tr.set_meso(t, 5000)
            session, start, gained, active = tr.session_id, dict(tr.start_info), tr.gained_exp, tr.elapsed(t)
            samples, meso_samples = len(tr.exp_samples), len(tr.meso_samples)
            if how == "manual pause":
                tr.pause(t)
            for i in range(30):                                   # quiet (and, for the time-out, it trips)
                t += 1; tr.feed(t, exp, pct_of(15, exp, tbl)); tr.tick(t)
            self.assertIn(tr.state, (ec.PAUSED, ec.TIMEOUT))
            t += 1; exp += 10; tr.feed(t, exp, pct_of(15, exp, tbl))   # EXP again
            self.assertEqual(tr.state, ec.RUNNING, how)
            self.assertEqual(tr.session_id, session)              # not a new session
            self.assertEqual(tr.start_info, start)                # same starting level / EXP
            self.assertEqual(tr.gained_exp, gained + 10)          # what was gained carries on
            self.assertGreaterEqual(tr.elapsed(t), active)        # the clock carries on from where it stopped
            self.assertLess(tr.elapsed(t), active + (10 if how == 'idle time-out' else 0) + 3)   # (nothing added by a pause)
            self.assertGreater(len(tr.exp_samples), samples)      # the graph keeps its history
            self.assertEqual(len(tr.meso_samples), meso_samples)  # and so do the mesos readings
            self.assertEqual(tr.meso_samples[0][1], 5000)

    def test_manual_pause_excludes_time_and_exp(self):
        tr, tbl = make_tracker(auto_start=False, timeout=0)
        _, exp = feed_seq(tr, tbl, 15, 1000, 0, 2)
        tr.start(2.0)
        t = 2.0
        for i in range(30):
            t += 1; exp += 10; tr.feed(t, exp, pct_of(15, exp, tbl))
        tr.pause(t)
        before = tr.gained_exp
        for i in range(60):
            t += 1; exp += 10; tr.feed(t, exp, pct_of(15, exp, tbl))
        self.assertEqual(tr.gained_exp, before)
        self.assertEqual(tr.state, ec.PAUSED)           # MANUAL mode: only the play button resumes
        tr.start(t)
        for i in range(30):
            t += 1; exp += 10; tr.feed(t, exp, pct_of(15, exp, tbl))
        self.assertEqual(tr.gained_exp, before + 300)
        self.assertAlmostEqual(tr.elapsed(t), 60.0, delta=0.01)

    def test_level_up_carries_over_exact_exp(self):
        tr, tbl = make_tracker()
        total = 7050
        _, exp = feed_seq(tr, tbl, 15, 6900, 0, 2)
        tr.start(2.0)
        evs = []
        virtual = 6900
        for i in range(12):
            virtual += 40
            if virtual < total:
                e, L = virtual, 15
            else:
                e, L = virtual - total, 16
            evs.append(tr.feed(3.0 + i, e, pct_of(L, e, tbl)))
        self.assertEqual(evs.count("levelup"), 1, evs)
        self.assertEqual(tr.level, 16)
        self.assertEqual(tr.level_ups, 1)
        self.assertEqual(tr.gained_exp, 40 * 12)       # exact: carry-over is counted
        want_pct = (total - 6900) / total * 100 + (virtual - total) / 8840 * 100
        self.assertAlmostEqual(tr.gained_pct, 6900 and (40 * 12 - (virtual - total)) / total * 100 +
                               (virtual - total) / 8840 * 100, delta=0.01)

    def test_level_up_with_tiny_new_percent_and_a_single_garbage_reading(self):
        tr, tbl = make_tracker()
        _, _ = feed_seq(tr, tbl, 15, 6990, 0, 2)
        tr.start(2.0)
        seq = [(7040, 15), (7049, 15), (3, 16), (3, 16), (60, 16), (500, 20)]  # last one is garbage-ish
        evs = [tr.feed(3.0 + i, e, pct_of(L, e, tbl)) for i, (e, L) in enumerate(seq)]
        self.assertEqual(evs[2], "pending")
        self.assertEqual(evs[3], "levelup")
        self.assertEqual(tr.level, 16)
        self.assertEqual(tr.gained_exp, (7049 - 6990) + (7050 - 7049) + 3 + (60 - 3))

    def test_level_up_without_percent_uses_the_big_drop_rule(self):
        tr, tbl = make_tracker()
        _, _ = feed_seq(tr, tbl, 15, 6900, 0, 2)
        tr.start(2.0)
        tr.feed(3.0, 7000, None)
        self.assertEqual(tr.feed(4.0, 20, None), "pending")
        self.assertEqual(tr.feed(5.0, 25, None), "levelup")
        self.assertEqual(tr.level, 16)
        self.assertEqual(tr.gained_exp, 100 + 50 + 25)

    def test_death_is_a_loss_not_a_level_up(self):
        tr, tbl = make_tracker()
        _, _ = feed_seq(tr, tbl, 27, 50000, 0, 2)
        tr.start(2.0)
        for i, e in enumerate([50500, 51000, 44000, 44100]):   # lost ~7000 (11% of the level)
            ev = tr.feed(3.0 + i, e, pct_of(27, e, tbl))
            self.assertEqual(ev, "ok")
        self.assertEqual(tr.level, 27)
        self.assertEqual(tr.level_ups, 0)
        self.assertEqual(tr.gained_exp, 44100 - 50000)

    def test_misread_is_ignored(self):
        tr, tbl = make_tracker()
        _, exp = feed_seq(tr, tbl, 27, 7409, 0, 2)
        tr.start(2.0)
        evs = []
        for i in range(10):
            e = exp + 100 * (i + 1)
            if i == 4:
                evs.append(tr.feed(3.0 + i, e + 40000, pct_of(27, e, tbl)))   # digit misread, % says otherwise
            else:
                evs.append(tr.feed(3.0 + i, e, pct_of(27, e, tbl)))
        self.assertEqual(evs[4], "rejected")
        self.assertEqual(tr.gained_exp, 1000)

    def test_character_switch_rebases_without_gains(self):
        tr, tbl = make_tracker(auto_start=False)
        _, _ = feed_seq(tr, tbl, 27, 7409, 0, 2)
        tr.start(2.0)
        tr.feed(3.0, 7500, pct_of(27, 7500, tbl))
        evs = [tr.feed(4.0 + i, 3000 + i * 10, pct_of(15, 3000 + i * 10, tbl)) for i in range(4)]
        self.assertIn("rebased", evs)
        self.assertEqual(tr.level, 15)
        self.assertEqual(tr.gained_exp, 91 + 10)        # 7409->7500, then +10 on the new level after the re-base
        self.assertEqual(tr.level_ups, 0)

    def test_level_override_without_percent(self):
        tr, tbl = make_tracker(level_override=15)
        self.assertEqual(tr.feed(0.0, 6340, None), "waiting")
        self.assertEqual(tr.feed(1.0, 6350, None), "baseline")
        self.assertEqual(tr.level, 15)
        tr2, _ = make_tracker(level_override=15)
        self.assertEqual(tr2.feed(0.0, 99999, None), "mismatch")    # more than the level needs

    def test_unknown_level_waits(self):
        tr, tbl = make_tracker()
        self.assertEqual(tr.feed(0.0, 0, 0.0), "waiting")
        self.assertEqual(tr.feed(1.0, 0, 0.0), "ambiguous")        # exp 0 fits every level
        self.assertEqual(tr.feed(2.0, 100, pct_of(15, 100, tbl)), "baseline")
        self.assertEqual(tr.level, 15)
        tr2, _ = make_tracker()
        self.assertEqual(tr2.feed(0.0, 5, None), "need_pct")

    def test_high_level_detection_and_levelup(self):
        tr, tbl = make_tracker()
        for lvl, exp in ((60, 300000), (89, 5000000), (90, 11000000)):
            tr2, _ = make_tracker()
            evs = [tr2.feed(float(i), exp + i * 1000, pct_of(lvl, exp + i * 1000, tbl)) for i in range(4)]
            self.assertEqual(evs[:2], ["waiting", "baseline"], lvl)
            self.assertEqual(tr2.level, lvl)
            self.assertEqual(set(evs[2:]), {"ok"})
        # level 89 -> 90 carry-over
        tr, _ = make_tracker()
        tr.feed(0.0, 5600000, pct_of(89, 5600000, tbl)); tr.feed(1.0, 5600000, pct_of(89, 5600000, tbl))
        tr.start(1.0)
        tr.feed(2.0, 5684000, pct_of(89, 5684000, tbl))
        tr.feed(3.0, 2210, pct_of(90, 2210, tbl)); ev = tr.feed(4.0, 2210, pct_of(90, 2210, tbl))
        self.assertEqual(ev, "levelup")
        self.assertEqual(tr.gained_exp, (5684000 - 5600000) + (5684790 - 5684000) + 2210)

    def test_meso_tracking(self):
        tr, tbl = make_tracker()
        tr.set_meso(0.0, 1000)                  # typed before the session exists
        _, _ = feed_seq(tr, tbl, 15, 1000, 0, 2)
        tr.start(2.0)
        self.assertEqual(tr.meso_samples[0], [0.0, 1000])
        self.assertIsNone(tr.meso_rate())
        tr.set_meso(1802.0, 61000)               # 30 minutes later
        self.assertEqual(tr.meso_gain(), 60000)
        self.assertAlmostEqual(tr.meso_rate(), 120000, delta=1)
        self.assertEqual(len(tr.meso_series()), 1)

    def test_rate_series_and_decimation(self):
        times = [0.0] + [float(t) for t in range(1, 601)]
        gains = [0.0] + [t * 10.0 for t in range(1, 601)]
        series = ec.rolling_rate_series(times, gains, 600.0, 300.0, 60)
        self.assertTrue(series)
        for t, r in series:
            self.assertAlmostEqual(r, 36000.0, delta=1.0)

    def test_reset_clears_session_keeps_level(self):
        tr, tbl = make_tracker()
        _, exp = feed_seq(tr, tbl, 15, 1000, 0, 2)
        tr.start(2.0)
        feed_seq(tr, tbl, 15, 1000, 20, 121, t0=2.0)
        tr.set_meso(10.0, 5000); tr.set_meso(110.0, 9000)
        self.assertTrue(tr.has_session())
        tr.reset()
        self.assertFalse(tr.has_session())
        self.assertEqual(tr.state, ec.IDLE)
        self.assertEqual(tr.level, 15)               # baseline survives for the next session
        self.assertEqual(tr.gained_exp, 0)
        self.assertEqual(tr.meso_samples, [])

    def test_configure_changes_take_effect(self):
        tr, tbl = make_tracker()
        feed_seq(tr, tbl, 27, 7409, 0, 2)
        self.assertEqual(tr.level, 27)
        tr.configure(timeout=30, auto_start=True, level_override=15)
        self.assertEqual(tr.timeout, 30)
        self.assertIsNone(tr.level)                    # re-detects with the new override

    def test_formatting(self):
        self.assertEqual(ec.fmt_eta(None), "--")
        self.assertEqual(ec.fmt_eta(30), "<1m")
        self.assertEqual(ec.fmt_eta(3 * 3600 + 12 * 60), "3h 12m")
        self.assertEqual(ec.fmt_eta(26 * 3600), "1d 2h")
        self.assertEqual(ec.fmt_clock(15807), "04:23:27")
        self.assertEqual(ec.fmt_short(432247), "432k")
        self.assertEqual(ec.fmt_short(1_250_000), "1.2M")
        self.assertEqual(ec.fmt_int(432247.4), "432,247")


def frame_with_inventory(mesos, org=(214, 55), W=1366, H=768):
    """A game frame with the inventory window's title and mesos box drawn at the real offsets."""
    img = np.full((H, W, 3), 90, dtype=np.uint8)
    ox, oy = org
    for y, row in enumerate(ec.INV_TITLE):
        for x, c in enumerate(row):
            img[oy + y, ox + x] = 0 if c == "#" else (255 if c == "." else 150)
    b = ec.INV_MESO_BOX
    img[oy + b["dy"]:oy + b["dy"] + b["h"], ox + b["dx"]:ox + b["dx"] + b["w"]] = 255
    x = ox + b["dx"] + b["w"] - 3
    for ch in reversed(f"{mesos:,}"):
        bm = ec._rows_to_bitmap(ec.MESO_GLYPHS[ch])
        h, w = bm.shape
        x -= w
        y0 = oy + b["dy"] + (8 if ch == "," else 2)
        img[y0:y0 + h, x:x + w][bm] = 0
        x -= 1 if ch != "," else 2
    return img


class FrameCap:
    def __init__(self, frame):
        self.frame = frame

    def grab(self, r):
        return self.frame[r["top"]:r["top"] + r["height"], r["left"]:r["left"] + r["width"]]


class InventoryTests(unittest.TestCase):
    WIN = {"left": 0, "top": 0, "width": 1366, "height": 768}

    def test_reads_mesos_wherever_the_window_is(self):
        for org, mesos in (((214, 55), 175965), ((42, 36), 2216), ((600, 120), 0), ((900, 300), 1234567890)):
            rd = ec.InventoryReader()
            self.assertEqual(rd.poll(FrameCap(frame_with_inventory(mesos, org)), self.WIN, 10.0), mesos)
            self.assertEqual(rd.origin, org)

    def test_closed_inventory_reads_nothing(self):
        rd = ec.InventoryReader()
        cap = FrameCap(np.full((768, 1366, 3), 90, dtype=np.uint8))
        self.assertIsNone(rd.poll(cap, self.WIN, 10.0))
        self.assertIsNone(rd.poll(cap, self.WIN, 10.5))      # throttled: no new full search yet

    def test_follows_the_window_when_it_moves_or_closes(self):
        rd = ec.InventoryReader()
        self.assertEqual(rd.poll(FrameCap(frame_with_inventory(5000, (100, 100))), self.WIN, 1.0), 5000)
        self.assertEqual(rd.poll(FrameCap(frame_with_inventory(5100, (100, 100))), self.WIN, 2.0), 5100)
        self.assertIsNone(rd.poll(FrameCap(np.full((768, 1366, 3), 90, dtype=np.uint8)), self.WIN, 3.0))
        self.assertEqual(rd.poll(FrameCap(frame_with_inventory(5200, (300, 200))), self.WIN, 6.0), 5200)

    def test_game_window_offset_is_respected(self):
        win = {"left": 200, "top": 100, "width": 1366, "height": 768}
        frame = np.full((1000, 1700, 3), 90, dtype=np.uint8)
        frame[100:868, 200:1566] = frame_with_inventory(42000, (50, 60))
        self.assertEqual(ec.InventoryReader().poll(FrameCap(frame), win, 1.0), 42000)

class MesoTests(unittest.TestCase):
    def test_each_session_gets_an_id(self):
        tr, tbl = make_tracker(auto_start=False)
        feed_seq(tr, tbl, 15, 1000, 0, 2)
        self.assertEqual(tr.session_id, 0)
        tr.start(1.0)
        self.assertEqual(tr.session_id, 1)
        tr.pause(2.0)
        tr.start(3.0)                                         # resuming is not a new session
        self.assertEqual(tr.session_id, 1)
        tr.reset()
        tr.start(4.0)
        self.assertEqual(tr.session_id, 2)

    def test_rates_exist_from_the_first_second(self):
        tr, tbl = make_tracker(auto_start=True)
        feed_seq(tr, tbl, 15, 1000, 0, 2)
        t = 10.0
        tr.start(t)
        self.assertIsNone(tr.rate(t))                         # nothing elapsed yet
        feed_seq(tr, tbl, 15, 1100, 0, 1)
        r = tr.rate(t + 2.0)
        self.assertIsNotNone(r)

    def test_mesos_ignored_while_stopped_and_rebaselined_on_resume(self):
        tr, tbl = make_tracker(auto_start=False)
        feed_seq(tr, tbl, 15, 1000, 0, 2)
        self.assertTrue(tr.set_meso(1.0, 5000))               # before the session: the start value
        tr.start(2.0)
        self.assertEqual(tr.meso_samples, [[0.0, 5000]])
        self.assertTrue(tr.set_meso(12.0, 5600))
        tr.pause(12.0)
        self.assertFalse(tr.set_meso(20.0, 9000))             # paused: ignored
        tr.start(40.0)
        self.assertTrue(tr.set_meso(41.0, 9100))              # first look after resuming: the new baseline
        self.assertEqual(tr.meso_samples[-1][1], 5600)        # (+3500 happened while stopped; none of it counts)
        self.assertTrue(tr.set_meso(51.0, 9150))
        self.assertEqual(tr.meso_samples[-1][1], 5650)
        self.assertAlmostEqual(tr.meso_rate(), 650 / tr.meso_samples[-1][0] * 3600)

    def test_meso_trend_windows_use_the_data_there_is(self):
        tr, tbl = make_tracker(auto_start=False)
        feed_seq(tr, tbl, 15, 1000, 0, 2)
        tr.set_meso(0.0, 0)
        tr.start(0.0)
        for t in range(10, 130, 10):                          # 10 mesos a second
            tr.set_meso(float(t), t * 10)
        full = tr.meso_rate()
        self.assertAlmostEqual(full, 36000.0)
        self.assertAlmostEqual(tr.meso_rate(60), 36000.0)
        self.assertAlmostEqual(tr.meso_rate(900), 36000.0)    # shorter session than the window: all of it


if __name__ == "__main__":
    unittest.main(verbosity=1)
