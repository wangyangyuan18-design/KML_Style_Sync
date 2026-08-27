from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

GeometryType = Literal["POINT", "LINE", "POLYGON", "MIXED", "UNKNOWN"]

@dataclass(slots=True)
class StyleUsage:
    key: str
    count: int = 0

@dataclass(slots=True)
class LayerInfo:
    name: str
    file_path: Path
    relative_path: Path
    geometry_type: GeometryType
    feature_count: int
    style_usage: dict[str, int] = field(default_factory=dict)
    standard_style_key: str | None = None
    standard_style_xml: str | None = None

    @property
    def standard_style_ratio(self) -> float:
        if not self.feature_count or not self.standard_style_key:
            return 0.0
        return self.style_usage.get(self.standard_style_key, 0) / self.feature_count

@dataclass(slots=True)
class MatchRow:
    template: LayerInfo
    source: LayerInfo | None = None
    status: str = "UNMATCHED"
