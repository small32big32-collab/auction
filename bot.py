import os
import asyncio
import logging
import httpx

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from supabase import create_client, Client

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Конфигурация окружения
BOT_TOKEN = os.getenv("BOT_TOKEN", "8877726623:AAEV6YFhuuBnzKWiJZxwiWM49khiaxazwRE")
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://mdursbqpogprwzbhjzxz.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1kdXJzYnFwb2dwcnd6Ymhqenh6Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NzE0MzU5NCwiZXhwIjoyMTAyNzE5NTk0fQ.AXb2IUi3VOY1hNHxrvZUpsk4f6ycGDc2qaC_4zzM1Mo")
API_BASE_URL = os.getenv("API_BASE_URL", "https://auction-production-a352.up.railway.app")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Локальная сессия пользователей для лицензионных ключей
user_sessions = {}

ALL_RARITIES = ["Обычный", "Необычный", "Особый", "Редкий", "Исключительный", "Легендарный"]

class SniperState(StatesGroup):
    waiting_for_license = State()
    waiting_for_item_search = State()
    waiting_for_price = State()


def get_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🎯 Мои снайперы", callback_data="list_snipers"))
    builder.row(InlineKeyboardButton(text="➕ Добавить снайпера", callback_data="add_sniper"))
    return builder.as_markup()


