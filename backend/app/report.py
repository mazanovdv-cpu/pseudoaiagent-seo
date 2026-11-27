"""PDF-отчёт из текста блока «Результат»."""

import re
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import WrapMode

FONT_PATH = Path(__file__).resolve().parent / "fonts" / "DejaVuSans.ttf"
_EXTRA = re.compile(r"[\U00010000-\U0010FFFF]")


def _plain(value: str) -> str:
    return _EXTRA.sub("", value.replace("\x00", "").replace("\r", "")).strip()


def build_report_pdf(text: str, title: str) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.add_font("DejaVu", "", str(FONT_PATH))
    pdf.set_font("DejaVu", size=16)
    pdf.multi_cell(0, 9, _plain(title) or "Отчет", wrapmode=WrapMode.CHAR)
    pdf.ln(3)
    pdf.set_font("DejaVu", size=11)
    pdf.multi_cell(0, 6, _plain(text) or "Пустой отчёт.", wrapmode=WrapMode.CHAR)
    return bytes(pdf.output())
