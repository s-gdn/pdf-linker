import json
import zipfile

import pytest

from pdflinker.project import read_project, save_project


def test_empty_project_can_be_saved_and_reopened(tmp_path):
    path = tmp_path / "empty.pdflinker"
    save_project(path, template=None, spreadsheet_path=None, headers=[], rows=[], links={},
                 checked=[], current_row=-1, sheet="", header_row=1, filename="Form_{row}")
    manifest, template, links, spreadsheet, warnings = read_project(path)
    assert manifest["rows"] == []
    assert template is None and spreadsheet is None
    assert not links and not warnings


def test_failed_save_preserves_existing_project(tmp_path):
    path = tmp_path / "existing.pdflinker"
    path.write_bytes(b"existing data")
    with pytest.raises(FileNotFoundError):
        save_project(path, template=None, spreadsheet_path=tmp_path / "missing.xlsx", headers=[],
                     rows=[], links={}, checked=[], current_row=-1, sheet="", header_row=1, filename="Form_{row}")
    assert path.read_bytes() == b"existing data"
    assert not list(tmp_path.glob(".pdf-linker-*.tmp"))


def test_invalid_project_data_rejected_before_changing_workspace(tmp_path):
    path = tmp_path / "invalid.pdflinker"
    payload = {"format": "pdf-linker-project", "version": 1, "headers": ["Name"], "rows": [["Alex", "extra"]]}
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("project.json", json.dumps(payload))
    with pytest.raises(ValueError, match="spreadsheet data"):
        read_project(path)
