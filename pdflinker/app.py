from __future__ import annotations

import copy
import os
from pathlib import Path
import sys
import tempfile
import threading
import uuid

import pymupdf as fitz
from PySide6.QtCore import Qt, QRectF, Signal, QTimer, QThread, QUrl, QSettings, QEvent
from PySide6.QtGui import QColor, QCursor, QIcon, QImage, QPainter, QPen, QPixmap, QKeySequence, QShortcut, QPalette, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QPlainTextEdit,
    QGraphicsScene, QGraphicsView, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressDialog, QPushButton,
    QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    QFrame,
    QSizePolicy,
)

from .core import Field, Template, assigned_fields, field_value, format_field_value, output_name, read_sheet, sheet_names
from .project import read_project, save_project as write_project
from .jobs import jobs_directory, list_jobs, result_message


class FieldCard(QFrame):
    link_changed = Signal(str, object)
    remove_requested = Signal(str)
    font_changed = Signal(str, int)
    manual_changed = Signal(str, bool, str, bool)

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("fieldCard")
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation, True)
        self.field_key = None
        self.column_state = None
        self.row_selected = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        self.title = QLabel()
        self.title.setObjectName("cardTitle")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.context_note = QLabel()
        self.context_note.setObjectName('muted')
        self.context_note.setWordWrap(True)
        layout.addWidget(self.context_note)
        row = QHBoxLayout()
        self.message = QLabel()
        self.message.setWordWrap(True)
        row.addWidget(self.message, 1)
        self.unlink = QPushButton("×")
        self.unlink.setObjectName("unlink")
        self.unlink.setFixedSize(28, 28)
        self.unlink.setToolTip("Remove this field's link")
        self.unlink.clicked.connect(lambda: self.link_changed.emit(self.field_key, None))
        row.addWidget(self.unlink, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(row)
        self.columns = QComboBox()
        self.columns.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.columns.setMinimumContentsLength(12)
        self.columns.currentIndexChanged.connect(lambda: self.link_changed.emit(self.field_key, self.columns.currentData()))
        layout.addWidget(self.columns)
        self.value = QLabel()
        self.value.setObjectName("muted")
        self.value.setWordWrap(True)
        layout.addWidget(self.value)
        self.manual_enabled = QCheckBox("Use a manual value")
        layout.addWidget(self.manual_enabled)
        self.manual_input = QPlainTextEdit()
        self.manual_input.setPlaceholderText("Enter the value for this PDF field")
        self.manual_input.setFixedHeight(64)
        layout.addWidget(self.manual_input)
        self.persist_manual = QCheckBox("Persist across rows and jobs")
        layout.addWidget(self.persist_manual)
        self.manual_hint = QLabel()
        self.manual_hint.setWordWrap(True)
        self.manual_hint.setObjectName("muted")
        layout.addWidget(self.manual_hint)
        self.manual_enabled.toggled.connect(self.manual_edited)
        self.persist_manual.toggled.connect(self.manual_edited)
        self.manual_input.textChanged.connect(self.manual_edited)
        self.manual_options = QWidget()
        options = QHBoxLayout(self.manual_options)
        options.setContentsMargins(0, 0, 0, 0)
        options.addWidget(QLabel("Text size"))
        self.font = QSpinBox()
        self.font.setRange(1, 100)
        self.font.setSuffix(" pt")
        self.font.valueChanged.connect(lambda size: self.font_changed.emit(self.field_key, size))
        options.addWidget(self.font)
        self.remove = QPushButton("Remove field")
        self.remove.clicked.connect(lambda: self.remove_requested.emit(self.field_key))
        options.addWidget(self.remove)
        layout.addWidget(self.manual_options)
        self.hide()

    def populate(self, field, headers, column, record, manual_value=None, persistent=False, row_selected=True, uncertainty_threshold=.7):
        self.field_key = field.key
        self.row_selected = row_selected
        self.title.setText(field.name if field.match_basis.startswith('field_id') else field.label or field.name)
        self.title.setToolTip('\n'.join(p for p in (field.name,field.section,field.question,field.nearby_label) if p))
        context='\n'.join(p for p in (f'Section: {field.section}' if field.section else '',
                                     f'Question: {field.question}' if field.question else '') if p)
        self.context_note.setText(context)
        self.context_note.setVisible(bool(context))
        self.message.setText(f"Linked to: {column}" if column is not None else
                             "Field not linked. Use Exact link, Suggest links or choose a column here.")
        if column and field.transform_source == column:
            if field.companion_columns:
                self.message.setText("Linked to: " + " + ".join((column, *field.companion_columns)))
            if field.source_part:
                descriptions = {"line1": "First address line", "line2": "Additional address lines",
                                "city": "Town/city when identifiable", "postcode": "Postcode"}
                self.message.setText(self.message.text() + "\nUses: " + descriptions[field.source_part])
        if column and field.match_score is not None:
            uncertain=' — Uncertain' if field.match_score < uncertainty_threshold else ''
            self.message.setText(self.message.text()+f'\nModel score: {field.match_score*100:.1f}/100{uncertain}')
        if column and field.match_note:
            self.message.setText(self.message.text()+'\n'+field.match_note)
        active_manual = manual_value is not None
        if active_manual:
            self.message.setText("Manual value — all rows and jobs" if persistent else "Manual value — this row only")
        self.unlink.setVisible(column is not None and not active_manual)
        state = (field.key, tuple(headers), column)
        if state != self.column_state:
            self.column_state = state
            self.columns.blockSignals(True)
            self.columns.clear()
            self.columns.addItem("Choose spreadsheet column…", None)
            for header in headers:
                self.columns.addItem(header, header)
            self.columns.setCurrentIndex(max(0, self.columns.findData(column)))
            self.columns.blockSignals(False)
        self.columns.setEnabled(bool(headers) and not active_manual)
        try:
            preview_value = format_field_value(field, manual_value) if active_manual else field_value(field, column, record) if column and record else field.original_value
            self.value.setText(f"Preview: {preview_value or '—'}" if column or active_manual else
                               "Import a spreadsheet to choose a column." if not headers else "Choose a column to preview its value.")
        except ValueError as error:
            preview_value = ""
            self.value.setText(f"Preview needs attention: {error}")
        for control in (self.manual_enabled, self.manual_input, self.persist_manual):
            control.blockSignals(True)
        self.manual_enabled.setChecked(active_manual)
        text = manual_value if active_manual else preview_value
        if self.manual_input.toPlainText() != text:
            self.manual_input.setPlainText(text)
        self.persist_manual.setChecked(persistent if active_manual else not row_selected)
        self.manual_input.setEnabled(active_manual)
        self.persist_manual.setEnabled(active_manual and row_selected)
        self.manual_hint.setText("Saved with the project; included in newly created jobs." if persistent else
                                 "Applies to the selected row. Check persistence to use it for every row and new job." if row_selected else
                                 "No row selected. A manual value will apply to every row.")
        for control in (self.manual_enabled, self.manual_input, self.persist_manual):
            control.blockSignals(False)
        self.manual_options.setVisible(field.manual)
        self.font.blockSignals(True)
        self.font.setValue(int(field.font_size))
        self.font.blockSignals(False)
        self.font.setEnabled(field.kind == "text")

    def manual_edited(self, *_):
        self.manual_changed.emit(self.field_key, self.manual_enabled.isChecked(), self.manual_input.toPlainText(),
                                 self.persist_manual.isChecked() or not self.row_selected)


class Preview(QGraphicsView):
    box_drawn = Signal(object)
    field_clicked = Signal(str)
    zoom_changed = Signal(int)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QColor("#10151e"))
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        # A scrollbar appearing must never trigger a second, automatic fit.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.drawing = False
        self.origin = None
        self.rubber = None
        self.boxes = []
        self.bounds = QRectF()
        self.fit_mode = "width"
        self.page_item = None
        self.page_data = None
        self.page_number = 0
        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(120)
        self.render_timer.timeout.connect(self.render_raster)
        self.click_origin = None

    def set_drawing(self, enabled):
        self.drawing = enabled
        self.setDragMode(QGraphicsView.DragMode.NoDrag if enabled else QGraphicsView.DragMode.ScrollHandDrag)
        self.setCursor(Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor)

    def show_page(self, data: bytes, page_number: int, fields: list[Field], selected: str | None, outlines: bool, links=None, overrides=None, uncertainty_threshold=.7):
        previous_bounds = self.bounds
        previous_center = self.mapToScene(self.viewport().rect().center())
        self.scene().clear()
        self.page_item = None
        self.boxes = []
        self.outline_items = {}
        self.origin = self.rubber = None
        with fitz.open(stream=data, filetype="pdf") as doc:
            page = doc[page_number]
            self.page_data, self.page_number = data, page_number
            self.page_item = self.scene().addPixmap(QPixmap())
            self.page_item.setZValue(-1)
            self.bounds = QRectF(0, 0, page.rect.width, page.rect.height)
            self.scene().setSceneRect(self.bounds)
            for field in fields:
                if field.page != page_number:
                    continue
                rect = fitz.Rect(field.rect)
                if not field.manual:
                    rect = rect * page.rotation_matrix
                qrect = QRectF(rect.x0, rect.y0, rect.width, rect.height)
                self.boxes.append((qrect, field.key))
                if outlines:
                    linked=field.key in (links or {})
                    uncertain=(linked and field.match_score is not None and field.match_score < uncertainty_threshold
                               and field.constant_value is None and field.key not in (overrides or {}))
                    color = QColor('#facc15' if uncertain else '#36d399' if linked else '#fb7185')
                    pen = QPen(color, 2 if field.key == selected else 1.3)
                    pen.setCosmetic(True)
                    fill = QColor(color)
                    fill.setAlpha(20)
                    self.outline_items[field.key] = self.scene().addRect(qrect, pen, fill)
        if self.bounds == previous_bounds:
            self.centerOn(previous_center)
        else:
            self.apply_fit()
        self.render_raster()

    def render_raster(self):
        if self.page_item is None or not self.page_data:
            return
        with fitz.open(stream=self.page_data, filetype="pdf") as doc:
            page = doc[self.page_number]
            # Re-render after zooming for legible text, with a memory limit for large sheets.
            memory_limit = (12_000_000 / max(1, page.rect.get_area())) ** .5
            resolution = min(max(1.6, self.transform().m11() * self.devicePixelRatioF()), 4, memory_limit)
            pix = page.get_pixmap(matrix=fitz.Matrix(resolution, resolution), alpha=False)
            image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
            self.page_item.setPixmap(QPixmap.fromImage(image))
            self.page_item.setScale(1 / resolution)

    def reset_document(self):
        self.bounds = QRectF()
        self.fit_mode = "width"

    def zoom_by(self, factor):
        if self.bounds.isEmpty():
            return
        self.fit_mode = None
        current = self.transform().m11()
        desired = max(.1, min(current * factor, 8))
        self.scale(desired / current, desired / current)
        self.zoom_changed.emit(round(desired * 100))
        self.render_timer.start()

    def apply_fit(self):
        if self.bounds.isEmpty() or self.fit_mode is None:
            return
        width = max(1, self.viewport().width() - 24) / self.bounds.width()
        height = max(1, self.viewport().height() - 24) / self.bounds.height()
        factor = min(width, height) if self.fit_mode == "page" else width
        self.resetTransform()
        self.scale(factor, factor)
        if self.fit_mode == "page":
            self.centerOn(self.bounds.center())
        else:
            self.centerOn(self.bounds.center().x(), self.viewport().height() / (2 * factor))
            self.verticalScrollBar().setValue(self.verticalScrollBar().minimum())
        self.zoom_changed.emit(round(factor * 100))
        self.render_timer.start()

    def fit_page(self):
        self.fit_mode = "page"
        self.apply_fit()

    def fit_width(self):
        self.fit_mode = "width"
        self.apply_fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.apply_fit()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_by(1.25 if event.angleDelta().y() > 0 else .8)
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        point = self.mapToScene(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and self.drawing and self.bounds.contains(point):
            self.origin = point
            self.rubber = self.scene().addRect(QRectF(point, point), QPen(QColor("#e59122"), 1))
            return
        if event.button() == Qt.MouseButton.LeftButton and not self.drawing:
            self.click_origin = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.origin is not None and self.rubber:
            rect = QRectF(self.origin, self.mapToScene(event.position().toPoint())).normalized().intersected(self.bounds)
            self.rubber.setRect(rect)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.origin is not None and self.rubber:
            rect = self.rubber.rect()
            self.scene().removeItem(self.rubber)
            self.origin = self.rubber = None
            if rect.width() >= 15 and rect.height() >= 10:
                self.box_drawn.emit((rect.left(), rect.top(), rect.right(), rect.bottom()))
            return
        if event.button() == Qt.MouseButton.LeftButton and self.click_origin is not None:
            position = event.position().toPoint()
            if (position - self.click_origin).manhattanLength() <= QApplication.startDragDistance():
                point = self.mapToScene(position)
                key = next((key for rect, key in reversed(self.boxes) if rect.contains(point)), "")
                self.field_clicked.emit(key)
            self.click_origin = None
        super().mouseReleaseEvent(event)


class ExportWorker(QThread):
    progress = Signal(int)
    result = Signal(int, str)

    def __init__(self, template, links, jobs):
        super().__init__()
        self.template = copy.deepcopy(template)
        self.links = dict(links)
        self.jobs = copy.deepcopy(jobs)
        self.cancelled = threading.Event()

    def run(self):
        completed = 0
        try:
            for job in self.jobs:
                path, record = job[:2]
                overrides = job[2] if len(job) > 2 else {}
                if self.cancelled.is_set():
                    self.result.emit(completed, "Cancelled. Completed files have been kept.")
                    return
                data = self.template.fill(self.links, record, overrides) if overrides else self.template.fill(self.links, record)
                # Exclusive create also protects files created after preflight.
                with path.open("xb") as stream:
                    try:
                        stream.write(data)
                    except BaseException:
                        stream.close()
                        path.unlink(missing_ok=True)
                        raise
                completed += 1
                self.progress.emit(completed)
            self.result.emit(completed, "")
        except Exception as error:
            self.result.emit(completed, str(error))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Linker — Spreadsheet to PDF")
        self.resize(1440, 940)
        self.template = None
        self.sheet_path = None
        self.spreadsheet_source_path = None
        self.project_path = None
        self.project_cache = None
        self.loaded_header = 1
        self.loaded_sheet = ""
        self.headers = []
        self.rows = []
        self.row_values = {}
        self.links = {}
        self.active_field = None
        self.dirty = False
        self.worker = None
        self.job_worker = None
        self.match_worker = None
        from .model_packs import PackManager, bundled_model_directory
        self.pack_manager = PackManager(root=bundled_model_directory())
        self.jobs_path = jobs_directory()
        self.settings = QSettings("PDFLinker", "PDFLinker")
        from .fusion import default_rrf,validate_rrf,DEFAULT_MINIMUM_SCORE
        self.suggestion_threshold=max(0,min(100,self.settings.value('suggestionThreshold',DEFAULT_MINIMUM_SCORE,type=int)))
        self.uncertainty_threshold=max(0,min(100,self.settings.value('uncertaintyThreshold',70,type=int)))
        import json
        try:self.rrf_settings=validate_rrf(json.loads(self.settings.value('rrfSettings','{}',type=str)))
        except (ValueError,TypeError,KeyError,OverflowError):self.rrf_settings=default_rrf()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(180)
        self.timer.timeout.connect(self.refresh_preview)
        self.build_ui()
        QApplication.instance().installEventFilter(self)
        for key, action in [("Ctrl+S", self.save_project), ("Ctrl+Shift+S", lambda: self.save_project(True)),
                            ("Ctrl+O", self.open_project_dialog), ("Ctrl+E", self.export_checked)]:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(lambda fn=action: self.perform(fn))

    def button(self, text, action, parent_layout, checkable=False):
        button = QPushButton(text)
        button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        button.setCheckable(checkable)
        button.clicked.connect(lambda checked=False: self.perform(lambda: action(checked) if checkable else action()))
        parent_layout.addWidget(button)
        return button

    def perform(self, action):
        try:
            action()
        except Exception as error:
            QMessageBox.warning(self, "Unable to complete action", str(error))

    def build_ui(self):
        from .ui import build_workspace
        build_workspace(self)

    def eventFilter(self, watched, event):
        card = getattr(self, "field_card", None)
        if card is not None and card.isVisible():
            if event.type() == QEvent.Type.MouseButtonPress:
                point = event.globalPosition().toPoint()
                inside = card.rect().contains(card.mapFromGlobal(point))
                popup = card.columns.view().window()
                inside_popup = card.columns.view().isVisible() and popup.frameGeometry().contains(point)
                if not inside and not inside_popup:
                    card.hide()
            elif event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
                if not card.columns.view().isVisible():
                    card.hide()
                    return True
            elif event.type() == QEvent.Type.ApplicationDeactivate:
                card.hide()
        return super().eventFilter(watched, event)

    def schedule_preview(self, *_):
        self.timer.start()

    def preview_fit(self):
        self.preview.fit_page()

    def current_record(self):
        row = self.data_table.currentRow()
        return dict(zip(self.headers, self.rows[row])) if 0 <= row < len(self.rows) else {}

    def current_row_values(self):
        return self.row_values.get(self.data_table.currentRow(), {})

    def confirm_discard(self):
        if not self.dirty:
            return True
        answer = QMessageBox.question(self, "Unsaved project", "Save changes to this project before continuing?",
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        return answer == QMessageBox.StandardButton.Discard

    def import_sheet(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import spreadsheet", "", "Spreadsheets (*.xlsx *.xls *.csv)")
        if not path:
            return
        candidate = Path(path)
        names = sheet_names(candidate)
        if not names:
            raise ValueError("The workbook contains no sheets.")
        headers, rows = read_sheet(candidate, names[0], 1)
        self.sheet_path = candidate
        self.spreadsheet_source_path = candidate.resolve()
        self.sheets.blockSignals(True)
        self.sheets.clear()
        self.sheets.addItems(names)
        self.sheets.blockSignals(False)
        self.header_row.blockSignals(True)
        self.header_row.setValue(1)
        self.header_row.blockSignals(False)
        self.sheet_label.setText(candidate.name)
        self.set_data(headers, rows)
        self.mark_dirty()

    def reload_sheet(self):
        if self.sheet_path and self.sheets.currentText():
            try:
                headers, rows = read_sheet(self.sheet_path, self.sheets.currentText(), self.header_row.value())
            except Exception:
                self.restore_sheet_controls()
                raise
            if self.rows:
                answer = QMessageBox.question(self, "Reload worksheet", "Reload this worksheet? Edits and row checks in the table will be reset.")
                if answer != QMessageBox.StandardButton.Yes:
                    self.restore_sheet_controls()
                    return
            self.set_data(headers, rows)
            self.mark_dirty()

    def restore_sheet_controls(self):
        self.sheets.blockSignals(True)
        self.header_row.blockSignals(True)
        self.sheets.setCurrentText(self.loaded_sheet)
        self.header_row.setValue(self.loaded_header)
        self.sheets.blockSignals(False)
        self.header_row.blockSignals(False)

    def set_data(self, headers, rows):
        self.row_values = {}
        self.loaded_sheet = self.sheets.currentText()
        self.loaded_header = self.header_row.value()
        self.headers, self.rows = headers, rows
        stale = [key for key, column in self.links.items() if column not in headers]
        if self.template:
            stale.extend(field.key for field in self.template.fields
                         if field.key in self.links and field.transform_source == self.links[field.key]
                         and set(field.companion_columns) - set(headers) and field.key not in stale)
        for key in stale:
            del self.links[key]
        if stale:
            self.dirty = True
            QMessageBox.information(self, "Links updated", f"Removed {len(stale)} links to columns absent from this worksheet.")
        self.data_table.blockSignals(True)
        self.data_table.clear()
        self.data_table.setColumnCount(len(headers) + 1)
        self.data_table.setRowCount(len(rows))
        self.data_table.setHorizontalHeaderLabels(["Export", *headers])
        self.data_table.setVerticalHeaderLabels([str(i + self.loaded_header + 1) for i in range(len(rows))])
        for row_index, row in enumerate(rows):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
            check.setCheckState(Qt.CheckState.Unchecked)
            self.data_table.setItem(row_index, 0, check)
            for column, value in enumerate(row, 1):
                self.data_table.setItem(row_index, column, QTableWidgetItem(value))
        self.data_table.resizeColumnsToContents()
        self.data_table.blockSignals(False)
        if rows:
            self.data_table.setCurrentCell(0, 1)
        self.update_count()
        self.update_links()
        self.schedule_preview()

    def import_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import PDF template", "", "PDF files (*.pdf)")
        if not path:
            return
        template = Template(Path(path))
        if self.template and not self.confirm_discard():
            return
        self.template, self.links = template, {}
        self.row_values = {}
        self.active_field = None
        self.mark_dirty()
        self.field_card.hide()
        self.draw_button.setChecked(False)
        self.preview.set_drawing(False)
        self.preview.reset_document()
        self.pdf_label.setText(f"{template.path.name}  •  {len(template.sizes)} pages  •  {len(template.fields)} fillable fields")
        self.pages.blockSignals(True)
        self.pages.clear()
        self.pages.addItems([str(i + 1) for i in range(len(template.sizes))])
        self.pages.blockSignals(False)
        self.update_links()
        self.schedule_preview()
        self.detect_fields()

    def row_changed(self, *_):
        self.mark_dirty()
        self.update_field_card_values()
        self.schedule_preview()

    def data_changed(self, item):
        self.mark_dirty()
        if item.column() == 0:
            self.update_count()
        else:
            self.rows[item.row()][item.column() - 1] = item.text()
            self.update_field_card_values()
            self.schedule_preview()

    def check_rows(self, checked):
        self.data_table.blockSignals(True)
        for row in range(len(self.rows)):
            self.data_table.item(row, 0).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.data_table.blockSignals(False)
        self.update_count()
        self.mark_dirty()

    def checked_rows(self):
        return [i for i in range(len(self.rows)) if self.data_table.item(i, 0).checkState() == Qt.CheckState.Checked]

    def update_count(self):
        self.row_label.setText(f"{len(self.checked_rows())} / {len(self.rows)} rows checked")

    def mark_dirty(self):
        self.dirty = True
        self.update_project_label()

    def update_project_label(self):
        name = self.project_path.stem if self.project_path else "Untitled project"
        self.setWindowTitle(f"{name}{' *' if self.dirty else ''} — PDF Linker")

    def update_links(self):
        self.update_field_card_values()

    def update_field_card_values(self):
        if not self.template or not self.field_card.isVisible():
            return
        field = next((f for f in self.template.fields if f.key == self.field_card.field_key), None)
        if field:
            self.populate_field_card(field)
        else:
            self.field_card.hide()

    def link_changed(self, key, column):
        self.match_identity = None
        if not self.template or key not in {f.key for f in self.template.fields}:
            return
        if column is None:
            self.links.pop(key, None)
        elif column in self.headers:
            self.links[key] = column
        else:
            return
        field = next(field for field in self.template.fields if field.key == key)
        field.match_basis='manual' if column is not None else ''
        field.match_note=''
        field.match_score=None
        if column != field.transform_source:
            field.source_part, field.companion_columns, field.transform_source = "", (), ""
        self.mark_dirty()
        self.update_field_card_values()
        self.schedule_preview()

    def populate_field_card(self, field):
        row_values = self.current_row_values()
        value = row_values.get(field.key, field.constant_value)
        persistent = field.key not in row_values and field.constant_value is not None
        self.field_card.populate(field, self.headers, self.links.get(field.key), self.current_record(),
                                 value, persistent, self.data_table.currentRow() >= 0,
                                 uncertainty_threshold=self.uncertainty_threshold/100)

    def manual_value_changed(self, key, enabled, value, persistent):
        self.match_identity = None
        field = next((field for field in self.template.fields if field.key == key), None) if self.template else None
        if field is None:
            return
        row = self.data_table.currentRow()
        if enabled and persistent:
            field.constant_value = value
            for values in self.row_values.values():
                values.pop(key, None)
        elif enabled and row >= 0:
            field.constant_value = None
            self.row_values.setdefault(row, {})[key] = value
        elif enabled:
            return
        else:
            field.constant_value = None
            self.row_values.get(row, {}).pop(key, None)
        self.mark_dirty()
        self.update_field_card_values()
        self.schedule_preview()

    def show_field_card(self, key, rect):
        if not self.template or self.preview.drawing:
            return
        field = next((field for field in self.template.fields if field.key == key), None)
        if field is None:
            return
        self.populate_field_card(field)
        self.field_card.setFixedWidth(min(370, self.preview.viewport().width() - 20))
        self.field_card.adjustSize()
        box = self.preview.mapFromScene(rect).boundingRect()
        x = max(8, min(box.left(), self.preview.viewport().width() - self.field_card.width() - 8))
        y = box.bottom() + 8
        if y + self.field_card.height() > self.preview.viewport().height() - 8:
            y = box.top() - self.field_card.height() - 8
        y = max(8, min(y, self.preview.viewport().height() - self.field_card.height() - 8))
        self.field_card.move(x, y)
        self.field_card.show()
        self.field_card.raise_()

    def select_field(self, key):
        if not key:
            self.field_card.hide()
            return
        self.active_field = key
        for rect, field_key in self.preview.boxes:
            if key == field_key:
                self.show_field_card(key, rect)
                break

    def page_changed(self, *_):
        if hasattr(self, "field_card"):
            self.field_card.hide()
        self.schedule_preview()

    def refresh_preview(self):
        if not self.template:
            return
        try:
            record = self.current_record()
            overrides = self.current_row_values()
            data = self.template.fill(self.links, record, overrides) if record or assigned_fields(self.template.fields, {}, overrides) else self.template.source
            assigned = assigned_fields(self.template.fields, self.links, overrides)
            self.preview.show_page(data, max(self.pages.currentIndex(), 0), self.template.fields,
                                   self.active_field, self.outlines.isChecked(), assigned, overrides,
                                   uncertainty_threshold=self.uncertainty_threshold/100)
            row = self.data_table.currentRow()
            self.preview_note.setText(f"Preview: spreadsheet row {row + self.loaded_header + 1}  •  {len(assigned)} / {len(self.template.fields)} fields assigned" if record else "Import a spreadsheet and select a row to preview filled values.")
            self.update_field_card_values()
        except Exception as error:
            # Do not leave an old, apparently valid filled preview on screen.
            self.preview.render_timer.stop()
            self.preview.page_item = None
            self.preview.scene().clear()
            self.preview_note.setText(f"Preview needs attention: {error}")

    def require_template(self):
        if not self.template:
            raise ValueError("Import a PDF template first.")

    def auto_match(self):
        self.require_template()
        if not self.headers:
            raise ValueError("Import a spreadsheet first.")
        self.match_fields()

    def suggest_links(self):
        self.require_template()
        if not self.headers:
            raise ValueError("Import a spreadsheet first.")
        self.match_fields(suggest=True)

    def open_settings(self):
        from .settings_ui import SettingsDialog
        dialog=SettingsDialog(self.suggestion_threshold,self.uncertainty_threshold,self,rrf=self.rrf_settings)
        dialog.settings_applied.connect(self.apply_auto_link_settings)
        dialog.rrf_applied.connect(self.apply_rrf_settings)
        dialog.exec()

    def apply_rrf_settings(self,config):
        import json
        from .fusion import validate_rrf
        self.rrf_settings=validate_rrf(config)
        self.settings.setValue('rrfSettings',json.dumps(self.rrf_settings))

    def apply_auto_link_settings(self, minimum_score, uncertainty_threshold):
        self.suggestion_threshold=max(0,min(100,minimum_score))
        self.uncertainty_threshold=max(0,min(100,uncertainty_threshold))
        self.settings.setValue('suggestionThreshold',self.suggestion_threshold)
        self.settings.setValue('uncertaintyThreshold',self.uncertainty_threshold)
        self.uncertain_legend.setToolTip(f'Model suggestions scoring below {self.uncertainty_threshold}/100')
        self.update_field_card_values()
        self.schedule_preview()

    def match_fields(self, suggest=False):
        from .field_matching import lite_links
        if not self.template or not self.headers:
            return
        if self.match_worker and self.match_worker.isRunning():
            raise ValueError('Suggest links is still running. Wait for it to finish.')
        if suggest:
            pack_id='medium-v1'
            from .pack_ui import MatchWorker,AbbreviationDialog
            from .abbreviations import abbreviation_candidates
            candidates=abbreviation_candidates(self.template.fields,self.headers)
            abbreviations={}
            if candidates:
                dialog=AbbreviationDialog(candidates,self)
                if not dialog.exec():return
                abbreviations=dialog.expansions()
            self.match_identity=(id(self.template),tuple(self.headers))
            self.match_worker=MatchWorker(self.pack_manager,pack_id,self.template.fields,self.headers,self.links,self.rows,
                                          minimum_score=self.suggestion_threshold/100,abbreviations=abbreviations,
                                          rrf=self.rrf_settings)
            self.match_worker.result.connect(self.match_finished)
            self.exact_link_button.setEnabled(False)
            self.suggest_links_button.setEnabled(False)
            self.preview_note.setText('Matching fields locally…')
            self.match_worker.start()
            return
        before = len(self.links)
        self.links = lite_links(self.template.fields, self.headers, self.links)
        self.dirty = self.dirty or len(self.links) != before
        self.update_project_label()
        self.update_links()
        self.schedule_preview()

    def match_finished(self,links,error):
        self.match_worker.wait()
        self.exact_link_button.setEnabled(True)
        self.suggest_links_button.setEnabled(True)
        if error:
            QMessageBox.warning(self,'Suggest links stopped',error);return
        if not self.template or self.match_identity!=(id(self.template),tuple(self.headers)):return
        before=len(self.links)
        completed={f.key:f for f in self.match_worker.fields}
        for field in self.template.fields:
            if field.key in links and field.key not in self.links and field.constant_value is None:
                self.links[field.key]=links[field.key]
                matched=completed[field.key]
                field.source_part=matched.source_part
                field.companion_columns=matched.companion_columns
                field.transform_source=matched.transform_source
                field.match_basis=matched.match_basis
                field.match_score=matched.match_score
                field.match_note=matched.match_note
        if len(self.links)!=before:self.mark_dirty()
        self.update_links();self.schedule_preview()
    def detect_fields(self):
        self.require_template()
        added = self.template.detect_fields()
        before = len(self.links)
        if self.headers:
            self.match_fields()
        self.dirty = self.dirty or bool(added) or len(self.links) != before
        self.update_project_label()
        self.update_links()
        self.schedule_preview()
        native = sum(not f.manual for f in self.template.fields)
        detected = sum(f.detected for f in self.template.fields)
        self.pdf_label.setText(f"{self.template.path.name}  •  {len(self.template.sizes)} pages  •  {native} fillable / {detected} detected fields")
        if self.template.fields:
            message = f"Found {len(self.template.fields)} fields; {len(self.links)} linked. Click a field to edit its value or column."
        else:
            message = "No additional fields found. Detection looks for blank outlined boxes and labeled writing lines in PDF graphics; image-only scans need manual placement."
        self.preview_note.setText(message)

    def clear_links(self):
        self.match_identity = None
        self.links = {}
        if self.template:
            for field in self.template.fields:
                field.match_score=None
                field.match_basis=''
                field.match_note=''
        self.mark_dirty()
        self.update_links()
        self.schedule_preview()

    def toggle_draw(self, enabled):
        if enabled and not self.template:
            self.draw_button.setChecked(False)
            raise ValueError("Import a PDF first.")
        self.preview.set_drawing(enabled)
        self.field_card.hide()
    def add_box(self, rect):
        self.require_template()
        name, accepted = QInputDialog.getText(self, "New text box", "Field name (use the matching column name for Exact link):")
        if accepted and name.strip():
            field = Field("manual:" + uuid.uuid4().hex, name.strip(), self.pages.currentIndex(), rect,
                          manual=True)
            self.template.fields.append(field)
            self.template.refresh_context()
            self.mark_dirty()
            self.match_fields()
            self.update_links()
            self.draw_button.setChecked(False)
            self.preview.set_drawing(False)
            self.schedule_preview()

    def remove_box(self, key=None):
        self.require_template()
        field = next((f for f in self.template.fields if f.key == (key or self.active_field)), None)
        if not field or not field.manual:
            raise ValueError("Only detected or drawn fields can be removed. Use × to unlink a native PDF field.")
        self.template.fields.remove(field)
        self.links.pop(field.key, None)
        for values in self.row_values.values():
            values.pop(field.key, None)
        self.active_field = None
        self.mark_dirty()
        self.field_card.hide()
        self.update_links()
        self.schedule_preview()

    def font_changed(self, key, value):
        if self.template:
            for field in self.template.fields:
                if field.key == key and field.manual:
                    field.font_size = value
                    self.mark_dirty()
                    self.schedule_preview()

    def edit_filename(self):
        value, accepted = QInputDialog.getText(self, "Export filename", "Use {row} or {Column Name} in the filename:", text=self.filename.text())
        if accepted and value.strip():
            self.filename.setText(value.strip())

    def save_project(self, force_dialog=False):
        path = self.project_path
        if path is None or force_dialog:
            chosen, _ = QFileDialog.getSaveFileName(self, "Save project", str(path or "Untitled.pdflinker"), "PDF Linker projects (*.pdflinker)")
            if not chosen:
                return False
            path = Path(chosen)
            if path.suffix.lower() != ".pdflinker":
                path = path.with_suffix(".pdflinker")
        write_project(path, template=self.template, spreadsheet_path=self.sheet_path,
                      headers=self.headers, rows=self.rows, links=self.links,
                      checked=self.checked_rows(), current_row=self.data_table.currentRow(),
                      sheet=self.sheets.currentText(), header_row=self.header_row.value(),
                      filename=self.filename.text(), outlines=self.outlines.isChecked(),
                      spreadsheet_source_path=self.spreadsheet_source_path or "", row_values=self.row_values)
        self.project_path = path
        self.dirty = False
        self.update_project_label()
        self.remember_project(path)
        return True

    def open_project_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open project", "", "PDF Linker projects (*.pdflinker)")
        if path:
            self.open_project(Path(path))

    def open_project(self, path):
        manifest, template, links, spreadsheet, warnings = read_project(path)
        cache, sheet_path, names = None, None, []
        if spreadsheet is not None:
            cache = tempfile.TemporaryDirectory(prefix="pdf-linker-project-")
            sheet_path = Path(cache.name) / manifest["spreadsheet_name"]
            sheet_path.write_bytes(spreadsheet)
            names = sheet_names(sheet_path)
            if manifest["sheet"] not in names:
                cache.cleanup()
                raise ValueError("The project's saved worksheet is absent from its workbook.")
        if not self.confirm_discard():
            if cache:
                cache.cleanup()
            return
        self.timer.stop()
        self.preview.render_timer.stop()
        self.field_card.hide()
        self.sheet_path = sheet_path
        self.spreadsheet_source_path = manifest.get("spreadsheet_source_path")
        self.project_cache = cache
        self.template, self.links = template, links
        self.active_field = None
        self.sheets.blockSignals(True)
        self.sheets.clear()
        self.sheets.addItems(names or ([manifest["sheet"]] if manifest["sheet"] else []))
        self.sheets.setCurrentText(manifest["sheet"])
        self.sheets.blockSignals(False)
        self.header_row.blockSignals(True)
        self.header_row.setValue(manifest["header_row"])
        self.header_row.blockSignals(False)
        self.sheet_label.setText(manifest.get("spreadsheet_name") or "No spreadsheet imported")
        self.set_data(manifest["headers"], manifest["rows"])
        self.row_values = {int(row): values for row, values in manifest.get("row_values", {}).items()}
        self.data_table.blockSignals(True)
        for row in manifest["checked"]:
            self.data_table.item(row, 0).setCheckState(Qt.CheckState.Checked)
        if self.rows:
            self.data_table.setCurrentCell(max(0, manifest["current_row"]), 1)
        self.data_table.blockSignals(False)
        self.update_count()
        self.filename.setText(manifest["filename"])
        self.outlines.setChecked(bool(manifest.get("outlines", True)))
        self.pages.blockSignals(True)
        self.pages.clear()
        if template:
            self.pages.addItems([str(i + 1) for i in range(len(template.sizes))])
            self.pdf_label.setText(f"{template.path.name}  |  {len(template.fields)} fields")
        else:
            self.pdf_label.setText("Import a template - fields are detected automatically")
        self.pages.blockSignals(False)
        self.draw_button.setChecked(False)
        self.preview.set_drawing(False)
        self.preview.reset_document()
        self.preview.page_item = None
        self.preview.page_data = None
        self.preview.scene().clear()
        self.project_path = Path(path)
        self.dirty = bool(warnings)
        self.update_project_label()
        self.refresh_preview()
        self.remember_project(path)

    def recent_project_paths(self):
        paths = self.settings.value("recentProjects", [], type=list)
        return [Path(path) for path in paths if isinstance(path, str) and path][:10]

    def remember_project(self, path):
        path = Path(path).resolve()
        identity = os.path.normcase(str(path))
        paths = [str(path)] + [str(previous) for previous in self.recent_project_paths()
                               if os.path.normcase(str(previous)) != identity]
        self.settings.setValue("recentProjects", paths[:10])
        self.settings.sync()
        self.refresh_recent_menu()

    def refresh_recent_menu(self):
        self.recent_menu.clear()
        self.recent_menu.setToolTipsVisible(True)
        paths = self.recent_project_paths()
        for index, path in enumerate(paths, 1):
            parent = str(path.parent)
            if len(parent) > 60:
                parent = "…" + parent[-60:]
            label = f"{path.name} — {parent}".replace("&", "&&")
            action = self.recent_menu.addAction(f"&{index % 10}  {label}")
            action.setToolTip(str(path))
            action.setData(str(path))
            action.triggered.connect(lambda checked=False, saved=path: self.perform(lambda: self.open_project(saved)))
        if paths:
            self.recent_menu.addSeparator()
            self.recent_menu.addAction("Clear recent projects", self.clear_recent_projects)
        else:
            self.recent_menu.addAction("No recent projects").setEnabled(False)

    def clear_recent_projects(self):
        self.settings.remove("recentProjects")
        self.settings.sync()
        self.refresh_recent_menu()

    def validate_export(self):
        self.require_template()
        if not self.rows:
            raise ValueError("Import a spreadsheet containing data rows first.")
        if not assigned_fields(self.template.fields, self.links) and not any(self.row_values.values()):
            raise ValueError("Link a PDF field or enter a manual value first.")

    def confirm_unfilled(self, indices):
        missing = []
        for index in indices:
            record = dict(zip(self.headers, self.rows[index]))
            fields = self.template.empty_fields(self.links, record, self.row_values.get(index))
            if fields:
                missing.append((index, fields))
        if not missing:
            return True
        count = sum(len(fields) for _, fields in missing)
        details = []
        for index, fields in missing[:5]:
            names = ", ".join(field.label or field.name for field in fields[:5])
            if len(fields) > 5:
                names += f", and {len(fields) - 5} more"
            details.append(f"Row {index + self.loaded_header + 1}: {names}")
        if len(missing) > 5:
            details.append(f"Plus {len(missing) - 5} more rows.")
        message = (f"There are {count} unfilled fields across {len(missing)} PDF(s).\n\n" +
                   "\n".join(details) + "\n\nExport anyway?")
        return QMessageBox.warning(self, "Unfilled PDF fields", message,
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                   QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Yes

    def create_job(self):
        from .job_ui import CreateJobDialog
        dialog = CreateJobDialog(self.jobs_path, self.project_path, self)
        if dialog.exec() and dialog.job_path:
            self.refresh_scripts_menu()
            QMessageBox.information(self, "Job created", "Run this job from Scripts, or double-click:\n\n" +
                                    str(dialog.job_path.parent / "Run job.bat") +
                                    "\n\nEach run checks for new rows once. Completion history is saved beside the script.")

    def refresh_scripts_menu(self):
        self.scripts_menu.clear()
        jobs = list_jobs(self.jobs_path)
        running = self.job_worker is not None and self.job_worker.isRunning()
        for name, path in jobs:
            action = self.scripts_menu.addAction(name.replace("&", "&&"))
            action.setToolTip(str(path))
            action.setEnabled(not running)
            action.triggered.connect(lambda checked=False, saved=path: self.perform(lambda: self.run_saved_job(saved)))
        if not jobs:
            self.scripts_menu.addAction("No saved jobs — use File → Create job").setEnabled(False)
        self.scripts_menu.addSeparator()
        self.scripts_menu.addAction("Open scripts folder", lambda: self.perform(self.open_scripts_folder))

    def open_scripts_folder(self):
        self.jobs_path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.jobs_path)))

    def run_saved_job(self, path):
        from .job_ui import JobWorker
        if self.job_worker and self.job_worker.isRunning():
            raise ValueError("A job is already running. Wait for it to finish.")
        self.job_progress = QProgressDialog("Checking for new spreadsheet rows…", "Cancel", 0, 0, self)
        self.job_progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.job_progress.setMinimumDuration(0)
        self.job_progress.setAutoClose(False)
        self.job_progress.setAutoReset(False)
        self.job_worker = JobWorker(path)
        self.job_progress.canceled.connect(self.job_worker.cancelled.set)
        self.job_worker.progress.connect(self.job_progress_changed)
        self.job_worker.result.connect(self.job_finished)
        self.job_worker.start()

    def job_progress_changed(self, done, total):
        self.job_progress.setRange(0, max(1, total))
        self.job_progress.setValue(done)
        self.job_progress.setLabelText(f"Exported {done} of {total} new PDFs…")

    def job_finished(self, result, error):
        self.job_worker.wait()
        self.job_progress.close()
        if error:
            QMessageBox.warning(self, "Job stopped", error + "\n\nCompleted rows remain recorded. See run.log in the job folder.")
        else:
            message = result_message(result)
            if result["cancelled"]:
                message += "\nCancelled. Run the job again to continue."
            QMessageBox.information(self, "Job complete", message)

    def export_current(self):
        self.validate_export()
        row = self.data_table.currentRow()
        if row < 0:
            raise ValueError("Select a preview row first.")
        record = self.current_record()
        name = output_name(self.filename.text(), record, row + self.loaded_header + 1)
        path, _ = QFileDialog.getSaveFileName(self, "Export preview row", name, "PDF files (*.pdf)",
                                            options=QFileDialog.Option.DontConfirmOverwrite)
        if path:
            target = Path(path)
            if target.exists():
                raise ValueError("That file already exists. Choose a new filename.")
            if self.confirm_unfilled([row]):
                self.start_export([(target, record, dict(self.row_values.get(row, {})))])

    def export_checked(self):
        self.validate_export()
        selected = self.checked_rows()
        if not selected:
            raise ValueError("Check the Export box beside at least one spreadsheet row.")
        folder = QFileDialog.getExistingDirectory(self, "Choose export folder")
        if not folder:
            return
        jobs, used = [], set()
        for index in selected:
            record = dict(zip(self.headers, self.rows[index]))
            name = output_name(self.filename.text(), record, index + self.loaded_header + 1)
            if name.casefold() in used:
                raise ValueError(f"Multiple rows produce '{name}'. Include {{row}} in the filename pattern to make names unique.")
            used.add(name.casefold())
            path = Path(folder) / name
            if path.exists():
                raise ValueError(f"'{name}' already exists. Choose another folder or filename pattern.")
            jobs.append((path, record, dict(self.row_values.get(index, {}))))
        if self.confirm_unfilled(selected):
            self.start_export(jobs)

    def start_export(self, jobs):
        if self.worker and self.worker.isRunning():
            raise ValueError("The previous export is still finishing. Wait for its result before starting another.")
        self.progress_dialog = QProgressDialog("Generating PDFs…", "Cancel", 0, len(jobs), self)
        self.progress_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setAutoClose(False)
        self.progress_dialog.setAutoReset(False)
        self.worker = ExportWorker(self.template, self.links, jobs)
        self.progress_dialog.canceled.connect(self.worker.cancelled.set)
        self.worker.progress.connect(self.progress_dialog.setValue)
        self.worker.result.connect(self.export_result)
        self.worker.start()

    def export_result(self, count, error):
        self.worker.wait()
        self.progress_dialog.close()
        message = f"Exported {count} PDF{'s' if count != 1 else ''}."
        if error:
            QMessageBox.warning(self, "Export stopped", message + "\n\n" + error)
        else:
            QMessageBox.information(self, "Export complete", message)

    def closeEvent(self, event):
        if self.match_worker and self.match_worker.isRunning():
            event.ignore()
            return
        if (self.worker and self.worker.isRunning()) or (self.job_worker and self.job_worker.isRunning()):
            event.ignore()
            return
        if self.confirm_discard():
            QApplication.instance().removeEventFilter(self)
            event.accept()
        else:
            event.ignore()


from .ui import STYLE


def main():
    if "--run-job" in sys.argv[1:]:
        from .jobs import command_line
        sys.exit(command_line(sys.argv[1:]))
    app = QApplication(sys.argv)
    app.setApplicationName("PDF Linker")
    app.setWindowIcon(QIcon(str(Path(__file__).with_name("assets") / "icon.ico")))
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in [(QPalette.ColorRole.Window, "#161d29"), (QPalette.ColorRole.WindowText, "#e2e8f0"),
                        (QPalette.ColorRole.Base, "#111925"), (QPalette.ColorRole.AlternateBase, "#162131"),
                        (QPalette.ColorRole.Text, "#e2e8f0"), (QPalette.ColorRole.Button, "#222c3d"),
                        (QPalette.ColorRole.ButtonText, "#e2e8f0"), (QPalette.ColorRole.Highlight, "#6366f1"),
                        (QPalette.ColorRole.HighlightedText, "#ffffff")]:
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
