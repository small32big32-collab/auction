import os
import asyncio
import logging
import httpx

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, PreCheckoutQuery

# Логирование
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8877726623:AAEV6YFhuuBnzKWiJZxwiWM49khiaxazwRE")
API_BASE_URL = os.getenv("API_BASE_URL", "https://auction-production-a352.up.railway.app")

# --- Настройки контактов и документов ---
SUPPORT_TGG = "https://t.me/montastaile_life"
SUPPORT_TG = "https://t.me/ungdaddy"
PLATEGA_PAY_URL = "https://platega.com/pay/your_link"
TERMS_URL = "https://telegra.ph/Polzovatelskoe-soglashenie-08-25-64"
PRIVACY_URL = "https://telegra.ph/Politika-konfidencialnosti-08-25-84"

ITEMS_PER_PAGE = 10  # Количество предметов на странице каталога

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- Состояния FSM ---
class AuthState(StatesGroup):
    waiting_for_key = State()

class SniperState(StatesGroup):
    waiting_for_price = State()
    waiting_for_edit_price = State()

user_sessions = {}

# --- Инлайн-клавиатуры ---
def get_buy_options_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Оплатить Telegram Stars", callback_data="buy_stars")],
        [InlineKeyboardButton(text="💳 Оплатить через Platega", url=PLATEGA_PAY_URL)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main_menu")]
    ])

def get_auth_inline_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Купить ключ", callback_data="open_buy_menu")],
        [InlineKeyboardButton(text="💬 Техническая поддержка", url=SUPPORT_TG)],
        [InlineKeyboardButton(text="Канал с новостями", url=SUPPORT_TGG)],
        [InlineKeyboardButton(text="📄 Пользовательское соглашение", url=TERMS_URL)],
        [InlineKeyboardButton(text="🔒 Политика конфиденциальности", url=PRIVACY_URL)]
    ])

def get_main_inline_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📂 Каталог предметов", callback_data="menu_catalog:0")],
        [InlineKeyboardButton(text="🎯 Настроить снайпер цен", callback_data="menu_snipers")],
        [InlineKeyboardButton(text="🛒 Купить ключ", callback_data="open_buy_menu")],
        [InlineKeyboardButton(text="🔑 Сменить ключ", callback_data="menu_change_key")],
        [InlineKeyboardButton(text="💬 Техническая поддержка", url=SUPPORT_TG)],
        [InlineKeyboardButton(text="Канал с новостями", url=SUPPORT_TGG)],
        [InlineKeyboardButton(text="📄 Пользовательское соглашение", url=TERMS_URL)],
        [InlineKeyboardButton(text="🔒 Политика конфиденциальности", url=PRIVACY_URL)]
    ])

def get_rarity_keyboard(item_id: str):
    rarities = [
        ("⚪ Обычный", "Обычный"),
        ("🟢 Необычный", "Необычный"),
        ("🔵 Особый", "Особый"),
        ("🟣 Редкий", "Редкий"),
        ("🔴 Исключительный", "Исключительный"),
        ("🟡 Легендарный", "Легендарный")
    ]
    builder = InlineKeyboardBuilder()
    for label, r_val in rarities:
        builder.button(text=label, callback_data=f"setrarity:{item_id}:{r_val}")
    
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="⬅️ Назад в каталог", callback_data="menu_catalog:0"))
    return builder.as_markup()

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

# --- Старт и авторизация ---
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
            res = await client.get(
                f"{API_BASE_URL}/items/{license_key}", 
                params={"telegram_id": user_id, "limit": 10000}, 
                timeout=10.0
            )
            if res.status_code == 200:
                user_sessions[user_id] = license_key
                await state.clear()
                await send_main_menu(message, text_prefix="✅ **Авторизация успешна!**\n\n")
            elif res.status_code == 403:
                await message.answer(
                    "⛔ **Этот ключ уже привязан к другому Telegram-аккаунту!**\n"
                    "Введите другой ключ или приобретите новый:",
                    reply_markup=get_auth_inline_menu(),
                    parse_mode="Markdown"
                )
            else:
                await message.answer(
                    "❌ **Неверный или просроченный ключ.** Попробуйте ввести другой или купите новый:",
                    reply_markup=get_auth_inline_menu()
                )
        except Exception as e:
            await message.answer(f"⚠️ Ошибка подключения к серверу: {e}")

