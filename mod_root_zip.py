import logging
import os
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Iterable, List, Optional, Sequence, Tuple


# Useful targets to install
USEFUL_EXT = {".package", ".ts4script"}

# Extras to ignore by default (copied only with include_extras=True)
EXTRA_EXT = {
    ".txt",
    ".pdf",
    ".md",
    ".rtf",
    ".png",
    ".jpg",
    ".jpeg",
    ".mp4",
    ".mov",
    ".ini",
    ".cfg",
}

# Noise entries/directories to skip entirely
NOISE_DIRS = {"__MACOSX"}
NOISE_FILES = {"thumbs.db", ".ds_store"}


logger = logging.getLogger(__name__)


@dataclass
class ZipEntry:
    name: str  # exact zip member name
    is_dir: bool

    @property
    def parts(self) -> Tuple[str, ...]:
        p = self.name.replace("\\", "/").rstrip("/")
        if not p:
            return tuple()
        return tuple(x for x in p.split("/") if x)

    @property
    def ext(self) -> str:
        if self.is_dir:
            return ""
        _, ext = os.path.splitext(self.name)
        return ext.lower()

    @property
    def top(self) -> Optional[str]:
        ps = self.parts
        return ps[0] if ps else None


def _is_noise(member: str) -> bool:
    member = member.replace("\\", "/")
    if not member:
        return True
    # Skip directories and files under known noise dirs
    parts = [p for p in member.split("/") if p]
    if not parts:
        return True
    if parts[0].casefold() in {d.casefold() for d in NOISE_DIRS}:
        return True
    # Skip known junk files
    base = parts[-1].casefold()
    if base in NOISE_FILES:
        return True
    return False


def _normalize_mod_name(name: str) -> str:
    # Keep ASCII letters, numbers, space, underscore and hyphen; collapse whitespace
    base = Path(name).stem
    base = re.sub(r"[^A-Za-z0-9 _.-]+", "", base)
    base = re.sub(r"\s+", " ", base).strip()
    return base or "Mod"


def _list_zip_entries(zpath: str) -> List[ZipEntry]:
    out: List[ZipEntry] = []
    with zipfile.ZipFile(zpath) as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if _is_noise(name):
                continue
            out.append(ZipEntry(name=name, is_dir=info.is_dir()))
    return out


def _is_useful_file(name: str) -> bool:
    return not name.endswith("/") and name.lower().endswith(tuple(USEFUL_EXT))


def _is_extra_file(name: str) -> bool:
    return not name.endswith("/") and name.lower().endswith(tuple(EXTRA_EXT))


def _has_useful_under(entries: Sequence[ZipEntry], prefix: str) -> bool:
    prefix = prefix.rstrip("/") + "/" if prefix else ""
    for e in entries:
        if e.is_dir:
            continue
        if prefix and not e.name.startswith(prefix):
            continue
        if _is_useful_file(e.name):
            return True
    return False


def _compute_top_level(entries: Sequence[ZipEntry]) -> Tuple[List[str], List[str]]:
    # Returns (top-level dirs with trailing slash, files at root)
    dirs: List[str] = []
    files: List[str] = []
    seen: set = set()
    for e in entries:
        if e.is_dir:
            parts = e.parts
            if parts:
                key = parts[0] + "/"
                if key not in seen:
                    seen.add(key)
                    dirs.append(key)
            continue
        # file
        parts = e.parts
        if len(parts) == 1:
            files.append(e.name)
        elif len(parts) > 1:
            key = parts[0] + "/"
            if key not in seen:
                seen.add(key)
                dirs.append(key)
    dirs.sort()
    files.sort()
    return dirs, files


def _dir_useful_stats(entries: Sequence[ZipEntry], dir_prefix: str) -> Tuple[int, List[int]]:
    # Returns (count_useful, list_of_depths_from_dir)
    dir_prefix = dir_prefix.rstrip("/") + "/"
    depths: List[int] = []
    count = 0
    for e in entries:
        if e.is_dir:
            continue
        if not e.name.startswith(dir_prefix):
            continue
        if _is_useful_file(e.name):
            count += 1
            # distance from dir (number of segments between dir and file)
            after = e.name[len(dir_prefix) :].rstrip("/")
            depth = len([p for p in after.split("/") if p])
            depths.append(max(0, depth))
    return count, depths


