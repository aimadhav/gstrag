"""Source-reviewed notification clauses and conservative update-check packets.

No legal precedence inference, automatic rate calculation, or answer approval.
"""

import hashlib
import re
from datetime import date

from .benchmark import allowed, normalize, assemble_context
from .ingestion import read_json

MONTHS = {name.lower(): i for i, name in enumerate([
    "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"], 1)}
REFERENCE = re.compile(r"\b(\d{1,3})\s*/\s*(\d{4})\s*[-\u2013\u2014]?\s*central\s+tax\s*\(\s*rate\s*\)", re.I)


def notification_key(number):
    match = re.fullmatch(r"(\d{1,3})/(\d{4})", number)
    if not match or int(match[1]) == 0:
        raise ValueError("Expected a Central Tax (Rate) notification number n/yyyy")
    return f"central_tax_rate:{int(match[1])}/{match[2]}"


def explicit_references(text):
    """Series is mandatory: Central Tax and Central Tax (Rate) are different."""
    return {notification_key(f"{n}/{year}") for n, year in REFERENCE.findall(text)}


def english_date(text):
    pattern = r"\b(\d{1,2})\s*(?:st|nd|rd|th)?\s+(?:day\s+of\s+)?(" + "|".join(MONTHS) + r")\s*,?\s*(\d{4})\b"
    matches = re.findall(pattern, text, flags=re.I)
    if len(matches) != 1:
        raise ValueError("Date evidence needs exactly one explicit English calendar date")
    day, month, year = matches[0]
    return date(int(year), MONTHS[month.lower()], int(day)).isoformat()


def source_items(directory):
    from docling_core.types.doc import DoclingDocument
    doc = DoclingDocument.load_from_json(directory / "docling.json")
    items = {}
    for item, _ in doc.iterate_items():
        label = str(getattr(item, "label", ""))
        text = item.export_to_markdown(doc=doc) if label == "table" else getattr(item, "text", "")
        if label == "table":
            # Preserve cell content/order, omit token-expensive Markdown padding
            # and separator rules. No legal text is summarized or generated.
            rows = [" | ".join(cell.strip() for cell in line.strip().strip("|").split("|")) for line in text.splitlines()
                    if line.strip() and not re.fullmatch(r"[\s|:\-]+", line)]
            text = "\n".join(rows)
        if text.strip() and label not in {"page_header", "page_footer"}:
            items[item.self_ref] = {"source_ref": item.self_ref, "text": text,
                                    "pages": sorted({p.page_no for p in item.prov}), "label": label}
    return items


def reviewed_records(directory, review_path, tokenizer):
    """Fail on stale anchors; retain full selected clause/table, not a summary."""
    review, manifest = read_json(review_path), read_json(directory / "manifest.json")
    if (review.get("review_status") != "source_audited" or review.get("reviewer_type") not in {"assistant", "human"}
            or review.get("source_sha256") != manifest["sha256"] or review.get("document_id") != manifest["document_id"]
            or review.get("docling_sha256") != hashlib.sha256((directory / "docling.json").read_bytes()).hexdigest()
            or manifest["source_type"] != "notification" or manifest["plan_required"] != "plus"):
        raise ValueError("Notification review is unreviewed or belongs to another PDF/parse")
    items = source_items(directory)
    for anchor in review["anchors"].values():
        item = items.get(anchor["source_ref"])
        if not item or anchor["pages"] != item["pages"] or normalize(anchor["quote"]) not in normalize(item["text"]):
            raise ValueError("Notification metadata anchor is not present on its claimed source page")
    key = notification_key(review["number"])
    if key not in explicit_references(review["anchors"]["identity"]["quote"]):
        raise ValueError("Notification identity does not match source evidence")
    for field in ["issued_on", "effective_from"]:
        if english_date(review["anchors"][field]["quote"]) != review[field]:
            raise ValueError("Notification date differs from its explicit source date")
    # The sample contains prospective amendments only; do not silently accept a
    # retrospective amendment through this intentionally limited schema.
    if review["effective_from"] < review["issued_on"]:
        raise ValueError("Retrospective effect needs a separate reviewed policy")
    if notification_key(review["amends"]) not in explicit_references(review["anchors"]["amends"]["quote"]):
        raise ValueError("Amendment target is not supported by its source anchor")
    records = []
    seen = set()
    for clause in review["clauses"]:
        if clause["id"] in seen or not clause["source_refs"] or not clause["topic_id"]:
            raise ValueError("Duplicate/empty notification clause")
        seen.add(clause["id"])
        if not set(clause["source_refs"]) <= set(items):
            raise ValueError("Notification clause points to an unknown source item")
        spans = [dict(anchor) for anchor in review["anchors"].values()]
        spans += [{"source_ref": ref, "pages": items[ref]["pages"], "quote": items[ref]["text"]} for ref in clause["source_refs"]]
        text = "\n\n".join(dict.fromkeys(span["quote"] for span in spans))
        prefix = f"Notification {review['number']} Central Tax (Rate) | issued {review['issued_on']} | effective {review['effective_from']}\n{clause['subject']}\n"
        embedding_text = prefix + text
        tokens = len(tokenizer.encode(embedding_text, add_special_tokens=False))
        if tokens > 512:
            raise ValueError(f"Reviewed notification clause {clause['id']} exceeds 512 tokens; do not truncate conditions")
        records.append({"chunk_id": f"{manifest['document_id']}:notification-v1:{clause['id']}",
            "document_id": manifest["document_id"], "source_type": "notification", "plan_required": "plus",
            "variant": "reviewed_notification_clause", "text": text, "embedding_text": embedding_text,
            "headings": [f"Notification {review['number']} Central Tax (Rate)", clause["subject"]],
            "source_refs": list(dict.fromkeys(s["source_ref"] for s in spans)), "pages": sorted({p for s in spans for p in s["pages"]}),
            "evidence_spans": spans, "token_count": tokens,
            "notification": {"key": key, "issued_on": review["issued_on"], "effective_from": review["effective_from"],
                "effective_to": None, "amends": notification_key(review["amends"]), "topic_id": clause["topic_id"],
                "provisions": clause["provisions"], "operative_change": clause["operative_change"],
                "conditions": "Retained verbatim in full selected clause; not automatically interpreted",
                "exceptions": "No global absence-of-exceptions claim; surrounding instruments may be required",
                "rate_scope": "cgst_only", "supersession_status": "not_established", "chain_complete": False,
                "review_status": "assistant_source_audited_not_admin_approved", "source_url": review["source_url"]}})
    return records


