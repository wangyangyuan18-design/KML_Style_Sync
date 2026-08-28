from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .kml_parser import analyze_file
from .matcher import build_match_rows, candidates_for
from .models import FolderInfo, KMLFileInfo, MatchRow
from .style_sync import sync_file
from .template_store import (
    delete_template,
    list_templates,
    rename_template,
    save_template,
    template_path,
    template_root,
)


class AnalysisWorker(QObject):
    finished = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, kind: str, path: Path, include_styles: bool) -> None:
        super().__init__()
        self.kind = kind
        self.path = path
        self.include_styles = include_styles

    @Slot()
    def run(self) -> None:
        try:
            result = analyze_file(self.path, include_styles=self.include_styles)
            self.finished.emit(self.kind, result)
        except Exception as exc:
            self.failed.emit(self.kind, str(exc))


class TemplateManagerDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("管理 B 标准模板")
        self.resize(520, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("已收藏的 B 标准模板："))
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, 1)

        buttons = QHBoxLayout()
        self.rename_button = QPushButton("重命名")
        self.delete_button = QPushButton("删除")
        self.open_button = QPushButton("打开所在位置")
        buttons.addWidget(self.rename_button)
        buttons.addWidget(self.delete_button)
        buttons.addWidget(self.open_button)
        layout.addLayout(buttons)

        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_box.rejected.connect(self.reject)
        layout.addWidget(close_box)

        self.rename_button.clicked.connect(self._rename)
        self.delete_button.clicked.connect(self._delete)
        self.open_button.clicked.connect(self._open_location)
        self._refresh()

    def _refresh(self) -> None:
        self.list_widget.clear()
        for item in list_templates():
            self.list_widget.addItem(item["name"])
        enabled = self.list_widget.count() > 0
        self.rename_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)
        self.open_button.setEnabled(enabled)

    def _selected_name(self) -> str | None:
        item = self.list_widget.currentItem()
        return item.text() if item else None

    def _rename(self) -> None:
        old = self._selected_name()
        if not old:
            return
        new, ok = QInputDialog.getText(self, "重命名模板", "新模板名称：", text=old)
        if not ok or not new.strip() or new.strip() == old:
            return
        try:
            rename_template(old, new)
        except Exception as exc:
            QMessageBox.warning(self, "重命名失败", str(exc))
            return
        self._refresh()

    def _delete(self) -> None:
        name = self._selected_name()
        if not name:
            return
        answer = QMessageBox.question(
            self,
            "删除模板",
            f"确定删除模板“{name}”？\n此操作不会影响原始 B 文件。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_template(name)
        except Exception as exc:
            QMessageBox.warning(self, "删除失败", str(exc))
            return
        self._refresh()

    def _open_location(self) -> None:
        name = self._selected_name()
        path = template_path(name) if name else None
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent if path else template_root())))


