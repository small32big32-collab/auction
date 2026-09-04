import os
import time
import asyncio
import logging
import json
from pathlib import Path
from typing import Optional, Any

import httpx
from supabase import create_client, Client


# ============================================================
# CONFIG
# ============================================================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

BOT_TOKEN = os.getenv("BOT_TOKEN")

STALCRAFT_CLIENT_ID = os.getenv("STALCRAFT_CLIENT_ID")
STALCRAFT_CLIENT_SECRET = os.getenv("STALCRAFT_CLIENT_SECRET")

STALCRAFT_REGION = os.getenv(
    "STALCRAFT_REGION",
    "ru",
)

AUCTION_API_URL = (
    f"https://eapi.stalcraft.net/"
    f"{STALCRAFT_REGION}/auction"
)

OAUTH_URL = "https://exbo.net/oauth/token"


# ============================================================
# INTERVALS
# ============================================================

COLLECT_INTERVAL = int(
    os.getenv(
        "COLLECT_INTERVAL",
        "60",
    )
)

SNIPER_INTERVAL = int(
    os.getenv(
        "SNIPER_INTERVAL",
        "10",
    )
)

SNIPER_COOLDOWN = int(
    os.getenv(
        "SNIPER_COOLDOWN",
        "300",
    )
)

MAX_CONCURRENT_REQUESTS = int(
    os.getenv(
        "MAX_CONCURRENT_REQUESTS",
        "3",
    )
)


# Если реальный лот существует,
# но в нём отсутствует/некорректна цена.
DEFAULT_AUCTION_PRICE = 150000


# ============================================================
# LOCAL OFFICIAL DATABASE
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent

DATABASE_PATH = (
    PROJECT_ROOT
    / "stalzone-database"
    / "ru"
    / "items"
)

# Работаем именно с официальными артефактами.
ARTIFACTS_DATABASE_PATH = (
    DATABASE_PATH
    / "artefact"
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# CONFIG VALIDATION
# ============================================================

required_config = {
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_KEY": SUPABASE_KEY,
    "BOT_TOKEN": BOT_TOKEN,
    "STALCRAFT_CLIENT_ID": STALCRAFT_CLIENT_ID,
    "STALCRAFT_CLIENT_SECRET": STALCRAFT_CLIENT_SECRET,
}

for config_name, config_value in required_config.items():

    if not config_value:

        logger.warning(
            "%s не установлен",
            config_name,
        )


# ============================================================
# SUPABASE
# ============================================================

if not SUPABASE_URL or not SUPABASE_KEY:

    raise RuntimeError(
        "SUPABASE_URL и SUPABASE_KEY должны "
        "быть установлены в переменных окружения."
    )

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY,
)


# ============================================================
# RARITY
# ============================================================

RARITY_NAMES = {

    "обычный": "Обычный",
    "common": "Обычный",
    "0": "Обычный",

    "необычный": "Необычный",
    "uncommon": "Необычный",
    "1": "Необычный",

    "особый": "Особый",
    "special": "Особый",
    "2": "Особый",

    "редкий": "Редкий",
    "rare": "Редкий",
    "3": "Редкий",

    "исключительный": "Исключительный",
    "exceptional": "Исключительный",
    "4": "Исключительный",

    "легендарный": "Легендарный",
    "legendary": "Легендарный",
    "5": "Легендарный",
}


RARITY_BY_NUMBER = {

    0: "Обычный",
    1: "Необычный",
    2: "Особый",
    3: "Редкий",
    4: "Исключительный",
    5: "Легендарный",

}


def normalize_rarity(
    value: Any,
) -> Optional[str]:

    if value is None:
        return None

    if isinstance(value, bool):
        return None

    if isinstance(
        value,
        (int, float),
    ):

        try:

            return RARITY_BY_NUMBER.get(
                int(value)
            )

        except Exception:

            return None

    value = str(
        value
    ).strip()

    if not value:
        return None

    if value.isdigit():

        return RARITY_BY_NUMBER.get(
            int(value)
        )

    return RARITY_NAMES.get(
        value.lower()
    )


