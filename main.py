import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery, FSInputFile,
    InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramForbiddenError

BOT_TOKEN = os.getenv("BOT_TOKEN")  # токен берем из Secrets (Replit) или переменных окружения
OWNER_ID = 7322925570  # твой Telegram ID

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()

DB_FILE = "moderation.db"
LOG_FILE = "violations.log"

# ================== DB INIT ==================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS forbidden_words(word TEXT UNIQUE)")
    cur.execute("CREATE TABLE IF NOT EXISTS admins(user_id INTEGER UNIQUE)")
    cur.execute("CREATE TABLE IF NOT EXISTS allowed_links(link TEXT UNIQUE)")
    cur.execute("""CREATE TABLE IF NOT EXISTS settings(
        key TEXT UNIQUE,
        value TEXT
    )""")
    cur.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('mute_time', '600')")
    cur.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('link_punish', 'ban')")
    cur.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('anti_links', 'on')")
    conn.commit()
    conn.close()

init_db()

# ================== HELPERS ==================
def db_get(query, args=(), one=False):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(query, args)
    rows = cur.fetchall()
    conn.close()
    return (rows[0] if rows else None) if one else rows

def db_exec(query, args=()):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(query, args)
    conn.commit()
    conn.close()

def log_violation(user: types.User, chat: types.Chat, thread_id, action, reason):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                f"USER: {user.username or '-'} (id={user.id}) | "
                f"CHAT: {chat.title} (id={chat.id}) | "
                f"TOPIC: {thread_id} | ACTION: {action} | REASON: {reason}\n")

def is_admin(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    row = db_get("SELECT 1 FROM admins WHERE user_id=?", (user_id,), one=True)
    return bool(row)

def get_setting(key: str, default=None):
    row = db_get("SELECT value FROM settings WHERE key=?", (key,), one=True)
    return row[0] if row else default

def set_setting(key: str, value: str):
    db_exec("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, value))

# ================== KEYBOARDS ==================
def admin_menu():
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🚫 Запрещённые слова", callback_data="words"),
        InlineKeyboardButton(text="🌐 Разрешённые ссылки", callback_data="links")
    )
    kb.row(
        InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings")
    )
    kb.row(
        InlineKeyboardButton(text="📂 Скачать лог", callback_data="download_log"),
        InlineKeyboardButton(text="🗑 Очистить лог", callback_data="clear_log")
    )
    kb.row(
        InlineKeyboardButton(text="👑 Админы", callback_data="admins")
    )
    return kb.as_markup()

def settings_menu():
    mute_time = int(get_setting("mute_time", "600"))
    punish = get_setting("link_punish", "ban")
    anti_links = get_setting("anti_links", "on")

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=f"⏱ Время мута: {mute_time//60} мин", callback_data="set_mute"))
    kb.row(InlineKeyboardButton(text=f"⚖️ Наказание за ссылки: {punish.upper()}", callback_data="set_punish"))
    kb.row(InlineKeyboardButton(text=f"🌐 Анти-ссылки: {anti_links.upper()}", callback_data="toggle_links"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_admin"))
    return kb.as_markup()

def mute_time_menu():
    kb = InlineKeyboardBuilder()
    for minutes in [5, 10, 30, 60]:
        kb.row(InlineKeyboardButton(text=f"{minutes} мин", callback_data=f"mute_{minutes}"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="settings"))
    return kb.as_markup()

def punish_menu():
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="Мут", callback_data="punish_mute"))
    kb.row(InlineKeyboardButton(text="Бан", callback_data="punish_ban"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="settings"))
    return kb.as_markup()

# ================== HANDLERS ==================
@dp.message(CommandStart())
async def start_cmd(message: Message):
    if message.chat.type == ChatType.PRIVATE:
        if is_admin(message.from_user.id):
            await message.answer("Привет! Это админ-панель. Введи /admin для управления.")
        else:
            return
    else:
        return

@dp.message(Command("admin"))
async def admin_cmd(message: Message):
    if message.chat.type != ChatType.PRIVATE:
        return
    if not is_admin(message.from_user.id):
        return
    await message.answer("Админ-панель:", reply_markup=admin_menu())

@dp.message(Command("dante"))
async def help_cmd(message: Message):
    text = (
        "📜 <b>Команды бота</b>\n\n"
        "/admin — открыть админ-панель (только в ЛС, для админов)\n"
        "/dante — список команд\n\n"
        "🔒 Функции:\n"
        "- Мут за запрещённые слова\n"
        "- Бан/мут за запрещённые ссылки\n"
        "- Белый список ссылок\n"
        "- Логи нарушений (скачать/очистить)\n"
        "- Настройки наказаний"
    )
    await message.answer(text)

