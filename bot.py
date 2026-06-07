import os
import re
import requests
import logging
from html import unescape
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

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

FB_PATTERNS = [
    r"https?://(?:www\.|m\.|web\.)?facebook\.com/\S+",
    r"https?://fb\.watch/\S+",
    r"https?://fb\.me/\S+",
]


def extract_fb_links(text: str) -> list:
    links = []
    for pattern in FB_PATTERNS:
        links.extend(re.findall(pattern, text))
    cleaned = [re.sub(r"[),.\"\s]+$", "", link) for link in links]
    seen = set()
    result = []
    for link in cleaned:
        if link not in seen:
            seen.add(link)
            result.append(link)
    return result


def fetch_page_title(url: str) -> str:
    """Lấy tiêu đề qua jsonlink.io API (hỗ trợ tốt Facebook)."""
    try:
        api_url = f"https://jsonlink.io/api/extract?url={requests.utils.quote(url, safe='')}"
        resp = requests.get(api_url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            title = data.get("title", "")
            if title and title.strip() and title.lower() != "facebook":
                return unescape(title.strip())
    except Exception as e:
        logger.warning(f"jsonlink.io thất bại: {e}")

    # Fallback: opengraph.io
    try:
        api_url2 = f"https://opengraph.io/api/1.1/site/{requests.utils.quote(url, safe='')}?app_id=sample_key"
        resp2 = requests.get(api_url2, timeout=15)
        if resp2.status_code == 200:
            data2 = resp2.json()
            title2 = data2.get("openGraph", {}).get("title", "") or data2.get("htmlInferred", {}).get("title", "")
            if title2 and title2.strip():
                return unescape(title2.strip())
    except Exception as e:
        logger.warning(f"opengraph.io thất bại: {e}")

    # Fallback cuối: fetch trực tiếp với facebookexternalhit
    try:
        headers = {
            "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
            "Accept-Language": "vi-VN,vi;q=0.9",
        }
        resp3 = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        # Tìm og:title trong raw bytes để tránh encoding issues
        text = resp3.content.decode("utf-8", errors="replace")
        for pattern in [
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',
            r'<title[^>]*>([^<]+)</title>',
        ]:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                t = unescape(m.group(1).strip())
                if t and t.lower() != "facebook":
                    return t
    except Exception as e:
        logger.warning(f"Direct fetch thất bại: {e}")

    return "(Không lấy được tiêu đề)"


def push_to_sheet(timestamp: str, title: str, link: str) -> bool:
    try:
        payload = {"timestamp": timestamp, "title": title, "link": link}
        resp = requests.post(APPS_SCRIPT_URL, json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json().get("status") == "success"
    except Exception as e:
        logger.error(f"Lỗi Sheet: {e}")
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Xin chào! Mình là bot lưu link Facebook.\n\n"
        "📌 Gửi link Facebook bất kỳ, mình tự động lưu vào Google Sheet:\n"
        "  • Thời gian\n  • Tiêu đề bài viết\n  • Đường link\n\n"
        "Gõ /help để xem thêm hướng dẫn."
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Hướng dẫn*\n\n"
        "Gửi link Facebook vào đây, bot tự lưu Sheet.\n"
        "Hỗ trợ: facebook.com, fb.watch, fb.me\n\n"
        "/status — Kiểm tra kết nối",
        parse_mode="Markdown",
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        resp = requests.get(APPS_SCRIPT_URL, timeout=10)
        if resp.status_code == 200:
            await update.message.reply_text("✅ Kết nối Google Sheet: OK")
        else:
            await update.message.reply_text(f"⚠️ HTTP {resp.status_code}")
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi: {e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or update.message.caption or ""
    links = extract_fb_links(text)

    if not links:
        await update.message.reply_text(
            "⚠️ Không tìm thấy link Facebook.\n"
            "Gửi link dạng facebook.com, fb.watch hoặc fb.me"
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
                f"✅ Đã lưu!\n📰 {title}\n🔗 {link}\n🕐 {timestamp}"
            )
        else:
            failed += 1
            await update.message.reply_text(f"❌ Lỗi khi lưu: {link}")

    summary = f"📊 Hoàn tất: {saved} lưu thành công"
    if failed:
        summary += f", {failed} thất bại"
    await update.message.reply_text(summary)


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
