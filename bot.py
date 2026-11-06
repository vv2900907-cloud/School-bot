import os
import asyncio
import re
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from playwright.async_api import async_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8244350771:AAE0-KxUTm5NJl3BTYo3Mc1ieddhjBAFJgU")  
LOGIN_START_URL = "https://diary.e-schools.by/#/login"
DIRECT_DIARY_URL = "https://diary.e-schools.by/#/diary?tab=diary"
SESSION_FILE = "state.json"

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
session_lock = asyncio.Lock()

def get_main_keyboard() -> ReplyKeyboardMarkup:
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row("📖 Домашнее задание", "⭐️ Оценки за день")
    keyboard.row("📊 Оценки за четверть")
    keyboard.row("⚙️ Аккаунт", "🔄 Войти заново")
    return keyboard

def get_days_inline_keyboard(prefix: str) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📅 Вся неделя", callback_data=f"{prefix}_all"),
        InlineKeyboardButton("📌 Понедельник", callback_data=f"{prefix}_1"),
        InlineKeyboardButton("📌 Вторник", callback_data=f"{prefix}_2"),
        InlineKeyboardButton("📌 Среда", callback_data=f"{prefix}_3"),
        InlineKeyboardButton("📌 Четверг", callback_data=f"{prefix}_4"),
        InlineKeyboardButton("📌 Пятница", callback_data=f"{prefix}_5")
    )
    return keyboard

