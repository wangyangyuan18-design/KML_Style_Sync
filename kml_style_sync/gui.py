from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .kml_parser import analyze_file
from .matcher import build_match_rows
from .models import FolderInfo, KMLFileInfo, MatchRow
from .style_sync import sync_file


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("KML Style Sync - Standalone")
        self.resize(1450, 800)
        self.source_info: KMLFileInfo | None = None
        self.template_info: KMLFileInfo | None = None
        self.rows: list[MatchRow] = []
        self._combo_boxes: list[QComboBox] = []
        self._building_table = False
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
            "运行逻辑：先完整解析 B 文件的所有 Folder、Geometry 和 Style；"
            "再按 Folder 名称预匹配 A。A 的每个 Folder 均可手动选择 B，候选项只显示相同 Geometry。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "A 工程 Folder",
            "Geometry A",
            "B 标准 Folder（可选择）",
            "Geometry B",
            "标准 Style",
            "匹配状态",
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.info = QLabel("请先选择 A 工程文件和 B 标准文件")
        refresh_btn = QPushButton("按名称重新预匹配")
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
        path, _ = QFileDialog.getOpenFileName(self, "选择 B 标准模板文件", "", self._file_filter())
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
    def _folder_key(folder: FolderInfo) -> str:
        return folder.display_path

    def _matching_templates(self, source: FolderInfo) -> list[FolderInfo]:
        if self.template_info is None:
            return []
        # Manual choices are restricted to B Folders having exactly the same
        # parsed geometry type. MIXED therefore only matches MIXED.
        return [
            folder for folder in self.template_info.folders
            if folder.geometry_type == source.geometry_type
        ]

    def _best_default_template(self, source: FolderInfo) -> FolderInfo | None:
        candidates = self._matching_templates(source)
        if not candidates:
            return None
        source_name = source.name.strip().casefold()
        source_path = source.display_path.strip().casefold()
        exact_path = [f for f in candidates if f.display_path.strip().casefold() == source_path]
        if len(exact_path) == 1:
            return exact_path[0]
        exact_name = [f for f in candidates if f.name.strip().casefold() == source_name]
        return exact_name[0] if len(exact_name) == 1 else None

    def _set_combo_items(self, combo: QComboBox, source: FolderInfo, selected: FolderInfo | None) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("— 不同步此 Folder —", None)
        for folder in self._matching_templates(source):
            combo.addItem(folder.display_path, folder)
        if selected is not None:
            index = combo.findText(selected.display_path, Qt.MatchFlag.MatchExactly)
            if index >= 0:
                combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _on_template_changed(self, row_index: int, combo: QComboBox) -> None:
        if self._building_table or row_index >= len(self.rows):
            return
        selected = combo.currentData()
        row = self.rows[row_index]
        row.template = selected
        row.status = "MATCHED" if selected is not None else "UNMATCHED"
        self._update_row_metadata(row_index, row)

    def _update_row_metadata(self, row_index: int, row: MatchRow) -> None:
        template = row.template
        self.table.setItem(row_index, 3, self._readonly_item(template.geometry_type if template else "—"))
        if template and template.standard_style_key and template.standard_style_key != "<unstyled>":
            style_text = f"{template.standard_style_ratio * 100:.1f}% 使用"
        else:
            style_text = "无可用 Style"
        self.table.setItem(row_index, 4, self._readonly_item(style_text))
        status_text = "✓ 已匹配" if template else "— 未匹配"
        self.table.setItem(row_index, 5, self._readonly_item(status_text))

    def refresh_matches(self) -> None:
        if self.source_info is None or self.template_info is None:
            self.table.setRowCount(0)
            self._combo_boxes.clear()
            return

        # This is the only automatic matching stage: B is parsed first, then
        # A is matched by Folder path/name + identical Geometry. Every A row
        # remains manually selectable afterwards.
        self.rows = build_match_rows(self.source_info.folders, self.template_info.folders)
        self.table.setRowCount(len(self.rows))
        self._combo_boxes = []
        self._building_table = True
        try:
            for i, row in enumerate(self.rows):
                source = row.source
                default_template = self._best_default_template(source)
                row.template = default_template
                row.status = "MATCHED" if default_template else "UNMATCHED"

                self.table.setItem(i, 0, self._readonly_item(source.display_path, source.display_path))
                self.table.setItem(i, 1, self._readonly_item(source.geometry_type))

                combo = QComboBox()
                combo.setMinimumWidth(300)
                self._set_combo_items(combo, source, default_template)
                combo.currentIndexChanged.connect(
                    lambda _index, row_index=i, cb=combo: self._on_template_changed(row_index, cb)
                )
                self.table.setCellWidget(i, 2, combo)
                self._combo_boxes.append(combo)
                self._update_row_metadata(i, row)
        finally:
            self._building_table = False

        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(0, max(280, self.table.columnWidth(0)))
        self.table.setColumnWidth(2, max(320, self.table.columnWidth(2)))
        matched = sum(r.template is not None for r in self.rows)
        self.info.setText(
            f"A Folder：{len(self.source_info.folders)} | "
            f"B Folder：{len(self.template_info.folders)} | 当前匹配：{matched} | "
            "下拉框候选仅允许选择相同 Geometry 的 B Folder"
        )

    def apply_sync(self) -> None:
        if self.source_info is None or self.template_info is None:
            QMessageBox.warning(self, "无法同步", "请先选择 A 工程文件和 B 标准文件。")
            return

        mappings: dict[tuple[str, ...], tuple[str, ...]] = {
            row.source.folder_path: row.template.folder_path
            for row in self.rows
            if row.template is not None and row.status == "MATCHED"
        }
        if not mappings:
            QMessageBox.warning(self, "无法同步", "没有可用的 Folder 匹配关系。")
            return

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
            result = sync_file(
                self.source_info.file_path,
                self.template_info.file_path,
                output_path,
                mappings,
            )
        except Exception as exc:
            QMessageBox.critical(self, "同步失败", str(exc))
            return

        msg = (
            "同步完成\n\n"
            f"处理 Folder：{len(mappings)}\n"
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
