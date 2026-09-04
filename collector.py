import os
import json
import time
import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from supabase import create_client, Client


# ============================================================
# НАСТРОЙКИ
# ============================================================

REGION = os.getenv("STALCRAFT_REGION", "RU").upper()

AUCTION_API = os.getenv(
    "AUCTION_API",
    f"https://eapi.stalcraft.net/{REGION}/auction"
)

STALZONE_DATABASE_PATH = os.getenv(
    "STALZONE_DATABASE_PATH",
    "/app/stalzone-database/ru/items/artefact"
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

STALCRAFT_CLIENT_ID = os.getenv("STALCRAFT_CLIENT_ID")
STALCRAFT_CLIENT_SECRET = os.getenv("STALCRAFT_CLIENT_SECRET")

COLLECT_INTERVAL = int(os.getenv("COLLECT_INTERVAL", "300"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "30"))
AUCTION_LIMIT = int(os.getenv("AUCTION_LIMIT", "200"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "0.15"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))


# ============================================================
# ЛОГИ
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

logger = logging.getLogger("collector")


# ============================================================
# ПРОВЕРКА ENV
# ============================================================

required_env = {
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_KEY": SUPABASE_KEY,
    "STALCRAFT_CLIENT_ID": STALCRAFT_CLIENT_ID,
    "STALCRAFT_CLIENT_SECRET": STALCRAFT_CLIENT_SECRET,
}

missing_env = [
    key for key, value in required_env.items()
    if not value
]

if missing_env:
    raise RuntimeError(
        "Не заданы обязательные переменные окружения: "
        + ", ".join(missing_env)
    )


# ============================================================
# SUPABASE
# ============================================================

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)


# ============================================================
# СИСТЕМА РЕДКОСТЕЙ
# ============================================================

# Используем систему из второго коллектора,
# но определяем редкость конкретного лота через qlt.

QLT_TO_RARITY = {
    -1: "Обычный",
    0: "Обычный",
    1: "Необычный",
    2: "Особый",
    3: "Редкий",
    4: "Исключительный",
    5: "Легендарный",
}

ALL_RARITIES = [
    "Обычный",
    "Необычный",
    "Особый",
    "Редкий",
    "Исключительный",
    "Легендарный",
]


# Возможные названия качества внутри JSON
QUALITY_KEY_TO_RARITY = {
    "core.quality.common": "Обычный",
    "core.quality.uncommon": "Необычный",
    "core.quality.special": "Особый",
    "core.quality.rare": "Редкий",
    "core.quality.exclusive": "Исключительный",
    "core.quality.legendary": "Легендарный",
}


# ============================================================
# ЛОКАЛЬНАЯ БАЗА
# ============================================================

