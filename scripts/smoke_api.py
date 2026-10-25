"""Real localhost HTTP smoke with audited corpus and TEMPORARY users/database.

No persistent login, credentials or legal answer is created. BM25 makes no
provider calls; --retriever pinecone explicitly uses live Pinecone/Jina.
--fake-generation tests the real drafting/validation/storage flow with a local
synthetic provider, NEVER Google, even if a real Gemini key exists in .env.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time

import httpx
import uvicorn
from dotenv import load_dotenv

from gst_rag.api import create_app
from gst_rag.auth import PASSWORDS, Settings
from gst_rag.generation import DraftingService
from gst_rag.ingestion import write_json
from gst_rag.store import Store

ROOT = Path(__file__).resolve().parents[1]


class SyntheticDraftProvider:
    """Not a model or legal answer: deterministic local transport substitute."""
    def __init__(self):
        self.calls = 0

    def generate(self, data):
        self.calls += 1
        books = [c for c in data["evidence"] if c["source_type"] != "notification"]
        notices = [c for c in data["evidence"] if c["source_type"] == "notification"]
        def claims(sources):
            return [{"text": "Synthetic workflow statement: this excerpt is available for admin review, not a GST conclusion.",
                     "evidence": [{"citation_id": sources[0]["citation_id"], "quote": sources[0]["excerpt"][:240]}]}] if sources else []
        return {"status": "draft", "book_explanation": claims(books), "latest_notification": claims(notices),
                "practical_effect": [], "limitations": ["Synthetic local fake-provider output, not a live Gemini answer."],
                "review_flags": ["uncertain"], "clarification_question": ""}, {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retriever", choices=["bm25", "pinecone"], default="bm25")
    parser.add_argument("--fake-generation", action="store_true")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    checks, timings = {}, {}
    with tempfile.TemporaryDirectory(prefix="gst-api-smoke-") as temp:
        settings = Settings(ROOT, Path(temp) / "smoke.sqlite3", secrets.token_urlsafe(48), retriever=args.retriever,
                            pinecone_index=os.environ.get("PINECONE_INDEX_NAME", "gstrag-jina-v1"),
                            gemini_key="synthetic-offline-not-a-key" if args.fake_generation else None,
                            gemini_allow_firm_content=args.fake_generation)
        store = Store(settings.db_path)
        password = secrets.token_urlsafe(24)
        store.create_user("smoke-admin", PASSWORDS.hash(password), "pro", "admin", bootstrap=True)
        fake_provider = SyntheticDraftProvider() if args.fake_generation else None
        app = create_app(settings, store, drafter=DraftingService(settings, fake_provider))
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", access_log=False))
        thread = threading.Thread(target=server.run, name="gst-http-smoke", daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 20
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(.05)
            if not server.started:
                raise RuntimeError("Local test server did not start")
            port = server.servers[0].sockets[0].getsockname()[1]
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=20) as client:
                def auth(username):
                    response = client.post("/auth/token", json={"username": username, "password": password})
                    response.raise_for_status()
                    return {"Authorization": "Bearer " + response.json()["access_token"]}
                admin = auth("smoke-admin")
                created = client.post("/admin/users", headers=admin, json={"username": "smoke-pro", "password": password, "plan": "pro"})
                created.raise_for_status()
                user_id = created.json()["id"]
                user = auth("smoke-pro")

                def submit(question, parent=None):
                    body = {"question": question, "as_of": "2023-03-01", "topic_ids": ["pencil_sharpeners"]}
                    if parent:
                        body["parent_query_id"] = parent
                    response = client.post("/queries", headers=user, json=body)
                    checks["submission_returns_202"] = response.status_code == 202
                    response.raise_for_status()
                    return response.json()

                def wait(query_id):
                    start = time.monotonic()
                    deadline = start + 150
                    while time.monotonic() < deadline:
                        response = client.get("/queries/" + query_id, headers=user)
                        response.raise_for_status()
                        row = response.json()
                        if row["status"] not in {"queued", "processing"}:
                            timings[query_id] = round(time.monotonic() - start, 3)
                            return row
                        time.sleep(.1)
                    raise RuntimeError("Worker did not complete the HTTP smoke query")

                first = submit("How does the firm's pencil-and-sharpener kit example relate to the dated sharpener amendment?")
                public = wait(first["id"])
                private = client.get("/admin/queries/" + first["id"], headers=admin).json()
                packet = private["packet"]
                checks["real_retrieval_pending_review"] = public["status"] == "pending_review" and packet.get("retriever") == args.retriever
                checks["pro_receives_real_firm_and_notification_evidence"] = {"firm_book", "notification"} <= {c["source_type"] for c in packet["citations"]}
                checks["context_within_2048_tokens"] = packet["context_tokens"] <= 2048
                citation = next(c for c in packet["citations"] if c["source_type"] == "firm_book")
                pdf_path = citation["pdf_url"].split("#")[0]
                checks["pdf_download_admin_only"] = client.get(pdf_path, headers=user).status_code == 403 and client.get(pdf_path, headers=admin).status_code == 200
                if args.fake_generation:
                    draft_text = private["draft_text"]
                    checks["fake_generated_draft_saved_privately"] = packet["generation"] == "validated_private_draft" and bool(draft_text)
                    revision = private["revision"]
                    selected_citations = packet["generation_details"]["citation_ids"]
                else:
                    draft_text = "Synthetic workflow-check answer; this is not a GST conclusion."
                    saved = client.put(f"/admin/queries/{first['id']}/draft", headers=admin,
                        json={"revision": private["revision"], "draft_text": draft_text})
                    saved.raise_for_status()
                    revision = saved.json()["revision"]
                    selected_citations = [citation["citation_id"]]
                    checks["no_key_retains_manual_workflow"] = packet["generation"] == "not_configured"
                hidden = client.get("/queries/" + first["id"], headers=user).json()
                checks["draft_hidden_until_explicit_approval"] = hidden["answer"] is None and hidden["citations"] == [] and "packet" not in hidden
                approved = client.post(f"/admin/queries/{first['id']}/decision", headers=admin,
                    json={"revision": revision, "action": "approve", "citation_ids": selected_citations})
                approved.raise_for_status()
                checks["approval_exposes_text_and_plain_citations_only"] = approved.json()["answer"] == draft_text and set(approved.json()["citations"][0]) == {"citation_id", "source_name", "source_type", "pages"}
                changed = client.patch(f"/admin/users/{user_id}/plan", headers=admin, json={"plan": "plus"})
                changed.raise_for_status()
                checks["stale_pro_token_observes_current_plus_plan"] = client.get("/me", headers=user).json()["plan"] == "plus"
                checks["old_approved_pro_answer_survives_downgrade"] = client.get("/queries/" + first["id"], headers=user).json()["answer"] == draft_text
                followup = submit("Which loaded notification conditions apply to pencil sharpeners?", first["id"])
                after = wait(followup["id"])
                after_private = client.get("/admin/queries/" + followup["id"], headers=admin).json()
                checks["new_plus_followup_excludes_firm_sources_and_links"] = after_private["plan_at_retrieval"] == "plus" and all(
                    c["source_type"] != "firm_book" for c in after_private["packet"]["citations"]) and not after_private["packet"]["candidate_links"]
                checks["followup_shares_conversation_without_answer_replay"] = after["conversation_id"] == first["conversation_id"] and not after_private["packet"]["history_used_as_evidence"]
                checks["public_pending_response_hides_private_packet"] = after["answer"] is None and after["citations"] == [] and "packet" not in after and "draft_text" not in after
                checks["five_registered_sources"] = len(client.get("/admin/sources", headers=admin).json()) == 5
                if args.fake_generation:
                    checks["plus_followup_also_gets_private_validated_draft"] = after_private["packet"]["generation"] == "validated_private_draft" and bool(after_private["draft_text"])
        finally:
            server.should_exit = True
            thread.join(timeout=10)
        service = app.state.worker.service
        usage = {"jina_requests": service.jina.requests, "jina_tokens": service.jina.tokens,
                 "pinecone_requests": service.pinecone.requests, "pinecone_read_units": service.pinecone.read_units} if args.retriever == "pinecone" else {}
        result = {"status": "passed" if checks and all(checks.values()) else "failed", "checks": checks,
            "poll_to_review_seconds": list(timings.values()), "corpus_records": 149, "retriever": args.retriever,
            "provider_usage": usage, "provider_calls": sum(usage.get(k, 0) for k in ["jina_requests", "pinecone_requests"]),
            "generation_test_mode": "local_fake_provider" if args.fake_generation else "no_key_manual",
            "fake_generation_calls": fake_provider.calls if fake_provider else 0, "live_gemini_calls": 0,
            "scope": "Actual localhost HTTP, temporary users/SQLite, audited corpus, synthetic approved text. Optional local fake generation. Not answer accuracy, production security certification, or live Gemini generation."}
        destination = ROOT / "data/app/api_smoke.json" if args.retriever == "bm25" else ROOT / "data/app/pinecone" / (
            "http_smoke_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
        if args.fake_generation or args.retriever == "bm25":
            destination = ROOT / "data/app/generation" / ("http_" + result["generation_test_mode"] + "_" +
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
        write_json(destination, result)
        print(json.dumps(result, indent=2))
        if result["status"] != "passed":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
