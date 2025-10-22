import sys
import os
import json
import shutil
import shlex
import re
import subprocess
import webbrowser
import zipfile
import stat
import hashlib
import threading
import copy
import logging
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from typing import Dict, List, MutableMapping, Optional, Sequence, Set, Tuple
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from functools import partial
from urllib.parse import quote_plus
from PyQt5 import QtWidgets, QtCore, QtGui
from datetime import datetime, time, date
from openpyxl import Workbook

SETTINGS_PATH = "settings.json"
IGNORE_LIST_PATH = "ignorelist.txt"
VERSION_RELEASE_PATH = "version_release.json"
APP_VERSION = "v3.36"
APP_VERSION_DATE = "22/10/2025 13:43 UTC"
INSTALLED_MODS_PATH = "installed_mods.json"
MOD_SCAN_CACHE_PATH = "mod_scan_cache.json"

SUPPORTED_INSTALL_EXTENSIONS = {".package", ".ts4script", ".zip"}

IGNORED_ARCHIVE_PREFIXES = {"__MACOSX"}
IGNORED_ARCHIVE_PREFIX_MATCHES = (".git",)
IGNORED_ARCHIVE_FILENAMES = {"thumbs.db", ".ds_store"}
IGNORED_ARCHIVE_NAME_PREFIXES = ("readme", "license")
DISALLOWED_ARCHIVE_EXTENSIONS = {
    ".exe",
    ".dll",
    ".bat",
    ".cmd",
    ".com",
    ".msi",
    ".ps1",
    ".vbs",
    ".js",
    ".jar",
    ".scr",
    ".pif",
    ".apk",
    ".app",
    ".sh",
    ".bash",
    ".py",
    ".rb",
    ".php",
}
MAX_RELATIVE_DEPTH = 2

LOG_LEVEL_CHOICES = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}

DEFAULT_LOG_LEVEL = "DEBUG"

LOGGER = logging.getLogger("sims4_mod_manager")


def configure_logging(level_name: str = DEFAULT_LOG_LEVEL) -> int:
    target_level_name = str(level_name or DEFAULT_LOG_LEVEL).upper()
    level = LOG_LEVEL_CHOICES.get(target_level_name, logging.DEBUG)

    root_logger = logging.getLogger()
    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        root_logger.addHandler(handler)
    root_logger.setLevel(level)
    LOGGER.setLevel(level)
    LOGGER.debug("Configuration du logging appliquée au niveau %s", target_level_name)
    return level

MOD_NAME_SANITIZE_RE = re.compile(r"[^a-z0-9]+")
MIN_SIMILARITY_RATIO = 0.6
MAX_SIMILARITY_CANDIDATES = 80


@dataclass(frozen=True)
class ZipInstallEntry:
    member_name: str
    relative_parts: Tuple[str, ...]


@dataclass
class ZipInstallPlan:
    mod_folder_name: str
    target_folder: str
    entries: List[ZipInstallEntry]
    warnings: List[str]


@dataclass
class ZipPlanResult:
    success: bool
    plan: Optional[ZipInstallPlan]
    message: str = ""


def normalize_addon_metadata(addons):
    normalized = []
    if not isinstance(addons, list):
        return normalized

    def _append_or_merge(target_list, candidate):
        label = candidate.get("label", "")
        if not label:
            return
        key = label.casefold()
        for existing in target_list:
            if existing.get("label", "").casefold() == key:
                existing_paths = existing.setdefault("paths", [])
                for path in candidate.get("paths", []):
                    if path and path not in existing_paths:
                        existing_paths.append(path)
                if candidate.get("added_at") and not existing.get("added_at"):
                    existing["added_at"] = candidate.get("added_at")
                return
        target_list.append(candidate)

    for addon in addons:
        label = ""
        paths = []
        added_at = ""
        if isinstance(addon, dict):
            label = str(
                addon.get("label")
                or addon.get("name")
                or addon.get("source")
                or addon.get("title")
                or ""
            ).strip()
            raw_paths = addon.get("paths", [])
            if isinstance(raw_paths, (list, tuple)):
                for path in raw_paths:
                    path_str = str(path).replace("\\", "/").strip()
                    if path_str:
                        if path_str.startswith("..") or "/../" in path_str:
                            continue
                        if path_str.endswith("/"):
                            base_path = os.path.normpath(path_str[:-1])
                            normalized_path = base_path.replace("\\", "/") + "/"
                        else:
                            base_path = os.path.normpath(path_str)
                            normalized_path = base_path.replace("\\", "/")
                        if normalized_path not in paths:
                            paths.append(normalized_path)
            added_at = str(addon.get("added_at") or "").strip()
        else:
            label = str(addon).strip()

        if not label:
            continue

        _append_or_merge(
            normalized,
            {
                "label": label,
                "paths": paths,
                "added_at": added_at,
            },
        )

    return normalized


DEFAULT_VERSION_RELEASES = [
    {"version": "1.109.185.1030", "release_date": "2024-09-18"},
    {"version": "1.110.265.1030", "release_date": "2024-10-22"},
    {"version": "1.110.311.1020", "release_date": "2024-11-07"},
    {"version": "1.111.102.1030", "release_date": "2024-12-03"},
    {"version": "1.115.216.1030", "release_date": "2025-05-27"},
    {"version": "1.115.253.1020", "release_date": "2025-06-17"},
    {"version": "1.116.202.1030", "release_date": "2025-07-01"},
    {"version": "1.116.223.1030", "release_date": "2025-07-10"},
    {"version": "1.116.232.1030", "release_date": "2025-07-16"},
    {"version": "1.116.240.1020", "release_date": "2025-07-29"},
    {"version": "1.117.227.1030", "release_date": "2025-08-19"},
    {"version": "1.117.244.1020", "release_date": "2025-09-04"},
    {"version": "1.118.242.1030", "release_date": "2025-09-18"},
    {"version": "1.118.257.1020", "release_date": "2025-10-02"},
]


def parse_release_date(date_str):
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def format_release_date(date_obj):
    if not date_obj:
        return ""
    return date_obj.strftime("%d/%m/%Y")


def load_custom_version_releases(path=VERSION_RELEASE_PATH):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

    releases = {}
    if isinstance(data, dict):
        items = data.items()
    elif isinstance(data, list):
        items = ((entry.get("version"), entry.get("release_date")) for entry in data)
    else:
        return {}

    for version, date_str in items:
        if not version:
            continue
        parsed = parse_release_date(date_str)
        if parsed is None:
            continue
        releases[str(version)] = parsed
    return releases


def save_custom_version_releases(releases, path=VERSION_RELEASE_PATH):
    entries = [
        {"version": version, "release_date": date.isoformat()}
        for version, date in sorted(releases.items(), key=lambda item: (item[1], item[0]))
    ]
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=4, ensure_ascii=False)


def merge_version_releases(custom_releases):
    merged = {}
    for entry in DEFAULT_VERSION_RELEASES:
        version = entry.get("version")
        date_str = entry.get("release_date")
        if not version or not date_str:
            continue
        parsed = parse_release_date(date_str)
        if parsed is None:
            continue
        merged[version] = parsed
    for version, date_obj in custom_releases.items():
        if not version or date_obj is None:
            continue
        merged[version] = date_obj
    sorted_items = sorted(merged.items(), key=lambda item: (item[1], item[0]))
    return OrderedDict(sorted_items)


def estimate_version_from_dates(package_date, script_date, version_releases):
    candidates = [value for value in (package_date, script_date) if value is not None]
    if not candidates:
        return ""
    latest_datetime = max(candidates)
    latest_date = latest_datetime.date()
    estimated_version = ""
    for version, release_date in version_releases.items():
        if release_date <= latest_date:
            estimated_version = version
        elif not estimated_version:
            return version
        else:
            break
    return estimated_version


def format_datetime(value):
    if not value:
        return ""
    return value.strftime("%d/%m/%Y %H:%M")


def load_ignore_list(path=IGNORE_LIST_PATH):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def save_ignore_list(ignored_mods, path=IGNORE_LIST_PATH):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for mod_name in sorted(set(ignored_mods)):
            f.write(f"{mod_name}\n")


def load_installed_mods(path=INSTALLED_MODS_PATH):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return []

    normalized_entries = []
    for entry in data if isinstance(data, list) else []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or entry.get("mod_name") or "").strip()
        target_folder = str(entry.get("target_folder") or "").strip()
        if not name or not target_folder:
            continue
        normalized_entries.append({
            "name": name,
            "type": str(entry.get("type") or "").strip(),
            "installed_at": str(entry.get("installed_at") or "").strip(),
            "target_folder": target_folder,
            "source": str(entry.get("source") or "").strip(),
            "addons": normalize_addon_metadata(entry.get("addons", [])),
        })

    normalized_entries.sort(key=lambda item: item.get("installed_at", ""), reverse=True)
    return normalized_entries


def save_installed_mods(installed_mods, path=INSTALLED_MODS_PATH):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(installed_mods, handle, indent=4, ensure_ascii=False)


def load_mod_scan_cache(path=MOD_SCAN_CACHE_PATH):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    entries = data.get("entries")
    if not isinstance(entries, list):
        return None
    normalized_entries = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        path_value = str(entry.get("path") or "").strip()
        if not path_value:
            continue
        normalized_entries.append({
            "path": path_value.replace("\\", "/"),
            "mtime": int(entry.get("mtime", 0)),
            "size": int(entry.get("size", 0)),
            "type": str(entry.get("type") or ""),
        })
    normalized_entries.sort(key=lambda item: item["path"].casefold())
    normalized_root = str(data.get("root") or "").replace("\\", "/").strip()
    return {
        "root": normalized_root,
        "entries": normalized_entries,
    }