class LocalItemDatabase:

    def __init__(self, base_path: str):
        self.base_path = Path(base_path)

        # item_id -> данные
        self.items: Dict[str, Dict[str, Any]] = {}

        logger.info(
            "Путь официальной базы: %s",
            self.base_path
        )

        self.load()

    # --------------------------------------------------------
    # Загрузка
    # --------------------------------------------------------

    def load(self) -> None:

        if not self.base_path.exists():
            raise FileNotFoundError(
                f"Не найдена официальная база: {self.base_path}"
            )

        json_files = list(
            self.base_path.rglob("*.json")
        )

        logger.info(
            "Найдено JSON-файлов: %d",
            len(json_files)
        )

        for file_path in json_files:

            try:

                with open(
                    file_path,
                    "r",
                    encoding="utf-8"
                ) as f:
                    data = json.load(f)

            except Exception as e:

                logger.warning(
                    "Ошибка чтения %s: %s",
                    file_path,
                    e
                )

                continue

            item_id = data.get("id")

            if not item_id:
                continue

            name_data = data.get(
                "name",
                {}
            )

            if isinstance(name_data, dict):

                lines = name_data.get(
                    "lines",
                    {}
                )

                item_name = (
                    lines.get("ru")
                    or lines.get("en")
                    or item_id
                )

            else:

                item_name = str(
                    name_data or item_id
                )

            category = data.get(
                "category",
                "artefact"
            )

            color = data.get(
                "color",
                "DEFAULT"
            )

            # ------------------------------------------------
            # Вариант
            # ------------------------------------------------

            variant = self.detect_variant(
                file_path
            )

            # ------------------------------------------------
            # Качество из JSON
            # ------------------------------------------------

            json_rarity = self.detect_json_rarity(
                data
            )

            # ------------------------------------------------
            # Не перезаписываем полезный вариант
            # ------------------------------------------------

            if item_id not in self.items:

                self.items[item_id] = {
                    "id": item_id,
                    "name": item_name,
                    "name_ru": item_name,
                    "category": category,
                    "color": color,
                    "variant": variant,
                    "json_rarity": json_rarity,
                    "file": str(file_path),
                }

            else:

                current = self.items[item_id]

                if current.get("variant") == "0":
                    current["variant"] = variant

                if (
                    not current.get("json_rarity")
                    and json_rarity
                ):
                    current["json_rarity"] = json_rarity

        logger.info(
            "Официальная база: %s",
            self.base_path
        )

        logger.info(
            "Официальная база артефактов загружена: %d",
            len(self.items)
        )

    # --------------------------------------------------------
    # Определение варианта из пути
    # --------------------------------------------------------

    @staticmethod
    def detect_variant(
        file_path: Path
    ) -> str:

        parts = file_path.parts

        # Например:
        #
        # artefact/thermal/_variants/gy10/1.json
        #
        # variant = 1

        try:

            if "_variants" in parts:

                index = parts.index(
                    "_variants"
                )

                if index + 2 < len(parts):

                    variant = parts[index + 2]

                    if variant.endswith(".json"):
                        variant = variant[:-5]

                    if variant:
                        return str(variant)

        except Exception:
            pass

        return "0"

    # --------------------------------------------------------
    # Определение качества из JSON
    # --------------------------------------------------------

    @staticmethod
    def detect_json_rarity(
        data: Dict[str, Any]
    ) -> Optional[str]:

        def recursive_search(
            obj: Any
        ) -> Optional[str]:

            if isinstance(obj, dict):

                key = obj.get("key")

                if key in QUALITY_KEY_TO_RARITY:
                    return QUALITY_KEY_TO_RARITY[key]

                for value in obj.values():

                    result = recursive_search(
                        value
                    )

                    if result:
                        return result

            elif isinstance(obj, list):

                for value in obj:

                    result = recursive_search(
                        value
                    )

                    if result:
                        return result

            return None

        return recursive_search(data)

    # --------------------------------------------------------

    def get_item(
        self,
        item_id: str
    ) -> Optional[Dict[str, Any]]:

        return self.items.get(item_id)

    # --------------------------------------------------------

    def get_all_items(
        self
    ) -> List[Dict[str, Any]]:

        return list(
            self.items.values()
        )

    # --------------------------------------------------------

    def get_item_ids(
        self
    ) -> List[str]:

        return list(
            self.items.keys()
        )


# ============================================================
# ОПРЕДЕЛЕНИЕ РЕДКОСТИ ЛОТА
# ============================================================

def get_qlt(
    lot: Dict[str, Any]
) -> Optional[int]:

    additional = lot.get(
        "additional"
    )

    if not isinstance(
        additional,
        dict
    ):
        return None

    qlt = additional.get(
        "qlt"
    )

    if qlt is None:
        return None

    try:
        return int(qlt)

    except (
        TypeError,
        ValueError
    ):
        return None


