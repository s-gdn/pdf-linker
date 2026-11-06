"""Portable project snapshots: inputs, edits, mappings and generation settings."""
import json
import os
from pathlib import Path
import tempfile
import zipfile

from .core import Template, profile_data, restore_profile


def save_project(path: Path, *, template, spreadsheet_path, headers, rows, links,
                 checked, current_row, sheet, header_row, filename, outlines=True,
                 spreadsheet_source_path=None, row_values=None):
    manifest = {
        "format": "pdf-linker-project", "version": 1,
        "headers": headers, "rows": rows, "checked": checked, "current_row": current_row,
        "sheet": sheet, "header_row": header_row, "filename": filename, "outlines": outlines,
        "row_values": {str(row): values for row, values in (row_values or {}).items() if values},
        "pdf_name": template.path.name if template else None,
        "profile": profile_data(template, links) if template else None,
        "spreadsheet_name": spreadsheet_path.name if spreadsheet_path else None,
        "spreadsheet_source_path": (str(spreadsheet_source_path) or None) if spreadsheet_source_path is not None
        else str(Path(spreadsheet_path).resolve()) if spreadsheet_path else None,
    }
    descriptor, temporary = tempfile.mkstemp(prefix=".pdf-linker-", suffix=".tmp", dir=path.parent)
    os.close(descriptor)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("project.json", json.dumps(manifest, ensure_ascii=False))
            if template:
                archive.writestr("template.pdf", template.source)
            if spreadsheet_path:
                archive.writestr("spreadsheet", Path(spreadsheet_path).read_bytes())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_project(path: Path):
    with zipfile.ZipFile(path) as archive:
        if sum(info.file_size for info in archive.infolist()) > 512 * 1024 * 1024:
            raise ValueError("This project is too large to load (maximum 512 MB uncompressed).")
        manifest = json.loads(archive.read("project.json"))
        if manifest.get("format") != "pdf-linker-project" or manifest.get("version") != 1:
            raise ValueError("This is not a supported PDF Linker project.")
        headers, rows = manifest.get("headers"), manifest.get("rows")
        if (not isinstance(headers, list) or any(not isinstance(h, str) for h in headers)
                or len(set(headers)) != len(headers) or not isinstance(rows, list)
                or any(not isinstance(row, list) or len(row) != len(headers)
                       or any(not isinstance(cell, str) for cell in row) for row in rows)):
            raise ValueError("The project contains invalid spreadsheet data.")
        if (not isinstance(manifest.get("checked"), list)
                or any(type(i) is not int or not 0 <= i < len(rows) for i in manifest["checked"])
                or type(manifest.get("current_row")) is not int
                or not -1 <= manifest["current_row"] < max(1, len(rows))
                or type(manifest.get("header_row")) is not int or not 1 <= manifest["header_row"] <= 100000
                or not isinstance(manifest.get("filename"), str) or not isinstance(manifest.get("sheet"), str)):
            raise ValueError("The project contains invalid generation settings.")
        template, links, warnings = None, {}, []
        if manifest.get("pdf_name"):
            template = Template(Path(manifest["pdf_name"]).name, archive.read("template.pdf"))
            links, warnings = restore_profile(manifest["profile"], template, headers)
        row_values = manifest.get("row_values", {})
        field_keys = {field.key for field in template.fields} if template else set()
        if (not isinstance(row_values, dict) or any(not isinstance(key, str) or not key.isdecimal()
                or not 0 <= int(key) < len(rows) or not isinstance(values, dict)
                or any(field_key not in field_keys or not isinstance(value, str) for field_key, value in values.items())
                for key, values in row_values.items())):
            raise ValueError("The project contains invalid row-specific manual values.")
        spreadsheet = archive.read("spreadsheet") if manifest.get("spreadsheet_name") else None
        if spreadsheet is not None:
            name = Path(manifest["spreadsheet_name"]).name
            if Path(name).suffix.lower() not in {".xlsx", ".xls", ".csv"}:
                raise ValueError("The project contains an unsupported spreadsheet format.")
            manifest["spreadsheet_name"] = name
        return manifest, template, links, spreadsheet, warnings
