from __future__ import annotations

import copy
import logging
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from lxml import etree

from .logger import get_logger

NS = "http://www.opengis.net/kml/2.2"
NSMAP = {"k": NS}
log = get_logger()


def q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


@dataclass
class SyncResult:
    output_path: Path
    placemarks_changed: int
    styles_changed: int
    warnings: list[str]


def _local_id(value: str | None) -> str:
    return (value or "").strip().lstrip("#").split("/")[-1]


def _style_signature(style: etree._Element) -> bytes:
    clone = copy.deepcopy(style)
    clone.attrib.pop("id", None)
    return etree.tostring(clone, method="c14n")


def _collect_styles(root: etree._Element) -> dict[str, etree._Element]:
    return {el.get("id"): el for el in root.xpath(".//k:Style[@id]", namespaces=NSMAP)}


def _collect_stylemaps(root: etree._Element) -> dict[str, etree._Element]:
    return {el.get("id"): el for el in root.xpath(".//k:StyleMap[@id]", namespaces=NSMAP)}


def _resolve_style(root: etree._Element, style_url: str | None, visited: set[str] | None = None) -> etree._Element | None:
    sid = _local_id(style_url)
    if not sid:
        return None
    visited = visited or set()
    if sid in visited:
        log.warning("STYLE CYCLE: %s", sid)
        return None
    visited.add(sid)
    styles = _collect_styles(root)
    if sid in styles:
        return styles[sid]
    sm = _collect_stylemaps(root).get(sid)
    if sm is None:
        log.warning("STYLE NOT FOUND: %s", sid)
        return None
    fallback: str | None = None
    for pair in sm.xpath("./k:Pair", namespaces=NSMAP):
        key = pair.find(q("key"))
        url = pair.find(q("styleUrl"))
        if url is None or not (url.text or "").strip():
            continue
        if key is not None and (key.text or "").strip() in {"normalKey", "normal"}:
            return _resolve_style(root, url.text, visited)
        fallback = fallback or url.text
    return _resolve_style(root, fallback, visited) if fallback else None


def _resolve_pm_style(root: etree._Element, pm: etree._Element) -> etree._Element | None:
    inline = pm.find(q("Style"))
    if inline is not None:
        return inline
    urls = pm.xpath("./k:styleUrl/text()", namespaces=NSMAP)
    return _resolve_style(root, urls[0]) if urls else None


def _geometry_type(pm: etree._Element) -> str:
    flags = {"POINT": bool(pm.xpath(".//k:Point", namespaces=NSMAP)), "LINE": bool(pm.xpath(".//k:LineString", namespaces=NSMAP)), "POLYGON": bool(pm.xpath(".//k:Polygon", namespaces=NSMAP))}
    kinds = [k for k, present in flags.items() if present]
    return kinds[0] if len(kinds) == 1 else ("MIXED" if kinds else "UNKNOWN")


def _replace_style(pm: etree._Element, style: etree._Element) -> None:
    for child in list(pm):
        if child.tag in (q("Style"), q("styleUrl")):
            pm.remove(child)
    clone = copy.deepcopy(style)
    clone.attrib.pop("id", None)
    pm.insert(0, clone)


def _read_kml(path: Path) -> tuple[bytes, str | None]:
    log.debug("READ SOURCE: %s", path)
    if path.suffix.lower() == ".kml":
        return path.read_bytes(), None
    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()
        kml = next((n for n in names if n.lower().endswith(".kml") and Path(n).name.lower() == "doc.kml"), None)
        kml = kml or next((n for n in names if n.lower().endswith(".kml")), None)
        if not kml:
            raise ValueError(f"KMZ does not contain a KML file: {path}")
        log.debug("KMZ payload: %s; members=%d", kml, len(names))
        return zf.read(kml), kml


def _parse(data: bytes, label: str) -> etree._Element:
    log.debug("XML PARSE: %s bytes=%d", label, len(data))
    return etree.fromstring(data, etree.XMLParser(remove_blank_text=False, recover=False))


def _serialize(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def _copy_tree(source: Path, output: Path) -> None:
    log.info("COPY PROJECT: %s -> %s", source, output)
    shutil.copytree(source, output)


def sync_project(source: Path, template: Path, output: Path, mappings: dict[Path, Path]) -> SyncResult:
    log.info("SYNC START source=%s template=%s output=%s mappings=%d", source, template, output, len(mappings))
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    _copy_tree(source, output)
    warnings: list[str] = []
    changed = 0
    styles_changed = 0

    for index, (source_rel, template_rel) in enumerate(mappings.items(), 1):
        log.info("MAPPING %d/%d: A=%s <- B=%s", index, len(mappings), source_rel, template_rel)
        src = source / source_rel
        tpl = template / template_rel
        if not src.exists() or not tpl.exists():
            message = f"Missing mapping: {source_rel} <- {template_rel}"
            log.error(message)
            warnings.append(message)
            continue
        try:
            src_data, src_kml_name = _read_kml(src)
            tpl_data, _ = _read_kml(tpl)
            src_root = _parse(src_data, str(src))
            tpl_root = _parse(tpl_data, str(tpl))
            template_pms = tpl_root.xpath(".//k:Placemark", namespaces=NSMAP)
            source_pms = src_root.xpath(".//k:Placemark", namespaces=NSMAP)
            log.info("PLACEMARKS A=%d B=%d", len(source_pms), len(template_pms))
            if not template_pms:
                warnings.append(f"No Placemark in template: {template_rel}")
                continue

            counts: dict[bytes, int] = {}
            style_by_sig: dict[bytes, etree._Element] = {}
            for pm in template_pms:
                style = _resolve_pm_style(tpl_root, pm)
                if style is None:
                    continue
                sig = _style_signature(style)
                counts[sig] = counts.get(sig, 0) + 1
                style_by_sig[sig] = style
            if not counts:
                message = f"No usable Style/StyleMap in template: {template_rel}"
                log.error(message)
                warnings.append(message)
                continue
            standard = style_by_sig[max(counts, key=counts.get)]
            log.info("STANDARD STYLE selected usage=%d/%d", max(counts.values()), len(template_pms))

            target_type = _geometry_type(template_pms[0])
            file_changed = 0
            for pm in source_pms:
                if _geometry_type(pm) != target_type:
                    continue
                _replace_style(pm, standard)
                file_changed += 1
            changed += file_changed
            styles_changed += file_changed
            log.info("STYLE APPLIED: %d Placemark(s), geometry=%s", file_changed, target_type)

            dst = output / source_rel
            if src.suffix.lower() == ".kml":
                dst.write_bytes(_serialize(src_root))
            else:
                with zipfile.ZipFile(src, "r") as zin, zipfile.ZipFile(dst, "w") as zout:
                    for item in zin.infolist():
                        data = _serialize(src_root) if item.filename == src_kml_name else zin.read(item.filename)
                        zout.writestr(item, data)
                log.info("KMZ WRITTEN: %s", dst)
        except Exception:
            log.exception("MAPPING FAILED: A=%s <- B=%s", source_rel, template_rel)
            raise

    log.info("SYNC COMPLETE changed=%d styles=%d warnings=%d", changed, styles_changed, len(warnings))
    return SyncResult(output, changed, styles_changed, warnings)
