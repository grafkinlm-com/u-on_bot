import os
import re
import zipfile
import subprocess
import logging
import sqlite3
from datetime import datetime
from difflib import SequenceMatcher
from docx import Document
from lxml import etree
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

DOCS_FOLDER = "uploaded_docs"
os.makedirs(DOCS_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = (".doc", ".docx")
DB_PATH = "bot_activity.db"

# ─── База данных ──────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            action TEXT,
            details TEXT
        )
    """)
    conn.commit()
    conn.close()

def log_activity(user_id, username, action, details=""):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO activity_log (user_id, username, action, details) VALUES (?, ?, ?, ?)",
        (user_id, username, action, details)
    )
    conn.commit()
    conn.close()

init_db()

# ─── Чтение файлов ────────────────────────────────────────────────────────────

def read_file(file_path):
    if file_path.endswith(".docx"):
        doc = Document(file_path)
        return "\n".join([p.text for p in doc.paragraphs])
    elif file_path.endswith(".doc"):
        result = subprocess.run(
            ["antiword", file_path],
            capture_output=True, text=True,
            encoding="utf-8", errors="ignore"
        )
        return result.stdout.strip()
    return ""

def get_page_count(file_path):
    text = read_file(file_path)
    words = len(text.split())
    return max(1, words // 250)

def get_size_bytes(path):
    return os.path.getsize(path)

def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} Б"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes // 1024} КБ"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} МБ"

def format_diff(val, unit=""):
    sign = "+" if val > 0 else ""
    return f"{sign}{val}{unit}"

# ─── Алгоритм сравнения ───────────────────────────────────────────────────────

def split_sentences(text):
    """Разбивает текст на предложения."""
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in parts if len(s.strip()) > 10]

STOPWORDS = {
    "что", "как", "все", "его", "она", "они", "для", "при", "или",
    "уже", "еще", "ещё", "мне", "тем", "там", "так", "той", "тот",
    "эта", "это", "эти", "был", "были", "была", "есть", "нет", "нас",
    "вас", "чем", "чтобы", "если", "только", "когда", "где", "кто",
    "весь", "этот", "тоже", "себя", "него", "нее", "ней", "ним", "них",
    "про", "над", "под", "без", "через", "после", "перед", "между",
    "также", "либо", "ведь", "вот", "даже", "именно", "более", "менее",
    "очень", "просто", "можно", "нужно", "должен", "может",
    "такой", "такая", "такие", "каждый", "любой",
    "the", "and", "for", "are", "but", "not", "you", "all",
    "can", "was", "this", "that", "with", "have", "from",
}

def normalize_words(text):
    text = text.lower()
    text = re.sub(r"[^\wа-яёa-z0-9\s]", " ", text)
    return [w for w in text.split() if len(w) > 2 and w not in STOPWORDS]

def calc_similarity(text1, text2, pages1=None, pages2=None):
    """
    Комплексная оценка схожести:
      - 70% веса: совпадение последовательности предложений
      - 20% веса: совпадение объёма текста (слова)
      - 10% веса: совпадение количества страниц
    """
    sentences1 = split_sentences(text1)
    sentences2 = split_sentences(text2)

    if not sentences1 or not sentences2:
        return 0.0

    # 1. Последовательность предложений (порядок важен)
    sent_sim = SequenceMatcher(None, sentences1, sentences2).ratio()

    # 2. Объём текста — штраф за разницу количества слов
    wc1 = len(normalize_words(text1))
    wc2 = len(normalize_words(text2))
    if max(wc1, wc2) > 0:
        wc_ratio = min(wc1, wc2) / max(wc1, wc2)
    else:
        wc_ratio = 1.0

    # 3. Страницы — штраф за разницу
    if pages1 and pages2 and max(pages1, pages2) > 0:
        page_ratio = min(pages1, pages2) / max(pages1, pages2)
    else:
        page_ratio = 1.0

    return sent_sim * 0.70 + wc_ratio * 0.20 + page_ratio * 0.10

# ─── Обработчики команд ───────────────────────────────────────────────────────

user_mode = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or f"user_{update.effective_user.id}"
    log_activity(update.effective_user.id, username, "start", "")
    
    await update.message.reply_text(
        "Привет! Выбери режим:\n"
        "/add — добавить файл в базу\n"
        "/check — проверить файл на схожесть\n"
        "/list — показать все файлы\n"
        "/delete — удалить файлы"
    )

async def add_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or f"user_{user_id}"
    user_mode[user_id] = "add"
    log_activity(user_id, username, "mode_add", "")
    await update.message.reply_text("Режим: добавление в базу. Отправляй файлы Word (.doc или .docx).")

async def check_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or f"user_{user_id}"
    user_mode[user_id] = "check"
    log_activity(user_id, username, "mode_check", "")
    await update.message.reply_text("Режим: проверка. Отправь файл для сравнения (.doc или .docx).")

async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or f"user_{user_id}"
    files = [
        f for f in os.listdir(DOCS_FOLDER)
        if not f.startswith("temp") and any(f.endswith(e) for e in ALLOWED_EXTENSIONS)
    ]
    log_activity(user_id, username, "list", f"Found {len(files)} files")
    
    if not files:
        await update.message.reply_text("В базе нет загруженных файлов.")
        return
    
    files_list = "\n".join([f"{i+1}. {f}" for i, f in enumerate(sorted(files))])
    await update.message.reply_text(
        f"📚 Загруженные файлы:\n\n{files_list}\n\n"
        f"Для удаления отправь: /delete 1,2,3 (номера через запятую)"
    )

async def delete_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or f"user_{user_id}"
    args = context.args
    if not args:
        files = [
            f for f in os.listdir(DOCS_FOLDER)
            if not f.startswith("temp") and any(f.endswith(e) for e in ALLOWED_EXTENSIONS)
        ]
        if not files:
            await update.message.reply_text("В базе нет файлов для удаления.")
            return
        files_list = "\n".join([f"{i+1}. {f}" for i, f in enumerate(sorted(files))])
        await update.message.reply_text(
            f"📚 Доступные файлы:\n\n{files_list}\n\n"
            f"Отправь: /delete 1,2,3 (номера через запятую)"
        )
        return
    
    files = [
        f for f in os.listdir(DOCS_FOLDER)
        if not f.startswith("temp") and any(f.endswith(e) for e in ALLOWED_EXTENSIONS)
    ]
    files = sorted(files)
    
    try:
        indices = [int(x.strip()) - 1 for x in args[0].split(",")]
    except (ValueError, IndexError):
        await update.message.reply_text("Ошибка! Используй формат: /delete 1,2,3")
        return
    
    deleted = []
    errors = []
    for idx in indices:
        if 0 <= idx < len(files):
            file_path = os.path.join(DOCS_FOLDER, files[idx])
            try:
                os.remove(file_path)
                deleted.append(files[idx])
            except Exception as e:
                errors.append(f"{files[idx]}: {str(e)}")
        else:
            errors.append(f"Номер {idx+1} не существует")
    
    log_activity(user_id, username, "delete", f"Deleted: {', '.join(deleted)}")
    
    msg = ""
    if deleted:
        msg += f"✅ Удалено: {', '.join(deleted)}\n"
    if errors:
        msg += f"❌ Ошибки: {', '.join(errors)}"
    
    await update.message.reply_text(msg if msg else "Нечего было удалять.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or f"user_{user_id}"
    today = datetime.now().strftime("%Y-%m-%d")
    date_from = today
    date_to = today
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, user_id, username, timestamp, action, details
        FROM activity_log
        WHERE DATE(timestamp) BETWEEN ? AND ?
        ORDER BY username, timestamp ASC
    """, (date_from, date_to))
    
    results = cursor.fetchall()
    conn.close()
    
    if not results:
        await update.message.reply_text(f"Статистика за {date_from} - {date_to}: нет активности")
        return
    
    # Группируем по пользователю
    user_activities = {}
    for log_id, user_id_log, username_log, timestamp, action, details in results:
        if username_log not in user_activities:
            user_activities[username_log] = []
        user_activities[username_log].append((timestamp, action, details))
    
    # Формируем подробный отчёт
    report = f"📊 Подробная статистика ({date_from} — {date_to}):\n\n"
    
    action_display_map = {
        "start": "🚀 Запуск",
        "mode_add": "📥 Режим добавления",
        "mode_check": "🔍 Режим проверки",
        "list": "📋 Просмотр списка",
        "add": "📤 Загрузка",
        "check": "⚖️ Сравнение",
        "delete": "🗑️ Удаление"
    }
    
    for username_key in sorted(user_activities.keys()):
        report += f"👤 <b>{username_key}</b>\n"
        actions = user_activities[username_key]
        for timestamp, action, details in actions:
            action_label = action_display_map.get(action, action)
            time_str = timestamp.split(" ")[1][:5] if " " in timestamp else timestamp
            date_str = timestamp.split(" ")[0] if " " in timestamp else timestamp
            
            detail_str = f" [{details}]" if details else ""
            report += f"  {date_str} {time_str} — {action_label}{detail_str}\n"
        report += "\n"
    
    # Если отчёт слишком длинный, отправляем по частям
    MAX_LEN = 4000
    if len(report) > MAX_LEN:
        lines = report.split("\n")
        current_msg = ""
        for line in lines:
            if len(current_msg) + len(line) + 1 > MAX_LEN:
                if current_msg:
                    await update.message.reply_text(current_msg, parse_mode="HTML")
                current_msg = line + "\n"
            else:
                current_msg += line + "\n"
        if current_msg.strip():
            await update.message.reply_text(current_msg, parse_mode="HTML")
    else:
        await update.message.reply_text(report, parse_mode="HTML")

