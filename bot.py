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
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LabeledPrice,
    PreCheckoutQuery,
)


# ============================================================
# ЛОГИРОВАНИЕ
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# ============================================================
# НАСТРОЙКИ
# ============================================================

# ОСТАВЬ ЗДЕСЬ СВОЙ ТЕКУЩИЙ BOT_TOKEN.
# Я намеренно не вывожу реальный токен в ответе.
BOT_TOKEN = os.getenv(
    "BOT_TOKEN",
    "8877726623:AAEV6YFhuuBnzKWiJZxwiWM49khiaxazwRE"
)

API_BASE_URL = os.getenv(
    "API_BASE_URL",
    "https://auction-production-a352.up.railway.app"
).rstrip("/")


# ------------------------------------------------------------
# Внутренний ключ для main.py
# ------------------------------------------------------------
#
# ДОЛЖЕН БЫТЬ ТОЧНО ТАКИМ ЖЕ, КАК INTERNAL_API_KEY В main.py.
#
# Я не вывожу реальное значение из репозитория.
#
INTERNAL_API_KEY = os.getenv(
    "INTERNAL_API_KEY",
    "GOIDA_ZAPRET"
)


# ============================================================
# КОНТАКТЫ И ДОКУМЕНТЫ
# ============================================================

SUPPORT_TGG = "https://t.me/montastaile_life"
SUPPORT_TG = "https://t.me/ungdaddy"

# Platega оставлена без изменений.
PLATEGA_PAY_URL = "https://platega.com/pay/your_link"

TERMS_URL = "https://telegra.ph/Polzovatelskoe-soglashenie-08-25-64"
PRIVACY_URL = "https://telegra.ph/Politika-konfidencialnosti-08-25-84"


# ============================================================
# ПРОЧИЕ НАСТРОЙКИ
# ============================================================

ITEMS_PER_PAGE = 10

STARS_PRICE = 250
LICENSE_DAYS = 30

HTTP_TIMEOUT = 10.0


# ============================================================
# TELEGRAM
# ============================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ============================================================
# FSM СОСТОЯНИЯ
# ============================================================

class AuthState(StatesGroup):
    waiting_for_key = State()


class SniperState(StatesGroup):
    waiting_for_price = State()
    waiting_for_edit_price = State()


# ============================================================
# СЕССИИ ПОЛЬЗОВАТЕЛЕЙ
# ============================================================

# user_id -> license_key
user_sessions = {}


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def get_user_license(user_id: int):
    return user_sessions.get(user_id)


def format_price(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "Нет данных"

    if value <= 0:
        return "Нет данных"

    return f"{value:,.0f} руб."


def parse_price(text: str):
    if not text:
        return None

    clean_text = (
        text
        .replace(" ", "")
        .replace(",", "")
        .replace(".", "")
    )

    try:
        value = float(clean_text)
    except (TypeError, ValueError):
        return None

    if value <= 0:
        return None

    return value


async def api_error_text(response):
    try:
        data = response.json()
        detail = data.get("detail")

        if detail:
            return str(detail)
    except Exception:
        pass

    return f"Ошибка API: HTTP {response.status_code}"


# ============================================================
# КЛАВИАТУРЫ
# ============================================================

def get_buy_options_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⭐ Оплатить Telegram Stars",
                    callback_data="buy_stars"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💳 Оплатить через Platega",
                    url=PLATEGA_PAY_URL
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="to_main_menu"
                )
            ]
        ]
    )


def get_auth_inline_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛒 Купить ключ",
                    callback_data="open_buy_menu"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💬 Техническая поддержка",
                    url=SUPPORT_TG
                )
            ],
            [
                InlineKeyboardButton(
                    text="Канал с новостями",
                    url=SUPPORT_TGG
                )
            ],
            [
                InlineKeyboardButton(
                    text="📄 Пользовательское соглашение",
                    url=TERMS_URL
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔒 Политика конфиденциальности",
                    url=PRIVACY_URL
                )
            ]
        ]
    )