def _safe_join(root: Path, rel: str) -> Optional[Path]:
    # Normalize path separators, reject absolute or parent traversal
    rel_norm = rel.replace("\\", "/").lstrip("/")
    parts = tuple(p for p in Path(rel_norm).parts if p not in {"", "."})
    if any(p == ".." for p in parts):
        return None
    target = root
    for p in parts:
        target = target / p
    try:
        # Ensure inside root
        target_abs = target.resolve()
        root_abs = root.resolve()
    except Exception:
        # Fallback best effort
        target_abs = target
        root_abs = root
    try:
        if os.path.commonpath([str(root_abs), str(target_abs)]) != str(root_abs):
            return None
    except Exception:
        return None
    return target


class ArchiveType:
    FLAT = "FLAT"
    SINGLE_DIR = "SINGLE_DIR"
    MIXED = "MIXED"


def install_zip(
    zip_path: str,
    mods_root: str,
    include_extras: bool = False,
    *,
    override_root: Optional[str] = None,
    dest_folder_name: Optional[str] = None,
) -> str:
    """
    Install a .zip archive into Mods/ following deterministic mod-root rules.

    - Targets: *.package, *.ts4script
    - Ignore noise (__MACOSX, Thumbs.db, .DS_Store); extras copied only with include_extras=True.
    - Detects archive type (FLAT, SINGLE_DIR, MIXED) and chooses a mod root.
    - Preserves relative tree under the chosen mod root.
    - Validates at least one useful file in destination, otherwise rolls back.
    - Prevents path traversal and absolute writes.
    """
    if not zipfile.is_zipfile(zip_path):
        raise RuntimeError(f"Archive zip invalide: {zip_path}")

    entries = _list_zip_entries(zip_path)
    useful = [e for e in entries if _is_useful_file(e.name)]

    if not useful:
        raise RuntimeError("Archive sans fichiers utiles (.package/.ts4script)")

    toplevel_dirs, root_files = _compute_top_level(entries)

    # Determine archive type and mod root
    archive_type = ArchiveType.MIXED
    mod_root = ""
    dest_dir_name = None
    justification = ""

    if override_root is not None:
        # Validate override root
        if override_root == "":
            archive_type = ArchiveType.FLAT
            mod_root = ""
            dest_dir_name = dest_folder_name or _normalize_mod_name(Path(zip_path).stem)
            justification = "forcé par l'utilisateur: racine"
        else:
            # normalize with trailing slash for comparison
            ov = override_root.rstrip("/") + "/"
            if ov not in toplevel_dirs:
                raise RuntimeError(f"Racine spécifiée invalide: {override_root}")
            archive_type = ArchiveType.MIXED
            mod_root = ov
            dest_dir_name = dest_folder_name or _normalize_mod_name(Path(zip_path).stem)
            justification = f"forcé par l'utilisateur: {ov}"
    elif any(_is_useful_file(f) for f in root_files):
        archive_type = ArchiveType.FLAT
        mod_root = ""  # root of archive
        dest_dir_name = dest_folder_name or _normalize_mod_name(Path(zip_path).stem)
        justification = "fichiers utiles à la racine"
    elif len(toplevel_dirs) == 1 and _has_useful_under(entries, toplevel_dirs[0]):
        archive_type = ArchiveType.SINGLE_DIR
        mod_root = toplevel_dirs[0]
        dest_dir_name = dest_folder_name or Path(mod_root.rstrip("/")).name
        justification = f"dossier unique contenant des fichiers utiles: {mod_root}"
    else:
        archive_type = ArchiveType.MIXED
        # Choose dir with max useful, tie-breaker: shortest median distance
        best_dir = None
        best_count = -1
        best_median = float("inf")
        stats: List[Tuple[str, int, float]] = []
        for d in toplevel_dirs:
            cnt, depths = _dir_useful_stats(entries, d)
            med = float(median(depths)) if depths else float("inf")
            stats.append((d, cnt, med))
            if cnt > best_count or (cnt == best_count and med < best_median):
                best_dir = d
                best_count = cnt
                best_median = med
        mod_root = best_dir or ""
        dest_dir_name = dest_folder_name or _normalize_mod_name(Path(zip_path).stem)
        justification = (
            f"candidat choisi '{mod_root}' (utiles={best_count}, médiane_profondeur={best_median})"
            if mod_root
            else "aucun dossier dominant, racine"
        )

    mods_root_path = Path(mods_root)
    if archive_type == ArchiveType.SINGLE_DIR:
        dest = mods_root_path / dest_dir_name
    elif archive_type == ArchiveType.FLAT:
        dest = mods_root_path / dest_dir_name
    else:  # MIXED
        dest = mods_root_path / dest_dir_name

    logger.debug(
        "[ZIP] type=%s, mod_root=%s, justification=%s, dest=%s",
        archive_type,
        mod_root or "/",
        justification,
        str(dest),
    )

    # Extract preserving tree relative to mod_root
    installed: List[str] = []
    dest.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                if info.is_dir() or _is_noise(name):
                    continue
                if mod_root:
                    root_prefix = mod_root.rstrip("/") + "/"
                    if not name.startswith(root_prefix):
                        continue
                    rel = name[len(root_prefix) :]
                else:
                    rel = name

                # Filter extras unless include_extras
                if not include_extras and not _is_useful_file(name):
                    continue

                rel_norm = rel.replace("\\", "/").lstrip("/")
                # Security: block traversal and absolute
                out_path = _safe_join(dest, rel_norm)
                if out_path is None:
                    logger.debug("[ZIP] Ignored insecure path: %s", rel_norm)
                    continue

                out_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, "r") as src, open(out_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                try:
                    # Apply original timestamp when possible
                    mtime = datetime_from_zip(info)
                    if mtime:
                        os.utime(out_path, (mtime, mtime))
                except Exception:
                    pass
                installed.append(rel_norm)

        # Validation
        has_useful = any(p.suffix.lower() in USEFUL_EXT for p in dest.rglob("*"))
        if not has_useful:
            raise RuntimeError("Aucun fichier utile après extraction")

        logger.debug("[ZIP] %s → %s (%s)", zip_path, dest, archive_type)
        logger.debug("[ZIP] Fichiers installés (%d): %s", len(installed), installed)
        return str(dest)
    except Exception as exc:
        # Rollback on failure or empty useful set
        try:
            shutil.rmtree(dest, ignore_errors=True)
        except Exception:
            pass
        raise


def datetime_from_zip(info: zipfile.ZipInfo) -> float:
    # Convert ZipInfo date_time to POSIX timestamp
    from datetime import datetime

    try:
        dt = datetime(*info.date_time)
        return dt.timestamp()
    except Exception:
        return 0.0


def _plan_from_entries(entries: Sequence[ZipEntry], zip_basename: str) -> Tuple[str, str, str, str]:
    """
    Core planner used by both ZIP and extracted dirs.
    Returns (archive_type, mod_root, dest_dir_name, justification).
    """
    useful = [e for e in entries if _is_useful_file(e.name)]
    if not useful:
        raise RuntimeError("Archive sans fichiers utiles (.package/.ts4script)")

    toplevel_dirs, root_files = _compute_top_level(entries)

    if any(_is_useful_file(f) for f in root_files):
        return (
            ArchiveType.FLAT,
            "",
            _normalize_mod_name(zip_basename),
            "fichiers utiles à la racine",
        )

    if len(toplevel_dirs) == 1 and _has_useful_under(entries, toplevel_dirs[0]):
        only = toplevel_dirs[0]
        return (
            ArchiveType.SINGLE_DIR,
            only,
            Path(only.rstrip("/")).name,
            f"dossier unique contenant des fichiers utiles: {only}",
        )

    # MIXED
    best_dir = None
    best_count = -1
    best_median = float("inf")
    for d in toplevel_dirs:
        cnt, depths = _dir_useful_stats(entries, d)
        med = float(median(depths)) if depths else float("inf")
        if cnt > best_count or (cnt == best_count and med < best_median):
            best_dir = d
            best_count = cnt
            best_median = med
    justification = (
        f"candidat choisi '{best_dir}' (utiles={best_count}, médiane_profondeur={best_median})"
        if best_dir
        else "aucun dossier dominant, racine"
    )
    return (
        ArchiveType.MIXED,
        best_dir or "",
        _normalize_mod_name(zip_basename),
        justification,
    )


def plan_zip(zip_path: str, mods_root: str) -> Tuple[str, str, str, str]:
    """Return (dest_path, archive_type, mod_root, justification) without extracting."""
    if not zipfile.is_zipfile(zip_path):
        raise RuntimeError(f"Archive zip invalide: {zip_path}")
    entries = _list_zip_entries(zip_path)
    a_type, mod_root, dest_dir_name, justif = _plan_from_entries(entries, Path(zip_path).stem)
    dest = Path(mods_root) / dest_dir_name
    logger.debug("[PLAN ZIP] type=%s root=%s dest=%s (%s)", a_type, mod_root or "/", dest, justif)
    return str(dest), a_type, (mod_root or ""), justif


def _list_dir_entries(root: str) -> List[ZipEntry]:
    out: List[ZipEntry] = []
    base = Path(root)
    for cur, dirs, files in os.walk(base):
        rel_dir = Path(cur).relative_to(base).as_posix()
        # add subdirs (as dirs)
        for d in dirs:
            p = (Path(rel_dir) / d).as_posix() if rel_dir != "." else d
            if _is_noise(p + "/"):
                continue
            out.append(ZipEntry(name=p + "/", is_dir=True))
        for f in files:
            p = (Path(rel_dir) / f).as_posix() if rel_dir != "." else f
            if _is_noise(p):
                continue
            out.append(ZipEntry(name=p, is_dir=False))
    return out


def plan_extracted_dir(extracted_root: str, mods_root: str, default_name: str) -> Tuple[str, str, str, str]:
    """Return (dest_path, archive_type, mod_root, justification) for a previously extracted folder."""
    entries = _list_dir_entries(extracted_root)
    a_type, mod_root, dest_dir_name, justif = _plan_from_entries(entries, default_name)
    dest = Path(mods_root) / dest_dir_name
    logger.debug("[PLAN DIR] type=%s root=%s dest=%s (%s)", a_type, mod_root or "/", dest, justif)
    return str(dest), a_type, (mod_root or ""), justif


def install_extracted_dir(
    extracted_root: str,
    mods_root: str,
    default_name: str,
    include_extras: bool = False,
    *,
    override_root: Optional[str] = None,
    dest_folder_name: Optional[str] = None,
) -> str:
    """Install from a pre-extracted folder (7z/rar) using the same rules.
    override_root: either "" for archive root or a top-level directory name (with or without trailing '/') under extracted_root.
    dest_folder_name: optional destination base folder name.
    """
    entries = _list_dir_entries(extracted_root)
    if override_root is not None:
        # Validate override root candidate
        if override_root == "":
            a_type, mod_root, dest_dir_name, justif = (
                ArchiveType.FLAT,
                "",
                dest_folder_name or _normalize_mod_name(default_name),
                "forcé par l'utilisateur: racine",
            )
        else:
            ov = override_root.rstrip("/")
            # ensure exists as top-level dir
            top_dirs = {e.name.rstrip("/") for e in entries if e.is_dir and len(e.parts) == 1}
            if ov not in top_dirs:
                raise RuntimeError(f"Racine spécifiée invalide: {override_root}")
            a_type, mod_root, dest_dir_name, justif = (
                ArchiveType.MIXED,
                ov + "/",
                dest_folder_name or _normalize_mod_name(default_name),
                f"forcé par l'utilisateur: {ov}/",
            )
    else:
        a_type, mod_root, dest_dir_name, justif = _plan_from_entries(entries, default_name)
        dest_dir_name = dest_folder_name or dest_dir_name
    dest = Path(mods_root) / dest_dir_name
    logger.debug(
        "[DIR] type=%s, mod_root=%s, justification=%s, dest=%s",
        a_type,
        mod_root or "/",
        justif,
        str(dest),
    )

    dest.mkdir(parents=True, exist_ok=True)
    installed: List[str] = []
    root = Path(extracted_root)
    prefix_parts: Tuple[str, ...] = tuple(p for p in Path(mod_root).parts if p) if mod_root else tuple()
    for cur, _dirs, files in os.walk(root):
        for f in files:
            full = Path(cur) / f
            rel_parts = full.relative_to(root).parts
            if prefix_parts:
                if rel_parts[: len(prefix_parts)] != prefix_parts:
                    continue
                rel_parts = rel_parts[len(prefix_parts) :]
            if not rel_parts:
                continue
            rel_path = Path(*rel_parts).as_posix()
            # filter extras
            if not include_extras:
                if not _is_useful_file(rel_path):
                    continue
            # security
            out_path = _safe_join(dest, rel_path)
            if out_path is None:
                logger.debug("[DIR] Ignored insecure path: %s", rel_path)
                continue
            out_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(full), str(out_path))
            installed.append(rel_path)

    has_useful = any(p.suffix.lower() in USEFUL_EXT for p in dest.rglob("*"))
    if not has_useful:
        try:
            shutil.rmtree(dest, ignore_errors=True)
        except Exception:
            pass
        raise RuntimeError("Aucun fichier utile après extraction")
    logger.debug("[DIR] Fichiers installés (%d): %s", len(installed), installed)
    return str(dest)


__all__ = [
    "install_zip",
    "plan_zip",
    "plan_extracted_dir",
    "install_extracted_dir",
]