# ============================================================
# LOCAL ITEM DATABASE
# ============================================================

class LocalItemDatabase:

    def __init__(
        self,
        base_dir: Path,
    ):

        self.base_dir = base_dir

        self.items_by_id: dict[
            str,
            dict,
        ] = {}

        self._load()


    def _load(self) -> None:

        if not self.base_dir.exists():

            logger.error(
                "Папка официальной базы не найдена: %s",
                self.base_dir,
            )

            return

        loaded = 0
        skipped = 0

        for file_path in self.base_dir.rglob(
            "*.json"
        ):

            try:

                with open(
                    file_path,
                    "r",
                    encoding="utf-8",
                ) as file:

                    data = json.load(file)

                if not isinstance(
                    data,
                    dict,
                ):

                    skipped += 1
                    continue

                # ID берём ТОЛЬКО из официального JSON.
                item_id = data.get(
                    "id"
                )

                if not item_id:

                    skipped += 1
                    continue

                item_id = str(
                    item_id
                ).strip()

                if not item_id:

                    skipped += 1
                    continue

                name_data = data.get(
                    "name"
                )

                ru_name = ""

                if isinstance(
                    name_data,
                    dict,
                ):

                    lines = name_data.get(
                        "lines",
                        {},
                    )

                    if isinstance(
                        lines,
                        dict,
                    ):

                        ru_name = (
                            lines.get("ru")
                            or lines.get("en")
                            or ""
                        )

                ru_name = str(
                    ru_name
                ).strip()

                category = data.get(
                    "category"
                )

                # Если один и тот же ID встретился
                # несколько раз, оставляем первый.
                if item_id in self.items_by_id:

                    continue

                self.items_by_id[item_id] = {

                    "id": item_id,

                    "name": ru_name,

                    "category": (
                        str(category).strip()
                        if category is not None
                        else None
                    ),

                    "color": data.get(
                        "color"
                    ),

                    "file": str(
                        file_path
                    ),
                }

                loaded += 1

            except Exception as exc:

                skipped += 1

                logger.debug(
                    "Ошибка чтения %s: %s",
                    file_path,
                    exc,
                )

        logger.info(
            "Официальная база артефактов загружена: %s",
            loaded,
        )

        if skipped:

            logger.info(
                "Пропущено JSON-файлов: %s",
                skipped,
            )


    def get_by_id(
        self,
        item_id: Any,
    ) -> Optional[dict]:

        if item_id is None:
            return None

        return self.items_by_id.get(
            str(item_id).strip()
        )


    def get_all(
        self,
    ) -> list[dict]:

        return list(
            self.items_by_id.values()
        )


# Загружаем официальную базу ОДИН РАЗ
# при запуске коллектора.
local_database = LocalItemDatabase(
    ARTIFACTS_DATABASE_PATH
)


# ============================================================
# AUCTION ID CACHE
# ============================================================

_auction_invalid_ids: set[str] = set()

_auction_valid_ids: set[str] = set()


# ============================================================
# OAUTH
# ============================================================

_access_token: Optional[str] = None

_access_token_expires_at: float = 0

_token_lock = asyncio.Lock()


async def get_access_token() -> str:

    global _access_token
    global _access_token_expires_at

    if (
        not STALCRAFT_CLIENT_ID
        or not STALCRAFT_CLIENT_SECRET
    ):

        raise RuntimeError(
            "STALCRAFT_CLIENT_ID "
            "и STALCRAFT_CLIENT_SECRET "
            "не установлены."
        )

    async with _token_lock:

        now = time.time()

        if (
            _access_token
            and now
            < _access_token_expires_at - 30
        ):

            return _access_token

        payload = {

            "grant_type":
                "client_credentials",

            "client_id":
                STALCRAFT_CLIENT_ID,

            "client_secret":
                STALCRAFT_CLIENT_SECRET,

        }

        async with httpx.AsyncClient(
            timeout=20
        ) as client:

            response = await client.post(
                OAUTH_URL,
                data=payload,
            )

            response.raise_for_status()

            data = response.json()

        new_token = data.get(
            "access_token"
        )

        if not new_token:

            raise RuntimeError(
                "OAuth не вернул access_token."
            )

        _access_token = new_token

        expires_in = int(
            data.get(
                "expires_in",
                3600,
            )
        )

        _access_token_expires_at = (
            time.time()
            + expires_in
        )

        logger.info(
            "Получен новый STALCRAFT access token"
        )

        return _access_token