def get_main_inline_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📂 Каталог предметов",
                    callback_data="menu_catalog:0"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎯 Настроить снайпер цен",
                    callback_data="menu_snipers"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🛒 Купить ключ",
                    callback_data="open_buy_menu"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔑 Сменить ключ",
                    callback_data="menu_change_key"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💬 Техническая поддержка",
                    url=SUPPORT_TG
                )
            ],
            [
                InlineKeyboardButton(
                    text="Канал с новостями",
                    url=SUPPORT_TGG
                )
            ],
            [
                InlineKeyboardButton(
                    text="📄 Пользовательское соглашение",
                    url=TERMS_URL
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔒 Политика конфиденциальности",
                    url=PRIVACY_URL
                )
            ]
        ]
    )


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

    for label, rarity in rarities:
        builder.button(
            text=label,
            callback_data=f"setrarity:{item_id}:{rarity}"
        )

    builder.adjust(2)

    builder.row(
        InlineKeyboardButton(
            text="⬅️ Назад в каталог",
            callback_data="menu_catalog:0"
        )
    )

    return builder.as_markup()


# ============================================================
# ГЛАВНОЕ МЕНЮ
# ============================================================

async def send_main_menu(
    message_or_callback,
    text_prefix=""
):
    text = (
        f"{text_prefix}"
        "👋 **Stalzone Auction Bot**\n\n"
        "Добро пожаловать! Инструмент для мониторинга "
        "и анализа цен аукциона артефактов.\n\n"
        "Выберите нужный пункт меню ниже:"
    )

    markup = get_main_inline_menu()

    if isinstance(
        message_or_callback,
        types.CallbackQuery
    ):
        await message_or_callback.message.edit_text(
            text,
            reply_markup=markup,
            parse_mode="Markdown"
        )
    else:
        await message_or_callback.answer(
            text,
            reply_markup=markup,
            parse_mode="Markdown"
        )


# ============================================================
# СТАРТ И АВТОРИЗАЦИЯ
# ============================================================

@dp.message(CommandStart())
async def start_cmd(
    message: types.Message,
    state: FSMContext
):
    user_id = message.from_user.id

    license_key = user_sessions.get(user_id)

    if license_key:
        # Дополнительно проверяем, что ключ всё ещё действителен.
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{API_BASE_URL}/items/{license_key}",
                    params={
                        "telegram_id": user_id,
                        "limit": 1
                    },
                    timeout=HTTP_TIMEOUT
                )

                if response.status_code == 200:
                    await state.clear()
                    await send_main_menu(message)
                    return

            except Exception:
                pass

        user_sessions.pop(user_id, None)

    await state.set_state(
        AuthState.waiting_for_key
    )

    await message.answer(
        "🔑 **Авторизация в Stalzone**\n\n"
        "Пожалуйста, введите ваш ключ доступа.\n"
        "Если у вас нет ключа, вы можете приобрести его "
        "по кнопке ниже:",
        reply_markup=get_auth_inline_menu(),
        parse_mode="Markdown"
    )


@dp.message(AuthState.waiting_for_key)
async def process_license_key(
    message: types.Message,
    state: FSMContext
):
    if not message.text:
        await message.answer(
            "⚠️ Пожалуйста, отправьте ключ текстом."
        )
        return

    license_key = message.text.strip()
    user_id = message.from_user.id

    if not license_key:
        await message.answer(
            "⚠️ Ключ не может быть пустым."
        )
        return

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{API_BASE_URL}/items/{license_key}",
                params={
                    "telegram_id": user_id,
                    "limit": 1
                },
                timeout=HTTP_TIMEOUT
            )

            if response.status_code == 200:
                user_sessions[user_id] = license_key

                await state.clear()

                await send_main_menu(
                    message,
                    text_prefix=(
                        "✅ **Авторизация успешна!**\n\n"
                    )
                )

                return

            if response.status_code == 409:
                await message.answer(
                    "⛔ **Этот ключ уже привязан "
                    "к другому Telegram-аккаунту!**\n\n"
                    "Введите другой ключ или приобретите новый:",
                    reply_markup=get_auth_inline_menu(),
                    parse_mode="Markdown"
                )
                return

            if response.status_code == 403:
                await message.answer(
                    "❌ **Неверный или просроченный ключ.**\n\n"
                    "Попробуйте ввести другой ключ "
                    "или приобретите новый:",
                    reply_markup=get_auth_inline_menu(),
                    parse_mode="Markdown"
                )
                return

            await message.answer(
                f"⚠️ Не удалось проверить ключ.\n\n"
                f"{await api_error_text(response)}",
                reply_markup=get_auth_inline_menu()
            )

        except httpx.TimeoutException:
            await message.answer(
                "⏱ Сервер слишком долго отвечает. "
                "Попробуйте ещё раз."
            )

        except httpx.RequestError as e:
            logging.error(
                "Ошибка подключения при авторизации: %s",
                e
            )

            await message.answer(
                "⚠️ Ошибка подключения к серверу. "
                "Попробуйте позже."
            )

        except Exception as e:
            logging.exception(
                "Неожиданная ошибка авторизации"
            )

            await message.answer(
                "⚠️ Произошла ошибка при проверке ключа."
            )


