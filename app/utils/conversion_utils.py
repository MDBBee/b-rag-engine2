import logging
import re
from io import BytesIO
from pathlib import Path

import fitz
import mammoth
from docx import Document as DocxDocument
from PIL import Image
from reportlab.lib.colors import HexColor, black, grey
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

logger = logging.getLogger(__name__)

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 36 * mm

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".webp"}
DOCX_EXTENSIONS = {".docx"}
PDF_EXTENSIONS = {".pdf"}


def image_to_pdf(image_path: str) -> tuple[bytes, int]:
    """Convert a single image to a single-page PDF. Returns (pdf_bytes, page_count)."""
    img = Image.open(image_path)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    buffer = BytesIO()
    img.save(buffer, format="PDF", resolution=100.0)
    buffer.seek(0)
    return buffer.read(), 1


def docx_to_pdf(docx_path: str) -> tuple[bytes, int]:
    """Convert a DOCX file to PDF using python-docx + reportlab. Returns (pdf_bytes, page_count)."""
    doc = DocxDocument(docx_path)
    styles = build_styles()
    elements = []

    for para in doc.paragraphs:
        elem = process_paragraph(para, styles)
        if elem:
            elements.append(elem)

    for table in doc.tables:
        elements.append(process_table(table))
        elements.append(Spacer(1, 6))

    output = BytesIO()
    pdf_doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
    )
    pdf_doc.build(elements)
    output.seek(0)
    pdf_bytes = output.read()

    page_count = count_pdf_pages(pdf_bytes)
    return pdf_bytes, page_count


def docx_to_pdf_via_mammoth(docx_path: str) -> tuple[bytes, int]:
    """Convert DOCX to PDF via mammoth (HTML intermediate) + reportlab. Fallback for .doc files."""
    with open(docx_path, "rb") as f:
        result = mammoth.convert_to_html(f)

    if result.messages:
        for msg in result.messages:
            logger.warning("Mammoth conversion message: %s", msg.message)

    html = result.value
    if not html.strip():
        raise ValueError("No content extracted from document")

    output = BytesIO()
    pdf_doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
    )

    elements = html_to_flowables(html)
    pdf_doc.build(elements)
    output.seek(0)
    pdf_bytes = output.read()

    page_count = count_pdf_pages(pdf_bytes)
    return pdf_bytes, page_count


def merge_pdfs(file_paths: list[tuple[str, str]]) -> tuple[bytes, int, list[dict]]:
    """Merge multiple files into a single PDF. Each entry is (file_path, original_filename).
    Images are converted to PDF first. Returns (pdf_bytes, total_pages, sources_metadata)."""
    merger = fitz.open()
    sources = []

    for file_path, original_filename in file_paths:
        ext = Path(file_path).suffix.lower()

        if ext in IMAGE_EXTENSIONS:
            pdf_bytes, pages = image_to_pdf(file_path)
            temp_doc = fitz.open("pdf", pdf_bytes)
            merger.insert_pdf(temp_doc)
            temp_doc.close()
            sources.append({"filename": original_filename, "pages": pages})

        elif ext in PDF_EXTENSIONS:
            doc = fitz.open(file_path)
            pages = len(doc)
            merger.insert_pdf(doc)
            doc.close()
            sources.append({"filename": original_filename, "pages": pages})

        else:
            raise ValueError(f"Unsupported file type for merge: {ext}")

    output = BytesIO()
    merger.save(output)
    merger.close()
    output.seek(0)
    pdf_bytes = output.read()

    total_pages = count_pdf_pages(pdf_bytes)
    return pdf_bytes, total_pages, sources


def count_pdf_pages(pdf_bytes: bytes) -> int:
    """Count pages in a PDF from bytes."""
    doc = fitz.open("pdf", pdf_bytes)
    count = len(doc)
    doc.close()
    return count


def build_styles() -> dict:
    """Create reportlab paragraph styles mapped to common Word styles."""
    base = getSampleStyleSheet()

    styles = {
        "Normal": ParagraphStyle(
            "Normal",
            parent=base["Normal"],
            fontSize=11,
            leading=14,
            fontName="Helvetica",
            textColor=black,
            spaceAfter=6,
        ),
        "Heading1": ParagraphStyle(
            "Heading1",
            parent=base["Heading1"],
            fontSize=18,
            leading=24,
            fontName="Helvetica-Bold",
            textColor=HexColor("#1a1a1a"),
            spaceBefore=18,
            spaceAfter=10,
        ),
        "Heading2": ParagraphStyle(
            "Heading2",
            parent=base["Heading2"],
            fontSize=14,
            leading=18,
            fontName="Helvetica-Bold",
            textColor=HexColor("#333333"),
            spaceBefore=14,
            spaceAfter=8,
        ),
        "Heading3": ParagraphStyle(
            "Heading3",
            parent=base["Heading3"],
            fontSize=12,
            leading=16,
            fontName="Helvetica-Bold",
            textColor=HexColor("#444444"),
            spaceBefore=10,
            spaceAfter=6,
        ),
        "Bold": ParagraphStyle(
            "Bold",
            parent=base["Normal"],
            fontSize=11,
            leading=14,
            fontName="Helvetica-Bold",
            spaceAfter=6,
        ),
        "Italic": ParagraphStyle(
            "Italic",
            parent=base["Normal"],
            fontSize=11,
            leading=14,
            fontName="Helvetica-Oblique",
            spaceAfter=6,
        ),
    }
    return styles


