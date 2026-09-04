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

SUPABASE_URL = os.getenv(
    "SUPABASE_URL",
    "https://mdursbqpogprwzbhjzxz.supabase.co",
)

SUPABASE_KEY = os.getenv(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1kdXJzYnFwb2dwcnd6Ymhqenh6Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NzE0MzU5NCwiZXhwIjoyMTAyNzE5NTk0fQ.AXb2IUi3VOY1hNHxrvZUpsk4f6ycGDc2qaC_4zzM1Mo",
)

BOT_TOKEN = os.getenv(
    "BOT_TOKEN",
    "8877726623:AAEV6YFhuuBnzKWiJZxwiWM49khiaxazwRE",
)

STALCRAFT_CLIENT_ID = os.getenv(
    "STALCRAFT_CLIENT_ID",
    "3919",
)

STALCRAFT_CLIENT_SECRET = os.getenv(
    "STALCRAFT_CLIENT_SECRET",
    "ayazYFVWHuFnpWBvOAYWWvEDykdntMOgDNNppKTl",
)

STALCRAFT_REGION = os.getenv(
    "STALCRAFT_REGION",
    "ru",
)

AUCTION_API_URL = (
    f"https://eapi.stalcraft.net/{STALCRAFT_REGION}/auction"
)

OAUTH_URL = "https://exbo.net/oauth/token"


# ============================================================
# INTERVALS
# ============================================================

COLLECT_INTERVAL = 60
SNIPER_INTERVAL = 10
SNIPER_COOLDOWN = 300

MAX_CONCURRENT_REQUESTS = 3


# ============================================================
# LOCAL DATABASE
# ============================================================

