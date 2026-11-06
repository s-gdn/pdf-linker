import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf as fitz
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtGui import QFontDatabase, QFont

from pdflinker.app import ExportWorker, MainWindow, Preview
from pdflinker.core import Template, auto_link, read_sheet
from examples.create_examples import create


@pytest.fixture(scope="module", autouse=True)
def desktop_application():
    app = QApplication.instance() or QApplication([])
    # The Windows offscreen platform does not discover system fonts itself.
    for name in ["segoeui.ttf", "segoeuib.ttf"]:
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont("Segoe UI", 9))
    yield app


@pytest.fixture(autouse=True)
def close_test_windows(tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    monkeypatch.setattr("pdflinker.app.QSettings", lambda *args: QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat))
    yield
    for window in QApplication.topLevelWidgets():
        if isinstance(window, MainWindow):
            window.dirty = False
            window.timer.stop()
            window.preview.render_timer.stop()
            window.close()


def test_ui_preview_edit_mapping_and_row_checks(tmp_path):
    app = QApplication.instance() or QApplication([])
    create(tmp_path)
    window = MainWindow()
    window.sheets.addItem("People")
    headers, rows = read_sheet(tmp_path / "people.xlsx", "People")
    window.template = Template(tmp_path / "employee_form.pdf")
    window.pages.addItem("1")
    window.set_data(headers, rows)
    window.links = auto_link(window.template.fields, headers, {})
    window.update_links()
    window.refresh_preview()
    assert len(window.links) == 5
    assert window.preview.scene().items()
    assert window.checked_rows() == []
    window.data_table.item(1, 0).setCheckState(Qt.CheckState.Checked)
    assert window.checked_rows() == [1]
    window.data_table.setCurrentCell(1, 1)
    window.data_table.item(1, 1).setText("Edited Person")
    window.refresh_preview()
    assert window.current_record()["Name"] == "Edited Person"
    assert "row 3" in window.preview_note.text()
    window.check_rows(True)
    assert window.checked_rows() == [0, 1, 2]
    window.check_rows(False)
    assert window.checked_rows() == []
    window.timer.stop()
    window.dirty = False
    window.close()
    app.processEvents()


def test_export_distinct_records_and_protect_existing_files(tmp_path):
    create(tmp_path)
    template = Template(tmp_path / "employee_form.pdf")
    headers, rows = read_sheet(tmp_path / "people.xlsx", "People")
    links = auto_link(template.fields, headers, {})
    jobs = [(tmp_path / f"out_{i}.pdf", dict(zip(headers, rows[i]))) for i in [0, 2]]
    worker = ExportWorker(template, links, jobs)
    results = []
    worker.result.connect(lambda count, error: results.append((count, error)))
    worker.run()
    assert results == [(2, "")]
    for i in [0, 2]:
        with fitz.open(tmp_path / f"out_{i}.pdf") as doc:
            assert list(doc[0].widgets())[0].field_value == rows[i][0]
    original = jobs[0][0].read_bytes()
    worker.run()
    assert results[-1][0] == 0 and results[-1][1]
    assert jobs[0][0].read_bytes() == original


def test_cancel_export_before_start(tmp_path):
    create(tmp_path)
    worker = ExportWorker(Template(tmp_path / "employee_form.pdf"), {}, [(tmp_path / "not_created.pdf", {})])
    worker.cancelled.set()
    worker.run()
    assert not (tmp_path / "not_created.pdf").exists()


def test_zoom_beyond_viewport_survives_scrollbars_resize_and_live_update(tmp_path):
    app = QApplication.instance() or QApplication([])
    create(tmp_path)
    preview = Preview()
    preview.resize(500, 600)
    preview.show()
    template = Template(tmp_path / "employee_form.pdf")
    preview.show_page(template.source, 0, template.fields, None, True)
    app.processEvents()
    initial = preview.transform().m11()
    preview.zoom_by(3)
    app.processEvents()
    zoomed = preview.transform().m11()
    assert zoomed == initial * 3
    assert preview.horizontalScrollBar().maximum() > 0
    assert preview.verticalScrollBar().maximum() > 0
    preview.horizontalScrollBar().setValue(120)
    preview.verticalScrollBar().setValue(200)
    center = preview.mapToScene(preview.viewport().rect().center())
    preview.show_page(template.source, 0, template.fields, None, True)
    app.processEvents()
    assert preview.transform().m11() == zoomed
    assert (preview.mapToScene(preview.viewport().rect().center()) - center).manhattanLength() < 3
    preview.resize(600, 650)
    app.processEvents()
    assert preview.transform().m11() == zoomed
    preview.fit_page()
    assert preview.transform().m11() < initial * 3
    preview.render_timer.stop()
    preview.close()


