"""Local-demo authentication: Argon2 passwords and short-lived signed JWTs."""

from dataclasses import dataclass, field
import os
from pathlib import Path
import secrets
import time

import jwt
from pwdlib import PasswordHash

PASSWORDS = PasswordHash.recommended()


@dataclass
class Settings:
    root: Path
    db_path: Path
    jwt_secret: str
    retriever: str = "bm25"
    worker_enabled: bool = True
    token_seconds: int = 1800
    pinecone_index: str = "gstrag-jina-v1"
    generation: str = "gemini"
    gemini_key: str | None = field(default=None, repr=False)
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_allow_firm_content: bool = False
    notification_sync_enabled: bool = False
    notification_sync_secret: str | None = field(default=None, repr=False)
    notification_sync_max_pages: int = 1
    notification_sync_max_documents: int = 2
    notification_sync_since_year: int = 2025
    upload_worker_enabled: bool = False

    def __post_init__(self):
        if len(self.jwt_secret.encode()) < 32:
            raise ValueError("GST_JWT_SECRET must contain at least 32 bytes")
        if self.retriever not in {"bm25", "jina", "pinecone"}:
            raise ValueError("GST_RETRIEVER must be bm25, jina, or pinecone")
        if self.generation not in {"gemini", "off"}:
            raise ValueError("GST_GENERATION must be gemini or off")
        import re
        if self.notification_sync_secret is not None:
            if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", self.notification_sync_secret):
                raise ValueError("GST_NOTIFICATION_SYNC_SECRET must be a 32–256 character URL-safe random secret")
            if self.notification_sync_secret == self.jwt_secret:
                raise ValueError("Notification sync and JWT signing secrets must be different")
        if self.notification_sync_enabled and not self.notification_sync_secret:
            raise ValueError("Notification sync requires its dedicated secret")
        if not (1 <= self.notification_sync_max_pages <= 5 and 1 <= self.notification_sync_max_documents <= 5
                and 2000 <= self.notification_sync_since_year <= 2099):
            raise ValueError("Notification sync bounds are invalid")
        if not re.fullmatch(r"gemini-[a-z0-9.-]{1,80}", self.gemini_model):
            raise ValueError("GEMINI_MODEL must be a plain Gemini model ID")

    @classmethod
    def local(cls):
        from dotenv import load_dotenv
        root = Path(__file__).resolve().parents[2]
        load_dotenv(root / ".env", override=False)
        secret = os.environ.get("GST_JWT_SECRET")
        if not secret:
            path = root / "data/app/jwt.key"
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with path.open("x", encoding="utf-8") as handle:
                    handle.write(secrets.token_urlsafe(48))
            except FileExistsError:
                pass
            secret = path.read_text(encoding="utf-8").strip()
        return cls(root=root, db_path=root / "data/app/gstrag.sqlite3", jwt_secret=secret,
                   retriever=os.environ.get("GST_RETRIEVER", "bm25"),
                   pinecone_index=os.environ.get("PINECONE_INDEX_NAME", "gstrag-jina-v1"),
                   generation=os.environ.get("GST_GENERATION", "gemini"),
                   gemini_key=os.environ.get("GEMINI_API_KEY", "").strip() or None,
                   gemini_model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
                   gemini_allow_firm_content=os.environ.get("GEMINI_ALLOW_FIRM_CONTENT", "false").lower() == "true",
                   notification_sync_enabled=os.environ.get("GST_NOTIFICATION_SYNC_ENABLED", "false").lower() == "true",
                   notification_sync_secret=os.environ.get("GST_NOTIFICATION_SYNC_SECRET", "").strip() or None,
                   notification_sync_max_pages=int(os.environ.get("GST_NOTIFICATION_SYNC_MAX_PAGES", "1")),
                   notification_sync_max_documents=int(os.environ.get("GST_NOTIFICATION_SYNC_MAX_DOCUMENTS", "2")),
                   notification_sync_since_year=int(os.environ.get("GST_NOTIFICATION_SYNC_SINCE_YEAR", "2025")),
                   upload_worker_enabled=os.environ.get("GST_UPLOAD_WORKER_ENABLED", "true").lower() == "true")


def issue_token(user, settings):
    now = int(time.time())
    return jwt.encode({"sub": user["id"], "plan": user["plan"], "iat": now, "exp": now + settings.token_seconds,
                       "iss": "gst-rag-local", "aud": "gst-rag-api"}, settings.jwt_secret, algorithm="HS256")


def token_user_id(token, settings):
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], issuer="gst-rag-local", audience="gst-rag-api",
                      options={"require": ["sub", "iat", "exp", "iss", "aud"]})["sub"]
