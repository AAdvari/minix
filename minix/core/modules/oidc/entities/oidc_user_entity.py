from datetime import datetime
from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from minix.core.entity import SqlEntity


class OidcUserEntity(SqlEntity):
    """Profile row for an OIDC-authenticated user, keyed by the IdP ``sub``.

    Auto-provisioned on first authenticated request so the application has a
    stable local identity to attach data to, without storing passwords. The role
    is a plain string (e.g. "admin"/"user") so this module stays independent of
    the core auth module's role enum.
    """

    __tablename__ = "oidc_users"

    sub: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
