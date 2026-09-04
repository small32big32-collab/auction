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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger("auction_collector")


REGION = os.getenv("STALCRAFT_REGION", "RU").upper()

AUCTION_API = os.getenv(
    "AUCTION_API",
    f"https://eapi.stalcraft.net/{REGION}/auction",
)

DATABASE_PATH = os.getenv(
    "STALZONE_DATABASE_PATH",
    "/app/stalzone-database/ru/items/artefact",
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
        "Не заданы переменные окружения: "
        + ", ".join(missing_env)
    )


supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY,
)


# ============================================================
# ЛОКАЛЬНАЯ БАЗА STALZONE
# ============================================================

class LocalItemDatabase:
    """
    Официальная локальная база:
        stalzone-database/ru/items/artefact/**/*.json

    Она является ИСТОЧНИКОМ:
        - item_id
        - name
        - color

    Supabase.items здесь НЕ используется.
    """

    def __init__(self, root_path: str):
        self.root = Path(root_path)

        self.items: Dict[str, Dict[str, Any]] = {}

        self.load()

    # --------------------------------------------------------
    # Загрузка
    # --------------------------------------------------------

    def load(self):
        if not self.root.exists():
            raise FileNotFoundError(
                f"Официальная база не найдена: {self.root}"
            )

        json_files = list(self.root.rglob("*.json"))

        logger.info(
            "Путь официальной базы: %s",
            self.root,
        )

        logger.info(
            "Найдено JSON-файлов: %s",
            len(json_files),
        )

        for file_path in json_files:
            try:
                with open(
                    file_path,
                    "r",
                    encoding="utf-8",
                ) as f:
                    data = json.load(f)

                if not isinstance(data, dict):
                    continue

                item_id = data.get("id")

                if not item_id:
                    # Иногда ID может отсутствовать внутри JSON.
                    # Тогда используем имя файла.
                    item_id = file_path.stem

                item_id = str(item_id)

                name = self.extract_name(data)

                color = self.extract_color(data)

                self.items[item_id] = {
                    "item_id": item_id,
                    "name": name,
                    "color": color,
                    "raw": data,
                    "file": str(file_path),
                }

            except Exception as e:
                logger.warning(
                    "Ошибка чтения %s: %s",
                    file_path,
                    e,
                )

        logger.info(
            "Официальная база артефактов загружена: %s",
            len(self.items),
        )

    # --------------------------------------------------------
    # Имя
    # --------------------------------------------------------

    @staticmethod
    def extract_name(data: Dict[str, Any]) -> str:
        name = data.get("name")

        if isinstance(name, str):
            return name

        if isinstance(name, dict):
            lines = name.get("lines")

            if isinstance(lines, dict):
                if lines.get("ru"):
                    return str(lines["ru"])

                if lines.get("en"):
                    return str(lines["en"])

            if name.get("text"):
                return str(name["text"])

        return "Unknown"

    # --------------------------------------------------------
    # Цвет
    # --------------------------------------------------------

    @staticmethod
    def extract_color(data: Dict[str, Any]) -> str:
        """
        В официальной базе STALZONE есть поле:

            "color": "DEFAULT"

        Для артефактов это качество/редкость.
        """

        color = data.get("color")

        if color is None:
            return "DEFAULT"

        return str(color).upper()

    # --------------------------------------------------------
    # Получить предмет
    # --------------------------------------------------------

    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        return self.items.get(str(item_id))

    # --------------------------------------------------------
    # Все предметы
    # --------------------------------------------------------

    def get_all(self) -> List[Dict[str, Any]]:
        return list(self.items.values())


local_database = LocalItemDatabase(DATABASE_PATH)


# ============================================================
# ЦВЕТ → РЕДКОСТЬ
# ============================================================

COLOR_TO_RARITY = {
    # обычный
    "DEFAULT": "default",

    # зелёный
    "GREEN": "green",
    "QUALITY_UNCOMMON": "green",
    "UNCOMMON": "green",

    # синий
    "BLUE": "blue",
    "QUALITY_RARE": "blue",
    "RARE": "blue",

    # фиолетовый
    "PURPLE": "purple",
    "QUALITY_EPIC": "purple",
    "EPIC": "purple",

    # золотой / жёлтый
    "GOLD": "gold",
    "YELLOW": "gold",
    "QUALITY_LEGENDARY": "gold",
    "LEGENDARY": "gold",

    # красный
    "RED": "red",
    "QUALITY_UNIQUE": "red",
    "UNIQUE": "red",
}


