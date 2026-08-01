"""
Correlation graph — builds a NetworkX graph either scoped to one case
(entities within it) or across all cases (shared faces/emails/phones/devices).
Exports node/edge lists as plain dicts for the frontend's canvas-based
graph renderer (see frontend/app.js drawSimpleGraph()).
"""
import networkx as nx

import db


def build_cross_case_graph() -> nx.Graph:
    g = nx.Graph()
    cases = db.list_cases()
    for c in cases:
        g.add_node(c["id"], label=c.get("title") or c["id"], node_type="case")

    for edge in db.all_correlation_edges():
        g.add_edge(
            edge["case_id_a"],
            edge["case_id_b"],
            entity_type=edge["entity_type"],
            entity_value=edge["entity_value"],
        )
    return g


def build_case_face_graph(case_id: str) -> nx.Graph:
    """Faces seen within a single case, as a small bipartite-ish graph."""
    g = nx.Graph()
    g.add_node(case_id, label="This case", node_type="case")

    faces = [f for f in db.all_faces() if case_id in faces_seen_in(f["id"])]
    for f in faces:
        label = f.get("name_tag") or f"Face {f['id'][:6]}"
        g.add_node(f["id"], label=label, node_type="face")
        g.add_edge(case_id, f["id"])
    return g


def faces_seen_in(face_id: str):
    sightings = db.sightings_for_face(face_id)
    return {s["case_id"] for s in sightings}


def to_agraph_format(g: nx.Graph):
    """Shapes the graph into plain dict lists the frontend can render on a
    <canvas> element without needing a separate graph library."""
    nodes = [
        {
            "id": n,
            "label": data.get("label", n),
            "type": data.get("node_type", "unknown"),
        }
        for n, data in g.nodes(data=True)
    ]
    edges = [
        {
            "source": u,
            "target": v,
            "label": data.get("entity_type", ""),
        }
        for u, v, data in g.edges(data=True)
    ]
    return {"nodes": nodes, "edges": edges}
