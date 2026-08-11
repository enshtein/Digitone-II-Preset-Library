# Digitone II Preset Library

A cross-platform terminal app for browsing a collection of Digitone II presets
organized into banks A–H. It helps you find duplicate presets, browse tags, and
see which sound packs your presets came from. The app works with exported preset
files and does not connect to the Digitone II hardware.

## Requirements

- Python 3.10 or newer
- A folder containing bank folders named `A` through `H`
- A folder containing your sound-pack collection

No additional packages are required on macOS or Linux. On Windows, the launcher
automatically installs the small `windows-curses` terminal dependency the first
time it runs, so an internet connection is required for that first launch.

## Start the app

Use the launcher for your operating system:

- **macOS:** `Start Digitone II Preset Library (macOS).command`
- **Linux:** `Start Digitone II Preset Library (Linux).sh`
- **Windows:** `Start Digitone II Preset Library (Windows).bat`

On macOS or Linux, you can also run:

```bash
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

The main menu is always shown at the bottom of the screen:

`BANKS` · `SOUND PACKS` · `TAGS` · `STATISTICS` · `SETTINGS` · `EXIT`

- Click a menu item with the mouse; or
- Press `Tab`, select an item with `←` and `→`, then press `Enter`.

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

Browse every preset in banks A–H, see its tags and source sound pack, filter the
list by tag or match status, and spot duplicates highlighted in red.

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
