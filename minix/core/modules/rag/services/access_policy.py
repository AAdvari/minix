# Framework access policy for the RAG routes: global roles only.
#
# The RAG controller asks one object every permission question — "may this
# caller do X on collection Y", "which collections may they see", "which
# documents may retrieval return". The framework answers from the caller's
# global role (UserRole on the API key) and nothing else. A consuming layer that
# needs per-collection grants or per-document visibility overrides
# `RagController._svc_access()` to return its own object with the same methods.
from typing import Iterable

from fastapi import HTTPException

from minix.core.modules.rag.config import RagConfig
from minix.core.modules.auth.dependencies import AuthContext
from minix.core.modules.auth.entities import UserRole


def not_found() -> HTTPException:
    """The ONE 404 body for "this resource does not exist, or is not yours".

    A uniform 404 status is not enough on its own: if a missing resource and a
    resource the caller may not see returned different bodies, the body would
    become an existence oracle. Every "absent or not yours" path raises this.

    A fresh dict per call — the value is handed to FastAPI's serializer and a
    shared mutable default is an accident waiting to happen.
    """
    return HTTPException(404, {"error": "not_found"})


# Action -> the least-privileged global role allowed to perform it. `read`-type
# actions are open to every authenticated caller, writes need a non-readonly
# role, and dropping a whole collection is admin-only.
_READ_ACTIONS = frozenset({"read", "list_documents", "search", "query", "match"})
_WRITE_ACTIONS = frozenset({"ingest", "delete_document", "update_collection"})
_ADMIN_ACTIONS = frozenset({"delete_collection"})


class RoleAccessPolicy:
    """Role-only permission decisions for the framework RAG controller.

    With `RAG_ACCESS_CONTROL_ENABLED=false` every check passes (the
    anonymous-admin developer flow). With it on, the caller's global role is
    enforced per action. There are no per-collection grants and no per-document
    visibility, so retrieval is never filtered here.
    """

    def _flag(self) -> bool:
        return RagConfig.ACCESS_CONTROL_ENABLED

    @staticmethod
    def _required_role(action: str) -> str:
        if action in _READ_ACTIONS:
            return "readonly"
        if action in _WRITE_ACTIONS:
            return "user"
        if action in _ADMIN_ACTIONS:
            return "admin"
        raise ValueError(f"Unknown action: {action!r}")

    def check_collection_permission(self, auth: AuthContext, collection: str,
                                    action: str, *, force: bool = False) -> bool:
        required = self._required_role(action)
        if not (force or self._flag()):
            return True
        if auth.role == UserRole.ADMIN:
            return True
        if required == "admin":
            return False
        if required == "user":
            return auth.role != UserRole.READONLY
        return True

    def require_collection_permission(self, auth: AuthContext, collection: str,
                                      action: str, *, force: bool = False) -> None:
        """Raise 403 if the caller's role cannot perform `action`."""
        if self.check_collection_permission(auth, collection, action, force=force):
            return
        required = self._required_role(action)
        raise HTTPException(
            status_code=403,
            detail={
                "error": "forbidden",
                "action": action,
                "collection": collection,
                "required_role": required,
                "message": f"Action '{action}' requires the '{required}' role.",
            },
        )

    def allowed_collections(self, auth: AuthContext, action: str,
                            requested: Iterable[str] | None = None) -> list[str]:
        """Collections the caller may perform `action` on: all of them (or all
        of `requested`) when their role allows the action, otherwise none."""
        from minix.core.registry import Registry
        from minix.core.modules.rag.repositories.collection_repository import (
            RagCollectionRepository,
        )
        allowed = self.check_collection_permission(auth, "", action)
        if requested is not None:
            return list(requested) if allowed else []
        if not allowed:
            return []
        return [r.name for r in Registry().get(RagCollectionRepository).list_all()]

    def allowed_document_ids(self, auth: AuthContext, collection_name: str,
                             *, include_restricted: bool = False) -> set[str] | None:
        """The retrieval allowlist both hybrid legs derive from. `None` means no
        filter: the framework has no per-document visibility."""
        return None
