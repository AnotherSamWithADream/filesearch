"""Per-type content extraction.

Returns a small ``Extracted`` describing how the file should be handled:

  * kind="text"  -> ``content`` holds extracted text for the text model
  * kind="image" -> route the file itself to the vision model (no text)
  * kind="none"  -> not a content type we read; index metadata only

All readers are defensive: any failure yields empty content rather than raising,
so one unreadable file never stops a scan.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from charset_normalizer import from_bytes

# Extensions read as plain text (documents, code, config, data).
TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".rst", ".log", ".text", ".tex",
    ".csv", ".tsv", ".json", ".jsonl", ".ndjson", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".env", ".properties",
    ".xml", ".html", ".htm", ".css", ".rtf",
    # code
    ".py", ".pyi", ".ipynb", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".java", ".kt", ".kts", ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp",
    ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".scala", ".sh", ".bash",
    ".zsh", ".ps1", ".bat", ".cmd", ".sql", ".r", ".m", ".lua", ".pl",
    ".vue", ".svelte", ".dart", ".gradle", ".dockerfile", ".makefile",
}
PDF_EXTS = {".pdf"}
DOCX_EXTS = {".docx", ".docm"}
XLSX_EXTS = {".xlsx", ".xlsm"}
PPTX_EXTS = {".pptx", ".pptm"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}


@dataclass
class Extracted:
    kind: str  # "text" | "image" | "none"
    content: str = ""


def _read_text(path: Path, cap: int) -> str:
    try:
        # Read a bounded number of bytes so huge files stay cheap.
        raw = path.read_bytes()[: max(cap * 4, 65_536)]
    except Exception:
        return ""
    if not raw:
        return ""
    try:
        best = from_bytes(raw).best()
        text = str(best) if best is not None else raw.decode("utf-8", "replace")
    except Exception:
        text = raw.decode("utf-8", "replace")
    return text[:cap]


def _read_pdf(path: Path, cap: int) -> str:
    try:
        import fitz  # pymupdf

        parts: list[str] = []
        total = 0
        with fitz.open(str(path)) as doc:
            for i, page in enumerate(doc):
                if i >= 25 or total >= cap:
                    break
                t = page.get_text()
                if t:
                    parts.append(t)
                    total += len(t)
        return "".join(parts)[:cap]
    except Exception:
        return ""


def _read_docx(path: Path, cap: int) -> str:
    try:
        import docx

        doc = docx.Document(str(path))
        parts: list[str] = []
        total = 0
        for p in doc.paragraphs:
            if p.text:
                parts.append(p.text)
                total += len(p.text)
            if total >= cap:
                break
        return "\n".join(parts)[:cap]
    except Exception:
        return ""


def _read_xlsx(path: Path, cap: int) -> str:
    try:
        import openpyxl

        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        parts: list[str] = []
        total = 0
        for ws in wb.worksheets:
            parts.append(f"# Sheet: {ws.title}")
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None]
                if cells:
                    line = "\t".join(cells)
                    parts.append(line)
                    total += len(line)
                if total >= cap:
                    break
            if total >= cap:
                break
        wb.close()
        return "\n".join(parts)[:cap]
    except Exception:
        return ""


def _read_pptx(path: Path, cap: int) -> str:
    try:
        from pptx import Presentation

        prs = Presentation(str(path))
        parts: list[str] = []
        total = 0
        for slide in prs.slides:
            for shape in slide.shapes:
                if shape.has_text_frame and shape.text_frame.text:
                    t = shape.text_frame.text
                    parts.append(t)
                    total += len(t)
            if total >= cap:
                break
        return "\n".join(parts)[:cap]
    except Exception:
        return ""


def classify(ext: str) -> str:
    ext = ext.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in TEXT_EXTS or ext in PDF_EXTS or ext in DOCX_EXTS or ext in XLSX_EXTS or ext in PPTX_EXTS:
        return "text"
    return "none"


def extract(path: str, ext: str, cap: int, index_images: bool) -> Extracted:
    """Extract content for a single file according to its type."""
    ext = ext.lower()
    p = Path(path)
    if ext in IMAGE_EXTS:
        return Extracted("image" if index_images else "none")
    if ext in TEXT_EXTS:
        return Extracted("text", _read_text(p, cap))
    if ext in PDF_EXTS:
        return Extracted("text", _read_pdf(p, cap))
    if ext in DOCX_EXTS:
        return Extracted("text", _read_docx(p, cap))
    if ext in XLSX_EXTS:
        return Extracted("text", _read_xlsx(p, cap))
    if ext in PPTX_EXTS:
        return Extracted("text", _read_pptx(p, cap))
    return Extracted("none")
