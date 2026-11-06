"""The in-app guide, kept in a scrollable window as features grow."""
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout


HELP_HTML = """
<h2>How to use PDF Linker</h2>
<h3>1. Import your files</h3>
<p>Use <b>Import spreadsheet</b> to open XLSX, XLS or UTF-8 CSV. Choose the worksheet and
header row. Each following row is one record. Use <b>Import PDF</b> to load your template.
Fillable fields are read automatically; the app also attempts to find blank boxes and
writing lines in the PDF. Image-only scans may need manually placed fields.</p>

<h3>2. Link spreadsheet columns to PDF fields</h3>
<p>Click <b>Auto-link</b> to match field and column names. If some fields remain unlinked,
a second pass uses tooltips, nearby labels, section context and common abbreviations.
It can combine numbered tenant names, extract address parts, and format DDMMYYYY dates
when the PDF structure supports this. Existing links are preserved; uncertain matches stay unlinked.
Click a PDF field to review
or select its spreadsheet column. The card stays on that field while you interact with
the card or its dropdown. Click <b>×</b> to remove a link.</p>
<p><b>Fields → Field outlines</b> shows linked fields in green and unlinked fields in red.
The outlines are excluded from exported PDFs. <b>Fields → Clear links</b> removes all
links. Use <b>Fields → Draw field</b> to place an extra field; click a drawn or
detected field to change its text size or remove it.</p>

<p>Click outside the card or press Escape to close it. Enable <b>Use a manual value</b>
to type a value for the selected row. Enable <b>Persist across rows and jobs</b> to use
that value for every row. Save the project before creating a job; existing jobs keep
their saved settings. Row-only values are saved in projects but are excluded from jobs.</p>

<h3>3. Preview and export</h3>
<p>Click a spreadsheet row to preview it. Double-click a cell to edit its imported value.
Use <b>+</b>, <b>−</b> or <b>Ctrl + mouse wheel</b> to zoom, and drag the page or use its
scrollbars to pan. <b>View</b> contains Fit width, Fit page and Equal panel widths.</p>
<p>Check the rows to generate, then choose <b>File → Export PDFs → Export checked rows</b>.
Export preview row generates only the displayed record. Filename pattern is in the
same menu: <b>Form_{row}_{Name}</b> uses the spreadsheet row number and Name value.
Each selected row creates one PDF. Existing files are never overwritten.</p>

<p>Manual exports warn if any selected PDF has unfilled fields. Choose Yes to export
anyway, or Cancel to return and fill them. Jobs do not show this warning.</p>

<h3>4. Save a project</h3>
<p><b>File → Save project</b> saves a .pdflinker workspace containing the inputs, edited
table values, field placements, links, checked rows and export settings. Use <b>File → Open project</b>
to restore it, or Save project as to save a copy. <b>File → Open recent</b> lists the ten most
recently opened or saved projects, newest first, and remembers them between app sessions.
Clear recent projects clears the list without deleting any files. Table edits do not change the original
workbook. Switching worksheets reloads the original workbook values and resets row checks.</p>

<h3>5. Create a reusable job</h3>
<p>Choose <b>File → Create job…</b>, select a <b>saved project</b>, confirm the <b>live
spreadsheet</b>, enter the starting spreadsheet row and choose the output folder. Row
numbers include the header: use 2 when row 1 contains the column names.</p>
<p>Jobs read the current live spreadsheet, rather than the project's embedded copy or
unsaved table edits. Save changes in Excel before running. Jobs use their own copy of
the saved project's template and links, and their starting-row selection is independent
of the project's export checkboxes. Create a new job to use a changed project.</p>
<p>Enable <b>Create desktop shortcut to this job script</b> for a desktop shortcut.</p>

<h3>6. Choose PDF filenames</h3>
<p>Enable <b>Use column-based PDF filenames</b>, choose a column, and optionally enter
Text before and Text after. Choosing <b>Name</b> produces <b>Alex Morgan.pdf</b>.
Prefix <b>Staff_</b> and suffix <b>_signed</b> produce <b>Staff_Alex Morgan_signed.pdf</b>.
The example updates in the dialog. These options name the PDFs; Job name names the script.</p>
<p>Leave the checkbox off to use the project's filename pattern. Empty naming values
stop a run. Invalid filename characters are replaced; duplicate column-based names
receive numbered suffixes.</p>

<h3>7. Track new, changed and deleted records</h3>
<p>For sheets where records can move or be deleted, enable <b>Track records by unique ID</b>
and choose a permanent column such as <b>Employee ID</b> or <b>Reference</b>. Every nonblank
record needs a nonblank, unique ID. Keep each ID unchanged and never reuse it for another
record. You can use Name for PDF filenames and Reference for tracking.</p>
<p>On the first scan, IDs above the starting row are excluded. Later scans recognise
existing IDs even if rows move and find new IDs anywhere in the worksheet. Deleting a
record keeps its completion history and existing PDFs. Reintroducing the same ID with
unchanged data does not generate another PDF. Changing an ID counts as a new record.</p>
<p>With ID tracking, enable <b>Create new PDF for changed rows</b> to export a new revision,
such as <b>Alex Morgan (revision 2).pdf</b>, while keeping the previous PDF. When unchecked,
changed records are reported and skipped; new records can still export.</p>
<p><b>Without an ID column</b>, jobs are append-only. Editing, deleting or reordering
completed rows stops the job because row positions cannot reliably identify records.
The changed-row checkbox requires ID tracking. Existing jobs keep their previous
append-only settings; create a new job to enable these options.</p>

<h3>8. Run jobs and resume unfinished work</h3>
<p>Choose a job under <b>Scripts</b>, or run its <b>Run job.bat</b> or desktop shortcut.
Each run checks the spreadsheet <b>once</b>; it does not continuously watch the file.
Run again after adding or changing records. Completed records are remembered, and
successful exports remain recorded if a run fails or is cancelled.</p>
<p><b>Scripts → Open scripts folder</b> opens the job folders. Keep each job's script,
project copy, job.json and <b>history.json</b> together. History records completed exports
and revisions; do not delete it to restart a job. The run.log file records run results
and errors. Simultaneous runs of the same job are blocked.</p>

<h3>Keyboard shortcuts</h3>
<p><b>Ctrl+S</b> Save project · <b>Ctrl+Shift+S</b> Save as · <b>Ctrl+O</b> Open project ·
<b>Ctrl+E</b> Export checked rows.</p>
<p>Files are processed locally on this computer. Projects and job folders contain copies
of your work documents and spreadsheet data.</p>
"""


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("How to use PDF Linker")
        self.resize(760, 640)
        layout = QVBoxLayout(self)
        self.guide = QTextBrowser()
        self.guide.setStyleSheet("QTextBrowser { background: #111925; color: #e2e8f0; border: 1px solid #344158; border-radius: 6px; padding: 14px; }")
        self.guide.document().setDefaultStyleSheet("h2 { color: #c7d2fe; } h3 { color: #a5b4fc; margin-top: 20px; } p { line-height: 135%; }")
        self.guide.setHtml(HELP_HTML)
        layout.addWidget(self.guide)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def show_help(parent):
    HelpDialog(parent).exec()
