import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import sys
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="exp_ui_test_")
os.environ["EXP_TRACKER_DATA"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import exp_core as ec  # noqa: E402
import exp_ui  # noqa: E402
import test_core as T  # noqa: E402
import test_items as TI  # noqa: E402
import exp_items as ei  # noqa: E402

app = QApplication.instance() or QApplication([])
exp_ui.apply_dark_theme(app)
WIN = {"left": 0, "top": 0, "width": 1366, "height": 768}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeCap:
    """Plays the game: shows the EXP text for (level, exp), or blank / garbage on demand."""

    def __init__(self):
        self.level, self.exp, self.mode = 15, 6340, "hud"
        self.calls = []

    def grab(self, region):
        self.calls.append(region)
        w, h = region["width"], region["height"]
        if self.mode == "blank":
            return np.full((h, w, 3), 40, dtype=np.uint8)
        pct = round(self.exp * 100 / ec.ExpTable().total(self.level), 2)
        return T.render_hud_text(T.fmt(self.exp, pct), w, h)


def make(auto_start=False, timeout=0, win=WIN, cfg_edit=None, exp=1000):
    d = tempfile.mkdtemp(dir=_TMP)
    os.environ["EXP_TRACKER_DATA"] = d
    cfg = ec.load_config()
    cfg["auto_start"], cfg["timeout_seconds"] = auto_start, timeout
    cfg["read_mesos"] = False
    cfg["read_quickslots"] = False
    if cfg_edit:
        cfg_edit(cfg)
    clock, cap = Clock(), FakeCap()
    cap.exp = exp
    w = exp_ui.OverlayWindow(cfg=cfg, capture=cap, find_window=lambda c: win, clock=clock, start_timer=False)
    w.show()
    return w, clock, cap


def tick(w, clock, cap, n=1, gain=0, dt=1.0):
    for _ in range(n):
        clock.t += dt
        cap.exp += gain
        w.on_tick()
    app.processEvents()


def rows(chip):
    return [(r[0], r[1]) for r in chip.rows]


def done(w):
    w.timer.stop()
    w.close()


class OverlayTests(unittest.TestCase):
    def test_launches_idle_and_does_not_track(self):
        w, clock, cap = make()
        tick(w, clock, cap, 5, gain=10)
        self.assertEqual(w.tracker.state, ec.IDLE)
        self.assertEqual(w.tracker.level, 15)
        self.assertEqual(w.tracker.gained_exp, 0)
        self.assertEqual(w.timer_lbl.text(), "00:00:00")
        self.assertIn("press", w.status_lbl.text().lower())
        self.assertEqual(w.width(), 268)
        self.assertEqual(cap.calls[-1], {"left": 746, "top": 736, "width": 100, "height": 13})
        for gone in ("store", "report", "end_session_flow", "edit_notes"):
            self.assertFalse(hasattr(w, gone), gone)
        done(w)

    def test_ready_and_tracking_messages_have_no_dot(self):
        w, clock, cap = make(auto_start=True)
        tick(w, clock, cap, 2)
        self.assertIn("Ready—gain EXP or press play", w.status_lbl.text())
        tick(w, clock, cap, 1, gain=15)
        self.assertIn("Tracking", w.status_lbl.text())
        self.assertNotIn("●", w.status_lbl.text())
        done(w)

    def test_default_pause_is_15_seconds_and_opacity_range(self):
        self.assertEqual(ec.DEFAULT_CONFIG["timeout_seconds"], 15)
        w, clock, cap = make()
        w.set_opacity(0.2)
        self.assertEqual(w.opacity, 0.6)
        w.set_opacity(1.0)
        self.assertEqual((w.chip_exp.bg_alpha, w.chip_meso.bg_alpha), (255, 255))
        done(w)

    def test_auto_start_and_timeout_cycle(self):
        w, clock, cap = make(auto_start=True, timeout=30)
        tick(w, clock, cap, 3)
        self.assertEqual(w.tracker.state, ec.IDLE)
        tick(w, clock, cap, 1, gain=15)
        self.assertEqual(w.tracker.state, ec.RUNNING)
        tick(w, clock, cap, 20, gain=15)
        tick(w, clock, cap, 40, gain=0)
        self.assertEqual(w.tracker.state, ec.TIMEOUT)
        frozen = w.timer_lbl.text()
        tick(w, clock, cap, 100, gain=0)
        self.assertEqual(w.timer_lbl.text(), frozen)
        tick(w, clock, cap, 1, gain=15)
        self.assertEqual(w.tracker.state, ec.RUNNING)
        done(w)

    def test_status_messages(self):
        w, clock, cap = make()
        w.find_window = lambda c: None
        tick(w, clock, cap)
        self.assertIn("Game window not found", w.status_lbl.text())
        w.find_window = lambda c: {"left": 0, "top": 0, "width": 200, "height": 100}
        tick(w, clock, cap)
        self.assertIn("too small", w.status_lbl.text())
        w.find_window = lambda c: WIN
        cap.mode = "blank"
        tick(w, clock, cap)
        self.assertIn("Make sure the EXP number is showing.", w.status_lbl.text())
        cap.mode = "hud"
        w.lib.user_items = []
        w.lib.items = [(l, b) for l, b in w.lib.items if l != "7"]
        cap.exp = 7000
        tick(w, clock, cap)
        self.assertIn("Make sure the EXP number is showing.", w.status_lbl.text())
        done(w)

    def test_settings_page_toggles_inline_and_applies(self):
        w, clock, cap = make()
        tick(w, clock, cap, 2)
        main_h = w.height()
        w.btn_gear.clicked.emit()
        self.assertTrue(w.in_settings)
        self.assertEqual(w.pages.currentIndex(), 1)
        w.settings.timeout.setValue(90)
        w.settings.level.setValue(15)
        w.settings.title.setText("  Maple  ")
        w.settings.mode.setCurrentIndex(1)
        w.settings.interval.setValue(2.0)
        w.settings.opacity.setValue(70)
        self.assertAlmostEqual(w.opacity, 0.7, places=2)
        self.assertEqual(w.chip_exp.bg_alpha, 178)
        self.assertEqual((w.settings.opacity.minimum(), w.settings.opacity.maximum()), (60, 100))
        self.assertEqual(w.windowOpacity(), 1.0)       # only the backgrounds are translucent, never the text
        w.btn_back.clicked.emit()                       # back button returns and applies
        self.assertFalse(w.in_settings)
        self.assertEqual(w.pages.currentIndex(), 0)
        self.assertEqual((w.tracker.timeout, w.tracker.auto_start, w.tracker.level_override), (90.0, False, 15))
        self.assertEqual((w.cfg["window_title"], w.cfg["window_mode"], w.cfg["interval"]), ("Maple", "screen", 2.0))
        self.assertEqual(w.timer.interval(), 2000)
        self.assertEqual(w.height(), w._refit())                 # laid out again (the message may differ in length)
        w.btn_gear.clicked.emit()                       # gear opens again, gear returns too
        w.btn_gear2.clicked.emit()
        self.assertFalse(w.in_settings)
        self.assertEqual(ec.load_config()["timeout_seconds"], 90)
        done(w)

    def test_every_launch_starts_docked_left_wherever_it_was_left(self):
        for saved in ({"x": 300, "y": 100, "placed": True}, {"x": 60, "y": 60, "placed": False}):
            w, clock, cap = make(cfg_edit=lambda c, s=saved: c["overlay"].update(s))
            self.assertEqual((w.x(), w.y()), (saved["x"], saved["y"]))     # until the game window is found
            tick(w, clock, cap, 1)
            left_dock = w.x()
            self.assertLess(left_dock, 100)                                # docked at the game window's left edge
            w.move(450, 200)                                               # dragged somewhere else...
            tick(w, clock, cap, 3)
            self.assertEqual((w.x(), w.y()), (450, 200))                   # ...and left there for the rest of the run
            done(w)

    def test_dock_left_and_right(self):
        win = {"left": 20, "top": 30, "width": 760, "height": 700}
        w, clock, cap = make(win=win)
        tick(w, clock, cap, 1)                          # first run docks bottom-left on its own
        self.assertTrue(w.cfg["overlay"]["placed"])
        self.assertEqual(w.x(), 28)
        self.assertEqual(w.y() + w.height(), 30 + 700 - 8)
        w.dock("right")
        self.assertEqual(w.x(), 20 + 760 - 268 - 8)
        self.assertEqual(w.y() + w.height(), 30 + 700 - 8)
        w.chip_exp.clicked.emit()                       # grows upward from the bottom edge
        self.assertEqual(w.y() + w.height(), 30 + 700 - 8)
        w.find_window = lambda c: None
        w.last_win = None
        w.dock("left")
        self.assertIn("nothing to dock", w.status_lbl.text())
        done(w)

    def test_close_saves_position_without_prompt(self):
        w, clock, cap = make()
        tick(w, clock, cap, 3)
        w.btn_play.clicked.emit()
        tick(w, clock, cap, 20, gain=10)
        w.move(123, 77)
        w.btn_close.clicked.emit()
        cfg = ec.load_config()
        self.assertEqual((cfg["overlay"]["x"], cfg["overlay"]["y"]), (123, 77))

    def test_focus_gate_toggles_window_flag(self):
        w, clock, cap = make()
        F = Qt.WindowType.WindowDoesNotAcceptFocus
        self.assertTrue(w.windowFlags() & F)
        w._focus_mode(True)
        self.assertFalse(w.windowFlags() & F)
        w._focus_mode(False)
        self.assertTrue(w.windowFlags() & F)
        self.assertTrue(w._is_input(w.settings.timeout.lineEdit()))
        self.assertFalse(w._is_input(w.btn_play))
        done(w)

    def test_calibrate_dialog_reads_nudges_and_teaches(self):
        w, clock, cap = make(exp=6340)
        tick(w, clock, cap, 1)
        d = exp_ui.CalibrateDialog(w, w)
        self.assertIn("Reads: 6,340", d.reads.text())
        self.assertIn("Looks good", d.msg.text())
        d.spins["dx"].setValue(64)
        self.assertEqual(w.cfg["exp_region"]["dx"], 64)
        self.assertEqual(cap.calls[-1]["left"], 747)
        d.spins["dx"].setValue(63)
        w.lib.items = [(l, b) for l, b in w.lib.items if l != "3"]
        d.frozen = False
        d.refresh()
        self.assertTrue(d.frozen)
        self.assertFalse(d.teach_row.isHidden())
        d.entry.setText("6,340[89.93%]")
        d._teach()
        self.assertFalse(d.frozen)
        self.assertIn("Reads: 6,340", d.reads.text())
        self.assertTrue(any(l == "3" for l, _ in w.lib.user_items))
        d.timer.stop()
        d.accept()
        done(w)

    def test_calibrate_reports_missing_window(self):
        w, clock, cap = make()
        w.find_window = lambda c: None
        d = exp_ui.CalibrateDialog(w, w)
        self.assertIn("not found", d.msg.text())
        d.timer.stop()
        done(w)

    def test_level_override_path_without_percent(self):
        w, clock, cap = make(cfg_edit=lambda c: c.update(level_override=15))
        tick(w, clock, cap, 3)
        self.assertEqual(w.tracker.level, 15)
        done(w)

    def test_play_pause_and_headline_values(self):
        w, clock, cap = make()
        tick(w, clock, cap, 3)
        w.btn_play.clicked.emit()
        self.assertEqual(w.tracker.state, ec.RUNNING)
        self.assertEqual(w.btn_play.kind, "pause")
        self.assertIn("Tracking", w.status_lbl.text())
        tick(w, clock, cap, 60, gain=20)
        self.assertEqual(w.timer_lbl.text(), "00:01:00")
        self.assertEqual((w.chip_exp.value, w.chip_exp.unit), (f"{20 * 3600:,}", "/ hr"))
        self.assertEqual(w.chip_exp.rows, [])
        self.assertEqual(w.chip_meso.value, "---")
        w.btn_play.clicked.emit()
        self.assertEqual(w.tracker.state, ec.PAUSED)
        self.assertEqual(w.btn_play.kind, "play")
        tick(w, clock, cap, 10, gain=20)
        self.assertEqual(w.timer_lbl.text(), "00:01:00")
        done(w)

    def test_numbers_show_from_the_first_seconds(self):
        w, clock, cap = make(auto_start=True)
        tick(w, clock, cap, 2)
        self.assertEqual(w.chip_exp.value, "---")           # no session yet
        tick(w, clock, cap, 1, gain=100)                    # first EXP: the session starts
        tick(w, clock, cap, 1, gain=100)
        self.assertNotEqual(w.chip_exp.value, "---")        # a raw rate straight away...
        early = int(w.chip_exp.value.replace(",", ""))
        tick(w, clock, cap, 58)
        late = int(w.chip_exp.value.replace(",", ""))
        self.assertGreater(early, late)                     # ...that settles down towards the real rate
        done(w)

    def test_chips_cycle_through_their_views_and_back(self):
        w, clock, cap = make()
        tick(w, clock, cap, 3)
        w.btn_play.clicked.emit()
        tick(w, clock, cap, 60, gain=20)
        h0 = w.height()
        w.chip_exp.clicked.emit()                           # 2: detailed
        self.assertEqual([r[0] for r in w.chip_exp.rows], ["EXP (%)", "Next level up"])
        self.assertTrue(w.chip_exp.rows[0][1].endswith("%"))
        self.assertNotIn("--", w.chip_exp.rows[1][1])
        h1 = w.height()
        self.assertGreater(h1, h0)
        geo = w._screen_geo()
        self.assertTrue(geo.contains(w.geometry().topLeft()))
        w.chip_exp.clicked.emit()                           # 3: trends (flat numbers)
        self.assertEqual([r[0] for r in w.chip_exp.rows], ["Last 15m", "Last 5m", "Last 1m"])
        self.assertEqual({r[1] for r in w.chip_exp.rows}, {f"{20 * 3600:,}"})
        self.assertEqual({r[3] for r in w.chip_exp.rows}, {None})       # same as the session average: no arrow
        w.chip_exp.clicked.emit()                           # 4: trends (percent)
        self.assertTrue(all(r[1].endswith("%") for r in w.chip_exp.rows))
        w.chip_exp.clicked.emit()                           # and back to the basic view
        self.assertEqual(w.chip_exp.rows, [])
        self.assertEqual(w.height(), h0)
        for expected in (3, 3, 0):                          # mesos has three, independent of EXP
            w.chip_meso.clicked.emit()
            self.assertEqual(len(w.chip_meso.rows), expected)
        self.assertEqual(w.views["exp"], 0)
        w.grab()
        done(w)

    def test_trend_arrows_compare_with_the_session_average(self):
        w, clock, cap = make()
        tick(w, clock, cap, 3)
        w.btn_play.clicked.emit()
        tick(w, clock, cap, 600, gain=2)
        tick(w, clock, cap, 120, gain=8)                    # the last two minutes are faster
        w.views["exp"] = 2
        w.refresh(clock.t)
        arrows = {r[0]: r[3] for r in w.chip_exp.rows}
        self.assertEqual(arrows["Last 1m"], "up")
        self.assertEqual(arrows["Last 5m"], "up")
        tick(w, clock, cap, 70, gain=0)                     # then a quiet stretch
        w.refresh(clock.t)
        arrows = {r[0]: r[3] for r in w.chip_exp.rows}
        self.assertEqual(arrows["Last 1m"], "down")
        done(w)

    def test_mesos_follow_the_open_inventory(self):
        w, clock, cap = make(auto_start=True, cfg_edit=lambda c: c.update(read_mesos=True))
        frames = {"inv": T.frame_with_inventory(100000, (214, 55)), "none": np.full((768, 1366, 3), 90, np.uint8)}
        state = {"f": "inv"}
        hud = cap.grab

        def grab(region):
            if region["width"] == 100 and region["height"] == 13:      # the EXP box
                return hud(region)
            f = frames[state["f"]]
            return f[region["top"]:region["top"] + region["height"], region["left"]:region["left"] + region["width"]]

        cap.grab = grab
        tick(w, clock, cap, 2)
        tick(w, clock, cap, 1, gain=10)                      # session starts; start value comes from the inventory
        self.assertEqual(w.tracker.state, ec.RUNNING)
        frames["inv"] = T.frame_with_inventory(100000 + 50 * 40, (214, 55))
        tick(w, clock, cap, 40, gain=10)
        self.assertEqual(w.tracker.meso_samples[0][1], 100000)
        self.assertEqual(w.tracker.meso_samples[-1][1], 102000)
        self.assertEqual(w.chip_meso.value, f"{int(w.tracker.meso_rate()):,}")
        self.assertEqual(w.chip_meso.suffix, "0s ago")
        self.assertNotIn("Open inventory", w.status_lbl.text())
        n = len(w.tracker.meso_samples)
        state["f"] = "none"                                  # inventory closed: nothing new, nothing breaks
        tick(w, clock, cap, 70, gain=10)
        self.assertEqual(len(w.tracker.meso_samples), n)
        self.assertTrue(w.chip_meso.suffix.endswith("s ago") or w.chip_meso.suffix.endswith("m ago"))
        self.assertEqual(w.status_lbl.text(), "Tracking. Open inventory to sync mesos.")
        done(w)

    def test_mesos_pause_with_the_clock_and_rebaseline_on_resume(self):
        w, clock, cap = make(cfg_edit=lambda c: c.update(read_mesos=True))
        state = {"mesos": 1000}
        hud = cap.grab

        def grab(region):
            if region["width"] == 100 and region["height"] == 13:
                return hud(region)
            f = T.frame_with_inventory(state["mesos"], (214, 55))
            return f[region["top"]:region["top"] + region["height"], region["left"]:region["left"] + region["width"]]

        cap.grab = grab
        tick(w, clock, cap, 3)
        w.btn_play.clicked.emit()
        for i in range(60):                                  # +10 mesos a second for a minute
            state["mesos"] += 10
            tick(w, clock, cap)
        self.assertEqual(w.tracker.meso_gain(), 600)
        w.btn_play.clicked.emit()                            # pause
        n = len(w.tracker.meso_samples)
        state["mesos"] += 100000                             # a big sale in town while paused
        tick(w, clock, cap, 30)
        self.assertEqual(len(w.tracker.meso_samples), n)     # not tracked while paused
        w.btn_play.clicked.emit()                            # resume
        tick(w, clock, cap, 3)
        self.assertLess(w.tracker.meso_samples[-1][1] - w.tracker.meso_samples[0][1], 1000)   # no jump
        done(w)

    def test_auto_manual_switch(self):
        w, clock, cap = make(auto_start=True)
        fm = exp_ui.QFontMetrics(w.btn_mode._font)                  # the button is only as wide as its text + 5 px each side
        self.assertEqual((w.btn_mode.width(), w.btn_mode.height()), (fm.horizontalAdvance("AUTO") + 10, 22))
        w.btn_mode.set_auto(False)
        self.assertEqual(w.btn_mode.width(), fm.horizontalAdvance("MANUAL") + 10)
        w.btn_mode.set_auto(True)
        self.assertTrue(w.btn_mode.auto)
        tick(w, clock, cap, 2)
        self.assertEqual(w.status_lbl.text(), "Ready—gain EXP or press play to start")
        w.btn_mode.clicked.emit()
        self.assertFalse(w.btn_mode.auto)
        self.assertFalse(w.tracker.auto_start)
        self.assertFalse(w.cfg["auto_start"])
        self.assertEqual(ec.load_config()["auto_start"], False)
        self.assertEqual(w.status_lbl.text(), "Ready—press play to start")
        tick(w, clock, cap, 5, gain=20)
        self.assertEqual(w.tracker.state, ec.IDLE)                 # EXP alone no longer starts the clock
        w.btn_mode.clicked.emit()
        self.assertTrue(w.tracker.auto_start)
        tick(w, clock, cap, 2, gain=20)
        self.assertEqual(w.tracker.state, ec.RUNNING)
        done(w)

    def test_paused_messages(self):
        w, clock, cap = make(auto_start=True, timeout=10)
        tick(w, clock, cap, 2)
        tick(w, clock, cap, 3, gain=20)
        tick(w, clock, cap, 15)                                    # idle past the time-out
        self.assertEqual(w.tracker.state, ec.TIMEOUT)
        self.assertEqual(w.status_lbl.text(), "Paused—gain EXP or press play to resume")
        self.assertEqual(w.status_lbl.kind, "paused")
        w.btn_mode.clicked.emit()
        self.assertEqual(w.status_lbl.text(), "Paused—press play to resume")
        w.btn_play.clicked.emit()
        self.assertEqual(w.tracker.state, ec.RUNNING)
        w.btn_play.clicked.emit()                                  # a deliberate pause
        self.assertEqual(w.status_lbl.text(), "Paused—press play to resume")
        done(w)

    # ---- quick slots / potion cost -------------------------------------------------------------
    def quick_overlay(self, slots, **kw):
        """An overlay whose capture shows `slots` (a dict the test can change) in the quick-slot panel."""
        w, clock, cap = make(auto_start=True, cfg_edit=lambda c: c.update(read_quickslots=True), **kw)
        w.items = TI.taught_lib()
        hud = cap.grab

        def grab(region):
            if region["width"] == ei.STRIP_W and region["height"] == ei.STRIP_H:
                return TI.render_quickslots(slots)
            return hud(region)

        cap.grab = grab
        return w, clock, cap

    def test_potion_cost_and_profit_rows(self):
        slots = {5: (TI.RED, 281), 9: (TI.YELLOW, 606)}
        w, clock, cap = self.quick_overlay(slots)
        tick(w, clock, cap, 3)
        w.btn_play.clicked.emit()                              # the session starts: today's counts are the baseline
        tick(w, clock, cap, 2)
        w.tracker.set_meso(clock.t, 10_000)
        slots[5] = (TI.RED, 271)                               # drank 10 Red Potions (50 each)
        tick(w, clock, cap, 3)
        slots[9] = (TI.YELLOW, 600)                            # ate 6 Lemons (150 each)
        tick(w, clock, cap, 3)
        w.tracker.set_meso(clock.t, 12_500)
        w.meso_synced_at = clock.t
        w.views["meso"] = 1
        w.refresh(clock.t)
        self.assertEqual([r.label for r in w.chip_meso.rows], ["Mesos gained", "Potion cost", "Estimated profit"])
        gained, cost, profit = (r.value for r in w.chip_meso.rows)
        self.assertEqual((gained, cost, profit), ("2,500", f"{10 * 50 + 6 * 150:,}", f"{2500 - 1400:,}"))
        self.assertEqual(w.chip_meso.suffix, "0s ago")                     # the sync time sits by the Mesos name
        self.assertEqual(w.chip_meso.rows[0].note, "")
        self.assertEqual(w.chip_meso.rows[1].note, "(quick slots only)")
        self.assertEqual(w.chip_meso.footer, "Detected Red Potion, Lemon")
        self.assertEqual(w.chip_meso.link, "")
        w.chip_meso.grab()
        slots[5] = (TI.RED, 1)                                 # a big spend turns the profit negative (red)
        tick(w, clock, cap, 6)                                 # (271 -> 1 looks like a lost digit, so it is held to 4 reads)
        w.refresh(clock.t)
        self.assertTrue(w.chip_meso.rows[2].value.startswith("-"))
        self.assertEqual(w.chip_meso.rows[2].color.red(), 248)
        w.btn_reset.clicked.emit()                             # a reset forgets the baseline too
        self.assertFalse(w.stock.tracked())
        done(w)

    def test_looting_or_restocking_lowers_the_cost(self):
        slots = {5: (TI.RED, 100)}
        w, clock, cap = self.quick_overlay(slots)
        tick(w, clock, cap, 3)
        w.btn_play.clicked.emit()
        tick(w, clock, cap, 2)
        slots[5] = (TI.RED, 80)
        tick(w, clock, cap, 3)
        self.assertEqual(w.stock.cost(), 20 * 50)
        slots[5] = (TI.RED, 130)                               # restocked 50
        tick(w, clock, cap, 3)
        self.assertEqual(w.stock.cost(), -30 * 50)
        done(w)

    def test_counts_must_repeat_before_they_are_trusted(self):
        slots = {5: (TI.RED, 100)}
        w, clock, cap = self.quick_overlay(slots)
        tick(w, clock, cap, 3)
        w.btn_play.clicked.emit()
        tick(w, clock, cap, 2)
        slots[5] = (TI.RED, 7)                                 # one odd frame...
        tick(w, clock, cap, 1)
        slots[5] = (TI.RED, 100)                               # ...then back
        tick(w, clock, cap, 3)
        self.assertEqual(w.stock.cost(), 0)
        done(w)

    def test_a_count_that_loses_a_digit_is_not_believed_at_once(self):
        slots = {5: (TI.RED, 37)}
        w, clock, cap = self.quick_overlay(slots)
        tick(w, clock, cap, 3)
        w.btn_play.clicked.emit()
        tick(w, clock, cap, 2)
        slots[5] = (TI.RED, 3)                                 # 37 -> 3: how a half-read number looks
        tick(w, clock, cap, 3)
        self.assertEqual(w.stock.cost(), 0)                    # three reads are not enough...
        tick(w, clock, cap, 1)
        self.assertEqual(w.stock.cost(), 34 * 50)              # ...four in a row make it real (you did use them)
        slots[5] = (TI.RED, 37)                                # and a glitch that reverts leaves no trace
        tick(w, clock, cap, 5)
        slots[5] = (TI.RED, 3)
        tick(w, clock, cap, 2)
        slots[5] = (TI.RED, 37)
        tick(w, clock, cap, 5)
        self.assertEqual(w.stock.cost(), 0)
        done(w)

    def test_ordinary_changes_need_only_two_reads(self):
        slots = {5: (TI.RED, 100)}
        w, clock, cap = self.quick_overlay(slots)
        tick(w, clock, cap, 3)
        w.btn_play.clicked.emit()
        tick(w, clock, cap, 2)
        slots[5] = (TI.RED, 90)
        tick(w, clock, cap, 2)
        self.assertEqual(w.stock.cost(), 10 * 50)
        done(w)

    def test_pausing_stops_counting_potions(self):
        slots = {5: (TI.RED, 100)}
        w, clock, cap = self.quick_overlay(slots)
        tick(w, clock, cap, 3)
        w.btn_play.clicked.emit()
        tick(w, clock, cap, 2)
        w.btn_play.clicked.emit()                              # paused
        slots[5] = (TI.RED, 60)
        tick(w, clock, cap, 4)
        self.assertEqual(w.stock.cost(), 0)
        w.btn_play.clicked.emit()
        slots[5] = (TI.RED, 59)
        tick(w, clock, cap, 3)
        self.assertEqual(w.stock.cost(), 50)
        done(w)

    def test_detection_line_messages(self):
        slots = {}
        w, clock, cap = self.quick_overlay(slots)
        w.find_window = lambda c: None
        w.last_win = None
        w.on_tick()
        self.assertEqual(w.detection_line(), ("Quick slots not visible", ""))
        w.find_window = lambda c: WIN
        tick(w, clock, cap, 2)
        self.assertEqual(w.detection_line(), ("No known consumables found in quick slots.", "[Add custom]"))
        slots.update({5: (TI.RED, 281), 9: (TI.YELLOW, 606)})
        tick(w, clock, cap, 2)
        self.assertEqual(w.detection_line(), ("Detected Red Potion, Lemon", ""))
        slots[6] = (TI.GREEN, 40)                              # an icon it doesn't know, with a quantity
        tick(w, clock, cap, 2)
        self.assertEqual(w.detection_line(), ("Detected Red Potion, Lemon", "[Add custom]"))
        slots[6] = (TI.GREEN, None)                            # no quantity: a skill, so nothing to add
        slots[5] = (TI.RED, 6)
        slots[9] = (TI.YELLOW, 12)
        w.items.digits.cells = [(c, t) for c, t in w.items.digits.cells if c != "6"]     # '6' was never taught
        tick(w, clock, cap, 2)
        self.assertEqual(w.detection_line(), ("Detected Red Potion (count?), Lemon", "[Teach counts]"))
        done(w)

    def test_real_screenshot_end_to_end(self):
        w, clock, cap = make(auto_start=True, cfg_edit=lambda c: c.update(read_quickslots=True))
        w.items = TI.fresh_lib()
        hud = cap.grab
        cap.grab = lambda region: (TI.raw_strip() if region["width"] == ei.STRIP_W and region["height"] == ei.STRIP_H
                                   else hud(region))
        tick(w, clock, cap, 3)
        self.assertEqual(w.detection_line(),
                         ("Detected Pet Food, Orange Potion, Speed Potion, Warrior Potion", ""))
        w.views["meso"] = 1
        w.refresh(clock.t)
        self.assertEqual(w.chip_meso.footer, "Detected Pet Food, Orange Potion, Speed Potion, Warrior Potion")
        done(w)

    def test_sync_time_is_shown_next_to_mesos_in_every_view(self):
        w, clock, cap = make()
        tick(w, clock, cap, 2)
        w.meso_synced_at = clock.t - 125
        for view in range(3):
            w.views["meso"] = view
            w.refresh(clock.t)
            self.assertEqual(w.chip_meso.suffix, "2m ago", view)
        done(w)

    def test_real_top_row_screenshot_and_two_stacks(self):
        w, clock, cap = make(auto_start=True, cfg_edit=lambda c: c.update(read_quickslots=True))
        w.items = TI.fresh_lib()
        hud = cap.grab
        cap.grab = lambda region: (TI.raw_strip(2) if region["width"] == ei.STRIP_W and region["height"] == ei.STRIP_H
                                   else hud(region))
        tick(w, clock, cap, 3)
        text, link = w.detection_line()
        self.assertEqual(text, "Detected Red Potion, Meat, Blue Potion, Orange Potion, Speed Potion, Warrior Potion")
        self.assertEqual(link, "[Add custom]")                 # the Pure Water (19) is an icon it has not met
        self.assertEqual(w.qscan.counts()["Red Potion #2"], 50)
        done(w)

    def test_two_stacks_of_one_item_are_both_priced(self):
        slots = {1: (TI.RED, 50), 5: (TI.RED, 281)}            # e.g. a quest stack and a bought one
        w, clock, cap = self.quick_overlay(slots)
        tick(w, clock, cap, 3)
        w.btn_play.clicked.emit()
        tick(w, clock, cap, 2)
        slots[1] = (TI.RED, 40)                                # 10 from the first stack
        slots[5] = (TI.RED, 271)                               # 10 from the second
        tick(w, clock, cap, 3)
        self.assertEqual(w.stock.cost(), 20 * 50)
        done(w)

    def test_changing_a_view_resizes_the_window_once_and_consistently(self):
        from PySide6.QtCore import QEvent, QObject

        class Count(QObject):
            def __init__(self):
                super().__init__()
                self.resizes = 0

            def eventFilter(self, obj, ev):
                if ev.type() == QEvent.Type.Resize:
                    self.resizes += 1
                return False

        w, clock, cap = make()
        tick(w, clock, cap, 3)
        watcher = Count()
        w.installEventFilter(watcher)
        for which in ("exp", "exp", "exp", "exp", "meso", "meso", "meso"):   # every view, and round again
            before = watcher.resizes
            w.chip_exp.clicked.emit() if which == "exp" else w.chip_meso.clicked.emit()
            self.assertLessEqual(watcher.resizes - before, 1)                 # one resize per click, never two
            self.assertEqual(w.height(), w._refit())                          # and it is the right size straight away
            self.assertTrue(w.updatesEnabled())
        done(w)

    def test_footer_link_has_its_own_click(self):
        w, clock, cap = make()
        w.chip_meso.set_data("", "1", exp_ui.HR, [], [], "Detected Meat", "[Add custom]")
        w.chip_meso.resize(260, w.chip_meso.height())
        w.chip_meso.grab()
        hits = []
        w.chip_meso.link_clicked.disconnect()                  # (the window opens a modal dialog on it)
        w.chip_meso.link_clicked.connect(lambda: hits.append("link"))
        w.chip_meso.clicked.connect(lambda: hits.append("chip"))
        QTest.mouseClick(w.chip_meso, Qt.MouseButton.LeftButton, pos=w.chip_meso._link_rect.center().toPoint())
        QTest.mouseClick(w.chip_meso, Qt.MouseButton.LeftButton, pos=QPoint(20, 10))
        self.assertEqual(hits, ["link", "chip"])
        done(w)

    def test_dialog_adds_items_and_teaches_the_digits(self):
        slots = {5: (TI.RED, 281), 6: (TI.GREEN, 40), 9: (TI.YELLOW, None)}
        w, clock, cap = self.quick_overlay(slots)
        w.items = TI.fresh_lib()                               # knows no digits and none of these colours
        tick(w, clock, cap, 2)
        d = exp_ui.QuickSlotDialog(w, w)
        self.assertEqual(len(d.rows), 3)                       # three icons
        by_key = {r["info"].key: r for r in d.rows}
        self.assertFalse(by_key["Del"]["qty"].isEnabled())     # no quantity shown: a skill
        r = by_key["Ins"]
        r["name"].setText("Red Potion")
        self.assertEqual(r["price"].value(), 50)               # price filled in from the built-in list
        r["qty"].setText("281")
        g = by_key["Hm"]
        g["name"].setText("Homemade Tonic")
        g["price"].setValue(70)
        g["qty"].setText("40")                                 # '4' is a digit it has not seen: teach it too
        d.save()
        self.assertEqual(d.msg.text().split(".")[0], "Saved")
        self.assertEqual(w.qscan.counts(), {"Red Potion": 281, "Homemade Tonic": 40})
        self.assertEqual(w.items.price("Homemade Tonic"), 70)
        self.assertEqual(ei.ItemLibrary(path=w.items.path).load().price("Homemade Tonic"), 70)   # saved to disk
        by_key = {r["info"].key: r for r in d.rows}
        by_key["Ins"]["qty"].setText("99")                     # wrong number of digits: explained, not a crash
        d.save()
        self.assertIn("digit", d.msg.text())
        d._forget()
        self.assertEqual(w.items.price("Homemade Tonic"), 0)
        d.close()
        done(w)

    def test_the_dialog_picks_items_from_a_list_inside_the_window(self):
        slots = {5: (TI.RED, 281), 6: (TI.GREEN, 40)}
        w, clock, cap = self.quick_overlay(slots)
        w.items = TI.fresh_lib()
        tick(w, clock, cap, 2)
        d = exp_ui.QuickSlotDialog(w, w)
        d.show()
        r = {x["info"].key: x for x in d.rows}["Hm"]
        self.assertTrue(r["choices"].isHidden())
        r["pick"].click()                                      # a list opens in the dialog itself (no popup window)
        self.assertFalse(r["choices"].isHidden())
        self.assertEqual(r["choices"].window(), d)
        names = [r["choices"].item(i).text() for i in range(r["choices"].count())]
        self.assertIn("Meat", names)
        r["choices"].itemClicked.emit(r["choices"].item(names.index("Meat")))
        self.assertEqual(r["name"].text(), "Meat")
        self.assertEqual(r["price"].value(), 80)               # the price follows the pick
        self.assertTrue(r["choices"].isHidden())               # and the list closes only once you've chosen
        r["pick"].click()
        r["pick"].click()
        self.assertTrue(r["choices"].isHidden())
        d.close()
        done(w)

    def test_dialog_says_when_the_panel_is_not_visible(self):
        w, clock, cap = make()
        w.find_window = lambda c: None
        w.last_win = None
        d = exp_ui.QuickSlotDialog(w, w)
        self.assertIn("aren't visible", d.msg.text())
        d.close()
        done(w)

    def test_manual_mode_never_auto_pauses_in_the_overlay(self):
        w, clock, cap = make(auto_start=False, timeout=15)
        tick(w, clock, cap, 2)
        w.btn_play.clicked.emit()
        tick(w, clock, cap, 120)                               # two idle minutes
        self.assertEqual(w.tracker.state, ec.RUNNING)
        self.assertEqual(w.timer_lbl.text(), "00:02:00")
        self.assertIn("Tracking", w.status_lbl.text())
        w.btn_mode.clicked.emit()                              # AUTO: now the idle rule applies
        tick(w, clock, cap, 2)
        self.assertEqual(w.tracker.state, ec.TIMEOUT)
        done(w)

    def test_a_manual_pause_in_auto_mode_resumes_on_exp(self):
        w, clock, cap = make(auto_start=True)
        tick(w, clock, cap, 2)
        tick(w, clock, cap, 3, gain=20)
        self.assertEqual(w.tracker.state, ec.RUNNING)
        w.btn_play.clicked.emit()                                  # paused by hand
        tick(w, clock, cap, 2)
        self.assertEqual(w.tracker.state, ec.PAUSED)
        self.assertEqual(w.status_lbl.text(), "Paused—gain EXP or press play to resume")
        tick(w, clock, cap, 1, gain=20)                            # EXP arrives: AUTO takes over again
        self.assertEqual(w.tracker.state, ec.RUNNING)
        self.assertIn("Tracking", w.status_lbl.text())
        w.btn_mode.clicked.emit()                                  # MANUAL: it stays paused
        w.btn_play.clicked.emit()
        tick(w, clock, cap, 3, gain=20)
        self.assertEqual(w.tracker.state, ec.PAUSED)
        done(w)

    def test_painting_never_crashes_with_odd_data(self):
        w, clock, cap = make()
        rows = [exp_ui.Row("Last 15m", "123,456,789,012", "/ hr", "up"),
                exp_ui.Row("A very long label indeed", "---", "", "down", "a long note " * 5),
                exp_ui.Row("x", "y" * 40, "z" * 20, None, "", QColor(1, 2, 3))]
        w.chip_exp.set_data("5m ago", "123,456,789,012", "/ hr", rows, [(0, 5), (1, 5)], "f" * 90, "[Add custom]")
        w.chip_exp.set_data("", "1", "", [], [(0, 0), (0, 0)])
        w.chip_exp.set_data("", "---", "/ hr", [], [])
        w.chip_meso.set_data("x" * 60, "1", "/ hr", rows, [(0, 5), (1, -5), (2, 9)], "", "[x]")
        w.chip_meso.grab()
        w.chip_exp.grab()
        for kind in ("info", "ok", "paused", "warn", "error"):
            w.status_lbl.set_message("Game window not found. Is MapleStory open? " * 3, kind)
            w.status_lbl.set_message("short", kind)
            w.status_lbl.grab()
        w.btn_play.grab()
        w.btn_mode.grab()
        w.grab()
        done(w)


if __name__ == "__main__":
    unittest.main(verbosity=2)
