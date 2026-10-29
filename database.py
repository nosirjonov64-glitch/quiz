from datetime import datetime
from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint, func
)
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from config import load_settings

settings = load_settings()
engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram user ID
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Quiz(Base):
    __tablename__ = "quizzes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text)
    options: Mapped[str] = mapped_column(Text)  # options separated by newline
    correct_index: Mapped[int] = mapped_column(Integer)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class UserSettings(Base):
    __tablename__ = "user_settings"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    category_ids: Mapped[str] = mapped_column(Text, default="")  # comma-separated IDs; empty means all
    quiz_style: Mapped[str] = mapped_column(String(20), default="inline")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_quiz_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class ChatSettings(Base):
    __tablename__ = "chat_settings"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_type: Mapped[str] = mapped_column(String(20))  # group, supergroup, channel
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    category_ids: Mapped[str] = mapped_column(Text, default="")
    quiz_style: Mapped[str] = mapped_column(String(20), default="inline")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_quiz_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    added_by: Mapped[int] = mapped_column(BigInteger)

class QuizResult(Base):
    __tablename__ = "quiz_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(BigInteger)
    selected_index: Mapped[int] = mapped_column(Integer)
    is_correct: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class AdminAudit(Base):
    __tablename__ = "admin_audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(100))
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_session():
    async with SessionLocal() as session:
        yield session
