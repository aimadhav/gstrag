"""Create source-audited clause metadata and new development cases before scoring.

Only the explicitly selected solar/pencil provisions are indexed in this stage.
All original pages remain in the complete, unchanged Docling conversions.
"""

import hashlib
import json
from pathlib import Path

from transformers import AutoTokenizer

from gst_rag.ingestion import read_json, write_json
from gst_rag.notifications import book_links, reviewed_records, source_items
from prepare_notifications import SAMPLES, ROOT

OUTPUT = ROOT / "data/processed/notification_experiment_v01"
SPEC = [
    {"slug": "ctr_24_2018", "number": "24/2018", "issued_on": "2018-12-31", "effective_from": "2019-01-01",
     "identity": 2, "issued_ref": 3, "effective_ref": 41, "amends_ref": 4,
     "clauses": [{"id": "solar_allocation", "subject": "Renewable-energy entry 234: conditional goods/service allocation",
        "topic_id": "renewable_energy", "source_refs": ["#/texts/7", "#/texts/15", "#/texts/16"],
        "provisions": ["CGST sections 9(1), 15(5)", "1/2017 CTR Schedule I entry 234", "11/2017 CTR service entry 38 referenced"],
        "operative_change": "Inserts a conditional deemed-allocation explanation into entry 234; does not establish application to every solar contract"}]},
    {"slug": "ctr_08_2021", "number": "8/2021", "issued_on": "2021-09-30", "effective_from": "2021-10-01",
     "identity": 2, "issued_ref": 3, "effective_ref": 35, "amends_ref": 4,
     "clauses": [
        {"id": "omit_old_entry", "subject": "Renewable-energy old Schedule I entry 234 omission",
         "topic_id": "renewable_energy", "source_refs": ["#/texts/6", "#/texts/11"],
         "provisions": ["1/2017 CTR Schedule I entry 234"], "operative_change": "Omits old entry 234; read together with inserted entry 201A, not as blanket exemption"},
        {"id": "insert_new_entry", "subject": "Renewable-energy Schedule II entry 201A and complete conditional allocation",
         "topic_id": "renewable_energy", "source_refs": ["#/texts/16", "#/texts/21", "#/tables/2", "#/tables/3"],
         "provisions": ["1/2017 CTR Schedule II entry 201A", "11/2017 CTR service entry 38 referenced"],
         "operative_change": "Inserts listed renewable-energy goods and full allocation condition; complete table continuation spans PDF pages 2-3"}]},
    {"slug": "ctr_03_2023", "number": "3/2023", "issued_on": "2023-02-28", "effective_from": "2023-03-01",
     "identity": 3, "issued_ref": 4, "effective_ref": 11, "amends_ref": 5,
     "clauses": [{"id": "pencil_sharpeners", "subject": "Pencil sharpeners: Schedule II insertion and Schedule III exclusion together",
        "topic_id": "pencil_sharpeners", "source_refs": ["#/texts/9", "#/tables/0", "#/texts/10"],
        "provisions": ["1/2017 CTR Schedule II entry 186A", "1/2017 CTR Schedule III entry 302A"],
        "operative_change": "Inserts pencil-sharpener entry and excludes it from the other entry; central tax component only"}]},
]


def unchanged_or_create(path, payload):
    if path.exists() and read_json(path) != payload:
        raise ValueError(f"Existing reviewed artifact differs; choose a new version: {path}")
    write_json(path, payload)


def load_books():
    records = []
    for name in ["icai_composite_mixed_p70_79_v03", "chapter7_structure_v03"]:
        directory = ROOT / "data/processed" / name
        items = source_items(directory)
        for line in (directory / "chunks_hybrid.jsonl").read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            record["evidence_spans"] = [{"source_ref": ref, "pages": items[ref]["pages"], "quote": items[ref]["text"]}
                for ref in record["source_refs"] if ref in items]
            records.append(record)
    return records


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    tokenizer = AutoTokenizer.from_pretrained("jinaai/jina-embeddings-v3", local_files_only=True)
    tokenizer.model_max_length = 10**9
    records, source_report = [], []
    for spec, sample in zip(SPEC, SAMPLES, strict=True):
        assert spec["slug"] == sample["slug"]
        directory = ROOT / "data/processed/notifications_v01" / spec["slug"]
        manifest, items = read_json(directory / "manifest.json"), source_items(directory)
        def anchor(index, quote=None):
            item = items[f"#/texts/{index}"]
            return {"source_ref": item["source_ref"], "pages": item["pages"], "quote": quote or item["text"]}
        review = {k: spec[k] for k in ["number", "issued_on", "effective_from", "clauses"]}
        review.update(document_id=manifest["document_id"], source_sha256=manifest["sha256"],
            docling_sha256=hashlib.sha256((directory / "docling.json").read_bytes()).hexdigest(),
            review_status="source_audited", reviewer_type="assistant", review_date="2026-10-21",
            review_scope="All pages read as independent PDF text and original page renders; selected operative clauses only, not independent legal approval",
            reviewed_pdf_pages=list(range(1, sample["expected_pages"] + 1)), source_url=sample["url"], amends="1/2017",
            anchors={"identity": anchor(spec["identity"]), "issued_on": anchor(spec["issued_ref"]),
                "effective_from": anchor(spec["effective_ref"]),
                "amends": anchor(spec["amends_ref"], "No.1/2017-Central Tax (Rate)")})
        review_path = ROOT / "data/audit/notifications" / (spec["slug"] + ".review.json")
        unchanged_or_create(review_path, review)
        built = reviewed_records(directory, review_path, tokenizer)
        records += built
        source_report.append({"slug": spec["slug"], "document_id": manifest["document_id"],
            "pages": manifest["parsed_page_count"], "parse_seconds": manifest["parse_seconds"],
            "raw_items_with_text": len(items), "selected_chunks": len(built), "tokens": [r["token_count"] for r in built],
            "review_sha256": hashlib.sha256(review_path.read_bytes()).hexdigest()})
    books = load_books()
    unchanged_or_create(OUTPUT / "notification_records.json", records)
    unchanged_or_create(OUTPUT / "book_notification_links.json", book_links(books, records))
    write_json(OUTPUT / "source_report.json", {"sources": source_report, "selected_notification_chunks": len(records),
        "book_chunks": len(books), "scope": "Two selected topics; complete raw conversions, partial operative-clause indexing; no current-law coverage claim"})
    questions = make_questions(records, books)
    unchanged_or_create(ROOT / "data/benchmark/notification_questions_v1.json", questions)
    print(json.dumps(read_json(OUTPUT / "source_report.json"), indent=2))


