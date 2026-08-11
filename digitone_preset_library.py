#!/usr/bin/env python3
"""Browse and analyze Digitone II preset banks and sound-pack sources."""

from __future__ import annotations

import argparse
import curses
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable


APP_NAME = "Digitone II Preset Library"
LEGACY_APP_NAME = "Digitone Sound Pack Checker"
BANKS = tuple("ABCDEFGH")
PRESET_SUFFIXES = frozenset((".dn2pst", ".dnsnd"))
SLOT_PREFIX = re.compile(r"^[A-H]\d{3}\s+", re.IGNORECASE)


@dataclass(frozen=True)
class Settings:
    backup: Path | None = None
    packs: Path | None = None


def app_settings_path(app_name: str, linux_directory: str) -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_name / "settings.json"
    if sys.platform == "win32":
        config_home = Path(
            os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")
        )
        return config_home / app_name / "settings.json"
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / linux_directory / "settings.json"


def settings_path() -> Path:
    return app_settings_path(APP_NAME, "digitone-ii-preset-library")


def legacy_settings_path() -> Path:
    return app_settings_path(LEGACY_APP_NAME, "digitone-sound-pack-checker")


def load_settings() -> Settings:
    destination = settings_path()
    source = destination if destination.exists() else legacy_settings_path()
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
        backup = data.get("backup")
        packs = data.get("packs")
        settings = Settings(
            backup=Path(backup).expanduser() if isinstance(backup, str) and backup else None,
            packs=Path(packs).expanduser() if isinstance(packs, str) and packs else None,
        )
        if source != destination:
            try:
                save_settings(settings)
            except OSError:
                pass
        return settings
    except (OSError, ValueError, TypeError):
        return Settings()


def save_settings(settings: Settings) -> None:
    destination = settings_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "backup": str(settings.backup) if settings.backup else None,
                "packs": str(settings.packs) if settings.packs else None,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


@dataclass(frozen=True)
class ParsedPreset:
    path: Path
    display_name: str
    normalized_name: str
    fingerprint: str | None
    error: str | None = None
    tags: tuple[str, ...] = ()


@dataclass
class BackupPreset:
    bank: str
    slot: int
    parsed: ParsedPreset
    exact_packs: list[str] = field(default_factory=list)
    name_only_packs: list[str] = field(default_factory=list)
    duplicate_locations: list[str] = field(default_factory=list)


@dataclass
class PackDetails:
    preset_count: int
    tag_counts: dict[str, int]
    bank_matches: list[BackupPreset]
    name_only_matches: list[BackupPreset]


@dataclass
class ScanResult:
    banks: dict[str, list[BackupPreset]]
    pack_count: int
    pack_preset_count: int
    pack_file_counts: dict[str, int]
    pack_match_counts: dict[str, tuple[int, int, int]]
    errors: list[str]
    pack_details: dict[str, PackDetails] = field(default_factory=dict)


@dataclass(frozen=True)
class PresetMove:
    source: Path
    destination: Path
    source_bank: str
    destination_bank: str


@dataclass
class MovePlan:
    moves: list[PresetMove]
    before_counts: dict[str, int]

    @property
    def by_route(self) -> dict[tuple[str, str], int]:
        counts: Counter[tuple[str, str]] = Counter(
            (move.source_bank, move.destination_bank) for move in self.moves
        )
        return dict(counts)

    @property
    def after_counts(self) -> dict[str, int]:
        counts = dict(self.before_counts)
        for move in self.moves:
            counts[move.source_bank] -= 1
            counts[move.destination_bank] += 1
        return counts


def build_move_plan(result: ScanResult) -> MovePlan:
    """Plan redistribution by filling each destination bank to 256 in order."""
    before = {bank: len(result.banks[bank]) for bank in BANKS}
    overflow_rows = [
        row
        for bank in BANKS
        for row in result.banks[bank][256:]
    ]
    available = sum(max(0, 256 - before[bank]) for bank in BANKS)
    if len(overflow_rows) > available:
        raise ValueError(
            f"Не хватает свободных мест: нужно {len(overflow_rows)}, доступно {available}"
        )

    projected = dict(before)
    moves: list[PresetMove] = []
    for row in overflow_rows:
        candidates = [bank for bank in BANKS if projected[bank] < 256]
        if not candidates:
            raise ValueError("Не найден банк со свободным местом")
        destination_bank = candidates[0]
        destination = (
            row.parsed.path.parents[1] / destination_bank / row.parsed.path.name
        )
        moves.append(
            PresetMove(row.parsed.path, destination, row.bank, destination_bank)
        )
        projected[destination_bank] += 1
        projected[row.bank] -= 1
    return MovePlan(moves, before)


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def execute_move_plan(plan: MovePlan) -> None:
    """Copy, verify, then remove sources; never overwrite an existing file."""
    if not plan.moves:
        return
    roots = {move.source.parents[1] for move in plan.moves}
    if len(roots) != 1:
        raise ValueError("Все банки должны находиться в одной корневой папке")
    root = roots.pop()
    current_counts = {
        bank: sum(
            1 for path in (root / bank).glob("*")
            if path.is_file() and path.suffix.casefold() == ".dn2pst"
        )
        for bank in BANKS
    }
    if current_counts != plan.before_counts:
        raise RuntimeError("Содержимое банков изменилось после создания плана; пересканируйте")
    for move in plan.moves:
        if not move.source.is_file():
            raise RuntimeError(f"Исходный файл не найден: {move.source.name}")
        if move.destination.exists():
            raise FileExistsError(f"Целевой файл уже существует: {move.destination.name}")

    total_before = sum(current_counts.values())
    created: list[PresetMove] = []
    removed: list[PresetMove] = []
    try:
        # Exclusive creation ('xb') makes overwriting an existing preset impossible.
        for move in plan.moves:
            with move.source.open("rb") as source, move.destination.open("xb") as target:
                # Track the destination immediately, including a partial copy if
                # reading or writing fails, so rollback always removes it.
                created.append(move)
                shutil.copyfileobj(source, target, length=1024 * 1024)
            shutil.copystat(move.source, move.destination)
            if file_digest(move.source) != file_digest(move.destination):
                raise OSError(f"Проверка копии не пройдена: {move.source.name}")

        # Sources are removed only after every destination copy has been verified.
        for move in plan.moves:
            move.source.unlink()
            removed.append(move)

        after = plan.after_counts
        actual_after = {
            bank: sum(
                1 for path in (root / bank).glob("*")
                if path.is_file() and path.suffix.casefold() == ".dn2pst"
            )
            for bank in BANKS
        }
        if actual_after != after or sum(actual_after.values()) != total_before:
            raise RuntimeError("Итоговая проверка количества файлов не пройдена")
        if any(count > 256 for count in actual_after.values()):
            raise RuntimeError("После переноса один из банков всё ещё переполнен")
    except Exception as exc:
        rollback_errors: list[str] = []
        removed_sources = {move.source for move in removed}
        for move in reversed(created):
            try:
                if move.source in removed_sources and not move.source.exists():
                    move.destination.replace(move.source)
                elif move.destination.exists():
                    move.destination.unlink()
            except OSError as rollback_exc:
                rollback_errors.append(f"{move.source.name}: {rollback_exc}")
        if rollback_errors:
            raise RuntimeError(
                f"{exc}; ошибка восстановления: {'; '.join(rollback_errors)}"
            ) from exc
        raise


