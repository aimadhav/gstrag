from dataclasses import dataclass
from fastapi import Header, HTTPException
from .policy import Role

@dataclass(frozen=True)
class CurrentUser:
    id: str
    role: Role

def current_user(x_user_id: str | None = Header(default=None), x_user_role: str | None = Header(default=None)) -> CurrentUser:
    """Temporary adapter for local development; replace with Supabase JWT verification.

    Production must derive both fields from the verified bearer token, never trust
    client-provided role headers.
    """
    if not x_user_id or not x_user_role:
        raise HTTPException(401, "Authentication required")
    try:
        return CurrentUser(x_user_id, Role(x_user_role))
    except ValueError as exc:
        raise HTTPException(401, "Invalid role") from exc

def require_admin(user: CurrentUser) -> CurrentUser:
    if user.role is not Role.ADMIN:
        raise HTTPException(403, "Admin role required")
    return user
