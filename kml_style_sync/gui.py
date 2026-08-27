from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QPushButton,
)

from .kml_parser import scan_project
from .matcher import build_match_rows, candidates_for
from .models import MatchRow
from .style_sync import sync_project


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("KML Style Sync - Standalone")
        self.resize(1200, 720)
        self.source_root: Path | None = None
        self.template_root: Path | None = None
        self.source_layers = []
        self.template_layers = []
        self.rows: list[MatchRow] = []
        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        top = QHBoxLayout()
        self.source_label = QLabel("A 待同步工程：未选择")
        source_btn = QPushButton("选择 A 工程")
        source_btn.clicked.connect(self.choose_source)
        self.template_label = QLabel("B 标准模板：未选择")
        template_btn = QPushButton("选择 B 模板")
        template_btn.clicked.connect(self.choose_template)
        top.addWidget(self.source_label, 1)
        top.addWidget(source_btn)
        top.addWidget(self.template_label, 1)
        top.addWidget(template_btn)
        layout.addLayout(top)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["A 待同步图层", "Geometry", "B 标准图层", "标准 Style", "匹配状态"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.info = QLabel("请选择 A 和 B 工程")
        refresh_btn = QPushButton("重新匹配")
        refresh_btn.clicked.connect(self.refresh_matches)
        apply_btn = QPushButton("执行同步")
        apply_btn.clicked.connect(self.apply_sync)
        bottom.addWidget(self.info, 1)
        bottom.addWidget(refresh_btn)
        bottom.addWidget(apply_btn)
        layout.addLayout(bottom)

    def choose_source(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择 A 待同步工程")
        if path:
            self.source_root = Path(path)
            self.source_layers = scan_project(self.source_root)
            self.source_label.setText(f"A 待同步工程：{self.source_root}")
            self.refresh_matches()

    def choose_template(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择 B 标准模板工程")
        if path:
            self.template_root = Path(path)
            self.template_layers = scan_project(self.template_root)
            self.template_label.setText(f"B 标准模板：{self.template_root}")
            self.refresh_matches()

    def refresh_matches(self) -> None:
        if not self.source_layers or not self.template_layers:
            return
        self.rows = build_match_rows(self.source_layers, self.template_layers)
        self.table.setRowCount(len(self.rows))
        for i, row in enumerate(self.rows):
            combo = QComboBox()
            combo.addItem("— 未匹配 —", None)
            for layer in candidates_for(row.template, self.source_layers):
                combo.addItem(f"{layer.name}  [{layer.relative_path}]", layer)
            if row.source is not None:
                idx = next((j for j in range(combo.count()) if combo.itemData(j) is row.source), 0)
                combo.setCurrentIndex(idx)
            combo.currentIndexChanged.connect(lambda _, r=i, c=combo: self._combo_changed(r, c))
            self.table.setCellWidget(i, 0, combo)
            self.table.setItem(i, 1, QTableWidgetItem(row.template.geometry_type))
            self.table.setItem(i, 2, QTableWidgetItem(row.template.name))
            ratio = row.template.standard_style_ratio * 100
            self.table.setItem(i, 3, QTableWidgetItem(f"{ratio:.1f}%" if row.template.standard_style_key else "无 Style"))
            self.table.setItem(i, 4, QTableWidgetItem(row.status))
        self.table.resizeColumnsToContents()
        self.info.setText(f"B 图层：{len(self.template_layers)} | A 图层：{len(self.source_layers)} | 已匹配：{sum(r.source is not None for r in self.rows)}")

    def _combo_changed(self, row_index: int, combo: QComboBox) -> None:
        if row_index >= len(self.rows):
            return
        source = combo.currentData()
        self.rows[row_index].source = source
        self.rows[row_index].status = "MATCHED" if source is not None else "UNMATCHED"
        self.table.setItem(row_index, 4, QTableWidgetItem(self.rows[row_index].status))

    def apply_sync(self) -> None:
        if not self.source_root or not self.template_root:
            QMessageBox.warning(self, "无法同步", "请先选择 A 待同步工程和 B 标准模板工程。")
            return
        mappings: dict[Path, Path] = {}
        for row in self.rows:
            if row.source is not None:
                mappings[row.source.relative_path] = row.template.relative_path
        if not mappings:
            QMessageBox.warning(self, "无法同步", "没有已匹配的图层。")
            return
        output = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if not output:
            return
        output_root = Path(output) / f"{self.source_root.name}_StyleSynced"
        try:
            result = sync_project(self.source_root, self.template_root, output_root, mappings)
        except Exception as exc:
            QMessageBox.critical(self, "同步失败", str(exc))
            return
        msg = f"同步完成\n\n修改 Placemark：{result.placemarks_changed}\n同步 Style：{result.styles_changed}\n输出：{result.output_path}"
        if result.warnings:
            msg += "\n\n警告：\n" + "\n".join(result.warnings)
        QMessageBox.information(self, "KML Style Sync", msg)


def run() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    app.exec()
