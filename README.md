# MapleStory Classic World EXP tracker

A small always-on-top overlay that reads your EXP from the game's status bar (about once a second)
and shows EXP/hour and mesos/hour, with a trend graph behind each number. It only looks at screen
pixels; it never touches the game's process, memory or files. Whether any third-party tool is
acceptable under the game's rules is for you to check.

## Run it

```
pip install -r requirements.txt
python exp_tracker.py
```

Run the game **windowed or borderless fullscreen** (exclusive fullscreen can capture as black).
The overlay opens without tracking. Press ▶ (or, in AUTO mode, just gain some EXP).

`python exp_tracker.py --check` prints what the tracker sees right now (game window, EXP box, text read).

## The overlay

A narrow panel (268 px wide) built to sit in the empty strip beside the game's status bar. It docks
bottom-left of the game window every time you start it (as soon as it finds the game); Settings has **Dock left / Dock right**,
and you can drag it anywhere for the rest of that run.
Clicking it never takes keyboard focus away from the game (it only takes focus while you type in a text field).

- **Top bar**: the session clock (green while tracking), ▶/⏸ start and pause, ↺ reset, the **AUTO / MANUAL** switch, a sliders
  icon for settings, ✕ close. Reset and close never ask anything.
- **AUTO / MANUAL**: in AUTO the clock starts when you gain EXP, and **resumes the same session** after an auto-pause *or after you paused it by
  hand* the moment EXP comes in again (time, EXP, graphs, mesos and potions carry on; only the paused stretch is left out). In MANUAL only ▶ does.
  Only EXP triggers it: HP, MP and mesos changes never start the clock (you take damage leaving a map, sell things in town...).
- **Message line**: Ready, Tracking, Paused, or what's wrong (problems have an amber icon, e.g.
  "Make sure the EXP number is showing.").
- **EXP** and **Mesos** rows: click a row to step through its views, then back to the first. Each row keeps its own view.
  The trend graph sits faintly behind the numbers.

  | View | EXP | Mesos |
  | --- | --- | --- |
  | 1 | EXP/hr | Mesos/hr |
  | 2 | + EXP (%) per hour, time to next level | Mesos gained (and when it last synced), Potion cost, Estimated profit, and what the quick slots show |
  | 3 | Last 15m / 5m / 1m (EXP/hr) | Last 15m / 5m / 1m (mesos/hr) |
  | 4 | Last 15m / 5m / 1m (%/hr) | |

  The arrows in the trend views compare each window with your session average (green = faster, red = slower).
  If the session is shorter than a window, that row shows the session so far.
- **Settings** replace the panel in place. Use ‹ or the sliders icon to go back (changes apply then).

## How it finds your EXP

The status bar is always the same size, centered at the bottom of the game window. The tracker finds the
game window by title, then reads a 100×13 px box that starts 63 px right of the window's center and 32 px
above its bottom edge (measured on a 1366×768 window). It knows the HUD's pixel font (digits, `, . % [ ]`),
so no calibration is normally needed.

Your **level** is worked out automatically: the EXP number and the percent beside it only fit one level in
the official EXP table (levels 1-99), and the tracker re-checks every reading against it. From then on it
uses the table for level-ups (the carried-over EXP is counted), percent gained and the time to level.
A reading that doesn't fit is ignored as a misread. If it ever can't work out your level, set it in Settings.

## Sessions

- **Not tracking at launch.** ▶ starts it. In AUTO the clock also starts, and restarts after a time-out, as soon as you gain EXP.
- **Numbers show from the first second.** The first rates are raw (a single kill looks huge) and settle down as the
  session grows.
- **Auto-pause** (default 15 s, Settings, **AUTO mode only**): with no EXP gained for that long the clock stops where it is
  (it never jumps back) and carries on from there when EXP comes in again. In MANUAL the clock never pauses by itself. A death penalty counts as negative EXP.
- **Mesos** are read from the item inventory window whenever it is open (any tab, anywhere on screen): the tracker spots the
  "ITEM INVENTORY" title and reads the mesos box a fixed distance below it. The first reading is the start value. Readings
  are only as frequent as the inventory is open, so keep it open if you want accurate mesos rates. While the clock is
  stopped mesos aren't tracked, and the first reading after a resume becomes the new baseline (no jump).
