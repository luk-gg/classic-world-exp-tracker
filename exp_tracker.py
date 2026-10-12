#!/usr/bin/env python3
"""
MapleStory Classic World EXP tracker.

    python exp_tracker.py            # open the overlay (tracking starts when you press play / gain EXP)
    python exp_tracker.py --check    # print what the tracker sees right now (for troubleshooting)

It only reads a few screen pixels about once a second; it never touches the game itself.
"""
import sys


def check() -> int:
    import exp_core as ec
    cfg = ec.load_config()
    win = ec.find_game_window(cfg)
    print(f"data folder : {ec.data_dir()}")
    if not win:
        print("game window : NOT FOUND (title must contain "
              f"{cfg['window_title']!r}; or set window_mode to 'screen' in config.json)")
        return 1
    print(f"game window : {win.get('title')!r}  {win['width']}x{win['height']} at ({win['left']}, {win['top']})")
    region = ec.compute_region(win, cfg["exp_region"])
    if not region:
        print("EXP box     : falls outside the window")
        return 1
    print(f"EXP box     : {region}")
    lib = ec.GlyphLibrary().load()
    crop = ec.Capturer().grab(region)
    reading, _ = ec.read_exp(crop, cfg, lib)
    print(f"text read   : {reading.text!r}")
    if reading.exp is None:
        print("result      : could not read an EXP value")
        return 1
    cands = ec.ExpTable().candidates(reading.exp, reading.pct) if reading.pct is not None else []
    print(f"result      : EXP {reading.exp:,}  percent {reading.pct}  -> level candidates {cands}")
    return 0


def main() -> int:
    if "--check" in sys.argv:
        return check()
    from PySide6.QtWidgets import QApplication
    import exp_ui

    app = QApplication(sys.argv)
    app.setApplicationName("EXP Tracker")
    app.setQuitOnLastWindowClosed(False)
    exp_ui.apply_dark_theme(app)
    win = exp_ui.OverlayWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