async def fetch_latest_price_from_supabase(item_id: str, rarity: str) -> float | None:
    """Запрашивает свежую минимальную цену предмета прямо из Supabase."""
    try:
        res = (
            supabase.table("price_history")
            .select("min_buyout_price")
            .eq("item_id", item_id)
            .ilike("rarity", rarity)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if res.data and len(res.data) > 0:
            return float(res.data[0]["min_buyout_price"])
    except Exception as e:
        logging.error(f"Ошибка запроса цены из Supabase: {e}")
    return None


@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id

    # Проверка наличия ключа доступа в базе
    res = supabase.table("user_licenses").select("license_key").eq("user_id", user_id).execute()
    if res.data and len(res.data) > 0:
        user_sessions[user_id] = res.data[0]["license_key"]
        await message.answer("👋 **Добро пожаловать в Stalzone Auction Sniper!**", reply_markup=get_main_keyboard(), parse_mode="Markdown")
    else:
        await state.set_state(SniperState.waiting_for_license)
        await message.answer("🔑 **Введите ваш ключ доступа для активации бота:**", parse_mode="Markdown")


@dp.message(SniperState.waiting_for_license)
async def process_license_key(message: types.Message, state: FSMContext):
    license_key = message.text.strip()
    user_id = message.from_user.id

    try:
        res = supabase.table("licenses").select("*").eq("key", license_key).execute()
        if res.data and len(res.data) > 0:
            supabase.table("user_licenses").upsert({"user_id": user_id, "license_key": license_key}).execute()
            user_sessions[user_id] = license_key
            await state.clear()
            await message.answer("✅ **Ключ успешно активирован!**", reply_markup=get_main_keyboard(), parse_mode="Markdown")
        else:
            await message.answer("❌ **Неверный ключ доступа.** Попробуйте ввести еще раз:")
    except Exception as e:
        await message.answer(f"⚠️ Ошибка проверки ключа: {e}")


@dp.callback_query(F.data == "to_main_menu")
async def back_to_main_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("🎯 **Главное меню:**", reply_markup=get_main_keyboard(), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "list_snipers")
async def list_snipers(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    res = supabase.table("user_snipers").select("*").eq("user_id", user_id).execute()
    snipers = res.data or []

    builder = InlineKeyboardBuilder()

    if not snipers:
        text = "🎯 **У вас пока нет активных снайперов.**"
    else:
        text = "🎯 **Ваши активные снайперы:**\n\n"
        for s in snipers:
            text += f"📦 **{s.get('item_name')}** (`{s.get('rarity')}`)\n🎯 Порог: `{float(s.get('threshold', 0)):,.0f} руб.`\n\n"
            builder.row(InlineKeyboardButton(text=f"❌ Удалить {s.get('item_name')}", callback_data=f"del_sniper:{s.get('id')}"))

    builder.row(InlineKeyboardButton(text="➕ Добавить снайпера", callback_data="add_sniper"))
    builder.row(InlineKeyboardButton(text="⬅️ Главное меню", callback_data="to_main_menu"))

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data.startswith("del_sniper:"))
async def delete_sniper(callback: types.CallbackQuery):
    sniper_id = callback.data.split(":")[1]
    supabase.table("user_snipers").delete().eq("id", sniper_id).execute()
    await callback.answer("✅ Снайпер удален!")
    await list_snipers(callback)


@dp.callback_query(F.data == "add_sniper")
async def start_add_sniper(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(SniperState.waiting_for_item_search)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ Отмена", callback_data="to_main_menu"))
    
    await callback.message.edit_text(
        "🔍 **Введите название предмета (или его часть) для поиска:**", 
        reply_markup=builder.as_markup(), 
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.message(SniperState.waiting_for_item_search)
async def search_item_for_sniper(message: types.Message, state: FSMContext):
    query = message.text.strip().lower()
    user_id = message.from_user.id
    license_key = user_sessions.get(user_id)

    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(f"{API_BASE_URL}/items/{license_key}", params={"telegram_id": user_id}, timeout=5.0)
            items = res.json().get("data", [])
            
            # Фильтрация по введенному имени
            matched = [
                i for i in items 
                if query in str(i.get("name", "")).lower() or query in str(i.get("item_id", "")).lower()
            ]

            if not matched:
                await message.answer("❌ Предметы не найдены. Попробуйте ввести другое название:")
                return

            builder = InlineKeyboardBuilder()
            for item in matched[:10]:
                item_id = item.get("item_id") or item.get("id")
                item_name = item.get("name", item_id)
                builder.row(InlineKeyboardButton(text=item_name, callback_data=f"select_item:{item_id}"))

            builder.row(InlineKeyboardButton(text="⬅️ Отмена", callback_data="to_main_menu"))
            await message.answer("📦 **Выберите предмет из списка:**", reply_markup=builder.as_markup(), parse_mode="Markdown")

        except Exception as e:
            await message.answer(f"⚠️ Ошибка поиска: {e}")


@dp.callback_query(F.data.startswith("select_item:"))
async def select_item_rarity(callback: types.CallbackQuery):
    item_id = callback.data.split(":")[1]
    builder = InlineKeyboardBuilder()
    
    for r in ALL_RARITIES:
        builder.row(InlineKeyboardButton(text=r, callback_data=f"setrarity:{item_id}:{r}"))
    
    builder.row(InlineKeyboardButton(text="⬅️ Отмена", callback_data="to_main_menu"))
    await callback.message.edit_text("✨ **Выберите редкость предмета:**", reply_markup=builder.as_markup(), parse_mode="Markdown")
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

    # 1. Попытка получить данные о предмете через бэкенд API
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(f"{API_BASE_URL}/items/{license_key}", params={"telegram_id": user_id}, timeout=5.0)
            items = res.json().get("data", [])
            
            target_key = str(item_id).strip().lower()
            for item in items:
                raw_id = str(item.get("item_id") or item.get("id") or "").strip().lower()
                raw_name = str(item.get("name") or "").strip().lower()
                
                if target_key in (raw_id, raw_name):
                    item_name = item.get("name", item_id)
                    break
        except Exception as e:
            logging.error(f"Ошибка получения имени через API: {e}")

    # 2. Прямой поиск последней сохраненной минимальной цены в Supabase
    min_price = await fetch_latest_price_from_supabase(item_id, rarity)

    price_str = f"{min_price:,.0f} руб." if min_price and min_price > 0 else "Нет данных"

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
async def process_price_and_save_sniper(message: types.Message, state: FSMContext):
    try:
        threshold = float(message.text.strip().replace(" ", "").replace(",", "."))
    except ValueError:
        await message.answer("❌ Пожалуйста, введите корректное число (цена в рублях):")
        return

    data = await state.get_data()
    user_id = message.from_user.id
    item_id = data.get("target_item_id")
    item_name = data.get("target_item_name")
    rarity = data.get("target_rarity")

    payload = {
        "user_id": user_id,
        "item_id": item_id,
        "item_name": item_name,
        "rarity": rarity,
        "threshold": threshold
    }

    try:
        supabase.table("user_snipers").insert(payload).execute()
        await state.clear()
        
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🎯 К снайперам", callback_data="list_snipers"))
        builder.row(InlineKeyboardButton(text="⬅️ Главное меню", callback_data="to_main_menu"))

        await message.answer(
            f"✅ **Снайпер успешно уставил цель!**\n\n"
            f"📦 Предмет: **{item_name}** (`{rarity}`)\n"
            f"🎯 Порог срабатывания: **{threshold:,.0f} руб.**",
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer(f"⚠️ Ошибка сохранения снайпера: {e}")


async def main():
    print("🚀 Бот запущен!", flush=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
