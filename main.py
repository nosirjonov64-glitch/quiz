import asyncio
import logging
from datetime import datetime, timezone
from html import escape

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, delete

from config import load_settings
from database import init_db, SessionLocal, User, Category, Quiz, UserSettings, ChatSettings, QuizResult
from keyboards import main_menu, admin_menu, categories_keyboard, style_keyboard
from services import ensure_user, get_categories, get_random_quiz, quiz_options, next_time, parse_ids, send_quiz
from states import AdminFlow, UserFlow

logging.basicConfig(level=logging.INFO)
settings = load_settings()
bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="UTC")

def is_admin_id(user_id: int) -> bool:
    return user_id in settings.superadmin_ids

async def role_for(session, user_id: int) -> str:
    if is_admin_id(user_id):
        return "superadmin"
    user = await session.get(User, user_id)
    return user.role if user else "user"

async def can_admin(session, user_id: int) -> bool:
    return await role_for(session, user_id) in {"admin", "superadmin"}

async def refresh_user_role(session, user_id: int, username: str | None = None):
    user = await session.get(User, user_id)
    if not user:
        user = User(id=user_id, username=username, role="admin")
        session.add(user)
    else:
        user.role = "admin"
    await session.commit()

async def private_user(message: Message):
    if not message.from_user:
        return
    async with SessionLocal() as session:
        await ensure_user(session, message.from_user.id, message.from_user.username)

@dp.message(CommandStart())
async def start(message: Message):
    if not message.from_user:
        return
    async with SessionLocal() as session:
        user = await ensure_user(session, message.from_user.id, message.from_user.username)
        admin = is_admin_id(message.from_user.id) or user.role == "admin"
    await message.answer(
        "Salom! 🎯 Quiz botga xush kelibsiz.\n\n"
        "Quiz ishlash, intervalni sozlash yoki admin paneldan foydalanishingiz mumkin.",
        reply_markup=main_menu(admin)
    )

@dp.message(Command("help"))
@dp.message(F.text == "ℹ️ Yordam")
async def help_cmd(message: Message):
    await message.answer(
        "Buyruqlar:\n/start — boshlash\n/chatid — chat ID\n/bindchat — guruhni ro‘yxatdan o‘tkazish (guruh admini)\n"
        "/bindchannel — kanal ID sini shaxsiy chatdan ulash\n\n"
        "Shaxsiy interval: 🎯 Quiz sozlamalari. Adminlar: 🛠 Admin panel."
    )

@dp.message(Command("chatid"))
async def chatid(message: Message):
    await message.answer(f"Chat ID: <code>{message.chat.id}</code>\nTuri: <code>{message.chat.type}</code>")

@dp.message(Command("bindchat"))
async def bindchat(message: Message):
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        await message.answer("Bu buyruqni guruh ichida ishlating.")
        return
    if not message.from_user:
        return
    try:
        member = await bot.get_chat_member(message.chat.id, message.from_user.id)
        if member.status not in {"administrator", "creator"}:
            await message.answer("Faqat guruh administratori ulashi mumkin.")
            return
    except Exception:
        await message.answer("Guruhdagi admin huquqini tekshira olmadim. Botni guruhga qo‘shib qayta urinib ko‘ring.")
        return
    async with SessionLocal() as session:
        chat = await session.get(ChatSettings, message.chat.id)
        if not chat:
            chat = ChatSettings(chat_id=message.chat.id, chat_type=message.chat.type, title=message.chat.title,
                                interval_minutes=settings.default_chat_interval, category_ids="", quiz_style="inline",
                                enabled=True, next_quiz_at=next_time(settings.default_chat_interval), added_by=message.from_user.id)
            session.add(chat)
        else:
            chat.enabled = True
            chat.next_quiz_at = next_time(chat.interval_minutes)
        await session.commit()
    await message.answer("✅ Guruh ro‘yxatdan o‘tdi. Quizlar belgilangan intervalda yuboriladi.")

