from __future__ import annotations

import zipfile
from collections import Counter
from pathlib import Path
from lxml import etree

from .models import GeometryType, LayerInfo

KML_NS = "http://www.opengis.net/kml/2.2"
NS = {"kml": KML_NS}


def normalize_name(value: str) -> str:
    return " ".join(Path(value).stem.strip().lower().split())


def _read_kml_bytes(path: Path) -> bytes:
    if path.suffix.lower() == ".kml":
        return path.read_bytes()
    if path.suffix.lower() == ".kmz":
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            candidate = next((n for n in names if n.lower() == "doc.kml"), None)
            candidate = candidate or next((n for n in names if n.lower().endswith(".kml")), None)
            if candidate is None:
                raise ValueError(f"No KML found in {path}")
            return archive.read(candidate)
    raise ValueError(f"Unsupported file: {path}")


def _geometry_type(root: etree._Element) -> GeometryType:
    found = {kind for local, kind in {"Point":"POINT", "LineString":"LINE", "Polygon":"POLYGON"}.items()
             if root.xpath(f".//kml:{local}", namespaces=NS)}
    if len(found) == 1:
        return next(iter(found))  # type: ignore[return-value]
    return "MIXED" if found else "UNKNOWN"


def _style_table(root: etree._Element) -> dict[str, etree._Element]:
    table = {f"#{style.get('id')}": style for style in root.xpath(".//kml:Style[@id]", namespaces=NS)}
    for style_map in root.xpath(".//kml:StyleMap[@id]", namespaces=NS):
        refs = style_map.xpath("./kml:Pair[kml:key='normal']/kml:styleUrl/text()", namespaces=NS)
        if refs and refs[0] in table:
            table[f"#{style_map.get('id')}"] = table[refs[0]]
    return table


def _inline_key(style: etree._Element) -> str:
    return "inline:" + etree.tostring(style, method="c14n").decode("utf-8")


def analyze_file(path: Path, relative_root: Path | None = None) -> LayerInfo:
    root = etree.fromstring(_read_kml_bytes(path))
    styles = _style_table(root)
    usage: Counter[str] = Counter()
    for placemark in root.xpath(".//kml:Placemark", namespaces=NS):
        inline = placemark.find(f"{{{KML_NS}}}Style")
        style_url = placemark.findtext(f"{{{KML_NS}}}styleUrl")
        if inline is not None:
            usage[_inline_key(inline)] += 1
        elif style_url:
            usage[style_url.strip()] += 1
        else:
            usage["<unstyled>"] += 1

    standard = max(usage, key=usage.get) if usage else None
    standard_xml = (standard[len("inline:"):] if standard and standard.startswith("inline:")
                    else etree.tostring(styles[standard], encoding="unicode") if standard in styles else None)
    relative = path.relative_to(relative_root) if relative_root else Path(path.name)
    stem = path.stem.strip()
    parent_name = path.parent.name.strip()
    name = parent_name if relative_root and path.parent != relative_root and parent_name else stem

    return LayerInfo(name=name, file_path=path, relative_path=relative,
                     geometry_type=_geometry_type(root), feature_count=sum(usage.values()),
                     style_usage=dict(usage), standard_style_key=standard,
                     standard_style_xml=standard_xml)


def scan_project(root: Path) -> list[LayerInfo]:
    root = Path(root)
    files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in {".kml", ".kmz"}]
    return [analyze_file(path, root) for path in files]


def load_tree(path: Path) -> etree._Element:
    return etree.fromstring(_read_kml_bytes(path))


def serialize_tree(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
