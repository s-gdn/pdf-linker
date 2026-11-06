# <img src="pdflinker/assets/icon.svg" width="32" height="32" alt=""> PDF Linker

Fill PDF templates from Excel or CSV files. Preview changes, link fields, and export one PDF per row, all locally on your Windows computer.

## Download

[Download the latest Windows release](https://github.com/s-gdn/pdf-linker/releases/latest), extract the ZIP, and open **PDFLinker.exe**. Keep the extracted folder together. Python is not required.

## Use

1. Import a spreadsheet and PDF template.
2. Click **Auto-link**, or hover over a PDF field to choose its column.
3. Check the spreadsheet rows you want, then use **File > Export PDFs**.
4. Save your workspace with **File > Save project**.

**File > Create job** creates a reusable script, with an optional desktop shortcut. Jobs remember completed records. Choose a permanent unique-ID column to handle moved, deleted, or changed rows.

See **Help > How to use** in the app or the [user guide](docs/USER_GUIDE.md) for details. Scanned PDFs may need manually drawn fields.

## Run from source

Install Python 3.11 or later, then double-click **run.bat**. It installs dependencies on the first run.

## Build for Windows

Run these commands in PowerShell from the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python scripts\build_release.py
```

The app is built in `dist/PDFLinker/`. The ready-to-share release is `dist/PDFLinker-Windows.zip`, with the app, examples, documentation, licences, and source code.

## Licence

[GNU AGPLv3](LICENSE). See [third-party notices](THIRD_PARTY_NOTICES.md) for dependency licences.