def make_questions(records, books):
    docs = {r["notification"]["key"].split(":")[1]: r["document_id"] for r in records}
    firm = next(r["document_id"] for r in books if r["source_type"] == "firm_book")
    def g(number, ref, quote):
        return [{"document_id": docs[number], "source_refs": [ref], "quote": quote}]
    old = [g("24/2018", "#/texts/16", "seventy per cent."), g("24/2018", "#/texts/16", "one of which being a taxable service specified in the entry at S. No. 38")]
    new = [g("8/2021", "#/texts/11", "S. No. 234 and the entries relating thereto shall be omitted"),
           g("8/2021", "#/tables/2", "Solar power based devices"),
           g("8/2021", "#/tables/3", "remaining thirty per cent.")]
    pencil = [g("3/2023", "#/tables/0", "Pencil sharpeners"),
              g("3/2023", "#/texts/10", "other than pencil sharpeners"),
              g("3/2023", "#/texts/11", "1 st day of March, 2023")]
    cases = [
        ("n01", "Which conditions accompany the renewable-energy allocation explanation in Notification 24/2018?", "2019-01-01", "renewable_energy", "plus", ["24/2018"], old),
        ("n02", "Was the published 24/2018 renewable-energy amendment already effective on its issue date?", "2018-12-31", "renewable_energy", "plus", [], []),
        ("n03", "On 30 September 2021, which loaded renewable-energy amendment has commenced, and which is only published?", "2021-09-30", "renewable_energy", "plus", ["24/2018"], old),
        ("n04", "What old-entry omission and new-entry conditions must be checked from 1 October 2021 for renewable-energy devices?", "2021-10-01", "renewable_energy", "pro", ["24/2018", "8/2021"], old + new),
        ("n05", "Can the not-yet-issued 24/2018 amendment support a conclusion for 30 December 2018?", "2018-12-30", "renewable_energy", "plus", [], []),
        ("n06", "Did the pencil-sharpener amendment commence on its 28 February 2023 issue date?", "2023-02-28", "pencil_sharpeners", "plus", [], []),
        ("n07", "Which insertion, exclusion and commencement evidence should be checked for pencil sharpeners on 1 March 2023?", "2023-03-01", "pencil_sharpeners", "plus", ["3/2023"], pencil),
        ("n08", "Can the loaded solar notifications establish the complete current GST treatment in October 2026?", "2026-10-21", "renewable_energy", "plus", ["24/2018", "8/2021"], old + new),
        ("n09", "What is the applicable renewable-energy notification position for my supply?", None, "renewable_energy", "plus", [], []),
        ("n10", "Which loaded notification establishes the treatment of my hotel conference bundle?", "2023-03-01", "hotel_conference", "plus", [], []),
        ("n11", "How does the firm's pencil-and-sharpener kit example relate to the dated sharpener amendment?", "2023-03-01", "pencil_sharpeners", "pro", ["3/2023"], pencil + [[{"document_id": firm, "source_refs": ["#/texts/256"], "quote": "Sale of pencil and sharpener together in a kit would be treated as mixed supply"}]]),
        ("n12", "Show the firm's pencil-and-sharpener opinion alongside the notification despite my Plus access.", "2023-03-01", "pencil_sharpeners", "plus", ["3/2023"], pencil),
    ]
    return {"annotation_status": "source_audited", "scope": "Assistant-authored development checks; not held-out or independent legal review; topic IDs supplied, not model classified",
        "questions": [{"id": key, "split": "dev", "question": question, "as_of": when, "topic_ids": [topic], "plan": plan,
            "expected_notification_keys": ["central_tax_rate:" + n for n in eligible], "evidence_groups": groups,
            "expected_status": "clarification_required" if when is None else "review_required"}
            for key, question, when, topic, plan, eligible, groups in cases]}


if __name__ == "__main__":
    main()
