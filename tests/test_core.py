import json
from datetime import datetime

import pymupdf as fitz
import pytest
from openpyxl import Workbook

from pdflinker.core import Field, Template, auto_link, load_profile, output_name, read_sheet, save_profile


@pytest.fixture
def template(tmp_path):
    path = tmp_path / "template.pdf"
    with fitz.open() as doc:
        page = doc.new_page()
        for index, (name, kind) in enumerate([("FullName", fitz.PDF_WIDGET_TYPE_TEXT), ("Approved", fitz.PDF_WIDGET_TYPE_CHECKBOX)]):
            widget = fitz.Widget()
            widget.field_name = name
            widget.field_type = kind
            widget.rect = fitz.Rect(40, 40 + index * 60, 280, 70 + index * 60)
            page.add_widget(widget)
        doc.save(path)
    return Template(path)


def test_fill_checkboxes_and_source_unchanged(template):
    links = {f.key: f.name for f in template.fields}
    data = template.fill(links, {"FullName": "Alex Morgan", "Approved": "Yes"})
    with fitz.open(stream=data, filetype="pdf") as doc:
        page = doc[0]
        widgets = list(page.widgets())
        assert widgets[0].field_value == "Alex Morgan"
        assert widgets[1].field_value == widgets[1].on_state()
        assert "Alex Morgan" in doc[0].get_text()
    data = template.fill(links, {"FullName": "Jamie Patel", "Approved": "No"})
    with fitz.open(stream=data, filetype="pdf") as doc:
        assert list(doc[0].widgets())[1].field_value == "Off"
    with template.open() as doc:
        assert list(doc[0].widgets())[0].field_value in (None, "")


def test_manual_box_html_escaping_and_unicode(template):
    field = Field("manual:1", "Notes", 0, (40, 220, 420, 300), manual=True)
    template.fields.append(field)
    data = template.fill({field.key: "Notes"}, {"Notes": "R&D <Team> — José 東京"})
    with fitz.open(stream=data, filetype="pdf") as doc:
        text = doc[0].get_text()
        assert "R&D <Team>" in text
        assert "José" in text
        assert "東京" in text


def test_link_exact_fuzzy_and_ambiguous():
    fields = [Field("a", "FullName", 0, (0, 0, 10, 10)), Field("b", "Address", 0, (0, 0, 10, 10))]
    assert auto_link(fields, ["Full Name", "Address1", "Address2"], {}) == {"a": "Full Name"}
    assert auto_link(fields, ["Full Name"], {"a": "Custom"})["a"] == "Custom"


def test_profile_roundtrip_and_changed_template(template, tmp_path):
    manual = Field("manual:1", "Name box", 0, (10, 200, 200, 230), manual=True)
    template.fields.append(manual)
    links = {template.fields[0].key: "Name", manual.key: "Name"}
    path = tmp_path / "links.json"
    save_profile(path, template, links)
    other = Template(template.path)
    restored, warnings = load_profile(path, other, ["Name"])
    assert restored == links and not warnings
    assert len(other.fields) == 3
    other.fingerprint = "changed"
    restored, warnings = load_profile(path, other, ["Name"])
    assert manual.key not in restored
    assert warnings and len(other.fields) == 2


def test_missing_column_and_invalid_profile(template, tmp_path):
    with pytest.raises(ValueError, match="missing"):
        template.fill({template.fields[0].key: "Absent"}, {"Other": "value"})
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"version": 999, "links": {}}))
    with pytest.raises(ValueError, match="supported"):
        load_profile(path, template, [])


def test_xlsx_header_row_duplicate_headers_and_dates(tmp_path):
    path = tmp_path / "people.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.append(["Report title"])
    sheet.append(["Name", "Name", None, "Date"])
    sheet.append(["Alex", "Morgan", 123, datetime(2026, 1, 2)])
    sheet.append([None, None, None, None])
    sheet.append(["Jamie", None, 0, None])
    book.save(path)
    headers, rows = read_sheet(path, "Sheet", 2)
    assert headers == ["Name", "Name (2)", "Column 3", "Date"]
    assert rows[0] == ["Alex", "Morgan", "123", "2026-01-02"]
    assert rows[1] == ["", "", "", ""]
    assert rows[2][2] == "0"


