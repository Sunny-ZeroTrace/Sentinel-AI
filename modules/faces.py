"""
Face detection + matching.

Scope, deliberately: this matches faces appearing in case evidence against
a GLOBAL INDEX BUILT FROM THIS APP'S OWN CASES (previously-seen faces across
your cases, plus any reference photos you explicitly tag as a known suspect
or identified victim). It is not general-purpose facial recognition against
outside databases or the public.

Uses `face_recognition` (dlib-based). If the library isn't installed yet,
functions degrade to returning empty results rather than crashing the app,
so the rest of the platform stays usable while it's being installed.
"""
import json

import db
import config

try:
    import face_recognition
except ImportError:
    face_recognition = None

try:
    from PIL import Image
except ImportError:
    Image = None


def is_available() -> bool:
    return face_recognition is not None


def detect_and_encode(image_path: str):
    """Returns a list of dicts: [{'location': (t,r,b,l), 'encoding': [...]}, ...]"""
    if not is_available():
        return []
    image = face_recognition.load_image_file(image_path)
    locations = face_recognition.face_locations(image)
    encodings = face_recognition.face_encodings(image, known_face_locations=locations)
    return [
        {"location": loc, "encoding": enc.tolist()}
        for loc, enc in zip(locations, encodings)
    ]


def match_against_index(encoding: list):
    """
    Compares one face encoding against the global face_index table.
    Returns (matched_face_id_or_None, distance_or_None).
    """
    if not is_available():
        return None, None
    import numpy as np

    existing = db.all_faces()
    if not existing:
        return None, None

    target = np.array(encoding)
    known_encodings = [np.array(json.loads(f["encoding"])) for f in existing]
    distances = face_recognition.face_distance(known_encodings, target)

    best_idx = int(distances.argmin())
    best_distance = float(distances[best_idx])

    if best_distance <= config.FACE_MATCH_DISTANCE_THRESHOLD:
        return existing[best_idx]["id"], best_distance
    return None, best_distance


def save_face_thumbnail(image_path: str, location, case_id: str, face_id: str) -> str:
    """Crops the detected face region and saves a thumbnail into this
    case's faces/ folder, so the physical folder structure holds visible
    evidence, not just database rows. Returns the saved path, or '' if
    Pillow isn't available."""
    if Image is None:
        return ""
    try:
        top, right, bottom, left = location
        img = Image.open(image_path)
        pad = int((bottom - top) * 0.25)
        crop_box = (
            max(0, left - pad), max(0, top - pad),
            min(img.width, right + pad), min(img.height, bottom + pad),
        )
        thumb = img.crop(crop_box)
        thumb.thumbnail((300, 300))

        cdir = config.resolve_case_dir(case_id)
        faces_dir = cdir / "faces"
        faces_dir.mkdir(parents=True, exist_ok=True)
        out_path = faces_dir / f"{face_id}.jpg"
        thumb.convert("RGB").save(out_path, "JPEG")
        return str(out_path)
    except Exception:
        return ""


def sync_person_folder(face_id: str) -> None:
    """Copies this face's thumbnail(s) into the global persons/<face_id>/
    folder once it's been tagged, so identified individuals have one
    browsable folder spanning every case they appear in."""
    if Image is None:
        return
    sightings = db.sightings_for_face(face_id)
    if not sightings:
        return
    pdir = config.person_dir(config.get_data_root(), face_id)
    pdir.mkdir(parents=True, exist_ok=True)

    for i, sighting in enumerate(sightings):
        case_thumb = config.resolve_case_dir(sighting["case_id"]) / "faces" / f"{face_id}.jpg"
        if case_thumb.exists():
            dest = pdir / f"sighting_{i}_{sighting['case_id']}.jpg"
            try:
                dest.write_bytes(case_thumb.read_bytes())
            except OSError:
                continue


def process_evidence_photo(image_path: str, case_id: str):
    """
    Full pipeline for one uploaded photo:
    - detect faces
    - for each: match against global index, or register as a new face
    - save a cropped thumbnail into this case's faces/ folder
    - record a sighting either way
    - if the matched face was first seen in a DIFFERENT case, add a
      cross-case correlation edge automatically
    Returns a list of result dicts for the UI to render.
    """
    results = []
    faces = detect_and_encode(image_path)

    for face in faces:
        matched_id, distance = match_against_index(face["encoding"])

        if matched_id is None:
            face_id = db.add_face(face["encoding"], case_id, image_path)
            is_new = True
        else:
            face_id = matched_id
            is_new = False

        db.add_face_sighting(face_id, case_id, image_path)
        thumb_path = save_face_thumbnail(image_path, face["location"], case_id, face_id)

        if not is_new:
            existing_face_record = next(
                (f for f in db.all_faces() if f["id"] == face_id), None
            )
            if existing_face_record and existing_face_record["first_seen_case_id"] != case_id:
                db.add_correlation_edge(
                    existing_face_record["first_seen_case_id"],
                    case_id,
                    "face",
                    face_id,
                )
            if existing_face_record and existing_face_record.get("name_tag"):
                sync_person_folder(face_id)

        results.append(
            {
                "face_id": face_id,
                "is_new": is_new,
                "distance": distance,
                "location": face["location"],
                "thumbnail_path": thumb_path,
            }
        )

    return results


def tag_face(face_id: str, name: str) -> None:
    db.tag_face(face_id, name)
    sync_person_folder(face_id)


def cases_for_face(face_id: str):
    sightings = db.sightings_for_face(face_id)
    return sorted({s["case_id"] for s in sightings})
