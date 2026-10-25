"""Single-process review API. Optional Gemini drafting, NEVER auto-approval."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import secrets
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Header, Response, Request
from pydantic import BaseModel, ConfigDict
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
import jwt

from .auth import PASSWORDS, Settings, issue_token, token_user_id
from .generation import DraftingService
from .models import (AdminQuery, Credentials, Decision, Draft, NewUser, PlanChange, QueryView, Question,
                     Revision, UserView, NotificationReview, SourceRejection, PublicationPrepare, PublicationActivate, UploadReservation, BookReview)
from .notification_publication import Publications
from .service import Corpus, RetrievalService, Worker
from .store import StateError, Store
from .sync_jobs import SyncJobs, SyncWorker, import_notifications
from .uploads import Uploads, UploadWorker, MAX_BYTES
from .notification_feed import SyncError


class SyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def timestamp(value):
    return datetime.fromtimestamp(value, timezone.utc)


def public_query(row):
    status = "safe_refusal" if row["status"] == "refused" else row["status"]
    messages = {"queued": "Your question is queued.", "processing": "Your question is being checked.",
                "pending_review": "This query needs admin review before an answer can be shown.",
                "approved": "Your approved answer is ready."}
    return {"id": row["id"], "conversation_id": row["conversation_id"], "parent_query_id": row["parent_query_id"],
        "question": row["question"], "as_of": row["as_of"], "topic_ids": json.loads(row["topic_ids"]),
        "status": status, "message": messages.get(status, row["public_message"] or "Further clarification is required."),
        "answer": row["answer_text"] if status == "approved" else None,
        "citations": json.loads(row["citations"]) if status == "approved" else [],
        "approval_kind": row["approval_kind"] if status == "approved" else None,
        "created_at": timestamp(row["created_at"]), "expires_at": timestamp(row["expires_at"])}


def admin_query(row):
    return {k: row[k] for k in ["id", "user_id", "question", "conversation_id", "parent_query_id", "as_of",
                               "status", "revision", "plan_at_retrieval", "draft_text"]} | {
        "topic_ids": json.loads(row["topic_ids"]), "packet": json.loads(row["private_packet"]) if row["private_packet"] else None,
        "expires_at": timestamp(row["expires_at"])}


def create_app(settings=None, store=None, service_factory=None, drafter=None, publications=None, sync_runner=None, upload_parser=None):
    settings = settings or Settings.local()
    store = store or Store(settings.db_path)
    drafter = drafter or DraftingService(settings)
    worker = Worker(store, service_factory or (lambda: RetrievalService(settings)), drafter)
    publications = publications or Publications(settings.root)
    uploads = Uploads(settings.root, publications, **({"parser": upload_parser} if upload_parser else {}))
    upload_worker = UploadWorker(uploads)
    sync_jobs = SyncJobs(settings.root / "data/app/notification_sync")
    sync_worker = SyncWorker(sync_jobs, sync_runner or (lambda: import_notifications(settings)))
    # A real Argon2 verification also runs for unknown usernames, not a shortcut.
    dummy_hash = PASSWORDS.hash("non-user-dummy-password-not-a-login")
    bearer = HTTPBearer(auto_error=False)

    @asynccontextmanager
    async def lifespan(app):
        try:
            if settings.notification_sync_enabled:
                sync_worker.start()
            if settings.worker_enabled:
                worker.start()
            if settings.upload_worker_enabled:
                upload_worker.start()
            yield
        finally:
            worker.close()
            sync_worker.close()
            upload_worker.close()

    app = FastAPI(title="GST RAG local review API", version="0.1.0", lifespan=lifespan,
                  description="Local resume project. Optional evidence-bound Gemini drafts remain private until explicit admin approval.")
    app.state.store, app.state.worker, app.state.settings = store, worker, settings
    app.state.sync_jobs, app.state.sync_worker = sync_jobs, sync_worker
    app.state.uploads, app.state.upload_worker = uploads, upload_worker

    @app.exception_handler(SyncError)
    async def ingestion_conflict(request, exc):
        return JSONResponse({"error": "ingestion_operation_conflict"}, status_code=409)

    @app.exception_handler(StateError)
    async def state_error(request, exc):
        return JSONResponse({"error": exc.code}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Pydantic's raw error input can include passwords. Do not echo it.
        return JSONResponse({"error": "invalid_request", "fields": [{"location": e["loc"], "message": e["msg"]} for e in exc.errors()]}, status_code=422)

    def current_user(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        try:
            if credentials is None:
                raise ValueError("missing")
            user = store.user(user_id=token_user_id(credentials.credentials, settings))
            if user is None or not user["active"]:
                raise ValueError("inactive")
        except (jwt.InvalidTokenError, ValueError, TypeError):
            raise HTTPException(401, "invalid_or_expired_credentials", headers={"WWW-Authenticate": "Bearer"}) from None
        # JWT plan is an informational snapshot; current DB entitlement wins.
        return user

    def admin(user=Depends(current_user)):
        if user["role"] != "admin":
            raise HTTPException(403, "admin_required")
        return user

    def sync_access(response: Response, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        response.headers["Cache-Control"] = "no-store"
        if not settings.notification_sync_enabled or not settings.notification_sync_secret:
            raise HTTPException(503, "notification_sync_disabled")
        if credentials is None or not secrets.compare_digest(credentials.credentials.encode(), settings.notification_sync_secret.encode()):
            raise HTTPException(401, "invalid_sync_credentials", headers={"WWW-Authenticate": "Bearer"})
        return True

    @app.post("/internal/notification-sync/jobs", status_code=202)
    def trigger_sync(body: SyncRequest, idempotency_key: Annotated[str, Header(min_length=1, max_length=128)],
                     access=Depends(sync_access)):
        if not sync_worker.ready:
            raise HTTPException(503, "notification_sync_worker_unavailable")
        job = sync_jobs.enqueue(idempotency_key)
        sync_worker.wake.set()
        return job

    @app.get("/internal/notification-sync/jobs/{job_id}")
    def sync_status(job_id: UUID, access=Depends(sync_access)):
        return sync_jobs.get(str(job_id))

    @app.get("/admin/ingestion/sync")
    def admin_sync_status(response: Response, actor=Depends(admin)):
        response.headers["Cache-Control"] = "no-store"
        return {"enabled": settings.notification_sync_enabled, "worker_ready": sync_worker.ready,
                "max_pages": settings.notification_sync_max_pages,
                "max_documents": settings.notification_sync_max_documents,
                "since_year": settings.notification_sync_since_year, "jobs": sync_jobs.list()}

    @app.post("/admin/ingestion/sync", status_code=202)
    def admin_trigger_sync(body: SyncRequest, response: Response,
                           idempotency_key: Annotated[str, Header(min_length=1, max_length=128)], actor=Depends(admin)):
        response.headers["Cache-Control"] = "no-store"
        if not settings.notification_sync_enabled:
            raise HTTPException(503, "notification_sync_disabled")
        if not sync_worker.ready:
            raise HTTPException(503, "notification_sync_worker_unavailable")
        job = sync_jobs.enqueue(idempotency_key)
        sync_worker.wake.set()
        return job

    @app.get("/health")
    def health():
        return {"status": "ok", "generation": drafter.configuration_status(), "retriever": settings.retriever,
                "notification_sync": ("ready" if sync_worker.ready else "unavailable")
                if settings.notification_sync_enabled else "disabled",
                "upload_worker": "ready" if upload_worker.ready else "unavailable"}

    @app.post("/auth/token")
    def login(body: Credentials):
        user = store.user(username=body.username)
        valid = PASSWORDS.verify(body.password.get_secret_value(), user["password_hash"] if user else dummy_hash)
        if not valid or user is None or not user["active"]:
            raise HTTPException(401, "invalid_credentials", headers={"WWW-Authenticate": "Bearer"})
        return {"access_token": issue_token(user, settings), "token_type": "bearer", "expires_in": settings.token_seconds}

    @app.get("/me", response_model=UserView)
    def me(user=Depends(current_user)):
        return user

    @app.post("/admin/users", response_model=UserView, status_code=201)
    def create_user(body: NewUser, actor=Depends(admin)):
        return store.create_user(body.username, PASSWORDS.hash(body.password.get_secret_value()), body.plan)

    @app.get("/admin/users", response_model=list[UserView])
    def users(actor=Depends(admin)):
        return store.users()

    @app.patch("/admin/users/{user_id}/plan", response_model=UserView)
    def change_plan(user_id: UUID, body: PlanChange, actor=Depends(admin)):
        return store.set_plan(str(user_id), body.plan)

    @app.post("/queries", response_model=QueryView, status_code=202)
    def submit(body: Question, user=Depends(current_user)):
        row = store.enqueue(user["id"], body.question, body.as_of.isoformat() if body.as_of else None,
                            list(dict.fromkeys(body.topic_ids)), str(body.parent_query_id) if body.parent_query_id else None)
        worker.wake_event.set()
        return public_query(row)

    @app.get("/queries", response_model=list[QueryView])
    def list_queries(conversation_id: UUID | None = None, limit: int = Query(50, ge=1, le=100),
                     offset: int = Query(0, ge=0), user=Depends(current_user)):
        return [public_query(r) for r in store.queries(user["id"], str(conversation_id) if conversation_id else None, limit=limit, offset=offset)]

    @app.get("/queries/{query_id}", response_model=QueryView)
    def query(query_id: UUID, user=Depends(current_user)):
        return public_query(store.query(str(query_id), user["id"]))

    @app.get("/admin/reviews", response_model=list[AdminQuery])
    def reviews(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), actor=Depends(admin)):
        return [admin_query(r) for r in store.queries(review_only=True, limit=limit, offset=offset)]

    @app.get("/admin/queries/{query_id}", response_model=AdminQuery)
    def private_query(query_id: UUID, actor=Depends(admin)):
        return admin_query(store.query(str(query_id)))

    @app.put("/admin/queries/{query_id}/draft", response_model=AdminQuery)
    def draft(query_id: UUID, body: Draft, actor=Depends(admin)):
        return admin_query(store.draft(str(query_id), body.revision, body.draft_text, actor["id"]))

    @app.post("/admin/queries/{query_id}/decision", response_model=QueryView)
    def decision(query_id: UUID, body: Decision, actor=Depends(admin)):
        return public_query(store.decide(str(query_id), body.revision, body.action, body.text, body.citation_ids, actor["id"]))

    @app.post("/admin/queries/{query_id}/reprocess", response_model=AdminQuery, status_code=202)
    def reprocess(query_id: UUID, body: Revision, actor=Depends(admin)):
        row = store.requeue(str(query_id), body.revision, actor["id"])
        worker.wake_event.set()
        return admin_query(row)

    def corpus():
        try:
            return Corpus(settings.root)
        except (OSError, ValueError, KeyError):
            raise HTTPException(503, "registered_corpus_unavailable") from None

    @app.get("/admin/sources")
    def sources(actor=Depends(admin)):
        return [{"document_id": r["document_id"], "name": r["name"], "source_type": r["source_type"],
                 "page_count": r["page_count"], "pdf_url": f"/admin/sources/{r['document_id']}/pdf",
                 "archived": r.get("archived", False), "replaced_by": r.get("replaced_by")} for r in corpus().sources.values()]

    @app.get("/admin/uploads")
    def list_uploads(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), actor=Depends(admin)):
        return uploads.list(actor, limit, offset)

    @app.post("/admin/uploads", status_code=201)
    def reserve_upload(body: UploadReservation, actor=Depends(admin)):
        if not upload_worker.ready:
            raise HTTPException(503, "upload_worker_unavailable")
        return uploads.reserve(body, actor)

    @app.get("/admin/uploads/{version_id}")
    def uploaded_source(version_id: str, actor=Depends(admin)):
        return uploads.get(version_id, actor)

    @app.put("/admin/uploads/{version_id}/pdf", status_code=202)
    async def upload_pdf(version_id: str, request: Request, actor=Depends(admin)):
        if not upload_worker.ready:
            raise HTTPException(503, "upload_worker_unavailable")
        upload = uploads.get(version_id, actor)
        if request.headers.get("content-type", "").split(";")[0].lower() != "application/pdf":
            raise HTTPException(415, "pdf_content_type_required")
        if request.headers.get("content-encoding", "identity") != "identity":
            raise HTTPException(415, "compressed_upload_not_supported")
        chunks = bytearray()
        async for chunk in request.stream():
            if len(chunks) + len(chunk) > min(MAX_BYTES, upload["byte_count"]):
                raise HTTPException(413, "uploaded_pdf_size_limit")
            chunks.extend(chunk)
        # PDF validation/SQLite/file writes run off the event loop.
        from starlette.concurrency import run_in_threadpool
        result = await run_in_threadpool(uploads.receive, version_id, bytes(chunks), actor)
        upload_worker.wake.set()
        return result

    @app.get("/admin/uploads/{version_id}/detail")
    def uploaded_detail(version_id: str, actor=Depends(admin)):
        return uploads.detail(version_id, actor)

    @app.get("/admin/uploads/{version_id}/pdf")
    def uploaded_pdf(version_id: str, actor=Depends(admin)):
        uploads.get(version_id, actor)
        path = publications.pdf(version_id, actor)
        return FileResponse(path, media_type="application/pdf", filename="source.pdf",
                            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @app.post("/admin/uploads/{version_id}/retry", status_code=202)
    def retry_uploaded_parse(version_id: str, actor=Depends(admin)):
        if not upload_worker.ready: raise HTTPException(503, "upload_worker_unavailable")
        result = uploads.retry(version_id, actor); upload_worker.wake.set(); return result

    @app.put("/admin/uploads/{version_id}/review")
    def review_uploaded_book(version_id: str, body: BookReview, actor=Depends(admin)):
        return uploads.review_book(version_id, body, actor)

    @app.get("/admin/sources/{document_id}/pdf")
    def pdf(document_id: str, actor=Depends(admin)):
        path = corpus().pdf_path(document_id)
        return FileResponse(path, media_type="application/pdf", filename=path.name,
                            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @app.get("/admin/ingestion/notifications")
    def ingestion_sources(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), actor=Depends(admin)):
        return publications.list_sources(actor, limit, offset)

    @app.get("/admin/ingestion/notifications/{version_id}")
    def ingestion_source(version_id: str, actor=Depends(admin)):
        return publications.detail(version_id, actor)

    @app.get("/admin/ingestion/notifications/{version_id}/pdf")
    def ingestion_pdf(version_id: str, actor=Depends(admin)):
        path = publications.pdf(version_id, actor)
        return FileResponse(path, media_type="application/pdf", filename=path.name,
                            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @app.put("/admin/ingestion/notifications/{version_id}/review")
    def source_review(version_id: str, body: NotificationReview, actor=Depends(admin)):
        return publications.review(version_id, body, actor)

    @app.post("/admin/ingestion/notifications/{version_id}/reject")
    def source_rejection(version_id: str, body: SourceRejection, actor=Depends(admin)):
        return publications.reject(version_id, body, actor)

    @app.get("/admin/ingestion/corpus")
    def active_corpus(actor=Depends(admin)):
        return publications.active(actor)

    @app.get("/admin/ingestion/publications")
    def ingestion_publications(actor=Depends(admin)):
        return publications.list_publications(actor)

    @app.post("/admin/ingestion/publications", status_code=201)
    def prepare_publication(body: PublicationPrepare, actor=Depends(admin)):
        return publications.prepare(body.version_ids, body.base_sha256, actor)

    @app.post("/admin/ingestion/publications/{publication_id}/activate")
    def activate_publication(publication_id: str, body: PublicationActivate, actor=Depends(admin)):
        return publications.activate(publication_id, body.base_sha256, actor, settings.retriever, settings.pinecone_index)

    # Optional same-origin UI; only built public assets, never the repo/data tree.
    frontend = settings.root / "frontend/dist"
    if (frontend / "index.html").is_file():
        app.mount("/app", StaticFiles(directory=frontend, html=True), name="frontend")

    return app
