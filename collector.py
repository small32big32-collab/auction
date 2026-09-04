import os
import time
import asyncio
import logging
from typing import Optional

import httpx
from supabase import create_client, Client

# ============================================================
# НАСТРОЙКИ
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Ключи оставляем в файле
SUPABASE_URL = os.getenv(
    "SUPABASE_URL",
    "https://mdursbqpogprwzbhjzxz.supabase.co"
)

SUPABASE_KEY = os.getenv(
    "SUPABASE_KEY",
    "ВСТАВЬ_СЮДА_СВОЙ_SUPABASE_KEY"
)

BOT_TOKEN = os.getenv(
    "BOT_TOKEN",
    "ВСТАВЬ_СЮДА_СВОЙ_BOT_TOKEN"
)

# API STALZONE
STALCRAFT_CLIENT_ID = os.getenv(
    "STALCRAFT_CLIENT_ID",
    "ВСТАВЬ_СЮДА_CLIENT_ID"
)

STALCRAFT_CLIENT_SECRET = os.getenv(
    "STALCRAFT_CLIENT_SECRET",
    "ВСТАВЬ_СЮДА_CLIENT_SECRET"
)

STALCRAFT_REGION = os.getenv("STALCRAFT_REGION", "RU")

AUCTION_API = (
    f"https://eapi.stalcraft.net/"
    f"{STALCRAFT_REGION}/auction"
)

OAUTH_URL = "https://exbo.net/oauth/token"

# Интервал обновления цен
COLLECT_INTERVAL = int(os.getenv("COLLECT_INTERVAL", "60"))

# Максимальное количество лотов за запрос
AUCTION_LIMIT = 200

# ============================================================
# SUPABASE
# ============================================================

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)

# ============================================================
# TOKEN CACHE
# ============================================================

_access_token: Optional[str] = None
_token_expires_at: float = 0
_token_lock = asyncio.Lock()


