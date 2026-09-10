from fastapi import Depends, FastAPI, Header, HTTPException
from .models import ChatRequest, ChatResponse, Chunk
from .policy import Role, allowed_sources
from .retrieval import filtered_chunks, format_evidence
from .citations import validate_citations
from .risk import review_reason
from .auth import current_user, require_admin

app = FastAPI(title="GST RAG Assistant", version="1.0.0")

# Demo store; replace with Supabase repository in deployment.
DEMO_CHUNKS = [
    Chunk(id="c1", document_id="icai-1", document_title="ICAI GST Book", source_type="icai_book", page_number=42, section_path=["Input Tax Credit"], content="A registered person may claim eligible input tax credit subject to the statutory conditions.", similarity=.91),
    Chunk(id="c2", document_id="private-1", document_title="GST Practitioner Notes", source_type="private_book", page_number=12, section_path=["Practical analysis"], content="Practical examples and analysis of input tax credit claims.", similarity=.95),
    Chunk(id="c3", document_id="notif-15-2025", document_title="Notification 15/2025-Central Tax", source_type="notification", page_number=2, section_path=["Effective date"], content="This notification applies from 1 July 2025.", similarity=.87),
]

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

def _role(value: str | None) -> Role:
    try: return Role(value or "")
    except ValueError: raise HTTPException(401, "A valid authenticated role is required")

@app.post("/api/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, x_user_role: str | None = Header(default=None)) -> ChatResponse:
    role = _role(x_user_role)
    evidence = filtered_chunks(DEMO_CHUNKS, allowed_sources(role))
    if not evidence:
        return ChatResponse(answer="I could not find enough reliable source material to answer this confidently.", status="refused")
    answer = f"Based on the available GST material, the relevant rule is described in the retrieved evidence. See [Source 1] ({evidence[0].document_title}, page {evidence[0].page_number})."
    citations = validate_citations(answer, evidence)
    reason = review_reason(payload.question, answer, evidence, bool(citations))
    return ChatResponse(answer=answer if not reason else "This answer requires admin review before it can be shown.", status="review_required" if reason else "approved", citations=citations, review_reason=reason)

@app.get("/api/me")
def me(user=Depends(current_user)):
    return {"id": user.id, "role": user.role}

@app.post("/api/admin/check")
def admin_check(user=Depends(current_user)):
    require_admin(user)
    return {"authorized": True}