async def handle_docs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = update.message.document
    user_id = update.effective_user.id
    username = update.effective_user.username or f"user_{user_id}"

    if not any(file.file_name.endswith(ext) for ext in ALLOWED_EXTENSIONS):
        await update.message.reply_text("Нужен файл с расширением .doc или .docx")
        return

    mode = user_mode.get(user_id)

    if mode == "add":
        file_path = os.path.join(DOCS_FOLDER, file.file_name)
        tg_file = await file.get_file()
        await tg_file.download_to_drive(file_path)
        log_activity(user_id, username, "add", file.file_name)
        await update.message.reply_text(f"Файл {file.file_name} добавлен в базу!")

    elif mode == "check":
        await update.message.reply_text("Взял в работу. Анализирую...")

        ext = ".docx" if file.file_name.endswith(".docx") else ".doc"
        temp_path = os.path.join(DOCS_FOLDER, f"temp{ext}")
        tg_file = await file.get_file()
        await tg_file.download_to_drive(temp_path)

        new_text = read_file(temp_path)
        new_pages = get_page_count(temp_path)
        new_size = get_size_bytes(temp_path)
        new_words = len(normalize_words(new_text))
        results = []

        existing_files = [
            f for f in os.listdir(DOCS_FOLDER)
            if not f.startswith("temp") and any(f.endswith(e) for e in ALLOWED_EXTENSIONS)
        ]

        for existing in existing_files:
            ex_path = os.path.join(DOCS_FOLDER, existing)
            ex_text = read_file(ex_path)
            ex_pages = get_page_count(ex_path)
            ex_size = get_size_bytes(ex_path)
            ex_words = len(normalize_words(ex_text))

            sim = calc_similarity(new_text, ex_text, new_pages, ex_pages)
            sim_percent = round(sim * 100)

            if sim_percent >= 70:
                results.append((existing, sim_percent, ex_pages, ex_size, ex_words))

        total = len(existing_files)
        matches = len(results)
        log_activity(user_id, username, "check", f"{file.file_name} (matches: {matches}/{total})")
        
        new_pages_str = f"{new_pages} стр." if new_pages else "н/д"
        header = (
            f"📄 Ваш документ: {file.file_name}\n"
            f"   Страниц: {new_pages_str} | Слов: {new_words} | {format_size(new_size)}"
        )

        if results:
            results.sort(key=lambda x: x[1], reverse=True)
            lines_parts = []
            for name, pct, ex_pages, ex_size, ex_words in results:
                page_diff = ""
                if new_pages and ex_pages:
                    diff = ex_pages - new_pages
                    page_diff = f"Разница стр.: {format_diff(diff, ' стр.')}"
                else:
                    page_diff = "Страниц: н/д"

                word_diff = ex_words - new_words
                size_diff_kb = (ex_size - new_size) // 1024

                lines_parts.append(
                    f"📋 {name} : <b>{pct}%</b>\n"
                    f"   {page_diff}\n"
                    f"   Разница слов: {format_diff(word_diff)}\n"
                    f"   Разница размера: {format_diff(size_diff_kb, ' КБ')}"
                )

            lines = "\n\n".join(lines_parts)
            await update.message.reply_text(
                f"{header}\n\nНайдены совпадения:\n\n{lines}\n\nПроверено документов: {total}",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                f"{header}\n\nСовпадений от 70% и выше не найдено.\n\nПроверено документов: {total}"
            )

        os.remove(temp_path)

    else:
        await update.message.reply_text("Сначала выбери режим: /add или /check")

# ─── Точка входа ──────────────────────────────────────────────────────────────

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_mode))
    app.add_handler(CommandHandler("check", check_mode))
    app.add_handler(CommandHandler("list", list_files))
    app.add_handler(CommandHandler("delete", delete_mode))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_docs))

    logger.info("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