async def get_access_token() -> Optional[str]:
    """
    Получает OAuth access token для STALZONE API.
    Токен кешируется до окончания срока действия.
    """

    global _access_token, _token_expires_at

    # Если токен ещё действителен
    if _access_token and time.time() < _token_expires_at - 30:
        return _access_token

    async with _token_lock:

        # Повторная проверка после получения lock
        if _access_token and time.time() < _token_expires_at - 30:
            return _access_token

        if not STALCRAFT_CLIENT_ID or not STALCRAFT_CLIENT_SECRET:
            logger.error(
                "❌ STALCRAFT_CLIENT_ID / STALCRAFT_CLIENT_SECRET не заданы"
            )
            return None

        payload = {
            "grant_type": "client_credentials",
            "client_id": STALCRAFT_CLIENT_ID,
            "client_secret": STALCRAFT_CLIENT_SECRET
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:

                response = await client.post(
                    OAUTH_URL,
                    data=payload
                )

                if response.status_code != 200:
                    logger.error(
                        f"❌ OAuth ошибка {response.status_code}: "
                        f"{response.text[:500]}"
                    )
                    return None

                data = response.json()

                _access_token = data.get("access_token")

                expires_in = int(
                    data.get("expires_in", 3600)
                )

                _token_expires_at = (
                    time.time() + expires_in
                )

                logger.info("✅ OAuth токен STALZONE получен")

                return _access_token

        except Exception as e:
            logger.error(
                f"❌ Ошибка получения OAuth токена: {e}"
            )
            return None


# ============================================================
# STALZONE AUCTION API
# ============================================================

async def fetch_auction_lots(
    item_id: str,
    limit: int = AUCTION_LIMIT
) -> list[dict]:
    """
    Получает реальные лоты предмета с аукциона STALZONE.
    """

    token = await get_access_token()

    if not token:
        return []

    url = f"{AUCTION_API}/{item_id}/lots"

    params = {
        "limit": min(limit, 200),
        "sort": "buyout_price",
        "order": "asc"
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }

    for attempt in range(3):

        try:
            async with httpx.AsyncClient(
                timeout=20
            ) as client:

                response = await client.get(
                    url,
                    headers=headers,
                    params=params
                )

                # ------------------------------------------------
                # TOKEN ПРОТУХ
                # ------------------------------------------------

                if response.status_code == 401:

                    global _access_token
                    _access_token = None

                    token = await get_access_token()

                    if not token:
                        return []

                    headers["Authorization"] = (
                        f"Bearer {token}"
                    )

                    continue

                # ------------------------------------------------
                # RATE LIMIT
                # ------------------------------------------------

                if response.status_code == 429:

                    retry_after = response.headers.get(
                        "Retry-After",
                        "5"
                    )

                    try:
                        wait_time = int(retry_after)
                    except ValueError:
                        wait_time = 5

                    logger.warning(
                        f"⚠️ STALZONE API rate limit. "
                        f"Ждём {wait_time} сек."
                    )

                    await asyncio.sleep(wait_time)
                    continue

                # ------------------------------------------------
                # SERVER ERROR
                # ------------------------------------------------

                if response.status_code >= 500:

                    logger.warning(
                        f"⚠️ STALZONE API {response.status_code}. "
                        f"Попытка {attempt + 1}/3"
                    )

                    await asyncio.sleep(
                        2 ** attempt
                    )

                    continue

                # ------------------------------------------------
                # ДРУГАЯ ОШИБКА
                # ------------------------------------------------

                if response.status_code != 200:

                    logger.error(
                        f"❌ Auction API {response.status_code}: "
                        f"{response.text[:500]}"
                    )

                    return []

                data = response.json()

                # API может возвращать список напрямую
                if isinstance(data, list):
                    return data

                # Или объект с lots
                if isinstance(data, dict):

                    lots = data.get("lots")

                    if isinstance(lots, list):
                        return lots

                    # Некоторые версии API
                    # используют data
                    data_items = data.get("data")

                    if isinstance(data_items, list):
                        return data_items

                return []

        except httpx.TimeoutException:

            logger.warning(
                f"⚠️ Timeout STALZONE API "
                f"попытка {attempt + 1}/3"
            )

            await asyncio.sleep(
                2 ** attempt
            )

        except Exception as e:

            logger.error(
                f"❌ Ошибка запроса аукциона "
                f"{item_id}: {e}"
            )

            await asyncio.sleep(
                2 ** attempt
            )

    return []


# ============================================================
# ЦЕНА ЛОТА
# ============================================================

def get_lot_buyout_price(lot: dict) -> Optional[float]:
    """
    Достаёт цену выкупа из лота.
    """

    possible_fields = [
        "buyoutPrice",
        "buyout_price",
        "buyout",
        "price"
    ]

    for field in possible_fields:

        value = lot.get(field)

        if value is None:
            continue

        try:
            # Иногда цена может находиться
            # внутри объекта
            if isinstance(value, dict):
                value = (
                    value.get("amount")
                    or value.get("value")
                )

            return float(value)

        except (ValueError, TypeError):
            continue

    return None


# ============================================================
# МИНИМАЛЬНАЯ ЦЕНА
# ============================================================

async def fetch_auction_price(
    item_id: str
) -> Optional[float]:
    """
    Возвращает минимальную цену выкупа
    среди реальных лотов.
    """

    lots = await fetch_auction_lots(item_id)

    if not lots:
        return None

    prices = []

    for lot in lots:

        price = get_lot_buyout_price(lot)

        if price is not None and price > 0:
            prices.append(price)

    if not prices:
        return None

    return min(prices)


# ============================================================
# КАТАЛОГ
# ============================================================

def load_tracked_items() -> list[dict]:
    """
    Загружает реальные предметы из таблицы items.
    """

    try:

        response = (
            supabase
            .table("items")
            .select("item_id, name, category")
            .execute()
        )

        items = response.data or []

        result = []

        seen = set()

        for item in items:

            item_id = item.get("item_id")

            if not item_id:
                continue

            item_id = str(item_id).strip()

            if item_id in seen:
                continue

            seen.add(item_id)

            result.append({
                "item_id": item_id,
                "item_name": (
                    item.get("name")
                    or item_id
                ),
                "category": (
                    item.get("category")
                    or "Разное"
                )
            })

        logger.info(
            f"📦 Загружено предметов из Supabase: "
            f"{len(result)}"
        )

        return result

    except Exception as e:

        logger.error(
            f"❌ Ошибка загрузки каталога: {e}"
        )

        return []


# ============================================================
# TELEGRAM
# ============================================================

async def send_telegram_notification(
    user_id: int,
    text: str
):

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": user_id,
        "text": text,
        "parse_mode": "Markdown"
    }

    try:

        async with httpx.AsyncClient(
            timeout=10
        ) as client:

            response = await client.post(
                url,
                json=payload
            )

            if response.status_code != 200:

                logger.error(
                    f"❌ Telegram API "
                    f"{response.status_code}: "
                    f"{response.text[:300]}"
                )

    except Exception as e:

        logger.error(
            f"❌ Ошибка Telegram: {e}"
        )


# ============================================================
# СИНХРОНИЗАЦИЯ ПРЕДМЕТОВ
# ============================================================

def sync_all_items_to_supabase(
    tracked_items: list[dict]
):

    if not tracked_items:
        return

    records = []

    for item in tracked_items:

        records.append({
            "item_id": item["item_id"],
            "name": item["item_name"],
            "category": item["category"]
        })

    try:

        batch_size = 500

        for i in range(
            0,
            len(records),
            batch_size
        ):

            batch = records[
                i:i + batch_size
            ]

            (
                supabase
                .table("items")
                .upsert(
                    batch,
                    on_conflict="item_id"
                )
                .execute()
            )

        logger.info(
            f"✅ Каталог синхронизирован: "
            f"{len(records)} предметов"
        )

    except Exception as e:

        logger.error(
            f"❌ Ошибка синхронизации каталога: {e}"
        )


# ============================================================
# СОХРАНЕНИЕ ЦЕНЫ
# ============================================================

