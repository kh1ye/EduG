"""RAG retrieval helpers for document-grounded teaching answers."""
from __future__ import annotations

import re
import contextlib
import io
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from dashscope import TextEmbedding

from app.core import config as app_config
from app.core.chroma import add_document_chunks, create_document_collection, get_collection_stats, query_document_chunks
from app.core.logging_config import get_logger
from app.services.document_text import extract_uploaded_text, find_uploaded_file

logger = get_logger(__name__)


@dataclass
class RetrievedChunk:
    content: str
    metadata: Dict[str, Any]
    distance: float
    source_label: str


def _normalize_text(text: str, max_chars: int = 1200) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:max_chars]


def _query_embedding(query: str) -> Optional[List[float]]:
    try:
        import dashscope

        dashscope.api_key = app_config.settings.DASHSCOPE_API_KEY
        response = TextEmbedding.call(
            model="text-embedding-v2",
            input=query,
            text_type="query",
        )
        if response.status_code != 200:
            logger.warning(f"RAG query embedding failed: {response.message}")
            return None
        return response.output["embeddings"][0]["embedding"]
    except Exception as exc:
        logger.warning(f"RAG query embedding exception: {exc}")
        return None


def _format_source_label(index: int, metadata: Dict[str, Any]) -> str:
    page = metadata.get("page") or metadata.get("page_number")
    chunk_id = metadata.get("chunk_id") or metadata.get("index")
    title = metadata.get("title") or metadata.get("source_file") or metadata.get("source")

    parts = [f"chunk {index}"]
    if page:
        parts.append(f"page {page}")
    if chunk_id is not None:
        parts.append(f"id {chunk_id}")
    if title:
        parts.append(str(title).split("\\")[-1].split("/")[-1][:40])
    return " / ".join(parts)


def _keyword_fallback(document, query: str, max_chunks: int = 3) -> List[RetrievedChunk]:
    """Fallback recall from the uploaded file when vector search is unavailable."""
    text = extract_uploaded_text(document, max_chars=60000)
    if not text:
        return []

    keywords = [
        token
        for token in re.split(r"[\s,，。！？；;:：、()（）\[\]【】]+", query)
        if len(token) >= 2
    ][:8]

    windows: List[RetrievedChunk] = []
    used_ranges: List[tuple[int, int]] = []
    for keyword in keywords:
        pos = text.lower().find(keyword.lower())
        if pos < 0:
            continue
        start = max(0, pos - 500)
        end = min(len(text), pos + 900)
        if any(not (end < s or start > e) for s, e in used_ranges):
            continue
        used_ranges.append((start, end))
        windows.append(
            RetrievedChunk(
                content=_normalize_text(text[start:end]),
                metadata={"source": "uploaded_file", "fallback": True},
                distance=1.0,
                source_label=f"file fallback chunk {len(windows) + 1}",
            )
        )
        if len(windows) >= max_chunks:
            break

    if not windows:
        windows.append(
            RetrievedChunk(
                content=_normalize_text(text[:1400]),
                metadata={"source": "uploaded_file", "fallback": True},
                distance=1.0,
                source_label="file fallback beginning",
            )
        )

    return windows


async def rebuild_document_index(document) -> Dict[str, Any]:
    """Rebuild the ChromaDB vector index for an uploaded document."""
    file_path = find_uploaded_file(document)
    if not file_path:
        return {
            "ok": False,
            "status": "file_missing",
            "message": "Uploaded source file was not found.",
        }

    from app.services.document_processor import DocumentProcessor

    processor = DocumentProcessor()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        result = await processor.process_document(
            str(file_path),
            metadata={
                "document_id": getattr(document, "id", None),
                "title": getattr(document, "title", "") or getattr(document, "filename", ""),
                "filename": getattr(document, "filename", ""),
                "md5": document.md5_hash,
            },
        )

    chunks = result["chunks"]
    embeddings = result["embeddings"]
    chunk_texts = [chunk.page_content for chunk in chunks]
    chunk_metadata = [chunk.metadata.copy() for chunk in chunks]

    create_document_collection(document.md5_hash)
    add_document_chunks(
        md5_hash=document.md5_hash,
        chunks=chunk_texts,
        embeddings=embeddings,
        metadata=chunk_metadata,
    )

    stats = get_collection_stats(document.md5_hash) or {}
    return {
        "ok": True,
        "status": "indexed",
        "chunk_count": len(chunk_texts),
        "embedding_count": len(embeddings),
        "collection": stats,
    }


def retrieve_context(
    *,
    document,
    query: str,
    chapter_title: str = "",
    chapter_number: Optional[int] = None,
    subsection_title: Optional[str] = None,
    conversation_hint: str = "",
    n_results: int = 5,
) -> Dict[str, Any]:
    """Retrieve document-grounded context for a user query."""
    if not document or not getattr(document, "md5_hash", None):
        return {"context": "", "chunks": [], "status": "no_document"}

    search_query = "\n".join(
        part
        for part in [
            query,
            f"chapter: {chapter_title}" if chapter_title else "",
            f"chapter_number: {chapter_number}" if chapter_number else "",
            f"subsection: {subsection_title}" if subsection_title else "",
            conversation_hint,
        ]
        if part
    )

    chunks: List[RetrievedChunk] = []
    stats = get_collection_stats(document.md5_hash)
    embedding = _query_embedding(search_query)

    if stats and stats.get("count", 0) > 0 and embedding:
        try:
            results = query_document_chunks(
                md5_hash=document.md5_hash,
                query_embedding=embedding,
                n_results=n_results,
            )
            docs = (results.get("documents") or [[]])[0] or []
            metas = (results.get("metadatas") or [[]])[0] or []
            distances = (results.get("distances") or [[]])[0] or []

            for idx, doc_text in enumerate(docs, 1):
                metadata = metas[idx - 1] if idx - 1 < len(metas) and metas[idx - 1] else {}
                distance = distances[idx - 1] if idx - 1 < len(distances) else 0.0
                chunks.append(
                    RetrievedChunk(
                        content=_normalize_text(doc_text),
                        metadata=metadata,
                        distance=float(distance or 0.0),
                        source_label=_format_source_label(idx, metadata),
                    )
                )
        except Exception as exc:
            logger.warning(f"ChromaDB RAG retrieval failed: {exc}")

    status = "vector"
    if not chunks:
        chunks = _keyword_fallback(document, search_query, max_chunks=min(3, n_results))
        status = "fallback" if chunks else "empty"

    context_parts = []
    for idx, chunk in enumerate(chunks, 1):
        context_parts.append(f"[source {idx}: {chunk.source_label}]\n{chunk.content}")

    return {
        "context": "\n\n".join(context_parts),
        "chunks": [
            {
                "content": chunk.content,
                "metadata": chunk.metadata,
                "distance": chunk.distance,
                "source_label": chunk.source_label,
            }
            for chunk in chunks
        ],
        "status": status,
    }