def get_lot_rarity(
    lot: Dict[str, Any],
    item: Dict[str, Any]
) -> str:

    # --------------------------------------------------------
    # 1. Основной источник — qlt конкретного лота
    # --------------------------------------------------------

    qlt = get_qlt(lot)

    if qlt is not None:

        rarity = QLT_TO_RARITY.get(
            qlt
        )

        if rarity:
            return rarity

    # --------------------------------------------------------
    # 2. Если qlt отсутствует — качество из JSON
    # --------------------------------------------------------

    json_rarity = item.get(
        "json_rarity"
    )

    if json_rarity:
        return json_rarity

    # --------------------------------------------------------
    # 3. Запасной вариант — color
    # --------------------------------------------------------

    color = str(
        item.get(
            "color",
            "DEFAULT"
        )
    ).upper()

    color_map = {
        "DEFAULT": "Обычный",
        "GREEN": "Необычный",
        "BLUE": "Особый",
        "PURPLE": "Редкий",
        "GOLD": "Исключительный",
        "YELLOW": "Исключительный",
        "RED": "Легендарный",
        "UNCOMMON": "Необычный",
        "SPECIAL": "Особый",
        "RARE": "Редкий",
        "EXCLUSIVE": "Исключительный",
        "LEGENDARY": "Легендарный",
    }

    return color_map.get(
        color,
        "Обычный"
    )


# ============================================================
# TOKEN
# ============================================================

_token: Optional[str] = None
_token_expires_at: float = 0


async def get_access_token(
    force_refresh: bool = False
) -> str:

    global _token
    global _token_expires_at

    now = time.time()

    if (
        not force_refresh
        and _token
        and now < _token_expires_at
    ):
        return _token

    payload = {
        "client_id": STALCRAFT_CLIENT_ID,
        "client_secret": STALCRAFT_CLIENT_SECRET,
        "grant_type": "client_credentials",
    }

    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT
    ) as client:

        response = await client.post(
            "https://exbo.net/oauth/token",
            data=payload
        )

        response.raise_for_status()

        data = response.json()

    access_token = data.get(
        "access_token"
    )

    if not access_token:
        raise RuntimeError(
            "EXBO API не вернул access_token"
        )

    expires_in = int(
        data.get(
            "expires_in",
            3600
        )
    )

    _token = access_token

    _token_expires_at = (
        time.time()
        + max(
            expires_in - 60,
            60
        )
    )

    logger.info(
        "Получен новый STALCRAFT access token"
    )

    return _token


# ============================================================
# AUCTION API
# ============================================================

async def fetch_auction_lots(
    item_id: str
) -> Optional[List[Dict[str, Any]]]:

    url = (
        f"{AUCTION_API}/{item_id}/lots"
    )

    params = {
        "limit": AUCTION_LIMIT,
        "sort": "buyout_price",
        "order": "asc",
        "additional": "true",
    }

    for attempt in range(
        1,
        MAX_RETRIES + 1
    ):

        try:

            token = await get_access_token()

            headers = {
                "Authorization":
                    f"Bearer {token}",
                "Accept":
                    "application/json",
            }

            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT
            ) as client:

                response = await client.get(
                    url,
                    params=params,
                    headers=headers
                )

            if response.status_code == 401:

                logger.warning(
                    "Auction API 401 | ID=%s | "
                    "обновляем токен",
                    item_id
                )

                await get_access_token(
                    force_refresh=True
                )

                continue

            if response.status_code == 404:

                logger.warning(
                    "Auction API 404 | ID=%s",
                    item_id
                )

                return []

            response.raise_for_status()

            data = response.json()

            if isinstance(data, list):

                lots = data

            elif isinstance(data, dict):

                lots = data.get(
                    "lots",
                    []
                )

                if lots is None:
                    lots = []

            else:

                lots = []

            logger.info(
                "Auction API | ID=%s | лотов=%d",
                item_id,
                len(lots)
            )

            return lots

        except Exception as e:

            logger.warning(
                "Auction API ERROR | "
                "ID=%s | попытка=%d/%d | %s",
                item_id,
                attempt,
                MAX_RETRIES,
                e
            )

            if attempt < MAX_RETRIES:

                await asyncio.sleep(
                    attempt * 2
                )

    logger.error(
        "Auction API окончательно не ответил | ID=%s",
        item_id
    )

    return None


