import os
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from PIL import Image
from pyzbar.pyzbar import decode
from aiohttp import web

# ⚙️ SOZLAMALAR
BOT_TOKEN = "8807461132:AAEnuAdAkusJk5dpcbudCd-Rj8gD2WoAXN4"  # Tokenni yozing
ADMIN_ID = 8968641076  # Telegram ID raqamingizni yozing
KARTA_RAQAM = "9860080387113030"  # Karta raqamingizni yozing

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class AlarmState(StatesGroup):
    waiting_for_time = State()
    waiting_for_info = State()
    waiting_for_payment = State()

# --- VEB SERVER (Render o'chib qolmasligi uchun) ---
async def handle(request):
    return web.Response(text="Bot muvaffaqiyatli ishlamoqda!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# --- TELEGRAM BOT LOGIKASI ---

@dp.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Assalomu alaykum! Sizni nechada uygʻotish kerakligini yozing?\n*(Misol uchun: 02:00, 06:30)*"
    )
    await state.set_state(AlarmState.waiting_for_time)

@dp.message(AlarmState.waiting_for_time)
async def process_time(message: Message, state: FSMContext):
    await state.update_data(wakeup_time=message.text)
    await message.answer(
        "📝 Rahmat! Endi telefon raqamingiz va ismingizni yozing.\n*(Misol uchun: 9012345678 Muhammadziyo)*"
    )
    await state.set_state(AlarmState.waiting_for_info)

@dp.message(AlarmState.waiting_for_info)
async def process_info(message: Message, state: FSMContext):
    await state.update_data(user_info=message.text)
    await message.answer(
        f"💳 Xizmat faollashishi uchun ixtiyoriy miqdorda to'lov qiling:\n\n"
        f"📌 Karta raqam: `{KARTA_RAQAM}`\n\n"
        f"⚠️ To'lovni amalga oshirgach, **chekni (rasm yoki PDF formatida)** shu yerga yuboring. "
        f"Bot chekni avtomatik tekshiradi.",
        parse_mode="Markdown"
    )
    await state.set_state(AlarmState.waiting_for_payment)

@dp.message(AlarmState.waiting_for_payment, F.photo | F.document)
async def process_payment(message: Message, state: FSMContext):
    await message.answer("🔄 Chek tekshirilmoqda, iltimos kuting...")
    
    file_id = None
    if message.photo:
        file_id = message.photo[-1].file_id  
    elif message.document and (message.document.mime_type.startswith("image/") or message.document.mime_type == "application/pdf"):
        file_id = message.document.file_id

    if not file_id:
        await message.answer("❌ Iltimos, faqat rasm yoki PDF formatidagi chekni yuboring!")
        return

    file = await bot.get_file(file_id)
    destination = f"downloads/{file_id}"
    os.makedirs("downloads", exist_ok=True)
    await bot.download_file(file.path, destination)

    is_valid_chek = False
    qr_data = ""
    try:
        img = Image.open(destination)
        for obj in decode(img):
            qr_data = obj.data.decode("utf-8")
            if any(x in qr_data for x in ["click.uz", "payme.uz", "soliq.uz", "uzumbank"]):
                is_valid_chek = True
                break
    except Exception as e:
        print(f"Xatolik: {e}")

    if os.path.exists(destination):
        os.remove(destination)

    if is_valid_chek:
        user_data = await state.get_data()
        await message.answer(
            f"✅ **To'lov muvaffaqiyatli qabul qilindi!**\n\n"
            f"⏰ Uyg'otish vaqti: {user_data['wakeup_time']}\n"
            f"👤 Ma'lumotlaringiz: {user_data['user_info']}\n\n"
            f"Siz belgilangan vaqtda uyg'otilasiz. Rahmat!"
        )
        
        await bot.send_message(
            ADMIN_ID, 
            f"💰 Yangi to'lov!\n⏰ Soat: {user_data['wakeup_time']}\n👤 User: {user_data['user_info']}\n🔗 QR Link: {qr_data}"
        )
        await state.clear()
    else:
        await message.answer(
            "❌ **Xatolik: Soxta yoki yaroqsiz chek!**\n\n"
            "Tizim ushbu chekda rasmiy to'lov QR-kodini aniqlay olmadi. "
            "Iltimos, Click, Payme yoki Uzum ilovasidan yuklab olingan haqiqiy chekni yuboring."
        )

async def main():
    await asyncio.gather(
        start_web_server(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    asyncio.run(main())