# ============================================================
# AUCTION CACHE
# ============================================================

_lots_cache: dict[
    str,
    tuple[
        float,
        list[dict],
    ],
] = {}


LOTS_CACHE_TTL = max(
    2,
    SNIPER_INTERVAL - 1,
)


def _get_cached_lots(
    item_id: str,
) -> Optional[list[dict]]:

    cached = _lots_cache.get(
        item_id
    )

    if not cached:
        return None

    timestamp, lots = cached

    if (
        time.time()
        - timestamp
        > LOTS_CACHE_TTL
    ):

        _lots_cache.pop(
            item_id,
            None,
        )

        return None

    return lots


def _set_cached_lots(
    item_id: str,
    lots: list[dict],
) -> None:

    _lots_cache[item_id] = (
        time.time(),
        lots,
    )


# ============================================================
# AUCTION API
# ============================================================

async def fetch_auction_lots(
    item_id: str,
    limit: int = 200,
    force_refresh: bool = False,
) -> list[dict]:

    global _access_token
    global _access_token_expires_at

    item_id = str(
        item_id
    ).strip()

    if not item_id:
        return []

    # ID уже признан несуществующим API.
    if item_id in _auction_invalid_ids:

        return []

    # --------------------------------------------------------
    # CACHE
    # --------------------------------------------------------

    if not force_refresh:

        cached = _get_cached_lots(
            item_id
        )

        if cached is not None:

            return cached

    token = await get_access_token()

    url = (
        f"{AUCTION_API_URL}/"
        f"{item_id}/lots"
    )

    params = {

        "limit": limit,

        "sort":
            "buyout_price",

        "order":
            "asc",

        "additional":
            "true",

    }

    headers = {

        "Authorization":
            f"Bearer {token}",

        "Accept":
            "application/json",

    }

    for attempt in range(4):

        try:

            logger.debug(
                "Запрос Auction API: %s",
                url,
            )

            async with httpx.AsyncClient(
                timeout=20
            ) as client:

                response = await client.get(

                    url,

                    params=params,

                    headers=headers,

                )

            # ------------------------------------------------
            # TOKEN EXPIRED
            # ------------------------------------------------

            if response.status_code == 401:

                _access_token = None

                _access_token_expires_at = 0

                token = await get_access_token()

                headers["Authorization"] = (
                    f"Bearer {token}"
                )

                continue

            # ------------------------------------------------
            # RATE LIMIT
            # ------------------------------------------------

            if response.status_code == 429:

                wait_time = min(
                    2 ** attempt,
                    10,
                )

                logger.warning(
                    "STALCRAFT API rate limit. "
                    "Ожидание %s сек.",
                    wait_time,
                )

                await asyncio.sleep(
                    wait_time
                )

                continue

            # ------------------------------------------------
            # SERVER ERROR
            # ------------------------------------------------

            if response.status_code >= 500:

                wait_time = min(
                    2 ** attempt,
                    10,
                )

                logger.warning(
                    "STALCRAFT API %s для %s. "
                    "Повтор через %s сек.",
                    response.status_code,
                    item_id,
                    wait_time,
                )

                await asyncio.sleep(
                    wait_time
                )

                continue

            # ------------------------------------------------
            # INVALID ITEM ID
            # ------------------------------------------------

            if response.status_code == 400:

                try:

                    error_data = (
                        response.json()
                    )

                except Exception:

                    error_data = {}

                title = str(
                    error_data.get(
                        "title",
                        "",
                    )
                ).lower()

                detail = str(
                    error_data.get(
                        "detail",
                        "",
                    )
                ).lower()

                error_text = (
                    f"{title} {detail}"
                )

                if (
                    "invalid item id"
                    in error_text
                    or (
                        "item id"
                        in error_text
                        and "invalid"
                        in error_text
                    )
                ):

                    _auction_invalid_ids.add(
                        item_id
                    )

                    logger.warning(
                        "ID %s не существует "
                        "в Auction API — запоминаем.",
                        item_id,
                    )

                else:

                    logger.warning(
                        "Auction API вернул "
                        "400 для %s: %s",
                        item_id,
                        response.text[:500],
                    )

                return []

            # ------------------------------------------------
            # OTHER CLIENT ERRORS
            # ------------------------------------------------

            if response.status_code >= 400:

                logger.warning(
                    "Auction API вернул %s "
                    "для %s: %s",
                    response.status_code,
                    item_id,
                    response.text[:500],
                )

                return []

            # ------------------------------------------------
            # SUCCESS
            # ------------------------------------------------

            response.raise_for_status()

            data = response.json()

            if isinstance(
                data,
                list,
            ):

                lots = data

            elif isinstance(
                data,
                dict,
            ):

                lots = data.get(
                    "lots"
                )

                if lots is None:

                    lots = data.get(
                        "data"
                    )

                if lots is None:

                    lots = []

            else:

                lots = []

            if not isinstance(
                lots,
                list,
            ):

                lots = []

            _auction_valid_ids.add(
                item_id
            )

            _set_cached_lots(
                item_id,
                lots,
            )

            logger.debug(
                "Получено %s лотов для %s",
                len(lots),
                item_id,
            )

            return lots

        except (
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
        ) as exc:

            wait_time = min(
                2 ** attempt,
                10,
            )

            logger.warning(
                "Ошибка запроса аукциона %s: %s. "
                "Повтор через %s сек.",
                item_id,
                exc,
                wait_time,
            )

            await asyncio.sleep(
                wait_time
            )

        except Exception as exc:

            logger.exception(
                "Ошибка получения лотов %s: %s",
                item_id,
                exc,
            )

            break

    return []


