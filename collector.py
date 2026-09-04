import os
import json
import time
import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

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
# ЛОГИРОВАНИЕ
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
    name for name, value in required_env.items()
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
# ОФИЦИАЛЬНАЯ ЛОКАЛЬНАЯ БАЗА STALZONE
# ============================================================

class LocalItemDatabase:
    """
    Официальная локальная база предметов.

    ВАЖНО:
    Именно эта база является источником:
      - item_id
      - названия
      - цвета
      - списка предметов

    Supabase.items здесь НЕ используется как источник предметов.
    """

    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        self.items: Dict[str, Dict[str, Any]] = {}

        logger.info(
            "Путь официальной базы: %s",
            self.base_path
        )

        self.load()

    def load(self) -> None:
        if not self.base_path.exists():
            raise FileNotFoundError(
                f"Не найдена официальная база: {self.base_path}"
            )

        json_files = list(self.base_path.rglob("*.json"))

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

                item_id = data.get("id")

                if not item_id:
                    continue

                name_data = data.get("name", {})
                lines = name_data.get("lines", {})

                name_ru = (
                    lines.get("ru")
                    or lines.get("en")
                    or item_id
                )

                name_en = (
                    lines.get("en")
                    or name_ru
                )

                color = data.get("color")

                category = data.get(
                    "category",
                    "artefact"
                )

                self.items[item_id] = {
                    "id": item_id,
                    "name": name_ru,
                    "name_ru": name_ru,
                    "name_en": name_en,
                    "color": color,
                    "category": category,
                    "file": str(file_path),
                }

            except Exception as e:
                logger.warning(
                    "Ошибка чтения %s: %s",
                    file_path,
                    e
                )

        logger.info(
            "Официальная база: %s",
            self.base_path
        )

        logger.info(
            "Официальная база артефактов загружена: %d",
            len(self.items)
        )

    def get_item(
        self,
        item_id: str
    ) -> Optional[Dict[str, Any]]:
        return self.items.get(item_id)

    def get_all_items(self) -> List[Dict[str, Any]]:
        return list(self.items.values())

    def get_item_ids(self) -> List[str]:
        return list(self.items.keys())


# ============================================================
# ЦВЕТ → РЕДКОСТЬ
# ============================================================

COLOR_TO_RARITY = {
    "DEFAULT": "default",
    "GREEN": "green",
    "BLUE": "blue",
    "PURPLE": "purple",
    "GOLD": "gold",
    "YELLOW": "gold",
    "RED": "red",

    # Возможные альтернативные обозначения
    "UNCOMMON": "green",
    "RARE": "blue",
    "EPIC": "purple",
    "LEGENDARY": "gold",
    "UNIQUE": "red",

    "QUALITY_DEFAULT": "default",
    "QUALITY_GREEN": "green",
    "QUALITY_BLUE": "blue",
    "QUALITY_PURPLE": "purple",
    "QUALITY_GOLD": "gold",
    "QUALITY_RED": "red",
}


def normalize_color(color: Any) -> str:
    if color is None:
        return "DEFAULT"

    value = str(color).strip().upper()

    if not value:
        return "DEFAULT"

    return value


def get_item_rarity(
    item_id: str,
    local_db: LocalItemDatabase
) -> str:

    item = local_db.get_item(item_id)

    if not item:
        return "default"

    color = normalize_color(
        item.get("color")
    )

    rarity = COLOR_TO_RARITY.get(
        color,
        "default"
    )

    return rarity


# ============================================================
# OAUTH TOKEN
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

    url = "https://exbo.net/oauth/token"

    data = {
        "grant_type": "client_credentials",
        "client_id": STALCRAFT_CLIENT_ID,
        "client_secret": STALCRAFT_CLIENT_SECRET,
    }

    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT
    ) as client:

        response = await client.post(
            url,
            data=data
        )

        response.raise_for_status()

        result = response.json()

    access_token = result.get("access_token")

    if not access_token:
        raise RuntimeError(
            "OAuth не вернул access_token"
        )

    expires_in = int(
        result.get("expires_in", 3600)
    )

    _token = access_token

    # Обновляем немного заранее
    _token_expires_at = (
        time.time()
        + max(expires_in - 60, 60)
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

    for attempt in range(1, MAX_RETRIES + 1):

        try:
            token = await get_access_token()

            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            }

            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT
            ) as client:

                response = await client.get(
                    url,
                    params=params,
                    headers=headers
                )

            # Токен протух
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

            response.raise_for_status()

            data = response.json()

            # API может возвращать список
            if isinstance(data, list):
                lots = data

            # Или объект с lots
            elif isinstance(data, dict):
                lots = data.get("lots", [])

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
                "Auction API ERROR | ID=%s | "
                "попытка=%d/%d | %s",
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
# ПОЛУЧЕНИЕ BUYOUT PRICE
# ============================================================

def extract_buyout_price(
    lot: Dict[str, Any]
) -> Optional[float]:

    """
    Берём ТОЛЬКО реальную цену выкупа.

    Никаких искусственных fallback-цен.
    """

    possible_keys = [
        "buyoutPrice",
        "buyout_price",
        "buyout",
        "price",
    ]

    # Сначала основной объект
    for key in possible_keys:

        value = lot.get(key)

        if value is not None:
            try:
                price = float(value)

                if price > 0:
                    return price

            except (
                TypeError,
                ValueError
            ):
                pass

    # Затем additional
    additional = lot.get(
        "additional",
        {}
    )

    if isinstance(additional, dict):

        for key in possible_keys:

            value = additional.get(key)

            if value is not None:
                try:
                    price = float(value)

                    if price > 0:
                        return price

                except (
                    TypeError,
                    ValueError
                ):
                    pass

    return None


