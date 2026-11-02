"""Документ отчёта в формате DOCX."""
import io

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from app.export.template import Bullets, Heading, Image, Paragraph, Table

ACCENT = RGBColor(0x10, 0x42, 0x81)
HEADER_FILL = "E8EFF8"
WARNING_FILL = "FDF1D8"
PAGE_WIDTH_CM = 17.0


def _shade(cell, color: str) -> None:
    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:color"), "auto")
    shading.set(qn("w:fill"), color)
    cell._tc.get_or_add_tcPr().append(shading)


def _write_cell(cell, text: str, bold: bool = False) -> None:
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_after = Pt(1)
    run = paragraph.add_run(text)
    run.font.size = Pt(9)
    run.bold = bold


def _add_table(document, block: Table) -> None:
    table = document.add_table(rows=1, cols=len(block.header))
    table.style = "Table Grid"
    table.autofit = False
    for index, title in enumerate(block.header):
        _write_cell(table.rows[0].cells[index], title, bold=True)
        _shade(table.rows[0].cells[index], HEADER_FILL)
    repeat = OxmlElement("w:tblHeader")
    table.rows[0]._tr.get_or_add_trPr().append(repeat)
    for row in block.rows:
        cells = table.add_row().cells
        for index, value in enumerate(row):
            _write_cell(cells[index], value)
    for row in table.rows:
        for index, share in enumerate(block.widths):
            row.cells[index].width = Cm(PAGE_WIDTH_CM * share)
    document.add_paragraph()


def _add_warning(document, text: str) -> None:
    table = document.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    _write_cell(table.rows[0].cells[0], text, bold=True)
    _shade(table.rows[0].cells[0], WARNING_FILL)
    document.add_paragraph()


def render_docx(report, blocks: list) -> bytes:
    document = Document()
    section = document.sections[0]
    section.left_margin = section.right_margin = Cm(2)
    section.top_margin = section.bottom_margin = Cm(2)

    style = document.styles["Normal"]
    style.font.name = "Calibri"
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    style.font.size = Pt(11)

    title = document.add_paragraph()
    run = title.add_run("Отчёт о медиамониторинге")
    run.bold = True
    run.font.size = Pt(22)
    run.font.color.rgb = ACCENT
    subtitle = document.add_paragraph(report.title)
    subtitle.runs[0].font.size = Pt(12)
    created = document.add_paragraph(f"Управление стратегических коммуникаций ТюмГУ · сформирован {report.created_at:%d.%m.%Y}")
    created.runs[0].font.size = Pt(9)

    for block in blocks:
        if isinstance(block, Heading):
            heading = document.add_heading(block.text, level=1)
            for item in heading.runs:
                item.font.color.rgb = ACCENT
                item.font.size = Pt(14)
                item.font.name = "Calibri"
        elif isinstance(block, Paragraph):
            if block.warning:
                _add_warning(document, block.text)
            else:
                document.add_paragraph(block.text)
        elif isinstance(block, Bullets):
            for item in block.items:
                document.add_paragraph(item, style="List Bullet")
        elif isinstance(block, Image):
            document.add_picture(io.BytesIO(block.data), width=Cm(PAGE_WIDTH_CM))
            document.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            caption = document.add_paragraph(block.caption)
            caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
            caption.runs[0].font.size = Pt(9)
        elif isinstance(block, Table):
            _add_table(document, block)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
