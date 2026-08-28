from __future__ import annotations

import json
import os
import re
import uuid
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from lxml import etree

from .kml_parser import KML_NS, analyze_file, load_tree
from .logger import get_logger

log = get_logger()
NS = {"kml": KML_NS}


def template_root() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or str(Path.home())
    path = Path(base) / "KML_Style_Sync" / "templates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _index_path() -> Path:
    return template_root() / "templates.json"


def _read_index() -> list[dict[str, str]]:
    path = _index_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as exc:
        log.warning("TEMPLATE INDEX READ FAILED: %s", exc)
        return []


def _write_index(items: list[dict[str, str]]) -> None:
    _index_path().write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def list_templates() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    raw = _read_index()
    for item in raw:
        file_name = item.get("file")
        name = item.get("name")
        if file_name and name and (template_root() / file_name).exists():
            items.append({"name": name, "file": file_name})
    if items != raw:
        _write_index(items)
    return items


def template_path(name: str) -> Path | None:
    for item in list_templates():
        if item["name"] == name:
            return template_root() / item["file"]
    return None


def _safe_file_name(name: str) -> str:
    stem = re.sub(r"[^\w\-. ]+", "_", name.strip())[:80].strip() or "template"
    return f"{stem}_{uuid.uuid4().hex[:8]}.kmz"


def _sample_geometry(pm: etree._Element, geometry: str) -> None:
    if geometry == "POINT":
        node = etree.SubElement(pm, f"{{{KML_NS}}}Point")
        etree.SubElement(node, f"{{{KML_NS}}}coordinates").text = "0,0,0"
    elif geometry == "LINE":
        node = etree.SubElement(pm, f"{{{KML_NS}}}LineString")
        etree.SubElement(node, f"{{{KML_NS}}}coordinates").text = "0,0,0 0.001,0.001,0"
    elif geometry == "POLYGON":
        poly = etree.SubElement(pm, f"{{{KML_NS}}}Polygon")
        ring = etree.SubElement(poly, f"{{{KML_NS}}}outerBoundaryIs")
        linear = etree.SubElement(ring, f"{{{KML_NS}}}LinearRing")
        etree.SubElement(linear, f"{{{KML_NS}}}coordinates").text = (
            "0,0,0 0.001,0,0 0.001,0.001,0 0,0.001,0 0,0,0"
        )


def _ensure_folder(
    root: etree._Element,
    cache: dict[tuple[str, ...], etree._Element],
    path_parts: tuple[str, ...],
) -> etree._Element:
    for depth in range(1, len(path_parts) + 1):
        key = path_parts[:depth]
        if key in cache:
            continue
        parent = cache.get(path_parts[: depth - 1], root)
        folder = etree.SubElement(parent, f"{{{KML_NS}}}Folder")
        etree.SubElement(folder, f"{{{KML_NS}}}name").text = key[-1]
        cache[key] = folder
    return cache[path_parts]


def _referenced_assets(style_xml: str | None) -> set[str]:
    if not style_xml:
        return set()
    try:
        style = etree.fromstring(style_xml.encode("utf-8"))
    except Exception:
        return set()
    assets: set[str] = set()
    for href in style.xpath(".//kml:href/text()", namespaces=NS):
        value = unquote(str(href).strip())
        if value and not value.startswith(("http://", "https://", "data:")):
            assets.add(value.replace("\\", "/").lstrip("./"))
    return assets


def _minimal_kml(source_path: Path) -> tuple[bytes, set[str], int]:
    info = analyze_file(source_path, include_styles=True)
    kml = etree.Element(f"{{{KML_NS}}}kml", nsmap={None: KML_NS})
    document = etree.SubElement(kml, f"{{{KML_NS}}}Document")
    etree.SubElement(document, f"{{{KML_NS}}}name").text = f"KML Style Sync Template - {source_path.stem}"
    cache: dict[tuple[str, ...], etree._Element] = {}
    asset_refs: set[str] = set()
    kept = 0

    for folder in info.folders:
        if folder.geometry_type not in {"POINT", "LINE", "POLYGON"}:
            continue
        target = _ensure_folder(document, cache, folder.folder_path)
        pm = etree.SubElement(target, f"{{{KML_NS}}}Placemark")
        etree.SubElement(pm, f"{{{KML_NS}}}name").text = "__KML_STYLE_SYNC_STANDARD__"
        if folder.standard_style_xml and not folder.standard_style_ambiguous:
            try:
                style = etree.fromstring(folder.standard_style_xml.encode("utf-8"))
                style.attrib.pop("id", None)
                pm.append(style)
                asset_refs.update(_referenced_assets(folder.standard_style_xml))
            except Exception as exc:
                log.warning("TEMPLATE STYLE COPY FAILED: %s: %s", folder.display_path, exc)
        _sample_geometry(pm, folder.geometry_type)
        kept += 1

    return (
        etree.tostring(kml, xml_declaration=True, encoding="UTF-8", pretty_print=True),
        asset_refs,
        kept,
    )


