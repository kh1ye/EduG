"""Utilities for reading uploaded document text when vector storage is missing."""
from __future__ import annotations

from pathlib import Path
from typing import Optional


def find_uploaded_file(document) -> Optional[Path]:
    """Locate the uploaded file for a document record."""
    uploads_dir = Path("uploads")
    if not uploads_dir.exists():
        return None

    candidates = [
        uploads_dir / f"{document.uploaded_by}_{document.id}_{document.filename}",
        uploads_dir / f"{document.uploaded_by}_{document.filename}",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    matches = list(uploads_dir.glob(f"*_{document.filename}"))
    return matches[0] if matches else None


def extract_uploaded_text(document, max_chars: int = 15000) -> str:
    """Extract plain text from the uploaded source file."""
    file_path = find_uploaded_file(document)
    if not file_path:
        return ""

    suffix = file_path.suffix.lower()
    try:
        if suffix == ".pdf":
            import fitz

            chunks: list[str] = []
            with fitz.open(file_path) as pdf:
                for page in pdf:
                    text = page.get_text("text").strip()
                    if text:
                        chunks.append(text)
                    if sum(len(chunk) for chunk in chunks) >= max_chars:
                        break

            return "\n\n".join(chunks)[:max_chars]

        if suffix == ".txt":
            return file_path.read_text(encoding="utf-8", errors="ignore")[:max_chars]

        if suffix == ".docx":
            from docx import Document as DocxDocument

            doc = DocxDocument(file_path)
            text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
            return text[:max_chars]
    except Exception:
        return ""

    return ""