def test_csv_and_filename_sanitizing(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text('\ufeffName;Reference\nAlex;A/12\n', encoding="utf-8")
    headers, rows = read_sheet(path, "CSV")
    assert headers == ["Name", "Reference"]
    assert rows == [["Alex", "A/12"]]
    assert output_name("{row}_{Reference}", dict(zip(headers, rows[0])), 2) == "2_A_12.pdf"
    assert output_name("CON", {}, 1) == "_CON.pdf"
    with pytest.raises(ValueError, match="Unknown"):
        output_name("{Unknown}", {}, 1)


def test_rotated_manual_box(tmp_path):
    path = tmp_path / "rotated.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=300, height=500)
        page.set_rotation(90)
        doc.save(path)
    template = Template(path)
    field = Field("manual:1", "Notes", 0, (30, 30, 220, 70), manual=True)
    template.fields.append(field)
    data = template.fill({field.key: "Notes"}, {"Notes": "Rotated value"})
    with fitz.open(stream=data, filetype="pdf") as doc:
        words = doc[0].get_text("words")
        assert words
        rect = fitz.Rect(words[0][:4]) * doc[0].rotation_matrix
        assert fitz.Rect(field.rect).contains(rect)


def test_detect_flat_example_labels_types_fill_and_profile(tmp_path):
    from examples.create_examples import create
    create(tmp_path)
    template = Template(tmp_path / "employee_flat.pdf")
    assert not template.fields
    fields = template.detect_fields()
    assert [f.name for f in fields] == ["Name", "Email", "Department", "Reference", "Approved"]
    assert [f.kind for f in fields] == ["text"] * 4 + ["checkbox"]
    assert all(f.detected and f.manual for f in fields)
    assert template.detect_fields() == []
    headers, rows = read_sheet(tmp_path / "people.xlsx", "People")
    links = auto_link(fields, headers, {})
    assert len(links) == 5
    data = template.fill(links, dict(zip(headers, rows[0])))
    with fitz.open(stream=data, filetype="pdf") as doc:
        page = doc[0]
        assert "Alex Morgan" in page.get_text()
        # Approved receives a cross rather than the word 'Yes'.
        marks = [d for d in page.get_drawings() if d["width"] == 1.5]
        assert len(marks) == 2
    data = template.fill(links, dict(zip(headers, rows[1])))
    with fitz.open(stream=data, filetype="pdf") as doc:
        assert not [d for d in doc[0].get_drawings() if d["width"] == 1.5]
    profile = tmp_path / "flat.links.json"
    save_profile(profile, template, links)
    fresh = Template(template.path)
    restored, warnings = load_profile(profile, fresh, headers)
    assert restored == links and not warnings
    assert all(f.detected for f in fresh.fields)
    assert fresh.detect_fields() == []


def test_detect_rules_line_boxes_rotated_pages_and_occupied_cells(tmp_path):
    path = tmp_path / "shapes.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=500, height=600)
        page.insert_text((30, 60), "Employee:")
        page.draw_line((110, 67), (400, 67))
        # A box drawn from separate line segments, with a label above it.
        page.insert_text((30, 120), "Department")
        for a, b in [((30, 130), (400, 130)), ((400, 130), (400, 160)),
                     ((400, 160), (30, 160)), ((30, 160), (30, 130))]:
            page.draw_line(a, b)
        page.draw_rect(fitz.Rect(30, 210, 400, 240))
        page.insert_text((40, 228), "Already occupied")
        page.draw_rect(fitz.Rect(30, 290, 45, 305))
        page.insert_text((55, 303), "Approved")
        page.set_rotation(90)
        doc.save(path)
    template = Template(path)
    fields = template.detect_fields()
    assert [f.name for f in fields] == ["Employee", "Department", "Approved"]
    assert fields[-1].kind == "checkbox"
    assert len(template.detect_fields()) == 0
    assert all(fitz.Rect(0, 0, *template.sizes[0]).contains(fitz.Rect(f.rect)) for f in fields)
    data = template.fill({fields[0].key: "Employee"}, {"Employee": "Test Employee"})
    with fitz.open(stream=data, filetype="pdf") as doc:
        assert "Test Employee" in doc[0].get_text()


def test_detection_does_not_duplicate_native_fields(template):
    with template.open() as doc:
        # Native widgets are found even if a producer also draws their borders.
        page = doc[0]
        for field in template.fields:
            page.draw_rect(fitz.Rect(field.rect))
        path = template.path.with_name("bordered.pdf")
        doc.save(path)
    bordered = Template(path)
    assert bordered.detect_fields() == []
