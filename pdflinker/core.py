"""Spreadsheet, mapping and PDF operations independent of the interface."""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import date, datetime
from difflib import SequenceMatcher
import hashlib
import html
import json
from pathlib import Path
import re

import pymupdf as fitz


def display(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d" if value.time().isoformat() == "00:00:00" else "%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def sheet_names(path: Path) -> list[str]:
    if path.suffix.lower() == ".csv":
        return ["CSV"]
    if path.suffix.lower() == ".xls":
        import xlrd
        book = xlrd.open_workbook(str(path), on_demand=True)
        try:
            return book.sheet_names()
        finally:
            book.release_resources()
    from openpyxl import load_workbook
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        return book.sheetnames
    finally:
        book.close()


def read_sheet(path: Path, sheet: str, header_row: int = 1) -> tuple[list[str], list[list[str]]]:
    if header_row < 1:
        raise ValueError("Header row must be at least 1.")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            sample = stream.read(8192)
            stream.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            except csv.Error:
                dialect = csv.excel
            values = list(csv.reader(stream, dialect))
    elif suffix == ".xls":
        import xlrd
        book = xlrd.open_workbook(str(path), on_demand=True)
        try:
            tab = book.sheet_by_name(sheet)
            values = []
            for row in range(tab.nrows):
                cells = []
                for cell in tab.row(row):
                    value = cell.value
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        value = xlrd.xldate_as_datetime(value, book.datemode)
                    cells.append(value)
                values.append(cells)
        finally:
            book.release_resources()
    else:
        from openpyxl import load_workbook
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            values = list(book[sheet].iter_rows(values_only=True))
        finally:
            book.close()
    if len(values) < header_row:
        raise ValueError("The header row is outside this sheet.")
    raw_headers = list(values[header_row - 1])
    while raw_headers and not display(raw_headers[-1]).strip():
        raw_headers.pop()
    if not raw_headers:
        raise ValueError("The selected header row is empty.")
    headers, used = [], set()
    for index, value in enumerate(raw_headers):
        base = display(value).strip() or f"Column {index + 1}"
        name, count = base, 2
        while name in used:
            name = f"{base} ({count})"
            count += 1
        used.add(name)
        headers.append(name)
    rows = []
    for row in values[header_row:]:
        cells = [display(row[i]) if i < len(row) else "" for i in range(len(headers))]
        # Preserve physical row numbers, including blank rows, for filenames and selection.
        rows.append(cells)
    while rows and not any(rows[-1]):
        rows.pop()
    return headers, rows


@dataclass
class Field:
    key: str
    name: str
    page: int
    rect: tuple[float, float, float, float]
    kind: str = "text"
    manual: bool = False
    font_size: float = 11
    detected: bool = False


class Template:
    def __init__(self, path: Path, source: bytes | None = None):
        self.path = Path(path)
        self.source = self.path.read_bytes() if source is None else source
        self.fingerprint = hashlib.sha256(self.source).hexdigest()
        self.fields: list[Field] = []
        with self.open() as doc:
            if doc.needs_pass:
                raise ValueError("This PDF is password protected. Import an unlocked copy.")
            if not len(doc):
                raise ValueError("This PDF has no pages.")
            if doc.xref_get_key(doc.pdf_catalog(), "AcroForm/XFA")[0] != "null":
                raise ValueError("XFA forms are not supported. Save a standard PDF copy first.")
            self.sizes = [(p.rect.width, p.rect.height) for p in doc]
            occurrences = {}
            for page in doc:
                for widget in page.widgets() or []:
                    types = {fitz.PDF_WIDGET_TYPE_TEXT: "text", fitz.PDF_WIDGET_TYPE_CHECKBOX: "checkbox",
                             fitz.PDF_WIDGET_TYPE_COMBOBOX: "choice", fitz.PDF_WIDGET_TYPE_LISTBOX: "choice",
                             fitz.PDF_WIDGET_TYPE_RADIOBUTTON: "radio"}
                    if widget.field_type in types:
                        # Persist by field name + occurrence, never by unstable object references.
                        prefix = f"{page.number}:{widget.field_name}"
                        ordinal = occurrences.get(prefix, 0)
                        occurrences[prefix] = ordinal + 1
                        self.fields.append(Field(f"{prefix}:{ordinal}", widget.field_name or "Unnamed field",
                                                 page.number, tuple(widget.rect), types[widget.field_type]))

    def open(self):
        return fitz.open(stream=self.source, filetype="pdf")

    def detect_fields(self) -> list[Field]:
        """Infer blank boxes / writing rules and their nearest labels in vector PDFs.

        Geometry is read from the original document, never the filled preview.
        Overlay coordinates use the displayed page, just like user-drawn boxes.
        """
        added = []
        with self.open() as doc:
            for page in doc:
                labels = []
                for block in page.get_text("dict")["blocks"]:
                    for line in block.get("lines", []):
                        text = "".join(s["text"] for s in line["spans"]).strip().rstrip(": ")
                        if text:
                            labels.append((fitz.Rect(line["bbox"]), text))
                boxes, horizontal, vertical = [], [], []
                for path in page.get_drawings():
                    if "s" not in path["type"] or path.get("stroke_opacity", 1) < .1:
                        continue
                    for item in path["items"]:
                        if item[0] == "re":
                            boxes.append(fitz.Rect(item[1]))
                        elif item[0] == "l":
                            a, b = item[1:3]
                            if abs(a.y - b.y) < 1 and abs(a.x - b.x) >= 25:
                                horizontal.append((min(a.x, b.x), max(a.x, b.x), (a.y + b.y) / 2))
                            elif abs(a.x - b.x) < 1 and abs(a.y - b.y) >= 8:
                                vertical.append(((a.x + b.x) / 2, min(a.y, b.y), max(a.y, b.y)))
                # Some producers encode boxes as four separate lines.
                for x0, x1, top in horizontal:
                    for bx0, bx1, bottom in horizontal:
                        if not (8 <= bottom - top <= 160 and abs(x0 - bx0) < 2 and abs(x1 - bx1) < 2):
                            continue
                        def edge_at(x):
                            return any(abs(vx - x) < 2 and vy0 <= top + 2 and vy1 >= bottom - 2
                                       for vx, vy0, vy1 in vertical)
                        if edge_at(x0) and edge_at(x1):
                            boxes.append(fitz.Rect(x0, top, x1, bottom))

                def nearby_label(rect):
                    candidates = []
                    for text_rect, text in labels:
                        cy = (text_rect.y0 + text_rect.y1) / 2
                        # Labels immediately to the left, or above and aligned to this box.
                        gap = rect.x0 - text_rect.x1
                        if 0 <= gap <= 180 and rect.y0 - 5 <= cy <= rect.y1 + 5:
                            candidates.append((gap * .25 + abs(cy - (rect.y0 + rect.y1) / 2), text))
                        if (rect.width <= 36 and rect.height <= 36 and 0 <= text_rect.x0 - rect.x1 <= 90
                                and rect.y0 - 5 <= cy <= rect.y1 + 5):
                            candidates.append(((text_rect.x0 - rect.x1) * .25 + abs(cy - (rect.y0 + rect.y1) / 2), text))
                        above = rect.y0 - text_rect.y1
                        if (-1 <= above <= 45 and text_rect.x0 < rect.x1
                                and text_rect.x1 > rect.x0 - 3):
                            candidates.append((above + abs(text_rect.x0 - rect.x0) * .3 + 5, text))
                    return min(candidates, default=(0, ""), key=lambda item: item[0])[1]

                candidates = [(rect, False) for rect in boxes]
                for x0, x1, y in horizontal:
                    if any(abs(y - box.y0) < 2 or abs(y - box.y1) < 2
                           for box in boxes if abs(x0 - box.x0) < 2 and abs(x1 - box.x1) < 2):
                        continue
                    rect = fitz.Rect(x0, max(0, y - 21), x1, y - 1)
                    if nearby_label(rect):
                        candidates.append((rect, True))
                for rect, is_rule in sorted(candidates, key=lambda item: (item[0].y0, item[0].x0)):
                    bounds = page.rect * page.derotation_matrix
                    if (rect.is_empty or rect.width < 8 or not 8 <= rect.height <= 160
                            or rect.width > bounds.width * .96 or not bounds.contains(rect)):
                        continue
                    # Avoid occupied table cells and decorative panels containing text.
                    inner = fitz.Rect(rect.x0 + 2, rect.y0 + 2, rect.x1 - 2, rect.y1 - 2)
                    if any(inner.contains((text_rect.tl + text_rect.br) / 2) for text_rect, _ in labels):
                        continue
                    displayed = rect * page.rotation_matrix
                    duplicate = False
                    for field in self.fields:
                        if field.page != page.number:
                            continue
                        existing = fitz.Rect(field.rect)
                        if not field.manual:
                            existing = existing * page.rotation_matrix
                        overlap = (existing & displayed).get_area()
                        if overlap > .65 * min(existing.get_area(), displayed.get_area()):
                            duplicate = True
                            break
                    if duplicate:
                        continue
                    checkbox = not is_rule and 8 <= rect.width <= 36 and rect.height <= 36 and .6 <= rect.width / rect.height <= 1.5
                    key = f"detected:{page.number}:" + ":".join(f"{v:.1f}" for v in displayed)
                    field = Field(key, nearby_label(rect) or f"Field {len(self.fields) + 1}", page.number,
                                  tuple(displayed), kind="checkbox" if checkbox else "text",
                                  manual=True, detected=True)
                    self.fields.append(field)
                    added.append(field)
        return added

    def fill(self, links: dict[str, str], record: dict[str, str]) -> bytes:
        with self.open() as doc:
            for field in self.fields:
                column = links.get(field.key)
                if column is None:
                    continue
                if column not in record:
                    raise ValueError(f"Column '{column}' linked to '{field.name}' is missing.")
                value = record[column]
                page = doc[field.page]
                if field.manual:
                    # Stored boxes use displayed page coordinates; convert for rotated pages.
                    rect = fitz.Rect(field.rect) * page.derotation_matrix
                    if field.kind == "checkbox":
                        if value.strip().lower() in {"true", "yes", "y", "1", "x", "checked", "on"}:
                            inset = min(rect.width, rect.height) * .22
                            mark = fitz.Rect(rect.x0 + inset, rect.y0 + inset, rect.x1 - inset, rect.y1 - inset)
                            page.draw_line(mark.tl, mark.br, color=(0, 0, 0), width=1.5)
                            page.draw_line(mark.bl, mark.tr, color=(0, 0, 0), width=1.5)
                        continue
                    markup = html.escape(value).replace("\n", "<br>")
                    page.insert_htmlbox(rect, f"<div>{markup}</div>",
                                        css=f"* {{font-family: sans-serif; font-size: {field.font_size}pt;}} div {{margin:0;padding:2pt;line-height:1.3;}}",
                                        rotate=0 if field.detected else page.rotation, scale_low=0)
                else:
                    matches = [w for w in page.widgets() or [] if w.field_name == field.name]
                    ordinal = int(field.key.rsplit(":", 1)[1])
                    if ordinal >= len(matches):
                        raise ValueError(f"PDF field '{field.name}' is no longer available.")
                    widget = matches[ordinal]
                    if field.kind == "checkbox":
                        checked = value.strip().lower() in {"true", "yes", "y", "1", "x", "checked", "on"}
                        widget.field_value = widget.on_state() if checked else "Off"
                    elif field.kind == "radio":
                        widget.field_value = widget.on_state() if value == widget.on_state() else "Off"
                    else:
                        if field.kind == "choice" and value and value not in (widget.choice_values or []):
                            raise ValueError(f"'{value}' is not an allowed choice for '{field.name}'.")
                        widget.field_value = value
                    widget.update()
            return doc.tobytes(garbage=3, deflate=True)


def normalize(text: str) -> str:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    return "".join(c for c in text.casefold() if c.isalnum())


def auto_link(fields: list[Field], headers: list[str], existing: dict[str, str]) -> dict[str, str]:
    result = dict(existing)
    for field in fields:
        if field.key in result:
            continue
        target = normalize(field.name)
        scores = sorted(((SequenceMatcher(None, target, normalize(h)).ratio(), h) for h in headers), reverse=True)
        if not scores:
            continue
        best, column = scores[0]
        next_best = scores[1][0] if len(scores) > 1 else 0
        # Leave ambiguous matches for manual review.
        if best >= .78 and best - next_best >= .12:
            result[field.key] = column
    return result


def save_profile(path: Path, template: Template, links: dict[str, str]):
    path.write_text(json.dumps(profile_data(template, links), indent=2, ensure_ascii=False), encoding="utf-8")


def profile_data(template: Template, links: dict[str, str]):
    return {"version": 1, "template_sha256": template.fingerprint,
               "template_name": template.path.name, "fields": [asdict(f) for f in template.fields], "links": links}


def load_profile(path: Path, template: Template, headers: list[str]) -> tuple[dict[str, str], list[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return restore_profile(payload, template, headers)


def restore_profile(payload: dict, template: Template, headers: list[str]) -> tuple[dict[str, str], list[str]]:
    if payload.get("version") != 1 or not isinstance(payload.get("links"), dict):
        raise ValueError("This is not a supported mapping file.")
    same = payload.get("template_sha256") == template.fingerprint
    warnings, manual = [], []
    for raw in payload.get("fields", []):
        if not raw.get("manual"):
            continue
        if not same:
            warnings.append("Placed text boxes were skipped because the PDF template has changed.")
            break
        field = Field(**raw)
        rect = fitz.Rect(field.rect)
        if (field.page < 0 or field.page >= len(template.sizes) or rect.is_empty
                or rect.is_infinite or not 1 <= field.font_size <= 100):
            raise ValueError("The mapping file contains an invalid text box.")
        bounds = fitz.Rect(0, 0, *template.sizes[field.page])
        if not bounds.contains(rect):
            raise ValueError("A saved text box lies outside the PDF page.")
        manual.append(field)
    available = {f.key for f in template.fields if not f.manual} | {f.key for f in manual}
    links = {}
    for key, column in payload["links"].items():
        if key not in available:
            warnings.append(f"Skipped missing PDF field: {key}")
        elif column not in headers:
            warnings.append(f"Skipped missing spreadsheet column: {column}")
        else:
            links[key] = column
    template.fields = [f for f in template.fields if not f.manual] + manual
    return links, list(dict.fromkeys(warnings))


def output_name(pattern: str, record: dict[str, str], row_number: int) -> str:
    def replace(match):
        key = match.group(1)
        if key == "row":
            return str(row_number)
        if key not in record:
            raise ValueError(f"Unknown filename column: {key}")
        return record[key]
    name = re.sub(r"\{([^{}]+)\}", replace, pattern)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if name.lower().endswith(".pdf"):
        name = name[:-4].rstrip(" .")
    if not name:
        raise ValueError("The filename pattern produces an empty name.")
    if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        name = "_" + name
    return name[:180] + ".pdf"
