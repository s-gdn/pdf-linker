"""Persistent spreadsheet export jobs, with optional stable record identities."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import subprocess
import tempfile
import uuid

from .core import output_name, read_sheet
from .project import read_project


def jobs_directory() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "PDFLinker" / "jobs"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_digest(value) -> str:
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def atomic_json(path: Path, value):
    descriptor, temporary = tempfile.mkstemp(prefix=".saving-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def runtime_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve())]
    # A generated launcher does not depend on the caller's working directory.
    # The source launcher inserts the application directory into sys.path.
    return [str(Path(sys.executable).resolve()), str(Path(__file__).resolve().parent.parent / "launcher.py")]


def create_job(*, directory: Path, name: str, project: Path, spreadsheet: Path,
               start_row: int, output: Path, command=None, naming=None,
               identity_column=None, regenerate_changed=False) -> Path:
    project, spreadsheet, output = Path(project).resolve(), Path(spreadsheet).resolve(), Path(output).resolve()
    manifest, template, links, _, warnings = read_project(project)
    if not template or not links or not manifest["spreadsheet_name"]:
        raise ValueError("Choose a saved project with a PDF, a spreadsheet, and at least one field link.")
    if warnings:
        raise ValueError("Fix and save the project's links before creating a job: " + " ".join(warnings))
    if type(start_row) is not int or start_row <= manifest["header_row"]:
        raise ValueError(f"Start at a physical spreadsheet row after header row {manifest['header_row']}.")
    headers, _ = read_sheet(spreadsheet, manifest["sheet"], manifest["header_row"])
    missing = set(links.values()) - set(headers)
    if missing:
        raise ValueError("Live spreadsheet is missing linked columns: " + ", ".join(sorted(missing)))
    validate_options(headers, naming, identity_column, regenerate_changed)
    name = name.strip()
    if not name:
        raise ValueError("Give the job a name.")
    slug = re.sub(r"[^\w-]+", "-", name).strip("-")[:60] or "job"
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    folder = directory / (slug + "-" + uuid.uuid4().hex[:10])
    folder.mkdir()
    try:
        source = project.read_bytes()
        (folder / "project.pdflinker").write_bytes(source)
        config = {"format": "pdf-linker-job", "version": 2, "name": name,
                  "spreadsheet": str(spreadsheet), "start_row": start_row,
                  "output": str(output), "project_sha256": digest(source),
                  "naming": naming, "identity_column": identity_column,
                  "regenerate_changed": bool(regenerate_changed)}
        atomic_json(folder / "job.json", config)
        atomic_json(folder / "history.json", {"version": 1, "job_sha256": json_digest(config),
                                              "completed": {}, "pending": None})
        # Paths are arguments, never executable text taken from spreadsheet cells.
        # Disable delayed expansion and escape percent signs in fixed batch paths.
        args = command if command is not None else runtime_command()
        if not args or any('"' in str(arg) or "\n" in str(arg) or "\r" in str(arg) for arg in args):
            raise ValueError("The application command contains an unsupported path.")
        invocation = " ".join('"' + str(arg).replace("%", "%%") + '"' for arg in args)
        batch = ('@echo off\r\nsetlocal DisableDelayedExpansion\r\nchcp 65001 >nul\r\n' + invocation +
                 ' --run-job "%~dp0job.json" --interactive\r\nexit /b %errorlevel%\r\n')
        (folder / "Run job.bat").write_bytes(batch.encode("utf-8"))
        return folder / "job.json"
    except BaseException:
        # Delete only the files created in this exclusively owned directory.
        for filename in ("job.json", "history.json", "project.pdflinker", "Run job.bat"):
            (folder / filename).unlink(missing_ok=True)
        folder.rmdir()
        raise


def list_jobs(directory: Path) -> list[tuple[str, Path]]:
    result = []
    for path in Path(directory).glob("*/job.json"):
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
            if config.get("format") == "pdf-linker-job" and isinstance(config.get("name"), str):
                result.append((config["name"], path))
        except (OSError, ValueError):
            continue
    return sorted(result, key=lambda item: (item[0].casefold(), str(item[1])))


def validate_options(headers, naming, identity_column, regenerate_changed):
    if identity_column is not None and identity_column not in headers:
        raise ValueError(f"Unique ID column is missing: {identity_column}")
    if regenerate_changed and not identity_column:
        raise ValueError("Choose a unique ID column to reliably track changed records.")
    if naming is not None:
        if (not isinstance(naming, dict) or naming.get("column") not in headers
                or not isinstance(naming.get("prefix", ""), str)
                or not isinstance(naming.get("suffix", ""), str)):
            raise ValueError("Choose an available column and valid prefix/suffix for PDF filenames.")


def create_desktop_shortcut(launcher: Path, name: str, desktop: Path | None = None) -> Path:
    """Create a Windows shortcut, respecting a redirected / OneDrive Desktop."""
    if os.name != "nt":
        raise ValueError("Desktop shortcuts are supported on Windows.")
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")[:100] or "Job"
    payload = {"target": str(Path(launcher).resolve()), "name": "PDF Linker - " + safe_name,
               "icon": str(Path(__file__).with_name("assets") / "icon.ico"),
               "desktop": str(Path(desktop).resolve()) if desktop else None}
    encoded = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
    # Job names and paths are encoded data, not interpolated PowerShell code.
    script = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$data = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('PAYLOAD')) | ConvertFrom-Json
$shell = New-Object -ComObject WScript.Shell
$desktopPath = if ($data.desktop) { $data.desktop } else { $shell.SpecialFolders.Item('Desktop') }
$linkPath = Join-Path $desktopPath ($data.name + '.lnk')
$counter = 2
while (Test-Path -LiteralPath $linkPath) {
    $linkPath = Join-Path $desktopPath ($data.name + ' (' + $counter + ').lnk')
    $counter++
}
$shortcut = $shell.CreateShortcut($linkPath)
$shortcut.TargetPath = $data.target
$shortcut.WorkingDirectory = [IO.Path]::GetDirectoryName($data.target)
$shortcut.Description = 'Run saved PDF Linker export job'
if (Test-Path -LiteralPath $data.icon) { $shortcut.IconLocation = $data.icon }
$shortcut.Save()
[Console]::WriteLine($linkPath)
""".replace("PAYLOAD", encoded)
    command = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", command],
                            capture_output=True, encoding="utf-8", errors="replace", timeout=30,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise ValueError("Unable to create the desktop shortcut: " + result.stderr.strip())
    path = Path(result.stdout.strip())
    if not path.is_file():
        raise ValueError("Windows did not create the desktop shortcut.")
    return path


