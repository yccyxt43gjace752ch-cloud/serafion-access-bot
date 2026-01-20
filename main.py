
import os
import logging
import sqlite3
from datetime import datetime
from typing import Optional, Set, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# =========================
# LOGGING
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("serafion-access-bot")

# =========================
# CONFIG (ENV)
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# CHANNEL_ID: должен быть int, обычно -100xxxxxxxxxx
CHANNEL_ID_RAW = os.getenv("CHANNEL_ID", "").strip()
INVITE_LINK = os.getenv("INVITE_LINK", "").strip()

ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "").strip()  # пример: "123,456"
ADMIN_IDS: Set[int] = set()
if ADMIN_IDS_RAW:
    for part in ADMIN_IDS_RAW.split(","):
        part = part.strip()
        if part.isdigit():
            ADMIN_IDS.add(int(part))

# DB file in container FS
DB_PATH = os.getenv("DB_PATH", "db.sqlite3").strip()


def _parse_channel_id(raw: str) -> Optional[int]:
    if not raw:
        return None
    raw = raw.strip()
    # allow "-100..." or numeric
    try:
        return int(raw)
    except ValueError:
        return None


CHANNEL_ID = _parse_channel_id(CHANNEL_ID_RAW)

# =========================
# DB
# =========================
def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def db_init() -> None:
    conn = db_connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                event TEXT NOT NULL,
                meta TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                username TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def db_touch_user(user_id: int, username: Optional[str]) -> None:
    now = datetime.utcnow().isoformat()
    conn = db_connect()
    try:
        cur = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if row:
            conn.execute(
                "UPDATE users SET last_seen = ?, username = ? WHERE user_id = ?",
                (now, username, user_id),
            )
        else:
            conn.execute(
                "INSERT INTO users(user_id, first_seen, last_seen, username) VALUES(?,?,?,?)",
                (user_id, now, now, username),
            )
        conn.commit()
    finally:
        conn.close()


def db_log_event(user_id: int, username: Optional[str], event: str, meta: str = "") -> None:
    ts = datetime.utcnow().isoformat()
    conn = db_connect()
    try:
        conn.execute(
            "INSERT INTO events(ts, user_id, username, event, meta) VALUES(?,?,?,?,?)",
            (ts, user_id, username, event, meta),
        )
        conn.commit()
    finally:
        conn.close()


def db_stats() -> Tuple[int, int]:
    """returns (users_total, events_total)"""
    conn = db_connect()
    try:
        users_total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        events_total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        return users_total, events_total
    finally:
        conn.close()


# =========================
# HELPERS
# =========================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def build_subscribe_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    if CHANNEL_ID is not None:
        # Если хочешь кнопку "Открыть канал" — можно поставить публичный @username ссылкой через ENV,
        # но у нас её нет. Поэтому оставим только "Проверить подписку".
        pass
    buttons.append([InlineKeyboardButton("✅ Я подписался — проверить", callback_data="check_sub")])
    return InlineKeyboardMarkup(buttons)


def build_access_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    if INVITE_LINK:
        buttons.append([InlineKeyboardButton("🔗 Войти / Получить доступ", url=INVITE_LINK)])
    buttons.append([InlineKeyboardButton("🔁 Проверить ещё раз", callback_data="check_sub")])
    return InlineKeyboardMarkup(buttons)


async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Tuple[bool, str]:
    """
    Returns (ok, reason).
    ok=True если подписан (member/administrator/creator).
    """
    if CHANNEL_ID is None:
        return False, "CHANNEL_ID не задан в ENV"

    user = update.effective_user
    if not user:
        return False, "user is None"

    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user.id)
        status = getattr(member, "status", None)

        # statuses: "creator", "administrator", "member", "restricted", "left", "kicked"
        if status in ("creator", "administrator", "member"):
            return True, status
        return False, status or "unknown"
    except Forbidden:
        # Бот не админ/нет прав или канал недоступен боту
        return False, "Forbidden: бот не видит канал (добавь бота в канал админом)"
    except BadRequest as e:
        # user not found / chat not found etc.
        return False, f"BadRequest: {e.message if hasattr(e, 'message') else str(e)}"
    except Exception as e:
        logger.exception("check_subscription error: %s", e)
        return False, f"Exception: {type(e).__name__}"


# =========================
# HANDLERS
# =========================
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    user = update.effective_user
    if user:
        db_touch_user(user.id, user.username)
        db_log_event(user.id, user.username, "stats")

    users_total, events_total = db_stats()
    await update.message.reply_text(
        f"📊 Stats:\nUsers: {users_total}\nEvents: {events_total}"
    )


async def health_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text("OK")


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.message:
        return

    if not is_admin(user.id):
        return

if not update.message:
        return

    if ADMIN_IDS and (user is None or not is_admin(user.id)):
        await update.message.reply_text("⛔️ Нет доступа.")
        return

    users_total, events_total = db_stats()
    await update.message.reply_text(
        f"📊 Stats:\nUsers: {users_total}\nEvents: {events_total}"
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    await query.answer()

    if query.data == "check_sub":
        ok, reason = await check_subscription(update, context)
        if ok:
            await query.message.reply_text(
                "✅ <b>Подписка найдена</b>. Держи доступ:",
                parse_mode=ParseMode.HTML,
                reply_markup=build_access_keyboard(),
                disable_web_page_preview=True,
            )
        else:
            await query.message.reply_text(
                "❌ <b>Подписка не найдена</b>\n\n"
                "Подпишись и нажми проверку ещё раз.\n"
                f"<code>{reason}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=build_subscribe_keyboard(),
            )


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN пустой (Railway Variables).")

    db_init()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("health", health_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))

    app.run_polling(close_loop=False)


if name == "__main__":
    main()