# ============================================================
# PRICE
# ============================================================

def _extract_price_value(
    value: Any,
) -> Optional[float]:

    """
    Рекурсивно извлекает цену из возможных
    вариантов структуры Auction API.
    """

    if value is None:
        return None

    if isinstance(
        value,
        bool,
    ):

        return None

    if isinstance(
        value,
        (int, float),
    ):

        try:

            number = float(
                value
            )

            if number > 0:

                return number

        except (
            TypeError,
            ValueError,
        ):

            pass

        return None

    if isinstance(
        value,
        str,
    ):

        clean = value.strip()

        if not clean:
            return None

        try:

            number = float(
                clean
            )

            if number > 0:

                return number

        except (
            TypeError,
            ValueError,
        ):

            return None

        return None

    if isinstance(
        value,
        dict,
    ):

        # Приоритетные названия полей.
        for key in (
            "amount",
            "value",
            "price",
        ):

            if key in value:

                result = (
                    _extract_price_value(
                        value[key]
                    )
                )

                if result is not None:

                    return result

        return None

    return None


def get_lot_buyout_price(
    lot: dict,
) -> float:

    """
    Цена берётся только из реального лота.

    Если поле цены отсутствует или
    содержит некорректное значение,
    используется DEFAULT_AUCTION_PRICE.

    Сам лот при этом должен существовать.
    """

    possible_keys = (

        "buyoutPrice",

        "buyout_price",

        "buyout",

        "price",

    )

    for key in possible_keys:

        if key not in lot:

            continue

        price = _extract_price_value(
            lot.get(key)
        )

        if price is not None:

            return price

    return float(
        DEFAULT_AUCTION_PRICE
    )


# ============================================================
# RARITY DETECTION
# ============================================================

RARITY_KEYS = {

    "rarity",

    "rarityname",

    "rarity_name",

    "itemrarity",

    "item_rarity",

    "qualityrarity",

    "quality_rarity",

    "quality",

    "grade",

}


