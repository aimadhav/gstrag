"""Controlled chunking variants and section parents from one Docling parse."""

import copy
import hashlib
import re
import time
from pathlib import Path

from .ingestion import read_json, write_json
from .structure import apply_outline_review, repeated_edge_headers


def contextualize(text, headings):
    prefix = "\n".join(headings)
    return f"{prefix}\n{text}" if prefix else text


def pages_of(items):
    return sorted({p.page_no for item in items for p in getattr(item, "prov", [])})


def heading_number(text):
    """Recognize a leading outline number, allowing a terminal dot.

    Called only for actual heading strings, never to classify prose as headings.
    """
    match = re.match(r"^(\d+(?:\.\d+)*)\.?(?:\s+|$)", text.strip())
    return match.group(1) if match else None


def parent_headings_for(headings, reviewed_boundaries=None):
    numbered = [i for i, heading in enumerate(headings)
                if (heading in reviewed_boundaries if reviewed_boundaries is not None else heading_number(heading))]
    return headings[:numbered[-1] + 1] if numbered else headings[:1]


def load_picture_transcriptions(path, manifest, doc):
    """Load explicitly reviewed, document-bound picture text; never infer it.

    The immutable Docling parse is not edited. Serialization keeps the original
    picture item as its span source, preserving its reference and PDF provenance.
    """
    if path is None:
        return {}
    payload = read_json(path)
    if payload.get("document_id") != manifest["document_id"] or payload.get("source_sha256") != manifest["sha256"]:
        raise ValueError("Picture transcription belongs to a different PDF")
    pictures = {p.self_ref: p for p in doc.pictures}
    entries = {}
    for entry in payload["pictures"]:
        ref = entry["source_ref"]
        if ref not in pictures or ref in entries:
            raise ValueError("Unknown or duplicate picture transcription reference")
        if entry.get("review_status") != "source_audited" or entry.get("reviewer_type") not in {"assistant", "human"}:
            raise ValueError("Picture transcription needs an explicit source review")
        if sorted(entry["pages"]) != pages_of([pictures[ref]]) or not entry["text"].strip():
            raise ValueError("Picture transcription has incorrect pages or empty text")
        entries[ref] = entry
    return entries


def jsonl(path, records):
    import json
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")


def filter_document(original):
    """Remove only recognized furniture and obvious dotted-leader TOC items.

    Save an exclusion audit; preserve the original Docling conversion untouched.
    This is not claimed to be a complete or perfect TOC detector.
    """
    doc = copy.deepcopy(original)
    excluded = []
    edge_headers = repeated_edge_headers(doc)
    for item, _ in doc.iterate_items():
        label = str(getattr(item, "label", ""))
        text = getattr(item, "text", "")
        if label == "table":
            text = item.export_to_markdown(doc=doc)
        reason = None
        if label in {"page_header", "page_footer"}:
            reason = "furniture"
        elif item.self_ref in edge_headers:
            reason = "repeated_top_margin_heading"
        elif label == "document_index":
            reason = "document_index"
        elif re.search(r"\.{4,}", text):
            reason = "dotted_leader_candidate"
        elif text.strip().upper() == "SYNOPSIS":
            reason = "synopsis_heading"
        elif pages_of([item]) == [1] and (text.strip().upper() == "C H A P T E R" or re.fullmatch(r"\d+", text.strip())):
            reason = "chapter_decoration"
        if reason:
            excluded.append({"ref": item.self_ref, "reason": reason, "pages": pages_of([item]), "preview": text[:150]})
    refs = {e["ref"] for e in excluded}
    # Remove references, not the indexed text/table arrays, so all JSON pointers
    # remain stable between raw parsing, chunk variants, and evidence labels.
    for node in [doc.body, doc.furniture, *doc.groups, *doc.texts, *doc.tables, *doc.pictures]:
        node.children = [child for child in node.children if child.cref not in refs]
    return doc, excluded