def test_flat_detection_in_ui_links_and_preview_dominates_layout(tmp_path):
    app = QApplication.instance() or QApplication([])
    create(tmp_path)
    window = MainWindow()
    window.sheets.addItem("People")
    window.template = Template(tmp_path / "employee_flat.pdf")
    window.pages.addItem("1")
    window.set_data(*read_sheet(tmp_path / "people.xlsx", "People"))
    window.detect_fields()
    window.show()
    app.processEvents()
    window.refresh_preview()
    assert len(window.template.fields) == 5
    assert len(window.links) == 5
    assert "5 detected" in window.pdf_label.text()
    assert window.preview.height() > window.height() * .55
    assert abs(window.workspace_split.sizes()[0] - window.workspace_split.sizes()[1]) <= 1
    assert not hasattr(window, "mapping_table")
    first = window.template.fields[0]
    window.select_field(first.key)
    assert window.field_card.isVisible()
    assert window.field_card.columns.currentData() == "Name"
    window.detect_fields()
    assert len(window.template.fields) == 5
    window.timer.stop()
    window.preview.render_timer.stop()
    window.dirty = False
    window.close()


def test_hover_link_unlink_and_outline_colors(tmp_path):
    app = QApplication.instance() or QApplication([])
    create(tmp_path)
    window = MainWindow()
    window.sheets.addItem("People")
    window.template = Template(tmp_path / "employee_form.pdf")
    window.pages.addItem("1")
    window.set_data(*read_sheet(tmp_path / "people.xlsx", "People"))
    window.show()
    app.processEvents()
    window.refresh_preview()
    field = window.template.fields[0]
    assert window.preview.outline_items[field.key].pen().color().name() == "#fb7185"
    rect = next(rect for rect, key in window.preview.boxes if key == field.key)
    position = window.preview.mapFromScene(rect.center())
    QTest.mouseMove(window.preview.viewport(), position)
    app.processEvents()
    assert window.field_card.isVisible()
    assert window.field_card.message.text() == "Field not linked. Use auto-link or choose column here."
    assert not window.field_card.unlink.isVisible()
    window.field_card.columns.setCurrentIndex(window.field_card.columns.findData("Name"))
    assert window.links[field.key] == "Name"
    window.refresh_preview()
    assert window.preview.outline_items[field.key].pen().color().name() == "#36d399"
    assert window.field_card.message.text() == "Linked to: Name"
    assert window.field_card.unlink.isVisible()
    QTest.mouseClick(window.field_card.unlink, Qt.MouseButton.LeftButton)
    assert field.key not in window.links
    window.refresh_preview()
    assert window.preview.outline_items[field.key].pen().color().name() == "#fb7185"
    window.outlines.setChecked(False)
    window.refresh_preview()
    assert not window.preview.outline_items
    window.timer.stop()
    window.preview.render_timer.stop()
    window.dirty = False
    window.close()


def test_portable_project_restores_inputs_edits_links_and_checked_rows(tmp_path):
    app = QApplication.instance() or QApplication([])
    create(tmp_path)
    window = MainWindow()
    window.sheet_path = tmp_path / "people.xlsx"
    window.spreadsheet_source_path = window.sheet_path.resolve()
    window.sheets.addItem("People")
    window.template = Template(tmp_path / "employee_flat.pdf")
    window.pages.addItem("1")
    window.set_data(*read_sheet(window.sheet_path, "People"))
    window.detect_fields()
    window.data_table.item(1, 1).setText("Edited name")
    window.data_table.item(1, 0).setCheckState(Qt.CheckState.Checked)
    window.data_table.setCurrentCell(1, 1)
    window.filename.setText("Employee_{row}_{Name}")
    window.project_path = tmp_path / "saved.pdflinker"
    assert window.save_project()
    assert not window.dirty
    # Delete the inputs to prove that reopening uses the embedded copies.
    window.sheet_path.unlink()
    window.template.path.unlink()
    restored = MainWindow()
    restored.open_project(window.project_path)
    assert restored.rows[1][0] == "Edited name"
    assert restored.checked_rows() == [1]
    assert restored.current_record()["Name"] == "Edited name"
    assert len(restored.links) == 5 and len(restored.template.fields) == 5
    assert restored.filename.text() == "Employee_{row}_{Name}"
    assert restored.sheet_path.exists()
    assert restored.spreadsheet_source_path == str((tmp_path / "people.xlsx").resolve())
    assert restored.save_project()
    from pdflinker.project import read_project
    assert read_project(window.project_path)[0]["spreadsheet_source_path"] == restored.spreadsheet_source_path
    assert read_sheet(restored.sheet_path, "People")[1][1][0] == "Jamie Patel"
    assert not restored.dirty
    data = restored.template.fill(restored.links, restored.current_record())
    with fitz.open(stream=data, filetype="pdf") as doc:
        assert "Edited name" in doc[0].get_text()
    for item in [window, restored]:
        item.timer.stop()
        item.preview.render_timer.stop()
        item.dirty = False
        item.close()


