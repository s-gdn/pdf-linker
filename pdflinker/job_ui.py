"""Job creation dialog and background execution for the desktop app."""
from pathlib import Path
import threading

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                             QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                             QSpinBox, QVBoxLayout, QWidget)

from .jobs import create_desktop_shortcut, create_job, run_job
from .project import read_project
from .core import output_name, read_sheet


class CreateJobDialog(QDialog):
    def __init__(self, directory, project=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create export job")
        self.resize(700, 620)
        self.directory = Path(directory)
        self.job_path = None
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit()
        form.addRow("Job name", self.name)
        self.project = QLineEdit()
        form.addRow("Saved project", self.path_control(self.project, self.choose_project))
        self.spreadsheet = QLineEdit()
        form.addRow("Live spreadsheet", self.path_control(self.spreadsheet, self.choose_spreadsheet))
        self.start = QSpinBox()
        self.start.setRange(2, 1_048_576)
        form.addRow("Start at spreadsheet row", self.start)
        self.output = QLineEdit()
        form.addRow("PDF output folder", self.path_control(self.output, self.choose_output))
        layout.addLayout(form)
        self.naming_enabled = QCheckBox("Use column-based PDF filenames")
        layout.addWidget(self.naming_enabled)
        self.naming_options = QWidget()
        naming = QFormLayout(self.naming_options)
        naming.setContentsMargins(12, 0, 0, 0)
        self.filename_column = QComboBox()
        self.filename_prefix = QLineEdit()
        self.filename_suffix = QLineEdit()
        self.filename_prefix.setPlaceholderText("Optional text before the column value")
        self.filename_suffix.setPlaceholderText("Optional text after the column value")
        naming.addRow("Column", self.filename_column)
        naming.addRow("Text before", self.filename_prefix)
        naming.addRow("Text after", self.filename_suffix)
        self.filename_example = QLabel()
        self.filename_example.setWordWrap(True)
        self.filename_example.setObjectName("muted")
        naming.addRow("Example", self.filename_example)
        layout.addWidget(self.naming_options)
        identity = QHBoxLayout()
        self.identity_enabled = QCheckBox("Track records by unique ID")
        self.identity_column = QComboBox()
        self.identity_column.setToolTip("Choose a permanent, unique Employee ID, Reference, or similar column. Do not change an existing record's ID.")
        identity.addWidget(self.identity_enabled)
        identity.addWidget(self.identity_column, 1)
        layout.addLayout(identity)
        self.regenerate_changed = QCheckBox("Create new PDF for changed rows (keep previous PDF as an older revision)")
        layout.addWidget(self.regenerate_changed)
        self.desktop_shortcut = QCheckBox("Create desktop shortcut to this job script")
        layout.addWidget(self.desktop_shortcut)
        hint = QLabel("With unique IDs, records can move or be deleted without losing track; deleted records' PDFs are kept. "
                      "Start row sets the initial selection; later new IDs are found anywhere in the sheet. "
                      "Without IDs, jobs remain append-only and stop if completed rows move or change. Each run checks once.")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Create job")
        buttons.accepted.connect(self.create)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.preview_record = {}
        self.saved_headers = []
        self.saved_sheet = ""
        self.saved_header_row = 1
        self.spreadsheet.editingFinished.connect(self.load_columns)
        self.naming_enabled.toggled.connect(self.update_options)
        self.identity_enabled.toggled.connect(self.update_options)
        self.filename_column.currentIndexChanged.connect(self.update_filename_example)
        self.filename_prefix.textChanged.connect(self.update_filename_example)
        self.filename_suffix.textChanged.connect(self.update_filename_example)
        self.update_options()
        if project:
            self.set_project(Path(project))

    def path_control(self, edit, callback):
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit, 1)
        button = QPushButton("Browse…")
        button.clicked.connect(callback)
        row.addWidget(button)
        return widget

    def set_project(self, path):
        try:
            manifest, _, _, _, _ = read_project(path)
            self.saved_headers = manifest["headers"]
            self.saved_sheet = manifest["sheet"]
            self.saved_header_row = manifest["header_row"]
            self.project.setText(str(path.resolve()))
            self.name.setText(path.stem)
            self.start.setMinimum(manifest["header_row"] + 1)
            self.start.setValue(manifest["header_row"] + 1)
            source = manifest.get("spreadsheet_source_path")
            sibling = path.parent / (manifest.get("spreadsheet_name") or "")
            self.spreadsheet.setText(source or (str(sibling.resolve()) if sibling.is_file() else ""))
            self.output.setText(str(path.parent / (path.stem + " PDFs")))
            self.load_columns()
        except Exception as error:
            QMessageBox.warning(self, "Unable to read project", str(error))

    def choose_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose saved project", "", "PDF Linker projects (*.pdflinker)")
        if path:
            self.set_project(Path(path))

    def choose_spreadsheet(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose the live spreadsheet", "", "Spreadsheets (*.xlsx *.xls *.csv)")
        if path:
            self.spreadsheet.setText(path)
            self.load_columns()

    def update_options(self, *_):
        self.naming_options.setEnabled(self.naming_enabled.isChecked())
        self.identity_column.setEnabled(self.identity_enabled.isChecked())
        self.regenerate_changed.setEnabled(self.identity_enabled.isChecked())
        if not self.identity_enabled.isChecked():
            self.regenerate_changed.setChecked(False)
        self.update_filename_example()

    def load_columns(self):
        headers = self.saved_headers
        self.preview_record = {}
        try:
            if self.spreadsheet.text().strip() and self.saved_sheet:
                headers, rows = read_sheet(Path(self.spreadsheet.text()), self.saved_sheet, self.saved_header_row)
                if rows:
                    self.preview_record = dict(zip(headers, next((row for row in rows if any(row)), rows[0])))
        except Exception:
            pass  # Final creation validates the actual selected file and columns.
        for combo in (self.filename_column, self.identity_column):
            previous = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(headers)
            if previous in headers:
                combo.setCurrentText(previous)
            else:
                preferred = ["Name"] if combo is self.filename_column else ["Employee ID", "ID", "Reference"]
                for name in preferred:
                    if name in headers:
                        combo.setCurrentText(name)
                        break
            combo.blockSignals(False)
        self.update_filename_example()

    def update_filename_example(self, *_):
        column = self.filename_column.currentText()
        value = self.preview_record.get(column) or f"[{column or 'column value'}]"
        name = self.filename_prefix.text() + value + self.filename_suffix.text()
        try:
            self.filename_example.setText(output_name("{value}", {"value": name}, 1))
        except ValueError:
            self.filename_example.setText("The selected value does not produce a valid filename.")

    def choose_output(self):
        path = QFileDialog.getExistingDirectory(self, "Choose PDF output folder")
        if path:
            self.output.setText(path)

    def create(self):
        try:
            if not self.project.text().strip() or not self.spreadsheet.text().strip() or not self.output.text().strip():
                raise ValueError("Choose a saved project, its live spreadsheet, and an output folder.")
            self.job_path = create_job(directory=self.directory, name=self.name.text(),
                                       project=Path(self.project.text()), spreadsheet=Path(self.spreadsheet.text()),
                                       start_row=self.start.value(), output=Path(self.output.text()),
                                       naming={"column": self.filename_column.currentText(), "prefix": self.filename_prefix.text(),
                                               "suffix": self.filename_suffix.text()} if self.naming_enabled.isChecked() else None,
                                       identity_column=self.identity_column.currentText() if self.identity_enabled.isChecked() else None,
                                       regenerate_changed=self.regenerate_changed.isChecked())
            if self.desktop_shortcut.isChecked():
                try:
                    create_desktop_shortcut(self.job_path.parent / "Run job.bat", self.name.text())
                except Exception as error:
                    QMessageBox.warning(self, "Job created; shortcut unavailable", str(error) +
                                        "\n\nThe job is saved and can still be run from the Scripts menu.")
            self.accept()
        except Exception as error:
            QMessageBox.warning(self, "Unable to create job", str(error))


class JobWorker(QThread):
    progress = Signal(int, int)
    result = Signal(object, str)

    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self.cancelled = threading.Event()

    def run(self):
        try:
            result = run_job(self.path, progress=self.progress.emit, cancelled=self.cancelled)
            self.result.emit(result, "")
        except Exception as error:
            self.result.emit(None, str(error))