def restore_heading_depth(doc):
    """Infer outline levels from explicit numbering; keep an audit of changes.

    Docling detects headings in this PDF but emits them at the same level.
    Numbering is a structural signal, not inferred legal interpretation.
    """
    headings = [i for i, _ in doc.iterate_items() if str(getattr(i, "label", "")) == "section_header"]
    integers = [heading_number(i.text) for i in headings if heading_number(i.text) and "." not in heading_number(i.text)]
    if len(integers) != len(set(integers)) or any(int(b) < int(a) for a, b in zip(integers, integers[1:])):
        raise ValueError("Ambiguous single-number heading restart; supply a source-reviewed --outline-review")
    numeric_depth, audit = 1, []
    for item in headings:
        if str(getattr(item, "label", "")) != "section_header":
            continue
        number = heading_number(item.text)
        if number:
            numeric_depth = len(number.split("."))
            level = numeric_depth
        elif pages_of([item]) == [1]:
            level = 1
        else:
            level = numeric_depth + 1
        if item.level != level:
            audit.append({"ref": item.self_ref, "from": item.level, "to": level, "heading": item.text})
            item.level = level
    return audit


def fixed_windows(units, tokenizer, max_tokens, overlap):
    if not 0 <= overlap < max_tokens:
        raise ValueError("Overlap must be nonnegative and less than max tokens")
    source, spans = "", []
    for unit in units:
        start = len(source)
        source += unit["text"] + "\n\n"
        spans.append((start, start + len(unit["text"]), unit))
    encoded = tokenizer(source, add_special_tokens=False, return_offsets_mapping=True, truncation=False)
    offsets = encoded["offset_mapping"]
    start, windows = 0, []
    while start < len(offsets):
        end = min(start + max_tokens, len(offsets))
        while True:
            a, b = offsets[start][0], offsets[end - 1][1]
            hit = [unit for lo, hi, unit in spans if lo < b and hi > a]
            headings = list(dict.fromkeys(h for unit in hit for h in unit["headings"]))
            text = source[a:b]
            embedding_text = contextualize(text, headings)
            count = len(tokenizer.encode(embedding_text, add_special_tokens=False))
            if count <= max_tokens or end == start + 1:
                break
            end -= max(1, count - max_tokens)
            end = max(end, start + 1)
        windows.append({
            "text": text, "embedding_text": embedding_text, "headings": headings,
            "source_refs": list(dict.fromkeys(r for unit in hit for r in unit["source_refs"])),
            "parent_ids": list(dict.fromkeys(unit["parent_id"] for unit in hit)),
            "pages": sorted({p for unit in hit for p in unit["pages"]}),
        })
        if end == len(offsets):
            break
        start = max(start + 1, end - overlap)
    return windows


