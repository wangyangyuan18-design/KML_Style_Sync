from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

GeometryType = Literal["POINT", "LINE", "POLYGON", "MIXED", "UNKNOWN"]


@dataclass(slots=True)
class FolderInfo:
    """Metadata parsed from one KML Folder in document order."""

    name: str
    folder_path: tuple[str, ...]
    geometry_type: GeometryType
    feature_count: int
    style_usage: dict[str, int] = field(default_factory=dict)
    standard_style_key: str | None = None
    standard_style_xml: str | None = None
    standard_style_ambiguous: bool = False

    @property
    def display_path(self) -> str:
        return " / ".join(self.folder_path)

    @property
    def standard_style_ratio(self) -> float:
        if not self.feature_count or not self.standard_style_key:
            return 0.0
        return self.style_usage.get(self.standard_style_key, 0) / self.feature_count

    @property
    def style_status(self) -> str:
        if self.standard_style_ambiguous:
            return "需人工确认"
        if self.standard_style_key == "<unstyled>" or not self.standard_style_key:
            return "未找到"
        return f"{self.standard_style_ratio * 100:.1f}%"


@dataclass(slots=True)
class KMLFileInfo:
    """One selected KML/KMZ file and all of its KML Folders."""

    file_path: Path
    folders: list[FolderInfo] = field(default_factory=list)


@dataclass(slots=True)
class MatchRow:
    """One B-standard Folder row with an optional A-side match."""

    template: FolderInfo
    source: FolderInfo | None = None
    status: str = "UNMATCHED"
