import os
import asyncio
import httpx
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, PreCheckoutQuery

BOT_TOKEN = os.getenv("BOT_TOKEN", "8877726623:AAEV6YFhuuBnzKWiJZxwiWM49khiaxazwRE")
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api/v1")

# --- Настройки контактов и документов ---
SUPPORT_TG = "https://t.me/ungdaddy"
PLATEGA_PAY_URL = "https://platega.com/pay/your_link"
TERMS_URL = "https://example.com/terms"
PRIVACY_URL = "https://example.com/privacy"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- Состояния FSM ---
class AuthState(StatesGroup):
    waiting_for_key = State()

class SniperState(StatesGroup):
    waiting_for_price = State()
    waiting_for_edit_price = State()

user_sessions = {}

# --- Инлайн-клавиатура оплаты ---
def get_buy_options_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Оплатить Telegram Stars", callback_data="buy_stars")],
        [InlineKeyboardButton(text="💳 Оплатить через Platega", url=PLATEGA_PAY_URL)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main_menu")]
    ])

# --- Меню авторизации (до ввода ключа) ---
def get_auth_inline_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Купить ключ", callback_data="open_buy_menu")],
        [InlineKeyboardButton(text="💬 Техническая поддержка", url=SUPPORT_TG)],
        [InlineKeyboardButton(text="📄 Пользовательское соглашение", url=TERMS_URL)],
        [InlineKeyboardButton(text="🔒 Политика конфиденциальности", url=PRIVACY_URL)]
    ])

# --- Главное Inline-меню (после авторизации) ---
def get_main_inline_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📂 Каталог предметов", callback_data="menu_catalog")],
        [InlineKeyboardButton(text="🎯 Настроить снайпер цен", callback_data="menu_snipers")],
        [InlineKeyboardButton(text="🛒 Купить ключ", callback_data="open_buy_menu")],
        [InlineKeyboardButton(text="🔑 Сменить ключ", callback_data="menu_change_key")],
        [InlineKeyboardButton(text="💬 Техническая поддержка", url=SUPPORT_TG)],
        [InlineKeyboardButton(text="📄 Пользовательское соглашение", url=TERMS_URL)],
        [InlineKeyboardButton(text="🔒 Политика конфиденциальности", url=PRIVACY_URL)]
    ])

async def send_main_menu(message_or_callback, text_prefix=""):
    text = (
        f"{text_prefix}"
        "👋 **Stalzone Auction Bot**\n\n"
        "Добро пожаловать! Инструмент для мониторинга и анализа цен аукциона артефактов.\n"
        "Выберите нужный пункт меню ниже:"
    )
    markup = get_main_inline_menu()
    
    if isinstance(message_or_callback, types.CallbackQuery):
        await message_or_callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    else:
        await message_or_callback.answer(text, reply_markup=markup, parse_mode="Markdown")

