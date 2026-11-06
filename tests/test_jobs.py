import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pymupdf as fitz
from openpyxl import load_workbook
import pytest

from examples.create_examples import create
from pdflinker.core import Template, auto_link, read_sheet
from pdflinker.jobs import create_desktop_shortcut, create_job, job_lock, list_jobs, run_job
from pdflinker.project import read_project, save_project


@pytest.fixture
def setup(tmp_path):
    create(tmp_path)
    spreadsheet = tmp_path / "people.xlsx"
    template = Template(tmp_path / "employee_form.pdf")
    headers, rows = read_sheet(spreadsheet, "People")
    project = tmp_path / "saved.pdflinker"
    save_project(project, template=template, spreadsheet_path=spreadsheet,
                 headers=headers, rows=rows, links=auto_link(template.fields, headers, {}),
                 checked=[], current_row=0, sheet="People", header_row=1, filename="Employee_{row}_{Name}")
    return tmp_path, project, spreadsheet


def make_job(setup, start=2):
    root, project, spreadsheet = setup
    return create_job(directory=root / "jobs", name="Employee exports", project=project,
                      spreadsheet=spreadsheet, start_row=start, output=root / "output")


def append(spreadsheet, row):
    book = load_workbook(spreadsheet)
    book["People"].append(row)
    book.save(spreadsheet)
    book.close()


def history(path):
    return json.loads((path.parent / "history.json").read_text(encoding="utf-8"))


def test_job_exports_only_new_rows_and_uses_frozen_project(setup):
    root, project, spreadsheet = setup
    path = make_job(setup)
    assert list_jobs(root / "jobs") == [("Employee exports", path)]
    assert run_job(path)["exported"] == 3
    first = {p.name: p.read_bytes() for p in (root / "output").glob("*.pdf")}
    project.unlink()
    append(spreadsheet, ["New Person", "new@example.com", "IT", "REF-004", "Yes"])
    result = run_job(path)
    assert result["exported"] == 1 and result["skipped"] == 3
    for name, data in first.items():
        assert (root / "output" / name).read_bytes() == data
    with fitz.open(root / "output" / "Employee_5_New Person.pdf") as doc:
        assert "New Person" in doc[0].get_text()
    assert set(history(path)["completed"]) == {"2", "3", "4", "5"}
    assert run_job(path)["exported"] == 0
    assert (path.parent / "run.log").exists()


def test_start_row_is_physical_and_identical_new_records_are_distinct(setup):
    _, _, spreadsheet = setup
    path = make_job(setup, start=4)
    assert run_job(path)["exported"] == 1
    append(spreadsheet, ["Sam Taylor", "sam@example.com", "People", "REF-003", "Yes"])
    assert run_job(path)["exported"] == 1
    assert set(history(path)["completed"]) == {"4", "5"}


def test_blank_rows_not_completed_and_can_be_filled_later(setup):
    _, _, spreadsheet = setup
    book = load_workbook(spreadsheet)
    book["People"].cell(6, 1, "New")
    book.save(spreadsheet)
    book.close()
    path = make_job(setup, start=5)
    result = run_job(path)
    assert result["exported"] == 1 and result["blank"] == 1
    assert set(history(path)["completed"]) == {"6"}
    book = load_workbook(spreadsheet)
    book["People"]["A5"] = "Previously blank"
    book.save(spreadsheet)
    book.close()
    assert run_job(path)["exported"] == 1


def test_completed_rows_cannot_be_silently_replaced(setup):
    root, _, spreadsheet = setup
    path = make_job(setup)
    run_job(path)
    book = load_workbook(spreadsheet)
    book["People"]["A2"] = "Changed name"
    book["People"].append(["New", "", "", "", ""])
    book.save(spreadsheet)
    book.close()
    with pytest.raises(ValueError, match="Completed spreadsheet row 2"):
        run_job(path)
    assert len(list((root / "output").glob("*.pdf"))) == 3


def test_existing_files_are_not_guessed_as_completed(setup):
    root, _, _ = setup
    path = make_job(setup)
    (root / "output").mkdir()
    collision = root / "output" / "Employee_2_Alex Morgan.pdf"
    collision.write_bytes(b"Existing file")
    with pytest.raises(ValueError, match="already used"):
        run_job(path)
    assert collision.read_bytes() == b"Existing file"
    assert not history(path)["completed"]