def _asset_bytes(source_path: Path, archive: zipfile.ZipFile | None, asset: str) -> bytes | None:
    normalized = asset.replace("\\", "/").lstrip("/")
    if archive is not None:
        names = {name.replace("\\", "/").lstrip("/"): name for name in archive.namelist()}
        member = names.get(normalized) or names.get("files/" + normalized)
        if member:
            return archive.read(member)
        return None

    candidate = (source_path.parent / normalized).resolve()
    try:
        candidate.relative_to(source_path.parent.resolve())
    except ValueError:
        return None
    return candidate.read_bytes() if candidate.exists() and candidate.is_file() else None


def build_minimal_template(source_path: Path, output_path: Path) -> int:
    """Save one compact KMZ: one representative Placemark + highest-use Style per B layer.

    Only small style definitions and referenced local style assets are retained.
    All original Placemarks/geometries are discarded from the template copy.
    """
    source_path = Path(source_path)
    output_path = Path(output_path)
    kml_bytes, assets, kept = _minimal_kml(source_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    archive: zipfile.ZipFile | None = None
    try:
        if source_path.suffix.lower() == ".kmz":
            archive = zipfile.ZipFile(source_path, "r")
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as out:
            out.writestr("doc.kml", kml_bytes)
            for asset in sorted(assets):
                try:
                    data = _asset_bytes(source_path, archive, asset)
                except Exception as exc:
                    log.warning("TEMPLATE ASSET COPY FAILED: %s: %s", asset, exc)
                    continue
                if data is None:
                    log.warning("TEMPLATE ASSET NOT FOUND: %s", asset)
                    continue
                out.writestr(asset, data)
    finally:
        if archive is not None:
            archive.close()

    log.info(
        "TEMPLATE BUILT source=%s output=%s effective_layers=%d assets=%d",
        source_path,
        output_path,
        kept,
        len(assets),
    )
    return kept


def save_template(source_path: Path, name: str) -> Path:
    name = name.strip()
    if not name:
        raise ValueError("模板名称不能为空。")
    for item in list_templates():
        if item["name"] == name:
            raise ValueError(f"模板名称已存在：{name}")
    file_name = _safe_file_name(name)
    path = template_root() / file_name
    build_minimal_template(Path(source_path), path)
    items = list_templates()
    items.append({"name": name, "file": file_name})
    _write_index(items)
    return path


def rename_template(old_name: str, new_name: str) -> None:
    new_name = new_name.strip()
    if not new_name:
        raise ValueError("模板名称不能为空。")
    items = list_templates()
    if any(item["name"] == new_name for item in items):
        raise ValueError(f"模板名称已存在：{new_name}")
    for item in items:
        if item["name"] == old_name:
            item["name"] = new_name
            _write_index(items)
            return
    raise ValueError(f"找不到模板：{old_name}")


def delete_template(name: str) -> None:
    items = list_templates()
    kept: list[dict[str, str]] = []
    target: Path | None = None
    for item in items:
        if item["name"] == name:
            target = template_root() / item["file"]
        else:
            kept.append(item)
    if target is None:
        raise ValueError(f"找不到模板：{name}")
    target.unlink(missing_ok=True)
    _write_index(kept)


def template_summary(name: str) -> dict[str, Any]:
    path = template_path(name)
    if path is None:
        raise ValueError(f"找不到模板：{name}")
    info = analyze_file(path, include_styles=True)
    return {
        "name": name,
        "file": str(path),
        "effective_layers": len(info.folders),
        "folders": [
            {
                "path": folder.display_path,
                "geometry": folder.geometry_type,
                "style": folder.standard_style_key,
                "ratio": folder.standard_style_ratio,
            }
            for folder in info.folders
        ],
    }