def find_rarity_recursive(
    obj: Any,
    depth: int = 0,
) -> Optional[str]:

    if depth > 10:

        return None

    if isinstance(
        obj,
        dict,
    ):

        for key, value in obj.items():

            normalized_key = (
                str(key)
                .replace(
                    "-",
                    "_",
                )
                .replace(
                    " ",
                    "_",
                )
                .lower()
            )

            compact_key = (
                normalized_key
                .replace(
                    "_",
                    "",
                )
            )

            if (
                normalized_key
                in RARITY_KEYS
                or compact_key
                in RARITY_KEYS
            ):

                rarity = (
                    normalize_rarity(
                        value
                    )
                )

                if rarity:

                    return rarity

        for value in obj.values():

            result = (
                find_rarity_recursive(
                    value,
                    depth + 1,
                )
            )

            if result:

                return result

    elif isinstance(
        obj,
        list,
    ):

        for item in obj:

            result = (
                find_rarity_recursive(
                    item,
                    depth + 1,
                )
            )

            if result:

                return result

    return None


def get_lot_rarity(
    lot: dict,
) -> Optional[str]:

    rarity = (
        find_rarity_recursive(
            lot
        )
    )

    if rarity:

        return rarity

    additional = lot.get(
        "additional"
    )

    if additional:

        rarity = (
            find_rarity_recursive(
                additional
            )
        )

        if rarity:

            return rarity

    return None


# ============================================================
# COLLECT RARITY PRICES
# ============================================================

def collect_rarity_prices(
    lots: list[dict],
) -> dict[str, float]:

    result: dict[
        str,
        float,
    ] = {}

    for lot in lots:

        if not isinstance(
            lot,
            dict,
        ):

            continue

        rarity = get_lot_rarity(
            lot
        )

        if not rarity:

            continue

        price = get_lot_buyout_price(
            lot
        )

        old_price = result.get(
            rarity
        )

        if (
            old_price is None
            or price < old_price
        ):

            result[rarity] = price

    return result


# ============================================================
# AUCTION PRICE FOR SNIPER
# ============================================================

async def fetch_auction_price(
    item_id: str,
    rarity: Optional[str] = None,
) -> Optional[float]:

    lots = await fetch_auction_lots(
        item_id,
        force_refresh=True,
    )

    if not lots:

        return None

    target_rarity = normalize_rarity(
        rarity
    )

    min_price: Optional[
        float
    ] = None

    for lot in lots:

        if not isinstance(
            lot,
            dict,
        ):

            continue

        lot_rarity = get_lot_rarity(
            lot
        )

        if target_rarity:

            if (
                lot_rarity
                != target_rarity
            ):

                continue

        elif not lot_rarity:

            continue

        price = get_lot_buyout_price(
            lot
        )

        if (
            min_price is None
            or price < min_price
        ):

            min_price = price

    return min_price


# ============================================================
# LOCAL ITEMS
# ============================================================

async def load_tracked_items() -> list[dict]:

    """
    ВАЖНО:

    Источник списка предметов —
    только официальная локальная база:

        stalzone-database/ru/items/artefact

    Supabase.items здесь НЕ используется.

    Каждый элемент преобразуется в формат,
    который нужен коллектору.
    """

    items = []

    for local_item in local_database.get_all():

        item_id = str(
            local_item.get(
                "id",
                "",
            )
        ).strip()

        if not item_id:

            continue

        item_name = str(
            local_item.get(
                "name",
                "",
            )
        ).strip()

        items.append({

            "item_id":
                item_id,

            "name":
                item_name
                if item_name
                else item_id,

            "category":
                local_item.get(
                    "category"
                ),

        })

    logger.info(
        "Загружено предметов из официальной базы: %s",
        len(items),
    )

    return items


# ============================================================
# TELEGRAM
# ============================================================

