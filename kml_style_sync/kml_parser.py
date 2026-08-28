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
                raise ValueError(f"KMZ 中没有 KML：{path}")
            return archive.read(candidate)
    raise ValueError(f"不支持的文件：{path}")


def load_tree(path: Path) -> etree._Element:
    return etree.fromstring(_read_kml_bytes(Path(path)), etree.XMLParser(remove_blank_text=False, recover=False))


def _geometry_type(placemarks: list[etree._Element]) -> GeometryType:
    found: set[str] = set()
    for pm in placemarks:
        if pm.xpath(".//kml:Point", namespaces=NS):
            found.add("POINT")
        if pm.xpath(".//kml:LineString", namespaces=NS):
            found.add("LINE")
        if pm.xpath(".//kml:Polygon", namespaces=NS):
            found.add("POLYGON")
    if len(found) == 1:
        return next(iter(found))  # type: ignore[return-value]
    if len(found) > 1:
        return "MIXED"
    return "UNKNOWN"


def _style_table(root: etree._Element) -> dict[str, etree._Element]:
    return {
        f"#{style.get('id')}": style
        for style in root.xpath(".//kml:Style[@id]", namespaces=NS)
        if style.get("id")
    }


def _style_maps(root: etree._Element) -> dict[str, etree._Element]:
    return {
        f"#{style_map.get('id')}": style_map
        for style_map in root.xpath(".//kml:StyleMap[@id]", namespaces=NS)
        if style_map.get("id")
    }


def _local_style_id(value: str | None) -> str:
    return (value or "").strip().lstrip("#").split("/")[-1]


def _resolve_style(
    style_url: str | None,
    styles: dict[str, etree._Element],
    style_maps: dict[str, etree._Element],
    visited: set[str] | None = None,
) -> etree._Element | None:
    sid = _local_style_id(style_url)
    if not sid:
        return None
    visited = set() if visited is None else set(visited)
    if sid in visited:
        log.warning("STYLE CYCLE: %s", sid)
        return None
    visited.add(sid)
    direct = styles.get(f"#{sid}")
    if direct is not None:
        return direct
    style_map = style_maps.get(f"#{sid}")
    if style_map is None:
        return None
    fallback: str | None = None
    for pair in style_map.xpath("./kml:Pair", namespaces=NS):
        key = (pair.findtext(f"{{{KML_NS}}}key") or "").strip()
        url = (pair.findtext(f"{{{KML_NS}}}styleUrl") or "").strip()
        if not url:
            continue
        if key in {"normalKey", "normal"}:
            return _resolve_style(url, styles, style_maps, visited)
        fallback = fallback or url
    return _resolve_style(fallback, styles, style_maps, visited) if fallback else None


def _inline_key(style: etree._Element) -> str:
    return "inline:" + etree.tostring(style, method="c14n").decode("utf-8")


def _effective_style_key(
    placemark: etree._Element,
    styles: dict[str, etree._Element],
    style_maps: dict[str, etree._Element],
) -> str:
    inline = placemark.find(f"{{{KML_NS}}}Style")
    if inline is not None:
        return _inline_key(inline)
    url = placemark.findtext(f"{{{KML_NS}}}styleUrl")
    style = _resolve_style(url, styles, style_maps)
    if style is None:
        return "<unstyled>"
    sid = style.get("id")
    return f"#{sid}" if sid else _inline_key(style)


def _style_usage(
    placemarks: list[etree._Element],
    styles: dict[str, etree._Element],
    style_maps: dict[str, etree._Element],
) -> tuple[dict[str, int], str | None, str | None, bool]:
    usage: Counter[str] = Counter(_effective_style_key(pm, styles, style_maps) for pm in placemarks)
    usable = {key: count for key, count in usage.items() if key != "<unstyled>"}
    if not usable:
        return dict(usage), "<unstyled>", None, False
    maximum = max(usable.values())
    winners = [key for key, count in usable.items() if count == maximum]
    if len(winners) > 1:
        return dict(usage), None, None, True
    standard = winners[0]
    if standard.startswith("inline:"):
        return dict(usage), standard, standard[len("inline:"):], False
    style = styles.get(standard)
    xml = etree.tostring(style, encoding="unicode") if style is not None else None
    return dict(usage), standard, xml, False