# ============================================================
# BUYOUT
# ============================================================

def extract_buyout_price(
    lot: Dict[str, Any]
) -> Optional[float]:

    keys = [
        "buyoutPrice",
        "buyout_price",
        "buyout",
    ]

    for key in keys:

        value = lot.get(
            key
        )

        if value is not None:

            try:

                price = float(
                    value
                )

                if price > 0:
                    return price

            except (
                TypeError,
                ValueError
            ):
                pass

    additional = lot.get(
        "additional"
    )

    if isinstance(
        additional,
        dict
    ):

        for key in keys:

            value = additional.get(
                key
            )

            if value is not None:

                try:

                    price = float(
                        value
                    )

                    if price > 0:
                        return price

                except (
                    TypeError,
                    ValueError
                ):
                    pass

    # ВАЖНО:
    # startPrice специально НЕ используем.
    # Нам нужна именно цена выкупа.

    return None


# ============================================================
# СТАТИСТИКА ПО РЕДКОСТЯМ
# ============================================================

async def collect_item_statistics(
    item_id: str,
    local_db: LocalItemDatabase
) -> List[Dict[str, Any]]:

    item = local_db.get_item(
        item_id
    )

    if not item:
        return []

    item_name = item.get(
        "name",
        item_id
    )

    lots = await fetch_auction_lots(
        item_id
    )

    if lots is None:
        return []

    # --------------------------------------------------------
    # rarity -> prices
    # --------------------------------------------------------

    rarity_prices: Dict[
        str,
        List[float]
    ] = {
        rarity: []
        for rarity in ALL_RARITIES
    }

    # --------------------------------------------------------
    # rarity -> количество лотов
    # --------------------------------------------------------

    rarity_lots: Dict[
        str,
        int
    ] = {
        rarity: 0
        for rarity in ALL_RARITIES
    }

    # --------------------------------------------------------
    # Обрабатываем каждый лот
    # --------------------------------------------------------

    for lot in lots:

        if not isinstance(
            lot,
            dict
        ):
            continue

        price = extract_buyout_price(
            lot
        )

        if price is None:
            continue

        rarity = get_lot_rarity(
            lot,
            item
        )

        if rarity not in rarity_prices:

            rarity = "Обычный"

        rarity_prices[
            rarity
        ].append(
            price
        )

        rarity_lots[
            rarity
        ] += 1

    # --------------------------------------------------------
    # Формируем записи только для реально
    # существующих редкостей
    # --------------------------------------------------------

    result = []

    for rarity in ALL_RARITIES:

        prices = rarity_prices[
            rarity
        ]

        if not prices:
            continue

        prices.sort()

        min_price = prices[0]

        result.append({
            "item_id": item_id,
            "item_name": item_name,
            "rarity": rarity,

            "category": "Артефакт",

            "variant": item.get(
                "variant",
                "0"
            ),

            "min_buyout_price":
                min_price,

            "total_lots":
                rarity_lots[rarity],

        })

    # --------------------------------------------------------
    # Лог
    # --------------------------------------------------------

    if result:

        parts = []

        for row in result:

            parts.append(
                f"{row['rarity']}="
                f"{int(row['min_buyout_price'])}"
                f"/{row['total_lots']}"
            )

        logger.info(
            "ID=%s | %s | %s",
            item_id,
            item_name,
            " | ".join(parts)
        )

    else:

        logger.info(
            "ID=%s | %s | "
            "нет лотов с buyout",
            item_id,
            item_name
        )

    return result


# ============================================================
# SUPABASE
# ============================================================

