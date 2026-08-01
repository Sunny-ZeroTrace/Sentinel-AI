"""
Sentinel AI — FastAPI backend.
Serves the REST API under /api/* and the static frontend at /.
Run with: python server.py   (or via run.py, which also starts scheduler.py)
"""
import shutil
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

import db
import config
import llm_client
from modules import faces as faces_mod
from modules import graph as graph_mod
from modules import timeline as timeline_mod
from modules import hash_match
from modules import nlp_flags
from modules import rag_search
from modules import reports as reports_mod
from modules import gmail_client
from modules import synthetic_data
from modules import pdf_reader
from modules import image_caption
from modules import case_export
from modules.update_log import log_event, read_markdown
from modules.risk_score import compute_risk_score, priority_label

db.init_db()
config.ensure_dirs(config.get_data_root())

app = FastAPI(title="Sentinel AI API")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

FRONTEND_DIR = Path(__file__).parent / "frontend"


# --------------------------------------------------------------- local LLM

@app.get("/api/settings/ollama")
def get_ollama_settings():
    return {
        "reachable": llm_client.is_reachable(),
        "models_installed": llm_client.list_local_models(),
        "text_model": llm_client.get_text_model(),
        "vision_model": llm_client.get_vision_model(),
        "base_url": llm_client.get_base_url(),
    }


@app.post("/api/settings/ollama/test")
def test_ollama():
    ok, msg = llm_client.test_connection()
    return {"ok": ok, "message": msg}


@app.post("/api/settings/ollama")
def set_ollama_settings(
    text_model: Optional[str] = Form(None),
    vision_model: Optional[str] = Form(None),
    base_url: Optional[str] = Form(None),
):
    if text_model:
        llm_client.set_text_model(text_model)
    if vision_model:
        llm_client.set_vision_model(vision_model)
    if base_url:
        llm_client.set_base_url(base_url)
    return {"ok": True}


# --------------------------------------------------------- general settings

@app.get("/api/settings/general")
def get_general_settings():
    return {
        "demo_mode": db.get_setting("demo_mode", default=False),
        "data_root": str(config.get_data_root()),
        "real_interval_seconds": config.REAL_FOLLOWUP_INTERVAL_SECONDS,
        "demo_interval_seconds": config.DEMO_FOLLOWUP_INTERVAL_SECONDS,
        "gmail_configured": gmail_client.is_configured(),
    }


@app.post("/api/settings/general")
def set_general_settings(demo_mode: bool = Form(...)):
    db.set_setting("demo_mode", demo_mode)
    return {"ok": True}


# --------------------------------------------------------------- departments

@app.get("/api/settings/departments")
def get_departments():
    return db.list_departments()


@app.post("/api/settings/departments")
def add_department(label: str = Form(...), email: str = Form(...)):
    did = db.add_department(label, email)
    return {"id": did}


# -------------------------------------------------------------------- cases

