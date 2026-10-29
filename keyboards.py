from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

def main_menu(is_admin: bool = False):
    rows = [
        [KeyboardButton(text="🎯 Quiz sozlamalari"), KeyboardButton(text="📊 Natijalar")],
        [KeyboardButton(text="ℹ️ Yordam")]
    ]
    if is_admin:
        rows.append([KeyboardButton(text="🛠 Admin panel")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def admin_menu(is_superadmin: bool):
    b = InlineKeyboardBuilder()
    b.button(text="➕ Kategoriya yaratish", callback_data="admin:category_add")
    b.button(text="➕ Quiz qo‘shish", callback_data="admin:quiz_add")
    b.button(text="📚 Kategoriyalar", callback_data="admin:categories")
    b.button(text="📝 Quizlar", callback_data="admin:quizzes")
    if is_superadmin:
        b.button(text="👮 Admin qo‘shish", callback_data="admin:add_admin")
        b.button(text="🚫 Adminni olib tashlash", callback_data="admin:remove_admin")
    b.adjust(2, 2, 1, 1)
    return b.as_markup()

def categories_keyboard(categories, prefix="cat"):
    b = InlineKeyboardBuilder()
    for category in categories:
        b.button(text=category.name, callback_data=f"{prefix}:{category.id}")
    b.adjust(2)
    return b.as_markup()

def style_keyboard(prefix: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Inline tugmalar", callback_data=f"{prefix}:inline")],
        [InlineKeyboardButton(text="Telegram Quiz Poll", callback_data=f"{prefix}:poll")]
    ])

def options_keyboard(quiz_id: int, options: list[str]):
    b = InlineKeyboardBuilder()
    for i, option in enumerate(options):
        b.button(text=option[:60], callback_data=f"answer:{quiz_id}:{i}")
    b.adjust(1)
    return b.as_markup()