# --- Старт и проверка авторизации ---
@dp.message(CommandStart())
async def start_cmd(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id in user_sessions:
        await send_main_menu(message)
        return

    await state.set_state(AuthState.waiting_for_key)
    await message.answer(
        "🔑 **Авторизация в Stalzone**\n\n"
        "Пожалуйста, введите ваш ключ доступа.\n"
        "Если у вас нет ключа, вы можете приобрести его по кнопке ниже:",
        reply_markup=get_auth_inline_menu(),
        parse_mode="Markdown"
    )

@dp.message(AuthState.waiting_for_key)
async def process_license_key(message: types.Message, state: FSMContext):
    license_key = message.text.strip()
    user_id = message.from_user.id

    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(f"{API_BASE_URL}/items/{license_key}", timeout=5.0)
            if res.status_code == 200:
                user_sessions[user_id] = license_key
                await state.clear()
                await send_main_menu(message, text_prefix="✅ **Авторизация успешна!**\n\n")
            else:
                await message.answer(
                    "❌ **Неверный или просроченный ключ.** Попробуйте ввести другой или купите новый:",
                    reply_markup=get_auth_inline_menu()
                )
        except Exception as e:
            await message.answer(f"⚠️ Ошибка подключения к серверу: {e}")

# --- Покупка ключей и платежные шлюзы ---
@dp.callback_query(F.data == "open_buy_menu")
async def open_buy_menu_handler(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "💳 **Выберите удобный способ оплаты ключа доступа:**\n\n"
        "• **Telegram Stars** — быстрая оплата внутри мессенджера.\n"
        "• **Platega** — оплата банковскими картами и СБП.",
        reply_markup=get_buy_options_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "buy_stars")
async def send_stars_invoice(callback: types.CallbackQuery):
    prices = [LabeledPrice(label="Лицензионный ключ (30 дней)", amount=250)]
    await callback.message.answer_invoice(
        title="Ключ доступа Stalzone",
        description="Подписка на мониторинг аукциона на 30 дней",
        payload="license_key_30_days",
        currency="XTR",
        prices=prices
    )
    await callback.answer()

@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def successful_payment_handler(message: types.Message):
    new_key = "STALZONE-STARS-KEY-DEMO"
    await message.answer(
        f"🎉 **Оплата успешно завершена!**\n\n"
        f"Ваш ключ доступа: `{new_key}`\n\n"
        f"Отправьте этот ключ в чат для активации доступа.",
        parse_mode="Markdown"
    )

# --- Управление аккаунтом и навигация ---
@dp.callback_query(F.data == "menu_change_key")
async def change_key_callback(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user_sessions.pop(user_id, None)
    await state.set_state(AuthState.waiting_for_key)
    await callback.message.answer(
        "🔑 Введите новый ключ доступа:",
        reply_markup=get_auth_inline_menu(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "to_main_menu")
async def to_main_menu_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in user_sessions:
        await callback.message.edit_text(
            "🔑 **Авторизация в Stalzone**\n\nПожалуйста, введите ваш ключ доступа:",
            reply_markup=get_auth_inline_menu(),
            parse_mode="Markdown"
        )
    else:
        await send_main_menu(callback)
    await callback.answer()

# --- Логика Каталога ---
@dp.callback_query(F.data == "menu_catalog")
async def show_catalog_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    license_key = user_sessions.get(user_id)

    if not license_key:
        await callback.answer("⚠️ Сначала введите ключ доступа!", show_alert=True)
        return

    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(f"{API_BASE_URL}/items/{license_key}", timeout=5.0)
            items = res.json().get("data", [])
        except Exception as e:
            await callback.message.answer(f"⚠️ Ошибка загрузки каталога: {e}")
            await callback.answer()
            return

    if not items:
        await callback.message.answer("📦 Каталог предметов пуст.")
        await callback.answer()
        return

    builder = InlineKeyboardBuilder()
    for item in items[:20]:
        i_id = item["item_id"]
        name = item.get("name", i_id)
        rarity = item.get("rarity", "Обычный")
        builder.button(text=f"{name} ({rarity})", callback_data=f"add_sniper_{i_id}_{rarity}")

    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="⬅️ В главное меню", callback_data="to_main_menu"))
    await callback.message.edit_text("📂 **Выберите предмет из каталога:**", reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("add_sniper_"))
async def select_item_for_sniper(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    item_id = parts[2]
    rarity = parts[3] if len(parts) > 3 else "Обычный"

    await state.update_data(target_item_id=item_id, target_rarity=rarity)
    await state.set_state(SniperState.waiting_for_price)

    await callback.message.answer(f"🎯 Выбран предмет: `{item_id}` ({rarity}).\n\nВведите **максимальную цену в рублях**:", parse_mode="Markdown")
    await callback.answer()

@dp.message(SniperState.waiting_for_price)
async def set_sniper_price(message: types.Message, state: FSMContext):
    clean_text = message.text.replace(" ", "").replace(",", "")
    if not clean_text.isdigit():
        await message.answer("⚠️ Пожалуйста, введите корректное число.")
        return

    price = float(clean_text)
    user_id = message.from_user.id
    license_key = user_sessions.get(user_id)
    data = await state.get_data()

    payload = {
        "user_id": user_id,
        "license_key": license_key,
        "item_id": data["target_item_id"],
        "item_name": data["target_item_id"],
        "rarity": data["target_rarity"],
        "threshold": price
    }

    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(f"{API_BASE_URL}/snipers", json=payload, timeout=5.0)
            if res.status_code == 200:
                await message.answer(f"✅ **Снайпер установлен!**\nПредмет: `{data['target_item_id']}`\nЦена: **{price:,.0f} руб.**", parse_mode="Markdown")
                await send_main_menu(message)
            else:
                await message.answer("❌ Ошибка сохранения снайпера.")
        except Exception as e:
            await message.answer(f"⚠️ Ошибка сети: {e}")

    await state.clear()

# --- Логика Снайперов ---
@dp.callback_query(F.data == "menu_snipers")
async def show_user_snipers_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(f"{API_BASE_URL}/snipers/{user_id}", timeout=5.0)
            snipers = res.json().get("data", [])
        except Exception as e:
            await callback.message.answer(f"⚠️ Ошибка получения снайперов: {e}")
            await callback.answer()
            return

    if not snipers:
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ В главное меню", callback_data="to_main_menu")
        await callback.message.edit_text("🎯 У вас нет активных снайперов.", reply_markup=builder.as_markup())
        await callback.answer()
        return

    builder = InlineKeyboardBuilder()
    for s in snipers:
        s_id = s["id"]
        name = s.get("item_name", s.get("item_id", "Предмет"))
        rarity = s.get("rarity", "Обычный")
        price = float(s.get("threshold", 0))
        builder.button(text=f"📦 {name} ({rarity}) — до {price:,.0f} руб.", callback_data=f"manage_sniper_{s_id}")

    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(text="❌ Удалить все", callback_data="delete_all_snipers"),
        InlineKeyboardButton(text="⬅️ Главное меню", callback_data="to_main_menu")
    )
    await callback.message.edit_text("🎯 **Ваши снайперы:**\n\nНажмите на снайпер для управления:", reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("manage_sniper_"))
async def manage_sniper_menu(callback: types.CallbackQuery):
    sniper_id = callback.data.split("_")[-1]

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Изменить цену", callback_data=f"edit_price_{sniper_id}"),
            InlineKeyboardButton(text="🗑 Удалить снайпер", callback_data=f"delete_single_{sniper_id}")
        ],
        [InlineKeyboardButton(text="⬅️ Назад к списку", callback_data="menu_snipers")]
    ])

    await callback.message.edit_text("⚙️ **Выберите действие:**", reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("delete_single_"))
