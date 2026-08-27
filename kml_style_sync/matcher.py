from .kml_parser import normalize_name
from .models import LayerInfo, MatchRow


def build_match_rows(source_layers: list[LayerInfo], template_layers: list[LayerInfo]) -> list[MatchRow]:
    """Build rows in exact template scan order; geometry is a hard constraint."""
    rows: list[MatchRow] = []
    for template in template_layers:
        candidates = [s for s in source_layers if s.geometry_type == template.geometry_type]
        exact = [s for s in candidates if normalize_name(s.name) == normalize_name(template.name)]
        if len(exact) == 1:
            rows.append(MatchRow(template=template, source=exact[0], status="MATCHED"))
        elif len(exact) > 1:
            rows.append(MatchRow(template=template, status="AMBIGUOUS"))
        else:
            rows.append(MatchRow(template=template, status="UNMATCHED"))
    return rows


def candidates_for(template: LayerInfo, source_layers: list[LayerInfo]) -> list[LayerInfo]:
    return [layer for layer in source_layers if layer.geometry_type == template.geometry_type]