def save_mod_scan_cache(snapshot, path=MOD_SCAN_CACHE_PATH):
    if not isinstance(snapshot, dict):
        return
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    serializable = {
        "root": str(snapshot.get("root") or ""),
        "generated_at": snapshot.get("generated_at", ""),
        "entries": list(snapshot.get("entries", [])),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(serializable, handle, indent=2, ensure_ascii=False)


def mod_scan_snapshots_equal(first, second):
    if not first or not second:
        return False
    first_entries = first.get("entries") or []
    second_entries = second.get("entries") or []
    if len(first_entries) != len(second_entries):
        return False
    for a, b in zip(first_entries, second_entries):
        if (
            a.get("path") != b.get("path")
            or int(a.get("mtime", 0)) != int(b.get("mtime", 0))
            or int(a.get("size", 0)) != int(b.get("size", 0))
            or (a.get("type") or "") != (b.get("type") or "")
        ):
            return False
    return True


def sanitize_mod_folder_name(file_name):
    base_name = os.path.splitext(os.path.basename(file_name))[0]
    sanitized = re.sub(r"[\\/:*?\"<>|]", "_", base_name).strip()
    return sanitized or "mod"


def sanitize_archive_member_path(member_name):
    normalized = str(member_name).replace("\\", "/").strip()
    normalized = re.sub(r"/+", "/", normalized.lstrip("/"))
    if not normalized:
        return ""

    parts = []
    for raw_part in normalized.split("/"):
        part = raw_part.strip()
        if not part or part in {".", ".."}:
            continue
        safe_part = re.sub(r"[\\/:*?\"<>|]", "_", part)
        if safe_part:
            parts.append(safe_part)

    return "/".join(parts)


def _zipinfo_is_symlink(info):
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _member_should_be_skipped(parts, name):
    if not parts:
        return True
    first = parts[0].casefold()
    if first in {prefix.casefold() for prefix in IGNORED_ARCHIVE_PREFIXES}:
        return True
    for prefix in IGNORED_ARCHIVE_PREFIX_MATCHES:
        if first.startswith(prefix.casefold()):
            return True
    lowered = name.casefold()
    if lowered in IGNORED_ARCHIVE_FILENAMES:
        return True
    for prefix in IGNORED_ARCHIVE_NAME_PREFIXES:
        if lowered.startswith(prefix):
            return True
    return False


def _collapse_folder_name(parts):
    filtered = [part for part in parts if part]
    if not filtered:
        return ""
    if len(filtered) == 1:
        return filtered[0]
    return "-".join(filtered)


def _ensure_depth(parts):
    if len(parts) <= MAX_RELATIVE_DEPTH:
        return list(parts)
    folder = _collapse_folder_name(parts[:-1])
    if folder:
        return [folder, parts[-1]]
    return [parts[-1]]


def _register_directory(existing_dirs, parts, warnings):
    if not parts:
        return
    normalized = tuple(part.casefold() for part in parts)
    if normalized in existing_dirs:
        return
    existing_dirs.add(normalized)


def _ensure_unique_parts(existing_paths, existing_dirs, parts, warnings, *, is_dir=False):
    normalized = tuple(part.casefold() for part in parts)
    registry = existing_dirs if is_dir else existing_paths
    if normalized not in registry:
        registry.add(normalized)
        if not is_dir and parts[:-1]:
            _register_directory(existing_dirs, parts[:-1], warnings)
        return list(parts)

    base_name = parts[-1]
    if is_dir:
        stem = base_name
        suffix = ""
    else:
        stem, suffix = os.path.splitext(base_name)
    counter = 2
    while True:
        candidate_name = f"{stem}-v{counter}{suffix}"
        candidate_parts = list(parts[:-1]) + [candidate_name]
        normalized_candidate = tuple(part.casefold() for part in candidate_parts)
        if normalized_candidate not in registry:
            registry.add(normalized_candidate)
            if not is_dir:
                _register_directory(existing_dirs, candidate_parts[:-1], warnings)
            warnings.append(
                f"Conflit détecté pour '{base_name}', renommé en '{candidate_name}'."
            )
            return candidate_parts
        counter += 1


def _resolve_file_conflicts(target_root, relative_parts, warnings, written_paths):
    base_name = relative_parts[-1]
    stem, ext = os.path.splitext(base_name)
    if not stem:
        stem = "fichier"
    counter = 1
    renamed_target = None
    candidate_parts = list(relative_parts)

    while True:
        candidate_path = os.path.join(target_root, *candidate_parts)
        candidate_key = tuple(part.casefold() for part in candidate_parts)
        if candidate_key not in written_paths and not os.path.exists(candidate_path):
            written_paths.add(candidate_key)
            if renamed_target is not None:
                warnings.append(
                    f"Fichier existant détecté pour '{'/'.join(relative_parts)}', renommé en '{'/'.join(candidate_parts)}'."
                )
            return candidate_parts

        counter += 1
        renamed_target = f"{stem}-v{counter}{ext}"
        candidate_parts = list(relative_parts[:-1]) + [renamed_target]


def _preferred_parent_parts(entry):
    if len(entry["adjusted_parts"]) <= 1:
        return []
    folder = _collapse_folder_name(entry["adjusted_parts"][:-1])
    return [folder] if folder else []


def _organize_zip_entries(entries):
    plan_entries: List[ZipInstallEntry] = []
    warnings: List[str] = []
    existing_paths: Set[Tuple[str, ...]] = set()
    existing_dirs: Set[Tuple[str, ...]] = set()
    script_parents: Dict[str, Tuple[str, ...]] = {}
    scripts_by_base: Dict[str, List[Dict[str, object]]] = defaultdict(list)

    for entry in entries:
        if entry["is_ts4script"]:
            scripts_by_base[entry["base_name"]].append(entry)

    for entry in entries:
        if not entry["is_ts4script"]:
            continue
        normalized_name = (entry["name"].casefold(),)
        if normalized_name in existing_paths:
            module_base = sanitize_mod_folder_name(entry.get("raw_base") or entry["name"])
            module_base = module_base or "module"
            folder_candidate = module_base
            counter = 2
            while (folder_candidate.casefold(),) in existing_dirs:
                folder_candidate = f"{module_base}-v{counter}"
                counter += 1
            final_parts = _ensure_unique_parts(
                existing_paths,
                existing_dirs,
                [folder_candidate, entry["name"]],
                warnings,
            )
            script_parent = (final_parts[0],)
        else:
            final_parts = _ensure_unique_parts(
                existing_paths,
                existing_dirs,
                [entry["name"]],
                warnings,
            )
            script_parent = tuple(final_parts[:-1])
        script_parents[entry["member_name"]] = script_parent
        plan_entries.append(ZipInstallEntry(entry["member_name"], tuple(final_parts)))

    for entry in entries:
        if not entry["is_package"]:
            continue
        base_key = entry["base_name"]
        parent: Sequence[str] = []
        candidate_scripts = scripts_by_base.get(base_key, [])
        if candidate_scripts:
            script_entry = candidate_scripts[0]
            parent = script_parents.get(script_entry["member_name"], ())
        else:
            parent = _preferred_parent_parts(entry)
        final_parts = list(parent) + [entry["name"]]
        final_parts = _ensure_depth(final_parts)
        final_parts = _ensure_unique_parts(existing_paths, existing_dirs, final_parts, warnings)
        plan_entries.append(ZipInstallEntry(entry["member_name"], tuple(final_parts)))

    for entry in entries:
        if entry["is_ts4script"] or entry["is_package"]:
            continue
        parent = _preferred_parent_parts(entry)
        final_parts = parent + [entry["name"]]
        final_parts = _ensure_depth(final_parts)
        final_parts = _ensure_unique_parts(existing_paths, existing_dirs, final_parts, warnings)
        plan_entries.append(ZipInstallEntry(entry["member_name"], tuple(final_parts)))

    return plan_entries, warnings


def build_zip_install_plan(
    file_path,
    *,
    mod_directory,
    default_mod_name,
    existing_target=None,
):
    try:
        archive = zipfile.ZipFile(file_path, "r")
    except zipfile.BadZipFile as exc:
        return ZipPlanResult(False, None, f"Archive zip invalide : {exc}")

    with archive:
        entries: List[Dict[str, object]] = []
        for info in archive.infolist():
            sanitized = sanitize_archive_member_path(info.filename)
            if not sanitized:
                continue
            parts = sanitized.split("/")
            if not parts:
                continue
            name = parts[-1]
            if info.is_dir():
                if _member_should_be_skipped(parts, name):
                    continue
                continue
            if _zipinfo_is_symlink(info):
                return ZipPlanResult(False, None, f"Lien symbolique détecté dans l'archive : {info.filename}")
            extension = os.path.splitext(name)[1].lower()
            if extension in DISALLOWED_ARCHIVE_EXTENSIONS:
                return ZipPlanResult(False, None, f"Fichier interdit détecté : {name}")
            if _member_should_be_skipped(parts, name):
                continue
            raw_base = os.path.splitext(name)[0]
            entry = {
                "member_name": info.filename,
                "parts": parts,
                "name": name,
                "extension": extension,
                "is_ts4script": extension == ".ts4script",
                "is_package": extension == ".package",
                "base_name": raw_base.casefold(),
                "raw_base": raw_base,
            }
            entries.append(entry)

        if not entries:
            return ZipPlanResult(False, None, "Aucun fichier exploitable dans l'archive.")

        root_dirs: Set[str] = set()
        root_files_present = False
        for entry in entries:
            parts = entry["parts"]
            if len(parts) == 1:
                root_files_present = True
            else:
                root_dirs.add(parts[0])

        drop_segments = 0
        unique_root_name = ""
        if len(root_dirs) == 1 and not root_files_present:
            unique_root_name = next(iter(root_dirs))
            drop_segments = 1

        if existing_target:
            target_folder = existing_target
            mod_folder_name = os.path.basename(existing_target.rstrip("/\\")) or default_mod_name
        else:
            mod_folder_name = default_mod_name
            if unique_root_name:
                candidate = sanitize_mod_folder_name(unique_root_name)
                if candidate:
                    mod_folder_name = candidate
            target_folder = os.path.join(mod_directory, mod_folder_name)

        adjusted_entries: List[Dict[str, object]] = []
        for entry in entries:
            parts = entry["parts"][drop_segments:]
            if not parts:
                continue
            adjusted_entry = dict(entry)
            adjusted_entry["adjusted_parts"] = parts
            adjusted_entries.append(adjusted_entry)

        plan_entries, warnings = _organize_zip_entries(adjusted_entries)
        if not plan_entries:
            return ZipPlanResult(False, None, "Aucun fichier valide après normalisation de l'archive.")

        plan = ZipInstallPlan(
            mod_folder_name=mod_folder_name,
            target_folder=target_folder,
            entries=plan_entries,
            warnings=warnings,
        )
        return ZipPlanResult(True, plan, "")
def format_installation_display(iso_value):
    if not iso_value:
        return ""
    try:
        parsed = datetime.fromisoformat(iso_value)
    except ValueError:
        return iso_value
    return parsed.strftime("%d/%m/%Y %H:%M UTC")

def get_file_date(file_path):
    timestamp = os.path.getmtime(file_path)
    return datetime.fromtimestamp(timestamp)

def load_settings(path=SETTINGS_PATH):
    try:
        with open(path, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        settings = {}
    defaults = {
        "version_filter_start": "",
        "version_filter_end": "",
        "enable_version_filters": True,
        "show_package_mods": True,
        "show_ts4script_mods": True,
        "mod_directory": "",
        "sims_cache_directory": "",
        "backups_directory": "",
        "xls_file_path": "",
        "sims_executable_path": "",
        "sims_executable_arguments": "",
        "log_extra_extensions": [],
        "grab_logs_ignore_files": [],
        "ignored_mods": [],
        "show_ignored": False,
        "show_search_results": True,
        "log_level": DEFAULT_LOG_LEVEL,
    }
    for key, value in defaults.items():
        settings.setdefault(key, value)

    show_search_pref = settings.get("show_search_results")
    if isinstance(show_search_pref, str):
        normalized = show_search_pref.strip().lower()
        settings["show_search_results"] = normalized not in {"false", "0", "non", "no", "off"}
    else:
        settings["show_search_results"] = bool(show_search_pref)

    settings["enable_version_filters"] = bool(settings.get("enable_version_filters", True))
    legacy_combined_filter = settings.pop("filter_package_and_ts4script", None)
    if legacy_combined_filter is True:
        settings["show_package_mods"] = True
        settings["show_ts4script_mods"] = True
    legacy_hide_post_118 = settings.pop("hide_post_118", None)
    legacy_filter_range = settings.pop("filter_116_to_118", None)
    if not settings.get("version_filter_start") and legacy_filter_range:
        settings["version_filter_start"] = "1.116.202.1030"
    if not settings.get("version_filter_end") and (legacy_filter_range or legacy_hide_post_118):
        settings["version_filter_end"] = "1.118.242.1030"

    if isinstance(settings.get("log_extra_extensions"), str):
        settings["log_extra_extensions"] = [part.strip() for part in settings["log_extra_extensions"].split(",") if part.strip()]
    extra_extensions = []
    for entry in settings.get("log_extra_extensions", []):
        if not entry:
            continue
        ext = entry if entry.startswith(".") else f".{entry}"
        extra_extensions.append(ext.lower())
    settings["log_extra_extensions"] = sorted(set(extra_extensions))

    ignore_entries = settings.get("grab_logs_ignore_files", [])
    if isinstance(ignore_entries, str):
        raw_parts = re.split(r"[,;\n]+", ignore_entries)
    else:
        raw_parts = ignore_entries
    normalized_ignore = []
    seen = set()
    for part in raw_parts:
        if not part:
            continue
        cleaned = str(part).strip()
        if not cleaned or cleaned.lower() in seen:
            continue
        seen.add(cleaned.lower())
        normalized_ignore.append(cleaned)
    settings["grab_logs_ignore_files"] = normalized_ignore

    ignored_from_file = load_ignore_list()
    if not ignored_from_file and settings.get("ignored_mods"):
        ignored_from_file = settings.get("ignored_mods", [])
        save_ignore_list(ignored_from_file)
    settings["ignored_mods"] = ignored_from_file
    level_name = str(settings.get("log_level", DEFAULT_LOG_LEVEL)).upper()
    if level_name not in LOG_LEVEL_CHOICES:
        level_name = DEFAULT_LOG_LEVEL
    settings["log_level"] = level_name
    return settings

def save_settings(settings, path=SETTINGS_PATH):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=4, ensure_ascii=False)

def normalize_mod_basename(name):
    if not name:
        return ""
    base_name = os.path.splitext(os.path.basename(name))[0]
    normalized = MOD_NAME_SANITIZE_RE.sub("", base_name.casefold())
    return normalized


def stable_mod_name_hash(normalized_name):
    if not normalized_name:
        return 0
    digest = hashlib.sha1(normalized_name.encode("utf-8", errors="ignore")).hexdigest()
    return int(digest, 16)


def similarity_confidence_label(ratio):
    if ratio >= 0.9:
        return "Élevée"
    if ratio >= 0.75:
        return "Moyenne"
    return "Faible"

def build_mod_rows(
    package_files,
    ts4script_files,
    settings,
    version_releases,
    package_dates,
    script_dates,
    roots=None,
):
    version_filters_enabled = settings.get("enable_version_filters", True)
    start_version = settings.get("version_filter_start") or ""
    end_version = settings.get("version_filter_end") or ""
    if not version_filters_enabled:
        start_version = ""
        end_version = ""
    start_date = version_releases.get(start_version)
    end_date = version_releases.get(end_version)
    start_limit = datetime.combine(start_date, time.min) if start_date else None
    latest_version_key = next(reversed(version_releases)) if version_releases else None
    if end_version and latest_version_key and end_version == latest_version_key:
        end_limit = datetime.combine(date.today(), time.max)
    else:
        end_limit = datetime.combine(end_date, time.max) if end_date else None
    if start_limit and end_limit and start_limit > end_limit:
        start_limit, end_limit = end_limit, start_limit

    data_rows = []
    ignored_mods = set(settings.get("ignored_mods", []))
    show_ignored = settings.get("show_ignored", False)
    show_packages = settings.get("show_package_mods", True)
    show_scripts = settings.get("show_ts4script_mods", True)

    normalized_roots = [
        os.path.normcase(os.path.abspath(root))
        for root in (roots or [])
        if root
    ]

    def _resolve_parent(path):
        if not path:
            return ""
        return os.path.normcase(os.path.abspath(os.path.dirname(path)))

    def _relative_parent_display(parent_path: str) -> str:
        if not parent_path:
            return "."
        for root in normalized_roots:
            try:
                rel_parent = os.path.relpath(parent_path, root)
            except ValueError:
                continue
            if rel_parent == "." or not rel_parent.startswith(".."):
                return rel_parent
        return parent_path

    package_entries = {}
    for pkg, pkg_path in package_files.items():
        normalized_name = normalize_mod_basename(pkg)
        hash_source = normalized_name or os.path.splitext(pkg)[0].casefold()
        package_entries[pkg] = {
            "path": pkg_path,
            "base": os.path.splitext(pkg)[0],
            "normalized": normalized_name,
            "parent": _resolve_parent(pkg_path),
            "hash": stable_mod_name_hash(hash_source),
        }

    script_entries = {}
    for script, script_path in ts4script_files.items():
        normalized_name = normalize_mod_basename(script)
        hash_source = normalized_name or os.path.splitext(script)[0].casefold()
        script_entries[script] = {
            "path": script_path,
            "base": os.path.splitext(script)[0],
            "normalized": normalized_name,
            "parent": _resolve_parent(script_path),
            "hash": stable_mod_name_hash(hash_source),
        }

    unpaired_packages = set(package_entries.keys())
    unpaired_scripts = set(script_entries.keys())
    matches: Dict[str, Dict[str, str]] = {}

    # Pass 1 – même base normalisée
    scripts_by_norm = defaultdict(list)
    for script_name in unpaired_scripts:
        scripts_by_norm[script_entries[script_name]["normalized"]].append(script_name)
    for script_list in scripts_by_norm.values():
        script_list.sort(key=str.casefold)

    for pkg_name in list(unpaired_packages):
        pkg_info = package_entries[pkg_name]
        norm_name = pkg_info["normalized"]
        if not norm_name:
            continue
        candidates = scripts_by_norm.get(norm_name)
        if not candidates:
            continue
        script_name = next((candidate for candidate in candidates if candidate in unpaired_scripts), None)
        if not script_name:
            continue
        normalized_display = norm_name or pkg_info["base"].casefold()
        matches[pkg_name] = {
            "script": script_name,
            "confidence": "Élevée",
            "tooltip": (
                f"Appariement basé sur un nom normalisé identique ({normalized_display})."
            ),
        }
        unpaired_packages.remove(pkg_name)
        unpaired_scripts.remove(script_name)

    # Pass 2 – même dossier parent
    scripts_by_parent = defaultdict(list)
    for script_name in unpaired_scripts:
        scripts_by_parent[script_entries[script_name]["parent"]].append(script_name)
    for script_list in scripts_by_parent.values():
        script_list.sort(key=str.casefold)

    for pkg_name in list(unpaired_packages):
        pkg_info = package_entries[pkg_name]
        parent = pkg_info["parent"]
        candidates = scripts_by_parent.get(parent)
        if not candidates:
            continue
        script_name = next((candidate for candidate in candidates if candidate in unpaired_scripts), None)
        if not script_name:
            continue
        rel_parent = _relative_parent_display(parent)
        if rel_parent in (".", ""):
            folder_display = "(racine du dossier mods)"
        else:
            folder_display = rel_parent.replace("\\", "/")
        tooltip = (
            f"Appariement basé sur le même dossier parent : {folder_display}."
        )
        matches[pkg_name] = {
            "script": script_name,
            "confidence": "Moyenne",
            "tooltip": tooltip,
        }
        unpaired_packages.remove(pkg_name)
        unpaired_scripts.remove(script_name)

    # Pass 3 – similarité + fallback hash
    scripts_by_prefix = defaultdict(list)
    scripts_by_length = defaultdict(list)
    for script_name in unpaired_scripts:
        info = script_entries[script_name]
        normalized = info["normalized"] or info["base"].casefold()
        if normalized:
            if len(normalized) >= 2:
                scripts_by_prefix[(2, normalized[:2])].append(script_name)
            scripts_by_prefix[(1, normalized[:1])].append(script_name)
        else:
            scripts_by_prefix[(0, "")].append(script_name)
        scripts_by_length[len(normalized)].append(script_name)
    for script_list in scripts_by_prefix.values():
        script_list.sort(key=str.casefold)

    similarity_candidates = []
    for pkg_name in list(unpaired_packages):
        pkg_info = package_entries[pkg_name]
        normalized = pkg_info["normalized"] or pkg_info["base"].casefold()
        if not normalized and not pkg_info["base"]:
            continue
        prefixes = []
        if normalized:
            if len(normalized) >= 2:
                prefixes.append((2, normalized[:2]))
            prefixes.append((1, normalized[:1]))
        else:
            base_lower = pkg_info["base"].casefold()
            if len(base_lower) >= 2:
                prefixes.append((2, base_lower[:2]))
            if base_lower:
                prefixes.append((1, base_lower[:1]))
        if not prefixes:
            prefixes.append((0, ""))

        seen_scripts = set()
        for prefix in prefixes:
            for script_name in scripts_by_prefix.get(prefix, []):
                if script_name not in unpaired_scripts or script_name in seen_scripts:
                    continue
                seen_scripts.add(script_name)
                script_info = script_entries[script_name]
                script_norm = script_info["normalized"] or script_info["base"].casefold()
                ratio = SequenceMatcher(None, normalized, script_norm).ratio()
                if ratio < MIN_SIMILARITY_RATIO:
                    continue
                hash_gap = abs(pkg_info["hash"] - script_info["hash"])
                similarity_candidates.append((ratio, hash_gap, pkg_name, script_name))
                if len(seen_scripts) >= MAX_SIMILARITY_CANDIDATES:
                    break
            if len(seen_scripts) >= MAX_SIMILARITY_CANDIDATES:
                break

        if not seen_scripts:
            target_length = len(normalized)
            length_offsets = [0, 1, -1, 2, -2]
            for offset in length_offsets:
                candidate_length = target_length + offset
                if candidate_length < 0:
                    continue
                for script_name in scripts_by_length.get(candidate_length, []):
                    if script_name not in unpaired_scripts or script_name in seen_scripts:
                        continue
                    seen_scripts.add(script_name)
                    script_info = script_entries[script_name]
                    script_norm = script_info["normalized"] or script_info["base"].casefold()
                    ratio = SequenceMatcher(None, normalized, script_norm).ratio()
                    if ratio < MIN_SIMILARITY_RATIO:
                        continue
                    hash_gap = abs(pkg_info["hash"] - script_info["hash"])
                    similarity_candidates.append((ratio, hash_gap, pkg_name, script_name))
                    if len(seen_scripts) >= MAX_SIMILARITY_CANDIDATES:
                        break
                if len(seen_scripts) >= MAX_SIMILARITY_CANDIDATES:
                    break

    similarity_candidates.sort(key=lambda item: (-item[0], item[1], item[2], item[3]))

    for ratio, hash_gap, pkg_name, script_name in similarity_candidates:
        if pkg_name not in unpaired_packages or script_name not in unpaired_scripts:
            continue
        confidence = similarity_confidence_label(ratio)
        hash_note = f" (écart hash {hash_gap})" if hash_gap else ""
        tooltip = (
            f"Appariement basé sur la similarité des noms (SequenceMatcher {ratio:.2f}). "
            f"Départage assuré par un hash stable pour les égalités{hash_note}."
        )
        matches[pkg_name] = {
            "script": script_name,
            "confidence": confidence,
            "tooltip": tooltip,
        }
        unpaired_packages.remove(pkg_name)
        unpaired_scripts.remove(script_name)

    # Lignes finales
    for pkg, pkg_info in package_entries.items():
        pkg_path = pkg_info["path"]
        pkg_date = package_dates.get(pkg_path)
        match_info = matches.get(pkg)
        script_name = match_info["script"] if match_info else ""
        script_path = ts4script_files.get(script_name) if script_name else None
        script_date = script_dates.get(script_path) if script_path else None

        mod_latest_date = max((dt for dt in (pkg_date, script_date) if dt is not None), default=None)

        if end_limit and mod_latest_date and mod_latest_date > end_limit:
            continue
        if start_limit and mod_latest_date and mod_latest_date < start_limit:
            continue

        has_package = True
        has_script = script_path is not None
        if not ((has_package and show_packages) or (has_script and show_scripts)):
            continue

        candidates = [name for name in (pkg, script_name if script_path else None) if name]
        ignored = any(name in ignored_mods for name in candidates)
        if ignored and not show_ignored:
            continue

        status = "X" if script_path else "MS"
        version = estimate_version_from_dates(pkg_date, script_date, version_releases)
        confidence_value = match_info["confidence"] if match_info else "—"
        confidence_tooltip = match_info["tooltip"] if match_info else "Aucun appariement détecté."

        data_rows.append({
            "status": status,
            "package": pkg,
            "package_date": format_datetime(pkg_date),
            "script": script_name if script_path else "",
            "script_date": format_datetime(script_date),
            "version": version,
            "confidence": confidence_value,
            "confidence_tooltip": confidence_tooltip,
            "ignored": ignored,
            "ignore_candidates": candidates or [pkg],
            "paths": [path for path in (pkg_path, script_path) if path],
        })

    for script_name in sorted(unpaired_scripts, key=str.casefold):
        script_path = ts4script_files.get(script_name)
        if not script_path:
            continue
        script_date = script_dates.get(script_path)

        if end_limit and script_date and script_date > end_limit:
            continue
        if start_limit and script_date and script_date < start_limit:
            continue
        if not show_scripts:
            continue

        candidates = [script_name]
        ignored = any(name in ignored_mods for name in candidates)
        if ignored and not show_ignored:
            continue

        status = "MP"
        version = estimate_version_from_dates(None, script_date, version_releases)

        data_rows.append({
            "status": status,
            "package": "",
            "package_date": "",
            "script": script_name,
            "script_date": format_datetime(script_date),
            "version": version,
            "confidence": "—",
            "confidence_tooltip": "Aucun package correspondant trouvé.",
            "ignored": ignored,
            "ignore_candidates": candidates,
            "paths": [script_path],
        })
    return data_rows


class ScanWorker(QtCore.QObject):
    progress = QtCore.pyqtSignal(int)
    chunkReady = QtCore.pyqtSignal(list)
    finished = QtCore.pyqtSignal(bool, str)
    error = QtCore.pyqtSignal(str)

    def __init__(
        self,
        roots: List[str],
        settings: Dict[str, object],
        cache: MutableMapping,
        stop_flag: threading.Event,
        chunk_size: int = 200,
    ):
        super().__init__()
        self.roots = [os.path.abspath(path) for path in roots if path]
        self.settings = copy.deepcopy(settings) if settings is not None else {}
        self.cache = cache or {}
        self.stop_flag = stop_flag
        self.chunk_size = max(1, int(chunk_size or 200))
        self.snapshot = {}
        self.snapshot_changed = False
        self.rows_total = 0
        self.logger = logging.getLogger("sims4_mod_manager.scan")
        raw_version_items = self.settings.pop("_version_releases", [])
        self.version_releases = OrderedDict()
        for version, date_str in raw_version_items:
            parsed = parse_release_date(date_str)
            if parsed is not None and version:
                self.version_releases[version] = parsed

    def run(self):
        self.logger.debug("Scan démarré sur %d racine(s)", len(self.roots))
        try:
            self._run_impl()
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.exception("Erreur inattendue pendant le scan : %s", exc)
            self.error.emit(str(exc))
            self.finished.emit(False, "Erreur")

    def _run_impl(self):
        if not self.roots:
            self.finished.emit(False, "Aucun dossier valide")
            return
        total_files = self._estimate_total_files()
        self.logger.debug("Estimation de %d fichier(s) à traiter", total_files)
        self.progress.emit(0)

        cache_entries = {}
        cache_entries_list = self.cache.get("entries") if isinstance(self.cache, dict) else None
        if isinstance(cache_entries_list, list):
            for entry in cache_entries_list:
                if not isinstance(entry, dict):
                    continue
                key = str(entry.get("path") or "").strip()
                if key:
                    cache_entries[key] = entry

        package_files: Dict[str, str] = {}
        ts4script_files: Dict[str, str] = {}
        snapshot_entries = []
        file_stats: Dict[str, os.stat_result] = {}
        unchanged_paths: Set[str] = set()
        processed_files = 0

        for root in self.roots:
            self.logger.debug("Exploration du dossier %s", root)
            if self.stop_flag.is_set():
                self.logger.info("Scan interrompu avant exploration complète")
                self.finished.emit(False, "Cancelled")
                return
            for directory, entry in self._iter_directory(root):
                if self.stop_flag.is_set():
                    self.logger.info("Scan interrompu pendant l'exploration")
                    self.finished.emit(False, "Cancelled")
                    return
                full_path = os.path.join(directory, entry.name)
                try:
                    stat_result = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                extension = os.path.splitext(entry.name)[1].lower()
                relative_path = os.path.relpath(full_path, root).replace("\\", "/")
                cache_entry = cache_entries.get(relative_path)
                if cache_entry:
                    cached_mtime = int(cache_entry.get("mtime", 0))
                    cached_size = int(cache_entry.get("size", 0))
                    if int(stat_result.st_mtime) == cached_mtime and int(stat_result.st_size) == cached_size:
                        unchanged_paths.add(full_path)
                if extension not in {".package", ".ts4script", ".zip"}:
                    continue
                entry_type = (
                    "package"
                    if extension == ".package"
                    else "ts4script"
                    if extension == ".ts4script"
                    else "archive"
                )
                snapshot_entries.append(
                    {
                        "path": relative_path,
                        "mtime": int(stat_result.st_mtime),
                        "size": int(stat_result.st_size),
                        "type": entry_type,
                    }
                )
                if extension == ".package":
                    package_files[entry.name] = full_path
                elif extension == ".ts4script":
                    ts4script_files[entry.name] = full_path
                file_stats[full_path] = stat_result
                processed_files += 1
                if total_files:
                    percent = int((processed_files / total_files) * 100)
                    self.progress.emit(min(percent, 100))

        snapshot_entries.sort(key=lambda item: item["path"].casefold())
        root_value = self.roots[0] if self.roots else ""
        self.snapshot = {
            "root": root_value.replace("\\", "/"),
            "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "entries": snapshot_entries,
        }

        previous_snapshot = self.cache if isinstance(self.cache, dict) else None
        self.snapshot_changed = bool(previous_snapshot) and not mod_scan_snapshots_equal(previous_snapshot, self.snapshot)
        self.logger.debug("Instantané modifié : %s", self.snapshot_changed)

        package_dates: Dict[str, Optional[datetime]] = {}
        script_dates: Dict[str, Optional[datetime]] = {}

        def _schedule_dates(paths, target):
            changed = []
            for path in paths:
                if path in unchanged_paths and path in file_stats:
                    stat_result = file_stats[path]
                    target[path] = datetime.fromtimestamp(stat_result.st_mtime)
                else:
                    changed.append(path)
            if not changed:
                return None, []
            executor = ThreadPoolExecutor(max_workers=12)
            futures = [executor.submit(get_file_date, path) for path in changed]
            return executor, list(zip(futures, changed))

        package_executor, package_tasks = _schedule_dates(package_files.values(), package_dates)
        script_executor, script_tasks = _schedule_dates(ts4script_files.values(), script_dates)

        for future, path in package_tasks:
            try:
                package_dates[path] = future.result()
            except Exception:
                package_dates[path] = None

        for future, path in script_tasks:
            try:
                script_dates[path] = future.result()
            except Exception:
                script_dates[path] = None

        if package_executor is not None:
            package_executor.shutdown(wait=True)
        if script_executor is not None:
            script_executor.shutdown(wait=True)

        rows = build_mod_rows(
            package_files,
            ts4script_files,
            self.settings,
            self.version_releases,
            package_dates,
            script_dates,
            roots=self.roots,
        )
        self.rows_total = len(rows)
        self.logger.debug("%d ligne(s) générée(s) pour la table", self.rows_total)

        for chunk in self._chunk_rows(rows):
            if self.stop_flag.is_set():
                self.logger.info("Scan interrompu avant l'émission du dernier paquet")
                self.finished.emit(False, "Cancelled")
                return
            self.chunkReady.emit(chunk)
            self.logger.debug("Paquet de %d ligne(s) envoyé", len(chunk))

        save_mod_scan_cache(self.snapshot)
        self.progress.emit(100)
        self.logger.info("Scan terminé avec succès")
        self.finished.emit(True, "OK")

    def _chunk_rows(self, rows: List[dict]):
        chunk_size = self.chunk_size
        for index in range(0, len(rows), chunk_size):
            yield rows[index : index + chunk_size]

    def _is_supported(self, entry: os.DirEntry) -> bool:
        if not entry.is_file(follow_symlinks=False):
            return False
        return os.path.splitext(entry.name)[1].lower() in {".package", ".ts4script", ".zip"}

    def _iter_directory(self, root: str):
        stack = [root]
        while stack:
            current = stack.pop()
            if self.stop_flag.is_set():
                return
            try:
                with os.scandir(current) as iterator:
                    for entry in iterator:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif self._is_supported(entry):
                            yield current, entry
            except OSError:
                continue

    def _estimate_total_files(self) -> int:
        total = 0
        stack = list(self.roots)
        while stack:
            current = stack.pop()
            if self.stop_flag.is_set():
                self.logger.debug("Arrêt demandé pendant l'estimation")
                return total
            try:
                with os.scandir(current) as iterator:
                    for entry in iterator:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif self._is_supported(entry):
                            total += 1
            except OSError:
                continue
        self.logger.debug("Estimation terminée : %d fichier(s)", total)
        return total


class ModsModel(QtCore.QAbstractTableModel):
    COLUMN_KEYS = [
        "status",
        "package",
        "package_date",
        "script",
        "script_date",
        "version",
        "confidence",
        "ignored",
    ]
    HEADERS = [
        "État",
        "Fichier .package",
        "Date .package",
        "Fichier .ts4script",
        "Date .ts4script",
        "Version",
        "Confiance",
        "Ignoré",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: List[dict] = []

    def rowCount(self, parent=QtCore.QModelIndex()):  # noqa: N802 - Qt API
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent=QtCore.QModelIndex()):  # noqa: N802 - Qt API
        if parent.isValid():
            return 0
        return len(self.COLUMN_KEYS)

    def data(self, index, role=QtCore.Qt.DisplayRole):  # noqa: N802 - Qt API
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        key = self.COLUMN_KEYS[index.column()]
        if role == QtCore.Qt.DisplayRole:
            if key == "ignored":
                return "Oui" if row.get("ignored") else "Non"
            value = row.get(key, "")
            return "" if value is None else str(value)
        if role == QtCore.Qt.ToolTipRole and key == "confidence":
            return row.get("confidence_tooltip", "")
        return None

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):  # noqa: N802
        if role != QtCore.Qt.DisplayRole:
            return None
        if orientation == QtCore.Qt.Horizontal:
            if 0 <= section < len(self.HEADERS):
                return self.HEADERS[section]
            return ""
        return str(section + 1)

    def flags(self, index):  # noqa: N802 - Qt API
        if not index.isValid():
            return QtCore.Qt.NoItemFlags
        return QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable

    def clear(self):
        self.beginResetModel()
        self._rows = []
        self.endResetModel()

    def set_rows(self, rows: Sequence[dict]):
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def add_rows(self, rows: Sequence[dict]):
        if not rows:
            return
        start = len(self._rows)
        end = start + len(rows) - 1
        self.beginInsertRows(QtCore.QModelIndex(), start, end)
        self._rows.extend(rows)
        self.endInsertRows()

    def get_row(self, row_index: int):
        if 0 <= row_index < len(self._rows):
            return self._rows[row_index]
        return None

    def remove_row(self, row_index: int):
        if not (0 <= row_index < len(self._rows)):
            return
        self.beginRemoveRows(QtCore.QModelIndex(), row_index, row_index)
        self._rows.pop(row_index)
        self.endRemoveRows()


