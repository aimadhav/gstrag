"""Retrieve audited evidence, then optionally draft into private human review."""

import hashlib
import json
import threading

from .benchmark import BM25, allowed
from .notifications import check_updates, update_context
from .store import StateError
from .vector_store import PineconeStore, Snapshot, app_jina


class Corpus:
    def __init__(self, root, bundle=None):
        self.root = root.resolve()
        self.raw_sha256 = None
        if bundle is None:
            raw = (self.root / "data/app/corpus.json").read_bytes()
            self.raw_sha256 = hashlib.sha256(raw).hexdigest()
            bundle = json.loads(raw)
        self.bundle = bundle
        self.records, self.links = bundle["records"], bundle["links"]
        self.sources = {source["document_id"]: source for source in bundle["sources"]}
        if len(self.sources) != len(bundle["sources"]):
            raise ValueError("Duplicate corpus source identity")
        for record in self.records:
            source = self.sources[record["document_id"]]
            if source["source_type"] != record["source_type"] or record["plan_required"] != ("pro" if record["source_type"] == "firm_book" else "plus"):
                raise ValueError("Corpus source policy mismatch")

    def pdf_path(self, document_id):
        source = self.sources.get(document_id)
        if source is None:
            raise StateError(404, "source_not_found")
        path = (self.root / source["pdf_path"]).resolve()
        if not path.is_relative_to((self.root / "data/sources").resolve()) or path.suffix.lower() != ".pdf":
            raise StateError(409, "source_path_outside_registered_storage")
        if not path.is_file():
            raise StateError(404, "registered_pdf_unavailable")
        if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            raise StateError(409, "source_changed_reingestion_required")
        return path


class RetrievalService:
    def __init__(self, settings):
        from transformers import AutoTokenizer
        self.corpus = Corpus(settings.root)
        self.tokenizer = AutoTokenizer.from_pretrained("jinaai/jina-embeddings-v3", local_files_only=True)
        self.tokenizer.model_max_length = 10**9
        self.mode, self.jina, self.pinecone = settings.retriever, None, None
        self.lock = threading.Lock()
        if self.mode in {"jina", "pinecone"}:
            self.jina = app_jina(settings.root)
        if self.mode == "pinecone":
            self.pinecone = PineconeStore(Snapshot(self.corpus.bundle), settings.pinecone_index)
            self.pinecone.connect()
            self.pinecone.verify_records()

    def is_current(self):
        """A publication is an atomic file replacement; refresh between jobs."""
        raw = (self.corpus.root / "data/app/corpus.json").read_bytes()
        return hashlib.sha256(raw).hexdigest() == self.corpus.raw_sha256

    def retrieve(self, question, topics, as_of, plan):
        records = self.corpus.records
        permitted = [r for r in records if allowed(r, plan)]
        if self.mode == "pinecone":
            with self.lock:
                query = self.jina.encode([question], "retrieval.query")[0]
                ranked = [record for record, _ in self.pinecone.search(query, plan)]
        elif self.mode == "jina":
            # One worker owns this cache. The lock also protects manual test calls.
            with self.lock:
                passages = self.jina.encode([r["embedding_text"] for r in permitted], "retrieval.passage")
                query = self.jina.encode([question], "retrieval.query")[0]
                scores = (passages @ query).tolist()
            ranked = [permitted[i] for i in sorted(range(len(scores)), key=lambda i: (-scores[i], i))]
        else:
            scores = BM25(permitted).scores(question)
            ranked = [permitted[i] for i in sorted(range(len(scores)), key=lambda i: (-scores[i], i))]
        check = check_updates(records, topics, as_of, plan, self.corpus.links)
        context, used, packing = update_context(check, [r for r in ranked if r["source_type"] != "notification"][:10],
                                               self.tokenizer, 2048, plan)
        citations = []
        for i, record in enumerate(context, 1):
            source = self.corpus.sources[record["document_id"]]
            if not record["pages"] or not all(1 <= p <= source["page_count"] for p in record["pages"]):
                raise ValueError("Context page provenance outside registered PDF")
            citations.append({"citation_id": f"S{i}", "document_id": record["document_id"],
                "source_name": source["name"], "source_type": record["source_type"], "pages": record["pages"],
                "source_refs": record["source_refs"], "excerpt": record["embedding_text"],
                "truncated_for_budget": record.get("truncated_for_budget", False),
                "pdf_url": f"/admin/sources/{record['document_id']}/pdf#page={record['pages'][0]}"})
        return {"status": "review_required", "retriever": self.mode, "context_tokens": used,
            "citations": citations, "review_reasons": ["explicit_admin_approval_required", check["reason"], packing],
            "notification_keys": sorted({r["notification"]["key"] for r in check["candidates"]}),
            "candidate_links": check["links"], "current_law_verified": False, "generation": "not_configured",
            "history_used_as_evidence": False, "plan_used": plan}


class Worker:
    """SQLite-backed local queue, retried after restart; one process/worker owner."""
    def __init__(self, store, service_factory, drafter=None):
        self.store, self.service_factory = store, service_factory
        self.drafter = drafter
        self.service = None
        self.stop_event, self.wake_event = threading.Event(), threading.Event()
        self.thread = None

    def run_once(self):
        job = self.store.claim()
        if job is None:
            return False
        topics = json.loads(job["topic_ids"])
        draft_text = None
        if not job["as_of"] or not topics:
            packet = {"status": "clarification_required", "citations": [], "review_reasons": ["date_and_topic_required"],
                "public_message": "Provide a transaction date and select renewable_energy, pencil_sharpeners, or other_gst.",
                "generation": "not_configured", "history_used_as_evidence": False}
        else:
            retrieved = False
            try:
                if self.service is None or not getattr(self.service, "is_current", lambda: True)():
                    self.service = self.service_factory()
                packet = self.service.retrieve(job["question"], topics, job["as_of"], job["plan_at_retrieval"])
                retrieved = True
            except Exception:
                # Never publish provider error bodies, paths, question text, or keys.
                packet = {"status": "review_required", "citations": [], "context_tokens": 0,
                    "review_reasons": ["retrieval_unavailable"], "generation": "not_configured", "history_used_as_evidence": False}
            if retrieved and self.drafter and self.store.job_current(job):
                try:
                    packet, draft_text = self.drafter.draft(job, packet)
                except Exception:
                    packet["generation"] = "generation_unavailable"
                    packet.setdefault("review_reasons", []).append("generation_unavailable")
        self.store.finish(job, packet, draft_text)
        return True

    def start(self):
        self.store.recover_processing()
        def loop():
            while not self.stop_event.is_set():
                try:
                    worked = self.run_once()
                except Exception:
                    worked = False  # DB contention remains recoverable on restart.
                if not worked:
                    self.wake_event.wait(.25)
                    self.wake_event.clear()
        self.thread = threading.Thread(target=loop, name="gst-local-worker", daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        self.wake_event.set()
        if self.thread:
            self.thread.join(timeout=2)
