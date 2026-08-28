from __future__ import annotations

from collections import defaultdict
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
    """A-centric KML/KMZ style synchronization UI.

    A is the task list: every effective A layer is always shown.
    B is an independent, read-only standard-style library.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("KML Style Sync - Standalone")
        self.resize(1520, 920)
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
            "A 是待同步任务清单：所有 A 有效图层固定显示；B 是只读标准 Style 库。"
            "自动匹配仅使用“Folder 名称 + Geometry”精确匹配；人工下拉只能选择相同 Geometry 的 B 有效图层。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        library_title = QLabel("B 标准 Style 库（只读）")
        library_title.setStyleSheet("font-weight: bold;")
        layout.addWidget(library_title)

        self.library_table = QTableWidget(0, 4)
        self.library_table.setHorizontalHeaderLabels([
            "B 标准 Folder",
            "Geometry",
            "标准 Style",
            "Style 使用率",
        ])
        self.library_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.library_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.library_table.setAlternatingRowColors(True)
        self.library_table.setWordWrap(False)
        self.library_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.library_table.setMaximumHeight(260)
        layout.addWidget(self.library_table)

        task_title = QLabel("A 工程 Style 同步任务")
        task_title.setStyleSheet("font-weight: bold;")
        layout.addWidget(task_title)

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
        self.table.setWordWrap(False)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        layout.addWidget(self.table, 1)

        self.unmatched_label = QLabel("A 未匹配图层：—")
        self.unmatched_label.setWordWrap(True)
        self.unmatched_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.unmatched_label)

        bottom = QHBoxLayout()
        self.info = QLabel("请先选择 A 工程文件和 B 标准文件")
        refresh_btn = QPushButton("仅匹配未匹配项")
        refresh_btn.clicked.connect(self.refresh_unmatched)
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
        self._rebuild_matches(preserve_current=False)

    def _load_template(self, path: Path) -> None:
        try:
            self.template_info = analyze_file(path)
        except Exception as exc:
            QMessageBox.critical(self, "读取 B 标准文件失败", f"无法解析文件：\n{path}\n\n{exc}")
            return
        self.template_label.setText(f"B 标准文件：{path}")
        self.template_label.setToolTip(str(path))
        self._rebuild_matches(preserve_current=False)

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

    def _populate_library(self) -> None:
        self.library_table.setRowCount(0)
        if self.template_info is None:
            return
        self.library_table.setRowCount(len(self.template_info.folders))
        for i, folder in enumerate(self.template_info.folders):
            self.library_table.setItem(i, 0, self._readonly_item(folder.display_path, folder.display_path))
            self.library_table.setItem(i, 1, self._readonly_item(folder.geometry_type))
            self.library_table.setItem(i, 2, self._readonly_item(self._style_text(folder), folder.standard_style_xml))
            ratio = f"{folder.standard_style_ratio * 100:.1f}%" if folder.standard_style_key not in {None, "<unstyled>"} else "—"
            self.library_table.setItem(i, 3, self._readonly_item(ratio))
        self.library_table.resizeColumnsToContents()
        self.library_table.setColumnWidth(0, max(360, self.library_table.columnWidth(0)))
        self.library_table.setColumnWidth(2, max(360, self.library_table.columnWidth(2)))

    def _make_b_combo(self, row_index: int, source: FolderInfo, selected: FolderInfo | None) -> QComboBox:
        combo = QComboBox()
        combo.setMinimumWidth(420)
        combo.addItem("— 未匹配：选择 B 标准 Folder —", None)
        for template in candidates_for(source, self.template_info.folders if self.template_info else []):
            combo.addItem(template.display_path, template)
        if selected is not None:
            for idx in range(combo.count()):
                if combo.itemData(idx) is selected:
                    combo.setCurrentIndex(idx)
                    break
        combo.currentIndexChanged.connect(
            lambda _index, r=row_index, cb=combo: self._on_template_changed(r, cb)
        )
        return combo

    def _on_template_changed(self, row_index: int, combo: QComboBox) -> None:
        if self._building_table or row_index >= len(self.rows):
            return
        row = self.rows[row_index]
        row.template = combo.currentData()
        row.status = "UNMATCHED" if row.template is None else "MANUAL_MATCHED"
        self._update_row_cells(row_index, row)
        self._update_summary()

    def _update_row_cells(self, row_index: int, row: MatchRow) -> None:
        template = row.template
        self.table.setItem(row_index, 3, self._readonly_item(template.geometry_type if template else "—"))
        self.table.setItem(row_index, 4, self._readonly_item(self._style_text(template) if template else "—"))
        if row.template is None:
            if row.status == "AMBIGUOUS":
                status = "⚠ 名称重复，需手动选择"
            else:
                status = "— 未匹配"
        elif row.status == "AUTO_MATCHED":
            status = "✓ 自动匹配"
        else:
            status = "✓ 手动匹配"
        self.table.setItem(row_index, 5, self._readonly_item(status))

    def _refresh_duplicate_statuses(self) -> None:
        """Warn when one A Folder is assigned to multiple B rows.

        B standards may be reused by multiple A layers; the dangerous case is
        one A layer being assigned to multiple B standards, which cannot happen
        in this A-centric one-row-per-A model. This method is kept as a safety
        hook for future model extensions.
        """
        # One row represents exactly one A effective layer, so duplicate A
        # assignment across rows is structurally impossible in the A-centric UI.
        return

    def _update_summary(self) -> None:
        if self.source_info is None or self.template_info is None:
            self.info.setText("请先选择 A 工程文件和 B 标准文件")
            self.unmatched_label.setText("A 未匹配图层：—")
            return

        a_total = len(self.source_info.folders)
        b_total = len(self.template_info.folders)
        auto_count = sum(row.template is not None and row.status == "AUTO_MATCHED" for row in self.rows)
        manual_count = sum(row.template is not None and row.status == "MANUAL_MATCHED" for row in self.rows)
        unmatched_rows = [row.source.display_path for row in self.rows if row.template is None]
        unmatched_count = len(unmatched_rows)

        self.info.setText(
            f"A 有效图层：{a_total} | B 有效图层：{b_total} | "
            f"自动匹配：{auto_count} | 手动匹配：{manual_count} | A 未匹配：{unmatched_count}"
        )
        if unmatched_rows:
            self.unmatched_label.setText("⚠ A 未匹配图层（{}）：{}".format(unmatched_count, "、".join(unmatched_rows)))
        else:
            self.unmatched_label.setText("✓ A 未匹配图层：0（全部 A 有效图层均已有匹配）")

    def _rebuild_matches(self, preserve_current: bool) -> None:
        if self.source_info is None or self.template_info is None:
            self.table.setRowCount(0)
            self._combo_boxes.clear()
            self._populate_library()
            self._update_summary()
            return

        previous_by_a = {
            row.source.folder_path: (row.template, row.status)
            for row in self.rows
        } if preserve_current else {}

        self.rows = build_match_rows(self.source_info.folders, self.template_info.folders)
        if preserve_current:
            for row in self.rows:
                previous = previous_by_a.get(row.source.folder_path)
                if previous is not None:
                    row.template, row.status = previous

        self._populate_library()
        self.table.setRowCount(len(self.rows))
        self._combo_boxes = []
        self._building_table = True
        try:
            for i, row in enumerate(self.rows):
                source = row.source
                self.table.setItem(i, 0, self._readonly_item(source.display_path, source.display_path))
                self.table.setItem(i, 1, self._readonly_item(source.geometry_type))
                combo = self._make_b_combo(i, source, row.template)
                self.table.setCellWidget(i, 2, combo)
                self._combo_boxes.append(combo)
                self._update_row_cells(i, row)
        finally:
            self._building_table = False

        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(0, max(360, self.table.columnWidth(0)))
        self.table.setColumnWidth(2, max(450, self.table.columnWidth(2)))
        self._update_summary()

    def refresh_unmatched(self) -> None:
        if self.source_info is None or self.template_info is None:
            self._update_summary()
            return
        self._rebuild_matches(preserve_current=True)

    def apply_sync(self) -> None:
        if self.source_info is None or self.template_info is None:
            QMessageBox.warning(self, "无法同步", "请先选择 A 工程文件和 B 标准文件。")
            return

        unmatched = [row.source.display_path for row in self.rows if row.template is None]
        if unmatched:
            QMessageBox.warning(
                self,
                "A 仍有未匹配图层",
                "还有以下 A 有效图层未匹配 B 标准 Style，请先完成匹配：\n\n" + "\n".join(unmatched),
            )
            return

        blocked = [
            row.template.display_path
            for row in self.rows
            if row.template is not None
            and (row.template.standard_style_ambiguous or row.template.standard_style_key in {None, "<unstyled>"})
        ]
        if blocked:
            QMessageBox.warning(
                self,
                "存在无有效标准 Style 的 B 图层",
                "以下 B 标准 Folder 没有唯一可用 Style，无法安全同步：\n\n" + "\n".join(blocked),
            )
            return

        mappings: dict[tuple[str, ...], tuple[str, ...]] = {
            row.source.folder_path: row.template.folder_path
            for row in self.rows
            if row.template is not None
        }
        if not mappings:
            QMessageBox.warning(self, "无法同步", "没有可执行的 A→B 映射。")
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
            result = sync_file(self.source_info.file_path, self.template_info.file_path, output_path, mappings)
        except Exception as exc:
            QMessageBox.critical(self, "同步失败", str(exc))
            return

        msg = (
            "同步完成\n\n"
            f"A 有效图层：{len(self.source_info.folders)}\n"
            f"自动匹配：{sum(row.status == 'AUTO_MATCHED' for row in self.rows)}\n"
            f"手动匹配：{sum(row.status == 'MANUAL_MATCHED' for row in self.rows)}\n"
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
