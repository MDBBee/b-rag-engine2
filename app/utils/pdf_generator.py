import re
from io import BytesIO

from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


def markdown_to_pdf(markdown_text: str, title: str = "Summary") -> bytes:
    """Convert markdown text to PDF bytes.
    
    Simple markdown parsing: headings, paragraphs, lists, code blocks.
    Uses reportlab's HTML-like markup for Paragraph flowables.
    
    Args:
        markdown_text: Markdown-formatted text
        title: Title to display at top of PDF
        
    Returns:
        PDF file as bytes
    """
    if not markdown_text or not markdown_text.strip():
        markdown_text = "No content"
    
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
    
    elements.extend(_parse_markdown(markdown_text, styles))
    
    pdf.build(elements)
    buffer.seek(0)
    return buffer.read()


def _parse_markdown(text: str, styles) -> list:
    """Parse markdown text into reportlab flowables."""
    elements = []
    lines = text.split("\n")
    i = 0
    in_code_block = False
    code_lines = []
    
    while i < len(lines):
        line = lines[i]
        
        if line.strip().startswith("```"):
            if in_code_block:
                code_content = "\n".join(code_lines)
                if code_content.strip():
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
                    elements.append(Paragraph(
                        code_content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"),
                        code_style
                    ))
                code_lines = []
                in_code_block = False
            else:
                in_code_block = True
            i += 1
            continue
        
        if in_code_block:
            code_lines.append(line)
            i += 1
            continue
        
        stripped = line.strip()
        
        if not stripped:
            elements.append(Spacer(1, 6))
            i += 1
            continue
        
        if stripped.startswith("# "):
            content = _escape_html(stripped[2:].strip())
            elements.append(Paragraph(content, styles["Heading1"]))
        elif stripped.startswith("## "):
            content = _escape_html(stripped[3:].strip())
            elements.append(Paragraph(content, styles["Heading2"]))
        elif stripped.startswith("### "):
            content = _escape_html(stripped[4:].strip())
            elements.append(Paragraph(content, styles["Heading3"]))
        elif stripped.startswith(("- ", "* ")):
            content = _escape_html(stripped[2:].strip())
            content = _format_inline(content)
            elements.append(Paragraph(f"• {content}", styles["Normal"]))
        elif re.match(r"^\d+\.\s", stripped):
            content = _escape_html(re.sub(r"^\d+\.\s", "", stripped))
            content = _format_inline(content)
            elements.append(Paragraph(content, styles["Normal"]))
        else:
            content = _escape_html(stripped)
            content = _format_inline(content)
            elements.append(Paragraph(content, styles["Normal"]))
        
        i += 1
    
    return elements


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_inline(text: str) -> str:
    """Convert markdown inline formatting to HTML tags for reportlab."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    text = re.sub(r"`(.+?)`", r'<font face="Courier">\1</font>', text)
    return text
