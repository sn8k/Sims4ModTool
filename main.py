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
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple
from functools import partial
from urllib.parse import quote_plus
from PyQt5 import QtWidgets, QtCore, QtGui
from datetime import datetime, time, date
from openpyxl import Workbook

SETTINGS_PATH = "settings.json"
IGNORE_LIST_PATH = "ignorelist.txt"
VERSION_RELEASE_PATH = "version_release.json"
APP_VERSION = "v3.30"
APP_VERSION_DATE = "22/10/2025 11:32 UTC"
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
    return settings

def save_settings(settings, path=SETTINGS_PATH):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=4, ensure_ascii=False)

def scan_directory(directory, progress_callback=None):
    package_files = {}
    ts4script_files = {}
    snapshot_entries = []
    normalized_root = os.path.abspath(directory)
    relevant_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            lower_name = file.lower()
            if lower_name.endswith((".package", ".ts4script")):
                full_path = os.path.join(root, file)
                relevant_files.append((file, lower_name, full_path))

    total_files = len(relevant_files)
    if progress_callback is not None:
        try:
            progress_callback(0, total_files, "")
        except Exception:
            pass

    for index, (file, lower_name, full_path) in enumerate(relevant_files, start=1):
        if lower_name.endswith(".package"):
            package_files[file] = full_path
        else:
            ts4script_files[file] = full_path
        try:
            stat_result = os.stat(full_path)
        except OSError:
            continue
        relative_path = os.path.relpath(full_path, normalized_root)
        snapshot_entries.append({
            "path": relative_path.replace("\\", "/"),
            "mtime": int(stat_result.st_mtime),
            "size": int(stat_result.st_size),
            "type": "package" if lower_name.endswith(".package") else "ts4script",
        })
        if progress_callback is not None:
            try:
                progress_callback(index, total_files, full_path)
            except Exception:
                pass
    snapshot_entries.sort(key=lambda item: item["path"].casefold())
    snapshot = {
        "root": normalized_root.replace("\\", "/"),
        "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "entries": snapshot_entries,
    }
    return package_files, ts4script_files, snapshot