def book_links(book_records, notification_records):
    """Explicit-number candidate links only, not evidence of legal precedence."""
    by_key = {}
    for record in notification_records:
        by_key.setdefault(record["notification"]["key"], record["document_id"])
    return [{"book_document_id": book["document_id"], "book_chunk_id": book["chunk_id"],
             "book_source_type": book["source_type"], "notification_key": key, "notification_document_id": by_key[key],
             "status": "candidate_pending_admin_review", "basis": "explicit_number_and_series_reference"}
            for book in book_records if book["source_type"] in {"firm_book", "icai_book"}
            for key in sorted(explicit_references(book["text"]) & set(by_key))]


def check_updates(records, topic_ids, as_of, plan, links=()):
    """Mandatory separate notification lane: independent of book top-K ranking.

    Caller supplies reviewed topic IDs. Automatic question/topic classification
    and authenticated role lookup are not implemented by this library.
    """
    if plan not in {"plus", "pro"}:
        raise ValueError("Unknown access plan")
    visible = [r for r in records if allowed(r, plan)]
    topics = set(topic_ids)
    candidates = [r for r in visible if r["source_type"] == "notification" and r["notification"]["topic_id"] in topics]
    relevant_links = [link for link in links if link["book_document_id"] in {r["document_id"] for r in visible}
                      and link["notification_document_id"] in {r["document_id"] for r in candidates}]
    if as_of is None:
        return {"status": "clarification_required", "reason": "explicit_as_of_date_required", "candidates": [], "links": relevant_links}
    when = date.fromisoformat(as_of)
    eligible = [r for r in candidates if date.fromisoformat(r["notification"]["issued_on"]) <= when
                and date.fromisoformat(r["notification"]["effective_from"]) <= when]
    future = [r for r in candidates if date.fromisoformat(r["notification"]["issued_on"]) <= when
              and date.fromisoformat(r["notification"]["effective_from"]) > when]
    # Keep ALL matching amendments, not simply the one with the newest issue date.
    eligible.sort(key=lambda r: (r["notification"]["effective_from"], r["chunk_id"]))
    return {"status": "review_required", "reason": "incomplete_amendment_chain_and_unverified_applicability" if eligible else "no_effective_notification_evidence_in_loaded_corpus",
            "as_of": as_of, "candidates": eligible, "published_not_yet_effective": future,
            "links": [link for link in relevant_links if link["notification_document_id"] in {r["document_id"] for r in eligible}],
            "current_law_verified": False}


def public_status(check):
    """No source passages, draft conclusions, internal links, or PDF URLs leak."""
    if check["status"] == "clarification_required":
        return {"status": "clarification_required", "message": "Which transaction date should be checked? Please provide YYYY-MM-DD."}
    return {"status": "pending_review", "message": "This query needs admin review before an answer can be shown."}


def update_context(check, ranked_books, tokenizer, budget, plan):
    """Reserve complete required notification clauses before book context.

    Never truncate a mandatory notification condition just to fill the budget.
    Book excerpts retain the existing budgeted child-only context behavior.
    """
    if budget <= 0:
        raise ValueError("Context budget must be positive")
    if check["status"] == "clarification_required":
        return [], 0, "clarification_required"
    required = check["candidates"]
    if any(not allowed(r, plan) for r in required + ranked_books):
        raise ValueError("Update context contains a source disallowed for the plan")
    size = sum(len(tokenizer.encode(r["embedding_text"], add_special_tokens=False)) for r in required)
    if size > budget:
        return [], 0, "notification_evidence_over_budget_requires_review"
    context, used, _ = assemble_context(required + ranked_books, [], [], tokenizer, budget, "child", plan)
    return context, used, "notification_evidence_reserved"


def qualified_group_covered(group, records):
    """Docling refs restart at #/texts/0 in every PDF: match document identity too."""
    return any(r["document_id"] == a["document_id"]
               and normalize(a["quote"]) in normalize(r.get("embedding_text", r["text"]))
               and any(span["source_ref"] in a["source_refs"] and normalize(a["quote"]) in normalize(span["quote"])
                       for span in r.get("evidence_spans", []))
               for a in group for r in records)