def test_toolbar_and_panel_buttons_fit_at_small_window_size():
    from PySide6.QtWidgets import QPushButton
    from pdflinker.ui import STYLE
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.setStyleSheet(STYLE)
    window.resize(1100, 760)
    window.show()
    app.processEvents()
    for button in window.findChildren(QPushButton):
        if button.isVisible() and button.text() not in {"+", "−"}:
            assert button.width() >= button.sizeHint().width(), button.text()
    assert window.data_table.height() > window.height() * .4
    assert window.export_menu.title() == "Export PDFs"
    assert [action.text() for action in window.menuBar().actions()] == ["File", "View", "Scripts", "Help"]
    assert window.menuBar().height() < 40
    assert abs(window.workspace_split.sizes()[0] - window.workspace_split.sizes()[1]) <= 1
    assert window.preview.height() > window.height() * .7
    assert window.pdf_controls.height() < 45
    assert not hasattr(window, "mapping_table")
    window.close()


def test_pdf_controls_wrap_with_spacing_and_no_status_bar():
    from PySide6.QtWidgets import QStatusBar, QToolButton
    from pdflinker.ui import STYLE
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.setStyleSheet(STYLE)
    window.show()
    app.processEvents()
    flow = window.pdf_controls.layout()
    assert len({flow.itemAt(i).geometry().y() for i in range(flow.count())}) == 1
    window.resize(800, 760)
    app.processEvents()
    assert len({flow.itemAt(i).geometry().y() for i in range(flow.count())}) >= 2
    previous = None
    for index in range(flow.count()):
        item = flow.itemAt(index)
        rect = item.geometry()
        assert item.widget().isVisible()
        assert window.pdf_controls.rect().contains(rect)
        if previous is not None:
            if rect.y() == previous.y():
                assert rect.left() - previous.right() - 1 >= 8
            else:
                assert rect.top() - previous.bottom() - 1 >= 6
        previous = rect
    assert not window.findChildren(QStatusBar)
    assert "Fit" not in [button.text() for button in window.pdf_controls.findChildren(QToolButton)]
    window.resize(1440, 940)
    app.processEvents()
    assert len({flow.itemAt(i).geometry().y() for i in range(flow.count())}) == 1
    window.close()


