from __future__ import annotations

import copy
import zipfile
from pathlib import Path
from lxml import etree

from .kml_parser import KML_NS, _read_kml_bytes
from .models import LayerInfo


def _style_from_xml(xml: str) -> etree._Element:
    return etree.fromstring(xml.encode("utf-8"))


def apply_standard_style(source_file: Path, template: LayerInfo, output_file: Path) -> int:
    """Apply the resolved template standard Style inline to every source Placemark.

    Inline application deliberately avoids collisions between unrelated Style IDs.
    Geometry, names, descriptions and folder hierarchy are untouched.
    """
    if not template.standard_style_xml:
        raise ValueError(f"Template {template.name!r} has no resolved style")
    root = etree.fromstring(_read_kml_bytes(source_file))
    style_template = _style_from_xml(template.standard_style_xml)
    count = 0
    for placemark in root.xpath(".//kml:Placemark", namespaces={"kml": KML_NS}):
        old_inline = placemark.find(f"{{{KML_NS}}}Style")
        if old_inline is not None:
            placemark.remove(old_inline)
        style_url = placemark.find(f"{{{KML_NS}}}styleUrl")
        if style_url is not None:
            placemark.remove(style_url)
        # Insert style near the start of Placemark; valid before geometry.
        placemark.insert(0, copy.deepcopy(style_template))
        count += 1

    payload = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if source_file.suffix.lower() == ".kml":
        output_file.write_bytes(payload)
    elif source_file.suffix.lower() == ".kmz":
        with zipfile.ZipFile(source_file) as src, zipfile.ZipFile(output_file, "w", zipfile.ZIP_DEFLATED) as dst:
            replaced = False
            for item in src.infolist():
                data = src.read(item.filename)
                if item.filename.lower() == "doc.kml" or (not replaced and item.filename.lower().endswith(".kml")):
                    data = payload
                    replaced = True
                dst.writestr(item, data)
    else:
        raise ValueError(f"Unsupported file: {source_file}")
    return count
