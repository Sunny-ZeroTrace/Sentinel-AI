"""
Case-scoped document search — pure Python, no vector DB, no embedding
model download, no internet required. This replaces an earlier chromadb-
based version that could throw confusing "index"/collection errors and
needed to download an embedding model from the internet on first use.

Search is a simple word-overlap scoring (a lightweight TF-style ranking):
good enough to find the right evidence chunk for citations in a small,
per-case document set, with zero extra moving parts to break.
"""
import json
import re

from config import get_data_root

STORE_FILENAME = "rag_store.json"
_WORD_RE = re.compile(r"[a-z0-9']+")


def _store_path():
    return get_data_root() / STORE_FILENAME


def _load_store() -> dict:
    p = _store_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_store(store: dict) -> None:
    _store_path().write_text(json.dumps(store, indent=2), encoding="utf-8")


def _tokenize(text: str):
    return _WORD_RE.findall(text.lower())


def add_document(case_id: str, doc_id: str, text: str, source_label: str) -> None:
    """Adds (or replaces, if doc_id already exists) one document under a case."""
    store = _load_store()
    docs = store.setdefault(case_id, [])
    store[case_id] = [d for d in docs if d["id"] != doc_id]
    store[case_id].append({"id": doc_id, "text": text, "source": source_label})
    _save_store(store)


def delete_case_documents(case_id: str) -> None:
    """Removes all indexed documents for a case — called when a case is
    deleted, so the search index doesn't accumulate orphaned entries."""
    store = _load_store()
    if case_id in store:
        del store[case_id]
        _save_store(store)


def search_case(case_id: str, query: str, n_results: int = 5):
    store = _load_store()
    docs = store.get(case_id, [])
    if not docs:
        return []

    query_words = set(_tokenize(query))
    if not query_words:
        return []

    scored = []
    for d in docs:
        doc_words = _tokenize(d["text"])
        if not doc_words:
            continue
        overlap = sum(1 for w in doc_words if w in query_words)
        if overlap == 0:
            continue
        score = overlap / (len(doc_words) ** 0.5)  # mild length normalization
        scored.append((score, d))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"text": d["text"][:3000], "source": d["source"]} for _, d in scored[:n_results]]


def answer_with_citations(case_id: str, question: str) -> dict:
    """RAG-style answer: retrieves relevant chunks, then asks the local LLM
    to answer grounded only in them, with source labels attached."""
    import llm_client  # local import avoids a circular import at module load

    hits = search_case(case_id, question)
    if not hits:
        return {
            "answer": "No indexed documents/evidence for this case yet, or "
                      "nothing matched your question — try adding evidence "
                      "or notes first.",
            "sources": [],
        }

    context = "\n\n".join(f"[Source: {h['source']}]\n{h['text']}" for h in hits)
    prompt = (
        "Answer the investigator's question using ONLY the context below. "
        "If the answer isn't in the context, say so plainly. Cite which "
        "source(s) you used by their [Source: ...] label.\n\n"
        f"Context:\n{context}\n\nQuestion: {question}"
    )
    try:
        result = llm_client.call_llm(prompt)
        answer = result.text
    except Exception as e:
        answer = f"(Local LLM unavailable right now: {e}) Raw matching excerpts are shown below."

    return {"answer": answer, "sources": [h["source"] for h in hits]}
