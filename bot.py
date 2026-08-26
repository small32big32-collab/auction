import os
import asyncio
import uuid
import httpx
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import LabeledPrice
from aiogram.utils.keyboard import InlineKeyboardBuilder

BOT_TOKEN = os.getenv("BOT_TOKEN", "8877726623:AAEV6YFhuuBnzKWiJZxwiWM49khiaxazwRE")
API_BASE_URL = os.getenv("API_BASE_URL", "https://server-auth-7cw9.onrender.com/api/login")
PLATEGA_API_KEY = os.getenv("PLATEGA_API_KEY", "your_platega_api_key_here")
PLATEGA_API_URL = os.getenv("PLATEGA_API_URL", "https://api.platega.com/v1/payment")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

CATEGORY_NAMES = {
    "artifacts": "Артефакты",
    "Артефакт": "Артефакты",
}

class UserSession(StatesGroup):
    waiting_for_key = State()
    in_menu = State()
    waiting_invoice = State()
    waiting_for_sniper_threshold = State()


async def show_main_menu(message_or_callback, edit=False, has_key=False):
    builder = InlineKeyboardBuilder()
    
    if has_key:
        builder.button(text="📂 Каталог предметов", callback_data="back_to_cats")
        builder.button(text="🎯 Настроить снайпер цен", callback_data="sniper_menu")
        builder.button(text="🔑 Сменить ключ", callback_data="start_enter_key")
        builder.button(text="💬 Техническая поддержка", url="https://t.me/ungdaddy")
        builder.button(text="📄 Пользовательское соглашение", url="https://telegra.ph/Polzovatelskoe-soglashenie-08-25-64")
        builder.button(text="🔒 Политика конфиденциальности", url="https://telegra.ph/Politika-konfidencialnosti-08-25-84")
    else:
        builder.button(text="💳 Купить доступ (Тарифы)", callback_data="about_tariffs")
        builder.button(text="🔑 Ввести ключ", callback_data="start_enter_key")
        builder.button(text="💬 Техническая поддержка", url="https://t.me/ungdaddy")
        builder.button(text="📄 Пользовательское соглашение", url="https://telegra.ph/Polzovatelskoe-soglashenie-08-25-64")
        builder.button(text="🔒 Политика конфиденциальности", url="https://telegra.ph/Politika-konfidencialnosti-08-25-84")
    
    builder.adjust(1)

    text = (
        "👋 **Stalzone Auction Bot**\n\n"
        "Добро пожаловать! Инструмент для мониторинга и анализа цен аукциона артефактов.\n"
        "Выберите нужный пункт меню ниже:"
    )
    
    if edit:
        await message_or_callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    else:
        await message_or_callback.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    data = await state.get_data()
    license_key = data.get("license_key")
    if license_key:
        await state.set_state(UserSession.in_menu)
        await show_main_menu(message, edit=False, has_key=True)
    else:
        await state.clear()
        await show_main_menu(message, edit=False, has_key=False)


@dp.message(Command("key"))
async def cmd_key(message: types.Message, state: FSMContext):
    data = await state.get_data()
    license_key = data.get("license_key")
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад в меню", callback_data="back_to_main")
    builder.adjust(1)
    await message.answer("🔑 Введите ваш лицензионный ключ:", reply_markup=builder.as_markup())
    await state.set_state(UserSession.waiting_for_key)
    if license_key:
        await state.update_data(license_key=license_key)


