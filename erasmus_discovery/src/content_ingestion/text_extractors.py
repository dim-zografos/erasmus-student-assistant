from io import BytesIO
import re
import zipfile
from xml.etree import ElementTree

from bs4 import BeautifulSoup
from pypdf import PdfReader

from ..utils import compact_whitespace


XML_TEXT_TAGS = {
    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t",
    "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t",
}


def extract_text(data: bytes, content_type: str, url: str = "") -> str:
    content_type = (content_type or "").lower()
    if content_type == "html":
        return extract_html_text(data)
    if content_type == "pdf":
        return extract_pdf_text(data)
    if content_type == "docx":
        return extract_docx_text(data)
    if content_type == "xlsx":
        return extract_xlsx_text(data)
    if content_type == "doc":
        return extract_legacy_doc_text(data)
    if content_type == "xls":
        return extract_legacy_xls_text(data)
    return extract_plain_text(data)


def extract_html_text(data: bytes) -> str:
    soup = BeautifulSoup(data, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "aside"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    headings = [tag.get_text(" ", strip=True) for tag in soup.find_all(["h1", "h2", "h3"])]
    body_text = soup.get_text("\n", strip=True)
    parts = [title, *headings, body_text]
    return clean_extracted_text("\n".join(part for part in parts if part))


def extract_pdf_text(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return clean_extracted_text("\n".join(pages))


def extract_docx_text(data: bytes) -> str:
    with zipfile.ZipFile(BytesIO(data)) as docx:
        with docx.open("word/document.xml") as document:
            root = ElementTree.fromstring(document.read())
    paragraphs = []
    current = []
    for element in root.iter():
        if element.tag in XML_TEXT_TAGS and element.text:
            current.append(element.text)
        elif element.tag.endswith("}p") and current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return clean_extracted_text("\n".join(paragraphs))


def extract_xlsx_text(data: bytes) -> str:
    with zipfile.ZipFile(BytesIO(data)) as xlsx:
        shared_strings = _read_shared_strings(xlsx)
        sheet_names = [name for name in xlsx.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")]
        rows = []
        for sheet_name in sheet_names:
            rows.extend(_read_sheet_rows(xlsx, sheet_name, shared_strings))
    return clean_extracted_text("\n".join(rows))


def extract_legacy_doc_text(data: bytes) -> str:
    if _looks_like_ole_binary(data):
        raise ValueError("Legacy .doc parsing is not available without additional dependencies.")
    text = extract_plain_text(data)
    if len(text) < 100 or _looks_like_binary_text(text):
        raise ValueError("Legacy .doc parsing is not available without additional dependencies.")
    return text


def extract_legacy_xls_text(data: bytes) -> str:
    if not _looks_like_ole_binary(data):
        text = extract_plain_text(data)
        if len(text) >= 100 and not _looks_like_binary_text(text):
            return text

    try:
        import pandas as pd
    except ImportError as exc:
        raise ValueError("Legacy .xls parsing requires pandas and xlrd.") from exc

    try:
        sheets = pd.read_excel(BytesIO(data), sheet_name=None, header=None, dtype=str, engine="xlrd")
    except ImportError as exc:
        raise ValueError("Legacy .xls parsing requires xlrd. Install project requirements.") from exc
    except Exception as exc:
        raise ValueError(f"Legacy .xls parsing failed: {exc}") from exc

    rows = []
    for sheet_name, frame in sheets.items():
        if frame.empty:
            continue
        rows.append(f"Sheet: {sheet_name}")
        frame = frame.fillna("")
        for values in frame.astype(str).values.tolist():
            cells = [_clean_cell_value(value) for value in values]
            row_text = " | ".join(cell for cell in cells if cell)
            if row_text:
                rows.append(row_text)
    return clean_extracted_text("\n".join(rows))


def extract_plain_text(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "windows-1253", "latin-1"):
        try:
            return clean_extracted_text(data.decode(encoding))
        except UnicodeDecodeError:
            continue
    return clean_extracted_text(data.decode("utf-8", errors="ignore"))


def clean_extracted_text(text: str) -> str:
    lines = []
    for line in (text or "").splitlines():
        line = compact_whitespace(line)
        if line:
            lines.append(line)
    return "\n".join(lines)


def _read_shared_strings(xlsx: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in xlsx.namelist():
        return []
    root = ElementTree.fromstring(xlsx.read("xl/sharedStrings.xml"))
    strings = []
    for item in root:
        texts = [element.text or "" for element in item.iter() if element.tag in XML_TEXT_TAGS]
        strings.append("".join(texts))
    return strings


def _read_sheet_rows(xlsx: zipfile.ZipFile, sheet_name: str, shared_strings: list[str]) -> list[str]:
    root = ElementTree.fromstring(xlsx.read(sheet_name))
    rows = []
    for row in root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"):
        values = []
        for cell in row.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"):
            cell_type = cell.attrib.get("t")
            value_element = cell.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
            inline_text = cell.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}is")
            value = ""
            if cell_type == "s" and value_element is not None and value_element.text:
                index = int(value_element.text)
                value = shared_strings[index] if 0 <= index < len(shared_strings) else ""
            elif inline_text is not None:
                value = " ".join(element.text or "" for element in inline_text.iter() if element.tag in XML_TEXT_TAGS)
            elif value_element is not None and value_element.text:
                value = value_element.text
            values.append(_clean_cell_value(value))
        row_text = " | ".join(value for value in values if value)
        if row_text:
            rows.append(row_text)
    return rows


def _clean_cell_value(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _looks_like_ole_binary(data: bytes) -> bool:
    return data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")


def _looks_like_binary_text(text: str) -> bool:
    if not text:
        return True
    sample = text[:4000]
    control_chars = sum(1 for char in sample if ord(char) < 32 and char not in "\n\r\t")
    replacement_chars = sample.count("\ufffd")
    readable_chars = sum(1 for char in sample if char.isalnum() or char.isspace() or char in ".,;:!?()[]{}-/+_&%€$'\"")
    if control_chars + replacement_chars > max(10, len(sample) * 0.02):
        return True
    return readable_chars < len(sample) * 0.65
