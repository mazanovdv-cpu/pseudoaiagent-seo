from app.report import build_report_pdf


def test_report_pdf_accepts_cyrillic() -> None:
    pdf = build_report_pdf("Семантическое ядро\nкластер «пример»", "Отчет")
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000
