"""Generate a small, fictional workbook and two templates for trying the app."""
from pathlib import Path

import pymupdf as fitz
from openpyxl import Workbook


def create(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    sheet = book.active
    sheet.title = "People"
    sheet.append(["Name", "Email", "Department", "Reference", "Approved"])
    sheet.append(["Alex Morgan", "alex@example.com", "Operations", "REF-001", "Yes"])
    sheet.append(["Jamie Patel", "jamie@example.com", "Finance", "REF-002", "No"])
    sheet.append(["Sam Taylor", "sam@example.com", "People", "REF-003", "Yes"])
    sheet.freeze_panes = "A2"
    for column in "ABCDE":
        sheet.column_dimensions[column].width = 26
    book.save(folder / "people.xlsx")

    for fillable in (True, False):
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.draw_rect(fitz.Rect(0, 0, 595, 120), color=None, fill=(.07, .21, .33))
        page.insert_text((40, 65), "EMPLOYEE INFORMATION", fontsize=23, color=(1, 1, 1))
        page.insert_text((40, 94), "Example template / fictional data", fontsize=11, color=(.75, .85, .95))
        for index, name in enumerate(["Name", "Email", "Department", "Reference", "Approved"]):
            y = 170 + index * 85
            page.insert_text((40, y), name, fontsize=12)
            rect = fitz.Rect(40, y + 12, 555 if name != "Approved" else 62, y + 43)
            page.draw_rect(rect, color=(.65, .7, .75), fill=(.97, .98, 1))
            if fillable:
                widget = fitz.Widget()
                widget.field_name = name
                widget.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX if name == "Approved" else fitz.PDF_WIDGET_TYPE_TEXT
                widget.rect = rect
                widget.text_fontsize = 12
                page.add_widget(widget)
        page.insert_text((40, 790), "Created locally with PDF Linker", fontsize=10, color=(.4, .45, .5))
        doc.save(folder / ("employee_form.pdf" if fillable else "employee_flat.pdf"))
        doc.close()


if __name__ == "__main__":
    create(Path(__file__).parent)
