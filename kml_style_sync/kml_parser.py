from __future__ import annotations

import zipfile
from collections import Counter
from pathlib import Path

from lxml import etree

from .logger import get_logger
from .models import FolderInfo, KMLFileInfo, GeometryType

KML_NS = "http://www.opengis.net/kml/2.2"
NS = {"kml": KML_NS}
log = get_logger()


def normalize_name(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _read_kml_bytes(path: Path) -> bytes:
    path = Path(path)
    log.debug("READ FILE: %s", path)
    if path.suffix.lower() == ".kml":
        return path.read_bytes()
    if path.suffix.lower() == ".kmz":
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            candidate = next((n for n in names if Path(n).name.lower() == "doc.kml"), None)
            candidate = candidate or next((n for n in names if n.lower().endswith(".kml")), None)
            if candidate is None:
                raise ValueError(f"No KML found in {path}")
            log.debug("READ KMZ KML=%s members=%d", candidate, len(names))
            return archive.read(candidate)
    raise ValueError(f"Unsupported input file: {path}")


def load_tree(path: Path) -> etree._Element:
    return etree.fromstring(
        _read_kml_bytes(Path(path)),
        etree.XMLParser(remove_blank_text=False, recover=False),
    )


def _geometry_type(placemarks: list[etree._Element]) -> GeometryType:
    found: set[str] = set()
    checks = (("Point", "POINT"), ("LineString", "LINE"), ("Polygon", "POLYGON"))
    for pm in placemarks:
        for xml_name, kind in checks:
            if pm.xpath(f".//kml:{xml_name}", namespaces=NS):
                found.add(kind)
    if len(found) == 1:
        return next(iter(found))  # type: ignore[return-value]
    if found:
        return "MIXED"
    return "UNKNOWN"


def _style_table(root: etree._Element) -> dict[str, etree._Element]:
    table = {
        f"#{style.get('id')}": style
        for style in root.xpath(".//kml:Style[@id]", namespaces=NS)
        if style.get("id")
    }
    for style_map in root.xpath(".//kml:StyleMap[@id]", namespaces=NS):
        refs = style_map.xpath(
            "./kml:Pair[kml:key='normal']/kml:styleUrl/text()", namespaces=NS
        )
        if refs and refs[0].strip() in table:
            table[f"#{style_map.get('id')}"] = table[refs[0].strip()]
    return table


def _inline_key(style: etree._Element) -> str:
    return "inline:" + etree.tostring(style, method="c14n").decode("utf-8")


def _style_usage(
    root: etree._Element, placemarks: list[etree._Element]
) -> tuple[dict[str, int], str | None, str | None]:
    styles = _style_table(root)
    usage: Counter[str] = Counter()
    for pm in placemarks:
        inline = pm.find(f"{{{KML_NS}}}Style")
        style_url = pm.findtext(f"{{{KML_NS}}}styleUrl")
        if inline is not None:
            usage[_inline_key(inline)] += 1
        elif style_url and style_url.strip():
            usage[style_url.strip()] += 1
        else:
            usage["<unstyled>"] += 1
    standard = max(usage, key=usage.get) if usage else None
    if not standard or standard == "<unstyled>":
        return dict(usage), standard, None
    if standard.startswith("inline:"):
        xml = standard[len("inline:"):]
    else:
        style = styles.get(standard)
        xml = etree.tostring(style, encoding="unicode") if style is not None else None
    return dict(usage), standard, xml


def _folder_name(folder: etree._Element, index: int) -> str:
    value = (folder.findtext(f"{{{KML_NS}}}name") or "").strip()
    return value or f"(未命名 Folder {index})"


def _build_folder_info(
    root: etree._Element,
    folder: etree._Element,
    folder_path: tuple[str, ...],
) -> FolderInfo:
    placemarks = folder.xpath("./kml:Placemark", namespaces=NS)
    usage, standard, standard_xml = _style_usage(root, placemarks)
    info = FolderInfo(
        name=folder_path[-1],
        folder_path=folder_path,
        geometry_type=_geometry_type(placemarks),
        feature_count=len(placemarks),
        style_usage=usage,
        standard_style_key=standard,
        standard_style_xml=standard_xml,
    )
    log.debug(
        "FOLDER: path=%s geometry=%s placemarks=%d standard=%s",
        info.display_path,
        info.geometry_type,
        info.feature_count,
        info.standard_style_key,
    )
    return info


def _walk_folders(
    root: etree._Element,
    parent: etree._Element,
    parent_path: tuple[str, ...],
    result: list[FolderInfo],
) -> None:
    folders = parent.xpath("./kml:Folder", namespaces=NS)
    for index, folder in enumerate(folders, 1):
        name = _folder_name(folder, index)
        path = parent_path + (name,)
        result.append(_build_folder_info(root, folder, path))
        _walk_folders(root, folder, path, result)


def analyze_file(path: Path) -> KMLFileInfo:
    path = Path(path)
    if path.suffix.lower() not in {".kml", ".kmz"}:
        raise ValueError("请选择一个 .kml 或 .kmz 文件。")
    log.info("ANALYZE FILE START: %s", path)
    root = load_tree(path)
    result: list[FolderInfo] = []
    # Start only at top-level Folders. Nested Folders are discovered recursively.
    roots = root.xpath(".//kml:Folder[not(ancestor::kml:Folder)]", namespaces=NS)
    for index, folder in enumerate(roots, 1):
        name = _folder_name(folder, index)
        path_tuple = (name,)
        result.append(_build_folder_info(root, folder, path_tuple))
        _walk_folders(root, folder, path_tuple, result)
    log.info("ANALYZE FILE COMPLETE: folders=%d", len(result))
    return KMLFileInfo(file_path=path, folders=result)


def scan_project(path: Path) -> list[FolderInfo]:
    """Compatibility wrapper: a selected input is exactly one KML/KMZ file."""
    return analyze_file(Path(path)).folders


def serialize_tree(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