def generate_data_rows(directory, settings, version_releases, progress_callback=None, yield_callback=None):
    package_files, ts4script_files, snapshot = scan_directory(directory, progress_callback=progress_callback)
    previous_snapshot = load_mod_scan_cache()
    snapshot_changed = previous_snapshot is not None and not mod_scan_snapshots_equal(previous_snapshot, snapshot)
    save_mod_scan_cache(snapshot)
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
    throttle_counter = 0

    def _maybe_yield():
        nonlocal throttle_counter
        if yield_callback is None:
            return
        throttle_counter += 1
        if throttle_counter % 25 != 0:
            return
        try:
            yield_callback()
        except Exception:
            pass
    ignored_mods = set(settings.get("ignored_mods", []))
    show_ignored = settings.get("show_ignored", False)
    show_packages = settings.get("show_package_mods", True)
    show_scripts = settings.get("show_ts4script_mods", True)

    # .package files
    for pkg, pkg_path in package_files.items():
        pkg_date = get_file_date(pkg_path)
        base_name = os.path.splitext(pkg)[0]
        script_file = f"{base_name}.ts4script"
        script_path = ts4script_files.get(script_file)
        script_date = get_file_date(script_path) if script_path else None

        mod_latest_date = max((date for date in (pkg_date, script_date) if date is not None), default=None)

        # Appliquer filtres
        if end_limit and mod_latest_date and mod_latest_date > end_limit:
            continue
        if start_limit and mod_latest_date and mod_latest_date < start_limit:
            continue
        has_package = True
        has_script = script_path is not None
        if not ((has_package and show_packages) or (has_script and show_scripts)):
            continue

        candidates = [name for name in (pkg, script_file if script_path else None) if name]
        ignored = any(name in ignored_mods for name in candidates)
        if ignored and not show_ignored:
            continue

        status = "X" if script_path else "MS"
        version = estimate_version_from_dates(pkg_date, script_date, version_releases)

        data_rows.append({
            "status": status,
            "package": pkg,
            "package_date": format_datetime(pkg_date),
            "script": script_file if script_path else "",
            "script_date": format_datetime(script_date),
            "version": version,
            "ignored": ignored,
            "ignore_candidates": candidates or [pkg],
            "paths": [path for path in (pkg_path, script_path) if path],
        })
        _maybe_yield()

    # ts4script orphans
    for script, script_path in ts4script_files.items():
        base_name = os.path.splitext(script)[0]
        pkg_file = f"{base_name}.package"
        if pkg_file in package_files:
            continue

        script_date = get_file_date(script_path)

        if end_limit and script_date and script_date > end_limit:
            continue
        if start_limit and script_date and script_date < start_limit:
            continue
        if not show_scripts:
            continue
        candidates = [script]
        ignored = any(name in ignored_mods for name in candidates)
        if ignored and not show_ignored:
            continue
        status = "MP"

        version = estimate_version_from_dates(None, script_date, version_releases)

        data_rows.append({
            "status": status,
            "package": "",
            "package_date": "",
            "script": script,
            "script_date": format_datetime(script_date),
            "version": version,
            "ignored": ignored,
            "ignore_candidates": candidates,
            "paths": [script_path],
        })
        _maybe_yield()

    if yield_callback is not None:
        try:
            yield_callback()
        except Exception:
            pass

    return data_rows, snapshot_changed

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

        if self._parent is not None:
            self._parent.apply_configuration(
                mod_directory,
                cache_directory,
                backups_directory,
                sims_executable_path,
                sims_executable_arguments,
                sorted(set(extra_extensions)),
                ignore_files,
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
        self.custom_version_releases = load_custom_version_releases()
        self.version_releases = merge_version_releases(self.custom_version_releases)
        self.ignored_mods = set(self.settings.get("ignored_mods", []))
        self.last_scanned_directory = ""
        self.all_data_rows = []
        self._cache_clear_triggered_this_refresh = False

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
        self.scan_progress_bar.setMaximum(1)
        self.scan_progress_bar.setValue(0)
        self.scan_count_label = QtWidgets.QLabel("", self)
        self.scan_count_label.setVisible(False)
        progress_layout.addWidget(self.scan_status_label)
        progress_layout.addWidget(self.scan_progress_bar, stretch=1)
        progress_layout.addWidget(self.scan_count_label)
        layout.addLayout(progress_layout)

        # Table des mods
        self.table = QtWidgets.QTableWidget(self)
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "État",
            "Fichier .package",
            "Date .package",
            "Fichier .ts4script",
            "Date .ts4script",
            "Version",
            "Ignoré",
        ])
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

        header = self.table.horizontalHeader()
        for column in range(self.table.columnCount()):
            resize_mode = QtWidgets.QHeaderView.Stretch
            if column in (0, 2, 4, 5, self.table.columnCount() - 1):
                resize_mode = QtWidgets.QHeaderView.ResizeToContents
            header.setSectionResizeMode(column, resize_mode)
        header.setStretchLastSection(False)
        self.table.setSortingEnabled(True)
        self.table.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)

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
            self.scan_progress_bar.setMaximum(0)
            self.scan_progress_bar.setValue(0)
        if hasattr(self, "scan_count_label") and self.scan_count_label is not None:
            self.scan_count_label.setText("")
            self.scan_count_label.setVisible(True)
        self._yield_ui_events()

    def _finish_scan_progress(self):
        if hasattr(self, "scan_progress_bar") and self.scan_progress_bar is not None:
            self.scan_progress_bar.setVisible(False)
        if hasattr(self, "scan_count_label") and self.scan_count_label is not None:
            self.scan_count_label.setVisible(False)
        self._yield_ui_events()

    def _handle_scan_progress(self, processed, total, current_path):
        if hasattr(self, "scan_progress_bar") and self.scan_progress_bar is not None:
            if total:
                if self.scan_progress_bar.maximum() != total:
                    self.scan_progress_bar.setMaximum(total)
                self.scan_progress_bar.setValue(min(processed, total))
            else:
                self.scan_progress_bar.setMaximum(0)
        if hasattr(self, "scan_count_label") and self.scan_count_label is not None:
            if total:
                self.scan_count_label.setText(f"Objets scannés : {processed}/{total}")
            else:
                self.scan_count_label.setText(f"Objets scannés : {processed}")
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

    def apply_configuration(self, mod_directory, cache_directory, backups_directory, sims_executable_path, sims_executable_arguments, log_extra_extensions, grab_logs_ignore_files):
        previous_mod_directory = self.settings.get("mod_directory", "")
        self.settings["mod_directory"] = mod_directory
        self.settings["sims_cache_directory"] = cache_directory
        self.settings["backups_directory"] = backups_directory
        self.settings["sims_executable_path"] = sims_executable_path
        self.settings["sims_executable_arguments"] = sims_executable_arguments
        self.settings["log_extra_extensions"] = sorted(set(log_extra_extensions))
        self.settings["grab_logs_ignore_files"] = list(grab_logs_ignore_files)
        save_settings(self.settings)
        self.update_mod_directory_label()
        self.update_launch_button_state()

        if previous_mod_directory != mod_directory:
            self.last_scanned_directory = ""
            if hasattr(self, "table"):
                self.table.setRowCount(0)

    def refresh_tree(self):
        folder = self.settings.get("mod_directory", "")
        if not folder or not os.path.isdir(folder):
            QtWidgets.QMessageBox.critical(self, "Erreur", "Sélectionne un dossier valide dans la configuration.")
            return
        self.settings["mod_directory"] = folder
        save_settings(self.settings)
        self.update_mod_directory_label()
        self.ignored_mods = set(self.settings.get("ignored_mods", []))
        self.last_scanned_directory = folder
        self._update_scan_status("Scan en cours...")
        self._start_scan_progress()
        try:
            rows, scan_changed = generate_data_rows(
                folder,
                self.settings,
                self.version_releases,
                progress_callback=self._handle_scan_progress,
                yield_callback=self._yield_ui_events,
            )
        finally:
            self._finish_scan_progress()
        self.populate_table(rows)
        self._update_scan_status("")
        self._cache_clear_triggered_this_refresh = False
        if scan_changed:
            self._cache_clear_triggered_this_refresh = True
            self.clear_sims4_cache()

    def refresh_table_only(self):
        if self.last_scanned_directory and os.path.isdir(self.last_scanned_directory):
            self.ignored_mods = set(self.settings.get("ignored_mods", []))
            self._update_scan_status("Scan en cours...")
            self._cache_clear_triggered_this_refresh = False
            self._start_scan_progress()
            try:
                rows, scan_changed = generate_data_rows(
                    self.last_scanned_directory,
                    self.settings,
                    self.version_releases,
                    progress_callback=self._handle_scan_progress,
                    yield_callback=self._yield_ui_events,
                )
            finally:
                self._finish_scan_progress()
            self.populate_table(rows)
            self._update_scan_status("")
            if scan_changed:
                self._cache_clear_triggered_this_refresh = True
                self.clear_sims4_cache()

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
        self._apply_search_filter()

    def apply_search_filter(self, _text=None):
        self._apply_search_filter()

    def _apply_search_filter(self):
        query = ""
        if hasattr(self, "search_edit"):
            query = self.search_edit.text().strip().lower()

        show_search_results = self.settings.get("show_search_results", True)

        if not show_search_results:
            filtered_rows = list(self.all_data_rows)
        elif not query:
            filtered_rows = list(self.all_data_rows)
        else:
            filtered_rows = [
                row
                for row in self.all_data_rows
                if self._row_matches_query(row, query)
            ]

        self._render_table(filtered_rows)

    def _row_matches_query(self, row, query):
        for value in self._gather_searchable_values(row):
            if query in value:
                return True
        return False

    def _gather_searchable_values(self, row):
        values = [
            str(row.get("status", "")),
            str(row.get("package", "")),
            str(row.get("package_date", "")),
            str(row.get("script", "")),
            str(row.get("script_date", "")),
            str(row.get("version", "")),
        ]
        ignored_value = "oui" if row.get("ignored", False) else "non"
        values.append(ignored_value)
        values.extend(str(candidate) for candidate in row.get("ignore_candidates", []))
        values.extend(str(path) for path in row.get("paths", []))
        return [value.lower() for value in values if value]

    def _render_table(self, rows):
        header = self.table.horizontalHeader()
        sorting_enabled = self.table.isSortingEnabled()
        sort_section = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        table = self.table
        table.setSortingEnabled(False)
        table.setUpdatesEnabled(False)
        try:
            if table.rowCount():
                table.clearContents()
            table.setRowCount(len(rows))
            for row_index, row in enumerate(rows):
                columns = [
                    row.get("status", ""),
                    row.get("package", ""),
                    row.get("package_date", ""),
                    row.get("script", ""),
                    row.get("script_date", ""),
                    row.get("version", ""),
                ]
                for col_idx, value in enumerate(columns):
                    item = QtWidgets.QTableWidgetItem(str(value))
                    if col_idx == 0:
                        item.setData(QtCore.Qt.UserRole, tuple(row.get("ignore_candidates") or []))
                        item.setData(QtCore.Qt.UserRole + 1, tuple(row.get("paths") or []))
                    table.setItem(row_index, col_idx, item)

                ignored = row.get("ignored", False)
                ignore_item = QtWidgets.QTableWidgetItem("Oui" if ignored else "Non")
                ignore_item.setData(QtCore.Qt.UserRole, 1 if ignored else 0)
                ignore_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
                table.setItem(row_index, 6, ignore_item)

                ignore_checkbox = QtWidgets.QCheckBox()
                ignore_checkbox.stateChanged.connect(
                    partial(self.update_ignore_mod, tuple(row.get("ignore_candidates") or []))
                )
                ignore_checkbox.blockSignals(True)
                ignore_checkbox.setChecked(ignored)
                ignore_checkbox.blockSignals(False)
                table.setCellWidget(row_index, 6, ignore_checkbox)

                if row_index % 50 == 0:
                    self._yield_ui_events()
        finally:
            table.setUpdatesEnabled(True)

        table.setSortingEnabled(sorting_enabled)
        if sorting_enabled and rows:
            table.sortByColumn(sort_section, sort_order)
        table.viewport().update()
        self._yield_ui_events()

    def show_context_menu(self, position):
        index = self.table.indexAt(position)
        if not index.isValid():
            return

        row = index.row()
        status_item = self.table.item(row, 0)
        candidates = []
        if status_item is not None:
            stored_candidates = status_item.data(QtCore.Qt.UserRole)
            if stored_candidates:
                candidates = list(stored_candidates)

        menu = QtWidgets.QMenu(self)
        ignore_action = menu.addAction("Ignorer")
        show_in_explorer_action = menu.addAction("Afficher dans l'explorateur")
        delete_action = menu.addAction("Supprimer le mod")
        google_action = menu.addAction("Recherche Google")

        selected_action = menu.exec_(self.table.viewport().mapToGlobal(position))

        if selected_action == ignore_action:
            checkbox = self.table.cellWidget(row, 6)
            if checkbox is not None:
                checkbox.setChecked(not checkbox.isChecked())
        elif selected_action == show_in_explorer_action:
            self.show_in_explorer(row, candidates)
        elif selected_action == delete_action:
            self.delete_mod(row, candidates)
        elif selected_action == google_action:
            self.launch_google_search(row, candidates)

    def _resolve_row_paths(self, row):
        status_item = self.table.item(row, 0)
        if status_item is None:
            return []
        paths = status_item.data(QtCore.Qt.UserRole + 1)
        return list(paths) if paths else []

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

    def show_in_explorer(self, row, candidates):
        paths = self._resolve_row_paths(row)
        if not paths:
            return
        target_path = paths[0]
        if not os.path.exists(target_path):
            QtWidgets.QMessageBox.warning(self, "Fichier introuvable", "Le fichier sélectionné est introuvable sur le disque.")
            return

        directory = os.path.dirname(target_path) or target_path
        self._open_in_file_manager(directory)

    def delete_mod(self, row, candidates):
        paths = self._resolve_row_paths(row)
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
            self.table.removeRow(row)

    def launch_google_search(self, row, candidates):
        file_name = ""
        for column in (1, 3):
            item = self.table.item(row, column)
            if item:
                text = item.text().strip()
                if text:
                    file_name = text
                    break

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

    def export_current(self):
        rows = []
        for row in range(self.table.rowCount()):
            row_data = [self.table.item(row, col).text() for col in range(self.table.columnCount() - 1)]
            row_data.append(self.table.cellWidget(row, 6).isChecked())  # Ajouter l'état de la case à cocher "Ignoré"
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
