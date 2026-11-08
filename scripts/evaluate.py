"""Сравнивает работу системы с эталонной разметкой синтетических новостей.

Результат показывает, что конвейер работает согласованно, но не качество на реальных
СМИ: словарь и правила настраивались на тех же 100 текстах.
Запуск: python -m scripts.evaluate
"""
import json
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _accuracy(pairs) -> float:
    return sum(1 for expected, actual in pairs if expected == actual) / len(pairs) if pairs else 0.0


def _confusion(title, pairs) -> None:
    print(f"\n{title}: точность {_accuracy(pairs):.1%} на {len(pairs)} публикациях")
    errors = Counter(pair for pair in pairs if pair[0] != pair[1])
    for (expected, actual), count in errors.most_common(12):
        print(f"  ожидалось {expected:<12} получено {actual:<12} — {count}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    import os

    os.environ["MM_DATA_DIR"] = tempfile.mkdtemp(prefix="mm-eval-")
    from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score
    from sqlalchemy import select

    from app import seed
    from app.db import publications_session, reports_session
    from app.models import MonitoringObject, Publication, Report, ReportPublication, Source
    from app.nlp.sentiment import method_name
    from app.pipeline.report import ALL_CONTEXTS, ReportRequest, finish_report, start_report

    print("Метод тональности:", method_name())
    seed.seed(with_synthetic=True)
    dataset = json.loads((ROOT / "data" / "synthetic_news.json").read_text(encoding="utf-8"))
    labels = {entry["url"]: entry["labels"] for entry in dataset["publications"]}

    with publications_session() as session:
        object_id = session.scalar(select(MonitoringObject.id).where(MonitoringObject.name == "ТюмГУ"))
        source_ids = list(session.scalars(select(Source.id).where(Source.is_synthetic)).all())
        stored = {row.url: row for row in session.scalars(select(Publication)).all()}
    print(f"Загружено публикаций: {len(stored)} из {len(labels)}")

    report_id = start_report(
        ReportRequest(object_id, ALL_CONTEXTS, datetime(2026, 8, 1), datetime(2026, 10, 31), source_ids)
    )
    finish_report(report_id)

    with reports_session() as session:
        report = session.get(Report, report_id)
        items = list(session.scalars(select(ReportPublication).where(ReportPublication.report_id == report_id)).all())
        status = report.status
    print("Статус отчёта:", status, "; публикаций в отчёте:", len(items))

    relevance, sentiment, roles, topics = [], [], [], []
    clusters_true, clusters_pred = [], []
    for item in items:
        expected = labels[item.url]
        relevance.append((expected["relevance"], item.status))
        if expected["relevance"] == "relevant":
            sentiment.append((expected["sentiment"], item.sentiment))
            roles.append((expected["role"], item.role))
            topics.append((expected["topic"], item.topic))
            if item.cluster is not None:
                clusters_true.append(expected["topic"])
                clusters_pred.append(item.cluster)

    _confusion("Релевантность и дубликаты", relevance)
    _confusion("Тональность", sentiment)
    _confusion("Роль объекта", roles)
    _confusion("Тема", topics)
    print(f"\nКластеризация: NMI {normalized_mutual_info_score(clusters_true, clusters_pred):.2f}, "
          f"ARI {adjusted_rand_score(clusters_true, clusters_pred):.2f}, кластеров {len(set(clusters_pred))}")

    wrong = [(labels[i.url]["sentiment"], i.sentiment, i.sentiment_score, i.title[:70]) for i in items
             if labels[i.url]["relevance"] == "relevant" and labels[i.url]["sentiment"] != i.sentiment]
    if "-v" in sys.argv:
        for row in wrong:
            print(row)
        for i in items:
            e = labels[i.url]
            if e["relevance"] != i.status:
                print("REL", e["relevance"], i.status, i.relevance_score, i.removal_reason[:60], "|", i.title[:60])
            if e["relevance"] == "relevant" and e["topic"] != i.topic:
                print("TOP", e["topic"], i.topic, i.title[:60])
            if e["relevance"] == "relevant" and e["role"] != i.role:
                print("ROL", e["role"], i.role, i.title[:60])


if __name__ == "__main__":
    main()