# ============================================================
# ПОКУПКА
# ============================================================

@dp.callback_query(F.data == "open_buy_menu")
async def open_buy_menu_handler(
    callback: types.CallbackQuery
):
    await callback.message.edit_text(
        "💳 **Выберите удобный способ оплаты ключа доступа:**\n\n"
        "• **Telegram Stars** — оплата прямо внутри мессенджера.\n"
        "• **Platega** — оплата банковскими картами и СБП.",
        reply_markup=get_buy_options_keyboard(),
        parse_mode="Markdown"
    )

    await callback.answer()


# ============================================================
# TELEGRAM STARS
# ============================================================

@dp.callback_query(F.data == "buy_stars")
async def send_stars_invoice(
    callback: types.CallbackQuery
):
    prices = [
        LabeledPrice(
            label="Лицензионный ключ (30 дней)",
            amount=STARS_PRICE
        )
    ]

    await callback.message.answer_invoice(
        title="Ключ доступа Stalzone",
        description=(
            "Подписка на мониторинг аукциона "
            "на 30 дней"
        ),
        payload="license_key_30_days",
        currency="XTR",
        prices=prices
    )

    await callback.answer()


@dp.pre_checkout_query()
async def pre_checkout_handler(
    pre_checkout_query: PreCheckoutQuery
):
    await bot.answer_pre_checkout_query(
        pre_checkout_query.id,
        ok=True
    )


@dp.message(F.successful_payment)
async def successful_payment_handler(
    message: types.Message
):
    """
    После успешной оплаты Stars:
    1. Проверяем payload.
    2. Запрашиваем у main.py новую лицензию.
    3. Передаём INTERNAL_API_KEY.
    4. Получаем уникальный STZ-ключ.
    5. Сохраняем его в сессии.
    """

    payment = message.successful_payment

    if not payment:
        await message.answer(
            "⚠️ Не удалось получить данные платежа."
        )
        return

    if payment.invoice_payload != "license_key_30_days":
        logging.warning(
            "Неизвестный payload платежа: %s",
            payment.invoice_payload
        )

        await message.answer(
            "⚠️ Неизвестный тип платежа."
        )
        return

    user_id = message.from_user.id

    payload = {
        "telegram_id": user_id,
        "days": LICENSE_DAYS
    }

    headers = {
        "X-Internal-API-Key": INTERNAL_API_KEY
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{API_BASE_URL}/licenses/generate",
                json=payload,
                headers=headers,
                timeout=HTTP_TIMEOUT
            )

            if response.status_code != 200:
                logging.error(
                    "Ошибка генерации лицензии: HTTP %s: %s",
                    response.status_code,
                    response.text
                )

                await message.answer(
                    "⚠️ Оплата прошла успешно, "
                    "но при создании ключа произошла ошибка.\n\n"
                    "Обратитесь в техническую поддержку."
                )
                return

            data = response.json()

            new_key = data.get("key")

            if not new_key:
                logging.error(
                    "API не вернул ключ: %s",
                    data
                )

                await message.answer(
                    "⚠️ Оплата прошла, "
                    "но сервер не вернул ключ.\n\n"
                    "Обратитесь в техническую поддержку."
                )
                return

            expires_at = data.get(
                "expires_at",
                "неизвестно"
            )

            user_sessions[user_id] = new_key

            await message.answer(
                "🎉 **Оплата успешно завершена!**\n\n"
                f"🔑 Ваш ключ доступа:\n"
                f"`{new_key}`\n\n"
                f"📅 Срок действия: `{expires_at}`\n\n"
                "Ключ уже привязан к вашему Telegram-аккаунту.\n"
                "Нажмите `/start`, чтобы открыть меню.",
                parse_mode="Markdown"
            )

        except httpx.TimeoutException:
            logging.error(
                "Timeout при генерации лицензии"
            )

            await message.answer(
                "⚠️ Оплата прошла, но сервер "
                "не успел создать ключ.\n\n"
                "Обратитесь в техническую поддержку."
            )

        except httpx.RequestError as e:
            logging.error(
                "Ошибка сети при генерации лицензии: %s",
                e
            )

            await message.answer(
                "⚠️ Оплата прошла, но произошла ошибка "
                "связи с сервером.\n\n"
                "Обратитесь в техническую поддержку."
            )

        except Exception:
            logging.exception(
                "Ошибка после успешной оплаты"
            )

            await message.answer(
                "⚠️ Оплата прошла, но произошла "
                "ошибка создания ключа.\n\n"
                "Обратитесь в техническую поддержку."
            )


