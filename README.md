![EXP tracker preview](/misc/exp-tracker-preview.png)

# MapleStory Classic World EXP & Meso rate tracker
An overlay for tracking EXP & Meso rates in MapleStory Classic World. 

The exe isn't code-signed, so Windows SmartScreen or an antivirus may warn about it the first time.

## How it works
This program uses image recognition to read the values in your in-game UI every second to compute rates over time. It does not read from or write to game memory, interact with network packets, or interact with any other programs or files in any way. The program only scans for the game fonts used in specific areas of the UI, namely: current EXP above the EXP meter, current mesos in the inventory window (if open), and current potions in quick slots (if open, for calculating potion cost).

> [!CAUTION]
> This program is designed simply with the intention of allowing players to make informed decisions. It should not be modified in any way to abuse or exploit the game. Additionally, while the program is simply reading text in the game, it has not been directly audited by Nexon and thus the author(s) take no responsibility for any action taken against your account. Finally, only download executable files from the original author(s) and from sources that you trust.

## Setup
Downloads are available in [releases](https://github.com/luk-gg/classic-world-exp-tracker/releases).  
Otherwise, clone the repo and run with python:

```
pip install -r requirements.txt
python exp_tracker.py
```

To build the standalone executable:

```
pip install -r requirements.txt -r requirements-dev.txt
python -m PyInstaller exp_tracker.spec
```

An `exp_tracker_data` folder may be colocated alongside the exe.

## Usage
> [!IMPORTANT]
> The game must be in windowed mode for the overlay to work. The overlay has currently only been tested in 1366x768 game resolution.

At the top of the overlay, you have options to start/pause tracking, reset session, and switch between auto/manual mode. Auto will automatically restart whenever EXP is gained and pause after inactivity (timeout can be adjusted in settings). Manual requires you to manually click start and stop.

Click on the EXP or Meso sections to cycle between various data views.

![Data modes preview](/misc/exp-tracker-data-views.gif)

### Tracking mesos and potion cost
The bottom right messages that say "mesos/items/exp gained" can be fast and unreliable, so meso tracking uses the inventory to get your current meso amount. To update your meso rates, simply open your inventory or keep it open while playing. 

Potions in your quick slots can be tracked as well. The potion cost calculation uses the default NPC price to give you a rough estimate of how much it would cost to restock. It takes into account potions that you pick up. Only a few potions have been pre-configured for now--things like Pure Water, Salad, Ice Cream Pop, Watermelons have not been set, even if they are already available for purchase from an NPC. Items that can't be purchased (Sap of Ancient Tree, Drake's Blood) will likely never be pre-configured, but their icons might be taught in the future so you can manually add a price for them.