def normalized_stem(path: Path) -> str:
    """Normalize a preset filename while ignoring an exported bank/slot prefix."""
    name = SLOT_PREFIX.sub("", path.stem).strip()
    return " ".join(name.casefold().split())


def parse_preset(path: Path) -> ParsedPreset:
    """Read the actual sound payload from a .dn2pst ZIP and fingerprint it."""
    display = SLOT_PREFIX.sub("", path.stem).strip() or path.stem
    normalized = normalized_stem(path)
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            payload_name = manifest.get("Payload")
            if not isinstance(payload_name, str) or not payload_name:
                raise ValueError("manifest.json has no Payload")
            meta = manifest.get("MetaInfo", {})
            raw_tags = meta.get("Tags", []) if isinstance(meta, dict) else []
            tags = tuple(
                dict.fromkeys(
                    tag.strip() for tag in raw_tags
                    if isinstance(tag, str) and tag.strip()
                )
            ) if isinstance(raw_tags, list) else ()
            payload = archive.read(payload_name)
        return ParsedPreset(
            path, display, normalized, hashlib.sha256(payload).hexdigest(), tags=tags
        )
    except (OSError, KeyError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        return ParsedPreset(path, display, normalized, None, str(exc))


def preset_files(root: Path) -> Iterable[Path]:
    # Digitone II packs use .dn2pst; many compatible/older Digitone packs use
    # .dnsnd. Both are Elektron ZIP containers with a manifest and payload.
    return (p for p in root.rglob("*") if p.is_file() and p.suffix.casefold() in PRESET_SUFFIXES)


def pack_name(packs_root: Path, preset: Path) -> str:
    try:
        return preset.relative_to(packs_root).parts[0]
    except (ValueError, IndexError):
        return preset.parent.name


def mark_duplicates(banks: dict[str, list[BackupPreset]]) -> None:
    rows_by_hash: dict[str, list[BackupPreset]] = defaultdict(list)
    for rows in banks.values():
        for row in rows:
            if row.parsed.fingerprint:
                rows_by_hash[row.parsed.fingerprint].append(row)
    for rows in banks.values():
        for row in rows:
            matches = rows_by_hash.get(row.parsed.fingerprint, []) if row.parsed.fingerprint else []
            row.duplicate_locations = [
                f"{other.bank}{other.slot:03d}" for other in matches if other is not row
            ]


def scan(
    backup_root: Path,
    packs_root: Path,
    progress: Callable[[str], None] | None = None,
) -> ScanResult:
    """Scan only the eight top-level bank folders; ignore VER2/OVERFLOW."""
    progress = progress or (lambda _: None)
    errors: list[str] = []
    by_hash: dict[str, set[str]] = defaultdict(set)
    by_name: dict[str, set[str]] = defaultdict(set)
    # Every immediate child directory represents one sound pack, including a
    # pack that currently contains only docs/archives and no unpacked presets.
    pack_dirs = {p.name for p in packs_root.iterdir() if p.is_dir()}
    pack_file_counts = {name: 0 for name in pack_dirs}
    pack_presets: dict[str, list[ParsedPreset]] = defaultdict(list)
    pack_files = sorted(preset_files(packs_root), key=lambda p: str(p).casefold())

    total = len(pack_files)
    for index, path in enumerate(pack_files, 1):
        pack = pack_name(packs_root, path)
        pack_file_counts[pack] = pack_file_counts.get(pack, 0) + 1
        parsed = parse_preset(path)
        pack_presets[pack].append(parsed)
        if parsed.fingerprint:
            by_hash[parsed.fingerprint].add(pack)
        else:
            errors.append(f"{path}: {parsed.error}")
        by_name[parsed.normalized_name].add(pack)
        if index == 1 or index % 50 == 0 or index == total:
            progress(f"Sound Packs: {index}/{total}")

    banks: dict[str, list[BackupPreset]] = {}
    for bank in BANKS:
        folder = backup_root / bank
        paths = sorted(
            (p for p in folder.glob("*") if p.is_file() and p.suffix.casefold() == ".dn2pst"),
            key=lambda p: p.name.casefold(),
        ) if folder.is_dir() else []
        rows: list[BackupPreset] = []
        for slot, path in enumerate(paths, 1):
            parsed = parse_preset(path)
            exact = set(by_hash.get(parsed.fingerprint, ())) if parsed.fingerprint else set()
            same_name = set(by_name.get(parsed.normalized_name, ())) - exact
            if parsed.error:
                errors.append(f"{path}: {parsed.error}")
            rows.append(BackupPreset(bank, slot, parsed, sorted(exact), sorted(same_name)))
        banks[bank] = rows
        progress(f"Bank {bank}: {len(rows)} presets")
    mark_duplicates(banks)
    backup_hashes: set[str] = set()
    backup_names: set[str] = set()
    for rows in banks.values():
        for row in rows:
            if row.parsed.fingerprint:
                backup_hashes.add(row.parsed.fingerprint)
            backup_names.add(row.parsed.normalized_name)
    pack_match_counts: dict[str, tuple[int, int, int]] = {}
    all_backup_rows = [row for rows in banks.values() for row in rows]
    pack_details: dict[str, PackDetails] = {}
    for name in pack_dirs:
        exact = by_name_only = 0
        for preset in pack_presets[name]:
            if preset.fingerprint and preset.fingerprint in backup_hashes:
                exact += 1
            elif preset.normalized_name in backup_names:
                by_name_only += 1
        pack_match_counts[name] = (exact + by_name_only, exact, by_name_only)
        fingerprints = {
            preset.fingerprint for preset in pack_presets[name] if preset.fingerprint
        }
        normalized_names = {preset.normalized_name for preset in pack_presets[name]}
        bank_matches = [
            row for row in all_backup_rows if row.parsed.fingerprint in fingerprints
        ]
        tag_counts = Counter(
            tag for preset in pack_presets[name] for tag in preset.tags
        )
        pack_details[name] = PackDetails(
            preset_count=pack_file_counts[name],
            tag_counts=dict(tag_counts),
            bank_matches=bank_matches,
            name_only_matches=[
                row for row in all_backup_rows
                if row.parsed.fingerprint not in fingerprints
                and row.parsed.normalized_name in normalized_names
            ],
        )
    return ScanResult(
        banks, len(pack_dirs), total, pack_file_counts, pack_match_counts, errors,
        pack_details
    )


def export_report(result: ScanResult, destination: Path) -> None:
    lines = ["Digitone II — Sound Pack Match Report", "", "SOUND PACKS"]
    for pack in sorted(result.pack_file_counts, key=str.casefold):
        found, exact, by_name = result.pack_match_counts[pack]
        total = result.pack_file_counts[pack]
        lines.append(
            f"{pack} — {found}/{total} found (exact: {exact}, by name: {by_name})"
        )
    lines.append("")
    for bank in BANKS:
        lines.append(f"BANK {bank}")
        for row in result.banks[bank]:
            exact = ", ".join(row.exact_packs) or "—"
            tags = ", ".join(row.parsed.tags) or "—"
            line = f"{row.slot:03d}  {row.parsed.display_name}  —  {tags}  —  {exact}"
            if row.name_only_packs:
                line += f"  [same name, different data: {', '.join(row.name_only_packs)}]"
            if row.duplicate_locations:
                line += f"  [duplicates: {', '.join(row.duplicate_locations)}]"
            if row.parsed.error:
                line += f"  [ERROR: {row.parsed.error}]"
            lines.append(line)
        lines.append("")
    if result.errors:
        lines.extend(["READ ERRORS", *result.errors, ""])
    destination.write_text("\n".join(lines), encoding="utf-8")


class App:
    def __init__(
        self,
        screen: "curses._CursesWindow",
        result: ScanResult,
        report_path: Path,
        settings: Settings,
    ):
        self.screen = screen
        self.result = result
        self.report_path = report_path
        self.bank_index = 0
        self.selected = 0
        self.offset = 0
        self.tag_filter: str | None = None
        self.mode = 0  # 0 all, 1 found, 2 missing, 3 name-only
        self.pack_view = False
        self.tags_view = False
        self.stats_view = False
        self.settings_view = False
        self.settings = settings
        self.settings_selection = 0
        self.only_empty_packs = False
        self.pack_detail_offset = 0
        self.message = ""
        self.menu_index = 0
        self.menu_focused = False
        self.menu_hitboxes: list[tuple[int, int, int]] = []

    @property
    def bank(self) -> str:
        return BANKS[self.bank_index]

    def rows(self) -> list[BackupPreset]:
        rows = self.result.banks[self.bank]
        if self.tag_filter:
            rows = [r for r in rows if self.tag_filter in r.parsed.tags]
        if self.mode == 1:
            rows = [r for r in rows if r.exact_packs]
        elif self.mode == 2:
            rows = [r for r in rows if not r.exact_packs]
        elif self.mode == 3:
            rows = [r for r in rows if r.name_only_packs and not r.exact_packs]
        return rows

    def pack_names(self) -> list[str]:
        packs = sorted(self.result.pack_file_counts, key=str.casefold)
        if self.only_empty_packs:
            packs = [pack for pack in packs if self.result.pack_match_counts[pack][0] == 0]
        return packs

    def add(self, y: int, x: int, text: str, attr: int = 0) -> None:
        height, width = self.screen.getmaxyx()
        if 0 <= y < height and x < width:
            try:
                self.screen.addnstr(y, x, text, max(0, width - x - 1), attr)
            except curses.error:
                pass

    def settings_complete(self) -> bool:
        return all(
            path is not None and path.is_dir()
            for path in (self.settings.backup, self.settings.packs)
        )

    def current_section(self) -> int:
        if self.pack_view:
            return 1
        if self.tags_view:
            return 2
        if self.stats_view:
            return 3
        if self.settings_view:
            return 4
        return 0

    def activate_menu(self, index: int) -> str | None:
        if index == 5:
            return "quit"
        if not self.settings_complete() and index != 4:
            self.message = "Сначала укажите обе папки в настройках"
            self.settings_view = True
            return None
        self.pack_view = index == 1
        self.tags_view = index == 2
        self.stats_view = index == 3
        self.settings_view = index == 4
        self.selected = self.offset = 0
        self.pack_detail_offset = 0
        self.menu_index = index
        return None

    def draw_bottom_menu(self) -> None:
        height, width = self.screen.getmaxyx()
        y = height - 2
        self.add(y, 0, " " * max(0, width - 1))
        labels = ("БАНКИ", "САУНД-ПАКИ", "ТЕГИ", "СТАТИСТИКА", "НАСТРОЙКИ", "ВЫХОД")
        active = self.current_section()
        self.menu_hitboxes = []
        x = 2
        for index, label in enumerate(labels):
            text = f"[ {label} ]"
            if x + len(text) >= width:
                break
            attr = curses.A_BOLD
            if index == active:
                attr |= curses.color_pair(2)
            if self.menu_focused and index == self.menu_index:
                attr |= curses.A_REVERSE
            self.add(y, x, text, attr)
            self.menu_hitboxes.append((x, x + len(text), index))
            x += len(text) + 1

    def handle_mouse(self) -> str | None:
        try:
            _, x, y, _, button_state = curses.getmouse()
        except curses.error:
            return None
        click_mask = (
            getattr(curses, "BUTTON1_CLICKED", 0)
            | getattr(curses, "BUTTON1_PRESSED", 0)
            | getattr(curses, "BUTTON1_RELEASED", 0)
        )
        if not button_state & click_mask or y != self.screen.getmaxyx()[0] - 2:
            return None
        for start, end, index in self.menu_hitboxes:
            if start <= x < end:
                self.menu_index = index
                self.menu_focused = False
                return self.activate_menu(index)
        return None

    def draw_bank_tabs(self) -> None:
        x = 2
        for bank in BANKS:
            active = (
                bank == self.bank
                and not self.pack_view
                and not self.tags_view
                and not self.stats_view
                and not self.settings_view
            )
            self.add(2, x, "[" if active else " ", curses.A_BOLD)
            x += 1
            count = len(self.result.banks[bank])
            color = 2 if count < 256 else (3 if count == 256 else 4)
            self.add(2, x, bank, curses.color_pair(color) | curses.A_BOLD)
            x += 1
            suffix = "]  " if active else "   "
            self.add(2, x, suffix, curses.A_BOLD)
            x += len(suffix)
        packs_tab = "[САУНД-ПАКИ]" if self.pack_view else " САУНД-ПАКИ "
        self.add(2, x + 2, packs_tab, curses.A_BOLD)
        x += len(packs_tab) + 5
        tags_tab = "[ТЕГИ]" if self.tags_view else " ТЕГИ "
        self.add(2, x, tags_tab, curses.A_BOLD)
        x += len(tags_tab) + 3
        stats_tab = "[СТАТИСТИКА]" if self.stats_view else " СТАТИСТИКА "
        self.add(2, x, stats_tab, curses.A_BOLD)
        x += len(stats_tab) + 3
        settings_tab = "[НАСТРОЙКИ]" if self.settings_view else " НАСТРОЙКИ "
        self.add(2, x, settings_tab, curses.A_BOLD)

    def draw(self) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        title = " DIGITONE II · PRESET LIBRARY "
        self.add(0, 0, title.ljust(width - 1), curses.color_pair(1) | curses.A_BOLD)
        self.draw_bank_tabs()
        if self.pack_view:
            self.draw_packs()
            return
        if self.tags_view:
            self.draw_tags()
            return
        if self.stats_view:
            self.draw_stats()
            return
        if self.settings_view:
            self.draw_settings()
            return
        mode_names = ("ВСЕ", "НАЙДЕНЫ", "НЕ НАЙДЕНЫ", "ТОЛЬКО ИМЯ")
        bank_count = len(self.result.banks[self.bank])
        prefix = "ПРЕСЕТОВ: "
        self.add(3, 2, prefix)
        capacity = f"{bank_count}/256"
        capacity_attr = curses.color_pair(4) | curses.A_BOLD if bank_count > 256 else 0
        self.add(3, 2 + len(prefix), capacity, capacity_attr)
        status = f"   Совпадения: {mode_names[self.mode]}   Тег: {self.tag_filter or 'ВСЕ'}"
        status_x = 2 + len(prefix) + len(capacity)
        self.add(3, status_x, status)
        duplicate_count = sum(bool(row.duplicate_locations) for row in self.result.banks[self.bank])
        duplicate_text = f"   ДУБЛЕЙ: {duplicate_count}"
        duplicate_attr = curses.color_pair(4) | curses.A_BOLD if duplicate_count else curses.A_DIM
        self.add(3, status_x + len(status), duplicate_text, duplicate_attr)

        rows = self.rows()
        list_top, list_bottom = 5, max(6, height - 7)
        visible = max(1, list_bottom - list_top)
        self.selected = min(self.selected, max(0, len(rows) - 1))
        if self.selected < self.offset:
            self.offset = self.selected
        elif self.selected >= self.offset + visible:
            self.offset = self.selected - visible + 1
        self.add(4, 2, "№    PRESET                            TAGS                                      SOUND PACK(S)", curses.A_DIM)
        for y, row in enumerate(rows[self.offset:self.offset + visible], list_top):
            idx = self.offset + y - list_top
            packs = ", ".join(row.exact_packs)
            tags = ", ".join(row.parsed.tags) or "—"
            shown = packs or (", ".join(row.name_only_packs) if row.name_only_packs else "—")
            line = f"{row.slot:03d}  {row.parsed.display_name[:32]:32}  {tags[:40]:40}  {shown}"
            color = curses.color_pair(4) if row.duplicate_locations else (
                curses.color_pair(2) if packs else curses.color_pair(3))
            attr = color | (curses.A_REVERSE if idx == self.selected else 0)
            self.add(y, 2, line, attr)

        matched = sum(bool(r.exact_packs) for r in self.result.banks[self.bank])
        stats = f"Bank {self.bank}: {matched}/{len(self.result.banks[self.bank])} найдено · паков: {self.result.pack_count} · файлов: {self.result.pack_preset_count}"
        self.add(height - 5, 2, stats, curses.A_BOLD)
        if rows:
            row = rows[self.selected]
            detail = f"Файл: {row.parsed.path.name}"
            if row.name_only_packs:
                detail += f" · ≈ другое содержимое: {', '.join(row.name_only_packs)}"
            if row.duplicate_locations:
                detail += f" · дубли: {', '.join(row.duplicate_locations)}"
            self.add(height - 4, 2, detail, curses.A_DIM)
        self.add(height - 2, 2, "←/→ банк  ↑/↓ выбор  T фильтр  F совпадения  P паки  G теги  S статистика  E отчёт  R скан  Q выход")
        self.add(height - 1, 2, self.message, curses.color_pair(2))
        self.draw_bottom_menu()
        self.screen.refresh()

    def draw_settings(self) -> None:
        height, width = self.screen.getmaxyx()
        self.add(4, 2, "ПАПКИ ДЛЯ СКАНИРОВАНИЯ", curses.A_DIM | curses.A_BOLD)
        rows = (
            ("Банки A–H", self.settings.backup),
            ("Саунд-паки", self.settings.packs),
        )
        for index, (label, path) in enumerate(rows):
            y = 6 + index * 4
            attr = curses.A_REVERSE if index == self.settings_selection else curses.A_BOLD
            self.add(y, 4, f" {label} ", attr)
            valid = path is not None and path.is_dir()
            path_attr = curses.color_pair(2) if valid else curses.color_pair(4)
            shown = str(path) if path else "НЕ УКАЗАНО — выберите папку"
            self.add(y + 1, 6, shown[:max(1, width - 9)], path_attr)
        self.add(height - 4, 2, f"Файл настроек: {settings_path()}", curses.A_DIM)
        complete = all(
            path is not None and path.is_dir()
            for path in (self.settings.backup, self.settings.packs)
        )
        controls = "↑/↓ выбрать  Enter выбрать папку"
        if complete:
            controls += "  O банки  P паки  G теги  S статистика"
        controls += "  Q выход"
        self.add(height - 2, 2, controls)
        self.add(height - 1, 2, self.message, curses.color_pair(2))
        self.draw_bottom_menu()
        self.screen.refresh()

    def choose_folder(self, title: str, initial: Path | None) -> Path | None:
        if sys.platform == "darwin":
            default_location = initial or Path.home()
            while not default_location.is_dir() and default_location != default_location.parent:
                default_location = default_location.parent
            script = (
                'POSIX path of (choose folder with prompt "'
                + title.replace('"', '\\"')
                + '" default location POSIX file '
                + json.dumps(str(default_location))
                + ")"
            )
            try:
                completed = subprocess.run(
                    ["osascript", "-e", script],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                return Path(completed.stdout.strip().rstrip("/"))
            except subprocess.CalledProcessError:
                return None
        return self.prompt_path(title, initial or Path.home())

    def prompt_path(self, title: str, initial: Path) -> Path | None:
        curses.echo()
        curses.curs_set(1)
        try:
            self.screen.erase()
            self.add(0, 0, f" {title} ", curses.color_pair(1) | curses.A_BOLD)
            self.add(2, 2, "Введите полный путь и нажмите Enter:")
            self.add(4, 2, str(initial))
            self.screen.move(4, 2)
            value = self.screen.getstr(4, 2, 4096).decode("utf-8").strip()
            return Path(value).expanduser() if value else None
        finally:
            curses.noecho()
            curses.curs_set(0)

    def update_selected_setting(self) -> bool:
        labels = ("Выберите папку с банками A–H", "Выберите папку с саунд-паками")
        current = (self.settings.backup, self.settings.packs)[self.settings_selection]
        chosen = self.choose_folder(labels[self.settings_selection], current)
        if chosen is None:
            self.message = "Выбор папки отменён"
            return False
        if not chosen.is_dir():
            self.message = f"Папка не найдена: {chosen}"
            return False
        updated = Settings(
            backup=chosen if self.settings_selection == 0 else self.settings.backup,
            packs=chosen if self.settings_selection == 1 else self.settings.packs,
        )
        try:
            save_settings(updated)
        except OSError as exc:
            self.message = f"Не удалось сохранить настройки: {exc}"
            return False
        self.settings = updated
        self.message = "Настройки сохранены"
        return True

    def draw_packs(self) -> None:
        height, width = self.screen.getmaxyx()
        packs = self.pack_names()
        list_top, list_bottom = 5, max(6, height - 6)
        visible = max(1, list_bottom - list_top)
        self.selected = min(self.selected, max(0, len(packs) - 1))
        if self.selected < self.offset:
            self.offset = self.selected
        elif self.selected >= self.offset + visible:
            self.offset = self.selected - visible + 1
        pack_mode = "ТОЛЬКО БЕЗ НАЙДЕННЫХ" if self.only_empty_packs else "ВСЕ ПАПКИ"
        self.add(3, 2, f"Режим: {pack_mode}")
        left_width = min(58, max(34, width // 2 - 4))
        name_width = max(14, left_width - 18)
        self.add(4, 2, f"{'САУНД-ПАК':{name_width}}  НАЙДЕНО   ВСЕГО", curses.A_DIM)
        for y, pack in enumerate(packs[self.offset:self.offset + visible], list_top):
            idx = self.offset + y - list_top
            found, exact, by_name = self.result.pack_match_counts[pack]
            total = self.result.pack_file_counts[pack]
            line = f"{pack[:name_width]:{name_width}}  {found:5}     {total:5}"
            attr = curses.A_REVERSE if idx == self.selected else (
                curses.color_pair(2) if found else curses.color_pair(3))
            self.add(y, 2, line, attr)
        found_packs = sum(bool(v[0]) for v in self.result.pack_match_counts.values())
        summary = f"Найдены пресеты из {found_packs}/{self.result.pack_count} саунд-паков"
        self.add(height - 4, 2, summary[:left_width], curses.A_BOLD)
        if packs:
            pack = packs[self.selected]
            details = self.result.pack_details.get(
                pack, PackDetails(self.result.pack_file_counts[pack], {}, [], [])
            )
            self.draw_pack_details(pack, details, left_width + 5, width, height)
        self.add(height - 2, 2, "↑/↓ пак  ←/→ справа  Z без совпадений  P банки  G теги  S статистика  E отчёт  R скан  Q выход")
        self.add(height - 1, 2, self.message, curses.color_pair(2))
        self.draw_bottom_menu()
        self.screen.refresh()

    def draw_pack_details(
        self, pack: str, details: PackDetails, x: int, width: int, height: int
    ) -> None:
        panel_width = max(1, width - x - 2)
        for y in range(3, height - 2):
            self.add(y, x - 2, "│", curses.A_DIM)
        self.add(3, x, "ВЫБРАННЫЙ САУНД-ПАК", curses.A_BOLD)
        self.add(4, x, pack[:panel_width], curses.color_pair(2) | curses.A_BOLD)
        self.add(6, x, f"Пресетов внутри: {details.preset_count}")
        used = len(details.bank_matches) + len(details.name_only_matches)
        self.add(
            7,
            x,
            f"Найдено в банках: {used} · точно: {len(details.bank_matches)} · по имени: {len(details.name_only_matches)}"[:panel_width],
        )

        matches_x = x + min(34, max(22, panel_width // 3))
        matches = [
            (row, "") for row in details.bank_matches
        ] + [
            (row, "≈ ") for row in details.name_only_matches
        ]
        available = max(0, height - 12)
        self.pack_detail_offset = min(
            self.pack_detail_offset, max(0, len(matches) - available)
        )
        match_end = min(len(matches), self.pack_detail_offset + available)
        self.add(9, x, "ТЕГИ", curses.A_DIM | curses.A_BOLD)
        match_header = "ПРЕСЕТЫ В БАНКАХ"
        if matches:
            match_header += f"  {self.pack_detail_offset + 1}–{match_end}/{len(matches)}"
        self.add(9, matches_x, match_header, curses.A_DIM | curses.A_BOLD)
        tags = sorted(
            details.tag_counts,
            key=lambda tag: (-details.tag_counts[tag], tag.casefold()),
        )
        tag_width = max(8, matches_x - x - 4)
        for index, tag in enumerate(tags[:available]):
            self.add(10 + index, x, f"{tag[:tag_width]:{tag_width}} {details.tag_counts[tag]:4}")
        if len(tags) > available and available:
            self.add(10 + available - 1, x, f"… ещё {len(tags) - available + 1}", curses.A_DIM)

        match_width = max(8, width - matches_x - 2)
        visible_matches = matches[self.pack_detail_offset:match_end]
        for index, (row, marker) in enumerate(visible_matches):
            label = f"{marker}{row.bank}{row.slot:03d}  {row.parsed.display_name}"
            self.add(10 + index, matches_x, label[:match_width])
        if not matches:
            self.add(10, matches_x, "—", curses.A_DIM)

    def draw_tags(self) -> None:
        height, _ = self.screen.getmaxyx()
        counts = Counter(
            tag
            for rows in self.result.banks.values()
            for row in rows
            for tag in row.parsed.tags
        )
        tags = sorted(counts, key=lambda tag: (-counts[tag], tag.casefold()))
        list_top, list_bottom = 5, max(6, height - 6)
        visible = max(1, list_bottom - list_top)
        self.selected = min(self.selected, max(0, len(tags) - 1))
        if self.selected < self.offset:
            self.offset = self.selected
        elif self.selected >= self.offset + visible:
            self.offset = self.selected - visible + 1
        self.add(4, 2, "ТЕГ                                      ПРЕСЕТОВ", curses.A_DIM)
        for y, tag in enumerate(tags[self.offset:self.offset + visible], list_top):
            idx = self.offset + y - list_top
            line = f"{tag[:40]:40}  {counts[tag]:8}"
            attr = curses.A_REVERSE if idx == self.selected else curses.color_pair(2)
            self.add(y, 2, line, attr)
        tagged_presets = sum(
            bool(row.parsed.tags) for rows in self.result.banks.values() for row in rows
        )
        total_presets = sum(len(rows) for rows in self.result.banks.values())
        self.add(
            height - 4,
            2,
            f"Уникальных тегов: {len(tags)} · пресетов с тегами: {tagged_presets}/{total_presets}",
            curses.A_BOLD,
        )
        self.add(height - 2, 2, "↑/↓ выбор  G банки  P саунд-паки  S статистика  E отчёт  R скан  Q выход")
        self.add(height - 1, 2, self.message, curses.color_pair(2))
        self.draw_bottom_menu()
        self.screen.refresh()

    @staticmethod
    def capacity_text(count: int, maximum: int) -> tuple[str, int]:
        """Return a capacity label and its green/yellow/red color pair."""
        difference = count - maximum
        if difference < 0:
            return f"{count}/{maximum} (+{-difference})", 2
        if difference > 0:
            return f"{count}/{maximum} (+{difference} сверх)", 4
        return f"{count}/{maximum}", 3

    def draw_stats(self) -> None:
        height, _ = self.screen.getmaxyx()
        self.add(4, 2, "ЗАПОЛНЕННОСТЬ БАНКОВ", curses.A_DIM | curses.A_BOLD)
        for index, bank in enumerate(BANKS):
            count = len(self.result.banks[bank])
            capacity, color = self.capacity_text(count, 256)
            self.add(
                6 + index,
                4,
                f"BANK {bank}     {capacity}",
                curses.color_pair(color) | curses.A_BOLD,
            )

        total = sum(len(rows) for rows in self.result.banks.values())
        maximum = 256 * len(BANKS)
        capacity, color = self.capacity_text(total, maximum)
        summary_y = min(height - 5, 6 + len(BANKS) + 2)
        self.add(summary_y, 2, "ВСЕГО", curses.A_BOLD)
        self.add(
            summary_y,
            13,
            capacity,
            curses.color_pair(color) | curses.A_BOLD,
        )
        self.add(height - 2, 2, "M план переноса  S банки  P саунд-паки  G теги  E отчёт  R скан  Q выход")
        self.add(height - 1, 2, self.message, curses.color_pair(2))
        self.draw_bottom_menu()
        self.screen.refresh()

    def confirm_move_plan(self, plan: MovePlan) -> bool:
        """Show the complete plan and require an explicit MOVE confirmation."""
        selected_move = False  # Safe default: CANCEL.
        while True:
            self.screen.erase()
            height, width = self.screen.getmaxyx()
            self.add(
                0,
                0,
                " ПЛАН ПЕРЕРАСПРЕДЕЛЕНИЯ ".ljust(width - 1),
                curses.color_pair(1) | curses.A_BOLD,
            )
            self.add(2, 2, f"Будет перенесено пресетов: {len(plan.moves)}", curses.A_BOLD)
            sources: Counter[str] = Counter(move.source_bank for move in plan.moves)
            destinations: Counter[str] = Counter(
                move.destination_bank for move in plan.moves
            )
            self.add(
                4,
                2,
                "ИЗ: " + "   ".join(f"BANK {bank}: {sources[bank]}" for bank in BANKS if sources[bank]),
            )
            destination_parts = [
                f"BANK {bank}: +{destinations[bank]}"
                for bank in BANKS if destinations[bank]
            ]
            for index in range(0, len(destination_parts), 4):
                self.add(5 + index // 4, 2, "В:  " + "   ".join(destination_parts[index:index + 4]))

            y = 8
            self.add(y, 2, "ПОСЛЕ ПЕРЕНОСА", curses.A_DIM | curses.A_BOLD)
            y += 1
            after = plan.after_counts
            for start in range(0, len(BANKS), 4):
                parts = [
                    f"{bank}: {plan.before_counts[bank]}→{after[bank]}"
                    for bank in BANKS[start:start + 4]
                ]
                self.add(y, 4, "    ".join(parts), curses.color_pair(2))
                y += 1
            total_before = sum(plan.before_counts.values())
            total_after = sum(after.values())
            self.add(
                min(y + 1, height - 5),
                2,
                f"Всего: {total_before} → {total_after} (количество не изменится)",
                curses.A_BOLD,
            )
            button_y = height - 3
            move_attr = curses.A_REVERSE | curses.A_BOLD if selected_move else curses.A_BOLD
            cancel_attr = curses.A_BOLD if selected_move else curses.A_REVERSE | curses.A_BOLD
            self.add(button_y, 4, "[ MOVE ]", move_attr | curses.color_pair(4))
            self.add(button_y, 17, "[ CANCEL ]", cancel_attr)
            self.add(height - 1, 2, "←/→ выбрать  Enter подтвердить  Esc отменить", curses.A_DIM)
            self.screen.refresh()
            key = self.screen.getch()
            if key in (27, ord("q"), ord("Q")):
                return False
            if key in (curses.KEY_LEFT, curses.KEY_RIGHT, 9):
                selected_move = not selected_move
            elif key in (curses.KEY_ENTER, 10, 13):
                return selected_move

    def move_overflow_presets(self) -> bool:
        try:
            plan = build_move_plan(self.result)
        except (OSError, ValueError) as exc:
            self.message = f"Перенос невозможен: {exc}"
            return False
        if not plan.moves:
            self.message = "Переполненных банков нет — перенос не требуется"
            return False
        if not self.confirm_move_plan(plan):
            self.message = "Перенос отменён — файлы не изменены"
            return False

        self.screen.erase()
        self.add(0, 0, " ПЕРЕНОС ПРЕСЕТОВ ", curses.color_pair(1) | curses.A_BOLD)
        self.add(2, 2, f"Копирование и проверка {len(plan.moves)} файлов…")
        self.add(4, 2, "Не отключайте диск до завершения операции.", curses.A_BOLD)
        self.screen.refresh()
        try:
            execute_move_plan(plan)
        except (OSError, RuntimeError, ValueError) as exc:
            self.message = f"Перенос не выполнен: {exc}"
            return False
        return True

    def choose_tag_filter(self) -> None:
        tags = sorted(
            {tag for rows in self.result.banks.values() for row in rows for tag in row.parsed.tags},
            key=str.casefold,
        )
        options: list[str | None] = [None, *tags]
        choice = options.index(self.tag_filter) if self.tag_filter in options else 0
        offset = 0
        while True:
            self.screen.erase()
            height, width = self.screen.getmaxyx()
            self.add(0, 0, " ФИЛЬТР ПО ТЕГУ ".ljust(width - 1), curses.color_pair(1) | curses.A_BOLD)
            self.add(2, 2, "Выберите тег:", curses.A_BOLD)
            list_top = 4
            visible = max(1, height - 7)
            if choice < offset:
                offset = choice
            elif choice >= offset + visible:
                offset = choice - visible + 1
            for y, option in enumerate(options[offset:offset + visible], list_top):
                index = offset + y - list_top
                label = "ВСЕ ТЕГИ" if option is None else option
                self.add(y, 4, label, curses.A_REVERSE if index == choice else 0)
            self.add(height - 2, 2, "↑/↓ выбор  Enter применить  Esc отменить")
            self.screen.refresh()
            key = self.screen.getch()
            if key in (27, ord("q"), ord("Q")):
                return
            if key in (curses.KEY_DOWN, ord("j")):
                choice = min(len(options) - 1, choice + 1)
            elif key in (curses.KEY_UP, ord("k")):
                choice = max(0, choice - 1)
            elif key == curses.KEY_NPAGE:
                choice = min(len(options) - 1, choice + visible)
            elif key == curses.KEY_PPAGE:
                choice = max(0, choice - visible)
            elif key in (curses.KEY_ENTER, 10, 13):
                self.tag_filter = options[choice]
                self.selected = self.offset = 0
                return

    def run(self) -> str:
        while True:
            self.draw()
            key = self.screen.getch()
            if key == curses.KEY_MOUSE:
                action = self.handle_mouse()
                if action == "quit":
                    return "quit"
                continue
            if key in (ord("q"), ord("Q"), 27):
                return "quit"
            if key in (9, getattr(curses, "KEY_BTAB", -1)):
                backwards = key == getattr(curses, "KEY_BTAB", -1)
                if not self.menu_focused:
                    self.menu_index = self.current_section()
                    self.menu_focused = True
                else:
                    step = -1 if backwards else 1
                    self.menu_index = (self.menu_index + step) % 6
                continue
            if self.menu_focused:
                if key == curses.KEY_LEFT:
                    self.menu_index = (self.menu_index - 1) % 6
                elif key == curses.KEY_RIGHT:
                    self.menu_index = (self.menu_index + 1) % 6
                elif key in (curses.KEY_ENTER, 10, 13):
                    action = self.activate_menu(self.menu_index)
                    self.menu_focused = False
                    if action == "quit":
                        return "quit"
                elif key == curses.KEY_UP:
                    self.menu_focused = False
                continue
            settings_incomplete = not self.settings_complete()
            if self.settings_view and settings_incomplete:
                if key in (curses.KEY_DOWN, ord("j"), curses.KEY_UP, ord("k")):
                    self.settings_selection = 1 - self.settings_selection
                elif key in (curses.KEY_ENTER, 10, 13):
                    if self.update_selected_setting():
                        return "settings_changed"
                continue
            if key in (ord("p"), ord("P")):
                self.pack_view = not self.pack_view
                self.tags_view = False
                self.stats_view = False
                self.settings_view = False
                self.selected = self.offset = 0
                self.pack_detail_offset = 0
                continue
            if key in (ord("g"), ord("G")):
                self.tags_view = not self.tags_view
                self.pack_view = False
                self.stats_view = False
                self.settings_view = False
                self.selected = self.offset = 0
                self.pack_detail_offset = 0
                continue
            if key in (ord("s"), ord("S")):
                self.stats_view = not self.stats_view
                self.pack_view = False
                self.tags_view = False
                self.settings_view = False
                self.selected = self.offset = 0
                self.pack_detail_offset = 0
                continue
            if key in (ord("o"), ord("O")):
                self.settings_view = not self.settings_view
                self.pack_view = False
                self.tags_view = False
                self.stats_view = False
                self.selected = self.offset = 0
                continue
            if self.settings_view:
                if key in (curses.KEY_DOWN, ord("j"), curses.KEY_UP, ord("k")):
                    self.settings_selection = 1 - self.settings_selection
                elif key in (curses.KEY_ENTER, 10, 13):
                    if self.update_selected_setting():
                        return "settings_changed"
                continue
            if self.pack_view:
                pack_count = len(self.pack_names())
                if key in (curses.KEY_DOWN, ord("j")):
                    self.selected = min(max(0, pack_count - 1), self.selected + 1)
                    self.pack_detail_offset = 0
                elif key in (curses.KEY_UP, ord("k")):
                    self.selected = max(0, self.selected - 1)
                    self.pack_detail_offset = 0
                elif key == curses.KEY_NPAGE:
                    self.selected = min(max(0, pack_count - 1), self.selected + 10)
                    self.pack_detail_offset = 0
                elif key == curses.KEY_PPAGE:
                    self.selected = max(0, self.selected - 10)
                    self.pack_detail_offset = 0
                elif key == curses.KEY_RIGHT:
                    page = max(1, self.screen.getmaxyx()[0] - 12)
                    self.pack_detail_offset += page
                elif key == curses.KEY_LEFT:
                    page = max(1, self.screen.getmaxyx()[0] - 12)
                    self.pack_detail_offset = max(0, self.pack_detail_offset - page)
                elif key in (ord("z"), ord("Z")):
                    self.only_empty_packs = not self.only_empty_packs
                    self.selected = self.offset = 0
                    self.pack_detail_offset = 0
                elif key in (ord("e"), ord("E")):
                    export_report(self.result, self.report_path)
                    self.message = f"Отчёт сохранён: {self.report_path}"
                elif key in (ord("r"), ord("R")):
                    return "rescan"
                continue
            if self.tags_view:
                tag_count = len({
                    tag
                    for rows in self.result.banks.values()
                    for row in rows
                    for tag in row.parsed.tags
                })
                if key in (curses.KEY_DOWN, ord("j")):
                    self.selected = min(max(0, tag_count - 1), self.selected + 1)
                elif key in (curses.KEY_UP, ord("k")):
                    self.selected = max(0, self.selected - 1)
                elif key == curses.KEY_NPAGE:
                    self.selected = min(max(0, tag_count - 1), self.selected + 10)
                elif key == curses.KEY_PPAGE:
                    self.selected = max(0, self.selected - 10)
                elif key in (ord("e"), ord("E")):
                    export_report(self.result, self.report_path)
                    self.message = f"Отчёт сохранён: {self.report_path}"
                elif key in (ord("r"), ord("R")):
                    return "rescan"
                continue
            if self.stats_view:
                if key in (ord("m"), ord("M")):
                    if self.move_overflow_presets():
                        return "rescan"
                elif key in (ord("e"), ord("E")):
                    export_report(self.result, self.report_path)
                    self.message = f"Отчёт сохранён: {self.report_path}"
                elif key in (ord("r"), ord("R")):
                    return "rescan"
                continue
            if key in (curses.KEY_RIGHT, ord("]")):
                self.bank_index = (self.bank_index + 1) % len(BANKS)
                self.selected = self.offset = 0
            elif key in (curses.KEY_LEFT, ord("[")):
                self.bank_index = (self.bank_index - 1) % len(BANKS)
                self.selected = self.offset = 0
            elif key in (curses.KEY_DOWN, ord("j")):
                self.selected += 1
            elif key in (curses.KEY_UP, ord("k")):
                self.selected = max(0, self.selected - 1)
            elif key in (curses.KEY_NPAGE,):
                self.selected += 10
            elif key in (curses.KEY_PPAGE,):
                self.selected = max(0, self.selected - 10)
            elif key in (ord("t"), ord("T")):
                self.choose_tag_filter()
            elif key in (ord("f"), ord("F")):
                self.mode = (self.mode + 1) % 4
                self.selected = self.offset = 0
            elif key in (ord("e"), ord("E")):
                export_report(self.result, self.report_path)
                self.message = f"Отчёт сохранён: {self.report_path}"
            elif key in (ord("r"), ord("R")):
                return "rescan"


def run_ui(settings: Settings, report: Path) -> None:
    def wrapped(screen: "curses._CursesWindow") -> None:
        nonlocal settings
        curses.curs_set(0)
        screen.keypad(True)
        try:
            curses.mousemask(
                curses.ALL_MOUSE_EVENTS | getattr(curses, "REPORT_MOUSE_POSITION", 0)
            )
        except curses.error:
            pass
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
            curses.init_pair(2, curses.COLOR_GREEN, -1)
            curses.init_pair(3, curses.COLOR_YELLOW, -1)
            curses.init_pair(4, curses.COLOR_RED, -1)
        while True:
            missing = [
                path for path in (settings.backup, settings.packs)
                if path is None or not path.is_dir()
            ]
            if missing:
                empty = ScanResult({bank: [] for bank in BANKS}, 0, 0, {}, {}, [])
                app = App(screen, empty, report, settings)
                app.settings_view = True
                app.message = "Укажите существующие папки — один или оба текущих пути недоступны"
                action = app.run()
                if action == "settings_changed":
                    settings = load_settings()
                    continue
                break
            screen.erase()
            screen.addstr(0, 0, "Сканирование .dn2pst и .dnsnd…")
            screen.refresh()

            def progress(message: str) -> None:
                screen.addnstr(2, 0, message.ljust(70), 69)
                screen.refresh()

            assert settings.backup is not None and settings.packs is not None
            result = scan(settings.backup, settings.packs, progress)
            action = App(screen, result, report, settings).run()
            if action == "settings_changed":
                settings = load_settings()
                continue
            if action != "rescan":
                break

    curses.wrapper(wrapped)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path, help="override the saved banks folder")
    parser.add_argument("--packs", type=Path, help="override the saved sound-packs folder")
    parser.add_argument("--report", type=Path, default=Path(__file__).with_name("digitone_report.txt"))
    parser.add_argument("--no-ui", action="store_true", help="scan and write the text report")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    saved = load_settings()
    settings = Settings(args.backup or saved.backup, args.packs or saved.packs)
    if args.no_ui:
        missing = [
            "не указан" if path is None else str(path)
            for path in (settings.backup, settings.packs)
            if path is None or not path.is_dir()
        ]
        if missing:
            print("Не указаны или не найдены папки:\n" + "\n".join(missing), file=sys.stderr)
            return 2
        assert settings.backup is not None and settings.packs is not None
        result = scan(settings.backup, settings.packs, lambda text: print(text, file=sys.stderr))
        export_report(result, args.report)
        print(args.report)
    else:
        run_ui(settings, args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
