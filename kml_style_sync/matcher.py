from __future__ import annotations

from .kml_parser import normalize_name
from .models import FolderInfo, MatchRow


def _path_key(folder: FolderInfo) -> tuple[str, ...]:
    return tuple(normalize_name(part) for part in folder.folder_path)


def _exact_path_matches(template_folders: list[FolderInfo], source: FolderInfo) -> list[FolderInfo]:
    return [
        template for template in template_folders
        if template.geometry_type == source.geometry_type
        and _path_key(template) == _path_key(source)
    ]


def _name_matches(template_folders: list[FolderInfo], source: FolderInfo) -> list[FolderInfo]:
    return [
        template for template in template_folders
        if template.geometry_type == source.geometry_type
        and normalize_name(template.name) == normalize_name(source.name)
    ]


def build_match_rows(source_folders: list[FolderInfo], template_folders: list[FolderInfo]) -> list[MatchRow]:
    """Build one row for every effective A layer, preserving A document order.

    Automatic matching is deliberately conservative:
      1. normalized full Folder path + identical Geometry;
      2. normalized Folder name + identical Geometry;
      3. otherwise leave B empty.

    No geometry-only guessing and no fuzzy matching are performed.
    """
    rows: list[MatchRow] = []
    for source in source_folders:
        exact = _exact_path_matches(template_folders, source)
        if len(exact) == 1:
            rows.append(MatchRow(template=exact[0], source=source, status="AUTO_MATCHED"))
            continue

        by_name = _name_matches(template_folders, source)
        if len(by_name) == 1:
            rows.append(MatchRow(template=by_name[0], source=source, status="AUTO_MATCHED"))
        elif len(by_name) > 1:
            rows.append(MatchRow(template=None, source=source, status="AMBIGUOUS"))
        else:
            rows.append(MatchRow(template=None, source=source, status="UNMATCHED"))
    return rows


def candidates_for(source: FolderInfo, template_folders: list[FolderInfo]) -> list[FolderInfo]:
    """All B Folder choices allowed for an A row: identical Geometry only."""
    return [
        folder for folder in template_folders
        if folder.geometry_type == source.geometry_type
    ]
