from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .kml_parser import analyze_file
from .matcher import build_match_rows, candidates_for
from .models import FolderInfo, KMLFileInfo, MatchRow
from .style_sync import sync_file


class MainWindow(QMainWindow):
    """Standalone B-centric KML/KMZ style synchronization UI."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("KML Style Sync - Standalone")
        self.resize(1500, 820)
        self.source_info: KMLFileInfo | None = None
        self.template_info: KMLFileInfo | None = None
        self.rows: list[MatchRow] = []
        self._building_table = False
        self._combo_boxes: list[QComboBox] = []
        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        top = QHBoxLayout()
        self.source_label = QLabel("A 工程文件：未选择")
        source_btn = QPushButton("选择 A 工程文件")
        source_btn.clicked.connect(self.choose_source)
        self.template_label = QLabel("B 标准文件：未选择")
        template_btn = QPushButton("选择 B 标准文件")
        template_btn.clicked.connect(self.choose_template)
        top.addWidget(self.source_label, 1)
        top.addWidget(source_btn)
        top.addWidget(self.template_label, 1)
        top.addWidget(template_btn)
        layout.addLayout(top)

        hint = QLabel(
            "B 是标准库：先完整解析 B 文件中的全部 Folder、Geometry 与标准 Style；"
            "表格严格按 B Folder 原始顺序建立。A 仅负责选择对应 Folder；候选 A 只允许与 B 具有相同 Geometry。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "B 标准 Folder",
            "Geometry B",
            "标准 Style",
            "A 工程 Folder（可选择）",
            "Geometry A",
            "匹配状态",
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        layout.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.info = QLabel("请先选择 A 工程文件和 B 标准文件")
        refresh_btn = QPushButton("按名称重新匹配")
        refresh_btn.clicked.connect(self.refresh_matches)
        apply_btn = QPushButton("执行 Style 同步")
        apply_btn.clicked.connect(self.apply_sync)
        bottom.addWidget(self.info, 1)
        bottom.addWidget(refresh_btn)
        bottom.addWidget(apply_btn)
        layout.addLayout(bottom)

    @staticmethod
    def _file_filter() -> str:
        return "KML/KMZ 文件 (*.kml *.kmz);;KML 文件 (*.kml);;KMZ 文件 (*.kmz)"

    def choose_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 A 待同步工程文件", "", self._file_filter())
        if path:
            self._load_source(Path(path))

    def choose_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 B 标准文件", "", self._file_filter())
        if path:
            self._load_template(Path(path))

    def _load_source(self, path: Path) -> None:
        try:
            self.source_info = analyze_file(path)
        except Exception as exc:
            QMessageBox.critical(self, "读取 A 工程失败", f"无法解析文件：\n{path}\n\n{exc}")
            return
        self.source_label.setText(f"A 工程文件：{path}")
        self.source_label.setToolTip(str(path))
        self.refresh_matches()

    def _load_template(self, path: Path) -> None:
        try:
            self.template_info = analyze_file(path)
        except Exception as exc:
            QMessageBox.critical(self, "读取 B 标准文件失败", f"无法解析文件：\n{path}\n\n{exc}")
            return
        self.template_label.setText(f"B 标准文件：{path}")
        self.template_label.setToolTip(str(path))
        self.refresh_matches()

    @staticmethod
    def _readonly_item(text: str, tooltip: str | None = None) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        if tooltip:
            item.setToolTip(tooltip)
        return item

    @staticmethod
    def _style_text(folder: FolderInfo) -> str:
        if folder.standard_style_ambiguous:
            return "多个最高占比 Style，需人工确认"
        if folder.standard_style_key == "<unstyled>" or not folder.standard_style_key:
            return "未找到 Style"
        key = folder.standard_style_key
        if key.startswith("inline:"):
            return f"内联 Style ({folder.standard_style_ratio * 100:.1f}%)"
        return f"{key} ({folder.standard_style_ratio * 100:.1f}%)"

    def _make_a_combo(self, row_index: int, template: FolderInfo, selected: FolderInfo | None) -> QComboBox:
        combo = QComboBox()
        combo.setMinimumWidth(380)
        combo.addItem("— 不同步此 B Folder —", None)
        for source in candidates_for(template, self.source_info.folders if self.source_info else []):
            combo.addItem(source.display_path, source)
        if selected is not None:
            for idx in range(combo.count()):
                if combo.itemData(idx) is selected:
                    combo.setCurrentIndex(idx)
                    break
        combo.currentIndexChanged.connect(
            lambda _index, r=row_index, cb=combo: self._on_source_changed(r, cb)
        )
        return combo

    def _on_source_changed(self, row_index: int, combo: QComboBox) -> None:
        if self._building_table or row_index >= len(self.rows):
            return
        row = self.rows[row_index]
        selected = combo.currentData()
        row.source = selected
        if selected is None:
            row.status = "UNMATCHED"
            geometry_a = "—"
            status = "— 未匹配"
        else:
            row.status = "MANUAL_MATCHED"
            geometry_a = selected.geometry_type
            status = "✓ 手动匹配"
        self.table.setItem(row_index, 4, self._readonly_item(geometry_a))
        self.table.setItem(row_index, 5, self._readonly_item(status))

    def refresh_matches(self) -> None:
        if self.source_info is None or self.template_info is None:
            self.table.setRowCount(0)
            self._combo_boxes.clear()
            return

        self.rows = build_match_rows(self.source_info.folders, self.template_info.folders)
        self.table.setRowCount(len(self.rows))
        self._combo_boxes = []
        self._building_table = True
        try:
            for i, row in enumerate(self.rows):
                template = row.template
                source = row.source

                self.table.setItem(i, 0, self._readonly_item(template.display_path, template.display_path))
                self.table.setItem(i, 1, self._readonly_item(template.geometry_type))
                self.table.setItem(i, 2, self._readonly_item(self._style_text(template), template.standard_style_xml))

                combo = self._make_a_combo(i, template, source)
                self.table.setCellWidget(i, 3, combo)
                self._combo_boxes.append(combo)

                if source is None:
                    self.table.setItem(i, 4, self._readonly_item("—"))
                    status = "⚠ 名称重复，需手动选择" if row.status == "AMBIGUOUS" else "— 未匹配"
                else:
                    self.table.setItem(i, 4, self._readonly_item(source.geometry_type))
                    status = "✓ 自动匹配"
                self.table.setItem(i, 5, self._readonly_item(status))
        finally:
            self._building_table = False

        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(0, max(300, self.table.columnWidth(0)))
        self.table.setColumnWidth(2, max(300, self.table.columnWidth(2)))
        self.table.setColumnWidth(3, max(400, self.table.columnWidth(3)))
        matched = sum(row.source is not None for row in self.rows)
        self.info.setText(
            f"A Folder：{len(self.source_info.folders)} | B Folder：{len(self.template_info.folders)} | "
            f"当前匹配：{matched} | B 顺序固定 | A 下拉仅显示同 Geometry"
        )

    def apply_sync(self) -> None:
        if self.source_info is None or self.template_info is None:
            QMessageBox.warning(self, "无法同步", "请先选择 A 工程文件和 B 标准文件。")
            return

        mappings: dict[tuple[str, ...], tuple[str, ...]] = {}
        blocked: list[str] = []
        for row in self.rows:
            if row.source is None:
                continue
            if row.template.standard_style_ambiguous or row.template.standard_style_key in {None, "<unstyled>"}:
                blocked.append(row.template.display_path)
                continue
            mappings[row.source.folder_path] = row.template.folder_path

        if not mappings:
            QMessageBox.warning(self, "无法同步", "没有可执行的 Folder 匹配关系。请检查 A 选择和 B Style。")
            return
        if blocked:
            QMessageBox.warning(
                self,
                "存在需人工确认的 B Style",
                "以下 B Folder 没有唯一标准 Style，因此不会同步：\n\n" + "\n".join(blocked),
            )

        suffix = self.source_info.file_path.suffix.lower()
        default_name = f"{self.source_info.file_path.stem}_StyleSynced{suffix}"
        output, _ = QFileDialog.getSaveFileName(
            self,
            "保存同步后的 KML/KMZ 文件",
            str(self.source_info.file_path.with_name(default_name)),
            self._file_filter(),
        )
        if not output:
            return
        output_path = Path(output)
        if output_path.suffix.lower() != suffix:
            output_path = output_path.with_suffix(suffix)

        try:
            result = sync_file(self.source_info.file_path, self.template_info.file_path, output_path, mappings)
        except Exception as exc:
            QMessageBox.critical(self, "同步失败", str(exc))
            return

        msg = (
            "同步完成\n\n"
            f"处理映射：{len(mappings)}\n"
            f"修改 Placemark：{result.placemarks_changed}\n"
            f"同步 Style：{result.styles_changed}\n"
            f"输出：{result.output_path}"
        )
        if result.warnings:
            msg += "\n\n警告：\n" + "\n".join(result.warnings)
        QMessageBox.information(self, "KML Style Sync", msg)


def run() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    app.exec()