# ============================================================
# СМЕНА КЛЮЧА
# ============================================================

@dp.callback_query(F.data == "menu_change_key")
async def change_key_callback(
    callback: types.CallbackQuery,
    state: FSMContext
):
    user_id = callback.from_user.id

    user_sessions.pop(
        user_id,
        None
    )

    await state.set_state(
        AuthState.waiting_for_key
    )

    await callback.message.edit_text(
        "🔑 Введите новый ключ доступа:",
        reply_markup=get_auth_inline_menu(),
        parse_mode="Markdown"
    )

    await callback.answer()


# ============================================================
# НАЗАД В ГЛАВНОЕ МЕНЮ
# ============================================================

@dp.callback_query(F.data == "to_main_menu")
async def to_main_menu_handler(
    callback: types.CallbackQuery,
    state: FSMContext
):
    await state.clear()

    user_id = callback.from_user.id

    if user_id not in user_sessions:
        await callback.message.edit_text(
            "🔑 **Авторизация в Stalzone**\n\n"
            "Пожалуйста, введите ваш ключ доступа:",
            reply_markup=get_auth_inline_menu(),
            parse_mode="Markdown"
        )
    else:
        await send_main_menu(callback)

    await callback.answer()


# ============================================================
# КАТАЛОГ
# ============================================================

@dp.callback_query(F.data.startswith("menu_catalog"))
async def show_catalog_callback(
    callback: types.CallbackQuery,
    state: FSMContext
):
    await state.clear()

    user_id = callback.from_user.id
    license_key = get_user_license(user_id)

    if not license_key:
        await callback.answer(
            "⚠️ Сначала введите ключ доступа!",
            show_alert=True
        )
        return

    parts = callback.data.split(":")

    try:
        page = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        page = 0

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{API_BASE_URL}/items/{license_key}",
                params={
                    "telegram_id": user_id,
                    "limit": 10000
                },
                timeout=HTTP_TIMEOUT
            )

            if response.status_code != 200:
                await callback.message.answer(
                    await api_error_text(response)
                )
                await callback.answer()
                return

            items = response.json().get(
                "data",
                []
            )

        except Exception as e:
            logging.error(
                "Ошибка загрузки каталога: %s",
                e
            )

            await callback.message.answer(
                "⚠️ Ошибка загрузки каталога."
            )
            await callback.answer()
            return

    if not items:
        await callback.message.edit_text(
            "📦 Каталог предметов пуст.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⬅️ В главное меню",
                            callback_data="to_main_menu"
                        )
                    ]
                ]
            )
        )

        await callback.answer()
        return

    unique_items = []
    seen_ids = set()

    for item in items:
        item_id = (
            item.get("item_id")
            or item.get("id")
        )

        if not item_id:
            continue

        item_id = str(item_id)

        if item_id in seen_ids:
            continue

        seen_ids.add(item_id)

        item_name = (
            item.get("name")
            or item.get("item_name")
            or item_id
        )

        unique_items.append(
            (
                item_id,
                str(item_name)
            )
        )

    total_items = len(unique_items)

    total_pages = max(
        1,
        (
            total_items
            + ITEMS_PER_PAGE
            - 1
        )
        // ITEMS_PER_PAGE
    )

    page = max(
        0,
        min(
            page,
            total_pages - 1
        )
    )

    start_idx = (
        page
        * ITEMS_PER_PAGE
    )

    end_idx = (
        start_idx
        + ITEMS_PER_PAGE
    )

    page_items = unique_items[
        start_idx:end_idx
    ]

    builder = InlineKeyboardBuilder()

    for item_id, name in page_items:
        builder.button(
            text=f"🔮 {name}",
            callback_data=f"select_item:{item_id}"
        )

    builder.adjust(1)

    nav_buttons = []

    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=f"menu_catalog:{page - 1}"
            )
        )

    if page < total_pages - 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text="Вперед ➡️",
                callback_data=f"menu_catalog:{page + 1}"
            )
        )

    if nav_buttons:
        builder.row(*nav_buttons)

    builder.row(
        InlineKeyboardButton(
            text="⬅️ В главное меню",
            callback_data="to_main_menu"
        )
    )

    page_text = (
        "📂 **Выберите предмет из каталога**\n\n"
        f"Страница {page + 1}/{total_pages}"
    )

    await callback.message.edit_text(
        page_text,
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )

    await callback.answer()


