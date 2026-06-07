import os
import re
import requests
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8406134337:AAHJeazza035ZJsMEBv02mpACzlPY67g2bw")
APPS_SCRIPT_URL = os.getenv("APPS_SCRIPT_URL", "https://script.google.com/macros/s/AKfycbyBv4v8jC0EJB-6V7wEg5eSISg4CRv2zT6PP6xX4aLX326dhXbGM-1ju6rWQW1YgOxYww/exec")

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── FACEBOOK URL PATTERNS ────────────────────────────────────────────────────
FB_PATTERNS = [
    r"https?://(?:www\.|m\.|web\.)?facebook\.com/\S+",
    r"https?://fb\.watch/\S+",
    r"https?://fb\.me/\S+",
]


def extract_fb_links(text: str) -> list:
    """Trích xuất tất cả link Facebook trong tin nhắn."""
    links = []
    for pattern in FB_PATTERNS:
        links.extend(re.findall(pattern, text))
    # Loại bỏ dấu câu cuối link
    cleaned = [re.sub(r"[),.\"\s]+$", "", link) for link in links]
    # Loại trùng, giữ thứ tự
    seen = set()
    result = []
    for link in cleaned:
        if link not in seen:
            seen.add(link)
            result.append(link)
    return result


def fetch_page_title(url: str) -> str:
    """Lấy tiêu đề trang, thử nhiều User-Agent."""
    user_agents = [
        "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Twitterbot/1.0",
    ]
    for ua in user_agents:
        try:
            headers = {
                "User-Agent": ua,
                "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
            }
            resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
            resp.raise_for_status()

            # Ưu tiên Open Graph title
            og_match = re.search(
                r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
                resp.text, re.IGNORECASE,
            )
            if og_match:
                return og_match.group(1).strip()

            # Thử content trước property
            og_match2 = re.search(
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',
                resp.text, re.IGNORECASE,
            )
            if og_match2:
                return og_match2.group(1).strip()

            # Fallback: thẻ <title>
            title_match = re.search(r"<title[^>]*>([^<]+)</title>", resp.text, re.IGNORECASE)
            if title_match:
                title = title_match.group(1).strip()
                if title and title.lower() not in ("facebook", ""):
                    return title

        except Exception as e:
            logger.warning(f"Thất bại cho {url}: {e}")
            continue

    return "(Không lấy được tiêu đề)"


def push_to_sheet(timestamp: str, title: str, link: str) -> bool:
    """Gửi dữ liệu lên Google Sheet qua Apps Script Web App."""
    try:
        payload = {"timestamp": timestamp, "title": title, "link": link}
        resp = requests.post(APPS_SCRIPT_URL, json=payload, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        return result.get("status") == "success"
    except Exception as e:
        logger.error(f"Lỗi khi đẩy lên Sheet: {e}")
        return False


# ─── HANDLERS ─────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Xin chào! Mình là bot lưu link Facebook.\n\n"
        "📌 Chỉ cần gửi hoặc forward link Facebook bất kỳ, "
        "mình sẽ tự động lưu vào Google Sheet với:\n"
        "  • Thời gian\n"
        "  • Tiêu đề bài viết\n"
        "  • Đường link\n\n"
        "Gõ /help để xem thêm hướng dẫn."
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Hướng dẫn sử dụng*\n\n"
        "1. Gửi link Facebook vào chat này\n"
        "2. Bot sẽ tự phát hiện link, lấy tiêu đề và lưu vào Sheet\n"
        "3. Mỗi link được lưu 1 dòng riêng\n\n"
        "✅ Hỗ trợ:\n"
        "  • facebook.com/...\n"
        "  • fb.watch/...\n"
        "  • fb.me/...\n\n"
        "📊 /status — Kiểm tra kết nối",
        parse_mode="Markdown",
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Đang kiểm tra kết nối với Google Sheet...")
    try:
        resp = requests.get(APPS_SCRIPT_URL, timeout=10)
        if resp.status_code == 200:
            await update.message.reply_text("✅ Kết nối Google Sheet: OK")
        else:
            await update.message.reply_text(f"⚠️ Sheet trả về HTTP {resp.status_code}")
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi kết nối: {e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý mọi tin nhắn văn bản."""
    text = update.message.text or update.message.caption or ""
    links = extract_fb_links(text)

    if not links:
        await update.message.reply_text(
            "⚠️ Không tìm thấy link Facebook trong tin nhắn.\n"
            "Vui lòng gửi link dạng facebook.com, fb.watch hoặc fb.me"
        )
        return

    await update.message.reply_text(f"🔍 Tìm thấy {len(links)} link, đang xử lý...")

    saved, failed = 0, 0
    for link in links:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        title = fetch_page_title(link)
        success = push_to_sheet(timestamp, title, link)

        if success:
            saved += 1
            await update.message.reply_text(
                f"✅ Đã lưu!\n"
                f"📰 *{title}*\n"
                f"🔗 {link}\n"
                f"🕐 {timestamp}",
                parse_mode="Markdown",
            )
        else:
            failed += 1
            await update.message.reply_text(f"❌ Lỗi khi lưu: {link}")

    summary = f"📊 Hoàn tất: {saved} lưu thành công"
    if failed:
        summary += f", {failed} thất bại"
    await update.message.reply_text(summary)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.CAPTION & ~filters.COMMAND, handle_message))

    logger.info("🤖 Bot đang chạy...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