@dp.callback_query(F.data == "start_enter_key")
async def process_start_enter_key(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    license_key = data.get("license_key")
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад в меню", callback_data="back_to_main")
    builder.adjust(1)
    await callback.message.edit_text("🔑 Введите ваш лицензионный ключ:", reply_markup=builder.as_markup())
    await state.set_state(UserSession.waiting_for_key)
    if license_key:
        await state.update_data(license_key=license_key)
    await callback.answer()


@dp.callback_query(F.data == "back_to_main")
async def process_back_to_main(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    license_key = data.get("license_key")
    has_key = bool(license_key)

    if has_key:
        await state.set_state(UserSession.in_menu)

    try:
        await callback.message.delete()
    except Exception:
        pass
    
    await show_main_menu(callback.message, edit=False, has_key=has_key)
    await callback.answer()


@dp.callback_query(F.data == "about_tariffs")
async def process_about_tariffs(callback: types.CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Оплатить через Platega (299 руб.)", callback_data="buy_platega")
    builder.button(text="⭐ Оплатить через Telegram Stars (150 звёзд)", callback_data="buy_stars")
    builder.button(text="⬅️ Назад в меню", callback_data="back_to_main")
    builder.adjust(1)

    text = (
        "📋 **Информация о покупке и тарифы**\n\n"
        "Лицензионный доступ на 30 дней."
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()


@dp.message(UserSession.waiting_for_key)
async def process_key_input(message: types.Message, state: FSMContext):
    license_key = message.text.strip()
    url = f"{API_BASE_URL}/items/{license_key}"

    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(url)
            if res.status_code == 200:
                await state.update_data(license_key=license_key)
                await state.set_state(UserSession.in_menu)
                await message.answer("✅ Ключ принят!")
                await show_main_menu(message, edit=False, has_key=True)
            else:
                builder = InlineKeyboardBuilder()
                builder.button(text="⬅️ Назад в меню", callback_data="back_to_main")
                await message.answer("❌ Неверный или просроченный ключ. Попробуйте еще раз:", reply_markup=builder.as_markup())
        except Exception as e:
            await message.answer(f"⚠️ Ошибка сервера: {e}")


async def show_categories(message_or_callback, license_key: str, edit=False):
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(f"{API_BASE_URL}/items/{license_key}")
            if res.status_code == 200:
                items = res.json().get("data", [])
                raw_categories = list(set(i.get("category", "Разное") for i in items))

                builder = InlineKeyboardBuilder()
                for cat in raw_categories:
                    display_name = CATEGORY_NAMES.get(cat, cat)
                    builder.button(text=f"📁 {display_name}", callback_data=f"cat_{cat}")
                
                builder.button(text="⬅️ В главное меню", callback_data="back_to_main")
                builder.adjust(1)

                text = "📂 **Выберите категорию:**"
                if edit:
                    await message_or_callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
                else:
                    await message_or_callback.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        except Exception as e:
            print(f"Error: {e}")


@dp.callback_query(F.data == "back_to_cats")
async def process_back_to_cats(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    license_key = data.get("license_key")
    if license_key:
        await show_categories(callback, license_key, edit=True)
    await callback.answer()


@dp.callback_query(F.data.startswith("cat_"))
async def process_category_click(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    license_key = data.get("license_key")
    category_name = callback.data.replace("cat_", "")

    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(f"{API_BASE_URL}/items/{license_key}")
            if res.status_code == 200:
                items = res.json().get("data", [])
                filtered_items = [i for i in items if i.get("category", "Разное") == category_name]

                unique_items = {}
                for item in filtered_items:
                    name = item.get("name")
                    item_id = item.get("item_id")
                    if name and item_id and name not in unique_items:
                        unique_items[name] = item_id

                builder = InlineKeyboardBuilder()
                for name, item_id in unique_items.items():
                    builder.button(text=f"📦 {name}", callback_data=f"item_{item_id}")
                builder.adjust(1)
                builder.row(types.InlineKeyboardButton(text="⬅️ Назад к категориям", callback_data="back_to_cats"))

                display_cat = CATEGORY_NAMES.get(category_name, category_name)
                await callback.message.edit_text(f"📦 **Категория: {display_cat}**\nВыберите предмет:", reply_markup=builder.as_markup(), parse_mode="Markdown")
        except Exception as e:
            await callback.answer(f"Ошибка: {e}")
    await callback.answer()


@dp.callback_query(F.data.startswith("item_"))
async def process_item_click(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    license_key = data.get("license_key")
    item_id = callback.data.replace("item_", "")

    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(f"{API_BASE_URL}/history/{license_key}/{item_id}")
            if res.status_code == 200:
                history_data = res.json().get("data", [])
                if not history_data:
                    await callback.message.answer("Предмет не найден.")
                    await callback.answer()
                    return

                item_name = history_data[0].get("item_name", item_id)
                rarities = list(set(i.get("rarity", "Обычный") for i in history_data))

                builder = InlineKeyboardBuilder()
                for rarity in rarities:
                    builder.button(text=f"✨ {rarity}", callback_data=f"rarity_{item_id}_{rarity}")
                builder.button(text="⬅️ Назад к категориям", callback_data="back_to_cats")
                builder.adjust(1)

                await callback.message.edit_text(f"📦 **{item_name}**\n\nВыберите редкость:", reply_markup=builder.as_markup(), parse_mode="Markdown")
        except Exception as e:
            await callback.message.answer(f"Ошибка: {e}")
    await callback.answer()


@dp.callback_query(F.data.startswith("rarity_"))
async def process_rarity_click(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    license_key = data.get("license_key")
    parts = callback.data.replace("rarity_", "", 1).rsplit("_", 1)
    item_id, selected_rarity = parts[0], parts[1]

    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(f"{API_BASE_URL}/history/{license_key}/{item_id}")
            if res.status_code == 200:
                history_data = res.json().get("data", [])
                filtered = [i for i in history_data if i.get("rarity") == selected_rarity]
                if not filtered:
                    await callback.answer("Нет данных.")
                    return

                item_name = filtered[0].get("item_name", item_id)
                
                latest_record = filtered[-1]
                min_price = latest_record.get("min_buyout_price") or latest_record.get("min_price")
                total_lots = latest_record.get("total_lots", 0)

                price_str = f"{min_price:,.0f} руб." if min_price is not None else "Нет данных"
                lots_str = f"{total_lots} шт." if total_lots else "0 шт."

                builder = InlineKeyboardBuilder()
                builder.button(text="🎯 Поставить снайпер на эту редкость", callback_data=f"set_sniper_{item_id}_{selected_rarity}")
                builder.button(text="⬅️ Назад к выбору редкости", callback_data=f"item_{item_id}")
                builder.adjust(1)

                text = (
                    f"📊 **{item_name}** (`{selected_rarity}`)\n\n"
                    f"💰 Последняя мин. цена: **{price_str}**\n"
                    f"📦 Лотов в наличии: **{lots_str}**\n\n"
                    f"Нажмите кнопку ниже для настройки снайпера."
                )

                await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        except Exception as e:
            await callback.message.answer(f"Ошибка: {e}")
    await callback.answer()


@dp.callback_query(F.data.startswith("set_sniper_"))
async def process_set_sniper(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.replace("set_sniper_", "", 1).rsplit("_", 1)
    item_id, selected_rarity = parts[0], parts[1]
    data = await state.get_data()
    license_key = data.get("license_key")

    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(f"{API_BASE_URL}/history/{license_key}/{item_id}")
            history_data = res.json().get("data", []) if res.status_code == 200 else []
            item_name = history_data[0].get("item_name", item_id) if history_data else item_id
        except Exception:
            item_name = item_id

    await state.update_data(sniper_item_id=item_id, sniper_item_name=item_name, sniper_rarity=selected_rarity)
    await state.set_state(UserSession.waiting_for_sniper_threshold)

    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ В главное меню", callback_data="back_to_main")
    builder.adjust(1)

    await callback.message.edit_text(f"🎯 **Настройка снайпера для:** `{item_name}` (`{selected_rarity}`)\n\nВведите желаемую максимальную цену:", reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()


@dp.message(UserSession.waiting_for_sniper_threshold)
async def process_sniper_threshold_input(message: types.Message, state: FSMContext):
    try:
        threshold = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("❌ Введите корректное число:")
        return

    data = await state.get_data()
    user_id = message.from_user.id  # Числовой int для int8 в Supabase
    license_key = data.get("license_key")

    payload = {
        "user_id": user_id,
        "license_key": license_key,
        "item_id": data.get("sniper_item_id"),
        "item_name": data.get("sniper_item_name"),
        "rarity": data.get("sniper_rarity"),
        "threshold": threshold
    }

    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(f"{API_BASE_URL}/snipers", json=payload)
            print(f"Ответ API сохранения снайпера: {res.status_code} {res.text}")
        except Exception as e:
            print(f"Ошибка сохранения снайпера в БД: {e}")

    await state.set_state(UserSession.in_menu)
    await state.update_data(
        license_key=license_key,
        sniper_item_id=None,
        sniper_item_name=None,
        sniper_rarity=None
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="📂 В каталог", callback_data="back_to_cats")
    builder.button(text="🏠 Главное меню", callback_data="back_to_main")
    builder.adjust(1)

    await message.answer(f"✅ **Снайпер привязан к Telegram ID ({user_id})!**\nЦелевая цена: **{threshold:,.0f} руб.**", reply_markup=builder.as_markup(), parse_mode="Markdown")


@dp.callback_query(F.data == "sniper_menu")
async def process_sniper_menu(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    builder = InlineKeyboardBuilder()
    
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(f"{API_BASE_URL}/snipers/{user_id}")
            snipers = res.json().get("data", []) if res.status_code == 200 else []
        except Exception as e:
            print(f"Ошибка получения списка снайперов: {e}")
            snipers = []

    if snipers:
        text = "🎯 **Ваши активные снайперы:**\n\n"
        for s in snipers:
            text += f"• *{s['item_name']}* (`{s['rarity']}`) — до **{s['threshold']:,.0f} руб.**\n"
        builder.button(text="❌ Удалить все мои снайперы", callback_data="cancel_sniper")
    else:
        text = "🎯 У вас нет активных снайперов."

    builder.button(text="⬅️ В главное меню", callback_data="back_to_main")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "cancel_sniper")
async def process_cancel_sniper(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    async with httpx.AsyncClient() as client:
        try:
            await client.delete(f"{API_BASE_URL}/snipers/{user_id}")
        except Exception as e:
            print(f"Ошибка удаления снайперов: {e}")
    
    await callback.message.edit_text("❌ Все снайперы удалены.")
    data = await state.get_data()
    await show_main_menu(callback, edit=False, has_key=bool(data.get("license_key")))
    await callback.answer()


async def main():
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
