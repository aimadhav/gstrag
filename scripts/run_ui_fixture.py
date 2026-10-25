"""Disposable localhost UI integration fixture, NOT real ingestion or legal advice.

Uses the real auth/queue/review API with only synthetic evidence and a temporary
SQLite database. Never reads .env, original PDFs or provider keys. Public test
credentials below have no access to the real corpus and vanish on shutdown.
"""

import argparse
from pathlib import Path
import secrets
import tempfile

import uvicorn

from gst_rag.api import create_app
from gst_rag.auth import PASSWORDS, Settings
from gst_rag.ingestion import write_json
from gst_rag.store import Store

FIXTURE_PASSWORD = "ui-fixture-only-12345"  # Deliberately public, disposable test fixture.


class FixtureRetrieval:
    def retrieve(self, question, topics, as_of, plan):
        return {"status": "review_required", "retriever": "synthetic_fixture", "context_tokens": 20,
            "plan_used": plan, "current_law_verified": False, "history_used_as_evidence": False,
            "review_reasons": ["synthetic_evidence_only", "explicit_admin_approval_required"],
            "citations": [{"citation_id": "S1", "document_id": "synthetic-document", "source_name": "Synthetic UI fixture reference",
                "source_type": "icai_book", "pages": [1], "source_refs": ["synthetic-item"],
                "excerpt": "Synthetic source text for testing the interface. It makes no GST or legal assertion."}]}


class FixtureDrafting:
    def configuration_status(self):
        return "fixture_only"

    def draft(self, job, packet):
        return {**packet, "generation": "fixture_only"}, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="gst-ui-fixture-") as temporary:
        fixture = Path(temporary)
        write_json(fixture / "data/app/corpus.json", {"records": [], "sources": [], "links": []})
        settings = Settings(fixture, fixture / "fixture.sqlite3", secrets.token_urlsafe(48), generation="off")
        store = Store(settings.db_path)
        password_hash = PASSWORDS.hash(FIXTURE_PASSWORD)
        admin = store.create_user("ui-admin", password_hash, "pro", "admin", bootstrap=True)
        user = store.create_user("ui-user", password_hash, "plus")
        app = create_app(settings, store, lambda: FixtureRetrieval(), FixtureDrafting())
        first = store.enqueue(user["id"], "How do source citations work?", "2023-03-01", ["other_gst"])
        app.state.worker.run_once()
        private = store.query(first["id"])
        saved = store.draft(first["id"], private["revision"], "Book explanation\nThis is a synthetic UI workflow fixture, not tax advice. [S1]\n\nPractical effect\nUse this screen to test source citations and human review.", admin["id"])
        store.decide(first["id"], saved["revision"], "approve", None, ["S1"], admin["id"])
        store.enqueue(user["id"], "Which facts should a reviewer inspect?", "2023-03-01", ["other_gst"])
        # The temporary fixture can also serve the exact built frontend at /app/.
        if (root / "frontend/dist/index.html").is_file():
            from fastapi.staticfiles import StaticFiles
            app.mount("/app", StaticFiles(directory=root / "frontend/dist", html=True))
        print("SYNTHETIC UI FIXTURE ONLY: ui-user / ui-admin; password: " + FIXTURE_PASSWORD, flush=True)
        print("No real documents, provider calls or permanent accounts. Ctrl+C removes the temporary fixture database.", flush=True)
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