async def save_price_history(
    statistics: Dict[str, Any]
) -> bool:

    item_id = statistics[
        "item_id"
    ]

    item_name = statistics[
        "item_name"
    ]

    rarity = statistics[
        "rarity"
    ]

    min_buyout_price = int(
        round(
            float(
                statistics[
                    "min_buyout_price"
                ]
            )
        )
    )

    total_lots = int(
        statistics[
            "total_lots"
        ]
    )

    category = statistics.get(
        "category",
        "Артефакт"
    )

    variant = statistics.get(
        "variant",
        "0"
    )

    # --------------------------------------------------------
    # buyout_price тоже BIGINT
    # --------------------------------------------------------

    buyout_price = int(
        min_buyout_price
    )

    payload = {
        "item_id": item_id,
        "item_name": item_name,

        "min_buyout_price":
            min_buyout_price,

        "total_lots":
            total_lots,

        "rarity":
            rarity,

        "category":
            category,

        "variant":
            variant,

        "buyout_price":
            buyout_price,
    }

    try:

        await asyncio.to_thread(
            lambda: (
                supabase
                .table(
                    "price_history"
                )
                .insert(payload)
                .execute()
            )
        )

        logger.info(
            "SUPABASE OK | "
            "price_history | "
            "ID=%s | %s | "
            "variant=%s | "
            "min=%d | lots=%d",
            item_id,
            rarity,
            variant,
            min_buyout_price,
            total_lots
        )

        return True

    except Exception as e:

        logger.error(
            "SUPABASE ERROR | "
            "price_history | "
            "payload=%s | "
            "error=%s",
            payload,
            e
        )

        return False


# ============================================================
# СНАЙПЕРЫ
# ============================================================

async def monitor_snipers(
    local_db: LocalItemDatabase
) -> None:

    try:

        result = await asyncio.to_thread(
            lambda: (
                supabase
                .table(
                    "user_snipers"
                )
                .select("*")
                .execute()
            )
        )

        snipers = result.data or []

        logger.info(
            "Загружено настроек снайперов: %d",
            len(snipers)
        )

        for sniper in snipers:

            item_id = (
                sniper.get("item_id")
                or sniper.get("itemId")
            )

            if not item_id:
                continue

            if not local_db.get_item(
                item_id
            ):

                logger.warning(
                    "Снайпер содержит ID, "
                    "которого нет в официальной базе: %s",
                    item_id
                )

    except Exception as e:

        logger.error(
            "Ошибка чтения user_snipers: %s",
            e
        )


# ============================================================
# ОСНОВНОЙ ЦИКЛ
# ============================================================