class ModsProxyModel(QtCore.QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter_text = ""
        self._show_search_results = True

    def setFilterFixedString(self, pattern):  # noqa: N802 - Qt API
        self._filter_text = str(pattern or "")
        super().setFilterFixedString(pattern)

    def set_show_search_results(self, enabled: bool):
        self._show_search_results = bool(enabled)
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):  # noqa: N802 - Qt API
        if not self._show_search_results:
            return True
        query = self._filter_text.strip().casefold()
        if not query:
            return True
        source_model = self.sourceModel()
        if not isinstance(source_model, ModsModel):
            return super().filterAcceptsRow(source_row, source_parent)
        row = source_model.get_row(source_row)
        if not row:
            return False
        values = [
            str(row.get("status", "")),
            str(row.get("package", "")),
            str(row.get("package_date", "")),
            str(row.get("script", "")),
            str(row.get("script_date", "")),
            str(row.get("version", "")),
            str(row.get("confidence", "")),
            "oui" if row.get("ignored") else "non",
        ]
        tooltip = row.get("confidence_tooltip")
        if tooltip:
            values.append(str(tooltip))
        values.extend(str(candidate) for candidate in row.get("ignore_candidates", []))
        values.extend(str(path) for path in row.get("paths", []))
        for value in values:
            if query in value.casefold():
                return True
        return False

def export_to_excel(save_path, data_rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "Mods"

    headers = [
        "État",
        "Fichier .package",
        "Date .package",
        "Fichier .ts4script",
        "Date .ts4script",
        "Version",
        "Confiance",
        "Ignoré",
    ]
    for idx, h in enumerate(headers, start=1):
        ws.cell(row=1, column=idx, value=h)

    for row_idx, row in enumerate(data_rows, start=2):
        for col_idx, value in enumerate(row, start=1):
            ws.cell(row=row_idx, column=col_idx, value=value)

    wb.save(save_path)


class AddUpdateDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ajouter une mise à jour")
        self.setModal(True)

        layout = QtWidgets.QFormLayout(self)
        self.version_edit = QtWidgets.QLineEdit(self)
        self.version_edit.setPlaceholderText("1.118.257.1020")
        self.date_edit = QtWidgets.QDateEdit(self)
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd/MM/yyyy")
        self.date_edit.setDate(QtCore.QDate.currentDate())

        layout.addRow("Numéro de version :", self.version_edit)
        layout.addRow("Date de sortie :", self.date_edit)

        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def accept(self):
        if not self.version_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, "Informations manquantes", "Indique un numéro de version valide.")
            return
        super().accept()

    def get_values(self):
        return self.version_edit.text().strip(), self.date_edit.date()