@contextmanager
def job_lock(folder: Path):
    with (folder / "run.lock").open("a+b") as stream:
        if not stream.tell():
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError("This job is already running. Wait for it to finish.") from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def run_job(path: Path, progress=None, cancelled=None) -> dict:
    path = Path(path).resolve()
    with job_lock(path.parent):
        try:
            result = _run_job(path, progress, cancelled)
        except Exception as error:
            _log(path.parent, "ERROR: " + str(error))
            raise
        _log(path.parent, f"Exported {result['exported']}; already completed {result['skipped']}; "
                         f"blank rows {result['blank']}; updated {result['updated']}; "
                         f"changed ignored {result['changed_ignored']}; deleted {result['deleted']}; cancelled {result['cancelled']}.")
        return result


def _log(folder, message):
    with (folder / "run.log").open("a", encoding="utf-8") as stream:
        stream.write(datetime.now(timezone.utc).isoformat() + " " + message + "\n")


def _run_job(path, progress, cancelled):
    folder = path.parent
    config = json.loads(path.read_text(encoding="utf-8"))
    if (config.get("format") != "pdf-linker-job" or config.get("version") not in (1, 2)
            or type(config.get("start_row")) is not int or config["start_row"] < 1):
        raise ValueError("This is not a supported job configuration.")
    history_path = folder / "history.json"
    if not history_path.exists():
        raise ValueError("Job history is missing. Restore it or create a new job; completion records cannot be guessed.")
    history = json.loads(history_path.read_text(encoding="utf-8"))
    if (history.get("version") != 1 or history.get("job_sha256") != json_digest(config)
            or not isinstance(history.get("completed"), dict)):
        raise ValueError("Job settings or history have changed. Restore them or create a new job.")
    snapshot = folder / "project.pdflinker"
    if digest(snapshot.read_bytes()) != config["project_sha256"]:
        raise ValueError("The job's saved project has changed. Create a new job for the updated project.")
    manifest, template, links, _, warnings = read_project(snapshot)
    if warnings or template is None or not links:
        raise ValueError("The job's project does not have valid PDF field links.")
    source = Path(config["spreadsheet"])
    if not source.is_file():
        raise ValueError(f"Live spreadsheet not found: {source}")
    headers, rows = read_sheet(source, manifest["sheet"], manifest["header_row"])
    missing = set(links.values()) - set(headers)
    if missing:
        raise ValueError("Live spreadsheet is missing linked columns: " + ", ".join(sorted(missing)))
    identity_column = config.get("identity_column")
    naming = config.get("naming")
    regenerate = config.get("regenerate_changed", False)
    validate_options(headers, naming, identity_column, regenerate)
    records, blank = {}, 0
    for index, cells in enumerate(rows):
        number = str(index + manifest["header_row"] + 1)
        record = dict(zip(headers, cells))
        empty = not any(value.strip() for value in cells)
        if empty and int(number) >= config["start_row"]:
            blank += 1
        if identity_column:
            if empty:
                continue
            identity = record[identity_column].strip()
            if not identity:
                raise ValueError(f"Unique ID is blank in spreadsheet row {number}. Every record needs a stable ID.")
            key = "id:" + identity
            if key in records:
                raise ValueError(f"Duplicate unique ID '{identity}' in rows {records[key][0]} and {number}.")
        else:
            if int(number) < config["start_row"]:
                continue
            key = number
        records[key] = (number, record)
    completed = history["completed"]
    # A durable intent allows recovery if the process stops after PDF creation
    # but before the completion checkpoint is committed.
    pending = history.get("pending")
    if pending:
        target = Path(pending["output"])
        if target.exists():
            if digest(target.read_bytes()) != pending["pdf_sha256"]:
                raise ValueError(f"An incomplete or conflicting PDF needs attention: {target}. Remove it to retry this row.")
            completed[pending.get("key", pending["row"])] = {key: value for key, value in pending.items() if key != "key"}
        history["pending"] = None
        atomic_json(history_path, history)
    deleted = len(set(completed) - set(records)) if identity_column else 0
    if identity_column:
        # Freeze the initial start-row exclusion by ID, not by position. Later
        # insertions / deletions can move records across that original boundary.
        excluded = set(history.get("excluded_ids", [key for key, (number, _) in records.items()
                                                   if int(number) < config["start_row"]]))
        records = {key: value for key, value in records.items() if key not in excluded}
    else:
        for key, entry in completed.items():
            if key not in records or json_digest(records[key][1]) != entry["record_sha256"]:
                raise ValueError(f"Completed spreadsheet row {key} has changed or been removed. "
                                 "This job uses row numbers. Create a job with a unique ID column to handle edits and deletions.")
    output = Path(config["output"])
    output.mkdir(parents=True, exist_ok=True)
    used = {Path(filename).name.casefold() for entry in completed.values()
            for filename in [entry["output"], *entry.get("previous_outputs", [])]}
    work, skipped, ignored = [], 0, 0
    for key, (number, record) in records.items():
        previous = completed.get(key)
        if previous:
            if previous["record_sha256"] == json_digest(record):
                skipped += 1
                continue
            if not regenerate:
                ignored += 1
                continue
        if not any(value.strip() for value in record.values()):
            continue
        if naming:
            value = record[naming["column"]].strip()
            if not value:
                raise ValueError(f"Filename column '{naming['column']}' is empty in row {number}.")
            # Prefix/suffix are literal text; braces in them are not expressions.
            name = output_name("{value}", {"value": naming.get("prefix", "") + value + naming.get("suffix", "")}, int(number))
        else:
            name = output_name(manifest["filename"], record, int(number))
        revision = previous.get("revision", 1) + 1 if previous else 1
        if revision > 1:
            name = name[:-4] + f" (revision {revision}).pdf"
        if name.casefold() in used or (output / name).exists():
            if not naming and not identity_column:
                raise ValueError(f"Output filename already used: {name}. No files were overwritten. "
                                 "Use a project filename pattern containing {row} for unique filenames.")
            base, counter = name[:-4], 2
            while name.casefold() in used or (output / name).exists():
                name = f"{base[:160]} ({counter}).pdf"
                counter += 1
        used.add(name.casefold())
        work.append((key, number, record, output / name, revision, previous))
    if identity_column and "excluded_ids" not in history:
        history["excluded_ids"] = sorted(excluded)
        atomic_json(history_path, history)
    result = {"exported": 0, "skipped": skipped, "blank": blank, "cancelled": False,
              "updated": 0, "changed_ignored": ignored, "deleted": deleted}
    if progress:
        progress(0, len(work))
    for key, number, record, target, revision, previous in work:
        if cancelled and cancelled.is_set():
            result["cancelled"] = True
            break
        data = template.fill(links, record)
        entry = {"key": key, "row": number, "record_sha256": json_digest(record), "output": str(target),
                 "pdf_sha256": digest(data), "completed_at": datetime.now(timezone.utc).isoformat(),
                 "revision": revision, "previous_outputs": [*previous.get("previous_outputs", []), previous["output"]] if previous else []}
        history["pending"] = entry
        atomic_json(history_path, history)
        # Exclusive create also handles a file appearing after the preflight.
        try:
            stream = target.open("xb")
        except FileExistsError:
            history["pending"] = None
            atomic_json(history_path, history)
            raise ValueError(f"Output file appeared during export: {target}. It was not overwritten.")
        with stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        completed[key] = {name: value for name, value in entry.items() if name != "key"}
        history["pending"] = None
        atomic_json(history_path, history)
        result["exported"] += 1
        result["updated"] += int(revision > 1)
        if progress:
            progress(result["exported"], len(work))
    return result


def result_message(result):
    message = f"Exported {result['exported']} new PDFs. Already completed: {result['skipped']}."
    if result.get("updated"):
        message += f"\nUpdated records: {result['updated']} (previous PDFs retained)."
    if result.get("changed_ignored"):
        message += f"\nChanged records skipped: {result['changed_ignored']} (change exports disabled)."
    if result.get("deleted"):
        message += f"\nPreviously exported records absent from the sheet: {result['deleted']}. Their PDFs are retained."
    return message


def command_line(argv):
    import argparse
    parser = argparse.ArgumentParser(description="Export unprocessed spreadsheet rows for a PDF Linker job.")
    parser.add_argument("--run-job", required=True, type=Path)
    parser.add_argument("--interactive", action="store_true")
    options = parser.parse_args(argv)
    try:
        result = run_job(options.run_job)
        message = result_message(result)
        success = True
    except Exception as error:
        message, success = str(error), False
    if sys.stdout:
        print(message)
    if options.interactive:
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication([])
        if success:
            QMessageBox.information(None, "PDF Linker job complete", message)
        else:
            QMessageBox.warning(None, "PDF Linker job stopped", message)
    return 0 if success else 1
