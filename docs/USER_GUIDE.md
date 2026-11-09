# PDF Linker user guide

A local Windows desktop app that fills PDF templates using spreadsheet rows.

## Start

Double-click **run.bat**. It requires Python 3.11 or later, and downloads dependencies and prepares the pinned Medium models on the first run. After setup, documents are processed locally without an internet connection.

Or run from PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python scripts\prepare_models.py
.\.venv\Scripts\python -m pdflinker
```

## Workflow

1. **Import spreadsheet** in the Spreadsheet panel: choose XLSX, XLS, or UTF-8 CSV. Select a worksheet and its header row. Each subsequent row is one record; blank rows remain visible to preserve original row numbers.
2. **Import PDF** in the PDF panel: native form fields are read and detection automatically attempts to find additional blank outlined boxes and labeled writing lines. Nearby text supplies names; small square boxes are inferred as checkboxes. Matching columns are linked when a spreadsheet is available. No separate detection button is needed.
3. **Exact link** accepts only unique normalised matches between PDF field names/detected labels and spreadsheet columns. Case, punctuation, Unicode and CamelCase are normalised; role words and numbers remain. Use one clear, unique spreadsheet header per column and matching names or readable nearby PDF labels. **Suggest links** uses the included Medium models for similar meanings when wording differs. Use descriptive headers and labels, including roles such as Landlord email and Agent email, and keep labels close to PDF fields. Image-only scans need readable text or manually named fields. Hover over either button for preparation tips. Suggestions can be wrong: review every mapping before export. Both buttons keep existing links and shared manual values; model suggestions below the minimum score remain unlinked. The complete Windows app includes the models and works offline without uploading documents. Jobs use saved links without running models.
4. Click a PDF field to manage its link directly on the page. The card stays on its current field while the pointer is over it or its column dropdown, including when it covers other fields. Linked fields show the column name and an **×** button to remove that link. Unlinked fields display **“Field not linked. Use Exact link, Suggest links or choose a column here.”** with a dropdown of spreadsheet columns. The dropdown also changes existing links. One column can populate several fields. Enable **Fields → Field outlines** (also in View) to see model suggestions below the configured uncertainty threshold (70/100 by default) in yellow, other linked fields in green and unlinked fields in red; these colors are excluded from exports.
5. Click a spreadsheet row to preview its values. Double-click a cell to edit the imported copy. Preview updates after a short delay. New templates open at **Fit width**. Use **+**, **−**, or **Ctrl + mouse wheel** to zoom beyond the window, then drag the page or use scrollbars to pan. Manual zoom persists during resizing and live updates. **View → Fit width** and **View → Fit page** adjust the page size; there is no separate Fit button in the PDF panel.
6. **Fields → Draw field** is optional: drag a rectangle on the PDF and name it. Click a detected or drawn field to change its text size or remove it. Native fields can be unlinked but cannot be removed from the source template.
7. Use **File → Save project** and **File → Open project** to save/reopen a `.pdflinker` workspace. **File → Open recent** remembers the ten most recently opened or saved projects between sessions, newest first. Reopening or saving an existing entry moves it to the top. **Clear recent projects** clears the list without deleting files. Projects embed the original PDF and spreadsheet, current edited table values, field placements, links, checked rows, preview row, filename pattern, and outline setting. They can be moved to another computer without the original input files. Save updates the current project; **Save project as** or **Ctrl+Shift+S** saves a copy. **Ctrl+S** saves and **Ctrl+O** opens. Unsaved changes are marked with an asterisk in the window title.
8. Check the **Export** checkbox beside the rows to generate, or use **Check all** / **Uncheck all**. Open **File → Export PDFs**, then choose **Export checked rows** (one PDF per checked row) or **Export preview row** (the displayed record). **Filename pattern** is in the same menu. **Ctrl+E** exports checked rows.

## Saved jobs and scripts

**File → Create job…** opens a dialog to choose a saved project, its live spreadsheet, the physical spreadsheet row to start at, a job name, and an output folder. For example, start at **2** when row 1 is the header. Enable **Create desktop shortcut to this job script** to put a Windows shortcut on the desktop. Existing shortcuts are kept; duplicate names receive a number.

Enable **Use column-based PDF filenames** to select a spreadsheet column and optional **Text before** / **Text after**. Choosing `Name` produces `Alex Morgan.pdf`; prefix `Staff_` and suffix `_signed` produce `Staff_Alex Morgan_signed.pdf`. The example updates in the dialog. These settings name the generated PDFs; the **Job name** still names the saved script. Disabled naming uses the project's filename pattern. Prefix/suffix text is literal, invalid filename characters are replaced, blank naming values stop the run, and duplicate column-based names receive numbered suffixes.

Enable **Track records by unique ID**, then choose a stable column such as `Employee ID` or `Reference`, to support rows that are moved, deleted, inserted, or changed. Every nonblank record must have a nonblank, unique ID. IDs are compared as case-sensitive text with surrounding whitespace ignored, and must not change or be reused for a different record. Names are suitable only when unique and permanent. The initial start row excludes the IDs above it on the first scan; subsequent scans find new IDs anywhere in the worksheet, even when deleting earlier rows moves records above that original position.

With ID tracking, **Create new PDF for changed rows** can be enabled. A changed record gets a new file such as `Alex Morgan (revision 2).pdf`, and its previous PDFs remain untouched. A subsequent unchanged run produces nothing. When unchecked, changed records are reported and skipped while other new records can still export. Deleted IDs retain both their completion history and their existing PDFs; reintroducing the same ID with unchanged data does not duplicate the export. Changing an ID is treated as deleting the old record and introducing a new one.

Projects saved with this version remember the original spreadsheet path. For older or moved projects, browse to the live XLSX, XLS, or CSV file in the dialog. A job reads the saved worksheet and header row from that live file, rather than the embedded spreadsheet snapshot or session-only table edits. Save spreadsheet changes in Excel before running. The first scan selects nonblank rows at or after the start row, independent of the project's export checkboxes; ID-tracked jobs preserve that initial selection by ID thereafter.

Created jobs appear in the **Scripts** menu. Click a job to run it inside the app, or double-click its generated **Run job.bat** / desktop shortcut. Each invocation checks the current spreadsheet once and exports unprocessed records, plus changed records if that option is enabled. It does not continuously watch the file or install a schedule. The command-line entry can also be used by an existing scheduler:

```powershell
.\PDFLinker.exe --run-job "C:\path\to\job\job.json"
```

Use `--interactive` to display a completion/error dialog, as the generated batch script does. Without it the runner exits with code 0 for success and 1 for failure; `run.log` records the result. The application folder must remain available at the location used when the launcher was generated. The Scripts menu runs the job directly using the current app.

**Scripts → Open scripts folder** opens `%LOCALAPPDATA%\PDFLinker\jobs`. Each job has its own folder containing `Run job.bat`, `job.json`, a frozen `project.pdflinker`, `history.json`, `run.lock`, and `run.log` (the last two appear when run). Keep these together. The copied project fixes the PDF template, links, and filename pattern for that job; create a new job to use a changed project. Job folders contain work documents and should be handled like their source files.

Completion history is saved after each successful PDF. Failed or cancelled runs keep their successful exports and can be rerun to continue. Recovery also checks an interrupted export against its recorded PDF hash before accepting it as complete, including revision exports. Existing output files are never overwritten or guessed to be completed work, and simultaneous runs of the same job are blocked. Column-named / ID-tracked jobs choose numbered filenames when names collide. Other jobs stop on a collision; including `{row}` in their project filename pattern avoids duplicates.

Jobs **without a unique ID column** expect rows to be appended, with completed rows kept in their original positions and unchanged. Editing, deleting, or reordering completed rows stops those jobs with an explanation, because row numbers alone cannot reliably distinguish an edit from a different record shifting into that position. The changed-row checkbox requires an ID column for this reason. Existing jobs retain their previous append-only behavior; create a new job to enable ID tracking and new filename options. Blank rows remain uncompleted and can be filled later. Do not delete `history.json` to restart a job. Desktop shortcuts use the Windows Desktop location, including redirected/OneDrive desktops. If shortcut creation fails, the saved job remains available in Scripts.

Filenames default to `Form_{row}.pdf`, where `{row}` is the original spreadsheet row number. Column names also work: `Form_{row}_{Name}`. Duplicate output names and existing files stop export; files are never overwritten. A cancelled or failed batch keeps its completed PDFs and reports how many were created. Batch export runs in a background thread.

Table edits do not alter the source workbook; save a project to preserve them. Switching worksheets reloads the original workbook values and resets table edits and row checks. Projects contain copies of work documents and spreadsheet data; exported PDFs contain the selected record. All processing and saving stay on the computer.

## Supported behavior and limits

- Text fields, checkboxes, dropdowns, lists, radio buttons, and manually placed text are supported. Checkbox true values: `yes`, `true`, `y`, `1`, `x`, `checked`, `on` (case-insensitive). Other values clear the checkbox. Radio values must match the button's PDF export state. Choice values must match an allowed option.
- PDF form field formatting and fonts come from the template; native fields may clip long text or lack glyphs. Drawn boxes use Unicode HTML text rendering and shrink to fit. Review the preview before generating a batch.
- Field detection is a heuristic for PDF vector graphics and embedded text. It supports rectangular outlines, boxes formed from separate straight lines, and labeled horizontal writing lines. Decorative shapes and unusual layouts may need correction. Image-only scans have no readable text/vector outlines for this detector; there is no OCR, and manual placement is still available for those files.
- Password-protected PDFs and XFA forms are rejected. Signatures and PDF form JavaScript calculations are not supported.
- XLSX formulas use Excel's last saved cached results. Recalculate and save the workbook in Excel first. Dates appear as `YYYY-MM-DD`; spreadsheet display formatting is not reproduced. Store identifiers with leading zeroes as text. XLSX/XLS workbooks and imported tables are held in memory, so very large sheets may take time to load.
- No automatic combination of several rows into a single PDF or mapping expressions. Use project files to preserve a workspace across app restarts; legacy JSON link profiles are not exposed in the new interface.

## Building the app

See the [README build instructions](../README.md#build-for-windows). The build script packages the icon, user guide, licence files, and source with the Windows app.

## Manual values and unfilled fields

Click a PDF field to open its card. Click outside the card or press Escape to close it. Enable **Use a manual value** to type a value for the selected row. **Persist across rows and jobs** applies the value to every row and includes it in newly created jobs. Save the project before creating a job; existing jobs keep their saved settings. Disable the manual value to return to the spreadsheet link. Manual values also turn the field outline green.

Row-specific manual values are saved with the project and used by manual exports, but are excluded from jobs. Reloading a worksheet clears row-specific values along with table edits.

Both manual export options check the selected rows for unfilled fields, including blank spreadsheet values. Choose Yes to export anyway or Cancel to return to editing. Jobs run without this warning.

## Suggestion scores

Suggest links builds separate attribute evidence for PDF fields and spreadsheet columns: type (such as date, identifier, amount or frequency), temporal purpose, and entity words. It compares immediate labels separately from broader question/section context. Clearly incompatible types or opposing purposes are excluded from automatic suggestions; original prepared IDs, saved links and manual values retain priority.

Source column types use headers plus narrow local value patterns, such as ISO dates, Monthly/Quarterly/Annually, or formatted telephone values. Numeric identifiers retain their original text, including leading zeros. An adjacent amount/frequency pattern can provide current/proposed grouping for duplicate frequency headings. This inferred group is shown on the field card and saved in projects; it does not rename the original column. Arbitrary column order, merged/multiple header rows and unknown abbreviations still need preparation or review.

The unresolved fields are assigned jointly, with an unmatched option, instead of taking the highest pair greedily. Explicit/shared mappings and completed address components remain fixed. Clear signatures and handwritten-note fields abstain unless their prepared ID or explicit mapping supplies a source. The model score shown is the average semantic evidence from the applicable views; assignment priorities and type evidence are separate, and scores remain similarities rather than probabilities.

Suggest links ranks remaining field/column pairs across the form. Experimental RRF is enabled by default: the average model score must meet the Auto-link minimum (50/100 by default), and the normalised rank score must meet its separate RRF cutoff (50/100 by default). Disabling RRF uses the previous average-score ranking. Model guesses reserve columns so one source is not reused for unrelated fields. Prepared/existing mappings and address components can still share columns. Displayed scores remain average similarities, not probabilities, and higher coverage can include wrong links.

Suggestions below the uncertainty threshold (70/100 by default) are yellow. File > Settings > Auto-link changes that threshold and updates existing outlines and field cards. Click a field to see its score and review the link. Selecting a column manually confirms it and removes the yellow marker. Scores are saved in projects. Row-specific or shared manual values display green while active. Below-minimum fields remain unlinked and red; no fixed number of links is forced based on the number of columns. Clear links before rerunning if you want to replace current suggestions.

## Settings

File > Settings opens application settings with a section list. Auto-link currently contains Minimum suggestion score (default 50/100) and Uncertainty threshold (default 70/100). Both accept values from 0 to 100 independently. The minimum affects future Suggest links runs and preserves current links; the uncertainty threshold changes yellow highlighting immediately when applied. Apply saves without closing, OK saves and closes, and Cancel discards changes since the last Apply. Restore Defaults resets the controls to 50 and 70; use Apply or OK to save them. Settings are remembered on this computer across projects and restarts.

The temporary **RRF (experimental)** section exposes the four relative model weights, rank smoothing constant `k` and normalised rank cutoff, plus an enable switch. Defaults follow the local experiment: relative weights 1:1:1:9 (Mixedbread 75%, each other model 8.333...%), `k = 1`, rank cutoff 50/100 and RRF enabled. Weights normalise automatically and at least one must be above zero. Larger `k` compresses rank differences; these settings are not probabilities. **Only change these values if you understand what you are doing.** Apply/OK saves them on this computer; Cancel preserves the last applied values; Restore Defaults resets them too. Changes affect subsequent suggestion runs, not existing links or saved job mappings. Scores shown on fields and their yellow highlighting still use the average model score.

## Abbreviations and address components

Suggest links looks for initialisms in column headings and field context, then checks full phrases found in the document context and other headings. Before matching, **Review abbreviations** shows the results. A single meaning is preselected; ambiguous and unknown abbreviations start blank. Select an alternative or type your own expansion. Leave a meaning blank to keep the abbreviation unchanged. **Continue** uses these choices for this suggestion run; **Cancel** stops without changing links. If none are detected, matching starts directly. Original PDF names, Excel headings and saved column links are preserved.

Address components belonging to the same section/question are ranked together against a common address source. This lets first line, second line, town/city and postcode follow the same address mapping instead of matching an unrelated field because of a shared word such as first. Existing mappings stay fixed. To replace an old incorrect suggestion, unlink it and run Suggest links again; Clear links provides a complete remap.

A matched address supplies a role clue for name fields in the same section. For example, after confirming PM as property manager, a section linked to PM Address can use property manager as extra context for its name field. Conflicting address-role clues are ignored. These remain model suggestions subject to the configured score thresholds and review.

Address value extraction supports comma-separated or multiline UK addresses in `street, city, postcode` or `street, locality, city, postcode` order. In the latter format, locality goes to line 2 and city to town/city without being duplicated. With four or more components before the postcode, or no recognised UK postcode, city remains blank and remaining address text stays in line 2. This is a format convention, not geographic recognition: if your last component is a county or country, use separate explicit columns or check the extracted values manually. County is not inferred from a full address.
