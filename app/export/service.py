"""Формирование документов отчёта и сохранение их в базу отчётов."""
from sqlalchemy import select

from app.db import reports_session
from app.export.docx_report import render_docx
from app.export.pdf_report import render_pdf
from app.export.template import build_blocks
from app.export.xlsx_report import render_xlsx
from app.models import Report, ReportDocument, ReportPublication, utcnow
from app.pipeline.report import mark_step

MIME_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def export_report(report_id: int) -> None:
    """Обрабатывает команду «Экспортировать отчёт». Повторный экспорт заменяет файлы."""
    with reports_session() as session:
        report = session.get(Report, report_id)
        items = session.scalars(select(ReportPublication).where(ReportPublication.report_id == report_id)).all()

        blocks = build_blocks(report, items)
        files = {
            "docx": render_docx(report, blocks),
            "pdf": render_pdf(report, blocks),
            "xlsx": render_xlsx(report, items),
        }

        report.documents.clear()
        session.flush()
        stamp = f"{utcnow():%Y-%m-%d}"
        for extension, content in files.items():
            report.documents.append(
                ReportDocument(
                    format=extension,
                    filename=f"Отчёт_{report.id}_{report.object_name}_{stamp}.{extension}".replace(" ", "_"),
                    mime=MIME_TYPES[extension],
                    size=len(content),
                    content=content,
                )
            )
        if report.status == "ready":
            report.status = "exported"
        report.exported_at = utcnow()
        mark_step(report, "export", "done", "Команда сотрудника получена")
        mark_step(report, "document", "done", "DOCX, PDF и XLSX сохранены в базе отчётов")