def _folder_name(folder: etree._Element, index: int) -> str:
    value = (folder.findtext(f"{{{KML_NS}}}name") or "").strip()
    return value or f"(未命名 Folder {index})"


def _build_folder_info(
    folder: etree._Element,
    folder_path: tuple[str, ...],
    styles: dict[str, etree._Element] | None,
    style_maps: dict[str, etree._Element] | None,
) -> FolderInfo:
    placemarks = folder.xpath("./kml:Placemark", namespaces=NS)
    geometry = _geometry_type(placemarks)
    if styles is None or style_maps is None:
        usage, standard, standard_xml, ambiguous = {}, None, None, False
    else:
        usage, standard, standard_xml, ambiguous = _style_usage(placemarks, styles, style_maps)
    return FolderInfo(
        name=folder_path[-1],
        folder_path=folder_path,
        geometry_type=geometry,
        feature_count=len(placemarks),
        style_usage=usage,
        standard_style_key=standard,
        standard_style_xml=standard_xml,
        standard_style_ambiguous=ambiguous,
    )


def _walk_folders(
    parent: etree._Element,
    parent_path: tuple[str, ...],
    result: list[FolderInfo],
    styles: dict[str, etree._Element] | None,
    style_maps: dict[str, etree._Element] | None,
) -> None:
    for index, folder in enumerate(parent.xpath("./kml:Folder", namespaces=NS), 1):
        name = _folder_name(folder, index)
        path = parent_path + (name,)
        result.append(_build_folder_info(folder, path, styles, style_maps))
        _walk_folders(folder, path, result, styles, style_maps)


def analyze_file(path: Path, include_styles: bool = True) -> KMLFileInfo:
    path = Path(path)
    if path.suffix.lower() not in {".kml", ".kmz"}:
        raise ValueError("请选择一个 .kml 或 .kmz 文件。")
    log.info("ANALYZE FILE START: %s include_styles=%s", path, include_styles)
    root = load_tree(path)
    styles = _style_table(root) if include_styles else None
    style_maps = _style_maps(root) if include_styles else None

    parsed: list[FolderInfo] = []
    roots = root.xpath(".//kml:Folder[not(ancestor::kml:Folder)]", namespaces=NS)
    for index, folder in enumerate(roots, 1):
        name = _folder_name(folder, index)
        folder_path = (name,)
        parsed.append(_build_folder_info(folder, folder_path, styles, style_maps))
        _walk_folders(folder, folder_path, parsed, styles, style_maps)

    result = [folder for folder in parsed if folder.is_effective_layer]

    if not result and not roots:
        placemarks = root.xpath(".//kml:Placemark", namespaces=NS)
        geometry = _geometry_type(placemarks)
        if include_styles and styles is not None and style_maps is not None:
            usage, standard, standard_xml, ambiguous = _style_usage(placemarks, styles, style_maps)
        else:
            usage, standard, standard_xml, ambiguous = {}, None, None, False
        implicit = FolderInfo(
            name=path.stem,
            folder_path=(path.stem,),
            geometry_type=geometry,
            feature_count=len(placemarks),
            style_usage=usage,
            standard_style_key=standard,
            standard_style_xml=standard_xml,
            standard_style_ambiguous=ambiguous,
        )
        if implicit.is_effective_layer:
            result.append(implicit)

    log.info(
        "ANALYZE FILE COMPLETE: folders=%d effective_layers=%d containers_or_empty=%d",
        len(parsed),
        len(result),
        len(parsed) - len(result),
    )
    return KMLFileInfo(file_path=path, folders=result)


def scan_project(path: Path) -> list[FolderInfo]:
    return analyze_file(Path(path), include_styles=False).folders


def serialize_tree(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
