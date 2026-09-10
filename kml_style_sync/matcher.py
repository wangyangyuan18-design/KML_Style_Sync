from __future__ import annotations

from difflib import SequenceMatcher

from .kml_parser import normalize_name
from .mapping_store import get_mapping
from .models import FolderInfo, MatchRow


def _name_score(a: str, b: str) -> float:
    a, b = normalize_name(a), normalize_name(b)
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _parent_score(source: FolderInfo, template: FolderInfo) -> float:
    if len(source.folder_path) < 2 or len(template.folder_path) < 2:
        return 0.0
    return _name_score(source.folder_path[-2], template.folder_path[-2])


def score_candidate(source: FolderInfo, template: FolderInfo) -> float:
    """Weighted smart-match score: name 75%, parent Folder 25%."""
    if template.geometry_type != source.geometry_type:
        return 0.0
    return 0.75 * _name_score(source.name, template.name) + 0.25 * _parent_score(source, template)


def ranked_candidates(source: FolderInfo, template_folders: list[FolderInfo]) -> list[tuple[FolderInfo, float]]:
    ranked = [(folder, score_candidate(source, folder)) for folder in template_folders
              if folder.geometry_type == source.geometry_type]
    return sorted(ranked, key=lambda item: item[1], reverse=True)


def _saved_template(source: FolderInfo, template_folders: list[FolderInfo]) -> FolderInfo | None:
    """Return the previously selected B Folder when it still exists and Geometry is unchanged."""
    saved = get_mapping(source.folder_path, source.geometry_type)
    if saved is None:
        return None
    target_path, target_geometry = saved
    if target_geometry != source.geometry_type:
        return None
    for folder in template_folders:
        if folder.geometry_type == target_geometry and folder.folder_path == target_path:
            return folder
    return None


def build_match_rows(source_folders: list[FolderInfo], template_folders: list[FolderInfo]) -> list[MatchRow]:
    """Restore saved mappings first, then exact matching and conservative smart recommendations."""
    rows: list[MatchRow] = []
    for source in source_folders:
        saved = _saved_template(source, template_folders)
        if saved is not None:
            rows.append(MatchRow(template=saved, source=source,
                                 status="HISTORY_MATCHED", confidence=1.0))
            continue

        exact = [f for f in template_folders
                 if f.geometry_type == source.geometry_type
                 and normalize_name(f.name) == normalize_name(source.name)]
        if len(exact) == 1:
            rows.append(MatchRow(template=exact[0], source=source,
                                 status="EXACT_MATCHED", confidence=1.0))
            continue
        if len(exact) > 1:
            rows.append(MatchRow(template=None, source=source, status="AMBIGUOUS"))
            continue

        ranked = ranked_candidates(source, template_folders)
        if ranked and ranked[0][1] >= 0.85:
            rows.append(MatchRow(template=ranked[0][0], source=source,
                                 status="SMART_MATCHED", confidence=ranked[0][1]))
        else:
            rows.append(MatchRow(template=None, source=source,
                                 status="UNMATCHED",
                                 confidence=ranked[0][1] if ranked else 0.0))
    return rows


def candidates_for(source: FolderInfo, template_folders: list[FolderInfo]) -> list[FolderInfo]:
    """Geometry-compatible B choices, ordered by smart recommendation score."""
    return [folder for folder, _score in ranked_candidates(source, template_folders)]
