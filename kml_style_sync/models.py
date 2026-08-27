from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

GeometryType = Literal["POINT", "LINE", "POLYGON", "MIXED", "UNKNOWN"]


@dataclass(slots=True)
class FolderInfo:
    """Information derived from one KML Folder and its direct Placemarks."""

    name: str
    folder_path: tuple[str, ...]
    geometry_type: GeometryType
    feature_count: int
    style_usage: dict[str, int] = field(default_factory=dict)
    standard_style_key: str | None = None
    standard_style_xml: str | None = None

    @property
    def display_path(self) -> str:
        return " / ".join(self.folder_path)

    @property
    def standard_style_ratio(self) -> float:
        if not self.feature_count or not self.standard_style_key:
            return 0.0
        return self.style_usage.get(self.standard_style_key, 0) / self.feature_count


@dataclass(slots=True)
class KMLFileInfo:
    """One selected KML/KMZ input file and the Folders found inside it."""

    file_path: Path
    folders: list[FolderInfo] = field(default_factory=list)


@dataclass(slots=True)
class MatchRow:
    """A read-only matching result: A Folder -> B template Folder."""

    source: FolderInfo
    template: FolderInfo | None = None
    status: str = "UNMATCHED"
