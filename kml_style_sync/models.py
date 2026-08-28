from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

GeometryType = Literal["POINT", "LINE", "POLYGON", "MIXED", "UNKNOWN"]
MatchStatus = Literal["AUTO_MATCHED", "MANUAL_MATCHED", "UNMATCHED", "AMBIGUOUS"]


@dataclass(slots=True)
class FolderInfo:
    """Metadata for one KML Folder, preserving document order and hierarchy."""

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
    def is_effective_layer(self) -> bool:
        """True only when this Folder itself directly contains recognized geometry."""
        return self.geometry_type in {"POINT", "LINE", "POLYGON"} and self.feature_count > 0

    @property
    def is_container(self) -> bool:
        return not self.is_effective_layer

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
    """One selected KML/KMZ file and all parsed effective Folders."""

    file_path: Path
    folders: list[FolderInfo] = field(default_factory=list)


@dataclass(slots=True)
class MatchRow:
    """One B-standard effective-layer row with the current A assignment."""

    template: FolderInfo
    source: FolderInfo | None = None
    status: MatchStatus = "UNMATCHED"