async def delete_single_sniper_handler(callback: types.CallbackQuery):
    sniper_id = callback.data.split("_")[-1]

    async with httpx.AsyncClient() as client:
        await client.delete(f"{API_BASE_URL}/snipers/single/{sniper_id}")

    await callback.answer("✅ Снайпер удален!", show_alert=True)
    await show_user_snipers_callback(callback)

@dp.callback_query(F.data == "delete_all_snipers")
async def delete_all_snipers_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    async with httpx.AsyncClient() as client:
        await client.delete(f"{API_BASE_URL}/snipers/{user_id}")

    await callback.answer("✅ Все снайперы удалены!", show_alert=True)
    await send_main_menu(callback)

@dp.callback_query(F.data.startswith("edit_price_"))
async def edit_price_start(callback: types.CallbackQuery, state: FSMContext):
    sniper_id = callback.data.split("_")[-1]
    await state.update_data(editing_sniper_id=sniper_id)
    await state.set_state(SniperState.waiting_for_edit_price)

    await callback.message.answer("✏️ Введите новую цену в рублях (например: `350000`):", parse_mode="Markdown")
    await callback.answer()

@dp.message(SniperState.waiting_for_edit_price)
async def process_new_price(message: types.Message, state: FSMContext):
    clean_text = message.text.replace(" ", "").replace(",", "")

    if not clean_text.isdigit():
        await message.answer("⚠️ Пожалуйста, введите число.")
        return

    new_price = float(clean_text)
    data = await state.get_data()
    sniper_id = data.get("editing_sniper_id")

    async with httpx.AsyncClient() as client:
        await client.patch(
            f"{API_BASE_URL}/snipers/{sniper_id}",
            json={"threshold": new_price}
        )

    await state.clear()
    await message.answer(f"✅ Цена обновлена: **{new_price:,.0f} руб.**", parse_mode="Markdown")
    await send_main_menu(message)

# --- Точка входа ---
async def main():
    print("🚀 Запуск Telegram-бота Stalzone...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
