import os
import asyncio
import ssl
import sqlite3
import re
import aiohttp
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from pypdf import PdfReader
from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

# Muhit o'zgaruvchilarini yuklash
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")

ssl._create_default_https_context = ssl._create_unverified_context

# 💳 KARTA RAQAMLARI
KARTA_RAQAMLARI = ["9860080387113030", "9860 0803 8711 3030", "986008******3030"]
ASOSIY_KARTA_KORINISHI = "9860 0803 8711 3030"

# 💾 SQLITE BAZANI SOZLASH
conn = sqlite3.connect("cheklar.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS ishlatilgan_cheklar (chek_id TEXT PRIMARY KEY)")
cursor.execute("CREATE TABLE IF NOT EXISTS buyurtmalar (id INTEGER PRIMARY KEY AUTOINCREMENT, sana TEXT, soat TEXT, jinsi TEXT, info TEXT, summa INTEGER, vaqt TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
conn.commit()

# --- BAZA FUNKSIYALARI ---
def chek_mavjudmi(chek_id):
    cursor.execute("SELECT 1 FROM ishlatilgan_cheklar WHERE chek_id = ?", (chek_id,))
    return cursor.fetchone() is not None

def chek_qoshish(chek_id):
    try:
        cursor.execute("INSERT INTO ishlatilgan_cheklar (chek_id) VALUES (?)", (chek_id,))
        conn.commit()
    except sqlite3.IntegrityError: pass

def buyurtma_saqlash(sana, soat, jinsi, info, summa):
    cursor.execute("INSERT INTO buyurtmalar (sana, soat, jinsi, info, summa) VALUES (?, ?, ?, ?, ?)", (sana, soat, jinsi, info, summa))
    conn.commit()

def statistika_olish():
    cursor.execute("SELECT COUNT(*), SUM(summa) FROM buyurtmalar")
    jami, jami_pul = cursor.fetchone()
    return jami, (jami_pul if jami_pul else 0)

def oxirgi_buyurtmalar():
    cursor.execute("SELECT sana, soat, jinsi, info, summa FROM buyurtmalar ORDER BY id DESC LIMIT 5")
    return cursor.fetchall()

# --- RASMDAN MATNNI ONLINE EKSTRAKT QILISH (OCR SPACE FREE API) ---
async def rasmdan_matn_oqish(file_path: str) -> str:
    url = "https://ocr.space"
    payload = {"apikey": "helloworld", "language": "eng", "isOverlayRequired": "false"}
    try:
        async with aiohttp.ClientSession() as session:
            with open(file_path, 'rb') as f:
                data = aiohttp.FormData()
                data.add_field('file', f, filename=os.path.basename(file_path))
                for k, v in payload.items(): data.add_field(k, v)
                async with session.post(url, data=data, timeout=30) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if "ParsedResults" in result and len(result["ParsedResults"]) > 0:
                            return result["ParsedResults"]["ParsedText"]
    except Exception as e: print(f"OCR API Xatolik: {e}")
    return ""

def chek_summasini_top(matn: str) -> int:
    matn_lower = matn.lower()
    patterns = [r'(?:summa|miqdori|amount|итого|оплата|uzs|so\'m|som)[\s\:\-]*([\d\s\.,]+)', r'([\d\s\.,]+)[\s]*(?:uzs|so\'m|som)']
    topilgan_raqamlar = []
    for pattern in patterns:
        matches = re.findall(pattern, matn_lower)
        for match in matches:
            clean_num = re.sub(r'[^\d]', '', match)
            if clean_num:
                val = int(clean_num)
                if 1000 <= val <= 5000000: topilgan_raqamlar.append(val)
    if not topilgan_raqamlar:
        all_numbers = re.findall(r'\b\d[\d\s\.,]{3,7}\d\b', matn_lower)
        for num in all_numbers:
            clean_num = re.sub(r'[^\d]', '', num)
            if clean_num:
                val = int(clean_num)
                if 1000 <= val <= 5000000: topilgan_raqamlar.append(val)
    for v in topilgan_raqamlar:
        if v >= 5000: return v
    return topilgan_raqamlar if topilgan_raqamlar else 0

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class AlarmState(StatesGroup):
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_gender = State()
    waiting_for_info = State()
    waiting_for_payment = State()

def get_admin_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📊 Statistika"), KeyboardButton(text="📋 Oxirgi 5 ta buyurtma")]], resize_keyboard=True)

@dp.message(F.text == "/admin")
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("👑 **Admin panelga xush kelibsiz!**", reply_markup=get_admin_keyboard())

@dp.message(F.text == "📊 Statistika")
async def show_stats(message: Message):
    if message.from_user.id != ADMIN_ID: return
    jami, jami_pul = statistika_olish()
    await message.answer(f"📈 **Bot Statistikasi:**\n\n⏰ Jami buyurtmalar: **{jami} ta**\n💰 Kassaga tushgan jami pul: **{jami_pul:,} so'm**")

@dp.message(F.text == "📋 Oxirgi 5 ta buyurtma")
async def show_orders(message: Message):
    if message.from_user.id != ADMIN_ID: return
    orders = oxirgi_buyurtmalar()
    if not orders:
        await message.answer("📭 Hozircha faol buyurtmalar mavjud emas.")
        return
    text = "📋 **Oxirgi 5 ta faol buyurtma:**\n\n"
    for idx, (sana, soat, jinsi, info, summa) in enumerate(orders, 1):
        text += f"{idx}. 📅 {sana} | ⏰ {soat} | 👤 {jinsi}\n💰 {summa:,} so'm | 📝 {info}\n" + "-"*25 + "\n"
    await message.answer(text)

@dp.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("👋 Assalomu alaykum! Tizimga xush kelibsiz.\n\n📅 Birinchi navbatda, **sanani** kiriting:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AlarmState.waiting_for_date)

@dp.message(AlarmState.waiting_for_date)
async def process_date(message: Message, state: FSMContext):
    await state.update_data(wakeup_date=message.text)
    await message.answer("⏰ Rahmat! Endi sizni **nechada** uygʻotish kerakligini yozing:")
    await state.set_state(AlarmState.waiting_for_time)

@dp.message(AlarmState.waiting_for_time)
async def process_time(message: Message, state: FSMContext):
    await state.update_data(wakeup_time=message.text)
    gender_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🙋‍♂️ Erkak"), KeyboardButton(text="🙋‍♀️ Ayol")]], resize_keyboard=True, one_time_keyboard=True)
    await message.answer("👤 Iltimos, pastdagi tugmalardan foydalanib jinsingizni tanlang:", reply_markup=gender_kb)
    await state.set_state(AlarmState.waiting_for_gender)

@dp.message(AlarmState.waiting_for_gender, F.text.in_({"🙋‍♂️ Erkak", "🙋‍♀️ Ayol"}))
async def process_gender(message: Message, state: FSMContext):
    await state.update_data(user_gender=message.text)
    await message.answer("📝 Endi telefon raqamingiz va ismingizni kiriting:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AlarmState.waiting_for_info)

@dp.message(AlarmState.waiting_for_info)
async def process_info(message: Message, state: FSMContext):
    await state.update_data(user_info=message.text)
    await message.answer(f"💳 Xizmat faollashishi uchun **5000 so'm** to'lov qiling:\n\n📌 Karta raqam: `{ASOSIY_KARTA_KORINISHI}`\n\n⚠️ To'lovni amalga oshirgach, chek rasmini yoki PDF chekni yuboring.")
    await state.set_state(AlarmState.waiting_for_payment)

@dp.message(AlarmState.waiting_for_payment, F.photo | F.document)
async def process_payment(message: Message, state: FSMContext):
    await message.answer("🔄 Chek va to'lov summasi tekshirilmoqda, iltimos kuting...")
    os.makedirs("downloads", exist_ok=True)
    detected_text_all = ""
    
    if message.photo:
        file_id = message.photo[-1].file_id
        file = await bot.get_file(file_id)
        file_path = f"downloads/{file_id}.jpg"
        await bot.download_file(file.file_path, file_path)
        detected_text_all = await rasmdan_matn_oqish(file_path)
        if os.path.exists(file_path): os.remove(file_path)
    elif message.document and message.document.file_name.endswith('.pdf'):
        file_id = message.document.file_id
        file = await bot.get_file(file_id)
        file_path = f"downloads/{file_id}.pdf"
        await bot.download_file(file.file_path, file_path)
        try:
            pdf_reader = PdfReader(file_path)
            detected_text_all = " ".join([p.extract_text() for p in pdf_reader.pages if p.extract_text()])
        except Exception as e: print(f"PDF xatolik: {e}")
        if os.path.exists(file_path): os.remove(file_path)
    else:
        await message.answer("❌ Iltimos, faqat rasm yoki PDF yuboring!")
        return

    clean_text = detected_text_all.lower().replace("-", "").replace(" ", "").replace("\n", "")
    is_valid_karta = any(karta.replace(" ", "") in clean_text for karta in KARTA_RAQAMLARI)
    tushgan_summa = chek_summasini_top(detected_text_all)
    chek_unikal_id = clean_text[:20] if len(clean_text) > 20 else clean_text
    
    if chek_mavjudmi(chek_unikal_id):
        await message.answer("❌ **To'lov rad etildi!**\n\nSababi: Tizimda bu chek ishlatilgan!")
        return
        
    if is_valid_karta and tushgan_summa >= 5000:
        chek_qoshish(chek_unikal_id)
        user_data = await state.get_data()
        buyurtma_saqlash(user_data['wakeup_date'], user_data['wakeup_time'], user_data['user_gender'], user_data['user_info'], tushgan_summa)
        await message.answer(f"✅ **To'lov cheki muvaffaqiyatli tasdiqlandi!** Rahmat!")
        
        report_text = (
            f"✅ 💰 **Muvaffaqiyatli To'lov Yakunlandi!**\n\n"
            f"💵 **Tushgan summa:** {tushgan_summa:,} so'm\n"
            f"📅 **Sana:** {user_data['wakeup_date']}\n"
            f"⏰ **Soat:** {user_data['wakeup_time']}\n"
            f"👤 **Jinsi:** {user_data['user_gender']}\n"