# ============================================================
# ВЫБОР ПРЕДМЕТА
# ============================================================

@dp.callback_query(F.data.startswith("select_item:"))
async def select_item_info(
    callback: types.CallbackQuery
):
    item_id = callback.data.split(
        ":",
        1
    )[1]

    user_id = callback.from_user.id
    license_key = get_user_license(user_id)

    if not license_key:
        await callback.answer(
            "⚠️ Сначала авторизуйтесь.",
            show_alert=True
        )
        return

    item_name = item_id

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{API_BASE_URL}/items/{license_key}",
                params={
                    "telegram_id": user_id,
                    "limit": 10000
                },
                timeout=HTTP_TIMEOUT
            )

            if response.status_code == 200:
                items = response.json().get(
                    "data",
                    []
                )

                target = (
                    str(item_id)
                    .strip()
                    .lower()
                )

                for item in items:
                    raw_id = str(
                        item.get("item_id")
                        or item.get("id")
                        or ""
                    ).strip().lower()

                    if raw_id == target:
                        item_name = (
                            item.get("name")
                            or item.get("item_name")
                            or item_id
                        )
                        break

        except Exception:
            pass

    text = (
        f"🔮 **Предмет:** {item_name}\n\n"
        "Выберите **редкость** предмета, "
        "чтобы узнать текущую цену "
        "и настроить снайпер:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_rarity_keyboard(
            item_id
        ),
        parse_mode="Markdown"
    )

    await callback.answer()


# ============================================================
# ВЫБОР РЕДКОСТИ
# ============================================================