async def send_telegram_message(
    chat_id: str | int,
    text: str,
) -> bool:

    if not BOT_TOKEN:

        logger.error(
            "BOT_TOKEN не установлен"
        )

        return False

    url = (
        "https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"
    )

    payload = {

        "chat_id":
            chat_id,

        "text":
            text,

    }

    try:

        async with httpx.AsyncClient(
            timeout=15
        ) as client:

            response = await client.post(
                url,
                json=payload,
            )

        if response.is_success:

            return True

        logger.warning(
            "Telegram API error: %s",
            response.text[:500],
        )

    except Exception as exc:

        logger.exception(
            "Ошибка отправки Telegram: %s",
            exc,
        )

    return False


# ============================================================
# SAVE PRICE
# ============================================================

async def save_price(
    item: dict,
    price: float,
    rarity: str,
) -> None:

    """
    Supabase используется здесь именно
    как хранилище результатов аукциона.

    Источник item_id/name —
    официальная локальная база.
    """

    try:

        payload = {

            "item_id": str(
                item.get(
                    "item_id"
                )
            ),

            "item_name": item.get(
                "name",
                "Unknown",
            ),

            "price": float(
                price
            ),

            "rarity": rarity,

        }

        (
            supabase
            .table("price_history")
            .insert(payload)
            .execute()
        )

    except Exception as exc:

        logger.exception(
            "Ошибка сохранения цены %s: %s",
            item.get(
                "item_id"
            ),
            exc,
        )


# ============================================================
# COLLECT ONE ITEM
# ============================================================

async def collect_item(
    item: dict,
) -> None:

    item_id = str(
        item.get(
            "item_id",
            "",
        )
    ).strip()

    item_name = (
        item.get(
            "name"
        )
        or item_id
    )

    if not item_id:

        return

    # --------------------------------------------------------
    # Дополнительная защита:
    # ID должен существовать в локальной официальной базе.
    # --------------------------------------------------------

    official_item = (
        local_database.get_by_id(
            item_id
        )
    )

    if official_item is None:

        logger.warning(
            "Пропуск неизвестного ID %s — "
            "его нет в официальной базе.",
            item_id,
        )

        return

    lots = await fetch_auction_lots(

        item_id,

        force_refresh=True,

    )

    if not lots:

        logger.debug(
            "На аукционе нет лотов: "
            "%s (%s)",
            item_name,
            item_id,
        )

        return

    rarity_prices = (
        collect_rarity_prices(
            lots
        )
    )

    if not rarity_prices:

        logger.debug(
            "Для %s (%s) не удалось "
            "определить цены по редкости.",
            item_name,
            item_id,
        )

        return

    for rarity, price in (
        rarity_prices.items()
    ):

        await save_price(

            item,

            price,

            rarity,

        )

        logger.info(

            "%s | ID=%s | %s | %s поинтов",

            item_name,

            item_id,

            rarity,

            f"{price:,.0f}",

        )


# ============================================================
# GENERAL COLLECTOR
# ============================================================

async def collect_all_items() -> None:

    # Получаем список ПРЯМО ИЗ LOCAL DATABASE.
    items = await load_tracked_items()

    if not items:

        logger.warning(
            "Список официальных предметов пуст."
        )

        return

    semaphore = asyncio.Semaphore(
        MAX_CONCURRENT_REQUESTS
    )

    async def worker(
        item: dict,
    ):

        async with semaphore:

            try:

                await collect_item(
                    item
                )

            except Exception as exc:

                logger.exception(
                    "Ошибка обработки item %s: %s",
                    item.get(
                        "item_id"
                    ),
                    exc,
                )

    await asyncio.gather(
        *(
            worker(item)
            for item in items
        )
    )


# ============================================================
# COLLECTION CYCLE
# ============================================================

async def sync_and_collect() -> None:

    """
    Один цикл коллектора:

    1. Берём официальные ID из
       stalzone-database.
    2. Проверяем эти ID через Auction API.
    3. Получаем лоты.
    4. Определяем минимальную цену каждой редкости.
    5. Сохраняем результат в Supabase.price_history.

    Никакой синхронизации официальной базы
    в Supabase.items здесь нет.
    """

    await collect_all_items()


# ============================================================
# SNIPER
# ============================================================

_sniper_last_alert: dict[
    int,
    float,
] = {}


