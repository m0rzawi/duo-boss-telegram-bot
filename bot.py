
import asyncio
import logging
import os
import secrets
import sqlite3

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

TOKEN = os.getenv("BOT_TOKEN")
DB = "duo.db"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Ожидание следующего сообщения от пользователя
pending = {}

CATEGORIES = {
    "meet": "📅 Встречи",
    "idea": "💭 Идеи",
    "memory": "📸 Воспоминания",
    "goal": "🎯 Наши цели",
    "letter": "💌 Послания",
}


def connect():
    return sqlite3.connect(DB)


def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT DEFAULT 'Участник'
        );

        CREATE TABLE IF NOT EXISTS couples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            user1 INTEGER,
            user2 INTEGER
        );

        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            couple_id INTEGER,
            user_id INTEGER,
            category TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)


def register(user_id):
    with connect() as db:
        db.execute(
            "INSERT OR IGNORE INTO users(user_id) VALUES(?)",
            (user_id,)
        )


def get_name(user_id):
    with connect() as db:
        row = db.execute(
            "SELECT name FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()
    return row[0] if row else "Участник"


def get_pair(user_id):
    with connect() as db:
        return db.execute("""
            SELECT id, user1, user2, code FROM couples
            WHERE user1=? OR user2=?
        """, (user_id, user_id)).fetchone()


def get_partner(user_id):
    pair = get_pair(user_id)
    if not pair or not pair[2]:
        return None
    return pair[2] if pair[1] == user_id else pair[1]


def main_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="💞 Наше пространство", callback_data="home")
    kb.button(text="📅 Встречи", callback_data="view:meet")
    kb.button(text="💭 Идеи", callback_data="view:idea")
    kb.button(text="📸 Воспоминания", callback_data="view:memory")
    kb.button(text="🎯 Наши цели", callback_data="view:goal")
    kb.button(text="💌 Послания", callback_data="view:letter")
    kb.button(text="🔒 Личное", callback_data="private")
    kb.button(text="👤 Мой профиль", callback_data="profile")
    kb.adjust(1, 2, 2, 2, 1)
    return kb.as_markup()


def add_keyboard(category):
    kb = InlineKeyboardBuilder()
    kb.button(
        text="➕ Добавить",
        callback_data=f"add:{category}"
    )
    kb.button(text="🏠 На главную", callback_data="home")
    kb.adjust(1)
    return kb.as_markup()


async def notify_partner(user_id, text):
    partner = get_partner(user_id)
    if partner:
        try:
            await bot.send_message(partner, text)
        except Exception:
            logging.exception("Notification failed")


async def show_home(target, user_id):
    pair = get_pair(user_id)

    if not pair or not pair[2]:
        text = (
            "💜 **DUO — ваш мир на двоих**\n\n"
            "Здесь будет ваша общая история: встречи, идеи, "
            "воспоминания и маленькие планы.\n\n"
            "Чтобы начать, создайте комнату или присоединитесь "
            "к комнате партнёра."
        )
        kb = InlineKeyboardBuilder()
        kb.button(text="💞 Создать нашу комнату", callback_data="create")
        kb.button(text="🔗 У меня есть код", callback_data="join")
        kb.adjust(1)
        await target.answer(text, reply_markup=kb.as_markup(),
                            parse_mode="Markdown")
        return

    partner = get_partner(user_id)
    partner_name = get_name(partner)

    with connect() as db:
        count = db.execute(
            "SELECT COUNT(*) FROM entries WHERE couple_id=?",
            (pair[0],)
        ).fetchone()[0]

        recent = db.execute("""
            SELECT category, content FROM entries
            WHERE couple_id=? ORDER BY id DESC LIMIT 3
        """, (pair[0],)).fetchall()

    text = (
        "💜 **DUO — ваше пространство**\n\n"
        f"💞 Вы вместе с: **{partner_name}**\n"
        f"📚 Записей в вашей истории: **{count}**\n\n"
        "✨ **Последние события:**\n"
    )

    if recent:
        for category, content in recent:
            text += f"\n• {CATEGORIES.get(category, category)}: {content[:90]}"
    else:
        text += "\nПока здесь тихо. Создайте первое воспоминание!"

    await target.answer(
        text,
        reply_markup=main_keyboard(),
        parse_mode="Markdown"
    )


