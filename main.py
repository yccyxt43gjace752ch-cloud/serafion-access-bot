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
# callback data
CB_CHECK = "check_access"


def kb_start():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_SUBSCRIBE, url=INVITE_LINK)],
            [InlineKeyboardButton(BTN_CHECK, callback_data=CB_CHECK)],
        ]
    )


def kb_granted():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_OPEN, url=INVITE_LINK)],
        ]
    )


# =========================
# HELPERS
# =========================
async def safe_edit_or_send(
    update: Update,
    text: str,
    reply_markup=None,
    parse_mode=ParseMode.MARKDOWN,
):
    """
    Если пришёл callback — редактируем сообщение.
    Если пришло /start — отвечаем новым сообщением.
    """
    try:
        if update.callback_query and update.callback_query.message:
            await update.callback_query.edit_message_text(
                text=text, reply_markup=reply_markup, parse_mode=parse_mode
            )
        else:
            await update.message.reply_text(
                text=text, reply_markup=reply_markup, parse_mode=parse_mode
            )
    except BadRequest as e:
        # Иногда Telegram ругается: "Message is not modified" — игнорим
        if "Message is not modified" in str(e):
            return
        log.warning("BadRequest in safe_edit_or_send: %s", e)


async def check_membership(bot, user_id: int) -> bool:
    """
    Проверка подписки на основной канал.
    Требования:
    - бот добавлен админом в канал
    - у бота есть права "Просматривать участников" (или аналогичные)
    """
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        status = getattr(member, "status", None)
        # member.status: 'creator'/'administrator'/'member'/'restricted'/'left'/'kicked'
        return status in ("creator", "administrator", "member")
    except Forbidden:
        # обычно значит: бот не админ в канале / нет прав
        log.error("Forbidden: bot has no access to get_chat_member. Add bot as admin.")
        return False
    except BadRequest as e:
        # user not found / chat not found / etc.
        log.warning("BadRequest in check_membership: %s", e)
        return False
    except Exception as e:
        log.exception("Unexpected error in check_membership: %s", e)
        return False


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS if ADMIN_IDS else False


# =========================
# HANDLERS
# =========================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db_upsert_user(u)
    db_log_event(u.id, "start", u.username or "")
    await safe_edit_or_send(update, WELCOME_TEXT, reply_markup=kb_start())


async def check_access_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    u = update.effective_user
    db_upsert_user(u)
    db_log_event(u.id, "check_access", "")

    ok = await check_membership(context.bot, u.id)

    if ok:
        await safe_edit_or_send(update, GRANTED_TEXT, reply_markup=kb_granted())
        db_log_event(u.id, "granted", "")
    else:
        await safe_edit_or_send(update, f"{DENIED_TEXT}\n\n{INVITE_LINK}", reply_markup=kb_start())
        db_log_event(u.id, "denied", "")


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not is_admin(u.id):
        return

    users, events, top = db_stats()
    lines = [
        "📊 *Stats*",
        f"Users: *{users}*",
        f"Events: *{events}*",
        "",
        "*Top events:*",
    ]
    for ev, c in top:
        lines.append(f"- {ev}: *{c}*")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def health_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("OK")


# =========================
# MAIN
# =========================
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is empty. Set it in environment variables.")

    db_init()

    app = Application.

> ———-:
import os
import logging
import sqlite3
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
# CONFIG (ENV)
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# твои значения (можно оставить тут, но ЛУЧШЕ держать в ENV)
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1003400683647"))  # основной канал (куда надо подписаться)
INVITE_LINK = os.getenv("INVITE_LINK", "https://t.me/+SvkDMFKpF9dlZTJk").strip()

# Админы (для /stats). Пример: "123,456"
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS = set()
if ADMIN_IDS_RAW:
    for x in ADMIN_IDS_RAW.split(","):
        x = x.strip()
        if x.isdigit():
            ADMIN_IDS.add(int(x))

# Webhook (если захочешь, но можно и без него)
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()  # типа: https://YOUR-SERVICE.onrender.com
PORT = int(os.getenv("PORT", "10000"))

# SQLite (логирование)
DB_PATH = os.getenv("DB_PATH", "bot.db").strip()

# =========================
# LOGGING
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("serafeon-access-bot")


# =========================
# DB
# =========================
def db_init():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            first_seen TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            user_id INTEGER,
            event TEXT,
            extra TEXT
        )
        """
    )
    con.commit()
    con.close()


def db_upsert_user(u):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO users (user_id, username, first_name, last_name, first_seen)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name,
            last_name=excluded.last_name
        """,
        (
            u.id,
            u.username or "",
            u.first_name or "",
            u.last_name or "",
            datetime.utcnow().isoformat(),
        ),
    )
    con.commit()
    con.close()


def db_log_event(user_id: int, event: str, extra: str = ""):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "INSERT INTO events (ts, user_id, event, extra) VALUES (?, ?, ?, ?)",
        (datetime.utcnow().isoformat(), user_id, event, extra),
    )
    con.commit()
    con.close()


def db_stats():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    users = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM events")
    events = cur.fetchone()[0]
    cur.execute(
        "SELECT event, COUNT(*) as c FROM events GROUP BY event ORDER BY c DESC LIMIT 10"
    )
    top = cur.fetchall()
    con.close()
    return users, events, top


# =========================
# UI TEXTS
# =========================
WELCOME_TEXT = (
    "🕯️ *Serafeon System*\n\n"
    "Чтобы открыть доступ к боту:\n"
    "1) Подпишись на основной канал\n"
    "2) Нажми *Check access*\n"
)
DENIED_TEXT = (
    "❌ *Access denied.*\n\n"
    "Subscribe to the main channel, then press *Check access*."
)
GRANTED_TEXT = (
    "✅ *Access granted.*\n\n"
    "Ты подписан на основной канал.\n"
    "Дальше тут появятся дополнительные опции (VIP / подписка — позже)."
)

BTN_SUBSCRIBE = "✅ Subscribe (main channel)"
BTN_CHECK = "🔎 Check access"
BTN_OPEN = "📌 Open main channel"

> ———-:
builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("health", health_cmd))
    app.add_handler(CallbackQueryHandler(check_access_cb, pattern=f"^{CB_CHECK}$"))

    # Если задан WEBHOOK_URL — работаем как Web Service (Render)
    if WEBHOOK_URL:
        # Telegram требует https и публичный URL
        full_url = WEBHOOK_URL.rstrip("/") + "/telegram"
        log.info("Starting webhook on port %s, url=%s", PORT, full_url)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path="telegram",
            webhook_url=full_url,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        # Если webhook не задан — long polling (подойдёт для локального теста)
        log.info("Starting polling...")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if name == "__main__":
    main()
