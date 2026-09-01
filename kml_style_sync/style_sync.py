from __future__ import annotations

import copy
import hashlib
import posixpath
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

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
    folder_names_changed: int
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


def _resolve_style(
    root: etree._Element,
    style_url: str | None,
    styles: dict[str, etree._Element],
    style_maps: dict[str, etree._Element],
    visited: set[str] | None = None,
) -> etree._Element | None:
    sid = _local_id(style_url)
    if not sid:
        return None
    visited = set() if visited is None else set(visited)
    if sid in visited:
        log.warning("STYLE CYCLE: %s", sid)
        return None
    visited.add(sid)
    if sid in styles:
        return styles[sid]
    sm = style_maps.get(sid)
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
            return _resolve_style(root, url.text, styles, style_maps, visited)
        fallback = fallback or url.text
    return _resolve_style(root, fallback, styles, style_maps, visited) if fallback else None


def _resolve_pm_style(
    root: etree._Element,
    pm: etree._Element,
    styles: dict[str, etree._Element],
    style_maps: dict[str, etree._Element],
) -> etree._Element | None:
    inline = pm.find(q("Style"))
    if inline is not None:
        return inline
    urls = pm.xpath("./k:styleUrl/text()", namespaces=NSMAP)
    return _resolve_style(root, urls[0], styles, style_maps) if urls else None


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


def _standard_style_for_folder(
    root: etree._Element,
    folder: etree._Element,
    label: str,
    styles: dict[str, etree._Element],
    style_maps: dict[str, etree._Element],
) -> tuple[etree._Element | None, str | None]:
    placemarks = folder.xpath("./k:Placemark", namespaces=NSMAP)
    counts: dict[bytes, int] = {}
    style_by_sig: dict[bytes, etree._Element] = {}
    for pm in placemarks:
        style = _resolve_pm_style(root, pm, styles, style_maps)
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


def _prepare_style_for_kmz(
    style: etree._Element,
    template_path: Path,
    template_archive: zipfile.ZipFile | None,
    asset_payloads: dict[str, bytes],
    asset_map: dict[str, str],
    warnings: list[str],
) -> etree._Element:
    clone = copy.deepcopy(style)
    for href in clone.xpath(".//k:href", namespaces=NSMAP):
        original = unquote((href.text or "").strip())
        if not original or original.startswith(("http://", "https://", "data:")):
            continue
        normalized = posixpath.normpath(original.replace("\\", "/")).lstrip("/")
        while normalized.startswith("../"):
            normalized = normalized[3:]
        if normalized in asset_map:
            href.text = asset_map[normalized]
            continue

        data: bytes | None = None
        if template_archive is not None:
            names = {name.replace("\\", "/").lstrip("/"): name for name in template_archive.namelist()}
            member = names.get(normalized) or names.get("files/" + normalized)
            if member:
                try:
                    data = template_archive.read(member)
                except Exception as exc:
                    warnings.append(f"读取 Style 资源失败：{original} ({exc})")
        else:
            candidate = (template_path.parent / normalized).resolve()
            try:
                candidate.relative_to(template_path.parent.resolve())
                if candidate.is_file():
                    data = candidate.read_bytes()
            except ValueError:
                pass

        if data is None:
            warnings.append(f"未找到 Style 资源：{original}")
            continue
        digest = hashlib.sha256(data).hexdigest()[:12]
        destination = f"kml_style_sync_assets/{digest}_{Path(normalized).name or 'asset.bin'}"
        asset_payloads[destination] = data
        asset_map[normalized] = destination
        href.text = destination
    return clone


def sync_file(
    source: Path,
    template: Path,
    output: Path,
    mappings: dict[tuple[str, ...], tuple[str, ...]],
    use_template_folder_structure: bool = False,
) -> SyncResult:
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
    template_styles = _collect_styles(tpl_root)
    template_stylemaps = _collect_stylemaps(tpl_root)
    template_folders = _folder_index(tpl_root)
    source_folders = _folder_index(src_root)

    # Optional structural mode: B is the output folder template.
    # All B folders are preserved; matched A Placemark content is copied
    # into the corresponding B folders.
    output_root = copy.deepcopy(tpl_root) if use_template_folder_structure else src_root
    output_folders = _folder_index(output_root)
    warnings: list[str] = []
    changed = 0
    changed_styles = 0
    folder_names_changed = 0
    template_archive: zipfile.ZipFile | None = None
    asset_payloads: dict[str, bytes] = {}
    asset_map: dict[str, str] = {}

    try:
        if template.suffix.lower() == ".kmz":
            template_archive = zipfile.ZipFile(template, "r")

        for source_path, template_path_value in mappings.items():
            label = " / ".join(template_path_value)
            log.info("MAPPING A=%s <- B=%s", " / ".join(source_path), label)
            template_folder = template_folders.get(template_path_value)
            if template_folder is None:
                warnings.append(f"B Folder 不存在：{label}")
                continue
            if use_template_folder_structure:
                source_folder = source_folders.get(source_path)
                target_folder = output_folders.get(template_path_value)
                if source_folder is None or target_folder is None:
                    warnings.append(f"无法迁入 Folder 内容：A {' / '.join(source_path)} -> B {label}")
                    continue

                # Keep B's complete hierarchy. For a matched effective folder,
                # replace only its direct Placemark content with A's content.
                for pm in list(target_folder.xpath("./k:Placemark", namespaces=NSMAP)):
                    target_folder.remove(pm)

                moved_count = 0
                for pm in source_folder.xpath("./k:Placemark", namespaces=NSMAP):
                    target_folder.append(copy.deepcopy(pm))
                    moved_count += 1
                folder_names_changed += moved_count
                log.info(
                    "CONTENT COPIED INTO B FOLDER A=%s -> B=%s placemarks=%d",
                    " / ".join(source_path), label, moved_count
                )

            standard, error = _standard_style_for_folder(
                tpl_root, template_folder, label, template_styles, template_stylemaps
            )
            if error:
                warnings.append(error)
                continue
            assert standard is not None

            if output.suffix.lower() == ".kmz":
                standard_for_output = _prepare_style_for_kmz(
                    standard, template, template_archive, asset_payloads, asset_map, warnings
                )
            else:
                standard_for_output = copy.deepcopy(standard)

            target_folder = (
                output_folders.get(template_path_value)
                if use_template_folder_structure
                else source_folders.get(source_path)
            )
            if target_folder is None:
                warnings.append(
                    f"输出 Folder 不存在：{' / '.join(template_path_value if use_template_folder_structure else source_path)}"
                )
                continue

            file_changed = 0
            for pm in target_folder.xpath("./k:Placemark", namespaces=NSMAP):
                _replace_style(pm, standard_for_output)
                file_changed += 1

            changed += file_changed
            changed_styles += 1 if file_changed else 0
            log.info("STYLE APPLIED folder=%s placemarks=%d", " / ".join(source_path), file_changed)

        output.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix.lower() == ".kml":
            output.write_bytes(_serialize(output_root))
        else:
            with zipfile.ZipFile(source, "r") as zin, zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = _serialize(output_root) if item.filename == src_kml_name else zin.read(item.filename)
                    zout.writestr(item, data)
                for asset_name, data in asset_payloads.items():
                    if asset_name not in zin.namelist():
                        zout.writestr(asset_name, data)
    finally:
        if template_archive is not None:
            template_archive.close()

    return SyncResult(output, changed, changed_styles, folder_names_changed, warnings)