async def save_price(
    item: dict,
    price: float
):

    record = {
        "item_id": item["item_id"],
        "item_name": item["item_name"],
        "rarity": "Обычный",
        "category": item["category"],
        "min_buyout_price": int(price)
    }

    try:

        (
            supabase
            .table("price_history")
            .insert(record)
            .execute()
        )

        logger.info(
            f"💰 {item['item_name']} "
            f"({item['item_id']}): "
            f"{price:,.0f} руб."
        )

    except Exception as e:

        logger.error(
            f"❌ Ошибка записи цены "
            f"{item['item_id']}: {e}"
        )


# ============================================================
# ВОРКЕР СБОРА ЦЕН
# ============================================================

async def general_collector_worker(
    tracked_items: list[dict]
):

    logger.info(
        "🚀 Запущен сборщик реальных цен аукциона"
    )

    while True:

        cycle_start = time.time()

        try:

            # Чтобы не долбить API одновременно
            semaphore = asyncio.Semaphore(3)

            async def process_item(item):

                async with semaphore:

                    item_id = item["item_id"]

                    try:

                        price = await fetch_auction_price(
                            item_id
                        )

                        if price is None:

                            logger.info(
                                f"📭 Нет buyout-лотов: "
                                f"{item['item_name']}"
                            )

                            return

                        await save_price(
                            item,
                            price
                        )

                    except Exception as e:

                        logger.error(
                            f"❌ Ошибка предмета "
                            f"{item_id}: {e}"
                        )

                    # Небольшая пауза
                    await asyncio.sleep(0.2)

            await asyncio.gather(
                *[
                    process_item(item)
                    for item in tracked_items
                ]
            )

            elapsed = time.time() - cycle_start

            wait_time = max(
                1,
                COLLECT_INTERVAL - elapsed
            )

            logger.info(
                f"🔄 Цикл завершён за "
                f"{elapsed:.1f} сек. "
                f"Следующий через "
                f"{wait_time:.1f} сек."
            )

            await asyncio.sleep(wait_time)

        except Exception as e:

            logger.error(
                f"❌ Ошибка главного цикла: {e}"
            )

            await asyncio.sleep(10)


# ============================================================
# СНАЙПЕР
# ============================================================

# Последнее уведомление:
# (sniper_id) -> timestamp
last_sniper_notifications = {}

# Минимальный интервал между одинаковыми уведомлениями
SNIPER_COOLDOWN = 300


async def sniper_monitoring_worker():

    logger.info(
        "🎯 Запущен мониторинг снайперов"
    )

    while True:

        try:

            response = (
                supabase
                .table("user_snipers")
                .select("*")
                .execute()
            )

            snipers = response.data or []

            for sniper in snipers:

                try:

                    sniper_id = str(
                        sniper.get("id")
                    )

                    user_id = sniper.get(
                        "user_id"
                    )

                    item_id = sniper.get(
                        "item_id"
                    )

                    item_name = (
                        sniper.get("item_name")
                        or item_id
                    )

                    threshold = float(
                        sniper.get("threshold", 0)
                    )

                    if not user_id or not item_id:
                        continue

                    if threshold <= 0:
                        continue

                    # Получаем реальную цену
                    current_price = (
                        await fetch_auction_price(
                            item_id
                        )
                    )

                    if current_price is None:
                        continue

                    if current_price > threshold:
                        continue

                    now = time.time()

                    last_notification = (
                        last_sniper_notifications.get(
                            sniper_id,
                            0
                        )
                    )

                    # Защита от спама
                    if (
                        now - last_notification
                        < SNIPER_COOLDOWN
                    ):
                        continue

                    last_sniper_notifications[
                        sniper_id
                    ] = now

                    msg = (
                        "🎯 **СНАЙПЕР СРАБОТАЛ!**\n\n"
                        f"📦 Предмет: **{item_name}**\n"
                        f"💰 Цена: "
                        f"`{current_price:,.0f} руб.`\n"
                        f"🎯 Ваш порог: "
                        f"`{threshold:,.0f} руб.`\n\n"
                        "🔥 Цена ниже установленного "
                        "порога!\n\n"
                        "Срочно заходите в игру "
                        "для выкупа!"
                    )

                    await send_telegram_notification(
                        int(user_id),
                        msg
                    )

                except Exception as e:

                    logger.error(
                        f"❌ Ошибка снайпера "
                        f"{sniper.get('id')}: {e}"
                    )

            await asyncio.sleep(10)

        except Exception as e:

            logger.error(
                f"❌ Ошибка воркера снайперов: {e}"
            )

            await asyncio.sleep(10)


# ============================================================
# MAIN
# ============================================================

async def main():

    logger.info(
        "======================================"
    )

    logger.info(
        "🚀 STALZONE AUCTION COLLECTOR"
    )

    logger.info(
        "======================================"
    )

    tracked_items = load_tracked_items()

    if not tracked_items:

        logger.error(
            "❌ В таблице items нет предметов."
        )

        # Не завершаем процесс —
        # каталог может появиться позже.
        while True:
            await asyncio.sleep(60)

    sync_all_items_to_supabase(
        tracked_items
    )

    await asyncio.gather(
        general_collector_worker(
            tracked_items
        ),
        sniper_monitoring_worker()
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        logger.info(
            "🛑 Collector остановлен"
        )

    except SystemExit:

        logger.info(
            "🛑 Collector завершён"
        )
