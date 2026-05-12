import logging
import os
from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Maxfiy ma'lumotlar — Railway environment variables orqali yuklanadi ===
# Railway dashboardidagi "Variables" bo'limidan sozlanadi.
# Lokalda sinash uchun .env faylidan (gitignore'ga qo'shilgan) yuklash mumkin.
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
MINI_APP_URL = os.environ.get(
    "MINI_APP_URL",
    "https://argos-bot-production.up.railway.app/static/index.html",
).strip()

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN environment variable o'rnatilmagan. "
        "Railway > Variables bo'limida BOT_TOKEN ni qo'shing."
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton(
            "🏥 ARGOS Testini Boshlash",
            web_app=WebAppInfo(url=f"{MINI_APP_URL}?user_id={user.id}")
        )]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"Assalomu alaykum, {user.first_name}! 👋\n\n"
        "🏥 *ARGOS Test Tayyorlov Botiga Xush Kelibsiz!*\n\n"
        "Bu bot shifokor va hamshiralar uchun ARGOS testiga tayyorlanishda yordam beradi.\n\n"
        "📝 Testni boshlash uchun quyidagi tugmani bosing:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Qo'llanma:*\n\n"
        "/start — Botni boshlash\n"
        "/yordam — Ushbu xabar\n\n"
        "Mini App ichida:\n"
        "📝 Test — Yangi test boshlash\n"
        "📊 Natijalar — O'z natijalaringiz\n"
        "❌ Xatolarim — Noto'g'ri javoblar\n",
        parse_mode="Markdown"
    )


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("yordam", help_command))
    logger.info("Bot ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()
