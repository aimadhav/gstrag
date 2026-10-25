"""Strict request schemas and deliberately small public response schemas."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Credentials(StrictModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: SecretStr = Field(min_length=12, max_length=256)

    @field_validator("username")
    @classmethod
    def canonical_username(cls, value):
        return value.lower()


class NewUser(Credentials):
    plan: Literal["plus", "pro"] = "plus"


class PlanChange(StrictModel):
    plan: Literal["plus", "pro"]


class Question(StrictModel):
    question: str = Field(min_length=1, max_length=4000)
    as_of: date | None = None
    topic_ids: list[Literal["renewable_energy", "pencil_sharpeners", "other_gst"]] = Field(default_factory=list, max_length=3)
    parent_query_id: UUID | None = None


class Revision(StrictModel):
    revision: int = Field(ge=0)


class Draft(Revision):
    draft_text: str = Field(min_length=1, max_length=16000)


class Decision(Revision):
    action: Literal["approve", "edit_and_approve", "refuse", "request_clarification"]
    text: str | None = Field(default=None, min_length=1, max_length=16000)
    citation_ids: list[str] = Field(default_factory=list, max_length=20)


class UserView(BaseModel):
    id: str
    username: str
    role: Literal["user", "admin"]
    plan: Literal["plus", "pro"]


class PublicCitation(BaseModel):
    citation_id: str
    source_name: str
    source_type: Literal["firm_book", "icai_book", "notification"]
    pages: list[int]


class QueryView(BaseModel):
    id: str
    conversation_id: str
    parent_query_id: str | None
    question: str
    as_of: str | None
    topic_ids: list[str]
    status: str
    message: str
    answer: str | None
    citations: list[PublicCitation]
    approval_kind: str | None
    created_at: datetime
    expires_at: datetime


class AdminQuery(BaseModel):
    id: str
    user_id: str
    question: str
    conversation_id: str
    parent_query_id: str | None
    as_of: str | None
    topic_ids: list[str]
    status: str
    revision: int
    plan_at_retrieval: str | None
    draft_text: str | None
    packet: dict | None
    expires_at: datetime


class SourceAnchor(StrictModel):
    source_ref: str = Field(pattern=r"^#/(texts|tables)/\d+$")
    pages: list[int] = Field(min_length=1, max_length=30)
    quote: str = Field(min_length=5, max_length=4000)


class NotificationAnchors(StrictModel):
    identity: SourceAnchor
    issued_on: SourceAnchor
    effective_from: SourceAnchor
    amends: SourceAnchor | None = None


class NotificationClause(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    subject: str = Field(min_length=5, max_length=300)
    topic_id: Literal["renewable_energy", "pencil_sharpeners", "other_gst"]
    source_refs: list[str] = Field(min_length=1, max_length=60)
    provisions: list[str] = Field(min_length=1, max_length=20)
    operative_change: str = Field(min_length=5, max_length=2000)
    complete_clause_confirmed: Literal[True]


class NotificationReview(StrictModel):
    revision: int = Field(ge=0)
    stage_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    issued_on: date
    effective_from: date
    amends: str | None = Field(default=None, pattern=r"^central_tax(?:_rate)?:[1-9][0-9]{0,2}/[0-9]{4}$")
    source_checked: Literal[True]
    anchors: NotificationAnchors
    clauses: list[NotificationClause] = Field(min_length=1, max_length=20)


class SourceRejection(StrictModel):
    revision: int = Field(ge=0)
    stage_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=5, max_length=1000)


class PublicationPrepare(StrictModel):
    version_ids: list[str] = Field(min_length=1, max_length=10)
    base_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class PublicationActivate(StrictModel):
    base_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirm: Literal[True]


class UploadReservation(StrictModel):
    title: str = Field(min_length=3, max_length=160)
    source_type: Literal["icai_book", "firm_book", "notification"]
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    byte_count: int = Field(ge=1, le=25 * 1024 * 1024)
    replaces_document_id: str | None = Field(default=None, min_length=1, max_length=200)
    series: Literal["central_tax", "central_tax_rate"] | None = None
    number: int | None = Field(default=None, ge=1, le=999)
    year: int | None = Field(default=None, ge=2000, le=2099)


class BookReview(StrictModel):
    revision: int = Field(ge=0)
    stage_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: Literal["approve", "reject"]
    reason: str = Field(min_length=5, max_length=1000)
    source_checked: bool = False
    structure_checked: bool = False

    @model_validator(mode="after")
    def approval_checks(self):
        if self.action == "approve" and not (self.source_checked and self.structure_checked):
            raise ValueError("Book approval requires original PDF and structure review")
        return self
