"""
User model, matching elysium_master.users (docs/IMPLEMENTATION_PLAN.md
section 2.1). `roles` is an array rather than the LLD's single `role` field
— see plan section 10 item 1 for why.
"""

from dataclasses import dataclass, field
from datetime import datetime

ROLE_ADMIN = "admin"
ROLE_STREAMER = "streamer"


@dataclass
class User:
    id: str
    username: str
    password_hash: str
    roles: list[str] = field(default_factory=list)
    streamer_database_key: str | None = None
    streamer_database_name: str | None = None
    is_active: bool = True
    decommission_status: str | None = None
    created_at: datetime | None = None
    created_by: str | None = None
    updated_at: datetime | None = None
    password_reset_at: datetime | None = None
    disabled_at: datetime | None = None

    @property
    def is_admin(self) -> bool:
        return ROLE_ADMIN in self.roles

    @property
    def is_streamer(self) -> bool:
        return ROLE_STREAMER in self.roles

    def to_document(self) -> dict:
        doc = {
            "_id": self.id,
            "username": self.username,
            "password_hash": self.password_hash,
            "roles": self.roles,
            "is_active": self.is_active,
            "decommission_status": self.decommission_status,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "updated_at": self.updated_at,
            "password_reset_at": self.password_reset_at,
            "disabled_at": self.disabled_at,
        }

        # Sparse unique indexes only skip documents missing the field
        # entirely -- a stored `null` still counts as a value and would let
        # at most one non-streamer account ever exist. Omit rather than
        # null these out for non-streamers.
        if self.streamer_database_key is not None:
            doc["streamer_database_key"] = self.streamer_database_key

        if self.streamer_database_name is not None:
            doc["streamer_database_name"] = self.streamer_database_name

        return doc

    @staticmethod
    def from_document(doc: dict) -> "User":
        return User(
            id=doc["_id"],
            username=doc["username"],
            password_hash=doc["password_hash"],
            roles=list(doc.get("roles", [])),
            streamer_database_key=doc.get("streamer_database_key"),
            streamer_database_name=doc.get("streamer_database_name"),
            is_active=doc.get("is_active", True),
            decommission_status=doc.get("decommission_status"),
            created_at=doc.get("created_at"),
            created_by=doc.get("created_by"),
            updated_at=doc.get("updated_at"),
            password_reset_at=doc.get("password_reset_at"),
            disabled_at=doc.get("disabled_at"),
        )
