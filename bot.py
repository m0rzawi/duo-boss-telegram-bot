
import asyncio
import logging
import os
import secrets
import string

import aiosqlite
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

TOKEN = os.getenv("BOT_TOKEN")
DB = "duo.db"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
dp = Dispatcher()

MENU = """
💜 DUO — ваше общее пространство

👤 Профиль: /profile
✏️ Изменить имя: /name Имя

💞 Создать пару: /create_pair
🔗 Присоединиться: /join КОД

📅 Добавить план: /plan Текст
💡 Добавить идею: /idea Текст
📸 Сохранить воспоминание: /memory Текст
📝 Общий список: /list
✅ Выполнить задачу: /done ID

🔒 Личная заметка: /note Текст
📖 Мои заметки: /notes

❓ Помощь: /help
"""


async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                name TEXT DEFAULT 'Участник'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS couples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE,
                user1 INTEGER,
                user2 INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                couple_id INTEGER,
                user_id INTEGER,
                category TEXT,
                content TEXT,
                done INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                content TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


async def register(user_id):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users(user_id) VALUES(?)",
            (user_id,)
        )
        await db.commit()


async def get_name(user_id):
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT name FROM users WHERE user_id=?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else "Участник"


async def get_couple(user_id):
    async with aiosqlite.connect(DB) as db:
        async with db.execute("""
            SELECT id, user1, user2, code
            FROM couples
            WHERE user1=? OR user2=?
        """, (user_id, user_id)) as cursor:
            return await cursor.fetchone()


async def partner_id(user_id):
    couple = await get_couple(user_id)
    if not couple or not couple[2]:
        return None
    return couple[2] if couple[1] == user_id else couple[1]


async def notify_partner(user_id, text):
    partner = await partner_id(user_id)
    if partner:
        try:
            await bot.send_message(partner, text)
        except Exception:
            logging.exception("Не удалось отправить уведомление")


async def add_entry(user_id, category, content):
    couple = await get_couple(user_id)

    if not couple or not couple[2]:
        return False

    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            INSERT INTO entries(couple_id, user_id, category, content)
            VALUES(?, ?, ?, ?)
        """, (couple[0], user_id, category, content))
        await db.commit()

    name = await get_name(user_id)
    await notify_partner(
        user_id,
        f"💜 {name} добавил(а) в раздел «{category}»:\n{content}"
    )
    return True


@dp.message(Command("start"))
async def start(message: Message):
    await register(message.from_user.id)
    await message.answer(
        "💜 Добро пожаловать в DUO!\n\n"
        "Ваше маленькое общее пространство начинается здесь.\n\n"
        + MENU
    )


@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(MENU)


@dp.message(Command("name"))
async def set_name(message: Message):
    await register(message.from_user.id)
    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        await message.answer("Напиши имя после команды: /name Андрей")
        return

    name = parts[1][:40]

    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE users SET name=? WHERE user_id=?",
            (name, message.from_user.id)
        )
        await db.commit()

    await message.answer(f"💜 Теперь твоё имя в DUO: {name}")


@dp.message(Command("profile"))
async def profile(message: Message):
    await register(message.from_user.id)
    name = await get_name(message.from_user.id)
    couple = await get_couple(message.from_user.id)

    if couple and couple[2]:
        status = "💞 Вы состоите в паре"
        partner = await partner_id(message.from_user.id)
        partner_name = await get_name(partner)
        status += f"\nПартнёр: {partner_name}"
    elif couple:
        status = f"🔗 Ожидается партнёр. Код: {couple[3]}"
    else:
        status = "Пока ты не состоишь в паре."

    await message.answer(
        f"👤 Твой профиль\n\nИмя: {name}\n{status}"
    )


@dp.message(Command("create_pair"))
async def create_pair(message: Message):
    user_id = message.from_user.id
    await register(user_id)

    existing = await get_couple(user_id)
    if existing:
        await message.answer("У тебя уже есть комната DUO.")
        return

    alphabet = string.ascii_uppercase + string.digits
    code = "".join(secrets.choice(alphabet) for _ in range(8))

    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            INSERT INTO couples(code, user1, user2)
            VALUES(?, ?, NULL)
        """, (code, user_id))
        await db.commit()

    await message.answer(
        "💞 Комната создана!\n\n"
        f"Код приглашения: <code>{code}</code>\n\n"
        "Отправь его партнёру. Ему нужно написать:\n"
        f"/join {code}",
        parse_mode="HTML"
    )


