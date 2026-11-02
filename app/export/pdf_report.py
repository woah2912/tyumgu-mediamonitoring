"""Документ отчёта в формате PDF."""
import io
from html import escape
from pathlib import Path

import matplotlib
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image as PdfImage
from reportlab.platypus import ListFlowable, ListItem, Paragraph as PdfParagraph
from reportlab.platypus import CondPageBreak, SimpleDocTemplate, Spacer
from reportlab.platypus import Table as PdfTable
from reportlab.platypus import TableStyle

from app.export.template import Bullets, Heading, Image, Paragraph, Table

# Шрифт DejaVu с кириллицей уже есть в поставке matplotlib.
_FONTS = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
pdfmetrics.registerFont(TTFont("DejaVu", _FONTS / "DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", _FONTS / "DejaVuSans-Bold.ttf"))

ACCENT = colors.HexColor("#104281")
HEADER_FILL = colors.HexColor("#E8EFF8")
WARNING_FILL = colors.HexColor("#FDF1D8")
LINE = colors.HexColor("#C3C2B7")
PAGE_WIDTH = A4[0] - 4 * cm
HEADING_ROOM = 8 * cm  # заголовок не должен оставаться внизу страницы без содержимого

_BODY = ParagraphStyle("body", fontName="DejaVu", fontSize=9.5, leading=13.5, spaceAfter=6)
_CELL = ParagraphStyle("cell", fontName="DejaVu", fontSize=7.5, leading=10)
_HEAD = ParagraphStyle("head", parent=_CELL, fontName="DejaVu-Bold")
_H1 = ParagraphStyle("h1", fontName="DejaVu-Bold", fontSize=13, leading=17, textColor=ACCENT, spaceBefore=12, spaceAfter=6)
_TITLE = ParagraphStyle("title", fontName="DejaVu-Bold", fontSize=20, leading=25, textColor=ACCENT, spaceAfter=6)
_SMALL = ParagraphStyle("small", fontName="DejaVu", fontSize=8, leading=11, spaceAfter=10, textColor=colors.HexColor("#52514E"))
_CAPTION = ParagraphStyle("caption", parent=_SMALL, alignment=TA_CENTER)


def _text(value: str, style: ParagraphStyle) -> PdfParagraph:
    return PdfParagraph(escape(value), style)


def _table(block: Table) -> PdfTable:
    rows = [[_text(item, _HEAD) for item in block.header]]
    rows += [[_text(item, _CELL) for item in row] for row in block.rows]
    table = PdfTable(rows, colWidths=[PAGE_WIDTH * share for share in block.widths], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HEADER_FILL),
                ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _image(block: Image):
    width, height = ImageReader(io.BytesIO(block.data)).getSize()
    return PdfImage(io.BytesIO(block.data), width=PAGE_WIDTH, height=PAGE_WIDTH * height / width)


def _footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setFont("DejaVu", 7.5)
    canvas.setFillColor(colors.HexColor("#898781"))
    canvas.drawString(2 * cm, 1.2 * cm, "Медиамониторинг ТюмГУ")
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, str(document.page))
    canvas.restoreState()


def render_pdf(report, blocks: list) -> bytes:
    story = [
        _text("Отчёт о медиамониторинге", _TITLE),
        _text(report.title, _BODY),
        _text(f"Управление стратегических коммуникаций ТюмГУ · сформирован {report.created_at:%d.%m.%Y}", _SMALL),
    ]
    for block in blocks:
        if isinstance(block, Heading):
            story += [CondPageBreak(HEADING_ROOM), _text(block.text, _H1)]
        elif isinstance(block, Paragraph):
            if block.warning:
                warning = PdfTable([[_text(block.text, _HEAD)]], colWidths=[PAGE_WIDTH])
                warning.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), WARNING_FILL), ("BOX", (0, 0), (-1, -1), 0.4, LINE)]))
                story += [warning, Spacer(1, 8)]
            else:
                story.append(_text(block.text, _BODY))
        elif isinstance(block, Bullets):
            items = [ListItem(_text(item, _BODY), leftIndent=12) for item in block.items]
            story.append(ListFlowable(items, bulletType="bullet", start="•", leftIndent=12))
        elif isinstance(block, Image):
            story += [_image(block), _text(block.caption, _CAPTION)]
        elif isinstance(block, Table):
            story += [_table(block), Spacer(1, 8)]

    buffer = io.BytesIO()
    template = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm, bottomMargin=1.8 * cm,
        title=report.title, author="Медиамониторинг ТюмГУ",
    )
    template.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()