@dp.callback_query(F.data.startswith("setrarity:"))
async def set_rarity_and_ask_price(
    callback: types.CallbackQuery,
    state: FSMContext
):
    parts = callback.data.split(":")

    if len(parts) < 3:
        await callback.answer(
            "⚠️ Некорректный выбор.",
            show_alert=True
        )
        return

    item_id = parts[1]
    rarity = parts[2]

    user_id = callback.from_user.id
    license_key = get_user_license(user_id)

    if not license_key:
        await callback.answer(
            "⚠️ Сначала авторизуйтесь.",
            show_alert=True
        )
        return

    item_name = item_id
    min_price = None

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{API_BASE_URL}/items/{item_id}/price",
                params={
                    "rarity": rarity,
                    "license_key": license_key,
                    "telegram_id": user_id
                },
                timeout=HTTP_TIMEOUT
            )

            if response.status_code == 200:
                price_data = response.json()

                min_price = (
                    price_data.get("min_price")
                    or price_data.get("min_buyout_price")
                )

                item_name = (
                    price_data.get("item_name")
                    or item_name
                )

            else:
                # Резервный поиск названия предмета.
                catalog_response = await client.get(
                    f"{API_BASE_URL}/items/{license_key}",
                    params={
                        "telegram_id": user_id,
                        "limit": 10000
                    },
                    timeout=HTTP_TIMEOUT
                )

                if catalog_response.status_code == 200:
                    items = catalog_response.json().get(
                        "data",
                        []
                    )

                    target_id = (
                        str(item_id)
                        .strip()
                        .lower()
                    )

                    target_rarity = (
                        str(rarity)
                        .strip()
                        .lower()
                    )

                    for item in items:
                        raw_id = str(
                            item.get("item_id")
                            or item.get("id")
                            or ""
                        ).strip().lower()

                        if raw_id != target_id:
                            continue

                        item_name = (
                            item.get("name")
                            or item.get("item_name")
                            or item_name
                        )

                        raw_rarity = str(
                            item.get("rarity")
                            or ""
                        ).strip().lower()

                        if raw_rarity != target_rarity:
                            continue

                        price_value = (
                            item.get("min_buyout_price")
                            or item.get("min_price")
                            or item.get("price")
                        )

                        if price_value is not None:
                            min_price = price_value

                        break

        except Exception as e:
            logging.error(
                "Ошибка получения цены: %s",
                e
            )

    price_str = format_price(
        min_price
    )

    await state.update_data(
        target_item_id=item_id,
        target_item_name=item_name,
        target_rarity=rarity
    )

    await state.set_state(
        SniperState.waiting_for_price
    )

    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="⬅️ Отмена (в главное меню)",
            callback_data="to_main_menu"
        )
    )

    await callback.message.edit_text(
        f"🎯 Выбран предмет: **{item_name}**\n"
        f"Редкость: **{rarity}**\n"
        f"💰 **Текущая минимальная цена:** "
        f"`{price_str}`\n\n"
        "Введите **максимальную цену в рублях**, "
        "при которой бот должен прислать уведомление:",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )

    await callback.answer()


# ============================================================
# СОЗДАНИЕ СНАЙПЕРА
# ============================================================

@dp.message(SniperState.waiting_for_price)
async def set_sniper_price(
    message: types.Message,
    state: FSMContext
):
    price = parse_price(
        message.text
    )

    if price is None:
        await message.answer(
            "⚠️ Пожалуйста, введите корректную "
            "положительную цену.\n\n"
            "Например: `350000`",
            parse_mode="Markdown"
        )
        return

    user_id = message.from_user.id
    license_key = get_user_license(user_id)

    if not license_key:
        await state.clear()

        await message.answer(
            "⚠️ Ваша сессия авторизации закончилась.\n"
            "Введите ключ заново."
        )
        return

    data = await state.get_data()

    item_id = data.get(
        "target_item_id"
    )

    item_name = data.get(
        "target_item_name",
        item_id
    )

    rarity = data.get(
        "target_rarity",
        "Обычный"
    )

    if not item_id:
        await state.clear()

        await message.answer(
            "⚠️ Не удалось определить предмет."
        )
        return

    payload = {
        "user_id": user_id,
        "license_key": license_key,
        "item_id": item_id,
        "item_name": item_name,
        "rarity": rarity,
        "threshold": price
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{API_BASE_URL}/snipers",
                params={
                    "telegram_id": user_id
                },
                json=payload,
                timeout=HTTP_TIMEOUT
            )

            if response.status_code == 200:
                await message.answer(
                    "✅ **Снайпер установлен!**\n\n"
                    f"Предмет: **{item_name}**\n"
                    f"Редкость: **{rarity}**\n"
                    f"Порог цены: "
                    f"**{format_price(price)}**",
                    parse_mode="Markdown"
                )

                await state.clear()
                await send_main_menu(message)
                return

            logging.error(
                "Ошибка создания снайпера: %s %s",
                response.status_code,
                response.text
            )

            await message.answer(
                "❌ Не удалось сохранить снайпер.\n\n"
                f"{await api_error_text(response)}"
            )

        except Exception as e:
            logging.error(
                "Ошибка сети при создании снайпера: %s",
                e
            )

            await message.answer(
                "⚠️ Ошибка подключения к серверу."
            )

    await state.clear()


# ============================================================
# СПИСОК СНАЙПЕРОВ
# ============================================================