@dp.message(Command("bindchannel"))
async def bindchannel_start(message: Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE or not message.from_user:
        await message.answer("Bu buyruqni botning shaxsiy chatida ishlating.")
        return
    async with SessionLocal() as session:
        if not await can_admin(session, message.from_user.id):
            await message.answer("Bu amal faqat adminlar uchun.")
            return
    await state.set_state(AdminFlow.channel_id)
    await message.answer("Kanalning raqamli ID sini yuboring (odatda -100 bilan boshlanadi). Bot kanal admini bo‘lishi kerak.")

@dp.message(AdminFlow.channel_id)
async def bindchannel_save(message: Message, state: FSMContext):
    if not message.from_user:
        return
    try:
        channel_id = int((message.text or "").strip())
        chat_info = await bot.get_chat(channel_id)
        if chat_info.type != ChatType.CHANNEL:
            raise ValueError
        member = await bot.get_chat_member(channel_id, (await bot.get_me()).id)
        if member.status not in {"administrator", "creator"}:
            await message.answer("Bot bu kanalda administrator emas. Avval kanalga admin qilib qo‘shing.")
            return
    except Exception:
        await message.answer("Kanal ID noto‘g‘ri yoki bot kanalga admin sifatida qo‘shilmagan. Qayta yuboring.")
        return
    async with SessionLocal() as session:
        chat = await session.get(ChatSettings, channel_id)
        if not chat:
            session.add(ChatSettings(chat_id=channel_id, chat_type="channel", title=chat_info.title,
                interval_minutes=settings.default_chat_interval, category_ids="", quiz_style="inline",
                enabled=True, next_quiz_at=next_time(settings.default_chat_interval), added_by=message.from_user.id))
        else:
            chat.enabled = True
            chat.next_quiz_at = next_time(chat.interval_minutes)
        await session.commit()
    await state.clear()
    await message.answer(f"✅ Kanal ulandi: <b>{escape(chat_info.title or str(channel_id))}</b>")

@dp.message(F.text == "🛠 Admin panel")
async def admin_panel(message: Message):
    if not message.from_user:
        return
    async with SessionLocal() as session:
        if not await can_admin(session, message.from_user.id):
            await message.answer("Sizda admin huquqi yo‘q.")
            return
        role = await role_for(session, message.from_user.id)
    await message.answer("Admin panel:", reply_markup=admin_menu(role == "superadmin"))

@dp.callback_query(F.data.startswith("admin:"))
async def admin_callbacks(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    action = callback.data.split(":", 1)[1]
    async with SessionLocal() as session:
        if not await can_admin(session, callback.from_user.id):
            await callback.answer("Ruxsat yo‘q", show_alert=True)
            return
        role = await role_for(session, callback.from_user.id)
        if action == "category_add":
            await state.set_state(AdminFlow.category_name)
            await callback.message.answer("Yangi kategoriya nomini yuboring:")
        elif action == "quiz_add":
            cats = await get_categories(session)
            if not cats:
                await callback.message.answer("Avval kategoriya yarating.")
            else:
                await state.set_state(AdminFlow.quiz_category)
                await callback.message.answer("Quiz qaysi kategoriyaga qo‘shilsin?", reply_markup=categories_keyboard(cats, "quizcat"))
        elif action == "categories":
            cats = await get_categories(session)
            await callback.message.answer("\n".join(f"{c.id}. {escape(c.name)}" for c in cats) or "Kategoriya yo‘q.")
        elif action == "quizzes":
            rows = (await session.execute(select(Quiz).order_by(Quiz.id.desc()).limit(30))).scalars().all()
            await callback.message.answer("\n".join(f"#{q.id} (cat {q.category_id}): {escape(q.question[:70])}" for q in rows) or "Quiz yo‘q.")
        elif action == "add_admin" and role == "superadmin":
            await state.set_state(AdminFlow.admin_id)
            await callback.message.answer("Admin qilinadigan foydalanuvchining Telegram ID sini yuboring:")
        elif action == "remove_admin" and role == "superadmin":
            await state.set_state(AdminFlow.remove_admin_id)
            await callback.message.answer("Adminlikdan olinadigan foydalanuvchining Telegram ID sini yuboring:")
    await callback.answer()

@dp.message(AdminFlow.category_name)
async def category_name(message: Message, state: FSMContext):
    if not message.from_user or not message.text:
        return
    async with SessionLocal() as session:
        if not await can_admin(session, message.from_user.id):
            await state.clear(); await message.answer("Ruxsat yo‘q."); return
        name = message.text.strip()[:120]
        existing = (await session.execute(select(Category).where(Category.name == name))).scalar_one_or_none()
        if existing:
            await message.answer("Bu kategoriya allaqachon mavjud.")
        else:
            session.add(Category(name=name))
            await session.commit()
            await message.answer(f"✅ Kategoriya yaratildi: <b>{escape(name)}</b>")
    await state.clear()

@dp.callback_query(F.data.startswith("quizcat:"))
async def quiz_category(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    async with SessionLocal() as session:
        if not await can_admin(session, callback.from_user.id):
            await callback.answer("Ruxsat yo‘q", show_alert=True); return
        category_id = int(callback.data.split(":")[1])
        if not await session.get(Category, category_id):
            await callback.answer("Kategoriya topilmadi", show_alert=True); return
    await state.update_data(category_id=category_id)
    await state.set_state(AdminFlow.quiz_question)
    await callback.message.answer("Savol matnini yuboring:")
    await callback.answer()

@dp.message(AdminFlow.quiz_question)
async def quiz_question(message: Message, state: FSMContext):
    if not message.from_user or not message.text:
        return
    async with SessionLocal() as session:
        if not await can_admin(session, message.from_user.id):
            await state.clear(); await message.answer("Ruxsat yo‘q."); return
    await state.update_data(question=message.text.strip()[:1000])
    await state.set_state(AdminFlow.quiz_options)
    await message.answer("Javob variantlarini har birini yangi qatordan yozing (2–10 ta).")

@dp.message(AdminFlow.quiz_options)
async def quiz_options_step(message: Message, state: FSMContext):
    if not message.text:
        return
    options = [line.strip() for line in message.text.splitlines() if line.strip()]
    if not 2 <= len(options) <= 10:
        await message.answer("2 tadan 10 tagacha variant kiriting, har biri yangi qatorda.")
        return
    await state.update_data(options=options)
    await state.set_state(AdminFlow.quiz_correct)
    numbered = "\n".join(f"{i+1}. {escape(o)}" for i, o in enumerate(options))
    await message.answer("To‘g‘ri javob raqamini yuboring:\n" + numbered)

@dp.message(AdminFlow.quiz_correct)
async def quiz_correct(message: Message, state: FSMContext):
    if not message.text or not message.text.strip().isdigit():
        await message.answer("Raqam yuboring.")
        return
    data = await state.get_data()
    correct = int(message.text.strip()) - 1
    if not 0 <= correct < len(data["options"]):
        await message.answer("Variant raqami noto‘g‘ri.")
        return
    await state.update_data(correct_index=correct)
    await state.set_state(AdminFlow.quiz_explanation)
    await message.answer("Izohni yuboring yoki '-' yuborib o‘tkazing.")

@dp.message(AdminFlow.quiz_explanation)
async def quiz_explanation(message: Message, state: FSMContext):
    if not message.from_user:
        return
    data = await state.get_data()
    explanation = (message.text or "").strip()
    async with SessionLocal() as session:
        if not await can_admin(session, message.from_user.id):
            await state.clear(); await message.answer("Ruxsat yo‘q."); return
        session.add(Quiz(category_id=data["category_id"], question=data["question"],
            options="\n".join(data["options"]), correct_index=data["correct_index"],
            explanation=None if explanation == "-" or not explanation else explanation[:1000],
            created_by=message.from_user.id, active=True))
        await session.commit()
    await state.clear()
    await message.answer("✅ Quiz saqlandi.")

@dp.message(AdminFlow.admin_id)
async def add_admin(message: Message, state: FSMContext):
    if not message.from_user or not (message.text or "").strip().isdigit():
        await message.answer("Raqamli Telegram ID yuboring."); return
    target = int(message.text.strip())
    async with SessionLocal() as session:
        if not is_admin_id(message.from_user.id):
            await state.clear(); await message.answer("Faqat superadmin."); return
        await refresh_user_role(session, target)
        await message.answer(f"✅ {target} admin qilindi.")
    await state.clear()

@dp.message(AdminFlow.remove_admin_id)
async def remove_admin(message: Message, state: FSMContext):
    if not message.from_user or not (message.text or "").strip().isdigit():
        await message.answer("Raqamli Telegram ID yuboring."); return
    target = int(message.text.strip())
    if target in settings.superadmin_ids:
        await message.answer("Superadminni bu yerdan olib tashlab bo‘lmaydi."); await state.clear(); return
    async with SessionLocal() as session:
        if not is_admin_id(message.from_user.id):
            await state.clear(); await message.answer("Faqat superadmin."); return
        user = await session.get(User, target)
        if user:
            user.role = "user"
            await session.commit()
        await message.answer(f"Adminlik bekor qilindi: {target}")
    await state.clear()

@dp.message(F.text == "🎯 Quiz sozlamalari")
async def user_settings(message: Message, state: FSMContext):
    if not message.from_user:
        return
    async with SessionLocal() as session:
        await ensure_user(session, message.from_user.id, message.from_user.username)
        cats = await get_categories(session)
    await message.answer("Quiz usulini tanlang:", reply_markup=style_keyboard("userstyle"))
    await message.answer("Kategoriyani tanlash (hammasi uchun /all yuboring):", reply_markup=categories_keyboard(cats, "usercat") if cats else None)
    await message.answer("Intervalni o‘zgartirish uchun /interval buyrug‘idan foydalaning.")

@dp.callback_query(F.data.startswith("userstyle:"))
async def user_style(callback: CallbackQuery):
    if not callback.from_user: return
    style = callback.data.split(":")[1]
    async with SessionLocal() as session:
        await ensure_user(session, callback.from_user.id, callback.from_user.username)
        prefs = await session.get(UserSettings, callback.from_user.id)
        prefs.quiz_style = style
        await session.commit()
    await callback.answer("Quiz usuli saqlandi")

@dp.callback_query(F.data.startswith("usercat:"))
async def user_category(callback: CallbackQuery):
    if not callback.from_user: return
    category_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        prefs = await session.get(UserSettings, callback.from_user.id)
        if not prefs:
            await ensure_user(session, callback.from_user.id, callback.from_user.username)
            prefs = await session.get(UserSettings, callback.from_user.id)
        prefs.category_ids = str(category_id)
        await session.commit()
    await callback.answer("Kategoriya saqlandi")

@dp.message(Command("all"))
async def all_categories(message: Message):
    if not message.from_user: return
    async with SessionLocal() as session:
        prefs = await session.get(UserSettings, message.from_user.id)
        if prefs:
            prefs.category_ids = ""
            await session.commit()
    await message.answer("Barcha kategoriyalar tanlandi.")

@dp.message(Command("interval"))
async def interval_cmd(message: Message, state: FSMContext):
    if not message.from_user: return
    await state.set_state(UserFlow.interval)
    await message.answer("Intervalni daqiqalarda yuboring (masalan, 30 yoki 120). Eng kamida 1 daqiqa.")

@dp.message(UserFlow.interval)
async def save_interval(message: Message, state: FSMContext):
    if not message.from_user or not (message.text or "").strip().isdigit():
        await message.answer("Butun son kiriting."); return
    minutes = int(message.text.strip())
    if not 1 <= minutes <= 10080:
        await message.answer("Interval 1–10080 daqiqa oralig‘ida bo‘lsin."); return
    async with SessionLocal() as session:
        prefs = await session.get(UserSettings, message.from_user.id)
        if not prefs:
            await ensure_user(session, message.from_user.id, message.from_user.username)
            prefs = await session.get(UserSettings, message.from_user.id)
        prefs.interval_minutes = minutes
        prefs.next_quiz_at = next_time(minutes)
        prefs.enabled = True
        await session.commit()
    await state.clear()
    await message.answer(f"✅ Shaxsiy quiz intervali: {minutes} daqiqa.")

@dp.callback_query(F.data.startswith("answer:"))
async def answer_quiz(callback: CallbackQuery):
    if not callback.from_user:
        return
    try:
        _, quiz_id_text, index_text = callback.data.split(":")
        quiz_id, selected = int(quiz_id_text), int(index_text)
    except Exception:
        await callback.answer("Javobni o‘qib bo‘lmadi.", show_alert=True); return
    async with SessionLocal() as session:
        quiz = await session.get(Quiz, quiz_id)
        if not quiz or not quiz.active:
            await callback.answer("Bu quiz endi mavjud emas.", show_alert=True); return
        existing = (await session.execute(select(QuizResult).where(
            QuizResult.quiz_id == quiz_id, QuizResult.user_id == callback.from_user.id
        ))).scalar_one_or_none()
        if existing:
            await callback.answer("Bu savolga allaqachon javob bergansiz.", show_alert=True); return
        options = quiz_options(quiz)
        if not 0 <= selected < len(options):
            await callback.answer("Variant noto‘g‘ri.", show_alert=True); return
        correct = selected == quiz.correct_index
        session.add(QuizResult(quiz_id=quiz_id, user_id=callback.from_user.id,
            selected_index=selected, is_correct=correct))
        await session.commit()
    await callback.answer("To‘g‘ri! 🎉" if correct else "Noto‘g‘ri.", show_alert=True)

@dp.message(F.text == "📊 Natijalar")
async def results(message: Message):
    if not message.from_user: return
    async with SessionLocal() as session:
        from sqlalchemy import func
        total = await session.scalar(select(func.count()).select_from(QuizResult).where(QuizResult.user_id == message.from_user.id)) or 0
        correct = await session.scalar(select(func.count()).select_from(QuizResult).where(QuizResult.user_id == message.from_user.id, QuizResult.is_correct.is_(True))) or 0
    await message.answer(f"📊 Javoblar: {total}\n✅ To‘g‘ri: {correct}\n❌ Noto‘g‘ri: {total-correct}")

async def scheduler_tick():
    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        users = (await session.execute(select(UserSettings).where(UserSettings.enabled.is_(True), UserSettings.next_quiz_at <= now))).scalars().all()
        chats = (await session.execute(select(ChatSettings).where(ChatSettings.enabled.is_(True), ChatSettings.next_quiz_at <= now))).scalars().all()
        user_jobs = [(u.user_id, u.interval_minutes, u.category_ids, u.quiz_style) for u in users]
        chat_jobs = [(c.chat_id, c.interval_minutes, c.category_ids, c.quiz_style) for c in chats]
        for u in users:
            u.next_quiz_at = next_time(u.interval_minutes)
        for c in chats:
            c.next_quiz_at = next_time(c.interval_minutes)
        await session.commit()
        for user_id, interval, category_string, style in user_jobs:
            quiz = await get_random_quiz(session, parse_ids(category_string) or None)
            if quiz:
                try:
                    await send_quiz(bot, user_id, quiz, style, user_id)
                except Exception as exc:
                    logging.warning("Private quiz send failed for %s: %s", user_id, exc)
        for chat_id, interval, category_string, style in chat_jobs:
            quiz = await get_random_quiz(session, parse_ids(category_string) or None)
            if quiz:
                try:
                    await send_quiz(bot, chat_id, quiz, style)
                except Exception as exc:
                    logging.warning("Chat quiz send failed for %s: %s", chat_id, exc)

async def main():
    await init_db()
    scheduler.add_job(scheduler_tick, "interval", seconds=15, id="quiz_scheduler", max_instances=1, coalesce=True)
    scheduler.start()
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
