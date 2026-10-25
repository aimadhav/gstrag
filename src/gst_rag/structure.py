"""Conservative layout cleanup plus explicit, source-bound outline reviews.

The review is a small ingestion supplement, not inferred legal/case semantics.
Raw Docling JSON and original PDF are never changed.
"""

import hashlib
import re
from collections import defaultdict

from .ingestion import read_json


def repeated_edge_headers(doc):
    """Require identical heading text on >=3 pages, near a stable top margin.

    Do not drop a unique heading, repeated body heading, or numbered section.
    Positions use Docling page dimensions, not publisher-specific page pixels.
    """
    candidates = defaultdict(list)
    for item, _ in doc.iterate_items():
        if str(getattr(item, "label", "")) != "section_header":
            continue
        text = " ".join(item.text.casefold().split())
        if not text or re.match(r"^\d", text) or len(item.prov) != 1:
            continue
        prov = item.prov[0]
        page = doc.pages.get(prov.page_no)
        if page is None or not page.size.height or not page.size.width:
            continue
        box = prov.bbox
        height, width = page.size.height, page.size.width
        # BOTH ends must be inside the top 12%; coordinate origin is explicit.
        y = sorted((box.t / height, box.b / height))
        if str(box.coord_origin).upper().endswith("BOTTOMLEFT"):
            y = [1 - y[1], 1 - y[0]]
        if 0 <= y[0] <= y[1] <= .12:
            candidates[text].append((item, prov.page_no, y[0], box.l / width))
    refs = set()
    for matches in candidates.values():
        if (len({m[1] for m in matches}) >= 3
                and max(m[2] for m in matches) - min(m[2] for m in matches) <= .02
                and max(m[3] for m in matches) - min(m[3] for m in matches) <= .03):
            refs.update(m[0].self_ref for m in matches)
    return refs


def apply_outline_review(doc, manifest, path, raw_path):
    """Validate all anchors first, then apply only the reviewed levels/moves.

    Integer numbering is ambiguous: a local 1..5 list can live inside section 4.
    A checksum-bound review is safer than pretending the number implies depth.
    Reading-order moves operate on intact body children (including list groups).
    """
    if path is None:
        return None
    from docling_core.types.doc import RefItem

    review = read_json(path)
    if (review.get("document_id") != manifest["document_id"]
            or review.get("source_sha256") != manifest["sha256"]
            or review.get("docling_sha256") != hashlib.sha256(raw_path.read_bytes()).hexdigest()):
        raise ValueError("Outline review does not match this PDF and Docling parse")
    if review.get("review_status") != "source_audited" or review.get("reviewer_type") not in {"assistant", "human"}:
        raise ValueError("Outline review must be explicitly source audited")
    actual = {i.self_ref: i for i, _ in doc.iterate_items() if str(getattr(i, "label", "")) == "section_header"}
    entries = review["headings"]
    if len(entries) != len(actual) or {e["source_ref"] for e in entries} != set(actual):
        raise ValueError("Outline review must cover each retained heading exactly once")
    for entry in entries:
        item = actual[entry["source_ref"]]
        if (entry["text"] != item.text or entry["pages"] != sorted({p.page_no for p in item.prov})
                or type(entry["level"]) is not int or not 1 <= entry["level"] <= 6
                or type(entry["parent_boundary"]) is not bool):
            raise ValueError("Invalid outline heading anchor, level, or boundary")
    if len({e["text"] for e in entries}) != len(entries):
        raise ValueError("Reviewed parent boundaries need unambiguous heading text")
    levels = {e["source_ref"]: e["level"] for e in entries}
    body_refs = {r.cref for r in doc.body.children}
    for move in review.get("reading_order_moves", []):
        refs = move["source_refs"]
        anchor = move["anchor"]
        if (not refs or len(set(refs)) != len(refs) or not set(refs) <= body_refs
                or anchor not in body_refs or anchor in refs or move["position"] not in {"before", "after"}
                or not move.get("reason")):
            raise ValueError("Invalid reviewed body-order move")
        # No cross-page transfers: all descendants of the group must match.
        def descendant_pages(ref):
            item = RefItem(cref=ref).resolve(doc)
            return {p.page_no for p in getattr(item, "prov", [])} | {
                p for child in item.children for p in descendant_pages(child.cref)}
        if any(descendant_pages(ref) != {move["page"]} for ref in [*refs, anchor]):
            raise ValueError("Reviewed reading-order move crosses a PDF page")
    audit = []
    for entry in entries:
        item = actual[entry["source_ref"]]
        audit.append({"ref": item.self_ref, "from": item.level, "to": levels[item.self_ref],
                      "heading": item.text, "parent_boundary": entry["parent_boundary"], "reason": "source_reviewed_outline"})
        item.level = entry["level"]
    for move in review.get("reading_order_moves", []):
        by_ref = {r.cref: r for r in doc.body.children}
        moved = [by_ref[r] for r in move["source_refs"]]
        remaining = [r for r in doc.body.children if r.cref not in move["source_refs"]]
        index = next(i for i, r in enumerate(remaining) if r.cref == move["anchor"])
        if move["position"] == "after":
            index += 1
        doc.body.children = remaining[:index] + moved + remaining[index:]
    return {"heading_adjustments": audit, "parent_boundaries": {e["text"] for e in entries if e["parent_boundary"]},
            "reading_order_moves": review.get("reading_order_moves", []), "review_status": review["review_status"],
            "reviewer_type": review["reviewer_type"]}
