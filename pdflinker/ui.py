"""Desktop workspace layout and dark theme."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMenu, QSpinBox, QSplitter, QTableWidget, QToolButton,
    QVBoxLayout, QWidget, QMessageBox, QSizePolicy,
)
from .layouts import FlowLayout
from .help_ui import show_help


class ElidedLabel(QLabel):
    """Keep single-line metadata from shrinking controls or growing panel headers."""
    def __init__(self, text):
        super().__init__(text)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().windowText().color())
        painter.drawText(self.contentsRect(), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, self.width()))


def build_workspace(window):
    from .app import FieldCard, Preview
    w = window
    root = QWidget()
    w.setCentralWidget(root)
    layout = QVBoxLayout(root)
    layout.setContentsMargins(8, 6, 8, 6)
    layout.setSpacing(6)

    menu_bar = w.menuBar()
    menu_bar.setNativeMenuBar(False)
    file_menu = menu_bar.addMenu("File")
    file_menu.addAction("Open project...\tCtrl+O", lambda: w.perform(w.open_project_dialog))
    w.recent_menu = file_menu.addMenu("Open recent")
    w.recent_menu.aboutToShow.connect(w.refresh_recent_menu)
    w.refresh_recent_menu()
    file_menu.addAction("Save project\tCtrl+S", lambda: w.perform(w.save_project))
    file_menu.addAction("Save project as...\tCtrl+Shift+S", lambda: w.perform(lambda: w.save_project(True)))
    file_menu.addSeparator()
    file_menu.addAction("Import spreadsheet...", lambda: w.perform(w.import_sheet))
    file_menu.addAction("Import PDF...", lambda: w.perform(w.import_pdf))
    file_menu.addSeparator()
    export = file_menu.addMenu("Export PDFs")
    export.addAction("Export checked rows...\tCtrl+E", lambda: w.perform(w.export_checked))
    export.addAction("Export preview row...", lambda: w.perform(w.export_current))
    export.addSeparator()
    export.addAction("Filename pattern...", lambda: w.perform(w.edit_filename))
    w.export_menu = export
    file_menu.addSeparator()
    file_menu.addAction("Create job…", lambda: w.perform(w.create_job))
    file_menu.addSeparator()
    file_menu.addAction("Exit", w.close)
    view_menu = menu_bar.addMenu("View")
    view_menu.addAction("Zoom in", lambda: w.preview.zoom_by(1.25))
    view_menu.addAction("Zoom out", lambda: w.preview.zoom_by(.8))
    view_menu.addAction("Fit width", lambda: w.preview.fit_width())
    view_menu.addAction("Fit page", w.preview_fit)
    view_menu.addSeparator()
    view_menu.addAction("Equal panel widths", lambda: split.setSizes([1, 1]))
    w.scripts_menu = menu_bar.addMenu("Scripts")
    w.scripts_menu.aboutToShow.connect(w.refresh_scripts_menu)
    help_menu = menu_bar.addMenu("Help")
    help_menu.addAction("How to use", lambda: show_help(w))
    help_menu.addAction("About", lambda: QMessageBox.about(w, "About PDF Linker", "PDF Linker\nLocal spreadsheet-to-PDF workspace.\nFiles are processed on this computer."))
    w.filename = QLineEdit("Form_{row}", root)
    w.filename.hide()
    w.filename.textChanged.connect(lambda: w.mark_dirty())

    split = QSplitter(Qt.Orientation.Horizontal)
    split.setChildrenCollapsible(False)
    split.setHandleWidth(6)
    w.workspace_split = split
    layout.addWidget(split, 1)

    left = QFrame()
    left.setObjectName("panel")
    left.setMinimumWidth(300)
    ll = QVBoxLayout(left)
    ll.setContentsMargins(12, 10, 12, 10)
    ll.setSpacing(8)
    heading = QHBoxLayout()
    label = QLabel("Spreadsheet")
    label.setObjectName("panelTitle")
    heading.addWidget(label)
    w.sheet_label = ElidedLabel("Import an Excel or CSV file")
    w.sheet_label.setObjectName("muted")
    heading.addWidget(w.sheet_label, 1)
    w.button("Import spreadsheet", w.import_sheet, heading)
    ll.addLayout(heading)
    controls = QHBoxLayout()
    controls.addWidget(QLabel("Sheet"))
    w.sheets = QComboBox()
    w.sheets.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    w.sheets.setMinimumContentsLength(5)
    w.sheets.currentTextChanged.connect(lambda: w.perform(w.reload_sheet))
    controls.addWidget(w.sheets, 1)
    controls.addWidget(QLabel("Header row"))
    w.header_row = QSpinBox()
    w.header_row.setRange(1, 100000)
    w.header_row.setMinimumWidth(70)
    w.header_row.valueChanged.connect(lambda: w.perform(w.reload_sheet))
    controls.addWidget(w.header_row)
    ll.addLayout(controls)
    w.data_table = QTableWidget()
    w.data_table.setAlternatingRowColors(True)
    w.data_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    w.data_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    w.data_table.currentCellChanged.connect(w.row_changed)
    w.data_table.itemChanged.connect(w.data_changed)
    w.data_table.verticalHeader().setDefaultSectionSize(36)
    ll.addWidget(w.data_table, 1)
    selection = QHBoxLayout()
    w.button("Check all", lambda: w.check_rows(True), selection)
    w.button("Uncheck all", lambda: w.check_rows(False), selection)
    selection.addStretch()
    ll.addLayout(selection)
    w.row_label = QLabel("0 rows checked")
    w.row_label.setObjectName("muted")
    ll.addWidget(w.row_label)
    hint = QLabel("Click a row to preview. Check rows to export.\nDouble-click a cell to edit its value.")
    hint.setObjectName("muted")
    hint.setWordWrap(True)
    ll.addWidget(hint)
    split.addWidget(left)

    right = QFrame()
    right.setObjectName("panel")
    right.setMinimumWidth(300)
    rl = QVBoxLayout(right)
    rl.setContentsMargins(12, 10, 12, 10)
    rl.setSpacing(6)
    heading = QHBoxLayout()
    label = QLabel("PDF template")
    label.setObjectName("panelTitle")
    heading.addWidget(label)
    w.pdf_label = ElidedLabel("Import a template — fields are detected automatically")
    w.pdf_label.setObjectName("muted")
    heading.addWidget(w.pdf_label, 1)
    rl.addLayout(heading)
    controls = QWidget()
    controls.setObjectName("pdfControls")
    controls.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    flow = FlowLayout(controls)
    w.pdf_controls = controls
    w.button("Import PDF", w.import_pdf, flow)
    w.button("Auto-link", w.auto_match, flow)
    fields = QToolButton()
    fields.setText("Fields")
    fields.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    field_menu = QMenu(fields)
    w.draw_button = field_menu.addAction("Draw field")
    w.draw_button.setCheckable(True)
    w.draw_button.triggered.connect(lambda checked: w.perform(lambda: w.toggle_draw(checked)))
    field_menu.addAction("Clear links", lambda: w.perform(w.clear_links))
    field_menu.addSeparator()
    w.outlines = QAction("Field outlines", w)
    w.outlines.setCheckable(True)
    w.outlines.setChecked(True)
    w.outlines.toggled.connect(lambda: (w.mark_dirty(), w.schedule_preview()))
    field_menu.addAction(w.outlines)
    view_menu.addAction(w.outlines)
    fields.setMenu(field_menu)
    flow.addWidget(fields)
    page_group = QWidget()
    page_row = QHBoxLayout(page_group)
    page_row.setContentsMargins(0, 0, 0, 0)
    page_row.setSpacing(8)
    page_row.addWidget(QLabel("Page"))
    w.pages = QComboBox()
    w.pages.setFixedWidth(54)
    w.pages.currentIndexChanged.connect(w.page_changed)
    page_row.addWidget(w.pages)
    flow.addWidget(page_group)
    zoom_group = QWidget()
    zoom_row = QHBoxLayout(zoom_group)
    zoom_row.setContentsMargins(0, 0, 0, 0)
    zoom_row.setSpacing(8)
    w.button("−", lambda: w.preview.zoom_by(.8), zoom_row).setFixedWidth(26)
    w.zoom_label = QLabel("100%")
    w.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    w.zoom_label.setFixedWidth(40)
    zoom_row.addWidget(w.zoom_label)
    w.button("+", lambda: w.preview.zoom_by(1.25), zoom_row).setFixedWidth(26)
    flow.addWidget(zoom_group)
    rl.addWidget(controls)
    w.preview = Preview()
    w.preview.zoom_changed.connect(lambda percent: w.zoom_label.setText(f"{percent}%"))
    w.preview.box_drawn.connect(lambda rect: w.perform(lambda: w.add_box(rect)))
    w.preview.field_clicked.connect(w.select_field)
    w.preview.field_hovered.connect(w.hover_field)
    rl.addWidget(w.preview, 1)
    w.field_card = FieldCard(w.preview.viewport())
    w.field_card.link_changed.connect(w.link_changed)
    w.field_card.remove_requested.connect(lambda key: w.perform(lambda: w.remove_box(key)))
    w.field_card.font_changed.connect(w.font_changed)
    footer = QHBoxLayout()
    w.preview_note = ElidedLabel("Ctrl + wheel to zoom / Drag to pan")
    w.preview_note.setObjectName("muted")
    footer.addWidget(w.preview_note, 1)
    linked = QLabel("Linked")
    linked.setObjectName("linkedLegend")
    footer.addWidget(linked)
    unlinked = QLabel("Not linked")
    unlinked.setObjectName("unlinkedLegend")
    footer.addWidget(unlinked)
    rl.addLayout(footer)
    split.addWidget(right)
    split.setStretchFactor(0, 1)
    split.setStretchFactor(1, 1)
    split.setSizes([1, 1])


STYLE = """
QWidget { font-family: 'Segoe UI'; font-size: 12px; color: #e2e8f0; }
QMainWindow, QDialog, QMessageBox { background: #0c1018; }
QFrame#panel { background: #161d29; border: 1px solid #283245; border-radius: 8px; }
QLabel { background: transparent; border: none; }
QLabel#panelTitle { font-size: 15px; font-weight: 600; color: #f8fafc; }
QLabel#muted { color: #94a3b8; }
QLabel#linkedLegend { color: #36d399; }
QLabel#unlinkedLegend { color: #fb7185; }
QPushButton, QToolButton { background: #222c3d; border: 1px solid #344158; border-radius: 6px; padding: 8px 12px; color: #e2e8f0; }
QPushButton:hover, QToolButton:hover { background: #2d3950; border-color: #657494; }
QPushButton:pressed, QToolButton:pressed { background: #37445e; }
QPushButton:checked { background: #353376; border-color: #818cf8; }
QPushButton:disabled { color: #64748b; background: #1c2432; }
QToolButton::menu-indicator { width: 6px; right: 2px; }
QMenuBar { background: #161d29; color: #e2e8f0; padding: 1px 6px; border-bottom: 1px solid #283245; }
QMenuBar::item { background: transparent; padding: 4px 10px; }
QMenuBar::item:selected { background: #303d55; border-radius: 3px; }
QWidget#pdfControls QPushButton, QWidget#pdfControls QToolButton { padding: 4px 7px; border-radius: 4px; }
QWidget#pdfControls QComboBox { padding: 4px; }
QComboBox, QSpinBox, QLineEdit { background: #101722; border: 1px solid #344158; border-radius: 6px; padding: 6px; color: #e2e8f0; selection-background-color: #4f46a5; }
QComboBox:focus, QSpinBox:focus, QLineEdit:focus { border-color: #818cf8; }
QComboBox QAbstractItemView { background: #202b3d; color: #e2e8f0; selection-background-color: #454581; border: 1px solid #53627c; }
QTableWidget { background: #111925; alternate-background-color: #162131; gridline-color: #253246; border: 1px solid #28364b; border-radius: 6px; selection-background-color: #303d65; selection-color: white; }
QHeaderView::section { background: #202b3d; color: #cbd5e1; padding: 8px; border: none; border-right: 1px solid #2c3a50; }
QTableCornerButton::section { background: #202b3d; border: none; }
QGraphicsView { border: 1px solid #2a3548; border-radius: 6px; background: #10151e; }
QSplitter::handle { background: #0c1018; }
QSplitter::handle:hover { background: #3d4c68; border-radius: 4px; }
QScrollBar:vertical { background: #101722; width: 12px; margin: 0; }
QScrollBar:horizontal { background: #101722; height: 12px; margin: 0; }
QScrollBar::handle { background: #3e4b62; border-radius: 5px; min-height: 24px; min-width: 24px; }
QScrollBar::handle:hover { background: #64748b; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QCheckBox { spacing: 6px; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #64748b; border-radius: 4px; background: #111925; }
QCheckBox::indicator:checked { background: #6366f1; border-color: #a5b4fc; }
QFrame#fieldCard { background: #202b3d; border: 1px solid #667494; border-radius: 10px; }
QLabel#cardTitle { font-size: 14px; font-weight: 600; color: white; }
QPushButton#unlink { padding: 0; color: #fda4af; font-size: 20px; }
QMenu { background: #202b3d; color: #e2e8f0; border: 1px solid #4c5b76; border-radius: 6px; padding: 6px; }
QMenu::item { padding: 9px 22px; border-radius: 4px; }
QMenu::item:selected { background: #3e437b; }
QMenu::separator { height: 1px; background: #3c4860; margin: 5px; }
QToolTip { background: #263247; color: #f1f5f9; border: 1px solid #64748b; padding: 6px; }
QProgressBar { background: #111925; border: 1px solid #344158; border-radius: 5px; text-align: center; }
QProgressBar::chunk { background: #6366f1; }
"""