async def collector_loop(
    local_db: LocalItemDatabase
) -> None:

    logger.info(
        "Запущен основной сборщик аукциона"
    )

    items = (
        local_db.get_all_items()
    )

    logger.info(
        "Загружено предметов "
        "из официальной базы: %d",
        len(items)
    )

    first_lot_logged = False

    while True:

        cycle_start = time.time()

        logger.info(
            "========== НОВЫЙ ЦИКЛ СБОРА =========="
        )

        successful_items = 0
        saved_rows = 0

        for item in items:

            item_id = item[
                "id"
            ]

            try:

                # ------------------------------------------------
                # Получаем API один раз
                # ------------------------------------------------

                lots = await fetch_auction_lots(
                    item_id
                )

                if lots is None:
                    continue

                # ------------------------------------------------
                # Первый пример лота
                # ------------------------------------------------

                if (
                    not first_lot_logged
                    and lots
                ):

                    logger.warning(
                        "========== ПРИМЕР ЛОТА "
                        "AUCTION API =========="
                    )

                    try:

                        logger.warning(
                            json.dumps(
                                lots[0],
                                ensure_ascii=False,
                                indent=2
                            )
                        )

                    except Exception:

                        logger.warning(
                            str(lots[0])
                        )

                    logger.warning(
                        "=============================================="
                    )

                    first_lot_logged = True

                # ------------------------------------------------
                # Собираем статистику напрямую из уже
                # полученных lots
                # ------------------------------------------------

                item_name = item.get(
                    "name",
                    item_id
                )

                rarity_prices: Dict[
                    str,
                    List[float]
                ] = {
                    rarity: []
                    for rarity in ALL_RARITIES
                }

                rarity_lots: Dict[
                    str,
                    int
                ] = {
                    rarity: 0
                    for rarity in ALL_RARITIES
                }

                for lot in lots:

                    if not isinstance(
                        lot,
                        dict
                    ):
                        continue

                    price = (
                        extract_buyout_price(
                            lot
                        )
                    )

                    if price is None:
                        continue

                    rarity = get_lot_rarity(
                        lot,
                        item
                    )

                    if rarity not in rarity_prices:
                        rarity = "Обычный"

                    rarity_prices[
                        rarity
                    ].append(price)

                    rarity_lots[
                        rarity
                    ] += 1

                item_had_data = False

                # ------------------------------------------------
                # Записываем каждую реально найденную редкость
                # отдельно
                # ------------------------------------------------

                for rarity in ALL_RARITIES:

                    prices = rarity_prices[
                        rarity
                    ]

                    if not prices:
                        continue

                    item_had_data = True

                    prices.sort()

                    min_price = prices[
                        0
                    ]

                    statistics = {
                        "item_id":
                            item_id,

                        "item_name":
                            item_name,

                        "rarity":
                            rarity,

                        "category":
                            "Артефакт",

                        "variant":
                            item.get(
                                "variant",
                                "0"
                            ),

                        "min_buyout_price":
                            min_price,

                        "total_lots":
                            rarity_lots[
                                rarity
                            ],
                    }

                    if await save_price_history(
                        statistics
                    ):
                        saved_rows += 1

                if item_had_data:
                    successful_items += 1

                    rarity_log = []

                    for rarity in ALL_RARITIES:

                        prices = rarity_prices[
                            rarity
                        ]

                        if not prices:
                            continue

                        rarity_log.append(
                            f"{rarity}="
                            f"{int(prices[0])}"
                            f"/"
                            f"{len(prices)}"
                        )

                    logger.info(
                        "ID=%s | %s | %s",
                        item_id,
                        item_name,
                        " | ".join(
                            rarity_log
                        )
                    )

            except Exception as e:

                logger.exception(
                    "Ошибка обработки ID=%s: %s",
                    item_id,
                    e
                )

            await asyncio.sleep(
                REQUEST_DELAY
            )

        # --------------------------------------------------------
        # Снайперы
        # --------------------------------------------------------

        await monitor_snipers(
            local_db
        )

        # --------------------------------------------------------
        # Итоги
        # --------------------------------------------------------

        cycle_time = (
            time.time()
            - cycle_start
        )

        logger.info(
            "========== ЦИКЛ ЗАВЕРШЁН =========="
        )

        logger.info(
            "Обработано предметов: %d/%d",
            successful_items,
            len(items)
        )

        logger.info(
            "Записано строк в price_history: %d",
            saved_rows
        )

        logger.info(
            "Время цикла: %.2f сек.",
            cycle_time
        )

        sleep_time = max(
            0,
            COLLECT_INTERVAL
            - cycle_time
        )

        logger.info(
            "Следующий цикл через %.2f сек.",
            sleep_time
        )

        await asyncio.sleep(
            sleep_time
        )


# ============================================================
# MAIN
# ============================================================

async def main() -> None:

    logger.info(
        "STALZONE Auction Collector запускается..."
    )

    logger.info(
        "Официальная база: %s",
        STALZONE_DATABASE_PATH
    )

    local_db = LocalItemDatabase(
        STALZONE_DATABASE_PATH
    )

    logger.info(
        "Предметов в официальной базе: %d",
        len(
            local_db.get_all_items()
        )
    )

    await collector_loop(
        local_db
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        logger.info(
            "Collector остановлен"
        )

    except Exception as e:

        logger.exception(
            "Критическая ошибка collector: %s",
            e
        )