async def apply_stealth(page):
    await page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        window.navigator.chrome = { runtime: {} };
    """)

def get_safe_context_args() -> dict:
    if os.path.exists(SESSION_FILE):
        return {"storage_state": SESSION_FILE}
    return {}

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Бот готов к работе.\nВыбирай нужный раздел в меню ниже:", 
        reply_markup=get_main_keyboard()
    )

@dp.message_handler(lambda message: message.text in [
    "📊 Оценки за четверть", "⚙️ Аккаунт", "🔄 Войти заново"
])
async def process_menu(message: types.Message):
    action = message.text

    if action == "🔄 Войти заново":
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)
        await message.answer("🔄 Файл сессии удален. При следующем запросе откроется окно входа.", reply_markup=get_main_keyboard())
        return

    if action == "⚙️ Аккаунт":
        status = "🟢 Сессия сохранена" if os.path.exists(SESSION_FILE) else "🔴 Не авторизован"
        await message.answer(f"⚙️ **Статус:**\n• {status}", parse_mode="Markdown", reply_markup=get_main_keyboard())
        return

    if not os.path.exists(SESSION_FILE):
        await message.answer("🔐 **Сессия не найдена.** Открываю окно входа...\n\n1. Бот сам нажмет «Обучающийся».\n2. Войди через РИОС и открой свой дневник.\n3. Как только зайдешь, **бот сам всё сохранит** и закроет окно!", parse_mode="Markdown")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
            context = await browser.new_context()
            page = await context.new_page()
            await apply_stealth(page)
            
            try:
                await page.goto(LOGIN_START_URL, timeout=60000)
                try:
                    await page.wait_for_selector("text=Обучающийся", timeout=8000)
                    await page.click("text=Обучающийся")
                except:
                    pass

                logged_in = False
                for _ in range(120):
                    await asyncio.sleep(3)
                    try:
                        current_url = page.url
                        if "diary" in current_url and "login" not in current_url and "auth" not in current_url:
                            logged_in = True
                            break
                    except:
                        break

                if logged_in:
                    await asyncio.sleep(2)
                    await context.storage_state(path=SESSION_FILE)
                    await browser.close()
                    await message.answer("✅ **Сессия успешно сохранена автоматически!** Теперь запрашивай данные через меню.", reply_markup=get_main_keyboard())
                    return
                else:
                    await browser.close()
                    await message.answer("❌ Время входа истекло. Попробуй нажать кнопку заново.", reply_markup=get_main_keyboard())
                    return

            except Exception as e:
                try:
                    await browser.close()
                except:
                    pass
                await message.answer(f"❌ Ошибка: {e}", reply_markup=get_main_keyboard())
                return

    await message.answer("🔄 Получаю данные...", reply_markup=get_main_keyboard())
    result = await fetch_quarter_marks()
    await message.answer(result, parse_mode="Markdown", reply_markup=get_main_keyboard())


@dp.message_handler(lambda message: message.text == "📖 Домашнее задание")
async def cmd_homework_menu(message: types.Message):
    await message.answer("📅 **Выбери день для просмотра домашнего задания:**", parse_mode="Markdown", reply_markup=get_days_inline_keyboard("dz"))


@dp.message_handler(lambda message: message.text == "⭐️ Оценки за день")
async def cmd_marks_menu(message: types.Message):
    await message.answer("📅 **Выбери день для просмотра оценок:**", parse_mode="Markdown", reply_markup=get_days_inline_keyboard("marks"))


@dp.callback_query_handler(lambda c: c.data and (c.data.startswith('dz_') or c.data.startswith('marks_')))
async def process_day_callback(callback_query: types.CallbackQuery):
    data = callback_query.data
    chat_id = callback_query.message.chat.id
    
    await bot.answer_callback_query(callback_query.id)

    if data.startswith('dz_'):
        day_code = data.replace('dz_', '')
        await bot.send_message(chat_id, "🔄 Получаю домашнее задание...")
        result = await fetch_homework_by_day(day_code)
    else:
        day_code = data.replace('marks_', '')
        await bot.send_message(chat_id, "🔄 Получаю оценки за день...")
        result = await fetch_daily_marks_by_day(day_code)

    await bot.send_message(chat_id, result, parse_mode="Markdown")


def clean_group_clutter(text: str) -> str:
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    filtered = []
    skip_next = False
    for l in lines:
        lower_l = l.lower()
        if 'французский' in lower_l:
            skip_next = True
            continue
        if skip_next and ('§' in l or 'упр' in l or '№' in l or re.search(r'\b[1-9]\b', l)):
            skip_next = False
            continue
        filtered.append(l)
    return "\n".join(filtered)


async def fetch_homework_by_day(day_code: str) -> str:
    async with session_lock:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(**get_safe_context_args())
            page = await context.new_page()
            await apply_stealth(page)

            try:
                await page.goto(DIRECT_DIARY_URL, timeout=60000)
                await asyncio.sleep(4)

                if "login" in page.url or "auth" in page.url:
                    return "⚠️ Сессия устарела. Нажми кнопку **🔄 Войти заново** в меню."

                raw_page_text = await page.evaluate("() => document.body.innerText")
                await browser.close()

                days_pattern = re.compile(r'((Понедельник|Вторник|Среда|Четверг|Пятница|Суббота|Воскресенье)\s*\d{2}\.\d{2}\.\d{4})', re.IGNORECASE)
                split_text = days_pattern.split(raw_page_text)

                if len(split_text) < 4:
                    return "⚠️ Не удалось структурировать дни на странице. Попробуй позже."

                days_data = {}
                for i in range(1, len(split_text), 3):
                    day_title = split_text[i]
                    day_body = split_text[i+2] if i+2 < len(split_text) else ""
                    lower_title = day_title.lower()
                    if "понедельник" in lower_title:
                        days_data["1"] = (day_title, day_body)
                    elif "вторник" in lower_title:
                        days_data["2"] = (day_title, day_body)
                    elif "среда" in lower_title:
                        days_data["3"] = (day_title, day_body)
                    elif "четверг" in lower_title:
                        days_data["4"] = (day_title, day_body)
                    elif "пятница" in lower_title:
                        days_data["5"] = (day_title, day_body)

                def parse_day_lessons(day_name, body_text):
                    cleaned_body = clean_group_clutter(body_text)
                    lines = [l.strip() for l in cleaned_body.split('\n') if l.strip()]
                    results = []
                    current_lesson = "Урок"
                    lesson_counter = 0
                    
                    is_Wednesday = "среда" in day_name.lower()
                    is_Friday = "пятница" in day_name.lower()

                    for l in lines:
                        if re.match(r'^\d{1,2}[\.\)]', l):
                            lesson_counter += 1
                            current_lesson = l
                        elif any(sub in l.lower() for sub in ['география', 'физика', 'химия', 'математика', 'история', 'биология', 'информатика', 'литература', 'русский', 'беларуская', 'обществоведение', 'физическая', 'черчение', 'английский']):
                            current_lesson = f"{lesson_counter}. {l}"
                        
                        elif any(k in l.lower() for k in ['§', 'упр', 'стр', 'читать', 'выучить', 'повторить', 'параграф', 'номер', '№']):
                            target_lesson = current_lesson
                            if "история" in current_lesson.lower():
                                if not is_Wednesday and not (is_Friday and lesson_counter == 6):
                                    target_lesson = f"{lesson_counter}. Математика"
                            results.append(f"• **{target_lesson}**: {l}")
                    
                    return list(dict.fromkeys(results))

                if day_code != "all":
                    if day_code in days_data:
                        title, body = days_data[day_code]
                        parsed_dz = parse_day_lessons(title, body)
                        if not parsed_dz:
                            return f"📚 **Домашнее задание ({title}):**\n\n• Ничего заданного не найдено (или выходной)."
                        return f"📚 **Домашнее задание ({title}):**\n\n" + "\n".join(parsed_dz)
                    else:
                        return "⚠️ Этот день не найден в текущем расписании на странице."

                output = ["📚 **Домашнее задание на всю неделю:**\n"]
                for code in ["1", "2", "3", "4", "5"]:
                    if code in days_data:
                        title, body = days_data[code]
                        parsed_dz = parse_day_lessons(title, body)
                        output.append(f"\n📅 **{title}**")
                        if parsed_dz:
                            output.extend(parsed_dz[:10])
                        else:
                            output.append("• Нет домашнего задания")

                return "\n".join(output)

            except Exception as e:
                try:
                    await browser.close()
                except:
                    pass
                return f"❌ Ошибка: {str(e)}"


async def fetch_daily_marks_by_day(day_code: str) -> str:
    async with session_lock:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(**get_safe_context_args())
            page = await context.new_page()
            await apply_stealth(page)

            try:
                await page.goto(DIRECT_DIARY_URL, timeout=60000)
                await asyncio.sleep(4)

                if "login" in page.url or "auth" in page.url:
                    return "⚠️ Сессия устарела. Нажми кнопку **🔄 Войти заново** в меню."

                raw_page_text = await page.evaluate("() => document.body.innerText")
                await browser.close()

                days_pattern = re.compile(r'((Понедельник|Вторник|Среда|Четверг|Пятница|Суббота|Воскресенье)\s*\d{2}\.\d{2}\.\d{4})', re.IGNORECASE)
                split_text = days_pattern.split(raw_page_text)

                if len(split_text) < 4:
                    return "⚠️ Не удалось структурировать дни на странице."

                days_data = {}
                for i in range(1, len(split_text), 3):
                    day_title = split_text[i]
                    day_body = split_text[i+2] if i+2 < len(split_text) else ""
                    lower_title = day_title.lower()
                    if "понедельник" in lower_title:
                        days_data["1"] = (day_title, day_body)
                    elif "вторник" in lower_title:
                        days_data["2"] = (day_title, day_body)
                    elif "среда" in lower_title:
                        days_data["3"] = (day_title, day_body)
                    elif "четверг" in lower_title:
                        days_data["4"] = (day_title, day_body)
                    elif "пятница" in lower_title:
                        days_data["5"] = (day_title, day_body)

                def parse_day_marks(day_name, body_text):
                    cleaned_body = clean_group_clutter(body_text)
                    lines = [l.strip() for l in cleaned_body.split('\n') if l.strip()]
                    results = []
                    current_lesson = "Урок"
                    lesson_counter = 0
                    
                    is_Wednesday = "среда" in day_name.lower()
                    is_Friday = "пятница" in day_name.lower()

                    for l in lines:
                        if re.match(r'^\d{1,2}[\.\)]', l):
                            lesson_counter += 1
                            current_lesson = l
                        elif any(sub in l.lower() for sub in ['география', 'физика', 'химия', 'математика', 'история', 'биология', 'информатика', 'литература', 'русский', 'беларуская', 'обществоведение', 'физическая', 'черчение', 'английский']):
                            current_lesson = f"{lesson_counter}. {l}"
                        
                        elif re.search(r'\b(10|[1-9]|зач\.?)\b(?![:\d])', l, re.IGNORECASE) and not any(bad in l.lower() for bad in ['§', 'упр', 'стр', 'номер']):
                            target_lesson = current_lesson
                            if "история" in current_lesson.lower():
                                if not is_Wednesday and not (is_Friday and lesson_counter == 6):
                                    target_lesson = f"{lesson_counter}. Математика"

                            bolded = re.sub(r'\b(10|[1-9]|зач\.?)\b(?![:\d])', r'**\1**', l, flags=re.IGNORECASE)
                            results.append(f"• **{target_lesson}**: {bolded}")
                    
                    return list(dict.fromkeys(results))

                if day_code != "all":
                    if day_code in days_data:
                        title, body = days_data[day_code]
                        parsed_marks = parse_day_marks(title, body)
                        if not parsed_marks:
                            return f"⭐️ **Оценки за день ({title}):**\n\n• За этот день оценок пока нет."
                        return f"⭐️ **Оценки за день ({title}):**\n\n" + "\n".join(parsed_marks)
                    else:
                        return "⚠️ Этот день не найден в расписании."

                output = ["⭐️ **Оценки за всю неделю:**\n"]
                for code in ["1", "2", "3", "4", "5"]:
                    if code in days_data:
                        title, body = days_data[code]
                        parsed_marks = parse_day_marks(title, body)
                        output.append(f"\n📅 **{title}**")
                        if parsed_marks:
                            output.extend(parsed_marks)
                        else:
                            output.append("• Нет оценок")

                return "\n".join(output)

            except Exception as e:
                try:
                    await browser.close()
                except:
                    pass
                return f"❌ Ошибка: {str(e)}"


async def fetch_quarter_marks() -> str:
    async with session_lock:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(**get_safe_context_args())
            page = await context.new_page()
            await apply_stealth(page)

            try:
                await page.goto(DIRECT_DIARY_URL, timeout=60000)
                await asyncio.sleep(4)

                if "login" in page.url or "auth" in page.url:
                    return "⚠️ Сессия устарела. Нажми кнопку **🔄 Войти заново** в меню."

                try:
                    await page.click("text=Итоговые отметки", timeout=5000)
                    await asyncio.sleep(3)
                except Exception as e:
                    logging.info(f"Не удалось кликнуть по вкладке: {e}")

                raw_data = await page.evaluate("""() => {
                    const rows = document.querySelectorAll('tr, .v-data-table__tr');
                    let results = [];
                    rows.forEach(row => {
                        let text = row.innerText ? row.innerText.trim().replace(/\\n/g, ' ') : "";
                        if (text.length > 2) {
                            results.push(text);
                        }
                    });
                    return [...new Set(results)];
                }""")

                await browser.close()

                if not raw_data:
                    return "⚠️ Не удалось найти данные на странице."

                formatted_lines = []
                for line in raw_data:
                    clean_line = " ".join(line.split())

                    if any(bad in clean_line.lower() for bad in [
                        'электронный дневник', 'ведомость успеваемости', 'класс,', 
                        'режим работы', 'техподдержки', 'вопрос-ответ', 'предмет 1 четверть', 'французский'
                    ]):
                        continue

                    if any(q in clean_line.lower() for q in ['1 четверть', '2 четверть', '3 четверть', '4 четверть', 'экзамен', 'годовая', 'предмет']):
                        continue
                    
                    if re.search(r'\b(10|[1-9]|зач\.?)\b(?![:\d])', clean_line, re.IGNORECASE):
                        trimmed = re.sub(r'[\s\-–—]+$', '', clean_line)
                        bolded = re.sub(r'\b(10|[1-9]|зач\.?)\b(?![:\d])', r'**\1**', trimmed, flags=re.IGNORECASE)
                        formatted_lines.append(f"• {bolded}")

                formatted_lines = list(dict.fromkeys(formatted_lines))

                if not formatted_lines:
                    return "⚠️ В разделе «Оценки за четверть» пока нет подходящих данных."

                return "📊 **Оценки за четверть:**\n\n" + "\n".join(formatted_lines[:25])

            except Exception as e:
                try:
                    await browser.close()
                except:
                    pass
                return f"❌ Ошибка: {str(e)}"


async def main():
    await dp.start_polling()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Ошибка: {e}")