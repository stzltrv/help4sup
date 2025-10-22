from datetime import datetime

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Ticket(Base):
    __tablename__ = 'tickets'
    # temp vars
    local_id = int

    id: Mapped[int] = mapped_column(primary_key=True, nullable=False)
    system_name: Mapped[str] = mapped_column(String(16), nullable=False)
    # TODO
    # string > 16: HG-65931-157-MERGED
    mask: Mapped[str] = mapped_column(
        String(16), unique=True, index=True, nullable=False
    )
    group: Mapped[str] = mapped_column(String(16), nullable=False)
    # sub_group: Mapped[str] = mapped_column(String(16), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(255), nullable=False)
    user: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    spam_score: Mapped[float] = mapped_column(Float, default=0)


class SpamscoreList(Base):
    __tablename__ = 'ticket_spamscore_list'

    id: Mapped[int] = mapped_column(primary_key=True, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=True)
    subject: Mapped[str] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(String(255), nullable=True)
    body_hash: Mapped[str] = mapped_column(String(32), nullable=True)
    comment: Mapped[str] = mapped_column(String(255), nullable=True)