async def load_snipers() -> list[dict]:

    """
    user_snipers — это пользовательские настройки,
    поэтому они правильно хранятся в Supabase.

    В таблице user_snipers нет поля enabled.
    """

    try:

        response = (
            supabase
            .table("user_snipers")
            .select("*")
            .execute()
        )

        snipers = (
            response.data
            or []
        )

        logger.debug(
            "Загружено снайперов: %s",
            len(snipers),
        )

        return snipers

    except Exception as exc:

        logger.exception(
            "Ошибка загрузки снайперов: %s",
            exc,
        )

        return []


async def monitor_snipers() -> None:

    snipers = await load_snipers()

    if not snipers:

        return

    semaphore = asyncio.Semaphore(
        MAX_CONCURRENT_REQUESTS
    )

    # --------------------------------------------------------
    # Уникальные ID
    # --------------------------------------------------------

    unique_ids: set[str] = set()

    for sniper in snipers:

        item_id = sniper.get(
            "item_id"
        )

        if item_id:

            item_id = str(
                item_id
            ).strip()

            # Снайпер тоже может работать
            # только с официальным ID.
            if local_database.get_by_id(
                item_id
            ) is not None:

                unique_ids.add(
                    item_id
                )

    # --------------------------------------------------------
    # Проверяем Auction API
    # --------------------------------------------------------

    async def check_id(
        item_id: str,
    ):

        async with semaphore:

            try:

                await fetch_auction_lots(
                    item_id
                )

            except Exception as exc:

                logger.exception(
                    "Ошибка проверки sniper ID %s: %s",
                    item_id,
                    exc,
                )

    await asyncio.gather(
        *(
            check_id(item_id)
            for item_id in unique_ids
        )
    )

    # --------------------------------------------------------
    # Обрабатываем снайперов
    # --------------------------------------------------------

    for sniper in snipers:

        sniper_id = sniper.get(
            "id"
        )

        item_id = sniper.get(
            "item_id"
        )

        if not item_id:

            continue

        item_id = str(
            item_id
        ).strip()

        # ----------------------------------------------------
        # ID обязан присутствовать
        # в официальной базе.
        # ----------------------------------------------------

        official_item = (
            local_database.get_by_id(
                item_id
            )
        )

        if official_item is None:

            logger.warning(
                "Снайпер %s содержит ID %s, "
                "которого нет в официальной базе.",
                sniper_id,
                item_id,
            )

            continue

        if item_id in _auction_invalid_ids:

            continue

        item_name = (

            sniper.get(
                "item_name"
            )

            or sniper.get(
                "name"
            )

            or official_item.get(
                "name"
            )

            or item_id

        )

        rarity = normalize_rarity(
            sniper.get(
                "rarity"
            )
        )

        if not rarity:

            logger.warning(
                "Снайпер %s имеет "
                "неизвестную редкость: %s",
                sniper_id,
                sniper.get(
                    "rarity"
                ),
            )

            continue

        # ----------------------------------------------------
        # THRESHOLD
        # ----------------------------------------------------

        threshold_value = (
            sniper.get(
                "threshold"
            )
        )

        # Совместимость со старым полем.
        if threshold_value is None:

            threshold_value = (
                sniper.get(
                    "max_price"
                )
            )

        if threshold_value is None:

            threshold_value = (
                sniper.get(
                    "price"
                )
            )

        try:

            threshold = float(
                threshold_value
            )

        except (
            TypeError,
            ValueError,
        ):

            logger.warning(
                "Некорректный threshold "
                "у снайпера %s",
                sniper_id,
            )

            continue

        # ----------------------------------------------------
        # CURRENT AUCTION PRICE
        # ----------------------------------------------------

        try:

            current_price = (
                await fetch_auction_price(
                    item_id,
                    rarity,
                )
            )

        except Exception as exc:

            logger.exception(
                "Ошибка получения цены "
                "для sniper %s: %s",
                sniper_id,
                exc,
            )

            continue

        if current_price is None:

            continue

        # ----------------------------------------------------
        # PRICE CHECK
        # ----------------------------------------------------

        if current_price > threshold:

            continue

        # ----------------------------------------------------
        # COOLDOWN
        # ----------------------------------------------------

        if sniper_id is not None:

            try:

                sniper_key = int(
                    sniper_id
                )

            except (
                TypeError,
                ValueError,
            ):

                sniper_key = hash(
                    str(
                        sniper_id
                    )
                )

            last_alert = (
                _sniper_last_alert.get(
                    sniper_key,
                    0,
                )
            )

            if (
                time.time()
                - last_alert
                < SNIPER_COOLDOWN
            ):

                continue

        else:

            sniper_key = None

        # ----------------------------------------------------
        # TELEGRAM ID
        # ----------------------------------------------------

        telegram_id = (

            sniper.get(
                "telegram_id"
            )

            or sniper.get(
                "user_id"
            )

        )

        if not telegram_id:

            continue

        # ----------------------------------------------------
        # MESSAGE
        # ----------------------------------------------------

        text = (

            "🎯 НАЙДЕН ЛОТ!\n\n"

            f"📦 {item_name}\n"

            f"🆔 ID: {item_id}\n"

            f"⭐ Редкость: {rarity}\n"

            f"💰 Цена: "
            f"{current_price:,.0f} поинтов\n"

            f"🎯 Ваш порог: "
            f"{threshold:,.0f} поинтов"

        )

        sent = await send_telegram_message(

            telegram_id,

            text,

        )

        if (
            sent
            and sniper_key is not None
        ):

            _sniper_last_alert[
                sniper_key
            ] = time.time()

            logger.info(

                "Снайпер сработал: "
                "%s | ID=%s | %s | %s поинтов",

                item_name,

                item_id,

                rarity,

                f"{current_price:,.0f}",

            )


