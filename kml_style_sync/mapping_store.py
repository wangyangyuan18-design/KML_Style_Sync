from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .logger import get_logger

log = get_logger()


MAPPING_FILENAME = "KML_Style_Mapping.json"
LEGACY_FILENAME = "folder_mappings.json"


def mapping_root() -> Path:
    """Return the application data directory used only as a fallback.

    The primary mapping file is kept beside the EXE/project code so that all A
    projects share one cumulative, portable mapping table and the file can be
    copied to another PC together with the application.
    """
    base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or str(Path.home())
    path = Path(base) / "KML_Style_Sync"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _portable_mapping_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / MAPPING_FILENAME
    # Development mode: keep the same file at the repository/application root.
    return Path(__file__).resolve().parent.parent / MAPPING_FILENAME


def mapping_path() -> Path:
    """Single cumulative mapping table shared by all A files.

    Prefer the portable file beside the EXE. If that directory is not writable,
    transparently fall back to the existing per-user application-data location.
    """
    portable = _portable_mapping_path()
    try:
        portable.parent.mkdir(parents=True, exist_ok=True)
        if portable.exists() or os.access(portable.parent, os.W_OK):
            return portable
    except Exception:
        pass
    return mapping_root() / MAPPING_FILENAME


def _legacy_mapping_path() -> Path:
    return mapping_root() / LEGACY_FILENAME


def _read_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        log.warning("FOLDER MAPPING READ FAILED: %s", exc)
        return {}


def _read() -> dict[str, Any]:
    path = mapping_path()
    data = _read_file(path)
    if data:
        return data

    # One-time compatibility: retain mappings created by older builds.
    legacy = _read_file(_legacy_mapping_path())
    if legacy:
        try:
            _write(legacy)
        except Exception:
            pass
    return legacy


def _write(data: dict[str, Any]) -> None:
    path = mapping_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _key(parts: tuple[str, ...], geometry: str) -> str:
    return json.dumps({"path": list(parts), "geometry": geometry}, ensure_ascii=False, separators=(",", ":"))


def get_mapping(source_path: tuple[str, ...], geometry: str) -> tuple[tuple[str, ...], str] | None:
    data = _read()
    item = data.get(_key(source_path, geometry))
    if not isinstance(item, dict):
        return None
    target = item.get("template_path")
    target_geometry = item.get("geometry")
    if not isinstance(target, list) or not all(isinstance(x, str) for x in target):
        return None
    if not isinstance(target_geometry, str):
        return None
    return tuple(target), target_geometry


def save_mapping(
    source_path: tuple[str, ...],
    source_geometry: str,
    template_path: tuple[str, ...],
    template_geometry: str,
) -> None:
    data = _read()
    data[_key(source_path, source_geometry)] = {
        "source_path": list(source_path),
        "source_geometry": source_geometry,
        "template_path": list(template_path),
        "geometry": template_geometry,
    }
    _write(data)


def delete_mapping(source_path: tuple[str, ...], geometry: str) -> None:
    data = _read()
    data.pop(_key(source_path, geometry), None)
    _write(data)


def clear_mappings() -> None:
    path = mapping_path()
    path.unlink(missing_ok=True)