def test_create_job_dialog_and_scripts_menu_run_job(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog, QMessageBox
    from pdflinker.job_ui import CreateJobDialog
    from pdflinker.project import save_project
    from pdflinker.jobs import list_jobs
    app = QApplication.instance() or QApplication([])
    create(tmp_path)
    spreadsheet = tmp_path / "people.xlsx"
    template = Template(tmp_path / "employee_form.pdf")
    headers, rows = read_sheet(spreadsheet, "People")
    project = tmp_path / "job-project.pdflinker"
    save_project(project, template=template, spreadsheet_path=spreadsheet,
                 headers=headers, rows=rows, links=auto_link(template.fields, headers, {}),
                 checked=[], current_row=0, sheet="People", header_row=1, filename="Form_{row}")
    dialog = CreateJobDialog(tmp_path / "jobs", project)
    assert dialog.spreadsheet.text() == str(spreadsheet.resolve())
    dialog.start.setValue(3)
    dialog.output.setText(str(tmp_path / "out"))
    assert not dialog.regenerate_changed.isEnabled()
    dialog.naming_enabled.setChecked(True)
    dialog.filename_column.setCurrentText("Name")
    dialog.filename_prefix.setText("Staff_")
    dialog.filename_suffix.setText("_signed")
    dialog.identity_enabled.setChecked(True)
    dialog.identity_column.setCurrentText("Reference")
    dialog.regenerate_changed.setChecked(True)
    shortcuts = []
    monkeypatch.setattr("pdflinker.job_ui.create_desktop_shortcut", lambda path, name: shortcuts.append((path, name)))
    dialog.desktop_shortcut.setChecked(True)
    dialog.create()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert len(list_jobs(tmp_path / "jobs")) == 1
    assert shortcuts == [(dialog.job_path.parent / "Run job.bat", "job-project")]
    window = MainWindow()
    window.jobs_path = tmp_path / "jobs"
    window.refresh_scripts_menu()
    assert window.scripts_menu.actions()[0].text() == "job-project"
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    window.scripts_menu.actions()[0].trigger()
    assert window.job_worker.wait(10000)
    app.processEvents()
    assert messages and "Exported 2 new PDFs" in messages[0]
    assert len(list((tmp_path / "out").glob("*.pdf"))) == 2
    assert (tmp_path / "out" / "Staff_Jamie Patel_signed.pdf").is_file()
    window.close()


def test_hover_card_keeps_its_field_over_other_fields_and_open_dropdown(tmp_path):
    from PySide6.QtGui import QCursor
    app = QApplication.instance() or QApplication([])
    create(tmp_path)
    window = MainWindow()
    window.sheets.addItem("People")
    window.template = Template(tmp_path / "employee_form.pdf")
    window.pages.addItem("1")
    window.set_data(*read_sheet(tmp_path / "people.xlsx", "People"))
    window.show()
    app.processEvents()
    window.refresh_preview()
    first, second = window.template.fields[:2]
    window.select_field(first.key)
    card = window.field_card
    QCursor.setPos(card.mapToGlobal(card.rect().center()))
    assert card.testAttribute(Qt.WidgetAttribute.WA_NoMousePropagation)
    assert card.protects_pointer()
    second_rect = next(rect for rect, key in window.preview.boxes if key == second.key)
    window.hover_field(second.key, second_rect)
    window.select_field(second.key)
    window.hover_field("", None)
    assert card.field_key == first.key and not card.hide_timer.isActive()
    card.columns.showPopup()
    QCursor.setPos(window.mapToGlobal(window.rect().topLeft()))
    window.hover_field(second.key, second_rect)
    assert card.field_key == first.key
    card.columns.setCurrentIndex(card.columns.findData("Name"))
    card.columns.hidePopup()
    assert window.links[first.key] == "Name" and second.key not in window.links
    window.hover_field(second.key, second_rect)
    assert card.field_key == second.key
    window.dirty = False
    window.close()


def test_recent_projects_persist_deduplicate_and_open_from_menu(tmp_path):
    first = MainWindow()
    first.project_path = tmp_path / "first.pdflinker"
    assert first.save_project()
    first.project_path = tmp_path / "second.pdflinker"
    assert first.save_project()
    second = MainWindow()
    assert second.recent_project_paths() == [tmp_path / "second.pdflinker", tmp_path / "first.pdflinker"]
    # The menu opens the project through the normal workspace / unsaved-change path.
    second.refresh_recent_menu()
    second.recent_menu.actions()[1].trigger()
    assert second.project_path == tmp_path / "first.pdflinker"
    assert second.recent_project_paths() == [tmp_path / "first.pdflinker", tmp_path / "second.pdflinker"]
    second.save_project()
    assert len(second.recent_project_paths()) == 2
    second.clear_recent_projects()
    assert MainWindow().recent_project_paths() == []
    assert (tmp_path / "first.pdflinker").exists() and (tmp_path / "second.pdflinker").exists()
    first.close()
    second.close()


def test_recent_limit_and_failed_or_cancelled_open_does_not_change_history(tmp_path, monkeypatch):
    window = MainWindow()
    window.project_path = tmp_path / "valid.pdflinker"
    window.save_project()
    for index in range(12):
        window.remember_project(tmp_path / f"project-{index}.pdflinker")
    before = window.recent_project_paths()
    assert len(before) == 10 and before[0].name == "project-11.pdflinker"
    window.refresh_recent_menu()
    messages = []
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args[2]))
    window.recent_menu.actions()[0].trigger()
    assert messages and window.recent_project_paths() == before
    assert window.project_path == tmp_path / "valid.pdflinker"
    monkeypatch.setattr(window, "confirm_discard", lambda: False)
    window.open_project(tmp_path / "valid.pdflinker")
    assert window.recent_project_paths() == before
    monkeypatch.setattr(window, "confirm_discard", lambda: True)
    window.close()
