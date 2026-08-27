from __future__ import annotations

import copy
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
    return {el.get("id"): el for el in root.xpath(".//k:Style[@id]", namespaces=NSMAP) if el.get("id")}


def _collect_stylemaps(root: etree._Element) -> dict[str, etree._Element]:
    return {el.get("id"): el for el in root.xpath(".//k:StyleMap[@id]", namespaces=NSMAP) if el.get("id")}


def _resolve_style(root: etree._Element, style_url: str | None, visited: set[str] | None = None) -> etree._Element | None:
    sid = _local_id(style_url)
    if not sid:
        return None
    visited = set() if visited is None else set(visited)
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


def _replace_style(pm: etree._Element, style: etree._Element) -> None:
    for child in list(pm):
        if child.tag in (q("Style"), q("styleUrl")):
            pm.remove(child)
    clone = copy.deepcopy(style)
    clone.attrib.pop("id", None)
    pm.insert(0, clone)


def _read_kml(path: Path) -> tuple[bytes, str | None]:
    if path.suffix.lower() == ".kml":
        return path.read_bytes(), None
    with zipfile.ZipFile(path, "r") as zf:
        kml_name = next((n for n in zf.namelist() if Path(n).name.lower() == "doc.kml"), None)
        kml_name = kml_name or next((n for n in zf.namelist() if n.lower().endswith(".kml")), None)
        if not kml_name:
            raise ValueError(f"KMZ does not contain a KML file: {path}")
        return zf.read(kml_name), kml_name


def _parse(data: bytes, label: str) -> etree._Element:
    log.debug("XML PARSE: %s bytes=%d", label, len(data))
    return etree.fromstring(data, etree.XMLParser(remove_blank_text=False, recover=False))


def _serialize(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def _folder_name(folder: etree._Element, index: int) -> str:
    name = (folder.findtext(q("name")) or "").strip()
    return name or f"(未命名 Folder {index})"


def _folder_index(root: etree._Element) -> dict[tuple[str, ...], etree._Element]:
    result: dict[tuple[str, ...], etree._Element] = {}

    def walk(parent: etree._Element, parent_path: tuple[str, ...]) -> None:
        for index, folder in enumerate(parent.xpath("./k:Folder", namespaces=NSMAP), 1):
            name = _folder_name(folder, index)
            path = parent_path + (name,)
            result[path] = folder
            walk(folder, path)

    roots = root.xpath(".//k:Folder[not(ancestor::k:Folder)]", namespaces=NSMAP)
    for index, folder in enumerate(roots, 1):
        name = _folder_name(folder, index)
        path = (name,)
        result[path] = folder
        walk(folder, path)
    return result


def _standard_style_for_folder(root: etree._Element, folder: etree._Element, label: str) -> tuple[etree._Element | None, str | None]:
    placemarks = folder.xpath("./k:Placemark", namespaces=NSMAP)
    counts: dict[bytes, int] = {}
    style_by_sig: dict[bytes, etree._Element] = {}
    for pm in placemarks:
        style = _resolve_pm_style(root, pm)
        if style is None:
            continue
        sig = _style_signature(style)
        counts[sig] = counts.get(sig, 0) + 1
        style_by_sig[sig] = style
    if not counts:
        return None, f"B Folder 没有可用 Style：{label}"
    maximum = max(counts.values())
    winners = [sig for sig, count in counts.items() if count == maximum]
    if len(winners) > 1:
        return None, f"B Folder 存在多个最高占比 Style，需人工确认：{label}"
    return style_by_sig[winners[0]], None


def _apply_to_folder(root: etree._Element, folder_path: tuple[str, ...], standard: etree._Element) -> int:
    folder = _folder_index(root).get(folder_path)
    if folder is None:
        log.warning("SOURCE FOLDER NOT FOUND: %s", " / ".join(folder_path))
        return 0
    changed = 0
    for pm in folder.xpath("./k:Placemark", namespaces=NSMAP):
        _replace_style(pm, standard)
        changed += 1
    return changed


def sync_file(source: Path, template: Path, output: Path, mappings: dict[tuple[str, ...], tuple[str, ...]]) -> SyncResult:
    source = Path(source)
    template = Path(template)
    output = Path(output)
    log.info("SYNC START A=%s B=%s OUTPUT=%s MAPPINGS=%d", source, template, output, len(mappings))
    if source.resolve() == output.resolve():
        raise ValueError("输出文件不能覆盖 A 原始工程文件，请选择新的输出文件。")
    if output.suffix.lower() != source.suffix.lower():
        raise ValueError("A 工程与输出文件的扩展名必须保持一致。")

    src_data, src_kml_name = _read_kml(source)
    tpl_data, _ = _read_kml(template)
    src_root = _parse(src_data, str(source))
    tpl_root = _parse(tpl_data, str(template))
    template_folders = _folder_index(tpl_root)
    warnings: list[str] = []
    changed = 0

    for source_path, template_path in mappings.items():
        label = " / ".join(template_path)
        log.info("MAPPING A=%s <- B=%s", " / ".join(source_path), label)
        template_folder = template_folders.get(template_path)
        if template_folder is None:
            warnings.append(f"B Folder 不存在：{label}")
            continue
        standard, error = _standard_style_for_folder(tpl_root, template_folder, label)
        if error:
            warnings.append(error)
            continue
        assert standard is not None
        file_changed = _apply_to_folder(src_root, source_path, standard)
        changed += file_changed
        log.info("STYLE APPLIED folder=%s placemarks=%d", " / ".join(source_path), file_changed)

    output.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() == ".kml":
        output.write_bytes(_serialize(src_root))
    else:
        with zipfile.ZipFile(source, "r") as zin, zipfile.ZipFile(output, "w") as zout:
            for item in zin.infolist():
                data = _serialize(src_root) if item.filename == src_kml_name else zin.read(item.filename)
                zout.writestr(item, data)
    return SyncResult(output, changed, changed, warnings)