# ================== CALLBACKS ==================
@dp.callback_query(F.data == "back_admin")
async def cb_back(call: CallbackQuery):
    await call.message.edit_text("Админ-панель:", reply_markup=admin_menu())

@dp.callback_query(F.data == "settings")
async def cb_settings(call: CallbackQuery):
    await call.message.edit_text("⚙️ Настройки:", reply_markup=settings_menu())

@dp.callback_query(F.data == "set_mute")
async def cb_set_mute(call: CallbackQuery):
    await call.message.edit_text("Выбери время мута:", reply_markup=mute_time_menu())

@dp.callback_query(F.data.startswith("mute_"))
async def cb_mute_time(call: CallbackQuery):
    minutes = int(call.data.split("_")[1])
    set_setting("mute_time", str(minutes * 60))
    await call.answer(f"Время мута изменено на {minutes} мин")
    await cb_settings(call)

@dp.callback_query(F.data == "set_punish")
async def cb_set_punish(call: CallbackQuery):
    await call.message.edit_text("Выбери наказание за ссылки:", reply_markup=punish_menu())

@dp.callback_query(F.data.startswith("punish_"))
async def cb_punish(call: CallbackQuery):
    punish = call.data.split("_")[1]
    set_setting("link_punish", punish)
    await call.answer(f"Теперь за ссылки: {punish.upper()}")
    await cb_settings(call)

@dp.callback_query(F.data == "toggle_links")
async def cb_toggle_links(call: CallbackQuery):
    current = get_setting("anti_links", "on")
    new = "off" if current == "on" else "on"
    set_setting("anti_links", new)
    await call.answer(f"Анти-ссылки: {new.upper()}")
    await cb_settings(call)

@dp.callback_query(F.data == "download_log")
async def cb_download_log(call: CallbackQuery):
    if os.path.exists(LOG_FILE):
        await call.message.answer_document(FSInputFile(LOG_FILE))
    else:
        await call.answer("Лог пуст", show_alert=True)

@dp.callback_query(F.data == "clear_log")
async def cb_clear_log(call: CallbackQuery):
    open(LOG_FILE, "w").close()
    await call.answer("✅ Логи очищены", show_alert=True)

# ================== MODERATION ==================
@dp.message(F.chat.type.in_({"supergroup"}))
async def check_messages(message: Message):
    if not message.message_thread_id:  # только в темах
        return

    text = message.text or message.caption or ""
    user = message.from_user

    # Проверка слов
    words = [row[0].lower() for row in db_get("SELECT word FROM forbidden_words")]
    for w in words:
        if w in text.lower().split():  # точное совпадение
            mute_time = int(get_setting("mute_time", "600"))
            until_date = datetime.now() + timedelta(seconds=mute_time)
            try:
                await message.chat.restrict(user.id, until_date=until_date,
                                            permissions=types.ChatPermissions(can_send_messages=False))
                await message.delete()
            except TelegramForbiddenError:
                pass
            await message.reply(f'Пользователь <b>{user.username or "без ника"}</b> (id={user.id}) '
                                f'написал запрещённое слово и получил мут.\n'
                                f'Пожалуйста, соблюдайте правила чата.')
            log_violation(user, message.chat, message.message_thread_id,
                          f"MUTE {mute_time//60} min", "Запрещённое слово")
            return

    # Проверка ссылок
    if "http://" in text or "https://" in text:
        if get_setting("anti_links", "on") == "off":
            return
        allowed = [row[0] for row in db_get("SELECT link FROM allowed_links")]
        if text.strip() in allowed:  # точное совпадение
            return
        punish = get_setting("link_punish", "ban")
        try:
            if punish == "ban":
                await message.chat.ban(user.id)
                action = "BAN"
            else:
                mute_time = int(get_setting("mute_time", "600"))
                until_date = datetime.now() + timedelta(seconds=mute_time)
                await message.chat.restrict(user.id, until_date=until_date,
                                            permissions=types.ChatPermissions(can_send_messages=False))
                action = f"MUTE {mute_time//60} min"
            await message.delete()
        except TelegramForbiddenError:
            return
        await message.reply(f'Пользователь <b>{user.username or "без ника"}</b> (id={user.id}) '
                            f'отправил запрещённую ссылку и получил {action}.\n'
                            f'Пожалуйста, соблюдайте правила чата.')
        log_violation(user, message.chat, message.message_thread_id, action, "Запрещённая ссылка")

# ================== MAIN ==================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
