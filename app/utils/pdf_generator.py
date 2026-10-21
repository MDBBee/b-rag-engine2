from io import BytesIO

from bs4 import BeautifulSoup, NavigableString, Tag
from markdown import markdown
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def markdown_to_pdf(markdown_text: str, title: str = "Summary") -> bytes:
    """Convert markdown text to PDF bytes.

    Pipeline: markdown → HTML → BeautifulSoup → reportlab flowables.

    Args:
        markdown_text: Markdown-formatted text
        title: Title to display at top of PDF

    Returns:
        PDF file as bytes
    """
    if not markdown_text or not markdown_text.strip():
        markdown_text = "No content"

    html = markdown(
        markdown_text,
        extensions=["fenced_code", "tables", "extra"],
    )

    soup = BeautifulSoup(html, "html.parser")

    buffer = BytesIO()
    pdf = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=18,
        spaceAfter=12,
        alignment=TA_LEFT,
    )
    elements.append(Paragraph(title, title_style))
    elements.append(Spacer(1, 12))

    for child in soup.children:
        if isinstance(child, Tag):
            elements.extend(_convert_element(child, styles))

    if not elements or elements == [Paragraph(title, title_style), Spacer(1, 12)]:
        elements.append(Paragraph("No content", styles["Normal"]))

    pdf.build(elements)
    buffer.seek(0)
    return buffer.read()


def _convert_element(element: Tag, styles) -> list:
    """Convert a single HTML element to reportlab flowables."""
    tag = element.name
    result = []

    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        level = int(tag[1])
        style_name = f"Heading{min(level, 3)}"
        text = _get_inline_text(element)
        result.append(Paragraph(text, styles[style_name]))
        result.append(Spacer(1, 4))

    elif tag == "p":
        text = _get_inline_text(element)
        if text.strip():
            result.append(Paragraph(text, styles["Normal"]))
            result.append(Spacer(1, 4))

    elif tag == "pre":
        code_tag = element.find("code")
        if code_tag:
            code_text = code_tag.get_text()
        else:
            code_text = element.get_text()

        if code_text.strip():
            code_style = ParagraphStyle(
                "CodeBlock",
                parent=styles["Code"],
                fontSize=9,
                leading=12,
                leftIndent=10,
                rightIndent=10,
                spaceBefore=6,
                spaceAfter=6,
            )
            result.append(Preformatted(code_text, code_style))

    elif tag in ("ul", "ol"):
        result.extend(_convert_list(element, styles, ordered=(tag == "ol")))

    elif tag == "blockquote":
        text = _get_inline_text(element)
        bq_style = ParagraphStyle(
            "BlockQuote",
            parent=styles["Normal"],
            leftIndent=20,
            fontName="Helvetica-Oblique",
            textColor="#555555",
            spaceBefore=6,
            spaceAfter=6,
        )
        result.append(Paragraph(text, bq_style))

    elif tag == "table":
        result.extend(_convert_table(element, styles))

    elif tag == "hr":
        result.append(Spacer(1, 6))

    return result


def _convert_list(element: Tag, styles, ordered: bool = False) -> list:
    """Convert a <ul> or <ol> element to a ListFlowable."""
    items = []
    for i, li in enumerate(element.find_all("li", recursive=False), 1):
        text = _get_inline_text(li)
        if text.strip():
            if ordered:
                bullet = f"{i}."
            else:
                bullet = "bullet"
            items.append(ListItem(Paragraph(text, styles["Normal"]), bullet=bullet))

    if items:
        return [ListFlowable(items, bulletType="bullet" if not ordered else "1")]
    return []


def _convert_table(element: Tag, styles) -> list:
    """Convert a <table> element to a reportlab Table."""
    rows = []
    header_rows = 0

    thead = element.find("thead")
    if thead:
        for tr in thead.find_all("tr"):
            row = [_get_inline_text(td) or " " for td in tr.find_all(["th", "td"])]
            rows.append(row)
        header_rows = 1

    tbody = element.find("tbody")
    if tbody:
        for tr in tbody.find_all("tr"):
            row = [_get_inline_text(td) or " " for td in tr.find_all(["td", "th"])]
            rows.append(row)
    else:
        for tr in element.find_all("tr", recursive=False):
            row = [_get_inline_text(td) or " " for td in tr.find_all(["td", "th"])]
            if row:
                rows.append(row)

    if not rows:
        return []

    table = Table(rows, repeatRows=header_rows)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, "#CCCCCC"),
                ("BACKGROUND", (0, 0), (-1, header_rows - 1), "#F0F0F0"),
                ("FONTNAME", (0, 0), (-1, header_rows - 1), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    return [Spacer(1, 6), table, Spacer(1, 6)]


def _get_inline_text(element: Tag) -> str:
    """Extract text from element, preserving inline formatting as HTML tags.

    Converts inline HTML (bold, italic, code, links) to reportlab-compatible
    HTML-like markup that Paragraph can render.
    """
    parts = []

    for child in element.children:
        if isinstance(child, NavigableString):
            text = str(child)
            text = _escape_html(text)
            parts.append(text)
        elif isinstance(child, Tag):
            if child.name == "strong" or child.name == "b":
                inner = _get_inline_text(child)
                parts.append(f"<b>{inner}</b>")
            elif child.name == "em" or child.name == "i":
                inner = _get_inline_text(child)
                parts.append(f"<i>{inner}</i>")
            elif child.name == "code":
                inner = _escape_html(child.get_text())
                parts.append(f'<font face="Courier">{inner}</font>')
            elif child.name == "a":
                href = child.get("href", "")
                inner = _get_inline_text(child)
                parts.append(f'<a href="{href}">{inner}</a>')
            elif child.name == "br":
                parts.append("<br/>")
            elif child.name == "sub":
                inner = _get_inline_text(child)
                parts.append(f"<sub>{inner}</sub>")
            elif child.name == "sup":
                inner = _get_inline_text(child)
                parts.append(f"<super>{inner}</super>")
            else:
                parts.append(_get_inline_text(child))

    return "".join(parts)


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