def build_variants(directory: Path, max_tokens=512, overlap=64, tokenizer_name="jinaai/jina-embeddings-v3", picture_transcriptions=None, outline_review=None):
    if (directory / "experiment_freeze.json").exists():
        raise ValueError("Do not rebuild a frozen experiment; use a new artifact directory")
    from docling.chunking import HierarchicalChunker, HybridChunker
    from docling_core.transforms.chunker.hierarchical_chunker import ChunkingDocSerializer, ChunkingSerializerProvider
    from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
    from docling_core.transforms.serializer.markdown import MarkdownTableSerializer, MarkdownPictureSerializer
    from docling_core.transforms.serializer.base import BasePictureSerializer
    from docling_core.transforms.serializer.common import create_ser_result
    from docling_core.types.doc import DoclingDocument
    from transformers import AutoTokenizer

    if max_tokens < 64:
        raise ValueError("Use at least 64 tokens for this experiment")
    manifest = read_json(directory / "manifest.json")
    original = DoclingDocument.load_from_json(directory / "docling.json")
    doc, excluded = filter_document(original)
    review = apply_outline_review(doc, manifest, outline_review, directory / "docling.json")
    heading_audit = review["heading_adjustments"] if review else restore_heading_depth(doc)
    picture_text = load_picture_transcriptions(picture_transcriptions, manifest, doc)
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_name)
    if not tokenizer.is_fast:
        raise ValueError("Fixed windows need a fast tokenizer with offset mappings")
    # Counting tokens only; no embedding model is executed with these sequences.
    tokenizer.model_max_length = 10**9

    class ReviewedPictures(BasePictureSerializer):
        def serialize(self, *, item, doc_serializer, doc, **kwargs):
            original_result = MarkdownPictureSerializer().serialize(item=item, doc_serializer=doc_serializer, doc=doc, **kwargs)
            if item.self_ref in picture_text:
                description = create_ser_result(text="Diagram transcription reviewed against the PDF image:\n" + picture_text[item.self_ref]["text"], span_source=item)
                # Keep existing caption text and its own source span too. Adding
                # picture text must not silently remove previously indexed refs.
                parts = [description, original_result] if original_result.text else [description]
                return create_ser_result(text="\n\n".join(p.text for p in parts), span_source=parts)
            return original_result

    class MarkdownTables(ChunkingSerializerProvider):
        def get_serializer(self, doc):
            return ChunkingDocSerializer(doc=doc, table_serializer=MarkdownTableSerializer(), picture_serializer=ReviewedPictures())

    serializer = MarkdownTables()
    hierarchy = HierarchicalChunker(merge_list_items=False, serializer_provider=serializer)
    started = time.perf_counter()
    native_units = list(hierarchy.chunk(dl_doc=doc))
    units, parents, ref_parent = [], [], {}
    previous_heading = None
    for i, unit in enumerate(native_units):
        headings = list(unit.meta.headings or [])
        # A parent spans the numbered subsection, including its subordinate
        # examples, case headings, and author notes. It is not just one leaf.
        parent_headings = parent_headings_for(headings, review["parent_boundaries"] if review else None)
        if tuple(parent_headings) != previous_heading:
            parent_id = f"{manifest['document_id']}:p{len(parents):04d}"
            parents.append({"parent_id": parent_id, "headings": parent_headings, "unit_ids": [], "source_refs": [], "pages": [], "text": ""})
            previous_heading = tuple(parent_headings)
        refs = [item.self_ref for item in unit.meta.doc_items]
        record = {"unit_id": f"u{i:04d}", "text": unit.text, "headings": headings,
                  "source_refs": refs, "pages": pages_of(unit.meta.doc_items), "parent_id": parents[-1]["parent_id"]}
        units.append(record)
        parent = parents[-1]
        parent["unit_ids"].append(record["unit_id"])
        parent["source_refs"] = list(dict.fromkeys(parent["source_refs"] + refs))
        parent["pages"] = sorted(set(parent["pages"] + record["pages"]))
        local_headings = headings[len(parent_headings):]
        parent["text"] += ("\n\n" if parent["text"] else "") + contextualize(unit.text, local_headings)
        for ref in refs:
            ref_parent[ref] = parent["parent_id"]
    for parent in parents:
        parent.update(document_id=manifest["document_id"], source_type=manifest["source_type"], plan_required=manifest["plan_required"])
    hierarchy_seconds = time.perf_counter() - started
    hierarchical = [{"text": u["text"], "embedding_text": contextualize(u["text"], u["headings"]),
                     "headings": u["headings"], "source_refs": u["source_refs"],
                     "parent_ids": [u["parent_id"]], "pages": u["pages"]} for u in units]
    started = time.perf_counter()
    fixed = fixed_windows(units, tokenizer, max_tokens, overlap)
    fixed_seconds = time.perf_counter() - started
    started = time.perf_counter()
    hybrid_chunker = HybridChunker(
        tokenizer=HuggingFaceTokenizer(tokenizer=tokenizer, max_tokens=max_tokens),
        merge_peers=True, serializer_provider=serializer,
    )
    hybrid = []
    for chunk in hybrid_chunker.chunk(dl_doc=doc):
        refs = [item.self_ref for item in chunk.meta.doc_items]
        unknown = [ref for ref in refs if ref not in ref_parent]
        if unknown:
            raise ValueError(f"Hybrid has items outside canonical source: {unknown}")
        headings = list(chunk.meta.headings or [])
        hybrid.append({"text": chunk.text, "embedding_text": contextualize(chunk.text, headings),
                       "headings": headings, "source_refs": refs,
                       "parent_ids": list(dict.fromkeys(ref_parent[ref] for ref in refs)),
                       "pages": pages_of(chunk.meta.doc_items)})
    hybrid_seconds = time.perf_counter() - started

    config = {"tokenizer": tokenizer_name, "max_tokens": max_tokens, "overlap": overlap,
              "merge_peers": True, "table_serialization": "markdown",
              "headings": "same newline heading-prefix formatter across variants v1",
              "pipeline_version": "0.3.0",
              "parent_definition": "nearest reviewed boundary when supplied; otherwise nearest numbered subsection",
              "heading_depth": "integer and multipart outline; ambiguous integer restarts require a reviewed outline",
              "furniture_detection": "recognized labels plus identical non-numbered headings on >=3 pages in stable top 12 percent v1",
              "outline_review_sha256": hashlib.sha256(outline_review.read_bytes()).hexdigest() if outline_review else None,
              "picture_transcriptions_sha256": hashlib.sha256(picture_transcriptions.read_bytes()).hexdigest() if picture_transcriptions else None,
              "picture_serialization": "reviewed text plus preserved original captions and spans v1",
              "document_id": manifest["document_id"], "versions": manifest["versions"]}
    config_id = hashlib.sha256(__import__("json").dumps(config, sort_keys=True).encode()).hexdigest()[:12]
    stats = {}
    for name, records, seconds in [("fixed", fixed, fixed_seconds), ("hierarchical", hierarchical, hierarchy_seconds), ("hybrid", hybrid, hybrid_seconds)]:
        for i, record in enumerate(records):
            record.update(chunk_id=f"{manifest['document_id']}:{config_id}:{name}:{i:04d}", variant=name,
                          config_id=config_id, document_id=manifest["document_id"],
                          source_type=manifest["source_type"], plan_required=manifest["plan_required"],
                          token_count=len(tokenizer.encode(record["embedding_text"], add_special_tokens=False)))
        counts = sorted(r["token_count"] for r in records)
        covered = {ref for r in records for ref in r["source_refs"]}
        expected = set(ref_parent)
        stats[name] = {"chunks": len(records), "tokens_total": sum(counts), "tokens_median": counts[len(counts)//2] if counts else 0,
                       "tokens_max": max(counts, default=0), "over_512_or_configured_limit": sum(n > max_tokens for n in counts),
                       "missing_page_provenance": sum(not r["pages"] for r in records),
                       "uncovered_canonical_refs": sorted(expected - covered), "chunk_seconds": round(seconds, 3)}
        jsonl(directory / f"chunks_{name}.jsonl", records)
    write_json(directory / "units.json", units)
    write_json(directory / "parents.json", parents)
    write_json(directory / "exclusions.json", excluded)
    write_json(directory / "heading_adjustments.json", heading_audit)
    write_json(directory / "structure_review_audit.json", {k: v for k, v in review.items() if k != "parent_boundaries"} if review else {"review_status": "not_supplied", "reading_order_moves": []})
    write_json(directory / "picture_transcription_audit.json", list(picture_text.values()))
    report = {"config": config, "config_id": config_id, "canonical_units": len(units), "parents": len(parents),
              "excluded_items": len(excluded), "variants": stats,
              "warnings": ["Counts are structural diagnostics, not retrieval accuracy.",
                           "Hierarchical elements are intentionally not token-capped.",
                           "Source-item pages may be broader than a split excerpt, especially for multi-page tables.",
                           "Printed page labels have not been extracted."]}
    write_json(directory / "chunk_report.json", report)
    return report