class ConfigurationDialog(QtWidgets.QDialog):
    def __init__(self, parent, settings):
        super().__init__(parent)
        self.setWindowTitle("Configuration")
        self.setModal(True)
        self._parent = parent

        layout = QtWidgets.QVBoxLayout()

        self.mod_directory_edit = QtWidgets.QLineEdit(self)
        self.mod_directory_edit.setText(settings.get("mod_directory", ""))
        mod_dir_browse = QtWidgets.QPushButton("Parcourir...")
        mod_dir_browse.clicked.connect(lambda: self._browse_directory(self.mod_directory_edit))

        mod_dir_layout = QtWidgets.QHBoxLayout()
        mod_dir_layout.addWidget(QtWidgets.QLabel("Dossier des mods :"))
        mod_dir_layout.addWidget(self.mod_directory_edit)
        mod_dir_layout.addWidget(mod_dir_browse)
        layout.addLayout(mod_dir_layout)

        self.cache_directory_edit = QtWidgets.QLineEdit(self)
        self.cache_directory_edit.setText(settings.get("sims_cache_directory", ""))
        cache_dir_browse = QtWidgets.QPushButton("Parcourir...")
        cache_dir_browse.clicked.connect(lambda: self._browse_directory(self.cache_directory_edit))

        cache_dir_layout = QtWidgets.QHBoxLayout()
        cache_dir_layout.addWidget(QtWidgets.QLabel("Dossier caches sims :"))
        cache_dir_layout.addWidget(self.cache_directory_edit)
        cache_dir_layout.addWidget(cache_dir_browse)
        layout.addLayout(cache_dir_layout)

        self.backups_directory_edit = QtWidgets.QLineEdit(self)
        self.backups_directory_edit.setText(settings.get("backups_directory", ""))
        backups_dir_browse = QtWidgets.QPushButton("Parcourir...")
        backups_dir_browse.clicked.connect(lambda: self._browse_directory(self.backups_directory_edit))

        backups_dir_layout = QtWidgets.QHBoxLayout()
        backups_dir_layout.addWidget(QtWidgets.QLabel("Dossier Backups :"))
        backups_dir_layout.addWidget(self.backups_directory_edit)
        backups_dir_layout.addWidget(backups_dir_browse)
        layout.addLayout(backups_dir_layout)

        self.sims_executable_edit = QtWidgets.QLineEdit(self)
        self.sims_executable_edit.setText(settings.get("sims_executable_path", ""))
        sims_exec_browse = QtWidgets.QPushButton("Parcourir...")
        sims_exec_browse.clicked.connect(self._browse_executable)

        sims_exec_layout = QtWidgets.QHBoxLayout()
        sims_exec_layout.addWidget(QtWidgets.QLabel("Exécutable TS4_X64.exe :"))
        sims_exec_layout.addWidget(self.sims_executable_edit)
        sims_exec_layout.addWidget(sims_exec_browse)
        layout.addLayout(sims_exec_layout)

        self.sims_arguments_edit = QtWidgets.QLineEdit(self)
        self.sims_arguments_edit.setText(settings.get("sims_executable_arguments", ""))
        self.sims_arguments_edit.setPlaceholderText("Arguments supplémentaires (ex: -w)")

        sims_args_layout = QtWidgets.QHBoxLayout()
        sims_args_layout.addWidget(QtWidgets.QLabel("Arguments TS4_X64.exe :"))
        sims_args_layout.addWidget(self.sims_arguments_edit)
        layout.addLayout(sims_args_layout)

        self.log_extensions_edit = QtWidgets.QLineEdit(self)
        extra_extensions = ", ".join(settings.get("log_extra_extensions", []))
        self.log_extensions_edit.setText(extra_extensions)
        self.log_extensions_edit.setPlaceholderText("Extensions supplémentaires (.mdmp, .html, ...)")

        logs_ext_layout = QtWidgets.QHBoxLayout()
        logs_ext_layout.addWidget(QtWidgets.QLabel("Extensions de logs (supplémentaires) :"))
        logs_ext_layout.addWidget(self.log_extensions_edit)
        layout.addLayout(logs_ext_layout)

        self.log_level_combo = QtWidgets.QComboBox(self)
        for level_name in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            self.log_level_combo.addItem(level_name, level_name)
        current_level = settings.get("log_level", DEFAULT_LOG_LEVEL)
        current_index = self.log_level_combo.findData(current_level)
        if current_index == -1:
            current_index = 0
        self.log_level_combo.setCurrentIndex(current_index)

        log_level_layout = QtWidgets.QHBoxLayout()
        log_level_layout.addWidget(QtWidgets.QLabel("Niveau de log :"))
        log_level_layout.addWidget(self.log_level_combo)
        layout.addLayout(log_level_layout)

        self.grab_logs_ignore_edit = QtWidgets.QPlainTextEdit(self)
        self.grab_logs_ignore_edit.setPlaceholderText("last_crash.txt\nExceptionLog.txt")
        ignore_lines = "\n".join(settings.get("grab_logs_ignore_files", []))
        self.grab_logs_ignore_edit.setPlainText(ignore_lines)
        self.grab_logs_ignore_edit.setFixedHeight(100)

        ignore_layout = QtWidgets.QVBoxLayout()
        ignore_layout.addWidget(QtWidgets.QLabel("Fichiers de logs à ignorer (un par ligne ou séparés par des virgules) :"))
        ignore_layout.addWidget(self.grab_logs_ignore_edit)
        layout.addLayout(ignore_layout)

        version_group = QtWidgets.QGroupBox("Gestion des versions de patch", self)
        version_layout = QtWidgets.QVBoxLayout(version_group)
        self.version_list_widget = QtWidgets.QListWidget(version_group)
        self.version_list_widget.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.version_list_widget.setMinimumHeight(150)
        version_layout.addWidget(self.version_list_widget)
        self.add_version_button = QtWidgets.QPushButton("Add update info", version_group)
        self.add_version_button.clicked.connect(self._open_add_version_dialog)
        version_layout.addWidget(self.add_version_button)
        layout.addWidget(version_group)

        self._refresh_version_list()

        button_box = QtWidgets.QDialogButtonBox()
        save_button = button_box.addButton("Sauvegarder", QtWidgets.QDialogButtonBox.AcceptRole)
        cancel_button = button_box.addButton(QtWidgets.QDialogButtonBox.Cancel)
        save_button.clicked.connect(self._save_configuration)
        cancel_button.clicked.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

    def _refresh_version_list(self):
        if not hasattr(self, "version_list_widget"):
            return
        self.version_list_widget.clear()
        if self._parent is None:
            return
        for version, release_date in self._parent.get_version_entries():
            self.version_list_widget.addItem(f"{version} – {format_release_date(release_date)}")

    def _open_add_version_dialog(self):
        if self._parent is None:
            return
        dialog = AddUpdateDialog(self)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        version, release_date = dialog.get_values()
        success, message = self._parent.add_version_release(version, release_date)
        if success:
            QtWidgets.QMessageBox.information(self, "Version ajoutée", message)
            self._refresh_version_list()
        else:
            QtWidgets.QMessageBox.warning(self, "Ajout impossible", message)

    def _browse_directory(self, target_edit):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Choisir un dossier")
        if folder:
            target_edit.setText(folder)

    def _browse_executable(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Sélectionner TS4_X64.exe",
            "",
            "Executable Sims 4 (TS4_X64.exe);;Tous les fichiers (*)"
        )
        if file_path:
            self.sims_executable_edit.setText(file_path)

    def _save_configuration(self):
        mod_directory = self.mod_directory_edit.text().strip()
        cache_directory = self.cache_directory_edit.text().strip()
        backups_directory = self.backups_directory_edit.text().strip()
        sims_executable_path = self.sims_executable_edit.text().strip()
        sims_executable_arguments = self.sims_arguments_edit.text().strip()
        log_extensions_text = self.log_extensions_edit.text().strip()
        ignore_text = self.grab_logs_ignore_edit.toPlainText()

        extra_extensions = []
        if log_extensions_text:
            for part in re.split(r"[,;\s]+", log_extensions_text):
                cleaned = part.strip()
                if not cleaned:
                    continue
                if not cleaned.startswith("."):
                    cleaned = f".{cleaned}"
                extra_extensions.append(cleaned.lower())

        ignore_files = []
        seen_ignore = set()
        if ignore_text:
            for part in re.split(r"[,;\n]+", ignore_text):
                cleaned = part.strip()
                if not cleaned:
                    continue
                key = cleaned.lower()
                if key in seen_ignore:
                    continue
                seen_ignore.add(key)
                ignore_files.append(cleaned)

        log_level = DEFAULT_LOG_LEVEL
        if hasattr(self, "log_level_combo"):
            selected = self.log_level_combo.currentData()
            if isinstance(selected, str) and selected.upper() in LOG_LEVEL_CHOICES:
                log_level = selected.upper()

        if self._parent is not None:
            self._parent.apply_configuration(
                mod_directory,
                cache_directory,
                backups_directory,
                sims_executable_path,
                sims_executable_arguments,
                sorted(set(extra_extensions)),
                ignore_files,
                log_level,
            )
        self.accept()