# --- Оплата ---
@dp.callback_query(F.data == "open_buy_menu")
async def open_buy_menu_handler(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "💳 **Выберите удобный способ оплаты ключа доступа:**\n\n"
        "• **Telegram Stars** — оплата прямо внутри мессенджера.\n"
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

# --- Навигация ---
@dp.callback_query(F.data == "menu_change_key")
async def change_key_callback(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user_sessions.pop(user_id, None)
    await state.set_state(AuthState.waiting_for_key)
    await callback.message.edit_text(
        "🔑 Введите новый ключ доступа:",
        reply_markup=get_auth_inline_menu(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "to_main_menu")
async def to_main_menu_handler(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
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

# --- Каталог и Выбор Предметов (с Пагинацией) ---
@dp.callback_query(F.data.startswith("menu_catalog"))
async def show_catalog_callback(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    license_key = user_sessions.get(user_id)

    if not license_key:
        await callback.answer("⚠️ Сначала введите ключ доступа!", show_alert=True)
        return

    parts = callback.data.split(":")
    page = int(parts[1]) if len(parts) > 1 else 0

    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(
                f"{API_BASE_URL}/items/{license_key}", 
                params={"telegram_id": user_id, "limit": 10000}, 
                timeout=10.0
            )
            items = res.json().get("data", [])
        except Exception as e:
            await callback.message.answer(f"⚠️ Ошибка загрузки каталога: {e}")
            await callback.answer()
            return

    if not items:
        await callback.message.answer("📦 Каталог предметов пуст.")
        await callback.answer()
        return

    unique_items = []
    seen_ids = set()
    for item in items:
        i_id = item.get("item_id") or item.get("id")
        if i_id and i_id not in seen_ids:
            seen_ids.add(i_id)
            unique_items.append((i_id, item.get("name") or item.get("item_name") or i_id))

    total_items = len(unique_items)
    total_pages = max(1, (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    page_items = unique_items[start_idx:end_idx]

    builder = InlineKeyboardBuilder()
    for i_id, name in page_items:
        builder.button(text=f"🔮 {name}", callback_data=f"select_item:{i_id}")

    builder.adjust(1)

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"menu_catalog:{page - 1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"menu_catalog:{page + 1}"))

    if nav_buttons:
        builder.row(*nav_buttons)

    builder.row(InlineKeyboardButton(text="⬅️ В главное меню", callback_data="to_main_menu"))

    page_text = f"📂 **Выберите предмет из каталога (Стр. {page + 1}/{total_pages}):**"
    
    await callback.message.edit_text(page_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("select_item:"))
async def select_item_info(callback: types.CallbackQuery):
    item_id = callback.data.split(":")[1]
    user_id = callback.from_user.id
    license_key = user_sessions.get(user_id)

    item_name = item_id
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(
                f"{API_BASE_URL}/items/{license_key}", 
                params={"telegram_id": user_id, "limit": 10000}, 
                timeout=5.0
            )
            items = res.json().get("data", [])
            target = str(item_id).strip().lower()
            for item in items:
                raw_id = str(item.get("item_id") or item.get("id") or "").strip().lower()
                if raw_id == target:
                    item_name = item.get("name") or item.get("item_name") or item_id
                    break
        except Exception:
            pass

    text = (
        f"🔮 **Предмет:** {item_name}\n\n"
        f"Выберите **редкость** предмета, чтобы узнать текущую цену и настроить снайпер:"
    )

    await callback.message.edit_text(
        text, 
        reply_markup=get_rarity_keyboard(item_id), 
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("setrarity:"))
async def set_rarity_and_ask_price(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    item_id = parts[1]
    rarity = parts[2]
    user_id = callback.from_user.id
    license_key = user_sessions.get(user_id)

    item_name = item_id
    min_price = None

    async with httpx.AsyncClient() as client:
        try:
            # 1. Попытка запросить конкретную цену напрямую с сервера
            res_price = await client.get(
                f"{API_BASE_URL}/items/{item_id}/price",
                params={"rarity": rarity, "license_key": license_key},
                timeout=5.0
            )
            if res_price.status_code == 200:
                p_data = res_price.json()
                min_price = p_data.get("min_price") or p_data.get("min_buyout_price")
                item_name = p_data.get("item_name") or item_name
            else:
                # 2. Резервный поиск по всем объектам истории/предметов
                res = await client.get(
                    f"{API_BASE_URL}/items/{license_key}", 
                    params={"telegram_id": user_id, "limit": 10000}, 
                    timeout=5.0
                )
                if res.status_code == 200:
                    items = res.json().get("data", [])
                    target_id = str(item_id).strip().lower()
                    target_rarity = str(rarity).strip().lower()

                    for item in items:
                        raw_id = str(item.get("item_id") or item.get("id") or "").strip().lower()
                        raw_rarity = str(item.get("rarity") or "").strip().lower()

                        if raw_id == target_id:
                            item_name = item.get("name") or item.get("item_name") or item_name
                            price_val = item.get("min_buyout_price") or item.get("min_price") or item.get("price")
                            
                            if raw_rarity == target_rarity and price_val is not None:
                                min_price = price_val
                                break
                            elif min_price is None and price_val is not None:
                                min_price = price_val
        except Exception as e:
            logging.error(f"Ошибка получения цен: {e}")

    price_str = f"{float(min_price):,.0f} руб." if min_price and float(min_price) > 0 else "Нет данных"

    await state.update_data(target_item_id=item_id, target_item_name=item_name, target_rarity=rarity)
    await state.set_state(SniperState.waiting_for_price)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ Отмена (в главное меню)", callback_data="to_main_menu"))

    await callback.message.edit_text(
        f"🎯 Выбран предмет: **{item_name}**\n"
        f"Редкость: **{rarity}**\n"
        f"💰 **Текущая минимальная цена:** `{price_str}`\n\n"
        f"Введите **максимальную цену в рублях**, при которой бот должен прислать уведомление:",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.message(SniperState.waiting_for_price)
async def set_sniper_price(message: types.Message, state: FSMContext):
    clean_text = message.text.replace(" ", "").replace(",", "")
    try:
        price = float(clean_text)
    except ValueError:
        await message.answer("⚠️ Пожалуйста, введите корректное число.")
        return

    user_id = message.from_user.id
    license_key = user_sessions.get(user_id)
    data = await state.get_data()

    item_name = data.get("target_item_name", data["target_item_id"])

    payload = {
        "user_id": user_id,
        "license_key": license_key,
        "item_id": data["target_item_id"],
        "item_name": item_name,
        "rarity": data["target_rarity"],
        "threshold": price
    }

    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(f"{API_BASE_URL}/snipers", json=payload, timeout=5.0)
            if res.status_code == 200:
                await message.answer(
                    f"✅ **Снайпер установлен!**\n"
                    f"Предмет: **{item_name}** ({data['target_rarity']})\n"
                    f"Порог цены: **{price:,.0f} руб.**", 
                    parse_mode="Markdown"
                )
                await send_main_menu(message)
            else:
                await message.answer("❌ Ошибка сохранения снайпера.")
        except Exception as e:
            await message.answer(f"⚠️ Ошибка сети: {e}")

    await state.clear()

# --- Снайперы ---
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
    await callback.message.edit_text("🎯 **Ваши снайперы:**", reply_markup=builder.as_markup(), parse_mode="Markdown")
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

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ Отмена", callback_data="menu_snipers"))

    await callback.message.edit_text("✏️ Введите новую цену в рублях (например: `350000`):", reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()

@dp.message(SniperState.waiting_for_edit_price)
async def process_new_price(message: types.Message, state: FSMContext):
    clean_text = message.text.replace(" ", "").replace(",", "")

    try:
        new_price = float(clean_text)
    except ValueError:
        await message.answer("⚠️ Пожалуйста, введите корректное число.")
        return

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
    print("🚀 Запуск Telegram-бота Stalzone...", flush=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
