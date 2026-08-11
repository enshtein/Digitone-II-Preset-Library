# Digitone II Preset Library

A cross-platform terminal app for browsing a collection of Digitone II presets
organized into banks A–H. It helps you find duplicate presets, browse tags, and
see which sound packs your presets came from. The app works with exported preset
files and does not connect to the Digitone II hardware.

## Download

Standalone builds are available from the repository's **Releases** page:

- Windows x64: `.exe`
- macOS Apple Silicon: `.tar.gz`
- macOS Intel: `.tar.gz`
- Linux x86_64: `.tar.gz`

These builds include Python and all required packages. Users do not need to
install Python or Textual.

## Requirements

- Python 3.10 or newer
- A folder containing bank folders named `A` through `H`
- A folder containing your sound-pack collection

The app uses the Textual framework for its terminal interface. Each launcher
creates a private `.venv` environment and installs the required packages
automatically. An internet connection is required the first time you launch it.

## Start the app

If you downloaded a standalone release, extract it if necessary and run the
`Digitone II Preset Library` application. The launchers below are intended for
people running directly from the source code.

Use the launcher for your operating system:

- **macOS:** `Start Digitone II Preset Library (macOS).command`
- **Linux:** `Start Digitone II Preset Library (Linux).sh`
- **Windows:** `Start Digitone II Preset Library (Windows).bat`

To run the app manually, create an environment and install the dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 digitone_preset_library.py
```

## First launch

The app asks you to select two folders before scanning:

1. **Banks A–H** — the folder that contains your `A`, `B`, `C`, … `H` bank folders.
2. **Sound packs** — the folder that contains your sound-pack collection.

Both selections are saved automatically. You can change them later from
**Settings**. If a saved folder is no longer available, the app opens Settings
and asks you to select a valid folder before continuing.

## Navigation

The main navigation bar is always shown at the top of the screen:

`BANKS` · `SOUND PACKS` · `TAGS` · `STATISTICS` · `SETTINGS` · `EXIT`

- Click a tab with the mouse; or
- Press `Tab` to focus the navigation bar and select a tab with the arrow keys.

Tables support mouse selection, arrow-key navigation, and scrolling. Available
keyboard commands are shown in the footer at the bottom of the screen.

Keyboard shortcuts are also available:

- `P` — Sound Packs
- `G` — Tags
- `S` — Statistics
- `O` — Settings
- `E` — export a text report
- `R` — scan the folders again
- `Q` — exit

Within lists, use `↑` and `↓` to move, and `Page Up` / `Page Down` to scroll.

## What you can view

### Banks

Switch directly between banks using the permanent horizontal `A`–`H` tabs.
Browse every preset, see its tags and source sound pack, and spot duplicates
highlighted in red.

### Sound Packs

See how many presets from each sound pack are present in your banks. Select a
sound pack to view its tags and matching bank positions. Press `Z` to show only
sound packs with no presets found in the banks.

### Tags

View all tags found in your preset collection and the number of presets using
each tag.

### Statistics

View bank capacity at a glance. Each bank can contain up to 256 presets. If a
bank exceeds that limit, press `M` to review a redistribution plan. Files are
not moved until you explicitly select **MOVE** and confirm.

### Settings

Change the Banks A–H folder or Sound Packs folder. Select a row and press
`Enter` to choose a new folder. The new path is saved automatically and the
collection is scanned again.

## Command-line options

You can temporarily override the saved folders:

```bash
python3 digitone_preset_library.py \
  --backup "/path/to/banks" \
  --packs "/path/to/sound-packs"
```

To create a report without opening the interface:

```bash
python3 digitone_preset_library.py --no-ui --report report.txt
```