def test_failed_pdf_row_can_retry_without_repeating_successes(setup, monkeypatch):
    path = make_job(setup)
    original = Template.fill
    def fill(self, links, record):
        if record["Name"] == "Jamie Patel":
            raise ValueError("Simulated failure")
        return original(self, links, record)
    monkeypatch.setattr(Template, "fill", fill)
    with pytest.raises(ValueError, match="Simulated"):
        run_job(path)
    assert set(history(path)["completed"]) == {"2"}
    monkeypatch.setattr(Template, "fill", original)
    assert run_job(path)["exported"] == 2


def test_checkpoint_recovery_after_pdf_saved_but_before_commit(setup, monkeypatch):
    import pdflinker.jobs as jobs
    path = make_job(setup)
    original = jobs.atomic_json
    failed = False
    def save(target, value):
        nonlocal failed
        if "2" in value.get("completed", {}) and value.get("pending") is None and not failed:
            failed = True
            raise OSError("Checkpoint interrupted")
        return original(target, value)
    monkeypatch.setattr(jobs, "atomic_json", save)
    with pytest.raises(OSError, match="interrupted"):
        run_job(path)
    assert history(path)["pending"]["row"] == "2"
    monkeypatch.setattr(jobs, "atomic_json", original)
    result = run_job(path)
    assert result["exported"] == 2 and result["skipped"] == 1
    assert history(path)["pending"] is None


def test_lock_cancel_and_missing_history(setup):
    path = make_job(setup)
    with job_lock(path.parent):
        with pytest.raises(ValueError, match="already running"):
            run_job(path)
    cancelled = threading.Event()
    cancelled.set()
    result = run_job(path, cancelled=cancelled)
    assert result["cancelled"] and result["exported"] == 0
    (path.parent / "history.json").unlink()
    with pytest.raises(ValueError, match="history is missing"):
        run_job(path)


def test_live_file_source_preserved_in_project_and_cli_runs(setup):
    _, project, spreadsheet = setup
    manifest, *_ = read_project(project)
    assert manifest["spreadsheet_source_path"] == str(spreadsheet.resolve())
    path = make_job(setup)
    result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "launcher.py"),
                             "--run-job", str(path)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "Exported 3 new PDFs" in result.stdout
    assert len(history(path)["completed"]) == 3
    batch = (path.parent / "Run job.bat").read_text(encoding="utf-8")
    assert '--run-job "%~dp0job.json"' in batch
    assert "--interactive" in batch


def test_missing_column_or_live_file_stops_job(setup):
    _, _, spreadsheet = setup
    path = make_job(setup)
    book = load_workbook(spreadsheet)
    book["People"]["A1"] = "Renamed column"
    book.save(spreadsheet)
    book.close()
    with pytest.raises(ValueError, match="missing linked columns"):
        run_job(path)
    spreadsheet.unlink()
    with pytest.raises(ValueError, match="not found"):
        run_job(path)


@pytest.mark.skipif(os.name != "nt", reason="Windows shortcuts")
def test_desktop_shortcuts_are_real_and_do_not_overwrite(tmp_path):
    launcher = tmp_path / "Run job.bat"
    launcher.write_text("@echo off\n", encoding="utf-8")
    # Use a temporary desktop so this test never writes to the user's desktop.
    first = create_desktop_shortcut(launcher, "Test José & $name", desktop=tmp_path)
    original = first.read_bytes()
    second = create_desktop_shortcut(launcher, "Test José & $name", desktop=tmp_path)
    assert first.is_file() and second.is_file() and first != second
    assert first.read_bytes() == original
    assert first.stat().st_size > 0


def keyed_job(setup, **options):
    root, project, spreadsheet = setup
    return create_job(directory=root / "jobs", name="Tracked records", project=project,
                      spreadsheet=spreadsheet, start_row=options.pop("start_row", 2),
                      output=root / "output", identity_column="Reference", **options)


def test_unique_ids_survive_deletions_moves_and_start_row_boundary(setup):
    root, _, spreadsheet = setup
    path = keyed_job(setup, start_row=3)
    assert run_job(path)["exported"] == 2
    original = {p.name: p.read_bytes() for p in (root / "output").glob("*.pdf")}
    book = load_workbook(spreadsheet)
    book["People"].delete_rows(2)  # A completed record now moves above the start row.
    book["People"].append(["New", "new@example.com", "IT", "REF-004", "Yes"])
    book.save(spreadsheet)
    book.close()
    result = run_job(path)
    assert result["exported"] == 1 and result["skipped"] == 2 and result["deleted"] == 0
    book = load_workbook(spreadsheet)
    book["People"].delete_rows(2)  # Delete a completed ID, then append another record.
    book["People"].append(["Another", "", "", "REF-005", "No"])
    book.save(spreadsheet)
    book.close()
    result = run_job(path)
    assert result["exported"] == 1 and result["deleted"] == 1
    for name, data in original.items():
        assert (root / "output" / name).read_bytes() == data
    assert set(history(path)["completed"]) == {"id:REF-002", "id:REF-003", "id:REF-004", "id:REF-005"}