DATABASE_PATH = (
    Path(__file__).resolve().parent
    / "stalzone-database"
    / "ru"
    / "items"
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
# SUPABASE
# ============================================================

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

    if isinstance(value, (int, float)):

        try:
            return RARITY_BY_NUMBER.get(
                int(value)
            )

        except Exception:
            return None

    value = str(value).strip()

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
    """
    Локальная база предметов из:

        stalzone-database/ru/items

    Индексы:

        id -> item
        name -> список item
    """

    def __init__(
        self,
        base_dir: Path,
    ):

        self.base_dir = base_dir

        self.items_by_id: dict[str, dict] = {}
        self.items_by_name: dict[str, list[dict]] = {}

        self._load()

    @staticmethod
    def normalize_name(
        name: Any,
    ) -> str:

        if name is None:
            return ""

        return (
            str(name)
            .strip()
            .lower()
        )

    def _load(self) -> None:

        if not self.base_dir.exists():

            logger.error(
                "Локальная база предметов не найдена: %s",
                self.base_dir,
            )

            return

        loaded = 0

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
                    continue

                item_id = data.get("id")

                if not item_id:
                    continue

                item_id = str(
                    item_id
                ).strip()

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

                item = {
                    "id": item_id,
                    "name": ru_name,
                    "category": data.get(
                        "category"
                    ),
                    "color": data.get(
                        "color"
                    ),
                    "file": str(
                        file_path
                    ),
                }

                self.items_by_id[
                    item_id
                ] = item

                if ru_name:

                    name_key = (
                        self.normalize_name(
                            ru_name
                        )
                    )

                    self.items_by_name.setdefault(
                        name_key,
                        [],
                    ).append(
                        item
                    )

                loaded += 1

            except Exception as exc:

                logger.debug(
                    "Не удалось прочитать %s: %s",
                    file_path,
                    exc,
                )

        logger.info(
            "Локальная база предметов загружена: %s",
            loaded,
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

    def find_by_name(
        self,
        name: Any,
    ) -> list[dict]:

        name_key = (
            self.normalize_name(
                name
            )
        )

        if not name_key:
            return []

        return list(
            self.items_by_name.get(
                name_key,
                [],
            )
        )


local_database = LocalItemDatabase(
    DATABASE_PATH
)


# ============================================================
# ITEM ID RESOLUTION
# ============================================================

# Кэш:
#
# исходный ID -> проверенный ID
#
# None означает, что ID не найден.
_resolved_item_ids: dict[
    str,
    Optional[str],
] = {}

# Невалидные ID API.
#
# Они больше не будут отправляться на API
# каждые 10 секунд.
_invalid_item_ids: set[str] = set()

# Проверенные рабочие ID.
_valid_item_ids: set[str] = set()


def resolve_local_item_id(
    item: dict,
) -> Optional[str]:

    """
    Получает правильный ID предмета
    из локальной stalzone-database.

    Приоритет:

    1. ID из Supabase, если он существует
       в локальной базе.
    2. Поиск по точному названию.
    3. Старый ID как последний вариант.
    """

    original_id = str(
        item.get("item_id", "")
    ).strip()

    item_name = (
        item.get("name")
        or item.get("item_name")
        or ""
    )

    cache_key = (
        original_id
        or str(item_name)
    )

    if cache_key in _resolved_item_ids:

        return _resolved_item_ids[
            cache_key
        ]

    # --------------------------------------------------------
    # Сначала проверяем ID из Supabase
    # --------------------------------------------------------

    if original_id:

        local_item = (
            local_database.get_by_id(
                original_id
            )
        )

        if local_item:

            _resolved_item_ids[
                cache_key
            ] = original_id

            return original_id

    # --------------------------------------------------------
    # Затем ищем по точному названию
    # --------------------------------------------------------

    candidates = (
        local_database.find_by_name(
            item_name
        )
    )

    if candidates:

        if len(candidates) == 1:

            resolved_id = str(
                candidates[0]["id"]
            )

            logger.info(
                "ID предмета восстановлен "
                "по названию: %s -> %s",
                item_name,
                resolved_id,
            )

            _resolved_item_ids[
                cache_key
            ] = resolved_id

            return resolved_id

        logger.warning(
            "Для предмета '%s' найдено "
            "%s вариантов ID.",
            item_name,
            len(candidates),
        )

        # Первый кандидат пока является
        # основным.
        resolved_id = str(
            candidates[0]["id"]
        )

        _resolved_item_ids[
            cache_key
        ] = resolved_id

        return resolved_id

    # --------------------------------------------------------
    # Если локальная база не знает предмет,
    # возвращаем исходный ID.
    # --------------------------------------------------------

    if original_id:

        _resolved_item_ids[
            cache_key
        ] = original_id

        return original_id

    return None


# ============================================================
# OAUTH
# ============================================================

_access_token: Optional[str] = None
_access_token_expires_at: float = 0

_token_lock = asyncio.Lock()


async def get_access_token() -> str:

    global _access_token
    global _access_token_expires_at

    async with _token_lock:

        now = time.time()

        if (
            _access_token
            and now
            < _access_token_expires_at - 30
        ):
            return _access_token

        payload = {
            "grant_type": "client_credentials",
            "client_id": STALCRAFT_CLIENT_ID,
            "client_secret": STALCRAFT_CLIENT_SECRET,
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

        _access_token = data[
            "access_token"
        ]

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
    tuple[float, list[dict]],
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
        time.time() - timestamp
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
# AUCTION REQUEST
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

    # --------------------------------------------------------
    # Не отправляем заведомо невалидные ID
    # --------------------------------------------------------

    if item_id in _invalid_item_ids:

        return []

    # --------------------------------------------------------
    # Кэш
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
        "sort": "buyout_price",
        "order": "asc",
        "additional": "true",
    }

    headers = {
        "Authorization": (
            f"Bearer {token}"
        ),
        "Accept": "application/json",
    }

    for attempt in range(4):

        try:

            async with httpx.AsyncClient(
                timeout=20
            ) as client:

                response = await client.get(
                    url,
                    params=params,
                    headers=headers,
                )

            # ------------------------------------------------
            # Token expired
            # ------------------------------------------------

            if response.status_code == 401:

                _access_token = None
                _access_token_expires_at = 0

                token = (
                    await get_access_token()
                )

                headers[
                    "Authorization"
                ] = (
                    f"Bearer {token}"
                )

                continue

            # ------------------------------------------------
            # Rate limit
            # ------------------------------------------------

            if response.status_code == 429:

                wait_time = min(
                    2 ** attempt,
                    10,
                )

                logger.warning(
                    "STALCRAFT API rate limit. "
                    "Ждём %s сек.",
                    wait_time,
                )

                await asyncio.sleep(
                    wait_time
                )

                continue

            # ------------------------------------------------
            # Server error
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
            # Invalid item ID
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
                        ""
                    )
                ).lower()

                if (
                    "invalid item id"
                    in title
                ):

                    _invalid_item_ids.add(
                        item_id
                    )

                    logger.warning(
                        "ID %s признан "
                        "невалидным Auction API "
                        "и добавлен в кэш "
                        "невалидных ID.",
                        item_id,
                    )

                else:

                    logger.warning(
                        "STALCRAFT API "
                        "вернул 400 для %s: %s",
                        item_id,
                        response.text[:500],
                    )

                return []

            # ------------------------------------------------
            # Success
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

            _valid_item_ids.add(
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
# FIND WORKING AUCTION ID
# ============================================================

async def find_working_auction_id(
    item: dict,
) -> Optional[str]:

    """
    Проверяет ID предмета из локальной базы
    через Auction API.

    Если ID невалиден, пробует остальные
    варианты из локальной базы с тем же названием.
    """

    original_id = str(
        item.get("item_id", "")
    ).strip()

    item_name = (
        item.get("name")
        or item.get("item_name")
        or ""
    )

    # --------------------------------------------------------
    # Получаем локальный ID
    # --------------------------------------------------------

    local_id = (
        resolve_local_item_id(
            item
        )
    )

    candidates: list[str] = []

    if local_id:
        candidates.append(
            local_id
        )

    if (
        original_id
        and original_id not in candidates
    ):
        candidates.append(
            original_id
        )

    # --------------------------------------------------------
    # Все кандидаты с таким названием
    # --------------------------------------------------------

    local_candidates = (
        local_database.find_by_name(
            item_name
        )
    )

    for candidate in local_candidates:

        candidate_id = str(
            candidate.get("id", "")
        ).strip()

        if (
            candidate_id
            and candidate_id
            not in candidates
        ):

            candidates.append(
                candidate_id
            )

    if not candidates:

        logger.warning(
            "Не найден ID в stalzone-database "
            "для предмета '%s'.",
            item_name,
        )

        return None

    # --------------------------------------------------------
    # Проверяем кандидатов
    # --------------------------------------------------------

    for candidate_id in candidates:

        if candidate_id in _invalid_item_ids:
            continue

        # Если уже знаем, что ID рабочий,
        # не делаем дополнительный запрос.
        if candidate_id in _valid_item_ids:

            return candidate_id

        lots = await fetch_auction_lots(
            candidate_id
        )

        # ВАЖНО:
        # Пустой список не обязательно означает
        # невалидный ID.
        #
        # fetch_auction_lots сам добавляет ID
        # в _invalid_item_ids только при
        # "Invalid item id".
        if candidate_id not in _invalid_item_ids:

            _valid_item_ids.add(
                candidate_id
            )

            logger.info(
                "Auction ID подтверждён: "
                "%s -> %s",
                item_name,
                candidate_id,
            )

            return candidate_id

    logger.warning(
        "Не удалось найти рабочий Auction ID "
        "для предмета '%s'. "
        "Проверенные кандидаты: %s",
        item_name,
        candidates,
    )

    return None


# ============================================================
# PRICE PARSING
# ============================================================

def get_lot_buyout_price(
    lot: dict,
) -> Optional[float]:

    possible_keys = (
        "buyoutPrice",
        "buyout_price",
        "buyout",
        "price",
    )

    for key in possible_keys:

        value = lot.get(
            key
        )

        if value is None:
            continue

        if isinstance(
            value,
            dict,
        ):

            value = (
                value.get("amount")
                or value.get("value")
                or value.get("price")
            )

        try:

            price = float(
                value
            )

            if price > 0:
                return price

        except (
            TypeError,
            ValueError,
        ):

            continue

    return None


# ============================================================
# RARITY EXTRACTION
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

    if depth > 8:
        return None

    if isinstance(
        obj,
        dict,
    ):

        # Сначала проверяем известные ключи
        for key, value in obj.items():

            normalized_key = (
                str(key)
                .replace("-", "_")
                .replace(" ", "_")
                .lower()
            )

            compact_key = (
                normalized_key
                .replace("_", "")
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

        # Затем рекурсивно всё содержимое
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
# RARITY PRICES
# ============================================================

def collect_rarity_prices(
    lots: list[dict],
) -> dict[str, float]:

    result: dict[str, float] = {}

    for lot in lots:

        if not isinstance(
            lot,
            dict,
        ):
            continue

        price = (
            get_lot_buyout_price(
                lot
            )
        )

        if price is None:
            continue

        rarity = (
            get_lot_rarity(
                lot
            )
        )

        # Не угадываем редкость.
        if not rarity:
            continue

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
# AUCTION PRICE
# ============================================================

async def fetch_auction_price(
    item_id: str,
    rarity: Optional[str] = None,
) -> Optional[float]:

    lots = await fetch_auction_lots(
        item_id
    )

    if not lots:
        return None

    target_rarity = (
        normalize_rarity(
            rarity
        )
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

        price = (
            get_lot_buyout_price(
                lot
            )
        )

        if price is None:
            continue

        lot_rarity = (
            get_lot_rarity(
                lot
            )
        )

        if target_rarity:

            if (
                lot_rarity
                != target_rarity
            ):
                continue

        elif not lot_rarity:

            continue

        if (
            min_price is None
            or price < min_price
        ):

            min_price = price

    return min_price


# ============================================================
# ITEMS FROM SUPABASE
# ============================================================

async def load_tracked_items() -> list[dict]:

    try:

        response = (
            supabase
            .table("items")
            .select(
                "item_id,name,category"
            )
            .execute()
        )

        items = (
            response.data
            or []
        )

        logger.info(
            "Загружено предметов из Supabase: %s",
            len(items),
        )

        return items

    except Exception as exc:

        logger.exception(
            "Ошибка загрузки items: %s",
            exc,
        )

        return []


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
        "chat_id": chat_id,
        "text": text,
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
            item.get("item_id"),
            exc,
        )


# ============================================================
# COLLECT ONE ITEM
# ============================================================

async def collect_item(
    item: dict,
) -> None:

    # --------------------------------------------------------
    # Ищем рабочий Auction ID
    # --------------------------------------------------------

    auction_id = (
        await find_working_auction_id(
            item
        )
    )

    if not auction_id:

        logger.debug(
            "Рабочий Auction ID не найден: %s",
            item.get("name")
            or item.get("item_id"),
        )

        return

    # --------------------------------------------------------
    # Получаем лоты
    # --------------------------------------------------------

    lots = await fetch_auction_lots(
        auction_id,
        force_refresh=True,
    )

    if not lots:

        logger.debug(
            "Нет лотов для %s (%s)",
            item.get("name"),
            auction_id,
        )

        return

    # --------------------------------------------------------
    # Определяем цены по редкости
    # --------------------------------------------------------

    rarity_prices = (
        collect_rarity_prices(
            lots
        )
    )

    if not rarity_prices:

        logger.debug(
            "Не удалось определить "
            "редкость лотов %s",
            auction_id,
        )

        return

    # --------------------------------------------------------
    # Сохраняем цены
    # --------------------------------------------------------

    for rarity, price in (
        rarity_prices.items()
    ):

        save_item = dict(
            item
        )

        # ВАЖНО:
        # Сохраняем в историю рабочий ID,
        # который реально принял Auction API.
        save_item[
            "item_id"
        ] = auction_id

        await save_price(
            save_item,
            price,
            rarity,
        )

        logger.info(
            "%s | ID=%s | %s | %s",
            item.get(
                "name",
                auction_id,
            ),
            auction_id,
            rarity,
            price,
        )


# ============================================================
# GENERAL COLLECTOR
# ============================================================

async def sync_all_items_to_supabase() -> None:

    items = (
        await load_tracked_items()
    )

    if not items:

        logger.warning(
            "Список items пуст."
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
# SNIPER
# ============================================================

_sniper_last_alert: dict[
    int,
    float,
] = {}


async def load_snipers() -> list[dict]:

    """
    В таблице user_snipers НЕТ поля enabled.
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

    snipers = (
        await load_snipers()
    )

    if not snipers:
        return

    # ========================================================
    # Получаем рабочие ID предметов
    # ========================================================

    sniper_items: dict[
        str,
        dict,
    ] = {}

    for sniper in snipers:

        item_id = sniper.get(
            "item_id"
        )

        if not item_id:
            continue

        item_id = str(
            item_id
        ).strip()

        item_name = (
            sniper.get(
                "item_name"
            )
            or item_id
        )

        sniper_items.setdefault(
            item_id,
            {
                "item_id": item_id,
                "name": item_name,
                "category": None,
            },
        )

    if not sniper_items:
        return

    # ========================================================
    # Проверяем рабочие Auction ID
    # ========================================================

    semaphore = asyncio.Semaphore(
        MAX_CONCURRENT_REQUESTS
    )

    resolved_sniper_ids: dict[
        str,
        Optional[str],
    ] = {}

    async def resolve_sniper(
        original_id: str,
        item: dict,
    ):

        async with semaphore:

            try:

                resolved = (
                    await find_working_auction_id(
                        item
                    )
                )

                resolved_sniper_ids[
                    original_id
                ] = resolved

            except Exception as exc:

                logger.exception(
                    "Ошибка проверки "
                    "снайпера %s: %s",
                    original_id,
                    exc,
                )

                resolved_sniper_ids[
                    original_id
                ] = None

    await asyncio.gather(
        *(
            resolve_sniper(
                original_id,
                item,
            )
            for original_id, item
            in sniper_items.items()
        )
    )

    # ========================================================
    # Проверяем каждый снайпер
    # ========================================================

    for sniper in snipers:

        sniper_id = sniper.get(
            "id"
        )

        original_item_id = sniper.get(
            "item_id"
        )

        if not original_item_id:
            continue

        original_item_id = str(
            original_item_id
        ).strip()

        auction_id = (
            resolved_sniper_ids.get(
                original_item_id
            )
        )

        if not auction_id:
            continue

        item_name = (
            sniper.get(
                "item_name"
            )
            or original_item_id
        )

        rarity = (
            normalize_rarity(
                sniper.get(
                    "rarity"
                )
            )
        )

        if not rarity:

            logger.warning(
                "Снайпер %s имеет "
                "неизвестную редкость: %s",
                sniper_id,
                sniper.get("rarity"),
            )

            continue

        try:

            threshold = float(
                sniper.get(
                    "threshold"
                )
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
        # Цена
        # ----------------------------------------------------

        current_price = (
            await fetch_auction_price(
                auction_id,
                rarity,
            )
        )

        if current_price is None:
            continue

        if current_price > threshold:
            continue

        # ====================================================
        # COOLDOWN
        # ====================================================

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

        # ====================================================
        # TELEGRAM USER
        # ====================================================

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

        text = (
            "🎯 НАЙДЕН ЛОТ!\n\n"
            f"📦 {item_name}\n"
            f"⭐ Редкость: {rarity}\n"
            f"💰 Цена: "
            f"{current_price:,.0f} ₽\n"
            f"🎯 Ваш порог: "
            f"{threshold:,.0f} ₽"
        )

        sent = (
            await send_telegram_message(
                telegram_id,
                text,
            )
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
                "%s | ID=%s | %s | %s",
                item_name,
                auction_id,
                rarity,
                current_price,
            )


# ============================================================
# MAIN LOOPS
# ============================================================

async def collector_loop() -> None:

    logger.info(
        "Запущен основной сборщик аукциона"
    )

    while True:

        started = time.time()

        try:

            await sync_all_items_to_supabase()

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
        "Путь локальной базы: %s",
        DATABASE_PATH,
    )

    logger.info(
        "Предметов в локальной базе: %s",
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