# ============================================================
# КОЛИЧЕСТВО ПРЕДМЕТОВ В ЛОТЕ
# ============================================================

def get_lot_amount(
    lot: Dict[str, Any]
) -> int:

    value = lot.get("amount")

    if value is None:

        additional = lot.get(
            "additional",
            {}
        )

        if isinstance(additional, dict):
            value = additional.get(
                "amount"
            )

    try:
        amount = int(value)

        if amount > 0:
            return amount

    except (
        TypeError,
        ValueError
    ):
        pass

    return 1


# ============================================================
# СТАТИСТИКА ПРЕДМЕТА
# ============================================================

async def collect_item_statistics(
    item_id: str,
    local_db: LocalItemDatabase
) -> Optional[Dict[str, Any]]:

    item = local_db.get_item(item_id)

    if not item:
        logger.warning(
            "Предмет отсутствует в официальной базе | ID=%s",
            item_id
        )

        return None

    item_name = item.get(
        "name",
        item_id
    )

    color = normalize_color(
        item.get("color")
    )

    rarity = COLOR_TO_RARITY.get(
        color,
        "default"
    )

    lots = await fetch_auction_lots(
        item_id
    )

    if lots is None:
        return None

    prices: List[float] = []

    for lot in lots:

        if not isinstance(lot, dict):
            continue

        price = extract_buyout_price(
            lot
        )

        if price is not None and price > 0:
            prices.append(price)

    if not prices:

        logger.info(
            "ID=%s | %s | "
            "нет активных лотов с buyout",
            item_id,
            item_name
        )

        return None

    prices.sort()

    min_buyout_price = prices[0]

    total_lots = len(prices)

    logger.info(
        "ID=%s | %s | "
        "цвет=%s | редкость=%s | "
        "min=%s | лотов=%d",
        item_id,
        item_name,
        color,
        rarity,
        min_buyout_price,
        total_lots
    )

    return {
        "item_id": item_id,
        "item_name": item_name,
        "rarity": rarity,
        "color": color,
        "category": "artefact",
        "variant": None,

        "min_buyout_price": min_buyout_price,
        "total_lots": total_lots,

        "buyout_prices": prices,
    }


# ============================================================
# СОХРАНЕНИЕ В SUPABASE
# ============================================================

async def save_price_history(
    statistics: Dict[str, Any]
) -> bool:

    item_id = statistics["item_id"]
    item_name = statistics["item_name"]
    rarity = statistics["rarity"]

    # ========================================================
    # ВАЖНО:
    # Supabase price_history:
    #
    # min_buyout_price -> BIGINT
    # buyout_price     -> BIGINT
    #
    # Поэтому здесь обязательно int().
    # ========================================================

    min_buyout_price = int(
        round(
            float(
                statistics["min_buyout_price"]
            )
        )
    )

    total_lots = int(
        statistics["total_lots"]
    )

    category = statistics.get(
        "category",
        "artefact"
    )

    variant = statistics.get(
        "variant"
    )

    # Сейчас buyout_price =
    # минимальная цена выкупа.
    buyout_price = int(
        min_buyout_price
    )

    payload = {
        "item_id": item_id,
        "item_name": item_name,

        "min_buyout_price": min_buyout_price,
        "total_lots": total_lots,

        "rarity": rarity,
        "category": category,
        "variant": variant,

        "buyout_price": buyout_price,
    }

    try:

        await asyncio.to_thread(
            lambda: (
                supabase
                .table("price_history")
                .insert(payload)
                .execute()
            )
        )

        logger.info(
            "SUPABASE OK | price_history | "
            "ID=%s | %s | min=%d | lots=%d",
            item_id,
            rarity,
            min_buyout_price,
            total_lots
        )

        return True

    except Exception as e:

        logger.error(
            "SUPABASE ERROR | price_history | "
            "payload=%s | error=%s",
            payload,
            e
        )

        return False


# ============================================================
# МОНИТОРИНГ СНАЙПЕРОВ
# ============================================================

async def monitor_snipers(
    local_db: LocalItemDatabase
) -> None:

    try:

        result = await asyncio.to_thread(
            lambda: (
                supabase
                .table("user_snipers")
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

    items = local_db.get_all_items()

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

        successful = 0
        saved = 0

        for item in items:

            item_id = item["id"]

            try:

                statistics = (
                    await collect_item_statistics(
                        item_id,
                        local_db
                    )
                )

                if statistics is None:
                    continue

                successful += 1

                # =================================================
                # ЛОГ ПЕРВОГО ЛОТА
                # =================================================

                if not first_lot_logged:

                    lots = await fetch_auction_lots(
                        item_id
                    )

                    if lots:

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

                # =================================================
                # СУПАБЕЙЗ
                # =================================================

                if await save_price_history(
                    statistics
                ):
                    saved += 1

            except Exception as e:

                logger.exception(
                    "Ошибка обработки ID=%s: %s",
                    item_id,
                    e
                )

            await asyncio.sleep(
                REQUEST_DELAY
            )

        # ========================================================
        # СНАЙПЕРЫ
        # ========================================================

        await monitor_snipers(
            local_db
        )

        cycle_time = (
            time.time()
            - cycle_start
        )

        logger.info(
            "========== ЦИКЛ ЗАВЕРШЁН =========="
        )

        logger.info(
            "Обработано успешно: %d/%d",
            successful,
            len(items)
        )

        logger.info(
            "Записано в price_history: %d",
            saved
        )

        logger.info(
            "Время цикла: %.2f сек.",
            cycle_time
        )

        sleep_time = max(
            0,
            COLLECT_INTERVAL - cycle_time
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
# ЗАПУСК
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