def test_column_naming_changed_rows_and_revisions(setup):
    root, _, spreadsheet = setup
    path = keyed_job(setup, naming={"column": "Name", "prefix": "Staff_", "suffix": "_signed"}, regenerate_changed=True)
    assert run_job(path)["exported"] == 3
    original = root / "output" / "Staff_Alex Morgan_signed.pdf"
    data = original.read_bytes()
    book = load_workbook(spreadsheet)
    book["People"]["C2"] = "Changed department"
    book.save(spreadsheet)
    book.close()
    result = run_job(path)
    assert result["exported"] == 1 and result["updated"] == 1
    assert original.read_bytes() == data
    revised = root / "output" / "Staff_Alex Morgan_signed (revision 2).pdf"
    with fitz.open(revised) as doc:
        assert "Changed department" in doc[0].get_text()
    entry = history(path)["completed"]["id:REF-001"]
    assert entry["revision"] == 2 and entry["previous_outputs"] == [str(original)]
    assert run_job(path)["exported"] == 0


def test_changed_rows_ignored_when_disabled_while_new_records_continue(setup):
    _, _, spreadsheet = setup
    path = keyed_job(setup)
    run_job(path)
    book = load_workbook(spreadsheet)
    book["People"]["A2"] = "Updated name"
    book["People"].append(["New", "", "", "REF-004", ""])
    book.save(spreadsheet)
    book.close()
    result = run_job(path)
    assert result["exported"] == 1 and result["changed_ignored"] == 1 and result["updated"] == 0
    assert run_job(path)["exported"] == 0


@pytest.mark.parametrize("value, message", [("REF-001", "Duplicate unique ID"), (None, "Unique ID is blank")])
def test_invalid_record_ids_stop_before_export(setup, value, message):
    root, _, spreadsheet = setup
    path = keyed_job(setup)
    book = load_workbook(spreadsheet)
    book["People"]["D3"] = value
    book.save(spreadsheet)
    book.close()
    with pytest.raises(ValueError, match=message):
        run_job(path)
    assert not list((root / "output").glob("*.pdf"))
    assert not history(path)["completed"]


def test_duplicate_column_names_get_distinct_files_and_literal_prefix(setup):
    root, _, spreadsheet = setup
    book = load_workbook(spreadsheet)
    book["People"]["A2"] = book["People"]["A3"] = "Same"
    book.save(spreadsheet)
    book.close()
    path = keyed_job(setup, naming={"column": "Name", "prefix": "{literal}_", "suffix": ""})
    assert run_job(path)["exported"] == 3
    assert (root / "output" / "{literal}_Same.pdf").is_file()
    assert (root / "output" / "{literal}_Same (2).pdf").is_file()


def test_revision_checkpoint_recovery_preserves_history(setup, monkeypatch):
    import pdflinker.jobs as jobs
    _, _, spreadsheet = setup
    path = keyed_job(setup, regenerate_changed=True)
    run_job(path)
    book = load_workbook(spreadsheet)
    book["People"]["A2"] = "Edited"
    book.save(spreadsheet)
    book.close()
    original = jobs.atomic_json
    def interrupted(target, value):
        if value.get("completed", {}).get("id:REF-001", {}).get("revision") == 2 and not value.get("pending"):
            raise OSError("Interrupted revision checkpoint")
        return original(target, value)
    monkeypatch.setattr(jobs, "atomic_json", interrupted)
    with pytest.raises(OSError, match="Interrupted"):
        run_job(path)
    assert history(path)["pending"]["key"] == "id:REF-001"
    monkeypatch.setattr(jobs, "atomic_json", original)
    assert run_job(path)["exported"] == 0
    assert history(path)["completed"]["id:REF-001"]["revision"] == 2
    assert len(history(path)["completed"]["id:REF-001"]["previous_outputs"]) == 1


def test_legacy_version_one_jobs_remain_compatible(setup):
    from pdflinker.jobs import atomic_json, json_digest
    path = make_job(setup)
    config = json.loads(path.read_text())
    for key in ["identity_column", "naming", "regenerate_changed"]:
        config.pop(key)
    config["version"] = 1
    atomic_json(path, config)
    state = history(path)
    state["job_sha256"] = json_digest(config)
    atomic_json(path.parent / "history.json", state)
    assert run_job(path)["exported"] == 3
    assert run_job(path)["exported"] == 0