def process_paragraph(para, styles: dict):
    """Convert a python-docx paragraph to a reportlab flowable."""
    text = para.text.strip()
    if not text:
        return Spacer(1, 4)

    style_name = para.style.name.lower() if para.style else ""

    if "heading 1" in style_name:
        return Paragraph(text, styles["Heading1"])
    if "heading 2" in style_name:
        return Paragraph(text, styles["Heading2"])
    if "heading 3" in style_name:
        return Paragraph(text, styles["Heading3"])

    formatted_text = build_formatted_text(para)

    is_bold = all(run.bold for run in para.runs if run.text.strip()) and any(run.text.strip() for run in para.runs)
    is_italic = all(run.italic for run in para.runs if run.text.strip()) and any(run.text.strip() for run in para.runs)

    if is_bold:
        return Paragraph(formatted_text, styles["Bold"])
    if is_italic:
        return Paragraph(formatted_text, styles["Italic"])

    alignment = para.alignment
    if alignment is not None:
        align_map = {
            0: TA_LEFT,
            1: TA_CENTER,
            2: TA_RIGHT,
            3: TA_JUSTIFY,
        }
        style = ParagraphStyle(
            f"Custom_{id(para)}",
            parent=styles["Normal"],
            alignment=align_map.get(alignment, TA_LEFT),
        )
        return Paragraph(formatted_text, style)

    return Paragraph(formatted_text, styles["Normal"])


def build_formatted_text(para) -> str:
    """Build reportlab-compatible formatted text from a docx paragraph."""
    parts = []
    for run in para.runs:
        text = run.text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if not text:
            continue

        tags = []
        if run.bold:
            tags.append("b")
        if run.italic:
            tags.append("i")
        if run.underline:
            tags.append("u")
        if run.font.strike:
            tags.append("strike")

        for tag in tags:
            text = f"<{tag}>{text}</{tag}>"

        if run.font.size:
            size_pt = run.font.size / 12700
            text = f'<font size="{size_pt:.0f}">{text}</font>'

        parts.append(text)

    return "".join(parts) if parts else para.text


def process_table(table) -> Table:
    """Convert a python-docx table to a reportlab Table flowable."""
    data = []
    for row in table.rows:
        row_data = []
        for cell in row.cells:
            cell_text = cell.text.strip().replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            row_data.append(Paragraph(cell_text, getSampleStyleSheet()["Normal"]))
        data.append(row_data)

    col_count = len(table.columns)
    col_width = (PAGE_WIDTH - 2 * MARGIN) / col_count if col_count > 0 else 100 * mm

    tbl = Table(data, colWidths=[col_width] * col_count)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#e8e8e8")),
        ("TEXTCOLOR", (0, 0), (-1, 0), black),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, grey),
        ("BACKGROUND", (0, 1), (-1, -1), HexColor("#f8f8f8")),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return tbl


def html_to_flowables(html: str) -> list:
    """Convert simple HTML (from mammoth) to reportlab flowables. Basic implementation."""
    elements = []
    styles = getSampleStyleSheet()

    stripped = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
    stripped = re.sub(r'<script[^>]*>.*?</script>', '', stripped, flags=re.DOTALL)

    blocks = re.split(r'</(?:p|div|h[1-6]|li|ul|ol|hr|br)\s*>', stripped, flags=re.IGNORECASE)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        if re.match(r'^\s*<(h[1-6])', block, re.IGNORECASE):
            level_match = re.match(r'^\s*<(h[1-6])', block, re.IGNORECASE)
            level = int(level_match.group(1)[1]) if level_match else 1
            content = re.sub(r'<[^>]+>', '', block).strip()
            if content:
                size_map = {1: 18, 2: 14, 3: 12, 4: 11, 5: 10, 6: 9}
                style = ParagraphStyle(
                    f"H{level}",
                    parent=styles["Normal"],
                    fontSize=size_map.get(level, 11),
                    leading=size_map.get(level, 11) + 6,
                    fontName="Helvetica-Bold",
                    spaceBefore=12,
                    spaceAfter=6,
                )
                elements.append(Paragraph(content, style))

        elif re.match(r'^\s*<hr', block, re.IGNORECASE):
            elements.append(HRFlowable(width="100%", thickness=1, color=grey, spaceBefore=6, spaceAfter=6))

        elif re.match(r'^\s*<(?:p|div)', block, re.IGNORECASE):
            content = re.sub(r'<br\s*/?>', '\n', block, flags=re.IGNORECASE)
            content = re.sub(r'<[^>]+>', '', content).strip()
            if content:
                elements.append(Paragraph(content, styles["Normal"]))

    if not elements:
        plain_text = re.sub(r'<[^>]+>', '', stripped).strip()
        if plain_text:
            elements.append(Paragraph(plain_text, styles["Normal"]))

    return elements
