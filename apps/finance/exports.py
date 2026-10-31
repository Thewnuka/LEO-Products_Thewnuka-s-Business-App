"""
Report exports: CSV (opens in Excel) and a real .xlsx file, written with the standard
library only (no extra package). Text that a spreadsheet could run as a formula is
prefixed with an apostrophe (CSV/formula injection protection).
"""
import csv
import io
import zipfile
from decimal import Decimal
from xml.sax.saxutils import escape

from django.http import HttpResponse

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _safe_text(value):
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


def table(report, columns):
    """Header + rows + totals as plain Python values (numbers stay numbers)."""
    header = [c.label or "Item" for c in columns]
    body = []
    for row in report.rows + ([report.totals] if report.totals else []):
        cells = []
        for c in columns:
            value = row.get(c.key)
            if c.kind in ("money", "number", "int") and value is not None and not isinstance(value, str):
                cells.append(value)
            else:
                cells.append(_safe_text(value if value is not None else ""))
        body.append(cells)
    return header, body


def _filename(report, ext):
    period = f"_{report.period.start:%Y%m%d}-{report.period.end:%Y%m%d}" if report.period else ""
    return f"leo-{report.slug}{period}.{ext}"


def _title_lines(report):
    lines = [[f"LEO PRODUCTS — {report.title}"]]
    if report.period:
        lines.append([f"Period: {report.period.label}"])
    return lines


def csv_response(report, columns):
    header, body = table(report, columns)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerows(_title_lines(report))
    writer.writerow(header)
    writer.writerows([[f"{v:.2f}" if isinstance(v, Decimal) else v for v in row] for row in body])
    for note in report.warnings + report.notes:
        writer.writerow([_safe_text(note)])
    response = HttpResponse("﻿" + buffer.getvalue(), content_type="text/csv; charset=utf-8")  # BOM: Excel reads UTF-8
    response["Content-Disposition"] = f'attachment; filename="{_filename(report, "csv")}"'
    return response


def _col(index):
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def _cell(ref, value, style=0):
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return f'<c r="{ref}" s="{style or 1}"><v>{value}</v></c>'
    return f'<c r="{ref}" t="inlineStr" s="{style}"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>'


def xlsx_bytes(report, columns):
    header, body = table(report, columns)
    rows = [(cells, 2) for cells in _title_lines(report)] + [([], 0), (header, 2)] + [(r, 0) for r in body]
    rows += [([], 0)] + [([_safe_text(n)], 0) for n in report.warnings + report.notes]
    if report.totals:
        total_index = len(_title_lines(report)) + 2 + len(body)  # 1-based row of the totals line
    xml_rows = []
    for r, (cells, style) in enumerate(rows, start=1):
        bold_total = report.totals and r == total_index
        xml_rows.append(f'<row r="{r}">' + "".join(
            _cell(f"{_col(c)}{r}", v, 3 if bold_total and isinstance(v, (int, float, Decimal)) else (2 if bold_total else style))
            for c, v in enumerate(cells)) + "</row>")
    widths = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{28 if i == 0 else 18}" customWidth="1"/>' for i in range(len(header)))
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             f'<cols>{widths}</cols><sheetData>{"".join(xml_rows)}</sheetData></worksheet>')
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.00"/></numFmts>'
              '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
              '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
              '<borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs>'
              '<cellXfs count="4"><xf/><xf numFmtId="164" applyNumberFormat="1"/><xf fontId="1" applyFont="1"/>'
              '<xf numFmtId="164" fontId="1" applyNumberFormat="1" applyFont="1"/></cellXfs></styleSheet>')
    sheet_name = escape(report.title[:31].replace("/", "-"))
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{sheet_name}" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '</Relationships>',
        "xl/worksheets/sheet1.xml": sheet,
        "xl/styles.xml": styles,
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def xlsx_response(report, columns):
    response = HttpResponse(xlsx_bytes(report, columns),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{_filename(report, "xlsx")}"'
    return response