# ============================================================
# MAIN LOOPS
# ============================================================

async def collector_loop() -> None:

    logger.info(
        "Запущен основной сборщик аукциона"
    )

    logger.info(
        "Путь официальной базы: %s",
        ARTIFACTS_DATABASE_PATH,
    )

    logger.info(
        "Предметов в официальной базе: %s",
        len(
            local_database.items_by_id
        ),
    )

    # --------------------------------------------------------
    # Первый запуск сразу.
    # --------------------------------------------------------

    try:

        await sync_and_collect()

    except Exception as exc:

        logger.exception(
            "Ошибка первого цикла collector: %s",
            exc,
        )

    # --------------------------------------------------------
    # Основной цикл.
    # --------------------------------------------------------

    while True:

        started = time.time()

        try:

            await sync_and_collect()

        except Exception as exc:

            logger.exception(
                "Ошибка collector loop: %s",
                exc,
            )

        elapsed = (
            time.time()
            - started
        )

        sleep_time = max(

            1,

            COLLECT_INTERVAL
            - elapsed,

        )

        await asyncio.sleep(
            sleep_time
        )


async def sniper_loop() -> None:

    logger.info(
        "Запущен мониторинг снайперов"
    )

    while True:

        started = time.time()

        try:

            await monitor_snipers()

        except Exception as exc:

            logger.exception(
                "Ошибка sniper loop: %s",
                exc,
            )

        elapsed = (
            time.time()
            - started
        )

        sleep_time = max(

            1,

            SNIPER_INTERVAL
            - elapsed,

        )

        await asyncio.sleep(
            sleep_time
        )


# ============================================================
# MAIN
# ============================================================

async def main():

    logger.info(
        "STALZONE Auction Collector запускается..."
    )

    logger.info(
        "Регион STALCRAFT: %s",
        STALCRAFT_REGION,
    )

    logger.info(
        "Auction API: %s",
        AUCTION_API_URL,
    )

    logger.info(
        "Официальная база: %s",
        ARTIFACTS_DATABASE_PATH,
    )

    logger.info(
        "Предметов в официальной базе: %s",
        len(
            local_database.items_by_id
        ),
    )

    await asyncio.gather(

        collector_loop(),

        sniper_loop(),

    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        logger.info(
            "Collector остановлен."
        )