- **Potion cost** (quick slots only): the quick-slot numbers are your inventory counts, so the tracker watches the
  consumables you keep in the slots and prices them with the NPC buy price (Red Potion 50, Orange 150, White 350, Blue 220,
  Warrior / Sniper / Magic 500, Meat 80, Pet Food 35...). Cost = price × (count when the session started − count now), summed
  over the items. Buying or looting a stack raises the count, so it nets out against the mesos you gained (cost can go negative
  while you restock). Nothing counts while the clock is stopped, and a count that only differs from the last one by a digit appearing or vanishing
  (37 → 3) has to be read four times in a row before it is believed. **Estimated profit** = mesos gained − potion cost.
  The second mesos view lists what it found ("Detected Pet Food, Red Potion, Meat, Lemon") or "Quick slots not visible".
- **What it recognises out of the box**: Pet Food, Red / Orange / Blue / Speed / Warrior / Magic / Sniper Potion, Meat and
  Lemon (by their colours), and all ten digits of the count font. The font is proportional (a 1 is narrower than the others), so
  the digits are read one after another by comparing their black outlines. Anything else is added once: **[Add custom]** (also
  Settings ▸ Check quick slots…) lists the icons it doesn't know that show a quantity. Give the item a name and price and type
  the quantity you see. If a number ever can't be read it says "(count?)": open the same dialog and type what you see, which
  teaches it that shape.
- **All rows**: it reads the bottom two rows of the quick slots and, when the panel is expanded, the top row (hotkeys 1-4) too.
- **Two stacks of one item** (say a tradeable one and a quest one): different counts are two stacks and both are priced; the
  same count in two slots is taken to be one stack.
- **Exact position**: the quick-slot panel can sit a pixel or two differently from window to window, so it finds the panel's
  exact position from its frame every time before it reads anything.
- **Sharing**: what you teach it lives in `exp_tracker_data/consumables.json` (icons, prices, digit shapes). The shapes are
  those of the game's own font, so the file works on anyone's PC at the same game UI. Copy it into their `exp_tracker_data`
  folder, or send it to be built in as defaults.
- Nothing is written to disk except your settings and any characters you teach it.

## Settings

Auto-pause time, your level (blank = auto), game-window mode and title, read interval (EXP, mesos), opacity (60-100%: only the backgrounds fade, never the text),
Dock left/right, and **Check / adjust EXP box…** (shows the box on a live picture of your screen, lets you nudge
it, and teaches the tracker any character it doesn't know).

## Troubleshooting

| Status line | What to do |
| --- | --- |
| Game window not found | The window title must contain the text in Settings (default `MapleStory`). Use `--check`, or switch to "Use my whole main screen". |
| Can't see the EXP numbers | Game minimized, exclusive fullscreen, or the box is off: Settings ▸ Check / adjust EXP box. |
| Unknown character | Check / adjust EXP box: type what you see. |
| Detecting your level… | It locks on once your EXP changes (EXP 0 fits every level). |

## Files

`exp_tracker.py` (start here), `exp_core.py` (reading, tracking), `exp_items.py` (quick slots, potion cost),
`exp_ui.py` (interface), `test_core.py`, `test_items.py` and `test_ui.py` (`python -m unittest`). Data lives in `exp_tracker_data/` next to the script.
## Building the exe and releases

- **Build it yourself**: `pip install -r requirements.txt -r requirements-dev.txt`, then `.\build.ps1` (or
  `python -m PyInstaller exp_tracker.spec`). The result is `dist\MapleEXPTracker.exe` (about 48 MB). It keeps its settings and
  what you taught it in an `exp_tracker_data` folder next to the exe.
- **Automatic releases**: `.github/workflows/release.yml` runs on every push to `main`: the tests, then the build, then a new
  GitHub release (`v1.0.<run number>`) with the exe attached and notes generated from the commits. Put `[skip release]` in a
  commit message to skip it. `exp_tracker_data/` is in `.gitignore` on purpose: it holds your own settings and teaching.
- The exe isn't code-signed, so Windows SmartScreen or an antivirus may warn about it the first time.