@app.post("/api/pick-folder")
def pick_folder():
    """Opens a native OS folder-picker dialog on this machine (this is a
    fully local app, so the dialog opens on the same machine the browser
    is running on). Returns the chosen path, or null if cancelled."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(title="Choose a folder for this case")
        root.destroy()
        return {"path": path or None}
    except Exception as e:
        raise HTTPException(500, f"Could not open folder picker: {e}")


@app.get("/api/cases")
def get_cases(status: Optional[str] = None, q: Optional[str] = None):
    cases = db.list_cases(status=status)
    if q:
        ql = q.lower()
        cases = [
            c for c in cases
            if ql in (c.get("title") or "").lower()
            or ql in (c.get("victim_name") or "").lower()
            or ql in (c.get("location") or "").lower()
            or ql in (c.get("description") or "").lower()
        ]
    for c in cases:
        c["priority_label"] = priority_label(c["risk_score"]) if c.get("risk_score") is not None else "unscored"
    return cases


@app.delete("/api/cases/{case_id}")
def delete_case(case_id: str, confirm_title: str = Form(...)):
    """Permanently deletes a case: all database rows AND the physical
    folder on disk. Requires the exact case title to be typed as
    confirmation — this is a deliberately hard-to-trigger-by-accident
    action since it deletes real evidence from the computer."""
    case = db.get_case(case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    if confirm_title.strip() != case["title"]:
        raise HTTPException(
            400,
            f"Confirmation text did not match the case title exactly. "
            f"Expected '{case['title']}'.",
        )

    cdir = config.resolve_case_dir(case_id)
    rag_search.delete_case_documents(case_id)
    db.delete_case_db_rows(case_id)

    if cdir.exists():
        shutil.rmtree(cdir, ignore_errors=True)

    return {"ok": True, "deleted_folder": str(cdir)}


@app.post("/api/cases")
async def create_case(
    title: str = Form(...),
    victim_name: str = Form(""),
    location: str = Form(""),
    incident_datetime: str = Form(""),
    description: str = Form(""),
    assigned_officer: str = Form(""),
    custom_root: Optional[str] = Form(None),
    pdf_file: Optional[UploadFile] = File(None),
):
    case_id = db.create_case(
        title=title, victim_name=victim_name, location=location,
        incident_datetime=incident_datetime, description=description,
        assigned_officer=assigned_officer, custom_root=custom_root or None,
    )
    config.ensure_case_dirs(case_id, custom_root=custom_root or None)
    log_event(case_id, "Case created via guided intake form." + (f" Files stored at: {custom_root}" if custom_root else ""))

    if pdf_file is not None:
        cdir = config.resolve_case_dir(case_id)
        dest = cdir / "evidence" / "documents" / pdf_file.filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            shutil.copyfileobj(pdf_file.file, f)

        text = pdf_reader.extract_text(str(dest))
        if text:
            rag_search.add_document(case_id, f"{case_id}_import_{pdf_file.filename}", text, f"{pdf_file.filename} (imported)")
            log_event(case_id, f"Imported case PDF saved and indexed: {pdf_file.filename} ({len(text)} chars extracted).")
        else:
            log_event(case_id, f"Imported case PDF saved: {pdf_file.filename} (no extractable text — likely scanned/image-only).")

    return {"id": case_id}


@app.post("/api/sample-case")
def make_sample_case():
    case_id = synthetic_data.create_sample_case()
    return {"id": case_id}


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    case = db.get_case(case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    return case


@app.post("/api/cases/{case_id}/risk")
def recompute_risk(case_id: str):
    if not db.get_case(case_id):
        raise HTTPException(404, "Case not found")
    return compute_risk_score(case_id)


@app.get("/api/cases/{case_id}/timeline")
def get_timeline(case_id: str):
    return timeline_mod.build_timeline(case_id)


@app.get("/api/cases/{case_id}/update-log")
def get_update_log(case_id: str):
    return {"markdown": read_markdown(case_id)}


@app.post("/api/cases/{case_id}/update-log/regenerate")
def regenerate_update_log_summary(case_id: str):
    if not db.get_case(case_id):
        raise HTTPException(404, "Case not found")
    from modules.update_log import regenerate_ai_summary
    summary = regenerate_ai_summary(case_id)
    return {"summary": summary, "markdown": read_markdown(case_id)}


@app.post("/api/cases/{case_id}/report")
def generate_report(case_id: str):
    if not db.get_case(case_id):
        raise HTTPException(404, "Case not found")
    path = reports_mod.draft_case_report(case_id)
    log_event(case_id, f"Draft report generated: {path}")
    return FileResponse(path, filename="draft_report.md")


# ------------------------------------------------------------------ evidence

@app.post("/api/cases/{case_id}/evidence/photo")
async def upload_photo(case_id: str, file: UploadFile = File(...)):
    if not db.get_case(case_id):
        raise HTTPException(404, "Case not found")
    cdir = config.resolve_case_dir(case_id)
    photo_path = cdir / "evidence" / "images" / file.filename
    photo_path.parent.mkdir(parents=True, exist_ok=True)
    with open(photo_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    face_results = []
    if faces_mod.is_available():
        face_results = faces_mod.process_evidence_photo(str(photo_path), case_id)
    log_event(case_id, f"Evidence photo added: {file.filename} ({len(face_results)} face(s) detected).")

    matched, label = hash_match.check_hash(str(photo_path))
    if matched:
        log_event(case_id, f"Evidence photo triggered known-hash match: {label}")

    caption = image_caption.describe_image(str(photo_path))
    rag_search.add_document(case_id, f"{case_id}_{file.filename}_caption", caption, f"{file.filename} (photo description)")
    log_event(case_id, f"Photo description ({file.filename}): {caption}")

    return {
        "filename": file.filename,
        "faces": face_results,
        "hash_match": {"matched": matched, "label": label},
        "face_matching_available": faces_mod.is_available(),
        "caption": caption,
    }


@app.post("/api/cases/{case_id}/evidence/doc")
async def upload_doc(case_id: str, file: UploadFile = File(...)):
    if not db.get_case(case_id):
        raise HTTPException(404, "Case not found")
    cdir = config.resolve_case_dir(case_id)
    subfolder = config.evidence_subfolder_for_filename(file.filename)
    doc_path = cdir / subfolder / file.filename
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    with open(doc_path, "wb") as f:
        f.write(content)

    text = ""
    if file.filename.lower().endswith(".txt"):
        text = content.decode(errors="ignore")
    elif file.filename.lower().endswith(".pdf"):
        text = pdf_reader.extract_text(str(doc_path))

    flags = {}
    if text:
        rag_search.add_document(case_id, f"{case_id}_{file.filename}", text, file.filename)
        flags = nlp_flags.flag_text(case_id, text, source_label=file.filename)
        log_event(case_id, f"Evidence document added and indexed: {file.filename} ({len(text)} chars).")
    else:
        log_event(case_id, f"Evidence document added: {file.filename} (no text extracted — not indexed for search/chat).")

    return {"filename": file.filename, "flags": flags, "text_extracted": bool(text)}


# --------------------------------------------------------------------- graph

@app.get("/api/cases/{case_id}/graph")
def get_case_graph(case_id: str):
    g = graph_mod.build_case_face_graph(case_id)
    return graph_mod.to_agraph_format(g)


@app.get("/api/cross-case/graph")
def get_cross_case_graph():
    g = graph_mod.build_cross_case_graph()
    return graph_mod.to_agraph_format(g)


@app.get("/api/cross-case/edges")
def get_cross_case_edges():
    edges = db.all_correlation_edges()
    for e in edges:
        ca = db.get_case(e["case_id_a"])
        cb = db.get_case(e["case_id_b"])
        e["case_a_title"] = ca["title"] if ca else e["case_id_a"]
        e["case_b_title"] = cb["title"] if cb else e["case_id_b"]
    return edges


# --------------------------------------------------------------------- faces

@app.get("/api/faces")
def get_faces():
    all_faces = db.all_faces()
    for f in all_faces:
        f["cases"] = []
        for cid in faces_mod.cases_for_face(f["id"]):
            c = db.get_case(cid)
            f["cases"].append(c["title"] if c else cid)
    return all_faces


@app.get("/api/victims")
def get_victims():
    cases = db.list_cases()
    return [
        {"id": c["id"], "title": c["title"], "victim_name": c["victim_name"], "location": c.get("location")}
        for c in cases if c.get("victim_name")
    ]


@app.post("/api/faces/{face_id}/tag")
def tag_face(face_id: str, name: str = Form(...)):
    faces_mod.tag_face(face_id, name)
    return {"ok": True}


# --------------------------------------------------------------------- gmail

@app.post("/api/cases/{case_id}/summary-file")
def generate_summary_file(case_id: str, file_format: str = Form("docx")):
    if not db.get_case(case_id):
        raise HTTPException(404, "Case not found")
    try:
        if file_format == "pdf":
            path = case_export.generate_pdf(case_id)
        else:
            path = case_export.generate_docx(case_id)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    log_event(case_id, f"CaseSummary file generated ({file_format}): {Path(path).name}")
    return FileResponse(path, filename=Path(path).name)


@app.post("/api/cases/{case_id}/chat/image")
async def chat_image(case_id: str, file: UploadFile = File(...), message: str = Form("")):
    """Lets you share an image directly in the case chat. Uses the local
    vision model (moondream) ONLY for this image — text/PDF evidence
    never goes through the vision model, only through direct text
    extraction (pypdf). Saves the image as evidence too, not just a
    throwaway chat attachment."""
    if not db.get_case(case_id):
        raise HTTPException(404, "Case not found")
    cdir = config.resolve_case_dir(case_id)
    img_dir = cdir / "evidence" / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    img_path = img_dir / file.filename
    with open(img_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    face_results = []
    if faces_mod.is_available():
        face_results = faces_mod.process_evidence_photo(str(img_path), case_id)

    caption = image_caption.describe_image(str(img_path))
    rag_search.add_document(case_id, f"{case_id}_{file.filename}_caption", caption, f"{file.filename} (shared via chat)")
    log_event(case_id, f"Image shared via chat and analyzed: {file.filename} ({len(face_results)} face(s)).")

    db.add_chat_message(case_id, "user", message or f"[shared image: {file.filename}]")
    reply = f"Here's what I can see: {caption}"
    if face_results:
        reply += f"\n\n{len(face_results)} face(s) detected and checked against the global face index."
    db.add_chat_message(case_id, "assistant", reply)

    return {"caption": caption, "faces": face_results, "reply": reply}


@app.get("/api/cases/{case_id}/gmail/threads")
def get_threads(case_id: str):
    return db.list_threads_for_case(case_id)


@app.post("/api/cases/{case_id}/gmail/draft")
def draft_gmail(case_id: str, department_label: str = Form(...), request_desc: str = Form(...)):
    prompt = (
        f"Draft a formal, polite request email to {department_label} "
        f"for the following, referencing case {case_id}:\n{request_desc}"
    )
    try:
        result = llm_client.call_llm(prompt)
        return {"draft": result.text}
    except Exception as e:
        raise HTTPException(502, str(e))


@app.post("/api/cases/{case_id}/gmail/send")
def send_gmail(
    case_id: str,
    department_label: str = Form(...),
    department_email: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
):
    try:
        sent = gmail_client.send_email(department_email, subject, body)
        thread_id = db.create_email_thread(
            case_id, department_label, department_email, sent["threadId"], subject
        )
        log_event(case_id, f"Email sent to {department_label} ({department_email}).")
        return {"thread_id": thread_id}
    except Exception as e:
        raise HTTPException(502, str(e))


@app.get("/api/gmail/status")
def gmail_status():
    return {"configured": gmail_client.is_configured()}


# ---------------------------------------------------------------------- chat

@app.get("/api/cases/{case_id}/chat")
def get_chat_history(case_id: str):
    return db.chat_history_for_case(case_id)


@app.post("/api/cases/{case_id}/chat")
def post_chat(case_id: str, question: str = Form(...)):
    from modules import chat_assistant
    db.add_chat_message(case_id, "user", question)
    result = chat_assistant.handle_message(case_id, question)
    answer_text = result["answer"]
    if result["sources"]:
        answer_text += "\n\nSources: " + ", ".join(set(result["sources"]))
    db.add_chat_message(case_id, "assistant", answer_text)
    return {
        "answer": answer_text,
        "sources": result["sources"],
        "email_draft": result.get("email_draft"),
        "summary_file_path": result.get("summary_file_path"),
    }


# ------------------------------------------------------------- static files

app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
