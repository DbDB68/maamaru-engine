# Maamaru `🦊` — A Honmaru Steward for Touken Ranbu ONLINE China

[**简体中文**](README.md) · **English**

[![License](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](pyproject.toml)
[![GitHub stars](https://img.shields.io/github/stars/DbDB68/maamaru-engine?style=social)](https://github.com/DbDB68/maamaru-engine)

> **You decide what your Honmaru should do today. Maamaru handles the routine, keeps watch, wraps things up, and balances the books.**

I have played Touken Ranbu for nine years, and I still want to keep playing. I just no longer want to click through every repetitive task myself—or maintain an Excel sheet by hand to work out where my resources came from and where they went. That is why I built Maamaru: a steward that looks after my Honmaru when I need it and becomes a quiet, standalone ledger when I do not want it connected to the game.

**[Download the latest release](https://github.com/DbDB68/maamaru-engine/releases/latest)** · **[User guide (Chinese)](docs/user-manual.md)** · [What's new in v0.6.1 (Chinese)](docs/releases/v0.6.1.md) · [Report an issue](https://github.com/DbDB68/maamaru-engine/issues)

> [!IMPORTANT]
> Maamaru currently supports the **Simplified Chinese client and the China server only**. The app itself is also currently in Simplified Chinese. This English README is here so that international players and developers can understand the project.

## Welcome Back to My Honmaru

![My Honmaru home screen in the washi theme: Kogitsunemaru and Konnosuke in the courtyard, a Saniwa profile, daily notes, and a wish list](docs/assets/v061-home-washi.png)

![The same Honmaru home screen in the pixel theme](docs/assets/v061-home-pixel.png)

This is a small place for a Saniwa to call their own: a profile and avatar, a secretary sword, quick notes, a trace of each day's work, and the swords and goals they are looking forward to. Kogitsunemaru and Konnosuke occasionally stop by the courtyard for a chat. Little by little, each day becomes part of your Honmaru's story. You can switch between the washi-paper and pixel themes at any time.

Before getting to work, come home and sit for a while.

## Choose How You Want to Use It

| What you want to do | Where to start | What Maamaru gives you |
|---|---|---|
| Run dailies, expeditions, sorties, or events | **Launch Maamaru** | Repetitive actions, live supervision, recovery from common problems, and a report when the job is done |
| Review resources, update records, or plan an event | **Open Ledger Only** | Reports, plans, journal entries, and Excel tools without connecting to the game at all |
| Quickly record resources, goals, and sword levels | **Android Offline Ledger** | A separate pocket ledger whose data stays on the phone |

The first two modes share the same ledger on your PC. The Android version is fully offline and does not currently sync with the desktop app.

## A Typical Day with Maamaru

**Choose a task → set the team, stop conditions, and resource permissions → start.**

While a task is running, the log keeps telling you what Maamaru is doing. Severe injuries, missing entry tokens, failed recognition, and network timeouts all have explicit stop and recovery rules. You do not need to supervise every click, but you always retain control over the goal, team composition, and acceptable risk.

For a routine of your own, use **Custom Workflows**. Dailies, expeditions, sorties, and events become building blocks that you can arrange in any order, name, save, and pin to the home screen. When the workflow is over, Maamaru can exit the game, close the emulator, or put the computer to sleep. Start one before bed, and Maamaru clocks out when the work is done.

![Custom Workflows turn routine tasks into reusable building blocks](docs/assets/v060-workflow-editor.png)

After a run, the report begins with what was accomplished and what happened recently. Dates, individual tasks, and resource sources stay one level deeper until you need to audit them. Maamaru attributes only changes it can verify; anything it cannot confirm remains explicitly unknown.

The bell in the top bar is the notification and incident center. If a script crashes, the watchdog has to terminate a run, or a one-click daily routine does not finish cleanly, it explains what happened, what may have caused it, and what you can do next. Repeated instances of the same issue increase a counter instead of flooding the screen.

## Plan an Event Before You Grind It

![Event planning for Iko: choose a map and daily play time to estimate runs, koban, and total time](docs/assets/v061-planning.png)

There is no need to guess how hard to grind an event. Choose a map and the amount of time you can spare each day, and Maamaru uses your measured run times to estimate how many runs you can complete, how much koban you should set aside, and how many hours the plan will take. You can save the result as a dedicated event budget so that it does not get mixed into everyday spending.

Entry costs, treasure-fragment drop rates, milestone rewards, and current bonus periods live on the same card. After each run, Maamaru reads the fragment inventory and records the difference, so the estimate gradually learns from your own Honmaru's results.

## Or Use It as a Standalone Ledger

![The desktop ledger with Excel import and export, preview, and automatic backups](docs/assets/v050-ledger-transfer.png)

**Open Ledger Only** never starts the emulator, ADB, MaaFramework, expedition scheduling, or game scripts. You can record income and spending, current balances, and manually played events; review trends and unusual days; set resource or event goals; and let Konnosuke estimate when you may reach them based on your recent pace.

Excel export includes the full transaction history, current balances, and daily summaries. Existing records can also be imported. Every import is previewed first, conflicts require confirmation, and Maamaru creates a backup before writing anything. Transactions verified by Maamaru can be exported, but an imported spreadsheet cannot rewrite them.

![The Android offline ledger: overview, transactions, journal, goals, and sword roster](docs/assets/v052-android-ledger.jpg)

The Android APK is an offline preview of this ledger. It can record resources, balances, events, goals, and each sword's level, Ranbu level, and notes. It contains no game automation and requests no network permission.

## Who Decides What

| The Saniwa decides | Maamaru handles |
|---|---|
| Today's goal, team, and formation rules | Repeating the agreed steps |
| When to stop for minor, moderate, or severe injuries | Reading injury states and blocking dangerous sorties |
| Whether to replenish passes, spend koban, or use items | Acting only within the permission given, and stopping when uncertain |
| Which swords may be repaired, dismantled, used for refinement, or deployed in an event | Enforcing protection lists without silently widening them |
| Which resource changes came from manual play | Keeping machine records and player notes separate instead of presenting guesses as facts |

## What Maamaru Can Do Today

- **Dailies and expeditions:** Combine login rewards, the daily shop visit, PvP practice, expeditions, internal affairs, forging, dismantling, refinement, mission rewards, inbox collection, and inventory snapshots into a one-click daily routine—or arrange them in any order with a custom workflow.
- **Sorties and events:** Normal battle maps, Chapter 1 of Iko, Underground Treasure Chest, Edo Castle Infiltration Investigation E4, Regiment Battle, and the Pumpkin event. Each mode keeps its own meaning for run counts, teams, injury rules, and spending.
- **Safety supervision:** Severe-injury blocking, injury-based stopping, repair-and-resume, troop replenishment, automatic captain rotation, interrupted-run recovery, a watchdog, and explicit end-of-run actions.
- **Reports:** Summaries of sorties, events, forging, drops, resource changes, and unusual days. A wish-list sword gets an extra notification when obtained; if the name cannot be read, Maamaru does not pretend otherwise.
- **Planning:** Estimates for Iko runs, play time, and koban based on measured pace; suggestions for where to obtain resources; and dedicated cards for forging shortages and Hakata koban spending.
- **Honmaru ledger:** Manual transactions, current balances, events, goals, history, Excel/CSV import and export, and backups. Automated and player-entered records are counted separately.
- **Errors in plain language:** Incident cards give a conclusion, likely causes, a next step, and a direct route back to the relevant task. A task that did not actually finish is never shown as a clean success.

Every task's detailed options, prerequisites, and stop conditions are documented in the [Maamaru user guide](docs/user-manual.md), currently available in Chinese.

## Download and Get Started

Download a package from [GitHub Releases](https://github.com/DbDB68/maamaru-engine/releases):

- `maamaru-setup-v*.exe`: Windows installer;
- `maamaru-launcher-v*.zip`: portable Windows package—extract it, then run `まあ丸启动器.exe`;
- `maamaru-ledger-demo-v*.apk`: Android offline ledger, with no connection to the game or desktop data.

> [!CAUTION]
> This is an independent fan project and is not affiliated with the game's developer, publisher, or operators. The normal steward mode automates interactions with the game and may violate its terms of service, resulting in account penalties, unintended actions, or data loss. The standalone ledger does not connect to the game. Decide for yourself whether to use automation, and test every new task with a short supervised run—especially after a game update.

> [!NOTE]
> **Maamaru is under active development.** Its primary test environment is MuMu Player 12 with the game at 1280×720. It has seen long-running use on a real account and installation by non-technical users, but a new map, another emulator, a different resolution, or a game UI update may still break visual recognition.

## Where Your Data Lives

- The installed version stores configuration, logs, reports, journal entries, plans, and backups in `%LOCALAPPDATA%\Maamaru`. Updating the app does not remove this data.
- The source version uses `%LOCALAPPDATA%\Maamaru-Dev` by default, keeping development records separate from the installed app's ledger.
- Reports do not store game screenshots. An exported feedback bundle contains the app version, a system summary, and text logs—not configuration files, secrets, inventory data, or the state database.
- Android data stays in the app's directory on the phone. There is currently no sync or export, and uninstalling the APK erases its preview data. Do not use it as the only copy of information you cannot recreate.

## Current Limits

- Edo Castle automation supports E4 only; other difficulties are not planned. Iko currently supports Chapter 1 only.
- When the game controls marching, it also controls routes and formations. Maamaru chooses forks and formations only in its manual-marching mode.
- The Pumpkin event automation never buys extra tokens. It stops safely when none remain.
- Retreating before a boss, reading fatigue, captain rotation by drag, and reconnecting after a dropped connection all depend on the actual screen. Maamaru stops instead of guessing when it cannot verify the state.
- Secretary chat and remote notifications through QQ or Telegram have not completed real-device validation by the maintainer and are not primary entry points.
- Emergency Stop terminates the task process immediately, so it cannot guarantee a final inventory check or a return to the Honmaru. Check the emulator screen before starting another task.

## What's Next

v0.6.0 introduced Custom Workflows and the My Honmaru home screen. v0.6.1 added event planning and Iko data cards. The project is now in an observation period: real cases of getting stuck, confusing people, producing mismatched records, or making correction difficult take priority over adding pages for the sake of a new version. Desktop–Android ledger sync will remain a recorded request until there is evidence that people use the mobile ledger regularly. See the [near-term roadmap](docs/product-roadmap.md) (Chinese).

## Reporting a Problem

If a task stops, visual recognition fails, or installation goes wrong, preserve the current emulator screen first. Then export a feedback bundle from the panel or launcher and open a [GitHub Issue](https://github.com/DbDB68/maamaru-engine/issues) with the version, task, and steps to reproduce.

<details>
<summary><strong>Running from source and project structure</strong></summary>

Requirements: Windows and Python 3.12+. Normal steward mode also requires MuMu Player and ADB.

```powershell
git clone https://github.com/DbDB68/maamaru-engine.git
cd maamaru-engine
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe maamaru_app.py
```

You can also double-click `启动源码版.cmd`. The panel opens at `http://127.0.0.1:8080` by default. Running the installed and source versions at the same time is not recommended.

Maamaru combines Python orchestration, ADB, MaaFramework, FastAPI, and Vue 3 with TypeScript. Program files and user data are kept strictly separate. Migration from an old data directory copies, backs up, and verifies data before use; it never deletes the source automatically. See [User Data and Migration](docs/data-layout.md) and [Structured Runtime Data](docs/telemetry-data.md) for the detailed contracts (Chinese).

```text
maamaru-engine/
├─ launcher/            Launcher, updates, and data migration
├─ panel/               FastAPI backend and Vue Honmaru panel
├─ ledger_app/          Standalone ledger and Android offline edition
├─ touken/flows/        Dailies, sorties, events, expeditions, and recovery
├─ resource/base/       OCR, models, and recognition templates
├─ profiles/            Event runtime configuration
└─ docs/                User guide, release notes, and developer documentation
```

</details>

## Acknowledgements

Maamaru uses [MaaFramework](https://github.com/MaaXYZ/MaaFramework) for visual recognition and is built with open-source projects including [FastAPI](https://github.com/tiangolo/fastapi), [Vue](https://github.com/vuejs/core), [Vite](https://github.com/vitejs/vite), [pywebview](https://github.com/r0x0r/pywebview), [Fusion Pixel](https://github.com/TakWolf/fusion-pixel-font), and [Kenney Game Icons](https://kenney.nl/assets/game-icons). See [NOTICE](NOTICE) for complete license information.

Maamaru itself is also a collaboration between a human and AI. The human brings real use cases, defines gameplay rules and safety boundaries, chooses among proposed solutions, and validates them on a real device. Kimi Code K3, Codex, and WorkBuddy collaborate on implementation, debugging, testing, and releases.

Maamaru is open source under the [AGPL-3.0-or-later](LICENSE) license.

<details>
<summary>Repository easter egg: MCS (Multi-Cow System) 🐂🌙</summary>

We jokingly call our multi-agent workflow the MCS: the frontend cow, automation cow, outsourced-IT cow, and README cow each take a part of the job, while the human carries context between them, makes the decisions, and signs off on the result. Why cows? Codex's desktop pet is named **NULL**, which sounds a lot like the Chinese word for cow when you say it quickly.

### The Scripture Forged Beneath the Moon `🌙`

> _This sacred text was not wrought by one hand alone. In faithful observance of the ancient art of vibe coding, we hereby record every fellow cultivator's contribution at its source._

In ancient times, Moonshot AI sent Kimi K3 down from the heavens to forge the backend. Then came GPT-5.6 of the High Heavens to preside over the frontend. WorkBuddy DeepSeek V4 offered one final touch of enlightenment, and thus the *Maamaru Sutra* was complete.

> _This Honmaru follows the Great Python, with Java as its aide. If there are bugs, such is the Mandate of Heaven; if there are none, all credit belongs to our fellow cultivators._

</details>
