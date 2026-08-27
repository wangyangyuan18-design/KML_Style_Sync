from __future__ import annotations

from .kml_parser import normalize_name
from .models import FolderInfo, MatchRow


def _path_key(folder: FolderInfo) -> tuple[str, ...]:
    return tuple(normalize_name(part) for part in folder.folder_path)


def build_match_rows(source_folders: list[FolderInfo], template_folders: list[FolderInfo]) -> list[MatchRow]:
    """Match A Folders to B template Folders without making metadata editable.

    Matching priority:
      1. exact normalized full Folder path + same geometry;
      2. unique normalized Folder name + same geometry.
    Ambiguous or geometry-incompatible matches are left unmatched.
    """
    rows: list[MatchRow] = []
    used_templates: set[int] = set()
    for source in source_folders:
        exact = [
            (i, template)
            for i, template in enumerate(template_folders)
            if i not in used_templates
            and _path_key(template) == _path_key(source)
            and template.geometry_type == source.geometry_type
        ]
        if len(exact) == 1:
            i, template = exact[0]
            used_templates.add(i)
            rows.append(MatchRow(source=source, template=template, status="MATCHED"))
            continue

        by_name = [
            (i, template)
            for i, template in enumerate(template_folders)
            if i not in used_templates
            and normalize_name(template.name) == normalize_name(source.name)
            and template.geometry_type == source.geometry_type
        ]
        if len(by_name) == 1:
            i, template = by_name[0]
            used_templates.add(i)
            rows.append(MatchRow(source=source, template=template, status="MATCHED"))
        elif len(by_name) > 1:
            rows.append(MatchRow(source=source, status="AMBIGUOUS"))
        else:
            rows.append(MatchRow(source=source, status="UNMATCHED"))
    return rows


def candidates_for(source: FolderInfo, template_folders: list[FolderInfo]) -> list[FolderInfo]:
    """Return compatible B Folders; kept for API compatibility, not used by the UI."""
    return [
        folder for folder in template_folders
        if folder.geometry_type == source.geometry_type
    ]