class MainWindow(QMainWindow):
    """A-centric KML/KMZ style synchronization UI."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("KML Style Sync - Standalone")
        self.resize(1520, 900)
        self.source_info: KMLFileInfo | None = None
        self.template_info: KMLFileInfo | None = None
        self.current_template_name: str | None = None
        self.rows: list[MatchRow] = []
        self._analysis_threads: dict[str, QThread] = {}
        self._analysis_workers: dict[str, AnalysisWorker] = {}
        self._building_table = False
        self._build_ui()
        self._refresh_template_choices()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        top_a = QHBoxLayout()
        self.source_label = QLabel("A 工程文件：未选择")
        self.source_button = QPushButton("选择 A 工程文件")
        self.source_button.clicked.connect(self.choose_source)
        top_a.addWidget(self.source_label, 1)
        top_a.addWidget(self.source_button)
        layout.addLayout(top_a)

        top_b = QHBoxLayout()
        top_b.addWidget(QLabel("B 标准模板："))
        self.template_combo = QComboBox()
        self.template_combo.setMinimumWidth(360)
        self.template_combo.currentIndexChanged.connect(self._on_template_choice)
        self.template_file_button = QPushButton("选择 B 文件")
        self.template_file_button.clicked.connect(self.choose_template_file)
        self.save_template_button = QPushButton("收藏当前 B")
        self.save_template_button.clicked.connect(self.save_current_template)
        self.manage_template_button = QPushButton("管理模板")
        self.manage_template_button.clicked.connect(self.manage_templates)
        top_b.addWidget(self.template_combo, 1)
        top_b.addWidget(self.template_file_button)
        top_b.addWidget(self.save_template_button)
        top_b.addWidget(self.manage_template_button)
        layout.addLayout(top_b)
        self.template_label = QLabel("B：未加载")
        layout.addWidget(self.template_label)

        hint = QLabel(
            "A 是待同步任务清单：所有 A 有效图层固定显示；B 是可复用的只读标准 Style 库。"
            "自动匹配仅使用“Folder 名称 + Geometry”；手动选择 B 时只显示相同 Geometry。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.library_toggle = QToolButton()
        self.library_toggle.setText("▶ B 标准 Style 库（只读）")
        self.library_toggle.setCheckable(True)
        self.library_toggle.setChecked(False)
        self.library_toggle.clicked.connect(self._toggle_library)
        layout.addWidget(self.library_toggle)

        self.library_panel = QWidget()
        library_layout = QVBoxLayout(self.library_panel)
        library_layout.setContentsMargins(0, 0, 0, 0)
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
        self.library_table.setMaximumHeight(250)
        library_layout.addWidget(self.library_table)
        self.library_panel.setVisible(False)
        layout.addWidget(self.library_panel)

        task_header = QHBoxLayout()
        task_header.addWidget(QLabel("A 工程 Style 同步任务"))
        task_header.addStretch(1)
        task_header.addWidget(QLabel("状态筛选："))
        self.status_filter = QComboBox()
        self.status_filter.addItems(["全部", "未匹配", "自动匹配", "手动匹配"])
        self.status_filter.currentIndexChanged.connect(self._apply_status_filter)
        task_header.addWidget(self.status_filter)
        layout.addLayout(task_header)

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

        bottom = QHBoxLayout()
        self.info = QLabel("请先选择 A 工程文件和 B 标准模板")
        self.loading_label = QLabel("")
        apply_btn = QPushButton("执行 Style 同步")
        apply_btn.clicked.connect(self.apply_sync)
        bottom.addWidget(self.info, 1)
        bottom.addWidget(self.loading_label)
        bottom.addWidget(apply_btn)
        layout.addLayout(bottom)

    def _toggle_library(self, checked: bool) -> None:
        self.library_panel.setVisible(checked)
        self.library_toggle.setText("▼ B 标准 Style 库（只读）" if checked else "▶ B 标准 Style 库（只读）")

    @staticmethod
    def _file_filter() -> str:
        return "KML/KMZ 文件 (*.kml *.kmz);;KML 文件 (*.kml);;KMZ 文件 (*.kmz)"

    def choose_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 A 待同步工程文件", "", self._file_filter())
        if path:
            self._start_analysis("A", Path(path), include_styles=False)

    def choose_template_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 B 标准文件", "", self._file_filter())
        if path:
            self._start_analysis("B", Path(path), include_styles=True)

    def _start_analysis(self, kind: str, path: Path, include_styles: bool) -> None:
        old_thread = self._analysis_threads.get(kind)
        if old_thread and old_thread.isRunning():
            return
        button = self.source_button if kind == "A" else self.template_file_button
        button.setEnabled(False)
        self.loading_label.setText(f"正在解析 {kind}：{path.name} …")

        thread = QThread(self)
        worker = AnalysisWorker(kind, path, include_styles)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._analysis_finished)
        worker.failed.connect(self._analysis_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda k=kind, t=thread: self._analysis_thread_finished(k, t))
        self._analysis_threads[kind] = thread
        self._analysis_workers[kind] = worker
        thread.start()

    def _analysis_thread_finished(self, kind: str, thread: QThread) -> None:
        thread.deleteLater()
        self._analysis_threads.pop(kind, None)
        self._analysis_workers.pop(kind, None)
        self.source_button.setEnabled(True)
        self.template_file_button.setEnabled(True)
        if not self._analysis_threads:
            self.loading_label.setText("")

    @Slot(str, object)
    def _analysis_finished(self, kind: str, info: KMLFileInfo) -> None:
        if kind == "A":
            self.source_info = info
            self.source_label.setText(f"A 工程文件：{info.file_path}")
            self.source_label.setToolTip(str(info.file_path))
        else:
            self.template_info = info
            self.current_template_name = None
            self.template_label.setText(f"B：{info.file_path}")
            self.template_label.setToolTip(str(info.file_path))
            self._set_template_combo_to_manual_file()
        self._rebuild_matches(preserve_current=False)

    @Slot(str, str)
    def _analysis_failed(self, kind: str, error: str) -> None:
        title = "读取 A 工程失败" if kind == "A" else "读取 B 标准文件失败"
        QMessageBox.critical(self, title, error)

    def _set_template_combo_to_manual_file(self) -> None:
        self.template_combo.blockSignals(True)
        self.template_combo.setCurrentIndex(0)
        self.template_combo.blockSignals(False)

    def _refresh_template_choices(self) -> None:
        names = [item["name"] for item in list_templates()]
        self.template_combo.blockSignals(True)
        current = self.current_template_name
        self.template_combo.clear()
        self.template_combo.addItem("选择收藏模板…", None)
        for name in names:
            self.template_combo.addItem(name, name)
        if current and current in names:
            self.template_combo.setCurrentIndex(names.index(current) + 1)
        else:
            self.template_combo.setCurrentIndex(0)
        self.template_combo.blockSignals(False)

    def _on_template_choice(self, index: int) -> None:
        if index <= 0:
            return
        name = self.template_combo.currentData()
        if not name:
            return
        path = template_path(str(name))
        if path is None:
            QMessageBox.warning(self, "模板不存在", f"找不到模板：{name}")
            self._refresh_template_choices()
            return
        self.current_template_name = str(name)
        self._start_analysis("B", path, include_styles=True)

    def save_current_template(self) -> None:
        if self.template_info is None:
            QMessageBox.warning(self, "无法收藏", "请先选择并解析一个 B 标准文件。")
            return
        if self.current_template_name is not None:
            QMessageBox.information(self, "模板已在库中", f"当前正在使用收藏模板：{self.current_template_name}")
            return
        name, ok = QInputDialog.getText(self, "收藏 B 标准模板", "模板名称：")
        if not ok or not name.strip():
            return
        try:
            saved_path = save_template(self.template_info.file_path, name.strip())
        except Exception as exc:
            QMessageBox.warning(self, "收藏失败", str(exc))
            return
        self._refresh_template_choices()
        idx = self.template_combo.findData(name.strip())
        if idx >= 0:
            self.template_combo.setCurrentIndex(idx)
        QMessageBox.information(self, "收藏成功", f"模板已保存。\n\n{saved_path}")

    def manage_templates(self) -> None:
        dialog = TemplateManagerDialog(self)
        dialog.exec()
        self._refresh_template_choices()
        if self.current_template_name and template_path(self.current_template_name) is None:
            self.current_template_name = None
            self.template_info = None
            self.template_label.setText("B：未加载")
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
        if template is None:
            status = "— 未匹配"
        elif row.status == "AUTO_MATCHED":
            status = "✓ 自动匹配"
        else:
            status = "✓ 手动匹配"
        self.table.setItem(row_index, 5, self._readonly_item(status))

    def _update_summary(self) -> None:
        if self.source_info is None or self.template_info is None:
            self.info.setText("请先选择 A 工程文件和 B 标准模板")
            return
        a_total = len(self.source_info.folders)
        b_total = len(self.template_info.folders)
        auto_count = sum(row.template is not None and row.status == "AUTO_MATCHED" for row in self.rows)
        manual_count = sum(row.template is not None and row.status == "MANUAL_MATCHED" for row in self.rows)
        unmatched_count = sum(row.template is None for row in self.rows)
        self.info.setText(
            f"A 有效图层：{a_total} | B 有效图层：{b_total} | "
            f"自动匹配：{auto_count} | 手动匹配：{manual_count} | A 未匹配：{unmatched_count}"
        )

    def _apply_status_filter(self) -> None:
        selected = self.status_filter.currentIndex()
        for row_index, row in enumerate(self.rows):
            if selected == 0:
                visible = True
            elif selected == 1:
                visible = row.template is None
            elif selected == 2:
                visible = row.status == "AUTO_MATCHED"
            else:
                visible = row.status == "MANUAL_MATCHED"
            self.table.setRowHidden(row_index, not visible)

    def _rebuild_matches(self, preserve_current: bool) -> None:
        if self.source_info is None or self.template_info is None:
            self.table.setRowCount(0)
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
        self._building_table = True
        try:
            for i, row in enumerate(self.rows):
                source = row.source
                self.table.setItem(i, 0, self._readonly_item(source.display_path, source.display_path))
                self.table.setItem(i, 1, self._readonly_item(source.geometry_type))
                combo = self._make_b_combo(i, source, row.template)
                self.table.setCellWidget(i, 2, combo)
                self._update_row_cells(i, row)
        finally:
            self._building_table = False

        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(0, max(380, self.table.columnWidth(0)))
        self.table.setColumnWidth(2, max(460, self.table.columnWidth(2)))
        self._update_summary()
        self._apply_status_filter()

    def apply_sync(self) -> None:
        if self.source_info is None or self.template_info is None:
            QMessageBox.warning(self, "无法同步", "请先选择 A 工程文件和 B 标准模板。")
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
