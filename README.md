# <img src="pdflinker/assets/icon.svg" width="32" height="32" alt=""> PDF Linker

Fill PDF templates from Excel or CSV files. Preview changes, link fields, and export one PDF per row, all locally on your Windows computer.

## Download

[Download the latest Windows release](https://github.com/s-gdn/pdf-linker/releases/latest), extract the ZIP, and open **PDFLinker.exe**. Keep the extracted folder together. Python is not required.

## Use

1. Import a spreadsheet and PDF template.
2. Use **Exact link** for matching names, **Suggest links** for similar meanings, or click a PDF field to choose its column.
3. Check the spreadsheet rows you want, then use **File > Export PDFs**.
4. Save your workspace with **File > Save project**.

**File > Create job** creates a reusable script, with an optional desktop shortcut. Jobs remember completed records. Choose a permanent unique-ID column to handle moved, deleted, or changed rows.

See **Help > How to use** in the app or the [user guide](docs/USER_GUIDE.md) for details. Scanned PDFs may need manually drawn fields.

## Run from source

Install Python 3.11 or later, then double-click **run.bat**. It installs dependencies and prepares the bundled Medium models on the first run. Initial setup needs internet unless the pinned model archive is already available locally.

## Build for Windows

Run these commands in PowerShell from the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python scripts\build_release.py
```

The app is built in `dist/PDFLinker/`. The ready-to-share release is `dist/PDFLinker-Windows.zip`, with the app, documentation, licences, and source code.
The build automatically prepares and includes the pinned Medium models. If needed, it downloads their verified archive; no model download is required when using the finished Windows app. Model files are included once, alongside the app, and are excluded from the source copy.

## How linking works

**Exact link** accepts unique matches after normalising case, punctuation and spacing. **Suggest links** follows this pipeline:

1. **Read the documents.** Import Excel/CSV headers and PDF fields. Detect blank boxes and writing lines, then read nearby labels, sections and questions across the PDF pages.
2. **Review abbreviations.** Confirm or correct meanings such as FREQ = frequency. Original PDF names and spreadsheet headers stay unchanged.
3. **Keep reliable links.** Preserve existing links and manual values. Check original PDF field IDs first, then close ID matches and clear label/context matches.
4. **Describe the remaining fields.** Identify types such as date, identifier, amount or frequency, along with purpose such as current/proposed or start/end. Local value patterns and adjacent amount/frequency columns can add spreadsheet context.
5. **Compare meanings locally.** The bundled models compare each label and its wider context. Incompatible types or purposes are excluded. Signatures and handwritten-only fields normally stay unlinked.
6. **Resolve related fields.** Address components can share one source. A matched address can help identify the name belonging to the same section.
7. **Choose links together.** Weighted reciprocal rank fusion (RRF) ranks candidates. The app chooses the best combination above the acceptance minimums, allowing fields to remain unlinked.
8. **Review and export.** The preview updates with the selected spreadsheet row. Green means linked, yellow means uncertain and red means unlinked. Click a field to inspect the source, see inferred context, change the link or enter a manual value.

Matching stays on your computer. Record values are not sent to the models or an online service. Jobs use saved mappings without running suggestions again. Scanned PDFs still need readable text or manually placed fields.

**File > Settings** controls matching. Defaults are a **50/100** minimum model score, **50/100** minimum RRF score, `k = 1`, Mixedbread weight **75%**, and **8 1/3%** for each other model. Relative weights `1:1:1:9` preserve those shares exactly. The uncertainty threshold is **70/100**. Scores measure similarity, not probability; review suggestions before exporting. Only change the experimental RRF values if you understand what you are doing.

Existing links are preserved. Unlink a field or use Clear links before asking for a replacement suggestion. See the [user guide](docs/USER_GUIDE.md) for address formats, manual values and job behaviour.

## Licence

[GNU AGPLv3](LICENSE). See [third-party notices](THIRD_PARTY_NOTICES.md) for dependency licences.
