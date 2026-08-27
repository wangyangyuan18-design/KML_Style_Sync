from __future__ import annotations

import zipfile
from collections import Counter
from pathlib import Path
from lxml import etree

from .models import GeometryType, LayerInfo
from .logger import get_logger

KML_NS = "http://www.opengis.net/kml/2.2"
NS = {"kml": KML_NS}
log = get_logger()


def normalize_name(value: str) -> str:
    return " ".join(Path(value).stem.strip().lower().split())


def _read_kml_bytes(path: Path) -> bytes:
    log.debug("READ: %s", path)
    if path.suffix.lower() == ".kml":
        data = path.read_bytes()
        log.debug("READ KML bytes=%d", len(data))
        return data
    if path.suffix.lower() == ".kmz":
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            candidate = next((n for n in names if n.lower() == "doc.kml"), None)
            candidate = candidate or next((n for n in names if n.lower().endswith(".kml")), None)
            if candidate is None:
                raise ValueError(f"No KML found in {path}")
            data = archive.read(candidate)
            log.debug("READ KMZ KML=%s bytes=%d members=%d", candidate, len(data), len(names))
            return data
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
    log.info("ANALYZE START: %s", path)
    root = etree.fromstring(_read_kml_bytes(path))
    styles = _style_table(root)
    usage: Counter[str] = Counter()
    placemarks = root.xpath(".//kml:Placemark", namespaces=NS)
    for placemark in placemarks:
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
    geometry = _geometry_type(root)
    log.info("ANALYZE OK: name=%s geometry=%s placemarks=%d styles=%d standard=%s", name, geometry, len(placemarks), len(styles), standard)

    return LayerInfo(name=name, file_path=path, relative_path=relative,
                     geometry_type=geometry, feature_count=len(placemarks),
                     style_usage=dict(usage), standard_style_key=standard,
                     standard_style_xml=standard_xml)


def scan_project(root: Path) -> list[LayerInfo]:
    root = Path(root)
    log.info("SCAN START: %s", root)
    files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in {".kml", ".kmz"}]
    log.info("SCAN FOUND: %d KML/KMZ files", len(files))
    result: list[LayerInfo] = []
    for path in files:
        try:
            result.append(analyze_file(path, root))
        except Exception:
            log.exception("ANALYZE FAILED: %s", path)
            raise
    log.info("SCAN COMPLETE: %d layers", len(result))
    return result


def load_tree(path: Path) -> etree._Element:
    return etree.fromstring(_read_kml_bytes(path))


def serialize_tree(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
