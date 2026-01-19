> ———-:
import os
import sqlite3
import logging
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# =========================
# CONFIG (твои данные)
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1003400683647"))
INVITE_LINK = os.getenv("INVITE_LINK", "https://t.me/+SvkDMFKpF9dlZTJk").strip()

# Админ: твой Telegram user_id (опционально).
# Если укажешь, будут доступны /stats /broadcast /setwelcome
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID", "").strip()

# Тексты (можешь менять без кода, через ENV)
WELCOME_TEXT = os.getenv(
    "WELCOME_TEXT",
    "Welcome to *Serafeon System*.\n\n"
    "First step: join the main channel.\n"
    "Then press *Check access*."
)

GRANTED_TEXT = os.getenv(
    "GRANTED_TEXT",
    "✅ *Access granted.*\n\n"
    "You are inside the system."
)

DENIED_TEXT = os.getenv(
    "DENIED_TEXT",
    "❌ *Access denied.*\n\n"
    "Subscribe to the main channel, then press *Check access*."
)

# =========================
# LOGGING
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("serafeon-bot")

# =========================
# DB (SQLite)
# =========================
DB_PATH = os.getenv("DB_PATH", "bot.db")

def db_conn():
    return sqlite3.connect(DB_PATH)

def db_init():
    with db_conn() as con:
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                started_at TEXT,
                last_seen_at TEXT,
                is_member INTEGER DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT,
                user_id INTEGER,
                event TEXT,
                payload TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        # дефолт welcome
        cur.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('welcome', ?)", (WELCOME_TEXT,))
        con.commit()

def db_upsert_user(u):
    now = datetime.utcnow().isoformat()
    with db_conn() as con:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO users(user_id, username, first_name, last_name, started_at, last_seen_at)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                last_seen_at=excluded.last_seen_at
        """, (u.id, u.username, u.first_name, u.last_name, now, now))
        con.commit()

def db_set_member(user_id: int, is_member: bool):
    with db_conn() as con:
        cur = con.cursor()
        cur.execute("UPDATE users SET is_member=? WHERE user_id=?", (1 if is_member else 0, user_id))
        con.commit()

def db_log_event(user_id: int, event: str, payload: str = ""):
    ts = datetime.utcnow().isoformat()
    with db_conn() as con:
        cur = con.cursor()
        cur.execute("INSERT INTO events(ts, user_id, event, payload) VALUES(?, ?, ?, ?)", (ts, user_id, event, payload))
        con.commit()

def db_get_setting(key: str, default: str = "") -> str:
    with db_conn() as con:
        cur = con.cursor()
        cur.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row else default

def db_set_setting(key: str, value: str):
    with db_conn() as con:

> ———-:
cur = con.cursor()
        cur.execute("""
            INSERT INTO settings(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (key, value))
        con.commit()

# =========================
# HELPERS
# =========================
def is_admin(user_id: int) -> bool:
    if not ADMIN_USER_ID:
        return False
    try:
        return int(ADMIN_USER_ID) == int(user_id)
    except:
        return False

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Check access", callback_data="check_access")],
        [InlineKeyboardButton("📌 Join main channel", url=INVITE_LINK)],
    ])

def granted_keyboard():
    # дальше сюда добавим "VIP / Subscribe" и т.п., когда будешь готов
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Check access again", callback_data="check_access")],
        [InlineKeyboardButton("📌 Main channel", url=INVITE_LINK)],
    ])

async def safe_edit_or_send(update: Update, text: str, reply_markup=None):
    """
    Если это callback — стараемся edit.
    Если edit не получилось — отправляем новым сообщением.
    """
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            return
        except Exception:
            pass
        await update.callback_query.message.reply_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

async def check_membership(bot, user_id: int) -> bool:
    """
    Проверяем статус пользователя в канале.
    True = member/administrator/creator
    False = left/kicked/unknown
    """
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        status = getattr(member, "status", "")
        return status in ("member", "administrator", "creator")
    except Forbidden:
        # бот не админ в канале или нет доступа
        return False
    except BadRequest:
        # пользователь не найден, или неправильный chat_id
        return False
    except Exception:
        return False

# =========================
# HANDLERS
# =========================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db_upsert_user(u)
    db_log_event(u.id, "start", f"@{u.username}")

    welcome = db_get_setting("welcome", WELCOME_TEXT)

    # Показываем welcome + кнопки
    await safe_edit_or_send(update, welcome, reply_markup=main_keyboard())

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "*Commands*\n"
        "/start — start\n"
        "/help — help\n"
    )
    if is_admin(update.effective_user.id):
        text += (
            "\n*Admin*\n"
            "/stats — bot stats\n"
            "/setwelcome <text> — set welcome message\n"
            "/broadcast <text> — send to all users\n"
        )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def check_access_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    u = q.from_user
    db_upsert_user(u)
    db_log_event(u.id, "check_access", "")

    ok = await check_membership(context.bot, u.id)
    db_set_member(u.id, ok)

    if ok:
        await safe_edit_or_send(update, GRANTED_TEXT, reply_markup=granted_keyboard())
    else:
        await safe_edit_or_send(update, f"{DENIED_TEXT}\n\n{INVITE_LINK}", reply_markup=main_keyboard())

# =========================
# ADMIN
# =========================
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    with db_conn() as con:
        cur = con.cursor()
        cur.

> ———-:
execute("SELECT COUNT(*) FROM users")
        users_total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM users WHERE is_member=1")
        members_ok = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM events")
        events_total = cur.fetchone()[0]

    text = (
        f"*Stats*\n"
        f"Users: `{users_total}`\n"
        f"Members OK: `{members_ok}`\n"
        f"Events: `{events_total}`\n"
        f"Channel ID: `{CHANNEL_ID}`\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def setwelcome_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /setwelcome <text>")
        return
    text = " ".join(context.args).strip()
    db_set_setting("welcome", text)
    await update.message.reply_text("✅ Welcome message updated.")

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <text>")
        return

    msg = " ".join(context.args).strip()
    sent = 0
    failed = 0

    with db_conn() as con:
        cur = con.cursor()
        cur.execute("SELECT user_id FROM users")
        rows = cur.fetchall()

    for (uid,) in rows:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=msg,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(f"Broadcast done. Sent={sent}, failed={failed}")

# =========================
# ERROR HANDLER
# =========================
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled error: %s", context.error)

# =========================
# MAIN
# =========================
def build_app() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is empty. Set it in Render → Environment.")

    db_init()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))

    # callbacks
    app.add_handler(CallbackQueryHandler(check_access_cb, pattern="^check_access$"))

    # admin
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("setwelcome", setwelcome_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))

    app.add_error_handler(on_error)
    return app

def main():
    app = build_app()
    # Для Render проще начать с polling.
    # Если захочешь webhook — сделаем отдельным шагом.
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if name == "__main__":
    main()