class FileDropDialog(QtWidgets.QDialog):
    def __init__(self, title, instruction, drop_handler, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(520, 300)
        self.setAcceptDrops(True)
        self._drop_handler = drop_handler

        layout = QtWidgets.QVBoxLayout(self)

        info_label = QtWidgets.QLabel(instruction, self)
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self.drop_label = QtWidgets.QLabel("Déposez vos fichiers ici", self)
        self.drop_label.setAlignment(QtCore.Qt.AlignCenter)
        self.drop_label.setMinimumHeight(100)
        self._drop_idle_style = "QLabel { border: 2px dashed #aaaaaa; padding: 24px; background-color: #3a3a3a; }"
        self._drop_active_style = "QLabel { border: 2px solid #00aa88; padding: 24px; background-color: #2a2a2a; }"
        self.drop_label.setStyleSheet(self._drop_idle_style)
        layout.addWidget(self.drop_label)

        close_button = QtWidgets.QPushButton("Fermer", self)
        close_button.clicked.connect(self.reject)
        layout.addWidget(close_button, alignment=QtCore.Qt.AlignRight)

    def dragEnterEvent(self, event):
        if self._contains_supported_files(event):
            event.acceptProposedAction()
            self._set_drop_active(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        super().dragLeaveEvent(event)
        self._set_drop_active(False)

    def dropEvent(self, event):
        if not event.mimeData().hasUrls():
            event.ignore()
            self._set_drop_active(False)
            return

        file_paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        success_messages, error_messages = self._drop_handler(file_paths)

        if success_messages:
            QtWidgets.QMessageBox.information(
                self,
                "Opération terminée",
                "\n".join(success_messages),
            )
        if error_messages:
            QtWidgets.QMessageBox.warning(
                self,
                "Certaines opérations ont échoué",
                "\n".join(error_messages),
            )

        if success_messages and not error_messages:
            self.accept()
        elif success_messages:
            # Laisser la fenêtre ouverte pour d'éventuels ajouts complémentaires
            self._set_drop_active(False)
        else:
            self._set_drop_active(False)

        event.acceptProposedAction()

    def _contains_supported_files(self, event):
        if not event.mimeData().hasUrls():
            return False
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            if os.path.splitext(url.toLocalFile())[1].lower() in SUPPORTED_INSTALL_EXTENSIONS:
                return True
        return False

    def _set_drop_active(self, active):
        self.drop_label.setStyleSheet(self._drop_active_style if active else self._drop_idle_style)


class ModInstallerDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, mod_directory=""):
        super().__init__(parent)
        self.setWindowTitle("Mod Installer")
        self.setModal(True)
        self.resize(720, 420)
        self.setAcceptDrops(True)

        self.mod_directory = mod_directory
        self.installations_performed = False
        self.installed_mods = load_installed_mods()

        layout = QtWidgets.QVBoxLayout(self)

        info_label = QtWidgets.QLabel(
            "Glissez-déposez un fichier .package, .ts4script ou .zip pour l'installer dans le dossier des mods configuré."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        mod_dir_display = mod_directory if mod_directory else "(dossier non défini)"
        self.target_directory_label = QtWidgets.QLabel(f"Dossier cible : {mod_dir_display}")
        self.target_directory_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(self.target_directory_label)

        self.drop_label = QtWidgets.QLabel("Déposez vos fichiers ici")
        self.drop_label.setAlignment(QtCore.Qt.AlignCenter)
        self.drop_label.setMinimumHeight(80)
        self._drop_idle_style = "QLabel { border: 2px dashed #aaaaaa; padding: 24px; background-color: #3a3a3a; }"
        self._drop_active_style = "QLabel { border: 2px solid #00aa88; padding: 24px; background-color: #2a2a2a; }"
        self.drop_label.setStyleSheet(self._drop_idle_style)
        layout.addWidget(self.drop_label)

        self.table = QtWidgets.QTableWidget(self)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Mod",
            "Type",
            "Installé le",
            "Dossier",
            "Addons",
        ])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for column in range(1, self.table.columnCount()):
            self.table.horizontalHeader().setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeToContents)
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.table, stretch=1)

        close_button = QtWidgets.QPushButton("Fermer", self)
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button, alignment=QtCore.Qt.AlignRight)

        self.refresh_table()

    def dragEnterEvent(self, event):
        if self._contains_supported_files(event):
            event.acceptProposedAction()
            self._set_drop_active(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        super().dragLeaveEvent(event)
        self._set_drop_active(False)

    def dropEvent(self, event):
        if not event.mimeData().hasUrls():
            event.ignore()
            self._set_drop_active(False)
            return

        file_paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        success_entries = []
        error_messages = []

        for path in file_paths:
            success, message = self.install_mod_from_path(path)
            if success and message:
                success_entries.append(message)
            elif (not success) and message:
                error_messages.append(message)

        if success_entries:
            QtWidgets.QMessageBox.information(
                self,
                "Installation terminée",
                "\n".join(success_entries),
            )
        if error_messages:
            QtWidgets.QMessageBox.warning(
                self,
                "Installation incomplète",
                "\n".join(error_messages),
            )

        event.acceptProposedAction()
        self._set_drop_active(False)

    def _set_drop_active(self, active):
        self.drop_label.setStyleSheet(self._drop_active_style if active else self._drop_idle_style)

    def _contains_supported_files(self, event):
        if not event.mimeData().hasUrls():
            return False
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            if self._is_supported_extension(url.toLocalFile()):
                return True
        return False

    @staticmethod
    def _is_supported_extension(file_path):
        return os.path.splitext(file_path)[1].lower() in SUPPORTED_INSTALL_EXTENSIONS

    def _collect_tracked_folders(self):
        tracked = set()
        for entry in self.installed_mods:
            folder = entry.get("target_folder")
            if not folder:
                continue
            normalized = os.path.normcase(os.path.abspath(folder))
            tracked.add(normalized)
        return tracked

    def _find_untracked_duplicates(self, file_path):
        if not self.mod_directory or not os.path.isdir(self.mod_directory):
            return []
        file_name = os.path.basename(file_path)
        if not file_name:
            return []
        tracked = self._collect_tracked_folders()
        duplicates = []
        for root, dirs, files in os.walk(self.mod_directory):
            for candidate in files:
                if candidate.lower() != file_name.lower():
                    continue
                candidate_path = os.path.join(root, candidate)
                try:
                    if os.path.samefile(candidate_path, file_path):
                        continue
                except OSError:
                    pass
                parent_dir = os.path.normcase(os.path.abspath(root))
                if parent_dir in tracked:
                    continue
                duplicates.append(os.path.abspath(candidate_path))
        return duplicates

    def install_mod_from_path(self, file_path):
        if not os.path.isfile(file_path):
            return False, f"Fichier introuvable : {file_path}"

        if not self._is_supported_extension(file_path):
            return False, f"Extension non supportée : {os.path.basename(file_path)}"

        if not self.mod_directory or not os.path.isdir(self.mod_directory):
            return False, "Définissez d'abord un dossier de mods valide dans la configuration."

        sanitized_name = sanitize_mod_folder_name(file_path)
        extension = os.path.splitext(file_path)[1].lower()
        zip_plan = None
        display_name = os.path.splitext(os.path.basename(file_path))[0]

        duplicates_to_replace: List[str] = []

        if extension == ".zip":
            plan_result = build_zip_install_plan(
                file_path,
                mod_directory=self.mod_directory,
                default_mod_name=sanitized_name,
            )
            if not plan_result.success or plan_result.plan is None:
                return False, plan_result.message or "Impossible de préparer l'installation de l'archive."
            zip_plan = plan_result.plan
            sanitized_name = zip_plan.mod_folder_name
            target_folder = zip_plan.target_folder
            display_name = sanitized_name
        else:
            target_folder = os.path.join(self.mod_directory, sanitized_name)
            duplicates_to_replace = self._find_untracked_duplicates(file_path)
            if duplicates_to_replace:
                message_lines = [
                    "Le fichier existe déjà dans le dossier des mods en dehors du Mod Installer.",
                    "Chemins détectés :",
                ]
                message_lines.extend(duplicates_to_replace)
                message_lines.append("")
                message_lines.append("Souhaites-tu remplacer ces occurrences ?")
                response = QtWidgets.QMessageBox.question(
                    self,
                    "Fichier déjà présent",
                    "\n".join(message_lines),
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    QtWidgets.QMessageBox.Yes,
                )
                if response != QtWidgets.QMessageBox.Yes:
                    duplicates_to_replace = []

        replace_existing = False
        if not duplicates_to_replace and os.path.exists(target_folder):
            response = QtWidgets.QMessageBox.question(
                self,
                "Mod déjà installé",
                (
                    f"Le mod '{sanitized_name}' existe déjà dans le dossier des mods.\n"
                    "Voulez-vous le mettre à jour avec le fichier sélectionné ?"
                ),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.Yes,
            )
            if response != QtWidgets.QMessageBox.Yes:
                return False, f"Installation de '{display_name}' annulée."
            replace_existing = True

        if duplicates_to_replace:
            parent_directories = []
            for duplicate_path in duplicates_to_replace:
                parent_dir = os.path.dirname(duplicate_path)
                if parent_dir not in parent_directories:
                    parent_directories.append(parent_dir)
            success_messages = []
            for parent_dir in parent_directories:
                success, install_message, _ = self._install_file_to_target(
                    file_path,
                    parent_dir,
                    clean_before=False,
                    merge=True,
                    zip_plan=None,
                    skip_existing_prompt=True,
                )
                if not success:
                    return False, install_message
                success_messages.append(install_message)
                installed_at = datetime.utcnow().replace(microsecond=0).isoformat()
                self._record_installation({
                    "name": display_name,
                    "type": self._describe_install_type([file_path]),
                    "installed_at": installed_at,
                    "target_folder": parent_dir,
                    "source": os.path.basename(file_path),
                    "addons": [],
                })
            self.installations_performed = True
            return True, "\n".join(success_messages)

        success, install_message, _ = self._install_file_to_target(
            file_path,
            target_folder,
            clean_before=replace_existing,
            merge=False,
            zip_plan=zip_plan,
        )
        if not success:
            return False, install_message

        installed_at = datetime.utcnow().replace(microsecond=0).isoformat()
        self._record_installation({
            "name": display_name,
            "type": self._describe_install_type([file_path]),
            "installed_at": installed_at,
            "target_folder": target_folder,
            "source": os.path.basename(file_path),
            "addons": [],
        })

        self.installations_performed = True
        final_message = install_message or f"'{display_name}' installé avec succès."
        return True, final_message

    def _install_file_to_target(
        self,
        file_path,
        target_folder,
        *,
        clean_before=False,
        merge=False,
        zip_plan=None,
        skip_existing_prompt=False,
    ):
        extension = os.path.splitext(file_path)[1].lower()
        installed_entries = []
        plan_warnings: List[str] = []

        if clean_before and os.path.exists(target_folder):
            try:
                shutil.rmtree(target_folder)
            except OSError as exc:
                return False, f"Impossible de nettoyer le dossier existant : {exc}", []

        if extension == ".zip" and not zipfile.is_zipfile(file_path):
            return False, f"Le fichier n'est pas une archive zip valide : {os.path.basename(file_path)}", []

        try:
            os.makedirs(target_folder, exist_ok=True)
        except OSError as exc:
            return False, f"Impossible de créer le dossier cible : {exc}", []

        try:
            if extension in {".package", ".ts4script"}:
                destination_path = os.path.join(target_folder, os.path.basename(file_path))
                if os.path.exists(destination_path) and not clean_before:
                    if skip_existing_prompt:
                        response = QtWidgets.QMessageBox.Yes
                    else:
                        response = QtWidgets.QMessageBox.question(
                            self,
                            "Fichier déjà présent",
                            (
                                f"Le fichier '{os.path.basename(file_path)}' existe déjà dans le dossier cible.\n"
                                "Souhaitez-vous le remplacer ?"
                            ),
                            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                            QtWidgets.QMessageBox.Yes,
                        )
                    if response != QtWidgets.QMessageBox.Yes:
                        return False, f"Copie de '{os.path.basename(file_path)}' annulée.", []
                shutil.copy2(file_path, destination_path)
                installed_entries.append(os.path.basename(destination_path))
            else:
                if zip_plan is None:
                    plan_result = build_zip_install_plan(
                        file_path,
                        mod_directory=os.path.dirname(target_folder) or ".",
                        default_mod_name=os.path.basename(target_folder.rstrip("/\\")) or sanitize_mod_folder_name(target_folder),
                        existing_target=target_folder,
                    )
                    if not plan_result.success or plan_result.plan is None:
                        return False, plan_result.message or "Impossible de préparer l'extraction de l'archive.", []
                    zip_plan = plan_result.plan

                target_folder = zip_plan.target_folder
                target_root = os.path.abspath(target_folder)
                plan_warnings.extend(zip_plan.warnings)
                created_dirs: Set[Tuple[str, ...]] = set()
                written_paths: Set[Tuple[str, ...]] = set()

                with zipfile.ZipFile(file_path, "r") as archive:
                    for entry in zip_plan.entries:
                        relative_parts = list(entry.relative_parts)
                        if not relative_parts:
                            continue

                        for depth in range(1, len(relative_parts)):
                            dir_parts = tuple(relative_parts[:depth])
                            dir_path = os.path.join(target_root, *dir_parts)
                            if os.path.exists(dir_path):
                                if not os.path.isdir(dir_path):
                                    display = "/".join(dir_parts)
                                    return False, (
                                        f"Impossible de créer le dossier '{display}' : un fichier du même nom existe déjà."
                                    ), []
                            else:
                                os.makedirs(dir_path, exist_ok=True)
                                if dir_parts not in created_dirs:
                                    created_dirs.add(dir_parts)
                                    installed_entries.append("/".join(dir_parts) + "/")

                        relative_parts = _resolve_file_conflicts(
                            target_root,
                            relative_parts,
                            plan_warnings,
                            written_paths,
                        )
                        destination_path = os.path.join(target_root, *relative_parts)
                        destination_path = os.path.abspath(destination_path)
                        if os.path.commonpath([target_root, destination_path]) != target_root:
                            continue

                        parent_dir = os.path.dirname(destination_path)
                        os.makedirs(parent_dir, exist_ok=True)

                        with archive.open(entry.member_name, "r") as source, open(destination_path, "wb") as target_file:
                            shutil.copyfileobj(source, target_file)

                        display_path = "/".join(relative_parts)
                        if display_path not in installed_entries:
                            installed_entries.append(display_path)

                if not installed_entries:
                    return False, "L'archive ne contient aucun fichier exploitable après normalisation.", []
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            return False, f"Erreur lors de la copie : {exc}", []

        verb = "ajouté" if merge and not clean_before else "installé"
        message = f"{os.path.basename(file_path)} {verb} dans '{os.path.basename(target_folder)}'."
        if plan_warnings:
            message = message + "\n" + "\n".join(plan_warnings)
        return True, message, installed_entries

    @staticmethod
    def _describe_install_type(file_paths):
        extensions = []
        for path in file_paths:
            extension = os.path.splitext(path)[1].lower()
            if extension in {".package", ".ts4script"}:
                extensions.append(f"fichier {extension}")
            elif extension == ".zip":
                extensions.append("archive .zip")
        if not extensions:
            return ""
        if len(set(extensions)) == 1:
            return extensions[0]
        return ", ".join(sorted(set(extensions)))

    def _record_installation(self, entry):
        normalized_entry = dict(entry)
        normalized_entry["addons"] = normalize_addon_metadata(entry.get("addons", []))

        target = normalized_entry.get("target_folder")
        if not target:
            return
        replaced = False
        for existing in self.installed_mods:
            if existing.get("target_folder") == target:
                existing.update(normalized_entry)
                existing["addons"] = normalize_addon_metadata(existing.get("addons", []))
                replaced = True
                break
        if not replaced:
            normalized_entry.setdefault("addons", [])
            self.installed_mods.append(normalized_entry)
        self.installed_mods.sort(key=lambda item: item.get("installed_at", ""), reverse=True)
        save_installed_mods(self.installed_mods)
        self.refresh_table()

    def _show_context_menu(self, position):
        item = self.table.itemAt(position)
        if item is None:
            return
        row = item.row()
        if row < 0 or row >= len(self.installed_mods):
            return
        entry = self.installed_mods[row]

        menu = QtWidgets.QMenu(self)
        search_action = menu.addAction("Recherche Google")
        menu.addSeparator()
        open_action = menu.addAction("Ouvrir dans l'explorateur")
        addons_action = menu.addAction("Ajouter add-ons")
        remove_addons_action = menu.addAction("Supprimer add-ons")
        remove_addons_action.setEnabled(bool(entry.get("addons")))
        delete_action = menu.addAction("Supprimer le mod")
        update_action = menu.addAction("Mettre à jour le mod")

        chosen_action = menu.exec_(self.table.viewport().mapToGlobal(position))
        if chosen_action is None:
            return
        if chosen_action == search_action:
            self._open_google_search(entry)
        elif chosen_action == open_action:
            self._open_in_file_manager(entry.get("target_folder"))
        elif chosen_action == addons_action:
            self._prompt_addons(entry)
        elif chosen_action == remove_addons_action:
            self._prompt_remove_addons(entry)
        elif chosen_action == delete_action:
            self._delete_mod(entry)
        elif chosen_action == update_action:
            self._prompt_update_mod(entry)

    def _open_in_file_manager(self, target_path):
        if not target_path:
            return
        if not os.path.exists(target_path):
            QtWidgets.QMessageBox.warning(
                self,
                "Dossier introuvable",
                "Le dossier du mod est introuvable. Vérifiez qu'il n'a pas été supprimé.",
            )
            return

        if os.path.isfile(target_path):
            target_path = os.path.dirname(target_path) or target_path

        if sys.platform.startswith("win"):
            try:
                os.startfile(target_path)
            except OSError:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Erreur",
                    "Impossible d'ouvrir l'explorateur de fichiers.",
                )
        elif sys.platform == "darwin":
            QtCore.QProcess.startDetached("open", [target_path])
        else:
            QtCore.QProcess.startDetached("xdg-open", [target_path])

    def _open_google_search(self, entry):
        mod_name = entry.get("name") or os.path.basename(entry.get("target_folder", ""))
        if not mod_name:
            return
        query = quote_plus(mod_name)
        webbrowser.open(f"https://www.google.com/search?q={query}")

    def _prompt_update_mod(self, entry):
        target_folder = entry.get("target_folder")
        if not target_folder or not os.path.isdir(target_folder):
            QtWidgets.QMessageBox.warning(
                self,
                "Dossier introuvable",
                "Le dossier du mod est introuvable. Vérifiez qu'il n'a pas été supprimé.",
            )
            return

        def handle_drop(file_paths):
            return self._perform_update(entry, file_paths)

        instruction = (
            "Glissez-déposez un fichier .package, .ts4script ou .zip pour remplacer le contenu du dossier du mod."
        )
        dialog = FileDropDialog("Mettre à jour le mod", instruction, handle_drop, self)
        dialog.exec_()

    def _prompt_addons(self, entry):
        target_folder = entry.get("target_folder")
        if not target_folder or not os.path.isdir(target_folder):
            QtWidgets.QMessageBox.warning(
                self,
                "Dossier introuvable",
                "Le dossier du mod est introuvable. Vérifiez qu'il n'a pas été supprimé.",
            )
            return

        def handle_drop(file_paths):
            return self._perform_addons(entry, file_paths)

        instruction = (
            "Glissez-déposez des fichiers .package, .ts4script ou .zip pour les ajouter au dossier du mod."
        )
        dialog = FileDropDialog("Ajouter des add-ons", instruction, handle_drop, self)
        dialog.exec_()

    def _prompt_remove_addons(self, entry):
        entry_addons = normalize_addon_metadata(entry.get("addons", []))
        if not entry_addons:
            QtWidgets.QMessageBox.information(
                self,
                "Aucun add-on",
                "Aucun add-on n'est enregistré pour ce mod.",
            )
            return

        entry["addons"] = entry_addons

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Supprimer des add-ons")
        dialog.setModal(True)

        layout = QtWidgets.QVBoxLayout(dialog)
        info_label = QtWidgets.QLabel("Sélectionnez les add-ons à supprimer :")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        list_widget = QtWidgets.QListWidget(dialog)
        list_widget.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        for addon in entry_addons:
            label = addon.get("label") or "Add-on"
            added_at_display = format_installation_display(addon.get("added_at", ""))
            if added_at_display:
                item_text = f"{label} – {added_at_display}"
            else:
                item_text = label
            list_item = QtWidgets.QListWidgetItem(item_text)
            list_widget.addItem(list_item)
        layout.addWidget(list_widget)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal,
            dialog,
        )
        remove_button = buttons.button(QtWidgets.QDialogButtonBox.Ok)
        remove_button.setText("Supprimer")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return

        selected_rows = sorted({index.row() for index in list_widget.selectedIndexes()}, reverse=True)
        if not selected_rows:
            QtWidgets.QMessageBox.information(
                self,
                "Aucune sélection",
                "Sélectionnez au moins un add-on à supprimer.",
            )
            return

        success_messages = []
        error_messages = []
        removed_count = 0

        for row in selected_rows:
            if row < 0 or row >= len(entry_addons):
                continue
            addon = entry_addons[row]
            label = addon.get("label") or f"Add-on {row + 1}"
            removed, missing, errors = self._remove_addon_files(entry, addon)
            if errors:
                for message in errors:
                    error_messages.append(f"{label} : {message}")
                continue

            del entry_addons[row]
            removed_count += 1
            details = []
            if removed:
                details.append(f"{len(removed)} élément(s) supprimé(s)")
            if missing:
                details.append(f"{len(missing)} élément(s) introuvable(s)")
            if details:
                success_messages.append(f"{label} – {', '.join(details)}")
            else:
                success_messages.append(f"{label} supprimé.")

        if removed_count:
            updated_entry = dict(entry)
            updated_entry["addons"] = normalize_addon_metadata(entry_addons)
            updated_entry["installed_at"] = datetime.utcnow().replace(microsecond=0).isoformat()
            self._record_installation(updated_entry)
            self.installations_performed = True

        if success_messages:
            QtWidgets.QMessageBox.information(
                self,
                "Suppression terminée",
                "\n".join(success_messages),
            )
        if error_messages:
            QtWidgets.QMessageBox.warning(
                self,
                "Suppression partielle",
                "\n".join(error_messages),
            )

    def _remove_addon_files(self, entry, addon):
        target_folder = entry.get("target_folder")
        removed = []
        missing = []
        errors = []

        if not target_folder or not os.path.isdir(target_folder):
            return removed, missing, ["Dossier du mod introuvable."]

        raw_paths = []
        if isinstance(addon, dict):
            raw_paths = list(addon.get("paths", []))
            if not raw_paths and addon.get("label"):
                raw_paths = [addon.get("label")]
        else:
            raw_paths = [str(addon)]

        entries = []
        seen = set()
        for raw_path in raw_paths:
            path_str = str(raw_path).replace("\\", "/").strip()
            if not path_str:
                continue
            is_directory = path_str.endswith("/")
            trimmed = path_str[:-1] if is_directory else path_str
            normalized = os.path.normpath(trimmed).replace("\\", "/")
            if not normalized or normalized in {".", ""}:
                continue
            if normalized.startswith("..") or "/../" in normalized:
                errors.append(f"Chemin invalide ignoré : {path_str}")
                continue
            key = (normalized, is_directory)
            if key in seen:
                continue
            seen.add(key)
            entries.append((normalized, is_directory))

        if not entries:
            return removed, missing, errors

        target_root = os.path.realpath(target_folder)

        def _sorted_by_depth(items):
            return sorted(items, key=lambda value: (value.count("/"), value), reverse=True)

        file_entries = [value for value, is_dir in entries if not is_dir]
        dir_entries = [value for value, is_dir in entries if is_dir]

        for rel_path in _sorted_by_depth(file_entries):
            absolute_path = os.path.realpath(os.path.join(target_root, rel_path))
            if os.path.commonpath([target_root, absolute_path]) != target_root:
                errors.append(f"Chemin hors du mod : {rel_path}")
                continue
            if os.path.isfile(absolute_path):
                try:
                    os.remove(absolute_path)
                    removed.append(rel_path)
                except OSError as exc:
                    errors.append(f"{rel_path} : {exc}")
            elif os.path.isdir(absolute_path):
                try:
                    shutil.rmtree(absolute_path)
                    removed.append(f"{rel_path}/")
                except OSError as exc:
                    errors.append(f"{rel_path} : {exc}")
            else:
                missing.append(rel_path)

        for rel_path in _sorted_by_depth(dir_entries):
            absolute_path = os.path.realpath(os.path.join(target_root, rel_path))
            if os.path.commonpath([target_root, absolute_path]) != target_root:
                errors.append(f"Chemin hors du mod : {rel_path}/")
                continue
            if os.path.isdir(absolute_path):
                try:
                    shutil.rmtree(absolute_path)
                    removed.append(f"{rel_path}/")
                except OSError as exc:
                    errors.append(f"{rel_path}/ : {exc}")
            elif os.path.isfile(absolute_path):
                try:
                    os.remove(absolute_path)
                    removed.append(rel_path)
                except OSError as exc:
                    errors.append(f"{rel_path}/ : {exc}")
            else:
                missing.append(f"{rel_path}/")

        return removed, missing, errors

    def _perform_update(self, entry, file_paths):
        target_folder = entry.get("target_folder")
        if not target_folder:
            return [], ["Dossier cible invalide."]

        success_messages = []
        error_messages = []
        processed_files = []

        for index, path in enumerate(file_paths):
            if not os.path.isfile(path):
                error_messages.append(f"Fichier introuvable : {path}")
                continue
            if not self._is_supported_extension(path):
                error_messages.append(f"Extension non supportée : {os.path.basename(path)}")
                continue
            success, message, _ = self._install_file_to_target(
                path,
                target_folder,
                clean_before=(index == 0),
                merge=False,
            )
            if success:
                success_messages.append(message)
                processed_files.append(path)
            elif message:
                error_messages.append(message)

        if processed_files:
            updated_entry = dict(entry)
            updated_entry["installed_at"] = datetime.utcnow().replace(microsecond=0).isoformat()
            updated_entry["type"] = self._describe_install_type(processed_files)
            updated_entry["source"] = ", ".join(os.path.basename(path) for path in processed_files)
            updated_entry["addons"] = []
            self._record_installation(updated_entry)
            self.installations_performed = True

        return success_messages, error_messages

    def _perform_addons(self, entry, file_paths):
        target_folder = entry.get("target_folder")
        if not target_folder:
            return [], ["Dossier cible invalide."]

        success_messages = []
        error_messages = []
        added_sources = []
        new_addons = []

        for path in file_paths:
            if not os.path.isfile(path):
                error_messages.append(f"Fichier introuvable : {path}")
                continue
            if not self._is_supported_extension(path):
                error_messages.append(f"Extension non supportée : {os.path.basename(path)}")
                continue
            success, message, installed_paths = self._install_file_to_target(
                path,
                target_folder,
                clean_before=False,
                merge=True,
            )
            if success:
                success_messages.append(message)
                label = os.path.basename(path)
                added_sources.append(label)
                new_addons.append(
                    {
                        "label": label,
                        "paths": installed_paths,
                        "added_at": datetime.utcnow().replace(microsecond=0).isoformat(),
                    }
                )
            elif message:
                error_messages.append(message)

        if added_sources:
            updated_entry = dict(entry)
            existing_addons = normalize_addon_metadata(updated_entry.get("addons", []))
            existing_addons.extend(new_addons)
            updated_entry["addons"] = normalize_addon_metadata(existing_addons)
            updated_entry["installed_at"] = datetime.utcnow().replace(microsecond=0).isoformat()
            self._record_installation(updated_entry)
            self.installations_performed = True

        return success_messages, error_messages

    def _delete_mod(self, entry):
        target_folder = entry.get("target_folder")
        mod_name = entry.get("name") or os.path.basename(target_folder or "")
        response = QtWidgets.QMessageBox.question(
            self,
            "Supprimer le mod",
            (
                f"Voulez-vous supprimer le mod '{mod_name}' ?\n"
                "Le dossier correspondant sera supprimé du disque."
            ),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if response != QtWidgets.QMessageBox.Yes:
            return

        if target_folder and os.path.exists(target_folder):
            try:
                shutil.rmtree(target_folder)
            except OSError as exc:
                QtWidgets.QMessageBox.critical(
                    self,
                    "Suppression impossible",
                    f"Le dossier n'a pas pu être supprimé : {exc}",
                )
                return

        self.installed_mods = [item for item in self.installed_mods if item.get("target_folder") != target_folder]
        save_installed_mods(self.installed_mods)
        self.refresh_table()
        self.installations_performed = True

    def refresh_table(self):
        self.table.setRowCount(len(self.installed_mods))
        for row, entry in enumerate(self.installed_mods):
            mod_name = entry.get("name", "")
            mod_type = entry.get("type", "")
            installed_at = format_installation_display(entry.get("installed_at", ""))
            folder_name = os.path.basename(entry.get("target_folder", ""))

            addons_flag = "✗" if entry.get("addons") else ""

            for column, value in enumerate((mod_name, mod_type, installed_at, folder_name, addons_flag)):
                item = QtWidgets.QTableWidgetItem(value)
                item.setFlags(item.flags() ^ QtCore.Qt.ItemIsEditable)
                self.table.setItem(row, column, item)


class ModManagerApp(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(f"Gestionnaire de Mods Sims 4 – {APP_VERSION} ({APP_VERSION_DATE})")
        self.setGeometry(100, 100, 800, 600)

        self.settings = load_settings()
        configure_logging(self.settings.get("log_level", DEFAULT_LOG_LEVEL))
        LOGGER.info("Initialisation de l'application (version %s) avec le niveau de log %s", APP_VERSION, self.settings.get("log_level"))
        self.custom_version_releases = load_custom_version_releases()
        self.version_releases = merge_version_releases(self.custom_version_releases)
        self.ignored_mods = set(self.settings.get("ignored_mods", []))
        self.last_scanned_directory = ""
        self.all_data_rows = []
        self._cache_clear_triggered_this_refresh = False
        self.scan_thread = None
        self.scan_worker = None
        self._scan_stop_flag = None
        self._pending_scan_request = None
        self._cancel_for_restart = False
        self._user_cancelled_scan = False
        self._pending_rows = []
        self._scan_error_reported = False
        self._scan_buffer_timer = QtCore.QTimer(self)
        self._scan_buffer_timer.setSingleShot(True)
        self._scan_buffer_timer.setInterval(75)
        self._scan_buffer_timer.timeout.connect(self._flush_scan_buffer)
        self._stored_sort_section = 0
        self._stored_sort_order = QtCore.Qt.AscendingOrder

        self.init_ui()

        if not os.path.exists(MOD_SCAN_CACHE_PATH):
            mod_directory = self.settings.get("mod_directory", "")
            if mod_directory and os.path.isdir(mod_directory):
                QtCore.QTimer.singleShot(0, self.refresh_tree)

    def _yield_ui_events(self, max_time_ms=25):
        try:
            flags_type = QtCore.QEventLoop.ProcessEventsFlag
            flags = flags_type.ExcludeUserInputEvents | flags_type.ExcludeSocketNotifiers
        except AttributeError:
            flags = QtCore.QEventLoop.ExcludeUserInputEvents | QtCore.QEventLoop.ExcludeSocketNotifiers
        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        app.processEvents(flags, max_time_ms)

    def init_ui(self):
        # Layout
        layout = QtWidgets.QVBoxLayout()

        # Mode sombre - Définir le style global
        self.setStyleSheet("""
            QWidget {
                background-color: #2e2e2e;
                color: white;
            }
            QTableWidget {
                background-color: #333333;
                color: white;
                border: 1px solid #444444;
            }
            QHeaderView::section {
                background-color: #4e4e4e;
                color: white;
            }
            QCheckBox {
                color: white;
            }
        """)

        # Dossier des mods (affichage uniquement)
        mod_dir_layout = QtWidgets.QHBoxLayout()
        mod_dir_layout.addWidget(QtWidgets.QLabel("Dossier des mods :"))
        self.mod_directory_label = QtWidgets.QLabel()
        self.mod_directory_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        mod_dir_layout.addWidget(self.mod_directory_label, stretch=1)

        layout.addLayout(mod_dir_layout)
        self.update_mod_directory_label()

        # Filtrage
        version_range_layout = QtWidgets.QHBoxLayout()
        self.version_filters_checkbox = QtWidgets.QCheckBox("Versions", self)
        self.version_filters_checkbox.setChecked(self.settings.get("enable_version_filters", True))
        self.version_filters_checkbox.toggled.connect(self._on_version_filters_toggled)
        version_range_layout.addWidget(self.version_filters_checkbox)

        self.version_start_label = QtWidgets.QLabel("Version de départ :", self)
        version_range_layout.addWidget(self.version_start_label)
        self.version_start_combo = QtWidgets.QComboBox(self)
        self.version_start_combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        version_range_layout.addWidget(self.version_start_combo)
        self.version_end_label = QtWidgets.QLabel("Version d'arrivée :", self)
        version_range_layout.addWidget(self.version_end_label)
        self.version_end_combo = QtWidgets.QComboBox(self)
        self.version_end_combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        version_range_layout.addWidget(self.version_end_combo)

        self.show_package_mods_checkbox = QtWidgets.QCheckBox("Show Package", self)
        self.show_package_mods_checkbox.setChecked(self.settings.get("show_package_mods", True))
        self.show_package_mods_checkbox.toggled.connect(lambda: self.toggle_setting("show_package_mods"))

        self.show_ts4script_mods_checkbox = QtWidgets.QCheckBox("Show TS4Script", self)
        self.show_ts4script_mods_checkbox.setChecked(self.settings.get("show_ts4script_mods", True))
        self.show_ts4script_mods_checkbox.toggled.connect(lambda: self.toggle_setting("show_ts4script_mods"))

        self.show_ignored_checkbox = QtWidgets.QCheckBox("Afficher les mods ignorés", self)
        self.show_ignored_checkbox.setChecked(self.settings.get("show_ignored", False))
        self.show_ignored_checkbox.toggled.connect(lambda: self.toggle_show_ignored())

        filter_layout = QtWidgets.QVBoxLayout()
        filter_layout.addLayout(version_range_layout)
        filter_layout.addWidget(self.show_package_mods_checkbox)
        filter_layout.addWidget(self.show_ts4script_mods_checkbox)
        filter_layout.addWidget(self.show_ignored_checkbox)

        layout.addLayout(filter_layout)

        self.populate_version_combos()
        self.version_start_combo.currentIndexChanged.connect(self.on_version_filter_changed)
        self.version_end_combo.currentIndexChanged.connect(self.on_version_filter_changed)
        self._update_version_filter_visibility()

        search_layout = QtWidgets.QHBoxLayout()
        self.search_edit = QtWidgets.QLineEdit(self)
        self.search_edit.setPlaceholderText("Nom du mod à rechercher")
        self._search_debounce_timer = QtCore.QTimer(self)
        self._search_debounce_timer.setInterval(100)
        self._search_debounce_timer.setSingleShot(True)
        self._search_debounce_timer.timeout.connect(self._apply_search_filter)
        self.search_edit.textChanged.connect(self.apply_search_filter)
        self.show_search_checkbox = QtWidgets.QCheckBox("Afficher recherche", self)
        self.show_search_checkbox.setChecked(self.settings.get("show_search_results", True))
        self.show_search_checkbox.toggled.connect(self.toggle_show_search_results)
        search_layout.addWidget(self.show_search_checkbox)
        search_layout.addWidget(QtWidgets.QLabel("Recherche mod :"))
        search_layout.addWidget(self.search_edit)

        self.search_edit.setEnabled(self.show_search_checkbox.isChecked())

        layout.addLayout(search_layout)

        progress_layout = QtWidgets.QHBoxLayout()
        self.scan_status_label = QtWidgets.QLabel("", self)
        self.scan_status_label.setVisible(False)
        self.scan_progress_bar = QtWidgets.QProgressBar(self)
        self.scan_progress_bar.setVisible(False)
        self.scan_progress_bar.setMinimum(0)
        self.scan_progress_bar.setMaximum(100)
        self.scan_progress_bar.setValue(0)
        self.scan_count_label = QtWidgets.QLabel("", self)
        self.scan_count_label.setVisible(False)
        self.cancel_scan_button = QtWidgets.QPushButton("Annuler le scan", self)
        self.cancel_scan_button.setVisible(False)
        self.cancel_scan_button.clicked.connect(self.cancel_scan)
        progress_layout.addWidget(self.scan_status_label)
        progress_layout.addWidget(self.scan_progress_bar, stretch=1)
        progress_layout.addWidget(self.scan_count_label)
        progress_layout.addWidget(self.cancel_scan_button)
        layout.addLayout(progress_layout)

        # Table des mods
        self.table = QtWidgets.QTableView(self)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        if hasattr(self.table, "setUniformRowHeights"):
            self.table.setUniformRowHeights(True)
        self.table.setWordWrap(False)
        self.table.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
        header.setStretchLastSection(False)
        self.table.verticalHeader().setVisible(False)
        self.mods_model = ModsModel(self)
        self.mods_proxy = ModsProxyModel(self)
        self.mods_proxy.setSourceModel(self.mods_model)
        self.mods_proxy.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.mods_proxy.setFilterKeyColumn(-1)
        self.mods_proxy.setSortCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.mods_proxy.setDynamicSortFilter(True)
        self.mods_proxy.set_show_search_results(self.settings.get("show_search_results", True))
        self.table.setModel(self.mods_proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, QtCore.Qt.AscendingOrder)
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self._stored_sort_section = 0
        self._stored_sort_order = QtCore.Qt.AscendingOrder

        layout.addWidget(self.table, stretch=1)

        # Boutons
        self.configuration_button = QtWidgets.QPushButton("Configuration", self)
        self.configuration_button.clicked.connect(self.open_configuration)

        self.mod_installer_button = QtWidgets.QPushButton("Mod Installer", self)
        self.mod_installer_button.clicked.connect(self.open_mod_installer)

        self.refresh_button = QtWidgets.QPushButton("Analyser / Rafraîchir", self)
        self.refresh_button.clicked.connect(self.refresh_tree)

        self.export_button = QtWidgets.QPushButton("Exporter vers Excel", self)
        self.export_button.clicked.connect(self.export_current)

        self.clear_cache_button = QtWidgets.QPushButton("Clear Sims4 Cache", self)
        self.clear_cache_button.clicked.connect(self.clear_sims4_cache)

        self.grab_logs_button = QtWidgets.QPushButton("Grab Logs", self)
        self.grab_logs_button.clicked.connect(self.grab_logs)

        self.launch_button = QtWidgets.QPushButton("Launch Sims 4", self)
        self.launch_button.clicked.connect(self.launch_sims4)

        self.kill_button = QtWidgets.QPushButton("Kill Sims 4", self)
        self.kill_button.clicked.connect(self.kill_sims4)

        self.tools_button = QtWidgets.QPushButton("Tools", self)
        self.tools_button.clicked.connect(self.open_tools_dialog)

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addWidget(self.configuration_button)
        button_layout.addWidget(self.mod_installer_button)
        button_layout.addWidget(self.tools_button)
        button_layout.addWidget(self.refresh_button)
        button_layout.addWidget(self.export_button)
        button_layout.addWidget(self.clear_cache_button)
        button_layout.addWidget(self.grab_logs_button)
        button_layout.addWidget(self.launch_button)
        button_layout.addWidget(self.kill_button)

        layout.addLayout(button_layout)

        # Final
        self.setLayout(layout)
        self.update_launch_button_state()

    def _update_scan_status(self, message):
        if hasattr(self, "scan_status_label") and self.scan_status_label is not None:
            self.scan_status_label.setText(message)
            self.scan_status_label.setVisible(bool(message))
            self._yield_ui_events()

    def _start_scan_progress(self):
        if hasattr(self, "scan_progress_bar") and self.scan_progress_bar is not None:
            self.scan_progress_bar.setVisible(True)
            self.scan_progress_bar.setMaximum(100)
            self.scan_progress_bar.setValue(0)
        if hasattr(self, "scan_count_label") and self.scan_count_label is not None:
            self.scan_count_label.setText("0 %")
            self.scan_count_label.setVisible(True)
        if hasattr(self, "cancel_scan_button") and self.cancel_scan_button is not None:
            self.cancel_scan_button.setVisible(True)
            self.cancel_scan_button.setEnabled(True)
        self._yield_ui_events()

    def _finish_scan_progress(self):
        if hasattr(self, "scan_progress_bar") and self.scan_progress_bar is not None:
            self.scan_progress_bar.setVisible(False)
        if hasattr(self, "scan_count_label") and self.scan_count_label is not None:
            self.scan_count_label.setVisible(False)
        if hasattr(self, "cancel_scan_button") and self.cancel_scan_button is not None:
            self.cancel_scan_button.setVisible(False)
        self._yield_ui_events()

    def _on_scan_progress(self, percentage):
        if hasattr(self, "scan_progress_bar") and self.scan_progress_bar is not None:
            self.scan_progress_bar.setValue(max(0, min(int(percentage), 100)))
        if hasattr(self, "scan_count_label") and self.scan_count_label is not None:
            self.scan_count_label.setText(f"{max(0, min(int(percentage), 100))} %")
            self.scan_count_label.setVisible(True)
        self._yield_ui_events()

    def populate_version_combos(self):
        if not hasattr(self, "version_start_combo"):
            return
        entries = list(self.version_releases.items())
        combo_map = (
            (self.version_start_combo, "version_filter_start"),
            (self.version_end_combo, "version_filter_end"),
        )
        for combo, setting_key in combo_map:
            current_value = self.settings.get(setting_key, "") or ""
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Aucune (pas de limite)", "")
            for version, release_date in entries:
                combo.addItem(f"{version} – {format_release_date(release_date)}", version)
            index = combo.findData(current_value)
            combo.setCurrentIndex(index if index != -1 else 0)
            combo.blockSignals(False)

    def _on_version_filters_toggled(self, checked):
        self.settings["enable_version_filters"] = bool(checked)
        save_settings(self.settings)
        self._update_version_filter_visibility()
        self.refresh_table_only()

    def _update_version_filter_visibility(self):
        enabled = bool(self.settings.get("enable_version_filters", True))
        if hasattr(self, "version_filters_checkbox"):
            if self.version_filters_checkbox.isChecked() != enabled:
                self.version_filters_checkbox.blockSignals(True)
                self.version_filters_checkbox.setChecked(enabled)
                self.version_filters_checkbox.blockSignals(False)
        widgets = [
            getattr(self, "version_start_label", None),
            getattr(self, "version_start_combo", None),
            getattr(self, "version_end_label", None),
            getattr(self, "version_end_combo", None),
        ]
        for widget in widgets:
            if widget is not None:
                widget.setVisible(enabled)
                widget.setEnabled(enabled)

    def on_version_filter_changed(self):
        if not hasattr(self, "version_start_combo"):
            return
        start_idx = self.version_start_combo.currentIndex()
        end_idx = self.version_end_combo.currentIndex()
        sender = self.sender()
        if start_idx > 0 and end_idx > 0 and start_idx > end_idx:
            if sender is self.version_start_combo:
                self.version_end_combo.blockSignals(True)
                self.version_end_combo.setCurrentIndex(start_idx)
                self.version_end_combo.blockSignals(False)
            else:
                self.version_start_combo.blockSignals(True)
                self.version_start_combo.setCurrentIndex(end_idx)
                self.version_start_combo.blockSignals(False)
            start_idx = self.version_start_combo.currentIndex()
            end_idx = self.version_end_combo.currentIndex()

        start_value = self.version_start_combo.itemData(start_idx)
        end_value = self.version_end_combo.itemData(end_idx)
        self.settings["version_filter_start"] = start_value or ""
        self.settings["version_filter_end"] = end_value or ""
        save_settings(self.settings)
        self.refresh_table_only()

    def get_version_entries(self):
        return list(self.version_releases.items())

    def add_version_release(self, version, release_date):
        normalized_version = str(version).strip()
        if not normalized_version:
            return False, "Le numéro de version est obligatoire."

        if hasattr(release_date, "toPyDate"):
            release_date = release_date.toPyDate()

        if release_date is None:
            return False, "La date de sortie est obligatoire."

        if normalized_version in self.version_releases:
            return False, "Cette version existe déjà."

        self.custom_version_releases[normalized_version] = release_date
        save_custom_version_releases(self.custom_version_releases)
        self.version_releases = merge_version_releases(self.custom_version_releases)
        self.populate_version_combos()
        self.refresh_table_only()
        return True, f"Version {normalized_version} ajoutée."

    def toggle_setting(self, key):
        self.settings[key] = getattr(self, f"{key}_checkbox").isChecked()
        save_settings(self.settings)
        self.refresh_table_only()

    def toggle_show_ignored(self):
        self.settings["show_ignored"] = self.show_ignored_checkbox.isChecked()
        save_settings(self.settings)
        self.refresh_table_only()

    def toggle_show_search_results(self):
        checked = self.show_search_checkbox.isChecked()
        self.settings["show_search_results"] = checked
        save_settings(self.settings)
        self.search_edit.setEnabled(checked)
        if hasattr(self, "mods_proxy"):
            self.mods_proxy.set_show_search_results(checked)
        self._apply_search_filter()

    def update_mod_directory_label(self):
        directory = self.settings.get("mod_directory", "")
        display_text = directory if directory else "(non défini)"
        self.mod_directory_label.setText(display_text)

    def open_configuration(self):
        dialog = ConfigurationDialog(self, dict(self.settings))
        dialog.exec_()

    def open_mod_installer(self):
        dialog = ModInstallerDialog(self, self.settings.get("mod_directory", ""))
        dialog.exec_()
        if dialog.installations_performed:
            self.refresh_tree()
            if not self._cache_clear_triggered_this_refresh:
                self.clear_sims4_cache()

    def apply_configuration(
        self,
        mod_directory,
        cache_directory,
        backups_directory,
        sims_executable_path,
        sims_executable_arguments,
        log_extra_extensions,
        grab_logs_ignore_files,
        log_level,
    ):
        previous_mod_directory = self.settings.get("mod_directory", "")
        self.settings["mod_directory"] = mod_directory
        self.settings["sims_cache_directory"] = cache_directory
        self.settings["backups_directory"] = backups_directory
        self.settings["sims_executable_path"] = sims_executable_path
        self.settings["sims_executable_arguments"] = sims_executable_arguments
        self.settings["log_extra_extensions"] = sorted(set(log_extra_extensions))
        self.settings["grab_logs_ignore_files"] = list(grab_logs_ignore_files)
        level_name = str(log_level or DEFAULT_LOG_LEVEL).upper()
        if level_name not in LOG_LEVEL_CHOICES:
            level_name = DEFAULT_LOG_LEVEL
        self.settings["log_level"] = level_name
        save_settings(self.settings)
        configure_logging(level_name)
        LOGGER.info("Configuration enregistrée avec le niveau de log %s", level_name)
        self.update_mod_directory_label()
        self.update_launch_button_state()

        if previous_mod_directory != mod_directory:
            self.last_scanned_directory = ""
            if hasattr(self, "mods_model"):
                self.mods_model.clear()
            self.all_data_rows = []
            if hasattr(self, "mods_proxy"):
                self.mods_proxy.invalidateFilter()

    def _start_scan(self, roots, *, update_last_scanned=False, status_message="Scan en cours..."):
        valid_roots = [path for path in roots if path and os.path.isdir(path)]
        if not valid_roots:
            QtWidgets.QMessageBox.critical(self, "Erreur", "Sélectionne un dossier valide dans la configuration.")
            return
        LOGGER.info("Lancement d'un scan sur %d dossier(s)", len(valid_roots))
        if self.scan_thread is not None and self.scan_thread.isRunning():
            self._pending_scan_request = (
                list(valid_roots),
                {"update_last_scanned": update_last_scanned, "status_message": status_message},
            )
            self._cancel_for_restart = True
            if self._scan_stop_flag is not None:
                self._scan_stop_flag.set()
            return

        self._pending_scan_request = None

        if update_last_scanned and valid_roots:
            self.last_scanned_directory = valid_roots[0]

        self._pending_rows = []
        self._scan_buffer_timer.stop()
        self.all_data_rows = []
        self._cache_clear_triggered_this_refresh = False
        if hasattr(self, "mods_model"):
            self.mods_model.clear()
        if hasattr(self, "mods_proxy"):
            self.mods_proxy.setDynamicSortFilter(False)
            self.mods_proxy.invalidateFilter()
        if hasattr(self, "table"):
            header = self.table.horizontalHeader()
            stored_section = header.sortIndicatorSection()
            stored_order = header.sortIndicatorOrder()
            if stored_section < 0 or stored_section >= header.count():
                stored_section = 0 if header.count() > 0 else -1
            if stored_order not in (QtCore.Qt.AscendingOrder, QtCore.Qt.DescendingOrder):
                stored_order = QtCore.Qt.AscendingOrder
            self._stored_sort_section = stored_section
            self._stored_sort_order = stored_order
            self.table.setSortingEnabled(False)

        self._update_scan_status(status_message)
        self._start_scan_progress()
        self._set_scan_controls_enabled(False)
        self._user_cancelled_scan = False
        self._cancel_for_restart = False
        self._scan_error_reported = False

        settings_snapshot = copy.deepcopy(self.settings)
        settings_snapshot.setdefault("ignored_mods", list(self.settings.get("ignored_mods", [])))
        settings_snapshot["_version_releases"] = [
            (version, release.isoformat()) for version, release in self.version_releases.items()
        ]
        cache_snapshot = load_mod_scan_cache() or {}

        self._scan_stop_flag = threading.Event()
        self.scan_worker = ScanWorker(valid_roots, settings_snapshot, cache_snapshot, self._scan_stop_flag)
        self.scan_thread = QtCore.QThread(self)
        self.scan_worker.moveToThread(self.scan_thread)
        self.scan_worker.progress.connect(self._on_scan_progress)
        self.scan_worker.chunkReady.connect(self._on_scan_chunk_ready)
        self.scan_worker.finished.connect(self._on_scan_finished)
        self.scan_worker.error.connect(self._on_scan_error)
        self.scan_thread.started.connect(self.scan_worker.run)
        self.scan_thread.finished.connect(self.scan_thread.deleteLater)
        self.scan_worker.finished.connect(self.scan_worker.deleteLater)
        self.scan_thread.start()
        LOGGER.debug("Thread de scan démarré")

    def refresh_tree(self):
        folder = self.settings.get("mod_directory", "")
        if not folder or not os.path.isdir(folder):
            QtWidgets.QMessageBox.critical(self, "Erreur", "Sélectionne un dossier valide dans la configuration.")
            return
        self.settings["mod_directory"] = folder
        save_settings(self.settings)
        self.update_mod_directory_label()
        self.ignored_mods = set(self.settings.get("ignored_mods", []))
        self._start_scan([folder], update_last_scanned=True)

    def refresh_table_only(self):
        if self.last_scanned_directory and os.path.isdir(self.last_scanned_directory):
            self.ignored_mods = set(self.settings.get("ignored_mods", []))
            self._start_scan([self.last_scanned_directory], update_last_scanned=False)

    def clear_sims4_cache(self):
        cache_directory = self.settings.get("sims_cache_directory", "")
        if not cache_directory or not os.path.isdir(cache_directory):
            QtWidgets.QMessageBox.warning(self, "Dossier cache invalide", "Configure un dossier cache Sims 4 valide dans la configuration.")
            return

        targets = [
            "localthumbcache.package",
            "localsimtexturecache.package",
            "avatarcache.package",
            "cachestr",
            "onlinethumbnailcache",
        ]

        removed = []
        missing = []
        errors = []

        for item in targets:
            path = os.path.join(cache_directory, item)
            if not os.path.exists(path):
                missing.append(item)
                continue
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                removed.append(item)
            except OSError as exc:
                errors.append(f"{item} : {exc}")

        messages = []
        if removed:
            messages.append("Supprimé : " + ", ".join(removed))
        if missing:
            messages.append("Absent : " + ", ".join(missing))
        if errors:
            messages.append("Erreurs :\n" + "\n".join(errors))

        if not messages:
            messages.append("Aucun fichier ou dossier à supprimer.")

        QtWidgets.QMessageBox.information(self, "Nettoyage du cache", "\n".join(messages))

        launch_response = QtWidgets.QMessageBox.question(
            self,
            "Lancer Les Sims 4",
            "Souhaitez-vous lancer Les Sims 4 maintenant ?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if launch_response == QtWidgets.QMessageBox.Yes:
            self.launch_sims4()

    def grab_logs(self):
        mod_directory = self.settings.get("mod_directory", "")
        if not mod_directory or not os.path.isdir(mod_directory):
            QtWidgets.QMessageBox.warning(self, "Dossier des mods invalide", "Définis un dossier des mods valide dans la configuration avant d'extraire les logs.")
            return

        backups_directory = self.settings.get("backups_directory", "")
        if not backups_directory:
            QtWidgets.QMessageBox.warning(self, "Dossier backups manquant", "Définis un dossier de backups dans la configuration avant d'extraire les logs.")
            return

        os.makedirs(backups_directory, exist_ok=True)

        extensions = {".log", ".txt"}
        extensions.update(self.settings.get("log_extra_extensions", []))
        ignored_log_names = {name.lower() for name in self.settings.get("grab_logs_ignore_files", []) if name}

        normalized_mod_dir = os.path.normpath(mod_directory)
        backups_directory_norm = os.path.normpath(backups_directory)
        found_logs = []

        for current_root, dirs, files in os.walk(normalized_mod_dir):
            dirs[:] = [d for d in dirs if os.path.normpath(os.path.join(current_root, d)) != backups_directory_norm]
            for file_name in files:
                if file_name.lower() in ignored_log_names:
                    continue
                _, ext = os.path.splitext(file_name)
                if ext.lower() in extensions:
                    file_path = os.path.join(current_root, file_name)
                    normalized_file = os.path.normpath(file_path)
                    try:
                        if os.path.commonpath([normalized_file, backups_directory_norm]) == backups_directory_norm:
                            continue
                    except ValueError:
                        pass
                    found_logs.append(file_path)

        if not found_logs:
            QtWidgets.QMessageBox.information(self, "Aucun log", "Aucun fichier de log correspondant n'a été trouvé.")
            return

        timestamp = datetime.now().strftime("Logs_%Y%m%d_%H%M%S")
        destination_root = os.path.join(backups_directory, timestamp)
        os.makedirs(destination_root, exist_ok=True)

        moved_files = []
        errors = []
        for source_path in found_logs:
            relative_path = os.path.relpath(source_path, normalized_mod_dir)
            destination_path = os.path.join(destination_root, relative_path)
            destination_dir = os.path.dirname(destination_path)
            os.makedirs(destination_dir, exist_ok=True)

            final_destination = destination_path
            counter = 1
            while os.path.exists(final_destination):
                name, ext = os.path.splitext(destination_path)
                final_destination = f"{name}_{counter}{ext}"
                counter += 1

            try:
                shutil.move(source_path, final_destination)
                moved_files.append(final_destination)
            except OSError as exc:
                errors.append(f"{source_path} → {exc}")

        if not moved_files:
            QtWidgets.QMessageBox.information(self, "Aucun log déplacé", "Aucun fichier n'a pu être déplacé.")
            return

        message_lines = [f"{len(moved_files)} fichier(s) de log déplacé(s) vers {destination_root}."]
        if errors:
            message_lines.append("\nErreurs:\n" + "\n".join(errors))
        QtWidgets.QMessageBox.information(self, "Logs sauvegardés", "\n".join(message_lines))
        self._open_in_file_manager(destination_root)

    def launch_sims4(self):
        executable_path = self.settings.get("sims_executable_path", "")
        if not executable_path:
            QtWidgets.QMessageBox.warning(self, "Exécutable manquant", "Configure le chemin de TS4_X64.exe dans la configuration.")
            return

        if not os.path.isfile(executable_path):
            QtWidgets.QMessageBox.critical(self, "Exécutable introuvable", "Le fichier TS4_X64.exe configuré est introuvable.")
            return

        args_text = self.settings.get("sims_executable_arguments", "").strip()
        try:
            args = shlex.split(args_text, posix=not sys.platform.startswith("win")) if args_text else []
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Arguments invalides", f"Les arguments spécifiés sont invalides : {exc}")
            return

        try:
            if sys.platform == "darwin":
                started = QtCore.QProcess.startDetached(executable_path, args)
            elif sys.platform.startswith("win"):
                started = QtCore.QProcess.startDetached(executable_path, args)
            else:
                started = QtCore.QProcess.startDetached(executable_path, args)
            if not started:
                raise OSError("le processus n'a pas pu être démarré")
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "Erreur", f"Impossible de lancer Sims 4 : {exc}")

    def kill_sims4(self):
        process_name = "TS4_x64.exe"
        if sys.platform.startswith("win"):
            command = ["taskkill", "/F", "/IM", process_name]
            missing_command_message = "La commande taskkill est introuvable."
        else:
            command = ["pkill", "-f", process_name]
            missing_command_message = "La commande pkill est introuvable."

        try:
            completed = subprocess.run(command, capture_output=True, text=True)
        except FileNotFoundError:
            QtWidgets.QMessageBox.critical(self, "Commande introuvable", missing_command_message)
            return

        if completed.returncode == 0:
            QtWidgets.QMessageBox.information(
                self,
                "Sims 4 arrêté",
                "Le processus TS4_x64.exe a été arrêté avec succès.",
            )
            return

        output = completed.stderr.strip() or completed.stdout.strip() or "La commande a échoué."
        QtWidgets.QMessageBox.warning(
            self,
            "Aucun processus arrêté",
            f"Impossible d'arrêter TS4_x64.exe : {output}",
        )

    def update_launch_button_state(self):
        if hasattr(self, "launch_button"):
            executable_path = self.settings.get("sims_executable_path", "")
            self.launch_button.setEnabled(bool(executable_path and os.path.isfile(executable_path)))

    def open_tools_dialog(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Tools")
        dialog.setModal(True)

        layout = QtWidgets.QVBoxLayout(dialog)
        button_definitions = [
            ("Find dupplicates", "La recherche de doublons n'est pas encore disponible."),
            ("Find non-mods files", "La détection des fichiers non mods sera ajoutée ultérieurement."),
            ("Disable all mods", "La désactivation des mods sera proposée dans une future mise à jour."),
            ("Correct ressource.cfg", "La correction du fichier resource.cfg n'est pas encore implémentée."),
        ]

        for label, message in button_definitions:
            button = QtWidgets.QPushButton(label, dialog)
            button.clicked.connect(partial(self._show_placeholder_message, label, message))
            layout.addWidget(button)

        close_button = QtWidgets.QPushButton("Fermer", dialog)
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)

        dialog.exec_()

    def _show_placeholder_message(self, title, message):
        QtWidgets.QMessageBox.information(self, title, message)

    def populate_table(self, data_rows):
        self.all_data_rows = list(data_rows)
        if hasattr(self, "mods_model"):
            self.mods_model.set_rows(self.all_data_rows)
        if hasattr(self, "mods_proxy"):
            self.mods_proxy.invalidateFilter()
        self._apply_search_filter()

    def apply_search_filter(self, _text=None):
        if hasattr(self, "_search_debounce_timer"):
            self._search_debounce_timer.stop()
            self._search_debounce_timer.start()

    def _apply_search_filter(self):
        if not hasattr(self, "mods_proxy"):
            return
        show_results = self.settings.get("show_search_results", True)
        self.mods_proxy.set_show_search_results(show_results)
        query = ""
        if show_results and hasattr(self, "search_edit"):
            query = self.search_edit.text().strip()
        self.mods_proxy.setFilterFixedString(query)
        if not self.mods_proxy.dynamicSortFilter():
            self.mods_proxy.invalidateFilter()

    def show_context_menu(self, position):
        index = self.table.indexAt(position)
        row_data, source_row = self._proxy_to_source_row(index)
        if row_data is None:
            return

        candidates = list(row_data.get("ignore_candidates") or [])
        menu = QtWidgets.QMenu(self)
        ignore_label = "Ne plus ignorer" if row_data.get("ignored") else "Ignorer"
        ignore_action = menu.addAction(ignore_label)
        show_in_explorer_action = menu.addAction("Afficher dans l'explorateur")
        delete_action = menu.addAction("Supprimer le mod")
        google_action = menu.addAction("Recherche Google")

        selected_action = menu.exec_(self.table.viewport().mapToGlobal(position))

        if selected_action == ignore_action:
            new_state = (
                QtCore.Qt.Unchecked if row_data.get("ignored") else QtCore.Qt.Checked
            )
            self.update_ignore_mod(tuple(candidates), new_state)
        elif selected_action == show_in_explorer_action:
            self.show_in_explorer(row_data)
        elif selected_action == delete_action:
            self.delete_mod(row_data, candidates, source_row)
        elif selected_action == google_action:
            self.launch_google_search(row_data, candidates)

    def _resolve_row_paths(self, row_data):
        if not row_data:
            return []
        paths = row_data.get("paths") or []
        return list(paths)

    def _open_in_file_manager(self, target_path):
        if sys.platform.startswith("win"):
            try:
                os.startfile(target_path)
            except OSError:
                QtWidgets.QMessageBox.warning(self, "Erreur", "Impossible d'ouvrir l'explorateur de fichiers.")
        elif sys.platform == "darwin":
            QtCore.QProcess.startDetached("open", [target_path])
        else:
            QtCore.QProcess.startDetached("xdg-open", [target_path])

    def show_in_explorer(self, row_data):
        paths = self._resolve_row_paths(row_data)
        if not paths:
            return
        target_path = paths[0]
        if not os.path.exists(target_path):
            QtWidgets.QMessageBox.warning(self, "Fichier introuvable", "Le fichier sélectionné est introuvable sur le disque.")
            return

        directory = os.path.dirname(target_path) or target_path
        self._open_in_file_manager(directory)

    def delete_mod(self, row_data, candidates, source_row):
        paths = self._resolve_row_paths(row_data)
        if not paths:
            return

        confirm = QtWidgets.QMessageBox.question(
            self,
            "Confirmer la suppression",
            "Supprimer ce mod supprimera définitivement les fichiers associés. Continuer ?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )

        if confirm != QtWidgets.QMessageBox.Yes:
            return

        errors = []
        for path in paths:
            if not os.path.exists(path):
                continue
            try:
                os.remove(path)
            except OSError as exc:
                errors.append(str(exc))

        if errors:
            QtWidgets.QMessageBox.warning(
                self,
                "Erreur lors de la suppression",
                "\n".join(errors),
            )

        if candidates:
            for name in candidates:
                self.ignored_mods.discard(name)
            save_ignore_list(self.ignored_mods)
            self.settings["ignored_mods"] = sorted(self.ignored_mods)
            save_settings(self.settings)

        if self.last_scanned_directory and os.path.isdir(self.last_scanned_directory):
            self.refresh_table_only()
        else:
            self._remove_source_row(source_row)

    def launch_google_search(self, row_data, candidates):
        file_name = row_data.get("package", "") or row_data.get("script", "")

        if not file_name and candidates:
            file_name = candidates[0]

        if not file_name:
            return

        base_name, _ = os.path.splitext(file_name)
        if not base_name:
            return

        search_url = QtCore.QUrl(f"https://www.google.com/search?q={quote_plus(base_name)}")
        QtGui.QDesktopServices.openUrl(search_url)

    def update_ignore_mod(self, candidates, state):
        candidates = [name for name in candidates if name]
        if not candidates:
            return

        canonical_key = candidates[0]
        if state == QtCore.Qt.Checked:
            for name in candidates[1:]:
                self.ignored_mods.discard(name)
            self.ignored_mods.add(canonical_key)
        else:
            for name in candidates:
                self.ignored_mods.discard(name)

        save_ignore_list(self.ignored_mods)
        self.settings["ignored_mods"] = sorted(self.ignored_mods)
        save_settings(self.settings)
        self.refresh_table_only()

    def _set_scan_controls_enabled(self, enabled):
        widgets = [
            getattr(self, "configuration_button", None),
            getattr(self, "mod_installer_button", None),
            getattr(self, "tools_button", None),
            getattr(self, "refresh_button", None),
            getattr(self, "export_button", None),
            getattr(self, "clear_cache_button", None),
            getattr(self, "grab_logs_button", None),
            getattr(self, "launch_button", None),
            getattr(self, "kill_button", None),
        ]
        for widget in widgets:
            if widget is not None:
                widget.setEnabled(enabled)

    def _on_scan_chunk_ready(self, rows):
        if not rows:
            return
        self._pending_rows.extend(rows)
        if not self._scan_buffer_timer.isActive():
            self._scan_buffer_timer.start()
        LOGGER.debug("Réception d'un paquet de %d ligne(s)", len(rows))

    def _flush_scan_buffer(self):
        if not self._pending_rows:
            return
        pending = self._pending_rows
        self._pending_rows = []
        LOGGER.debug("Insertion de %d ligne(s) dans le modèle", len(pending))
        self.all_data_rows.extend(pending)
        if hasattr(self, "mods_model"):
            self.mods_model.add_rows(pending)
        if hasattr(self, "mods_proxy"):
            self.mods_proxy.invalidateFilter()

    def _proxy_to_source_row(self, index):
        if not hasattr(self, "mods_proxy") or not hasattr(self, "mods_model"):
            return None, None
        if not index.isValid():
            return None, None
        source_index = self.mods_proxy.mapToSource(index)
        if not source_index.isValid():
            return None, None
        row_data = self.mods_model.get_row(source_index.row())
        return row_data, source_index.row()

    def _remove_source_row(self, source_row):
        if not hasattr(self, "mods_model"):
            return
        if source_row is None:
            return
        if 0 <= source_row < len(self.all_data_rows):
            self.all_data_rows.pop(source_row)
        self.mods_model.remove_row(source_row)
        if hasattr(self, "mods_proxy"):
            self.mods_proxy.invalidateFilter()

    def _cleanup_scan_thread(self):
        if self.scan_thread is not None:
            self.scan_thread.quit()
            self.scan_thread.wait()
            self.scan_thread = None
        self.scan_worker = None
        self._scan_stop_flag = None

    def _on_scan_finished(self, success, message):
        worker = self.scan_worker
        self._scan_buffer_timer.stop()
        self._flush_scan_buffer()
        snapshot_changed = bool(worker and getattr(worker, "snapshot_changed", False))
        self._cleanup_scan_thread()
        self._finish_scan_progress()
        self._set_scan_controls_enabled(True)
        LOGGER.info("Scan terminé (succès=%s, message=%s)", success, message)
        if hasattr(self, "mods_proxy"):
            self.mods_proxy.setDynamicSortFilter(True)
            self.mods_proxy.invalidateFilter()
        if hasattr(self, "table"):
            self.table.setSortingEnabled(True)
            column_count = self.mods_model.columnCount() if hasattr(self, "mods_model") else self.table.model().columnCount()
            target_section = self._stored_sort_section
            if not (0 <= target_section < column_count):
                target_section = 0 if column_count > 0 else -1
            if target_section >= 0 and column_count > 0:
                self.table.sortByColumn(target_section, self._stored_sort_order)
        if success:
            self._update_scan_status("")
            if snapshot_changed:
                self._cache_clear_triggered_this_refresh = True
                QtCore.QTimer.singleShot(0, self.clear_sims4_cache)
            else:
                self._cache_clear_triggered_this_refresh = False
            if hasattr(self, "scan_count_label") and self.scan_count_label is not None:
                self.scan_count_label.setText(f"{len(self.all_data_rows)} mods")
                self.scan_count_label.setVisible(True)
        else:
            if message == "Cancelled" and self._cancel_for_restart and self._pending_scan_request:
                roots, options = self._pending_scan_request
                self._pending_scan_request = None
                self._cancel_for_restart = False
                QtCore.QTimer.singleShot(0, lambda: self._start_scan(roots, **options))
                return
            self._update_scan_status("")
            if (
                message
                and message not in {"Cancelled", "OK"}
                and not self._user_cancelled_scan
                and not self._scan_error_reported
            ):
                QtWidgets.QMessageBox.warning(self, "Erreur", message)
        self._pending_scan_request = None
        self._cancel_for_restart = False
        self._user_cancelled_scan = False
        self._scan_error_reported = False

    def _on_scan_error(self, message):
        if message:
            LOGGER.error("Erreur remontée par le scan : %s", message)
            QtWidgets.QMessageBox.critical(self, "Erreur", message)
            self._scan_error_reported = True

    def cancel_scan(self):
        if self._scan_stop_flag is None or self._scan_stop_flag.is_set():
            return
        self._user_cancelled_scan = True
        self._pending_scan_request = None
        self._cancel_for_restart = False
        self._scan_stop_flag.set()
        self._update_scan_status("Annulation en cours...")
        if hasattr(self, "cancel_scan_button") and self.cancel_scan_button is not None:
            self.cancel_scan_button.setEnabled(False)
        LOGGER.info("Annulation du scan demandée par l'utilisateur")

    def closeEvent(self, event):
        if self._scan_stop_flag is not None and not self._scan_stop_flag.is_set():
            self._scan_stop_flag.set()
        if self.scan_thread is not None and self.scan_thread.isRunning():
            self.scan_thread.quit()
            self.scan_thread.wait()
        super().closeEvent(event)

    def export_current(self):
        rows = []
        if hasattr(self, "mods_proxy") and hasattr(self, "mods_model"):
            proxy = self.mods_proxy
            for row in range(proxy.rowCount()):
                source_index = proxy.mapToSource(proxy.index(row, 0))
                if not source_index.isValid():
                    continue
                row_dict = self.mods_model.get_row(source_index.row())
                if not row_dict:
                    continue
                row_data = [
                    str(row_dict.get("status", "")),
                    str(row_dict.get("package", "")),
                    str(row_dict.get("package_date", "")),
                    str(row_dict.get("script", "")),
                    str(row_dict.get("script_date", "")),
                    str(row_dict.get("version", "")),
                    str(row_dict.get("confidence", "")),
                    bool(row_dict.get("ignored", False)),
                ]
                rows.append(row_data)

        save_path = self.settings.get("xls_file_path", "")
        if not save_path:
            save_path = QtWidgets.QFileDialog.getSaveFileName(self, "Sauvegarder sous", "", "Excel Files (*.xlsx)")[0]
            if not save_path:
                return
            self.settings["xls_file_path"] = save_path
            save_settings(self.settings)

        export_to_excel(save_path, rows)
        QtWidgets.QMessageBox.information(self, "Info", f"Export terminé vers : {save_path}")

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = ModManagerApp()
    window.show()
    sys.exit(app.exec_())
