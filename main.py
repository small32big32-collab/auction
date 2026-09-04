import os
import secrets
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    PreCheckoutQuery, LabeledPrice
)
from supabase import create_client, Client

# Настройки логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Переменные окружения
BOT_TOKEN = os.getenv("BOT_TOKEN", "8877726623:AAEV6YFhuuBnzKWiJZxwiWM49khiaxazwRE")
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://mdursbqpogprwzbhjzxz.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1kdXJzYnFwb2dwcnd6Ymhqenh6Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NzE0MzU5NCwiZXhwIjoyMTAyNzE5NTk0fQ.AXb2IUi3VOY1hNHxrvZUpsk4f6ycGDc2qaC_4zzM1Mo")

# Инициализация клиентов
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()


# --- Состояния FSM ---

class AuthStates(StatesGroup):
    waiting_for_key = State()

class SniperStates(StatesGroup):
    waiting_for_item_search = State()
    selecting_rarity = State()
    waiting_for_threshold = State()


# --- Клавиатуры ---

def get_main_keyboard() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="🎯 Мои снайперы"), KeyboardButton(text="➕ Добавить снайпер")],
        [KeyboardButton(text="💳 Купить подписку"), KeyboardButton(text="🔑 Мой ключ")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    kb = [[KeyboardButton(text="⬅️ Отмена (в главное меню)")]]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_rarity_keyboard(item_id: str) -> InlineKeyboardMarkup:
    rarities = ["Обычный", "Необычный", "Особый", "Редкий", "Исключительный", "Легендарный"]
    buttons = []
    for r in rarities:
        buttons.append([InlineKeyboardButton(text=r, callback_data=f"select_rarity:{item_id}:{r}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# --- Вспомогательные функции ---

def check_user_license(telegram_id: int) -> Optional[dict]:
    """Проверяет наличие активной подписки у пользователя по telegram_id"""
    try:
        res = (
            supabase.table("licenses")
            .select("*")
            .eq("telegram_id", telegram_id)
            .eq("is_active", True)
            .execute()
        )
        if res.data:
            for lic in res.data:
                expires_at_str = lic.get("expires_at")
                if expires_at_str:
                    expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                    if datetime.now(timezone.utc) < expires_at:
                        return lic
        return None
    except Exception as e:
        logger.error(f"Ошибка проверки лицензии: {e}")
        return None

def generate_and_issue_license(telegram_id: int, days: int = 30) -> str:
    """Генерирует и сохраняет новый ключ в Supabase"""
    part1 = secrets.token_hex(3).upper()
    part2 = secrets.token_hex(3).upper()
    license_key = f"STALZONE-{part1}-{part2}"
    
    expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    
    # Деактивируем старые ключи пользователя
    try:
        supabase.table("licenses").update({"is_active": False}).eq("telegram_id", telegram_id).execute()
    except Exception:
        pass
    
    payload = {
        "key": license_key,
        "telegram_id": telegram_id,
        "is_active": True,
        "expires_at": expires_at,
        "hwid": None
    }
    
    supabase.table("licenses").insert(payload).execute()
    return license_key

def get_latest_item_price(item_id: str, rarity: str = "Обычный") -> Optional[float]:
    """Получает свежую минимальную цену предмета из price_history"""
    try:
        res = (
            supabase.table("price_history")
            .select("min_buyout_price")
            .eq("item_id", item_id)
            .eq("rarity", rarity)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if res.data and len(res.data) > 0:
            return float(res.data[0].get("min_buyout_price") or 0)
    except Exception as e:
        logger.error(f"Ошибка получения цены: {e}")
    return None


# --- Обработчики Команд и Авторизации ---

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    lic = check_user_license(user_id)
    
    if lic:
        await message.answer(
            f"👋 С возвращением! Подписка активна до: `{lic.get('expires_at')[:10]}`",
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            "👋 Добро пожаловать в Stalzone Auction Bot!\n\n"
            "У вас нет активной подписки. Введите ваш лицензионный ключ или купите подписку ниже:",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="💳 Купить подписку")],
                    [KeyboardButton(text="🔑 Ввести ключ")]
                ],
                resize_keyboard=True
            )
        )

@router.message(F.text == "🔑 Ввести ключ")
async def ask_for_key(message: Message, state: FSMContext):
    await state.set_state(AuthStates.waiting_for_key)
    await message.answer("Введите ваш лицензионный ключ:", reply_markup=get_cancel_keyboard())

@router.message(AuthStates.waiting_for_key)
async def process_key_input(message: Message, state: FSMContext):
    if message.text == "⬅️ Отмена (в главное меню)":
        await cmd_start(message, state)
        return

    input_key = message.text.strip()
    user_id = message.from_user.id
    
    try:
        res = supabase.table("licenses").select("*").eq("key", input_key).execute()
        if res.data and len(res.data) > 0:
            lic = res.data[0]
            if lic.get("is_active"):
                # Привязываем ключ к текущему Telegram ID
                supabase.table("licenses").update({"telegram_id": user_id}).eq("key", input_key).execute()
                await state.clear()
                await message.answer("✅ Ключ успешно активирован!", reply_markup=get_main_keyboard())
                return
            else:
                await message.answer("❌ Этот ключ деактивирован.")
                return
        await message.answer("❌ Неверный ключ. Попробуйте еще раз.")
    except Exception as e:
        logger.error(f"Ошибка проверки ключа: {e}")
        await message.answer("⚠️ Ошибка базы данных при проверке ключа.")

@router.message(F.text == "🔑 Мой ключ")
async def show_my_key(message: Message):
    user_id = message.from_user.id
    lic = check_user_license(user_id)
    if lic:
        await message.answer(
            f"🔑 Ваш ключ: `{lic.get('key')}`\n⏳ Активен до: `{lic.get('expires_at')[:10]}`",
            parse_mode="Markdown"
        )
    else:
        await message.answer("❌ У вас нет активной подписки.")


# --- Покупка Подписки (Telegram Stars) ---

@router.message(F.text == "💳 Купить подписку")
async def send_payment_invoice(message: Message):
    await message.answer_invoice(
        title="Подписка Stalzone Auction",
        description="Полный доступ к снайперу и ценам на 30 дней",
        payload="sub_30_days",
        currency="XTR",  # Telegram Stars
        prices=[LabeledPrice(label="Подписка на 1 месяц", amount=250)],
        start_parameter="buy-subscription"
    )

@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

@router.message(F.successful_payment)
async def process_successful_payment(message: Message):
    user_id = message.from_user.id
    new_key = generate_and_issue_license(telegram_id=user_id, days=30)
    
    msg = (
        f"✅ **Оплата прошла успешно!**\n\n"
        f"🔑 Ваш новый лицензионный ключ:\n`{new_key}`\n\n"
        f"⏳ Срок действия: **30 дней**\n\n"
        f"Подписка автоматически активирована на ваш аккаунт!"
    )
    await message.answer(msg, reply_markup=get_main_keyboard(), parse_mode="Markdown")


# --- Добавление Снайпера ---

@router.message(F.text == "⬅️ Отмена (в главное меню)")
async def cancel_to_main(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=get_main_keyboard())

@router.message(F.text == "➕ Добавить снайпер")
async def start_add_sniper(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not check_user_license(user_id):
        await message.answer("❌ Для добавления снайпера требуется активная подписка!")
        return

    await state.set_state(SniperStates.waiting_for_item_search)
    await message.answer("Введите название или часть названия предмета (например: Гребешок):", reply_markup=get_cancel_keyboard())

@router.message(SniperStates.waiting_for_item_search)
async def process_item_search(message: Message, state: FSMContext):
    query_text = message.text.strip()
    
    # Поиск артефактов в базе items
    try:
        res = supabase.table("items").select("*").ilike("name", f"%{query_text}%").limit(10).execute()
        items = res.data or []
        
        if not items:
            await message.answer("🔍 Предметы не найдены. Попробуйте ввести другое название:")
            return
            
        if len(items) == 1:
            item = items[0]
            await state.update_data(selected_item_id=item["item_id"], selected_item_name=item["name"])
            await state.set_state(SniperStates.selecting_rarity)
            await message.answer(
                f"Выбран предмет: **{item['name']}**\nВыберите редкость:",
                reply_markup=get_rarity_keyboard(item["item_id"]),
                parse_mode="Markdown"
            )
        else:
            # Если найдено несколько — выводим список кнопок
            buttons = [
                [InlineKeyboardButton(text=it["name"], callback_data=f"pick_item:{it['item_id']}:{it['name']}")]
                for it in items
            ]
            kb = InlineKeyboardMarkup(inline_keyboard=buttons)
            await message.answer("Выберите нужный предмет из списка:", reply_markup=kb)

    except Exception as e:
        logger.error(f"Ошибка поиска предметов: {e}")
        await message.answer("⚠️ Ошибка поиска предметов.")

@router.callback_query(F.data.startswith("pick_item:"))
async def on_item_picked(callback: CallbackQuery, state: FSMContext):
    _, item_id, item_name = callback.data.split(":", 2)
    await state.update_data(selected_item_id=item_id, selected_item_name=item_name)
    await state.set_state(SniperStates.selecting_rarity)
    
    await callback.message.edit_text(
        f"Выбран предмет: **{item_name}**\nВыберите редкость:",
        reply_markup=get_rarity_keyboard(item_id),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("select_rarity:"))
async def on_rarity_selected(callback: CallbackQuery, state: FSMContext):
    _, item_id, rarity = callback.data.split(":", 2)
    data = await state.get_data()
    item_name = data.get("selected_item_name", item_id)
    
    await state.update_data(selected_rarity=rarity)
    
    # Получаем текущую цену предмета задананой редкости
    min_price = get_latest_item_price(item_id, rarity)
    price_str = f"{min_price:,.0f} руб." if min_price else "нет данных"

    # Формирование точно такого же сообщения, как на скриншоте
    text = (
        f"🎯 Выбран предмет: {item_name}\n"
        f"Редкость: {rarity}\n"
        f"💰 Текущая минимальная цена: {price_str}\n\n"
        f"Введите максимальную цену в рублях, при которой бот должен прислать уведомление:"
    )
    
    await state.set_state(SniperStates.waiting_for_threshold)
    await callback.message.delete()
    await callback.message.answer(text, reply_markup=get_cancel_keyboard())
    await callback.answer()

@router.message(SniperStates.waiting_for_threshold)
async def process_threshold_input(message: Message, state: FSMContext):
    raw_text = message.text.replace(" ", "").replace(",", ".").strip()
    
    try:
        threshold = float(raw_text)
        if threshold <= 0:
            raise ValueError()
    except ValueError:
        await message.answer("❌ Пожалуйста, введите корректную сумму числом (например: 45000):")
        return

    data = await state.get_data()
    user_id = message.from_user.id
    lic = check_user_license(user_id)
    license_key = lic.get("key") if lic else None

    payload = {
        "user_id": user_id,
        "license_key": license_key,
        "item_id": data["selected_item_id"],
        "item_name": data["selected_item_name"],
        "rarity": data["selected_rarity"],
        "threshold": threshold
    }

    try:
        supabase.table("user_snipers").insert(payload).execute()
        await state.clear()
        
        success_msg = (
            f"✅ **Снайпер успешно добавлен!**\n\n"
            f"📦 Предмет: **{data['selected_item_name']}** ({data['selected_rarity']})\n"
            f"🎯 Порог цены: **{threshold:,.0f} руб.**\n\n"
            f"Бот уведомит вас, как только этот предмет появится по указанной цене или дешевле."
        )
        await message.answer(success_msg, reply_markup=get_main_keyboard(), parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Ошибка сохранения снайпера: {e}")
        await message.answer("⚠️ Не удалось сохранить снайпера в базу.")


# --- Управление Снайперами ---

@router.message(F.text == "🎯 Мои снайперы")
async def show_user_snipers(message: Message):
    user_id = message.from_user.id
    try:
        res = supabase.table("user_snipers").select("*").eq("user_id", user_id).execute()
        snipers = res.data or []

        if not snipers:
            await message.answer("У вас пока нет активных снайперов.")
            return

        text = "🎯 **Ваши активные снайперы:**\n\n"
        buttons = []
        
        for idx, s in enumerate(snipers, 1):
            text += f"{idx}. **{s['item_name']}** ({s['rarity']}) — до `{s['threshold']:,.0f} руб.`\n"
            buttons.append([InlineKeyboardButton(
                text=f"❌ Удалить: {s['item_name']} ({s['rarity']})",
                callback_data=f"del_sniper:{s['id']}"
            )])

        buttons.append([InlineKeyboardButton(text="🗑 Удалить все снайперы", callback_data="del_all_snipers")])
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await message.answer(text, reply_markup=kb, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Ошибка получения снайперов: {e}")
        await message.answer("⚠️ Ошибка при получении списка снайперов.")

@router.callback_query(F.data.startswith("del_sniper:"))
async def delete_single_sniper_cb(callback: CallbackQuery):
    sniper_id = callback.data.split(":")[1]
    try:
        supabase.table("user_snipers").delete().eq("id", sniper_id).execute()
        await callback.answer("Снайпер удален!")
        await callback.message.edit_text("✅ Снайпер успешно удален.")
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")
        await callback.answer("Ошибка при удалении.", show_alert=True)

@router.callback_query(F.data == "del_all_snipers")
async def delete_all_snipers_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    try:
        supabase.table("user_snipers").delete().eq("user_id", user_id).execute()
        await callback.answer("Все снайперы удалены!")
        await callback.message.edit_text("✅ Все ваши снайперы успешно удалены.")
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")
        await callback.answer("Ошибка при удалении.", show_alert=True)


# --- Запуск ---

async def main():
    dp.include_router(router)
    logger.info("🤖 Бот успешно запущен!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Бот остановлен.")
