import random
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import User, Category, Quiz, UserSettings, ChatSettings

def parse_ids(value: str) -> list[int]:
    return [int(x) for x in value.split(",") if x.strip().isdigit()]

async def ensure_user(session: AsyncSession, user_id: int, username: str | None):
    user = await session.get(User, user_id)
    if not user:
        user = User(id=user_id, username=username)
        session.add(user)
        await session.flush()
        session.add(UserSettings(user_id=user_id, next_quiz_at=datetime.now(timezone.utc) + timedelta(minutes=60)))
    else:
        user.username = username
    await session.commit()
    return user

async def get_categories(session: AsyncSession):
    result = await session.execute(select(Category).where(Category.active.is_(True)).order_by(Category.name))
    return list(result.scalars().all())

async def get_random_quiz(session: AsyncSession, category_ids: list[int] | None = None):
    stmt = select(Quiz).where(Quiz.active.is_(True))
    if category_ids:
        stmt = stmt.where(Quiz.category_id.in_(category_ids))
    result = await session.execute(stmt)
    quizzes = list(result.scalars().all())
    return random.choice(quizzes) if quizzes else None

def quiz_options(quiz: Quiz) -> list[str]:
    return [line.strip() for line in quiz.options.splitlines() if line.strip()]

def next_time(minutes: int):
    return datetime.now(timezone.utc) + timedelta(minutes=max(1, minutes))

async def send_quiz(bot, chat_id: int, quiz: Quiz, style: str, user_id: int | None = None):
    options = quiz_options(quiz)
    if len(options) < 2 or not (0 <= quiz.correct_index < len(options)):
        return
    if style == "poll":
        await bot.send_poll(
            chat_id=chat_id,
            question=quiz.question[:300],
            options=[o[:100] for o in options[:10]],
            type="quiz",
            correct_option_id=quiz.correct_index,
            explanation=(quiz.explanation or "")[:200] or None,
            is_anonymous=(chat_id < 0),
        )
    else:
        from keyboards import options_keyboard
        await bot.send_message(chat_id, f"🧠 <b>{quiz.question}</b>", reply_markup=options_keyboard(quiz.id, options), parse_mode="HTML")