@dp.message(CommandStart())
async def start(message: Message):
    register(message.from_user.id)
    await show_home(message, message.from_user.id)


@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "Все функции DUO находятся в меню. "
        "Нажми /start, чтобы открыть пространство."
    )


@dp.callback_query(F.data == "home")
async def home(callback: CallbackQuery):
    await callback.answer()
    await show_home(callback.message, callback.from_user.id)


@dp.callback_query(F.data == "create")
async def create_room(callback: CallbackQuery):
    user_id = callback.from_user.id
    register(user_id)

    if get_pair(user_id):
        await callback.answer("У тебя уже есть комната!", show_alert=True)
        return

    code = secrets.token_hex(4).upper()

    with connect() as db:
        db.execute(
            "INSERT INTO couples(code, user1) VALUES(?, ?)",
            (code, user_id)
        )

    await callback.message.answer(
        "💞 **Комната создана!**\n\n"
        f"Твой код приглашения: `{code}`\n\n"
        "Отправь его партнёру. Ему нужно открыть DUO "
        "и нажать «У меня есть код».",
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.callback_query(F.data == "join")
async def ask_code(callback: CallbackQuery):
    pending[callback.from_user.id] = {"action": "join"}
    await callback.message.answer("🔗 Отправь код приглашения:")
    await callback.answer()


@dp.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    name = get_name(user_id)
    pair = get_pair(user_id)

    text = f"👤 **Твой профиль**\n\nИмя: {name}\n"

    if pair and pair[2]:
        text += "Статус: 💞 В паре"
    elif pair:
        text += f"Статус: Ожидаем партнёра\nКод: `{pair[3]}`"
    else:
        text += "Статус: Пока без пары"

    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Изменить имя", callback_data="rename")
    kb.button(text="🏠 На главную", callback_data="home")
    kb.adjust(1)

    await callback.message.answer(
        text, reply_markup=kb.as_markup(), parse_mode="Markdown"
    )
    await callback.answer()


@dp.callback_query(F.data == "rename")
async def rename(callback: CallbackQuery):
    pending[callback.from_user.id] = {"action": "rename"}
    await callback.message.answer("✏️ Как тебя называть?")
    await callback.answer()


@dp.callback_query(F.data.startswith("view:"))
async def view_category(callback: CallbackQuery):
    category = callback.data.split(":")[1]
    pair = get_pair(callback.from_user.id)

    if not pair or not pair[2]:
        await callback.answer("Сначала создайте комнату DUO", show_alert=True)
        return

    with connect() as db:
        rows = db.execute("""
            SELECT id, content FROM entries
            WHERE couple_id=? AND category=?
            ORDER BY id DESC LIMIT 30
        """, (pair[0], category)).fetchall()

    title = CATEGORIES[category]
    text = f"**{title}**\n\n"

    if rows:
        for entry_id, content in rows:
            text += f"#{entry_id} · {content}\n\n"
    else:
        text += "Пока здесь пусто. Добавьте первую запись!"

    await callback.message.answer(
        text,
        reply_markup=add_keyboard(category),
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("add:"))
async def add_entry(callback: CallbackQuery):
    category = callback.data.split(":")[1]
    pending[callback.from_user.id] = {
        "action": "add",
        "category": category
    }

    prompts = {
        "meet": "📅 Что планируем вместе?",
        "idea": "💭 Какую идею хотите сохранить?",
        "memory": "📸 Какое воспоминание добавим?",
        "goal": "🎯 Какую цель хотите достичь вместе?",
        "letter": "💌 Напиши послание партнёру:"
    }

    await callback.message.answer(prompts[category])
    await callback.answer()


@dp.callback_query(F.data == "private")
async def private_menu(callback: CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Новая заметка", callback_data="note_add")
    kb.button(text="📖 Мои заметки", callback_data="note_view")
    kb.button(text="🏠 На главную", callback_data="home")
    kb.adjust(1)

    await callback.message.answer(
        "🔒 **Личное пространство**\n\n"
        "Твои заметки доступны только тебе.",
        reply_markup=kb.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.callback_query(F.data == "note_add")
async def note_add(callback: CallbackQuery):
    pending[callback.from_user.id] = {"action": "note"}
    await callback.message.answer("🔒 Напиши личную заметку:")
    await callback.answer()


@dp.callback_query(F.data == "note_view")
async def note_view(callback: CallbackQuery):
    with connect() as db:
        rows = db.execute("""
            SELECT id, content FROM notes
            WHERE user_id=? ORDER BY id DESC LIMIT 30
        """, (callback.from_user.id,)).fetchall()

    text = "🔒 **Твои личные заметки**\n\n"
    text += "\n".join(
        f"#{note_id} · {content}" for note_id, content in rows
    ) if rows else "Заметок пока нет."

    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()


@dp.message()
async def handle_text(message: Message):
    user_id = message.from_user.id
    state = pending.get(user_id)

    if not state or not message.text:
        return

    action = state["action"]
    content = message.text.strip()

    if not content:
        return

    if action == "join":
        code = content.upper()

        if get_pair(user_id):
            await message.answer("У тебя уже есть комната DUO.")
            pending.pop(user_id, None)
            return

        with connect() as db:
            room = db.execute(
                "SELECT id, user1 FROM couples WHERE code=? AND user2 IS NULL",
                (code,)
            ).fetchone()

            if not room:
                await message.answer("Код не найден или комната уже занята.")
                return

            if room[1] == user_id:
                await message.answer("Это твоя собственная комната.")
                return

            db.execute(
                "UPDATE couples SET user2=? WHERE id=?",
                (user_id, room[0])
            )

        pending.pop(user_id, None)
        await message.answer("💞 Вы теперь вместе в DUO!")
        try:
            await bot.send_message(
                room[1], "💜 Партнёр присоединился! Ваша комната готова."
            )
        except Exception:
            logging.exception("Pair notification failed")

        await show_home(message, user_id)
        return

    if action == "rename":
        with connect() as db:
            db.execute(
                "UPDATE users SET name=? WHERE user_id=?",
                (content[:40], user_id)
            )
        pending.pop(user_id, None)
        await message.answer(f"💜 Теперь твоё имя: {content[:40]}")
        return

    if action == "note":
        with connect() as db:
            db.execute(
                "INSERT INTO notes(user_id, content) VALUES(?, ?)",
                (user_id, content[:2000])
            )
        pending.pop(user_id, None)
        await message.answer("🔒 Заметка сохранена. Только для тебя.")
        return

    if action == "add":
        pair = get_pair(user_id)

        if not pair or not pair[2]:
            await message.answer("Сначала создайте пару DUO.")
            pending.pop(user_id, None)
            return

        category = state["category"]

        with connect() as db:
            db.execute("""
                INSERT INTO entries(couple_id, user_id, category, content)
                VALUES(?, ?, ?, ?)
            """, (pair[0], user_id, category, content[:2000]))

        pending.pop(user_id, None)

        await message.answer("💜 Сохранено в вашем общем пространстве!")

        label = CATEGORIES[category]
        if category == "letter":
            notification = (
                f"💌 Тебе послание от {get_name(user_id)}:\n\n{content}"
            )
        else:
            notification = (
                f"💜 {get_name(user_id)} добавил(а) в DUO:\n"
                f"{label}\n\n{content}"
            )

        await notify_partner(user_id, notification)


async def main():
    if not TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN")

    init_db()
    logging.info("DUO запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
