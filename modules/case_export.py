"""
Generates a complete CaseSummary file (DOCX or PDF) — case details,
timeline, risk score, update log, and every evidence photo (embedded,
with its saved AI description) and document (listed with a text excerpt).

This is the "give me a full context file" output the case chat can
trigger, and there's also a direct button for it in the Overview tab.
Saved into the case's summary/ folder.
"""
import datetime
from pathlib import Path

import db
import config
from modules import timeline as timeline_mod
from modules.risk_score import compute_risk_score

try:
    from docx import Document
    from docx.shared import Inches
except ImportError:
    Document = None

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
    from reportlab.lib.styles import getSampleStyleSheet
except ImportError:
    SimpleDocTemplate = None


def _gather_case_data(case_id: str) -> dict:
    case = db.get_case(case_id)
    events = timeline_mod.build_timeline(case_id)
    log_rows = db.update_log_for_case(case_id)
    risk = compute_risk_score(case_id)
    cdir = config.resolve_case_dir(case_id)
    image_paths = sorted((cdir / "evidence" / "images").glob("*")) if (cdir / "evidence" / "images").exists() else []
    return {
        "case": case, "events": events, "log_rows": log_rows,
        "risk": risk, "cdir": cdir, "image_paths": image_paths,
    }


def is_docx_available() -> bool:
    return Document is not None


def is_pdf_available() -> bool:
    return SimpleDocTemplate is not None


def generate_docx(case_id: str) -> str:
    if Document is None:
        raise RuntimeError("python-docx isn't installed — run `pip install python-docx`.")
    data = _gather_case_data(case_id)
    case = data["case"]

    doc = Document()
    doc.add_heading(f"Case Summary — {case.get('title', case_id)}", level=1)
    doc.add_paragraph(f"Case ID: {case_id}")
    doc.add_paragraph(f"Status: {case.get('status')} | Priority: {case.get('priority')} | Risk score: {data['risk']['score_0_100']}/100")
    doc.add_paragraph(f"Victim/subject: {case.get('victim_name') or '—'}")
    doc.add_paragraph(f"Location: {case.get('location') or '—'}")
    doc.add_paragraph(f"Incident time: {case.get('incident_datetime') or '—'}")
    doc.add_paragraph(f"Description: {case.get('description') or '—'}")

    doc.add_heading("Timeline", level=2)
    for e in data["events"]:
        flag = " (uncertain timestamp)" if e["uncertain"] else ""
        doc.add_paragraph(f"[{e['source']}] {e['description']}{flag}", style="List Bullet")

    doc.add_heading("Case log", level=2)
    for row in data["log_rows"]:
        ts = datetime.datetime.fromtimestamp(row["created_at"]).strftime("%Y-%m-%d %H:%M")
        doc.add_paragraph(f"{ts} — {row['entry']}", style="List Bullet")

    if data["image_paths"]:
        doc.add_heading("Evidence photos", level=2)
        for img_path in data["image_paths"]:
            try:
                doc.add_picture(str(img_path), width=Inches(4))
                doc.add_paragraph(f"({img_path.name})")
            except Exception:
                doc.add_paragraph(f"[Could not embed image: {img_path.name}]")

    out_dir = data["cdir"] / "summary"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"CaseSummary_{int(datetime.datetime.now().timestamp())}.docx"
    doc.save(str(out_path))
    return str(out_path)


def generate_pdf(case_id: str) -> str:
    if SimpleDocTemplate is None:
        raise RuntimeError("reportlab isn't installed — run `pip install reportlab`.")
    data = _gather_case_data(case_id)
    case = data["case"]
    styles = getSampleStyleSheet()

    out_dir = data["cdir"] / "summary"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"CaseSummary_{int(datetime.datetime.now().timestamp())}.pdf"

    doc = SimpleDocTemplate(str(out_path), pagesize=letter)
    story = [
        Paragraph(f"Case Summary — {case.get('title', case_id)}", styles["Title"]),
        Spacer(1, 12),
        Paragraph(f"Case ID: {case_id}", styles["Normal"]),
        Paragraph(f"Status: {case.get('status')} | Priority: {case.get('priority')} | Risk score: {data['risk']['score_0_100']}/100", styles["Normal"]),
        Paragraph(f"Victim/subject: {case.get('victim_name') or '—'}", styles["Normal"]),
        Paragraph(f"Location: {case.get('location') or '—'}", styles["Normal"]),
        Paragraph(f"Description: {case.get('description') or '—'}", styles["Normal"]),
        Spacer(1, 16),
        Paragraph("Timeline", styles["Heading2"]),
    ]
    for e in data["events"]:
        flag = " (uncertain timestamp)" if e["uncertain"] else ""
        story.append(Paragraph(f"[{e['source']}] {e['description']}{flag}", styles["Normal"]))

    story.append(Spacer(1, 12))
    story.append(Paragraph("Case log", styles["Heading2"]))
    for row in data["log_rows"]:
        ts = datetime.datetime.fromtimestamp(row["created_at"]).strftime("%Y-%m-%d %H:%M")
        story.append(Paragraph(f"{ts} — {row['entry']}", styles["Normal"]))

    if data["image_paths"]:
        story.append(Spacer(1, 12))
        story.append(Paragraph("Evidence photos", styles["Heading2"]))
        for img_path in data["image_paths"]:
            try:
                story.append(RLImage(str(img_path), width=4 * inch, height=3 * inch))
                story.append(Paragraph(img_path.name, styles["Normal"]))
                story.append(Spacer(1, 8))
            except Exception:
                story.append(Paragraph(f"[Could not embed image: {img_path.name}]", styles["Normal"]))

    doc.build(story)
    return str(out_path)
