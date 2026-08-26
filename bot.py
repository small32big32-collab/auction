import os
import asyncio
import httpx
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

BOT_TOKEN = os.getenv("BOT_TOKEN", "8877726623:AAEV6YFhuuBnzKWiJZxwiWM49khiaxazwRE")
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api/v1")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- Состояния FSM ---
class AuthState(StatesGroup):
    waiting_for_key = State()

class SniperState(StatesGroup):
    waiting_for_price = State()
    waiting_for_edit_price = State()

# Временное хранение сессий авторизованных пользователей в памяти
user_sessions = {}

# --- Клавиатуры ---
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🎯 Мои снайперы")
    builder.button(text="📦 Каталог предметов")
    builder.button(text="🔑 Сменить ключ")
    builder.adjust(2, 1)
    return builder.as_markup(resize_keyboard=True)

# --- Старт и Авторизация ---
@dp.message(CommandStart())
async def start_cmd(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id in user_sessions:
        await message.answer("👋 С возвращением в **Stalzone Sniper Bot**!", reply_markup=get_main_keyboard(), parse_mode="Markdown")
        return

    await state.set_state(AuthState.waiting_for_key)
    await message.answer("🔑 **Авторизация в Stalzone**\n\nПожалуйста, введите ваш ключ доступа:", parse_mode="Markdown")

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
                await message.answer("✅ **Авторизация успешна!** Добро пожаловать.", reply_markup=get_main_keyboard(), parse_mode="Markdown")
            else:
                await message.answer("❌ **Неверный или просроченный ключ.** Попробуйте ввести другой:")
        except Exception as e:
            await message.answer(f"⚠️ Ошибка подключения к серверу: {e}")

@dp.message(F.text == "🔑 Сменить ключ")
async def change_key_cmd(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_sessions.pop(user_id, None)
    await state.set_state(AuthState.waiting_for_key)
    await message.answer("🔑 Введите новый ключ доступа:", parse_mode="Markdown")

# --- Каталог и Создание Снайпера ---
@dp.message(F.text == "📦 Каталог предметов")
async def show_catalog(message: types.Message):
    user_id = message.from_user.id
    license_key = user_sessions.get(user_id)

    if not license_key:
        await message.answer("⚠️ Вы не авторизованы. Отправьте /start для ввода ключа.")
        return

    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(f"{API_BASE_URL}/items/{license_key}", timeout=5.0)
            items = res.json().get("data", [])
        except Exception as e:
            await message.answer(f"⚠️ Ошибка загрузки каталога: {e}")
            return

    if not items:
        await message.answer("📦 Каталог предметов пуст.")
        return

    builder = InlineKeyboardBuilder()
    # Ограничиваем первыми 20 предметами для компактности
    for item in items[:20]:
        i_id = item["item_id"]
        name = item.get("name", i_id)
        rarity = item.get("rarity", "Обычный")
        builder.button(text=f"{name} ({rarity})", callback_data=f"add_sniper_{i_id}_{rarity}")

    builder.adjust(1)
    await message.answer("📦 **Выберите предмет из списка для установки снайпера:**", reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("add_sniper_"))
async def select_item_for_sniper(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    item_id = parts[2]
    rarity = parts[3] if len(parts) > 3 else "Обычный"

    await state.update_data(target_item_id=item_id, target_rarity=rarity)
    await state.set_state(SniperState.waiting_for_price)

    await callback.message.answer(f"🎯 Выбран предмет: `{item_id}` (`{rarity}`).\n\nВведите **максимальную цену в рублях**, при которой присылать уведомление:", parse_mode="Markdown")
    await callback.answer()

@dp.message(SniperState.waiting_for_price)
async def set_sniper_price(message: types.Message, state: FSMContext):
    clean_text = message.text.replace(" ", "").replace(",", "")
    if not clean_text.isdigit():
        await message.answer("⚠️ Пожалуйста, введите корректную сумму числом.")
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
                await message.answer(f"✅ **Снайпер успешно уставителен!**\n\nПредмет: `{data['target_item_id']}`\nЦелевая цена: **{price:,.0f} руб.**", reply_markup=get_main_keyboard(), parse_mode="Markdown")
            else:
                await message.answer("❌ Ошибка сохранения снайпера на сервере.")
        except Exception as e:
            await message.answer(f"⚠️ Ошибка соединения: {e}")

    await state.clear()

# --- Мои Снайперы (Интерактивный Список) ---
@dp.message(F.text == "🎯 Мои снайперы")
async def show_user_snipers(message: types.Message):
    user_id = message.from_user.id

    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(f"{API_BASE_URL}/snipers/{user_id}", timeout=5.0)
            snipers = res.json().get("data", [])
        except Exception as e:
            await message.answer(f"⚠️ Ошибка получения снайперов: {e}")
            return

    if not snipers:
        await message.answer("🎯 У вас нет активных снайперов.", reply_markup=get_main_keyboard())
        return

    builder = InlineKeyboardBuilder()

    for s in snipers:
        s_id = s["id"]
        name = s.get("item_name", s.get("item_id", "Предмет"))
        rarity = s.get("rarity", "Обычный")
        price = float(s.get("threshold", 0))

        btn_text = f"📦 {name} ({rarity}) — до {price:,.0f} руб."
        builder.button(text=btn_text, callback_data=f"manage_sniper_{s_id}")

    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(text="❌ Удалить все", callback_data="delete_all_snipers"),
        InlineKeyboardButton(text="⬅️ Главное меню", callback_data="to_main_menu")
    )

    await message.answer("🎯 **Ваши активные снайперы:**\n\nНажмите на предмет для изменения цены или удаления:", reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("manage_sniper_"))
async def manage_sniper_menu(callback: types.CallbackQuery):
    sniper_id = callback.data.split("_")[-1]

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Изменить цену", callback_data=f"edit_price_{sniper_id}"),
            InlineKeyboardButton(text="🗑 Удалить снайпер", callback_data=f"delete_single_{sniper_id}")
        ],
        [InlineKeyboardButton(text="⬅️ Назад к списку", callback_data="back_to_snipers")]
    ])

    await callback.message.edit_text("⚙️ **Выберите действие для снайпера:**", reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "back_to_snipers")