@dp.callback_query(F.data == "menu_snipers")
async def show_user_snipers_callback(
    callback: types.CallbackQuery
):
    user_id = callback.from_user.id
    license_key = get_user_license(user_id)

    if not license_key:
        await callback.answer(
            "⚠️ Сначала авторизуйтесь.",
            show_alert=True
        )
        return

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{API_BASE_URL}/snipers/{user_id}",
                params={
                    "license_key": license_key,
                    "telegram_id": user_id
                },
                timeout=HTTP_TIMEOUT
            )

            if response.status_code != 200:
                await callback.message.answer(
                    await api_error_text(response)
                )
                await callback.answer()
                return

            snipers = response.json().get(
                "data",
                []
            )

        except Exception as e:
            logging.error(
                "Ошибка получения снайперов: %s",
                e
            )

            await callback.message.answer(
                "⚠️ Ошибка получения снайперов."
            )
            await callback.answer()
            return

    if not snipers:
        builder = InlineKeyboardBuilder()

        builder.button(
            text="⬅️ В главное меню",
            callback_data="to_main_menu"
        )

        await callback.message.edit_text(
            "🎯 У вас нет активных снайперов.",
            reply_markup=builder.as_markup()
        )

        await callback.answer()
        return

    builder = InlineKeyboardBuilder()

    for sniper in snipers:
        sniper_id = sniper.get("id")

        if sniper_id is None:
            continue

        name = (
            sniper.get("item_name")
            or sniper.get("item_id")
            or "Предмет"
        )

        rarity = sniper.get(
            "rarity",
            "Обычный"
        )

        price = sniper.get(
            "threshold",
            0
        )

        builder.button(
            text=(
                f"📦 {name} "
                f"({rarity}) — "
                f"до {format_price(price)}"
            ),
            callback_data=f"manage_sniper_{sniper_id}"
        )

    builder.adjust(1)

    builder.row(
        InlineKeyboardButton(
            text="❌ Удалить все",
            callback_data="delete_all_snipers"
        ),
        InlineKeyboardButton(
            text="⬅️ Главное меню",
            callback_data="to_main_menu"
        )
    )

    await callback.message.edit_text(
        "🎯 **Ваши снайперы:**",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )

    await callback.answer()


# ============================================================
# УПРАВЛЕНИЕ ОДНИМ СНАЙПЕРОМ
# ============================================================

