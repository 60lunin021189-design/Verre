"""SQLAlchemy models for Verre."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    """A Telegram user that has interacted with the bot."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mode: Mapped[str] = mapped_column(String(16), default="dryrun", nullable=False)
    size_percent: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    spot_mirror_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    api_key: Mapped[ApiKey | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    tracked: Mapped[list[TrackedLeader]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    mirrored_positions: Mapped[list[MirroredPosition]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ApiKey(Base):
    """Binance API key/secret encrypted at rest."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    encrypted_key: Mapped[str] = mapped_column(String, nullable=False)
    encrypted_secret: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    user: Mapped[User] = relationship(back_populates="api_key")


class TrackedLeader(Base):
    """A leaderboard trader (encryptedUid) followed by a user."""

    __tablename__ = "tracked_leaders"
    __table_args__ = (UniqueConstraint("user_id", "leader_uid", name="uq_user_leader"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    leader_uid: Mapped[str] = mapped_column(String(128), index=True)
    nickname: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    user: Mapped[User] = relationship(back_populates="tracked")


class MirroredPosition(Base):
    """A position currently mirrored for a user from a given leader."""

    __tablename__ = "mirrored_positions"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "leader_uid", "symbol", "position_side", name="uq_user_leader_symbol_side"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    leader_uid: Mapped[str] = mapped_column(String(128), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    # "LONG" or "SHORT" — derived from leader's position direction.
    position_side: Mapped[str] = mapped_column(String(8), nullable=False)
    # "FUTURES" or "SPOT" — where the order was placed for the user.
    market: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    leverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    user: Mapped[User] = relationship(back_populates="mirrored_positions")