async def back_to_snipers_handler(callback: types.CallbackQuery):
    await callback.message.delete()
    await show_user_snipers(callback.message)

@dp.callback_query(F.data.startswith("delete_single_"))
async def delete_single_sniper_handler(callback: types.CallbackQuery):
    sniper_id = callback.data.split("_")[-1]

    async with httpx.AsyncClient() as client:
        await client.delete(f"{API_BASE_URL}/snipers/single/{sniper_id}")

    await callback.answer("✅ Снайпер успешно удален!", show_alert=True)
    await callback.message.delete()
    await show_user_snipers(callback.message)

@dp.callback_query(F.data == "delete_all_snipers")
async def delete_all_snipers_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    async with httpx.AsyncClient() as client:
        await client.delete(f"{API_BASE_URL}/snipers/{user_id}")

    await callback.answer("✅ Все снайперы удалены!", show_alert=True)
    await callback.message.edit_text("🎯 Все ваши снайперы очищены.")

@dp.callback_query(F.data.startswith("edit_price_"))
async def edit_price_start(callback: types.CallbackQuery, state: FSMContext):
    sniper_id = callback.data.split("_")[-1]
    await state.update_data(editing_sniper_id=sniper_id)
    await state.set_state(SniperState.waiting_for_edit_price)

    await callback.message.answer("✏️ Введите новую пороговую цену в рублях (например: `350000`):", parse_mode="Markdown")
    await callback.answer()

@dp.message(SniperState.waiting_for_edit_price)
async def process_new_price(message: types.Message, state: FSMContext):
    clean_text = message.text.replace(" ", "").replace(",", "")

    if not clean_text.isdigit():
        await message.answer("⚠️ Введите число.")
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
    await message.answer(f"✅ Новая пороговая цена: **{new_price:,.0f} руб.**", parse_mode="Markdown")
    await show_user_snipers(message)

@dp.callback_query(F.data == "to_main_menu")
async def to_main_menu_handler(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("🏠 Главное меню:", reply_markup=get_main_keyboard())

async def main():
    print("🚀 Запуск Telegram-бота...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
