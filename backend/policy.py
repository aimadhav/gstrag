from enum import StrEnum

class Role(StrEnum):
    ADMIN = "admin"
    PLUS = "plus"
    PRO = "pro"

ALLOWED_SOURCES = {
    Role.ADMIN: frozenset(("icai_book", "private_book", "notification")),
    Role.PRO: frozenset(("icai_book", "private_book", "notification")),
    Role.PLUS: frozenset(("icai_book", "notification")),
}

def allowed_sources(role: str | Role) -> frozenset[str]:
    try:
        return ALLOWED_SOURCES[Role(role)]
    except (ValueError, KeyError):
        raise PermissionError("Unknown or missing user role")

def can_upload(role: str | Role) -> bool:
    return Role(role) is Role.ADMIN
