from __future__ import annotations

from .kml_parser import normalize_name
from .models import FolderInfo, MatchRow


def _path_key(folder: FolderInfo) -> tuple[str, ...]:
    return tuple(normalize_name(part) for part in folder.folder_path)


def build_match_rows(source_folders: list[FolderInfo], template_folders: list[FolderInfo]) -> list[MatchRow]:
    """Create one row for every A Folder.

    B is the authoritative template catalogue. Automatic matching is only a
    convenience: exact full-path match first, then unique Folder-name match.
    Geometry must be identical. The UI always lets the user override the
    automatic choice with a geometry-filtered B Folder combo box.
    """
    rows: list[MatchRow] = []
    for source in source_folders:
        exact = [
            template for template in template_folders
            if _path_key(template) == _path_key(source)
            and template.geometry_type == source.geometry_type
        ]
        if len(exact) == 1:
            rows.append(MatchRow(source=source, template=exact[0], status="MATCHED"))
            continue

        by_name = [
            template for template in template_folders
            if normalize_name(template.name) == normalize_name(source.name)
            and template.geometry_type == source.geometry_type
        ]
        if len(by_name) == 1:
            rows.append(MatchRow(source=source, template=by_name[0], status="MATCHED"))
        elif len(by_name) > 1:
            rows.append(MatchRow(source=source, status="AMBIGUOUS"))
        else:
            rows.append(MatchRow(source=source, status="UNMATCHED"))
    return rows


def candidates_for(source: FolderInfo, template_folders: list[FolderInfo]) -> list[FolderInfo]:
    """All B Folder choices allowed for this A Folder: same Geometry only."""
    return [
        folder for folder in template_folders
        if folder.geometry_type == source.geometry_type
    ]
