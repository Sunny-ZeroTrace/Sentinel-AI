"""
PDF text extraction — pure Python via pypdf, no network required.

Previously, uploaded PDFs were saved to disk but never actually read: only
.txt files were indexed for chat/search/NLP flagging. This module fixes
that gap so PDFs feed into the same pipeline as .txt evidence.
"""
try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None


def is_available() -> bool:
    return PdfReader is not None


def extract_text(path: str) -> str:
    """Best-effort text extraction. Returns '' (not an exception) on any
    failure, so callers can just check truthiness and move on — a
    scanned/image-only PDF with no extractable text is a normal case, not
    an error."""
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(path)
        pages_text = []
        for page in reader.pages:
            try:
                pages_text.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n".join(pages_text).strip()
    except Exception:
        return ""