def normalize_color(color: Any) -> str:
    if color is None:
        return "DEFAULT"

    return str(color).strip().upper()


def color_to_rarity(color: Any) -> str:
    normalized = normalize_color(color)

    return COLOR_TO_RARITY.get(
        normalized,
        normalized.lower(),
    )


# ============================================================
# OAUTH TOKEN
# ============================================================

_access_token: Optional[str] = None
_token_expires_at: float = 0


async def get_access_token(client: httpx.AsyncClient) -> str:
    global _access_token
    global _token_expires_at

    now = time.time()

    if _access_token and now < (_token_expires_at - 60):
        return _access_token

    response = await client.post(
        "https://exbo.net/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": STALCRAFT_CLIENT_ID,
            "client_secret": STALCRAFT_CLIENT_SECRET,
        },
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    _access_token = data["access_token"]

    expires_in = int(
        data.get("expires_in", 3600)
    )

    _token_expires_at = (
        time.time() + expires_in
    )

    logger.info(
        "Получен новый STALCRAFT access token"
    )

    return _access_token


# ============================================================
# AUCTION API
# ============================================================

async def fetch_auction_lots(
    client: httpx.AsyncClient,
    item_id: str,
) -> List[Dict[str, Any]]:

    token = await get_access_token(client)

    url = (
        f"{AUCTION_API}/"
        f"{item_id}/lots"
    )

    params = {
        "limit": AUCTION_LIMIT,
        "sort": "buyout_price",
        "order": "asc",
        "additional": "true",
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    for attempt in range(1, MAX_RETRIES + 1):

        try:
            response = await client.get(
                url,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )

            # Если токен протух
            if response.status_code == 401:
                global _access_token
                _access_token = None

                token = await get_access_token(client)

                headers["Authorization"] = (
                    f"Bearer {token}"
                )

                continue

            response.raise_for_status()

            data = response.json()

            if isinstance(data, dict):
                lots = data.get("lots")

                if lots is None:
                    lots = data.get("data")

                if lots is None:
                    lots = []

            elif isinstance(data, list):
                lots = data

            else:
                lots = []

            if not isinstance(lots, list):
                lots = []

            return [
                lot
                for lot in lots
                if isinstance(lot, dict)
            ]

        except Exception as e:

            logger.warning(
                "Auction API ошибка | ID=%s | попытка=%s/%s | %s",
                item_id,
                attempt,
                MAX_RETRIES,
                e,
            )

            if attempt < MAX_RETRIES:
                await asyncio.sleep(
                    attempt * 1.5
                )
            else:
                logger.error(
                    "Auction API окончательно не ответил | ID=%s",
                    item_id,
                )

    return []


# ============================================================
# ЦЕНА ЛОТА
# ============================================================

def extract_number(value: Any) -> Optional[float]:

    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        value = value.strip()

        if not value:
            return None

        try:
            return float(value)
        except ValueError:
            return None

    if isinstance(value, dict):

        for key in (
            "amount",
            "value",
            "price",
        ):
            if key in value:
                result = extract_number(
                    value[key]
                )

                if result is not None:
                    return result

    return None


def get_lot_buyout_price(
    lot: Dict[str, Any],
) -> Optional[float]:

    # Варианты названий, которые могут встречаться
    # в API.

    keys = (
        "buyoutPrice",
        "buyout_price",
        "buyout",
    )

    for key in keys:

        if key not in lot:
            continue

        price = extract_number(
            lot[key]
        )

        if price is not None:

            # 0 означает отсутствие цены выкупа.
            if price > 0:
                return price

    # Иногда цена может находиться
    # в price.

    if "price" in lot:

        price = extract_number(
            lot["price"]
        )

        if price is not None and price > 0:
            return price

    # Иногда цена находится в additional.

    additional = lot.get("additional")

    if isinstance(additional, dict):

        for key in (
            "buyoutPrice",
            "buyout_price",
            "buyout",
            "price",
        ):

            if key not in additional:
                continue

            price = extract_number(
                additional[key]
            )

            if price is not None and price > 0:
                return price

    # ВАЖНО:
    # Не подставляем выдуманную цену.
    return None


# ============================================================
# КОЛИЧЕСТВО
# ============================================================

def get_lot_amount(
    lot: Dict[str, Any],
) -> int:

    amount = lot.get("amount")

    if amount is None:

        additional = lot.get(
            "additional"
        )

        if isinstance(additional, dict):
            amount = additional.get(
                "amount",
                1,
            )

    try:
        amount = int(amount)

        if amount <= 0:
            return 1

        return amount

    except Exception:
        return 1


# ============================================================
# ЦВЕТ / РЕДКОСТЬ
# ============================================================

def get_item_rarity(
    item_id: str,
) -> Tuple[str, str]:

    item = local_database.get(item_id)

    if not item:
        return (
            "default",
            "DEFAULT",
        )

    color = item.get(
        "color",
        "DEFAULT",
    )

    rarity = color_to_rarity(
        color
    )

    return (
        rarity,
        normalize_color(color),
    )


# ============================================================
# АГРЕГАЦИЯ ЦЕН
# ============================================================

def collect_rarity_prices(
    item_id: str,
    lots: List[Dict[str, Any]],
) -> Dict[str, List[float]]:

    """
    Все лоты одного itemId относятся к одному
    предмету из официальной базы.

    Редкость берём из local database.color.

    Поэтому здесь результат:

        {
            "green": [100000, 120000],
        }

    """

    rarity, color = get_item_rarity(
        item_id
    )

    prices: List[float] = []

    for lot in lots:

        price = get_lot_buyout_price(
            lot
        )

        if price is None:
            continue

        amount = get_lot_amount(
            lot
        )

        # Цена лота сохраняется как цена всего лота.
        # Если позже потребуется цена за 1 штуку,
        # её можно отдельно рассчитать.
        prices.append(price)

    if not prices:
        return {}

    logger.info(
        "ID=%s | цвет=%s | редкость=%s | "
        "валидных цен=%s",
        item_id,
        color,
        rarity,
        len(prices),
    )

    return {
        rarity: prices
    }


# ============================================================
# SUPABASE
# ============================================================

async def save_price(
    item: Dict[str, Any],
    price: float,
    rarity: str,
) -> bool:

    payload = {
        "item_id": str(
            item.get("item_id")
        ),
        "item_name": item.get(
            "name",
            "Unknown",
        ),
        "price": float(price),
        "rarity": rarity,
    }

    try:

        result = await asyncio.to_thread(
            lambda: supabase
            .table("price_history")
            .insert(payload)
            .execute()
        )

        logger.info(
            "SUPABASE OK | price_history | "
            "ID=%s | %s | %.0f",
            payload["item_id"],
            rarity,
            price,
        )

        return True

    except Exception as e:

        logger.error(
            "SUPABASE ERROR | price_history | "
            "payload=%s | error=%s",
            payload,
            e,
        )

        return False


# ============================================================
# СБОР ОДНОГО ПРЕДМЕТА
# ============================================================

async def collect_item(
    client: httpx.AsyncClient,
    item: Dict[str, Any],
):

    item_id = str(
        item.get("item_id")
    )

    item_name = item.get(
        "name",
        "Unknown",
    )

    lots = await fetch_auction_lots(
        client,
        item_id,
    )

    logger.info(
        "Auction API | ID=%s | %s | лотов=%s",
        item_id,
        item_name,
        len(lots),
    )

    if not lots:
        logger.info(
            "ID=%s | %s | активных лотов нет",
            item_id,
            item_name,
        )
        return

    rarity_prices = collect_rarity_prices(
        item_id,
        lots,
    )

    if not rarity_prices:

        logger.info(
            "ID=%s | %s | нет валидных цен выкупа",
            item_id,
            item_name,
        )

        return

    saved = 0

    for rarity, prices in rarity_prices.items():

        for price in prices:

            success = await save_price(
                item,
                price,
                rarity,
            )

            if success:
                saved += 1

    logger.info(
        "ID=%s | %s | сохранено цен: %s",
        item_id,
        item_name,
        saved,
    )


# ============================================================
# ЗАГРУЗКА ОТСЛЕЖИВАЕМЫХ ПРЕДМЕТОВ
# ============================================================

def load_tracked_items() -> List[Dict[str, Any]]:

    items = local_database.get_all()

    logger.info(
        "Загружено предметов из официальной базы: %s",
        len(items),
    )

    return items


# ============================================================
# МОНИТОРИНГ СНАЙПЕРОВ
# ============================================================

async def monitor_snipers():

    try:

        result = await asyncio.to_thread(
            lambda: supabase
            .table("user_snipers")
            .select("*")
            .execute()
        )

        rows = result.data or []

        logger.info(
            "Загружено настроек снайперов: %s",
            len(rows),
        )

        valid = 0

        for row in rows:

            item_id = (
                row.get("item_id")
                or row.get("itemId")
            )

            if not item_id:
                continue

            if local_database.get(
                str(item_id)
            ):
                valid += 1

        logger.info(
            "Валидных снайперов по официальной базе: %s",
            valid,
        )

    except Exception as e:

        logger.error(
            "Ошибка мониторинга user_snipers: %s",
            e,
        )


# ============================================================
# ОСНОВНОЙ ЦИКЛ
# ============================================================

async def collector_loop():

    logger.info(
        "Запущен основной сборщик аукциона"
    )

    logger.info(
        "Путь официальной базы: %s",
        DATABASE_PATH,
    )

    logger.info(
        "Предметов в официальной базе: %s",
        len(local_database.get_all()),
    )

    items = load_tracked_items()

    if not items:
        logger.error(
            "Официальная база пуста!"
        )
        return

    async with httpx.AsyncClient(
        follow_redirects=True
    ) as client:

        first_dump_done = False

        while True:

            cycle_start = time.time()

            logger.info(
                "========== НОВЫЙ ЦИКЛ СБОРА =========="
            )

            for item in items:

                item_id = str(
                    item.get("item_id")
                )

                try:

                    lots = await fetch_auction_lots(
                        client,
                        item_id,
                    )

                    logger.info(
                        "Auction API | ID=%s | лотов=%s",
                        item_id,
                        len(lots),
                    )

                    # ------------------------------------------------
                    # Один раз показываем реальный формат лота.
                    # Это полезно для дальнейшей диагностики.
                    # ------------------------------------------------

                    if lots and not first_dump_done:

                        logger.warning(
                            "========== ПРИМЕР ЛОТА AUCTION API =========="
                        )

                        try:
                            logger.warning(
                                json.dumps(
                                    lots[0],
                                    ensure_ascii=False,
                                    indent=2,
                                )
                            )
                        except Exception:
                            logger.warning(
                                "%s",
                                lots[0],
                            )

                        logger.warning(
                            "================================================"
                        )

                        first_dump_done = True

                    if not lots:
                        await asyncio.sleep(
                            REQUEST_DELAY
                        )
                        continue

                    rarity_prices = (
                        collect_rarity_prices(
                            item_id,
                            lots,
                        )
                    )

                    if not rarity_prices:

                        logger.info(
                            "ID=%s | %s | "
                            "нет валидных цен выкупа",
                            item_id,
                            item.get("name"),
                        )

                        await asyncio.sleep(
                            REQUEST_DELAY
                        )

                        continue

                    total_saved = 0

                    for rarity, prices in (
                        rarity_prices.items()
                    ):

                        for price in prices:

                            success = await save_price(
                                item,
                                price,
                                rarity,
                            )

                            if success:
                                total_saved += 1

                    logger.info(
                        "ID=%s | %s | "
                        "сохранено=%s",
                        item_id,
                        item.get("name"),
                        total_saved,
                    )

                except Exception as e:

                    logger.exception(
                        "Ошибка обработки ID=%s: %s",
                        item_id,
                        e,
                    )

                await asyncio.sleep(
                    REQUEST_DELAY
                )

            # ------------------------------------------------
            # Проверяем настройки снайперов
            # ------------------------------------------------

            await monitor_snipers()

            elapsed = (
                time.time()
                - cycle_start
            )

            sleep_time = max(
                0,
                COLLECT_INTERVAL - elapsed,
            )

            logger.info(
                "========== ЦИКЛ ЗАВЕРШЁН =========="
            )

            logger.info(
                "Время цикла: %.1f сек.",
                elapsed,
            )

            logger.info(
                "Следующий цикл через: %.1f сек.",
                sleep_time,
            )

            await asyncio.sleep(
                sleep_time
            )


# ============================================================
# START
# ============================================================

async def main():

    logger.info(
        "STALZONE Auction Collector запускается..."
    )

    logger.info(
        "Регион STALCRAFT: %s",
        REGION,
    )

    logger.info(
        "Auction API: %s",
        AUCTION_API,
    )

    logger.info(
        "Официальная база: %s",
        DATABASE_PATH,
    )

    logger.info(
        "Предметов в официальной базе: %s",
        len(local_database.get_all()),
    )

    await collector_loop()


if __name__ == "__main__":

    try:
        asyncio.run(main())

    except KeyboardInterrupt:

        logger.info(
            "Collector остановлен"
        )

    except Exception as e:

        logger.exception(
            "Критическая ошибка collector: %s",
            e,
        )