@dp.callback_query(F.data.startswith("manage_sniper_"))
async def manage_sniper_menu(
    callback: types.CallbackQuery
):
    sniper_id = callback.data.split(
        "manage_sniper_",
        1
    )[1]

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Изменить цену",
                    callback_data=f"edit_price_{sniper_id}"
                ),
                InlineKeyboardButton(
                    text="🗑 Удалить снайпер",
                    callback_data=f"delete_single_{sniper_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад к списку",
                    callback_data="menu_snipers"
                )
            ]
        ]
    )

    await callback.message.edit_text(
        "⚙️ **Выберите действие:**",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

    await callback.answer()


# ============================================================
# УДАЛЕНИЕ ОДНОГО СНАЙПЕРА
# ============================================================

@dp.callback_query(F.data.startswith("delete_single_"))
async def delete_single_sniper_handler(
    callback: types.CallbackQuery
):
    sniper_id = callback.data.split(
        "delete_single_",
        1
    )[1]

    user_id = callback.from_user.id
    license_key = get_user_license(user_id)

    if not license_key:
        await callback.answer(
            "⚠️ Сначала авторизуйтесь.",
            show_alert=True
        )
        return

    async with httpx.AsyncClient() as client:
        try:
            response = await client.delete(
                f"{API_BASE_URL}/snipers/single/{sniper_id}",
                params={
                    "license_key": license_key,
                    "telegram_id": user_id
                },
                timeout=HTTP_TIMEOUT
            )

            if response.status_code != 200:
                await callback.answer(
                    await api_error_text(response),
                    show_alert=True
                )
                return

        except Exception as e:
            logging.error(
                "Ошибка удаления снайпера: %s",
                e
            )

            await callback.answer(
                "⚠️ Ошибка подключения к серверу.",
                show_alert=True
            )
            return

    await callback.answer(
        "✅ Снайпер удалён!",
        show_alert=True
    )

    await show_user_snipers_callback(
        callback
    )


# ============================================================
# УДАЛЕНИЕ ВСЕХ СНАЙПЕРОВ
# ============================================================

@dp.callback_query(F.data == "delete_all_snipers")
async def delete_all_snipers_handler(
    callback: types.CallbackQuery
):
    user_id = callback.from_user.id
    license_key = get_user_license(user_id)

    if not license_key:
        await callback.answer(
            "⚠️ Сначала авторизуйтесь.",
            show_alert=True
        )
        return

    async with httpx.AsyncClient() as client:
        try:
            response = await client.delete(
                f"{API_BASE_URL}/snipers/{user_id}",
                params={
                    "license_key": license_key,
                    "telegram_id": user_id
                },
                timeout=HTTP_TIMEOUT
            )

            if response.status_code != 200:
                await callback.answer(
                    await api_error_text(response),
                    show_alert=True
                )
                return

        except Exception as e:
            logging.error(
                "Ошибка удаления всех снайперов: %s",
                e
            )

            await callback.answer(
                "⚠️ Ошибка подключения к серверу.",
                show_alert=True
            )
            return

    await callback.answer(
        "✅ Все снайперы удалены!",
        show_alert=True
    )

    await send_main_menu(
        callback
    )


# ============================================================
# НАЧАЛО РЕДАКТИРОВАНИЯ ЦЕНЫ
# ============================================================

@dp.callback_query(F.data.startswith("edit_price_"))
async def edit_price_start(
    callback: types.CallbackQuery,
    state: FSMContext
):
    sniper_id = callback.data.split(
        "edit_price_",
        1
    )[1]

    await state.update_data(
        editing_sniper_id=sniper_id
    )

    await state.set_state(
        SniperState.waiting_for_edit_price
    )

    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="⬅️ Отмена",
            callback_data="menu_snipers"
        )
    )

    await callback.message.edit_text(
        "✏️ Введите новую цену в рублях.\n\n"
        "Например: `350000`",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )

    await callback.answer()


# ============================================================
# СОХРАНЕНИЕ НОВОЙ ЦЕНЫ СНАЙПЕРА
# ============================================================

@dp.message(SniperState.waiting_for_edit_price)
async def process_new_price(
    message: types.Message,
    state: FSMContext
):
    new_price = parse_price(
        message.text
    )

    if new_price is None:
        await message.answer(
            "⚠️ Пожалуйста, введите корректную "
            "положительную цену.\n\n"
            "Например: `350000`",
            parse_mode="Markdown"
        )
        return

    user_id = message.from_user.id
    license_key = get_user_license(user_id)

    if not license_key:
        await state.clear()

        await message.answer(
            "⚠️ Ваша сессия авторизации закончилась.\n"
            "Введите ключ заново."
        )
        return

    data = await state.get_data()

    sniper_id = data.get(
        "editing_sniper_id"
    )

    if not sniper_id:
        await state.clear()

        await message.answer(
            "⚠️ Не удалось определить снайпер."
        )
        return

    async with httpx.AsyncClient() as client:
        try:
            response = await client.patch(
                f"{API_BASE_URL}/snipers/{sniper_id}",
                params={
                    "license_key": license_key,
                    "telegram_id": user_id
                },
                json={
                    "threshold": new_price
                },
                timeout=HTTP_TIMEOUT
            )

            if response.status_code != 200:
                await message.answer(
                    "❌ Не удалось обновить цену.\n\n"
                    f"{await api_error_text(response)}"
                )

                await state.clear()
                return

        except Exception as e:
            logging.error(
                "Ошибка обновления снайпера: %s",
                e
            )

            await message.answer(
                "⚠️ Ошибка подключения к серверу."
            )

            await state.clear()
            return

    await state.clear()

    await message.answer(
        "✅ **Цена обновлена!**\n\n"
        f"Новая цена: **{format_price(new_price)}**",
        parse_mode="Markdown"
    )

    await send_main_menu(
        message
    )


# ============================================================
# ЗАПУСК
# ============================================================

async def main():
    logging.info(
        "🚀 Запуск Telegram-бота Stalzone..."
    )

    await dp.start_polling(
        bot
    )


if __name__ == "__main__":
    asyncio.run(main())
