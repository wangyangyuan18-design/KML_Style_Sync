from __future__ import annotations

from .kml_parser import normalize_name
from .models import FolderInfo, MatchRow


def _path_key(folder: FolderInfo) -> tuple[str, ...]:
    return tuple(normalize_name(part) for part in folder.folder_path)


def _exact_matches(source_folders: list[FolderInfo], template: FolderInfo) -> list[FolderInfo]:
    return [
        source for source in source_folders
        if source.geometry_type == template.geometry_type
        and _path_key(source) == _path_key(template)
    ]


def _name_matches(source_folders: list[FolderInfo], template: FolderInfo) -> list[FolderInfo]:
    return [
        source for source in source_folders
        if source.geometry_type == template.geometry_type
        and normalize_name(source.name) == normalize_name(template.name)
    ]


def build_match_rows(source_folders: list[FolderInfo], template_folders: list[FolderInfo]) -> list[MatchRow]:
    """Build one row for every B Folder, preserving B document order.

    Automatic matching is deliberately conservative:
      1. normalized full Folder path + identical Geometry;
      2. normalized Folder name + identical Geometry;
      3. otherwise leave A empty.

    No fuzzy matching and no geometry-only guessing are performed.
    """
    rows: list[MatchRow] = []
    for template in template_folders:
        exact = _exact_matches(source_folders, template)
        if len(exact) == 1:
            rows.append(MatchRow(template=template, source=exact[0], status="AUTO_MATCHED"))
            continue
        by_name = _name_matches(source_folders, template)
        if len(by_name) == 1:
            rows.append(MatchRow(template=template, source=by_name[0], status="AUTO_MATCHED"))
        elif len(by_name) > 1:
            rows.append(MatchRow(template=template, source=None, status="AMBIGUOUS"))
        else:
            rows.append(MatchRow(template=template, source=None, status="UNMATCHED"))
    return rows


def candidates_for(template: FolderInfo, source_folders: list[FolderInfo]) -> list[FolderInfo]:
    """All A Folder choices allowed for a B row: identical Geometry only."""
    return [
        folder for folder in source_folders
        if folder.geometry_type == template.geometry_type
    ]
