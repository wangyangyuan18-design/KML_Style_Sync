from __future__ import annotations

import copy
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from lxml import etree

NS = "http://www.opengis.net/kml/2.2"
NSMAP = {"k": NS}


def q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


@dataclass
class SyncResult:
    output_path: Path
    placemarks_changed: int
    styles_changed: int
    warnings: list[str]


def _local_id(value: str | None) -> str:
    return (value or "").strip().lstrip("#")


def _style_signature(style: etree._Element) -> bytes:
    clone = copy.deepcopy(style)
    clone.attrib.pop("id", None)
    return etree.tostring(clone, method="c14n")


def _collect_styles(root: etree._Element) -> dict[str, etree._Element]:
    return {
        el.get("id"): el
        for el in root.xpath(".//k:Style[@id]", namespaces=NSMAP)
    }


def _collect_stylemaps(root: etree._Element) -> dict[str, etree._Element]:
    return {
        el.get("id"): el
        for el in root.xpath(".//k:StyleMap[@id]", namespaces=NSMAP)
    }


def _style_from_url(root: etree._Element, style_url: str | None) -> etree._Element | None:
    sid = _local_id(style_url)
    if not sid:
        return None
    styles = _collect_styles(root)
    direct = styles.get(sid)
    if direct is not None:
        return direct
    maps = _collect_stylemaps(root)
    sm = maps.get(sid)
    if sm is None:
        return None
    # Normal Google Earth rendering uses normalKey first; fall back to highlightedKey.
    pairs = sm.xpath("./k:Pair", namespaces=NSMAP)
    preferred = None
    for pair in pairs:
        key = pair.find(q("key"))
        url = pair.find(q("styleUrl"))
        if key is not None and url is not None:
            if (key.text or "").strip() == "normalKey":
                preferred = url.text
                break
            preferred = preferred or url.text
    return _style_from_url(root, preferred)


def _replace_inline_style(placemark: etree._Element, standard_style: etree._Element) -> None:
    for child in list(placemark):
        if child.tag == q("Style"):
            placemark.remove(child)
    style = copy.deepcopy(standard_style)
    style.attrib.pop("id", None)
    # Inline style is self-contained and avoids cross-document style ID collisions.
    placemark.insert(0, style)


def _resolve_standard_style(template_root: etree._Element, placemark: etree._Element) -> etree._Element | None:
    inline = placemark.find(q("Style"))
    if inline is not None:
        return inline
    urls = placemark.xpath("./k:styleUrl/text()", namespaces=NSMAP)
    if urls:
        return _style_from_url(template_root, urls[0])
    return None


def _find_output_kml(path: Path) -> str:
    if path.suffix.lower() == ".kml":
        return path.read_text(encoding="utf-8")
    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()
        candidates = [n for n in names if n.lower().endswith(".kml")]
        if not candidates:
            raise ValueError(f"KMZ does not contain a KML file: {path}")
        return zf.read(candidates[0]).decode("utf-8")


def _parse_xml(text: str) -> etree._Element:
    parser = etree.XMLParser(remove_blank_text=False, recover=False)
    return etree.fromstring(text.encode("utf-8"), parser)


def _write_kml(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def sync_kml_or_kmz(source: Path, template: Path, output: Path) -> SyncResult:
    """Synchronize the template's standard styles into a copied source document.

    The source geometry and metadata remain untouched. Styles are embedded per
    Placemark to avoid cross-document Style/StyleMap ID collisions.
    For KMZ, every archive member other than the KML payload is copied byte-for-byte.
    """
    source_text = _find_output_kml(source)
    template_text = _find_output_kml(template)
    source_root = _parse_xml(source_text)
    template_root = _parse_xml(template_text)

    template_placemarks = template_root.xpath(".//k:Placemark", namespaces=NSMAP)
    source_placemarks = source_root.xpath(".//k:Placemark", namespaces=NSMAP)
    if not template_placemarks or not source_placemarks:
        raise ValueError("Source/template contains no Placemark elements")

    # Build a safe fallback standard style from the most frequently referenced
    # template style, while preserving explicit styles for individual template layers.
    style_counts: dict[bytes, int] = {}
    style_by_sig: dict[bytes, etree._Element] = {}
    for pm in template_placemarks:
        style = _resolve_standard_style(template_root, pm)
        if style is not None:
            sig = _style_signature(style)
            style_counts[sig] = style_counts.get(sig, 0) + 1
            style_by_sig[sig] = style
    if not style_counts:
        raise ValueError("Template contains no usable Style or StyleMap references")
    standard_style = style_by_sig[max(style_counts, key=style_counts.get)]

    changed = 0
    for pm in source_placemarks:
        _replace_inline_style(pm, standard_style)
        changed += 1

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".kml":
        output.write_bytes(_write_kml(source_root))
    elif output.suffix.lower() == ".kmz":
        with zipfile.ZipFile(source, "r") as zin, zipfile.ZipFile(output, "w") as zout:
            kml_name = next((n for n in zin.namelist() if n.lower().endswith(".kml")), None)
            if not kml_name:
                raise ValueError("Source KMZ has no KML payload")
            for item in zin.infolist():
                data = _write_kml(source_root) if item.filename == kml_name else zin.read(item.filename)
                zout.writestr(item, data)
    else:
        raise ValueError("Output must end in .kml or .kmz")

    return SyncResult(output, changed, changed, [])