@dp.message(Command("join"))
async def join_pair(message: Message):
    user_id = message.from_user.id
    await register(user_id)
    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        await message.answer("Используй: /join КОД")
        return

    code = parts[1].strip().upper()

    if await get_couple(user_id):
        await message.answer("Ты уже состоишь в комнате DUO.")
        return

    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT id, user1, user2 FROM couples WHERE code=?",
            (code,)
        ) as cursor:
            room = await cursor.fetchone()

        if not room:
            await message.answer("Такого кода нет. Проверь его.")
            return

        if room[2] is not None:
            await message.answer("В этой комнате уже есть два участника.")
            return

        if room[1] == user_id:
            await message.answer("Нельзя присоединиться к собственной комнате.")
            return

        await db.execute(
            "UPDATE couples SET user2=? WHERE id=?",
            (user_id, room[0])
        )
        await db.commit()

    await message.answer(
        "💜 Вы успешно объединились!\n"
        "Теперь у вас общее пространство DUO."
    )

    try:
        await bot.send_message(
            room[1],
            "💞 Партнёр присоединился! Ваша комната DUO готова."
        )
    except Exception:
        logging.exception("Ошибка уведомления")


@dp.message(Command("plan"))
async def plan(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Пример: /plan Сходить вместе в кино")
        return

    ok = await add_entry(message.from_user.id, "Планы", parts[1])
    await message.answer(
        "📅 План добавлен!" if ok
        else "Сначала создайте пару: /create_pair"
    )


@dp.message(Command("idea"))
async def idea(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Пример: /idea Устроить вечер настольных игр")
        return

    ok = await add_entry(message.from_user.id, "Идеи", parts[1])
    await message.answer(
        "💡 Идея сохранена!" if ok
        else "Сначала создайте пару: /create_pair"
    )


@dp.message(Command("memory"))
async def memory(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Пример: /memory Наша первая совместная прогулка")
        return

    ok = await add_entry(message.from_user.id, "Воспоминания", parts[1])
    await message.answer(
        "📸 Воспоминание сохранено!" if ok
        else "Сначала создайте пару: /create_pair"
    )


@dp.message(Command("list"))
async def shared_list(message: Message):
    couple = await get_couple(message.from_user.id)

    if not couple or not couple[2]:
        await message.answer("Сначала создайте пару: /create_pair")
        return

    async with aiosqlite.connect(DB) as db:
        async with db.execute("""
            SELECT id, category, content, done
            FROM entries
            WHERE couple_id=?
            ORDER BY id DESC LIMIT 50
        """, (couple[0],)) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await message.answer("Ваше общее пространство пока пустое 💜")
        return

    result = ["💜 ВАШЕ ОБЩЕЕ ПРОСТРАНСТВО\n"]
    for entry_id, category, content, done in rows:
        status = "✅" if done else "🕓"
        result.append(
            f"{status} #{entry_id} · {category}\n{content}"
        )

    await message.answer("\n\n".join(result))


@dp.message(Command("done"))
async def done(message: Message):
    parts = message.text.split(maxsplit=1)

    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Пример: /done 3")
        return

    couple = await get_couple(message.from_user.id)
    if not couple or not couple[2]:
        await message.answer("Сначала создайте пару.")
        return

    entry_id = int(parts[1])

    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute("""
            UPDATE entries SET done=1
            WHERE id=? AND couple_id=?
        """, (entry_id, couple[0]))
        await db.commit()

        if cursor.rowcount == 0:
            await message.answer("Не нашёл такую запись.")
            return

    await message.answer("✅ Готово! Запись отмечена выполненной.")
    name = await get_name(message.from_user.id)
    await notify_partner(
        message.from_user.id,
        f"✅ {name} отметил(а) запись #{entry_id} выполненной!"
    )


@dp.message(Command("note"))
async def note(message: Message):
    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        await message.answer("Пример: /note Купить подарок")
        return

    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO notes(user_id, content) VALUES(?, ?)",
            (message.from_user.id, parts[1])
        )
        await db.commit()

    await message.answer(
        "🔒 Личная заметка сохранена. Её видишь только ты."
    )


@dp.message(Command("notes"))
async def notes(message: Message):
    async with aiosqlite.connect(DB) as db:
        async with db.execute("""
            SELECT id, content FROM notes
            WHERE user_id=?
            ORDER BY id DESC LIMIT 30
        """, (message.from_user.id,)) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await message.answer("У тебя пока нет личных заметок.")
        return

    result = ["🔒 ТВОИ ЛИЧНЫЕ ЗАМЕТКИ\n"]
    for note_id, content in rows:
        result.append(f"#{note_id} · {content}")

    await message.answer("\n\n".join(result))


async def main():
    if not TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN в переменных окружения.")

    await init_db()
    logging.info("DUO запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
