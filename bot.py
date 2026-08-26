import os
import asyncio
import httpx
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

BOT_TOKEN = os.getenv("BOT_TOKEN", "8877726623:AAEV6YFhuuBnzKWiJZxwiWM49khiaxazwRE")
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api/v1")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


class EditSniperState(StatesGroup):
    waiting_for_new_price = State()


def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🎯 Мои снайперы")
    builder.button(text="📦 Каталог предметов")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)


@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    await message.answer("👋 **Добро пожаловать в Stalzone Sniper Bot!**", reply_markup=get_main_keyboard(), parse_mode="Markdown")


# --- Вывод списка снайперов с интерактивными кнопками ---

@dp.message(F.text == "🎯 Мои снайперы")
async def show_user_snipers(message: types.Message):
    user_id = message.from_user.id
    
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(f"{API_BASE_URL}/snipers/{user_id}", timeout=5.0)
            snipers = res.json().get("data", [])
        except Exception as e:
            await message.answer(f"⚠️ Ошибка получения данных от API: {e}")
            return

    if not snipers:
        await message.answer("🎯 У вас нет активных снайперов.", reply_markup=get_main_keyboard())
        return

    builder = InlineKeyboardBuilder()

    for s in snipers:
        s_id = s["id"]
        name = s.get("item_name", "Предмет")
        rarity = s.get("rarity", "Обычный")
        price = float(s.get("threshold", 0))
        
        btn_text = f"📦 {name} ({rarity}) — до {price:,.0f} руб."
        builder.button(text=btn_text, callback_data=f"manage_sniper_{s_id}")

    builder.adjust(1)
    
    # Кнопки групповых действий
    builder.row(
        InlineKeyboardButton(text="❌ Удалить все", callback_data="delete_all_snipers"),
        InlineKeyboardButton(text="⬅️ Главное меню", callback_data="to_main_menu")
    )

    await message.answer("🎯 **Ваши активные снайперы:**\n\nНажмите на снайпер для управления:", reply_markup=builder.as_markup(), parse_mode="Markdown")


# --- Опции управления отдельным снайпером ---

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


# --- Точечное и полное удаление ---

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
    await callback.message.edit_text("🎯 Все ваши снайперы были успешно очищены.")


# --- Редактирование пороговой цены снайпера ---

@dp.callback_query(F.data.startswith("edit_price_"))
async def edit_price_start(callback: types.CallbackQuery, state: FSMContext):
    sniper_id = callback.data.split("_")[-1]
    await state.update_data(editing_sniper_id=sniper_id)
    await state.set_state(EditSniperState.waiting_for_new_price)
    
    await callback.message.answer("✏️ Введите новую пороговую цену в рублях (например: `350000`):", parse_mode="Markdown")
    await callback.answer()


@dp.message(EditSniperState.waiting_for_new_price)
async def process_new_price(message: types.Message, state: FSMContext):
    clean_text = message.text.replace(" ", "").replace(",", "")
    
    if not clean_text.isdigit():
        await message.answer("⚠️ Пожалуйста, введите корректное число без букв.")
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
    await message.answer(f"✅ Пороговая цена обновлена: **{new_price:,.0f} руб.**", parse_mode="Markdown")
    await show_user_snipers(message)


@dp.callback_query(F.data == "to_main_menu")
async def to_main_menu_handler(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("🏠 Вы вернулись в главное меню.", reply_markup=get_main_keyboard())


async def main():
    print("🚀 Запуск Telegram-бота...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
