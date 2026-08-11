"""Textual user interface for Digitone II Preset Library."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Grid, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    ContentSwitcher,
    DataTable,
    DirectoryTree,
    Footer,
    Header,
    Input,
    Label,
    Static,
    Switch,
    Tab,
    Tabs,
)


class FolderPicker(ModalScreen[Path | None]):
    """A cross-platform folder picker with tree and direct path entry."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str, initial: Path | None) -> None:
        super().__init__()
        self.picker_title = title
        self.selected = initial if initial and initial.is_dir() else Path.home()
        anchor = Path(self.selected.anchor) if self.selected.anchor else Path.home()
        self.tree_root = anchor if anchor.is_dir() else Path.home()

    def compose(self) -> ComposeResult:
        with Vertical(id="folder-dialog"):
            yield Label(self.picker_title, id="folder-title")
            yield Input(str(self.selected), id="folder-path")
            yield DirectoryTree(str(self.tree_root), id="folder-tree")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Use This Folder", variant="primary", id="folder-use")
                yield Button("Cancel", id="folder-cancel")

    @on(DirectoryTree.DirectorySelected)
    def directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        self.selected = event.path
        self.query_one("#folder-path", Input).value = str(event.path)

    @on(Button.Pressed, "#folder-use")
    def use_folder(self) -> None:
        candidate = Path(self.query_one("#folder-path", Input).value).expanduser()
        if candidate.is_dir():
            self.dismiss(candidate)
        else:
            self.notify("That folder does not exist.", severity="error")

    @on(Button.Pressed, "#folder-cancel")
    def cancel_button(self) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmMove(ModalScreen[bool]):
    """Confirm a preset redistribution plan."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, plan: Any) -> None:
        super().__init__()
        self.plan = plan

    def compose(self) -> ComposeResult:
        after = self.plan.after_counts
        counts = "   ".join(
            f"{bank}: {self.plan.before_counts[bank]} → {after[bank]}"
            for bank in "ABCDEFGH"
        )
        with Vertical(id="confirm-dialog"):
            yield Label("Redistribution Plan", classes="dialog-title")
            yield Static(
                f"Presets to move: {len(self.plan.moves)}\n\n{counts}\n\n"
                "Files will not be overwritten. Continue?"
            )
            with Horizontal(classes="dialog-buttons"):
                yield Button("Move Presets", variant="error", id="confirm-move")
                yield Button("Cancel", variant="primary", id="confirm-cancel")

    @on(Button.Pressed, "#confirm-move")
    def confirm(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#confirm-cancel")
    def cancel_button(self) -> None:
        self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)


class BankSetupInfo(ModalScreen[None]):
    """Explain how to export presets after creating bank folders."""

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, root: Path, created: list[str]) -> None:
        super().__init__()
        self.root = root
        self.created = created

    def compose(self) -> ComposeResult:
        folders = ", ".join(self.created)
        with Vertical(id="setup-dialog"):
            yield Label("Bank Folders Are Ready", classes="dialog-title")
            yield Static(
                f"The missing bank folders ({folders}) were created in:\n"
                f"{self.root}\n\n"
                "For the library to display your Digitone II presets:\n\n"
                "1. Download and install the official Elektron Transfer application.\n"
                "2. Connect your Digitone II and open Elektron Transfer.\n"
                "3. Export the presets from every Digitone II bank into the matching "
                "A–H folder created here."
            )
            with Horizontal(classes="dialog-buttons"):
                yield Button("Got It", variant="primary", id="setup-close")

    @on(Button.Pressed, "#setup-close")
    def close_button(self) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class PresetLibraryApp(App[None]):
    """Modern terminal UI backed by the existing preset-library engine."""

    TITLE = "Digitone II Preset Library"
    SUB_TITLE = "Browse banks, sound packs, tags, and duplicates"

    CSS = """
    Screen { background: #07110d; color: #d8e9df; }
    Header { background: #087f8c; color: white; }
    Tabs { dock: top; background: #0b1c15; }
    Tab { padding: 0 2; }
    Tab.-active { background: #18a558; color: #07110d; text-style: bold; }
    #bank-tabs { height: 3; dock: top; background: #0d2118; }
    #bank-tabs Tab { width: 7; padding: 0 1; text-align: center; }
    ContentSwitcher { height: 1fr; }
    .view { height: 1fr; padding: 1; }
    .toolbar { height: 3; align-vertical: middle; }
    .toolbar Label { width: auto; margin-right: 1; }
    .toolbar Switch { margin-right: 1; }
    DataTable { height: 1fr; border: round #216e4e; }
    #packs-layout { height: 1fr; }
    #packs-table { width: 1fr; }
    #pack-details { width: 1fr; border: round #216e4e; padding: 1 2; }
    #settings-panel { width: 100%; max-width: 110; height: auto; padding: 1 2; border: round #18a558; }
    .setting-row { height: 5; align-vertical: middle; }
    .setting-label { width: 18; text-style: bold; }
    .setting-path { width: 1fr; border: round #216e4e; padding: 0 1; }
    .setting-row Button { width: 16; margin-left: 1; }
    #status { dock: bottom; height: 1; padding: 0 1; background: #0b1c15; color: #63d68b; }
    Footer { background: #10251b; }
    FolderPicker, ConfirmMove { align: center middle; background: rgba(0, 0, 0, 0.65); }
    #folder-dialog { width: 85%; height: 85%; padding: 1 2; border: thick #18a558; background: #10251b; }
    #folder-title, .dialog-title { height: 2; text-style: bold; text-align: center; }
    #folder-path { margin-bottom: 1; }
    #folder-tree { height: 1fr; border: round #216e4e; }
    #confirm-dialog { width: 80; height: auto; padding: 1 2; border: thick #18a558; background: #10251b; }
    #setup-dialog { width: 86; height: auto; padding: 1 2; border: thick #18a558; background: #10251b; }
    .dialog-buttons { height: 3; align-horizontal: center; margin-top: 1; }
    .dialog-buttons Button { margin: 0 1; }
    """

    BINDINGS = [
        ("p", "show('packs')", "Sound Packs"),
        ("g", "show('tags')", "Tags"),
        ("s", "show('stats')", "Statistics"),
        ("o", "show('settings')", "Settings"),
        ("r", "rescan", "Scan Again"),
        ("e", "export", "Export Report"),
        ("q", "quit", "Exit"),
    ]

    def __init__(
        self,
        settings: Any,
        report_path: Path,
        *,
        scan: Callable[..., Any],
        save_settings: Callable[[Any], None],
        export_report: Callable[[Any, Path], None],
        build_move_plan: Callable[[Any], Any],
        execute_move_plan: Callable[[Any], None],
        banks: tuple[str, ...],
    ) -> None:
        super().__init__()
        self.settings = settings
        self.report_path = report_path
        self.scan_engine = scan
        self.save_settings_engine = save_settings
        self.export_engine = export_report
        self.build_plan_engine = build_move_plan
        self.execute_plan_engine = execute_move_plan
        self.banks = banks
        self.result: Any | None = None
        self.current_bank = banks[0]
        self.pack_rows: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Tabs(
            Tab("Banks", id="tab-banks"),
            Tab("Sound Packs", id="tab-packs"),
            Tab("Tags", id="tab-tags"),
            Tab("Statistics", id="tab-stats"),
            Tab("Settings", id="tab-settings"),
            id="navigation",
        )
        with ContentSwitcher(initial="view-banks", id="content"):
            with Vertical(id="view-banks", classes="view"):
                yield Tabs(
                    *(Tab(bank, id=f"bank-{bank}") for bank in self.banks),
                    active=f"bank-{self.current_bank}",
                    id="bank-tabs",
                )
                yield DataTable(id="banks-table", cursor_type="row", zebra_stripes=True)
            with Vertical(id="view-packs", classes="view"):
                with Horizontal(classes="toolbar"):
                    yield Label("Show only packs with no matches")
                    yield Switch(False, id="empty-packs")
                with Horizontal(id="packs-layout"):
                    yield DataTable(id="packs-table", cursor_type="row", zebra_stripes=True)
                    yield Static("Select a sound pack to view details.", id="pack-details")
            with Vertical(id="view-tags", classes="view"):
                yield DataTable(id="tags-table", cursor_type="row", zebra_stripes=True)
            with Vertical(id="view-stats", classes="view"):
                yield DataTable(id="stats-table", cursor_type="row")
                yield Button("Review Redistribution Plan", variant="warning", id="move-plan")
            with Vertical(id="view-settings", classes="view"):
                with Vertical(id="settings-panel"):
                    yield Label("Collection Folders", classes="dialog-title")
                    with Horizontal(classes="setting-row"):
                        yield Label("Banks A–H", classes="setting-label")
                        yield Static("Not set", id="banks-path", classes="setting-path")
                        yield Button("Browse…", id="browse-banks")
                    with Horizontal(classes="setting-row"):
                        yield Label("Sound Packs", classes="setting-label")
                        yield Static("Not set", id="packs-path", classes="setting-path")
                        yield Button("Browse…", id="browse-packs")
                    yield Static("Choose both folders before opening the library.", id="settings-help")
        yield Static("Ready", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.update_settings_view()
        if self.settings_complete():
            self.scan_data()
        else:
            self.show_view("settings")
            self.lock_navigation(True)
            self.set_status("Select both collection folders to continue.")

    def settings_complete(self) -> bool:
        return all(path is not None and path.is_dir() for path in (self.settings.backup, self.settings.packs))

    def lock_navigation(self, locked: bool) -> None:
        for tab_id in ("tab-banks", "tab-packs", "tab-tags", "tab-stats"):
            self.query_one(f"#{tab_id}", Tab).disabled = locked

    def set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def show_view(self, name: str) -> None:
        if not self.settings_complete() and name != "settings":
            self.notify("Select both folders in Settings first.", severity="warning")
            name = "settings"
        self.query_one("#content", ContentSwitcher).current = f"view-{name}"
        self.query_one("#navigation", Tabs).active = f"tab-{name}"

    def action_show(self, name: str) -> None:
        self.show_view(name)

    @on(Tabs.TabActivated, "#navigation")
    def tab_activated(self, event: Tabs.TabActivated) -> None:
        if event.tab and event.tab.id:
            self.show_view(event.tab.id.removeprefix("tab-"))

    @work(thread=True, exclusive=True, group="scan")
    def scan_data(self) -> None:
        if not self.settings_complete():
            return
        self.call_from_thread(self.set_status, "Scanning preset banks and sound packs…")
        try:
            result = self.scan_engine(
                self.settings.backup,
                self.settings.packs,
                lambda message: self.call_from_thread(self.set_status, message),
            )
        except Exception as exc:
            self.call_from_thread(self.scan_failed, str(exc))
            return
        self.call_from_thread(self.apply_result, result)

    def scan_failed(self, message: str) -> None:
        self.set_status(f"Scan failed: {message}")
        self.notify(message, title="Scan failed", severity="error")

    def apply_result(self, result: Any) -> None:
        self.result = result
        self.populate_banks()
        self.populate_packs()
        self.populate_tags()
        self.populate_stats()
        total = sum(len(rows) for rows in result.banks.values())
        self.set_status(f"Scan complete · {total} presets · {result.pack_count} sound packs · {result.pack_preset_count} pack files")

    def clear_table(self, table_id: str, columns: tuple[str, ...]) -> DataTable:
        table = self.query_one(table_id, DataTable)
        table.clear(columns=True)
        table.add_columns(*columns)
        return table

    def populate_banks(self) -> None:
        if self.result is None:
            return
        table = self.clear_table("#banks-table", ("Slot", "Preset", "Sound Pack(s)", "Tags"))
        for row in self.result.banks[self.current_bank]:
            packs = ", ".join(row.exact_packs or row.name_only_packs) or "—"
            name = Text(row.parsed.display_name, style="bold red" if row.duplicate_locations else "")
            table.add_row(f"{row.slot:03d}", name, packs, ", ".join(row.parsed.tags) or "—")

    @on(Tabs.TabActivated, "#bank-tabs")
    def bank_changed(self, event: Tabs.TabActivated) -> None:
        if event.tab and event.tab.id:
            self.current_bank = event.tab.id.removeprefix("bank-")
            self.populate_banks()

    def populate_packs(self) -> None:
        if self.result is None:
            return
        table = self.clear_table("#packs-table", ("Sound Pack", "Found", "Total"))
        only_empty = self.query_one("#empty-packs", Switch).value
        self.pack_rows = []
        for pack in sorted(self.result.pack_file_counts, key=str.casefold):
            found = self.result.pack_match_counts[pack][0]
            if only_empty and found:
                continue
            self.pack_rows.append(pack)
            table.add_row(pack, found, self.result.pack_file_counts[pack], key=pack)

    @on(Switch.Changed, "#empty-packs")
    def empty_packs_changed(self) -> None:
        self.populate_packs()

    @on(DataTable.RowHighlighted, "#packs-table")
    def pack_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self.result is None:
            return
        pack = str(event.row_key.value)
        details = self.result.pack_details.get(pack)
        if details is None:
            return
        tags = "\n".join(f"  {tag}: {count}" for tag, count in sorted(details.tag_counts.items(), key=lambda item: (-item[1], item[0].casefold()))) or "  —"
        matches = details.bank_matches + details.name_only_matches
        positions = "\n".join(f"  {row.bank}{row.slot:03d}  {row.parsed.display_name}" for row in matches) or "  —"
        self.query_one("#pack-details", Static).update(
            f"[b]{pack}[/b]\n\nPresets in pack: {details.preset_count}\nFound in banks: {len(matches)}\n\n[b]Tags[/b]\n{tags}\n\n[b]Bank positions[/b]\n{positions}"
        )

    def populate_tags(self) -> None:
        if self.result is None:
            return
        from collections import Counter
        counts = Counter(tag for rows in self.result.banks.values() for row in rows for tag in row.parsed.tags)
        table = self.clear_table("#tags-table", ("Tag", "Presets"))
        for tag in sorted(counts, key=lambda value: (-counts[value], value.casefold())):
            table.add_row(tag, counts[tag])

    def populate_stats(self) -> None:
        if self.result is None:
            return
        table = self.clear_table("#stats-table", ("Bank", "Presets", "Capacity", "Status"))
        total = 0
        for bank in self.banks:
            count = len(self.result.banks[bank])
            total += count
            status = "Available" if count < 256 else ("Full" if count == 256 else "Over capacity")
            style = "red" if count > 256 else ("yellow" if count == 256 else "green")
            table.add_row(f"Bank {bank}", count, "256", Text(status, style=style))
        table.add_row("TOTAL", total, 256 * len(self.banks), "")

    def update_settings_view(self) -> None:
        self.query_one("#banks-path", Static).update(str(self.settings.backup) if self.settings.backup else "Not set")
        self.query_one("#packs-path", Static).update(str(self.settings.packs) if self.settings.packs else "Not set")

    @on(Button.Pressed, "#browse-banks")
    def browse_banks(self) -> None:
        self.push_screen(FolderPicker("Select the folder containing banks A–H", self.settings.backup), lambda path: self.folder_selected("backup", path))

    @on(Button.Pressed, "#browse-packs")
    def browse_packs(self) -> None:
        self.push_screen(FolderPicker("Select the sound-packs folder", self.settings.packs), lambda path: self.folder_selected("packs", path))

    def folder_selected(self, field: str, path: Path | None) -> None:
        if path is None:
            return
        created: list[str] = []
        if field == "backup":
            try:
                for bank in self.banks:
                    bank_folder = path / bank
                    if not bank_folder.exists():
                        bank_folder.mkdir()
                        created.append(bank)
                    elif not bank_folder.is_dir():
                        raise NotADirectoryError(f"{bank_folder} exists but is not a folder")
            except OSError as exc:
                self.notify(str(exc), title="Could not create bank folders", severity="error")
                return
        settings_type = type(self.settings)
        self.settings = settings_type(
            backup=path if field == "backup" else self.settings.backup,
            packs=path if field == "packs" else self.settings.packs,
        )
        try:
            self.save_settings_engine(self.settings)
        except OSError as exc:
            self.notify(str(exc), title="Could not save settings", severity="error")
            return
        self.update_settings_view()
        if created:
            self.push_screen(BankSetupInfo(path, created))
        if self.settings_complete():
            self.lock_navigation(False)
            self.notify("Settings saved. Scanning the collection…", severity="information")
            self.scan_data()

    def action_rescan(self) -> None:
        if self.settings_complete():
            self.scan_data()

    def action_export(self) -> None:
        if self.result is None:
            self.notify("Scan the collection before exporting a report.", severity="warning")
            return
        try:
            self.export_engine(self.result, self.report_path)
        except OSError as exc:
            self.notify(str(exc), title="Export failed", severity="error")
        else:
            self.notify(f"Report saved to {self.report_path}")

    @on(Button.Pressed, "#move-plan")
    def review_move_plan(self) -> None:
        if self.result is None:
            return
        try:
            plan = self.build_plan_engine(self.result)
        except (OSError, ValueError) as exc:
            self.notify(str(exc), severity="error")
            return
        if not plan.moves:
            self.notify("No banks are over capacity.")
            return
        self.push_screen(ConfirmMove(plan), lambda confirmed: self.perform_move(plan) if confirmed else None)

    @work(thread=True, exclusive=True, group="move")
    def perform_move(self, plan: Any) -> None:
        self.call_from_thread(self.set_status, f"Moving and verifying {len(plan.moves)} presets…")
        try:
            self.execute_plan_engine(plan)
        except Exception as exc:
            self.call_from_thread(self.scan_failed, str(exc))
            return
        self.call_from_thread(self.notify, "Preset redistribution completed.")
        self.call_from_thread(self.scan_data)


def run_textual_ui(
    settings: Any,
    report_path: Path,
    *,
    scan: Callable[..., Any],
    save_settings: Callable[[Any], None],
    export_report: Callable[[Any, Path], None],
    build_move_plan: Callable[[Any], Any],
    execute_move_plan: Callable[[Any], None],
    banks: tuple[str, ...],
) -> None:
    PresetLibraryApp(
        settings,
        report_path,
        scan=scan,
        save_settings=save_settings,
        export_report=export_report,
        build_move_plan=build_move_plan,
        execute_move_plan=execute_move_plan,
        banks=banks,
    ).run()
