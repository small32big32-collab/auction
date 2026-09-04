import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from supabase import Client, create_client


# ============================================================
# CONFIG
# ============================================================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

STALCRAFT_CLIENT_ID = os.getenv("STALCRAFT_CLIENT_ID")
STALCRAFT_CLIENT_SECRET = os.getenv("STALCRAFT_CLIENT_SECRET")

TOKEN_URL = "https://exbo.net/oauth/token"
AUCTION_BASE_URL = "https://eapi.stalcraft.net"

DATABASE_PATH = Path(
    os.getenv(
        "STALZONE_DATABASE_PATH",
        "/app/stalzone-database/ru/items/artefact",
    )
)

COLLECT_INTERVAL = int(
    os.getenv("COLLECT_INTERVAL", "300")
)

REQUEST_DELAY = float(
    os.getenv("REQUEST_DELAY", "0.15")
)

REQUEST_TIMEOUT = float(
    os.getenv("REQUEST_TIMEOUT", "30")
)

REQUEST_RETRIES = int(
    os.getenv("REQUEST_RETRIES", "3")
)

# Максимальное количество лотов за один запрос API
AUCTION_PAGE_SIZE = 200


# ============================================================
# VALIDATION
# ============================================================

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL is not set")

if not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_KEY is not set")

if not STALCRAFT_CLIENT_ID:
    raise RuntimeError("STALCRAFT_CLIENT_ID is not set")

if not STALCRAFT_CLIENT_SECRET:
    raise RuntimeError("STALCRAFT_CLIENT_SECRET is not set")


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

QLT_TO_RARITY = {
    -1: "Обычный",
    0: "Обычный",
    1: "Необычный",
    2: "Особый",
    3: "Редкий",
    4: "Исключительный",
    5: "Легендарный",
}


QUALITY_KEY_TO_RARITY = {
    "core.quality.common": "Обычный",
    "core.quality.uncommon": "Необычный",
    "core.quality.special": "Особый",
    "core.quality.rare": "Редкий",
    "core.quality.exclusive": "Исключительный",
    "core.quality.legendary": "Легендарный",
}


COLOR_TO_RARITY = {
    "DEFAULT": "Обычный",
    "GREEN": "Необычный",
    "BLUE": "Особый",
    "PURPLE": "Редкий",
    "GOLD": "Исключительный",
    "YELLOW": "Исключительный",
    "RED": "Легендарный",

    "COMMON": "Обычный",
    "UNCOMMON": "Необычный",
    "SPECIAL": "Особый",
    "RARE": "Редкий",
    "EXCLUSIVE": "Исключительный",
    "LEGENDARY": "Легендарный",
}


# ============================================================
# HELPERS
# ============================================================

def to_int(value: Any) -> Optional[int]:
    """
    Безопасное преобразование значения в int.

    Нужно, в частности, потому что Supabase BIGINT
    не принимает значения вида 234999.0.
    """

    if value is None:
        return None

    if isinstance(value, bool):
        return None

    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def normalize_string(
    value: Any,
) -> Optional[str]:

    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()

        if value:
            return value

        return None

    if isinstance(value, dict):

        # Сначала пробуем обычные варианты
        for key in (
            "ru",
            "name",
            "title",
        ):
            result = normalize_string(
                value.get(key)
            )

            if result:
                return result

        # Затем lines
        lines = value.get("lines")

        if isinstance(lines, dict):

            result = normalize_string(
                lines.get("ru")
            )

            if result:
                return result

            result = normalize_string(
                lines.get("en")
            )

            if result:
                return result

    return None


def get_json_name(
    data: Dict[str, Any],
) -> Optional[str]:

    result = normalize_string(
        data.get("name")
    )

    if result:
        return result

    return normalize_string(
        data.get("title")
    )


def normalize_category(
    value: Any,
) -> str:

    if isinstance(value, str):

        value = value.strip()

        if value:
            return value

    if isinstance(value, list):

        parts = []

        for item in value:

            if isinstance(item, str):

                item = item.strip()

                if item:
                    parts.append(item)

        if parts:
            return "/".join(parts)

    if isinstance(value, dict):

        for key in (
            "id",
            "key",
            "name",
        ):

            result = normalize_string(
                value.get(key)
            )

            if result:
                return result

    return "artefact"


# ============================================================
# RARITY FROM LOCAL DATABASE
# ============================================================

def detect_json_rarity(
    obj: Any,
) -> Optional[str]:

    if isinstance(obj, dict):

        key = obj.get("key")

        # ВАЖНО:
        # key иногда является dict.
        # Поэтому обязательно проверяем isinstance(str),
        # иначе получим:
        # TypeError: unhashable type: 'dict'

        if isinstance(key, str):

            rarity = (
                QUALITY_KEY_TO_RARITY.get(
                    key
                )
            )

            if rarity:
                return rarity

        color = obj.get("color")

        if isinstance(color, str):

            rarity = (
                COLOR_TO_RARITY.get(
                    color.upper()
                )
            )

            if rarity:
                return rarity

        for value in obj.values():

            rarity = detect_json_rarity(
                value
            )

            if rarity:
                return rarity

    elif isinstance(obj, list):

        for value in obj:

            rarity = detect_json_rarity(
                value
            )

            if rarity:
                return rarity

    return None


# ============================================================
# RECURSIVE SEARCH
# ============================================================

def find_value_recursive(
    obj: Any,
    keys: Tuple[str, ...],
) -> Any:
    """
    Рекурсивный поиск значения в JSON.

    Используется для поиска:

        qlt
        ptn

    в том числе внутри:

        additional
    """

    if isinstance(obj, dict):

        # Сначала проверяем текущий уровень
        for key in keys:

            if key in obj:

                value = obj.get(key)

                if value is not None:
                    return value

        # Затем рекурсивно ищем внутри
        for value in obj.values():

            result = find_value_recursive(
                value,
                keys,
            )

            if result is not None:
                return result

    elif isinstance(obj, list):

        for value in obj:

            result = find_value_recursive(
                value,
                keys,
            )

            if result is not None:
                return result

    return None


# ============================================================
# AUCTION JSON PARSING
# ============================================================

def extract_lots(
    data: Any,
) -> List[Dict[str, Any]]:
    """
    Извлекает список lots из ответа API.
    """

    if isinstance(data, dict):

        lots = data.get("lots")

        if isinstance(lots, list):

            return [
                lot
                for lot in lots
                if isinstance(lot, dict)
            ]

    elif isinstance(data, list):

        return [
            lot
            for lot in data
            if isinstance(lot, dict)
        ]

    return []


def extract_buyout_price(
    lot: Dict[str, Any],
) -> Optional[int]:
    """
    Получает buyoutPrice.

    Поддерживает разные варианты названия поля.
    """

    for key in (
        "buyoutPrice",
        "buyout_price",
        "buyout",
    ):

        value = to_int(
            lot.get(key)
        )

        if value is not None and value > 0:
            return value

    return None


def get_qlt(
    lot: Dict[str, Any],
) -> int:
    """
    Получает qlt.

    Если qlt отсутствует, считаем предмет обычным.
    """

    value = find_value_recursive(
        lot,
        ("qlt",),
    )

    result = to_int(value)

    if result is None:
        return -1

    return result


def get_ptn(
    lot: Dict[str, Any],
) -> Optional[int]:
    """
    Получает ptn.

    Если ptn отсутствует, возвращается None.
    """

    value = find_value_recursive(
        lot,
        ("ptn",),
    )

    return to_int(value)


# ============================================================
# LOCAL ITEM DATABASE
# ============================================================

class LocalItemDatabase:

    def __init__(
        self,
        database_path: Path,
    ):

        self.database_path = database_path

        self.items: Dict[
            str,
            Dict[str, Any],
        ] = {}

        self.variants: Dict[
            str,
            Dict[int, Dict[str, Any]],
        ] = {}

    # --------------------------------------------------------
    # LOAD DATABASE
    # --------------------------------------------------------

    def load(self) -> None:

        print(
            f"LOCAL DB | scanning: "
            f"{self.database_path}"
        )

        if not self.database_path.exists():

            raise RuntimeError(
                "Local database not found: "
                f"{self.database_path}"
            )

        files = list(
            self.database_path.rglob(
                "*.json"
            )
        )

        print(
            f"LOCAL DB | JSON files: "
            f"{len(files)}"
        )

        for file_path in files:

            if "_variants" in file_path.parts:

                self.load_variant(
                    file_path
                )

            else:

                self.load_main_item(
                    file_path
                )

        print(
            f"LOCAL DB | unique items: "
            f"{len(self.items)}"
        )

        print(
            f"LOCAL DB | items with variants: "
            f"{len(self.variants)}"
        )

    # --------------------------------------------------------
    # MAIN ITEM
    # --------------------------------------------------------

    def load_main_item(
        self,
        file_path: Path,
    ) -> None:

        try:

            with file_path.open(
                "r",
                encoding="utf-8",
            ) as file:

                data = json.load(file)

        except Exception as exc:

            print(
                f"LOCAL DB | ERROR reading "
                f"{file_path}: {exc}"
            )

            return

        if not isinstance(
            data,
            dict,
        ):
            return

        item_id = data.get(
            "id"
        )

        if not isinstance(
            item_id,
            str,
        ):
            return

        item_id = item_id.strip()

        if not item_id:
            return

        name = get_json_name(
            data
        )

        rarity = detect_json_rarity(
            data
        )

        category = normalize_category(
            data.get("category")
        )

        self.items[item_id] = {
            "id": item_id,
            "name": name or item_id,
            "rarity": rarity,
            "category": category,
            "color": data.get("color"),
            "path": str(file_path),
        }

    # --------------------------------------------------------
    # VARIANT
    # --------------------------------------------------------

    def load_variant(
        self,
        file_path: Path,
    ) -> None:

        parts = file_path.parts

        try:

            index = parts.index(
                "_variants"
            )

            item_id = parts[
                index + 1
            ]

        except (
            ValueError,
            IndexError,
        ):
            return

        if not file_path.stem.isdigit():
            return

        ptn = int(
            file_path.stem
        )

        try:

            with file_path.open(
                "r",
                encoding="utf-8",
            ) as file:

                data = json.load(file)

        except Exception:

            return

        if not isinstance(
            data,
            dict,
        ):
            return

        self.variants.setdefault(
            item_id,
            {},
        )[ptn] = data

    # --------------------------------------------------------
    # GET ITEMS
    # --------------------------------------------------------

    def get_items(
        self,
    ) -> List[Dict[str, Any]]:

        return list(
            self.items.values()
        )

    # --------------------------------------------------------
    # GET VARIANTS
    # --------------------------------------------------------

    def get_variants(
        self,
        item_id: str,
    ) -> List[int]:

        return sorted(
            self.variants.get(
                item_id,
                {},
            ).keys()
        )


# ============================================================
# AUCTION COLLECTOR
# ============================================================

class AuctionCollector:

    def __init__(
        self,
        database: LocalItemDatabase,
    ):

        self.database = database

        self.access_token: Optional[
            str
        ] = None

        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                REQUEST_TIMEOUT
            )
        )

    # ========================================================
    # TOKEN
    # ========================================================

    async def get_access_token(
        self,
    ) -> str:

        payload = {
            "grant_type":
                "client_credentials",

            "client_id":
                STALCRAFT_CLIENT_ID,

            "client_secret":
                STALCRAFT_CLIENT_SECRET,
        }

        for attempt in range(
            1,
            REQUEST_RETRIES + 1,
        ):

            try:

                response = (
                    await self.client.post(
                        TOKEN_URL,
                        data=payload,
                    )
                )

                if response.status_code == 200:

                    data = response.json()

                    token = data.get(
                        "access_token"
                    )

                    if token:

                        self.access_token = token

                        print(
                            "TOKEN OK"
                        )

                        return token

                    print(
                        "TOKEN ERROR | "
                        "access_token missing"
                    )

                else:

                    print(
                        f"TOKEN ERROR | "
                        f"HTTP "
                        f"{response.status_code} | "
                        f"{response.text[:300]}"
                    )

            except Exception as exc:

                print(
                    f"TOKEN EXCEPTION | "
                    f"attempt={attempt} | "
                    f"{exc}"
                )

            if attempt < REQUEST_RETRIES:

                await asyncio.sleep(
                    attempt
                )

        raise RuntimeError(
            "Unable to obtain "
            "STALCRAFT access token"
        )

    # ========================================================
    # ONE AUCTION PAGE
    # ========================================================

    async def request_auction_page(
        self,
        item_id: str,
        offset: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Получает одну страницу аукциона.

        Ключевой момент:

            additional=true

        Именно он нужен для получения
        дополнительных параметров:

            qlt
            ptn
        """

        if not self.access_token:

            await self.get_access_token()

        url = (
            f"{AUCTION_BASE_URL}"
            f"/RU/auction/"
            f"{item_id}"
            f"/lots"
        )

        params = {
            "additional": "true",

            "limit":
                AUCTION_PAGE_SIZE,

            "offset":
                offset,

            "sort":
                "time_created",

            "order":
                "desc",
        }

        headers = {
            "Authorization":
                f"Bearer {self.access_token}",

            "Accept":
                "application/json",
        }

        for attempt in range(
            1,
            REQUEST_RETRIES + 1,
        ):

            try:

                response = (
                    await self.client.get(
                        url,
                        params=params,
                        headers=headers,
                    )
                )

                # ------------------------------------------------
                # SUCCESS
                # ------------------------------------------------

                if response.status_code == 200:

                    try:

                        return response.json()

                    except Exception as exc:

                        print(
                            f"AUCTION JSON ERROR | "
                            f"ID={item_id} | "
                            f"{exc}"
                        )

                        return None

                # ------------------------------------------------
                # UNAUTHORIZED
                # ------------------------------------------------

                if response.status_code == 401:

                    print(
                        f"AUCTION 401 | "
                        f"ID={item_id} | "
                        f"refreshing token"
                    )

                    self.access_token = None

                    if attempt < REQUEST_RETRIES:

                        await self.get_access_token()

                        continue

                # ------------------------------------------------
                # RATE LIMIT
                # ------------------------------------------------

                if response.status_code == 429:

                    retry_after = to_int(
                        response.headers.get(
                            "Retry-After"
                        )
                    )

                    if retry_after is None:
                        retry_after = max(
                            1,
                            attempt * 2,
                        )

                    print(
                        f"AUCTION RATE LIMIT | "
                        f"ID={item_id} | "
                        f"wait={retry_after}s"
                    )

                    await asyncio.sleep(
                        retry_after
                    )

                    continue

                # ------------------------------------------------
                # OTHER ERROR
                # ------------------------------------------------

                print(
                    f"AUCTION ERROR | "
                    f"ID={item_id} | "
                    f"offset={offset} | "
                    f"HTTP "
                    f"{response.status_code} | "
                    f"{response.text[:300]}"
                )

            except Exception as exc:

                print(
                    f"AUCTION EXCEPTION | "
                    f"ID={item_id} | "
                    f"offset={offset} | "
                    f"attempt={attempt} | "
                    f"{exc}"
                )

            if attempt < REQUEST_RETRIES:

                await asyncio.sleep(
                    attempt
                )

        return None

    # ========================================================
    # FULL AUCTION
    # ========================================================

    async def request_auction(
        self,
        item_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Получает ВСЕ лоты предмета.

        API отдаёт максимум 200 лотов
        за страницу.

        Поэтому:

            offset=0
            offset=200
            offset=400
            ...

        пока лоты не закончатся.
        """

        all_lots: List[
            Dict[str, Any]
        ] = []

        offset = 0

        total: Optional[int] = None

        while True:

            data = (
                await self.request_auction_page(
                    item_id,
                    offset,
                )
            )

            if data is None:

                break

            lots = extract_lots(
                data
            )

            # Получаем total, если API его отдаёт
            if isinstance(
                data,
                dict,
            ):

                page_total = to_int(
                    data.get(
                        "total"
                    )
                )

                if page_total is not None:

                    total = page_total

            print(
                f"AUCTION LOTS | "
                f"ID={item_id} | "
                f"offset={offset} | "
                f"received={len(lots)}"
            )

            # Лотов больше нет
            if not lots:
                break

            all_lots.extend(
                lots
            )

            # Если страница неполная —
            # это последняя страница
            if len(lots) < AUCTION_PAGE_SIZE:

                break

            # Если знаем total и уже всё получили
            if (
                total is not None
                and len(all_lots) >= total
            ):

                break

            offset += AUCTION_PAGE_SIZE

            await asyncio.sleep(
                REQUEST_DELAY
            )

        return all_lots

    # ========================================================
    # SNIPERS
    # ========================================================

    async def load_snipers(
        self,
    ) -> List[Dict[str, Any]]:

        try:

            response = (
                supabase
                .table("user_snipers")
                .select("*")
                .execute()
            )

            return response.data or []

        except Exception as exc:

            print(
                f"SNIPERS ERROR | {exc}"
            )

            return []

    # ========================================================
    # SAVE HISTORY
    # ========================================================

    async def save_history(
        self,
        item: Dict[str, Any],
        lots: List[Dict[str, Any]],
    ) -> None:
        """
        Записывает данные в:

            price_history

        Используются существующие поля:

            item_id
            item_name
            min_buyout_price
            total_lots
            created_at
            rarity
            category
            variant
            buyout_price
        """

        if not lots:

            return

        valid_lots: List[
            Tuple[
                Dict[str, Any],
                int,
                int,
                Optional[int],
            ]
        ] = []

        for lot in lots:

            price = extract_buyout_price(
                lot
            )

            if price is None:
                continue

            qlt = get_qlt(
                lot
            )

            ptn = get_ptn(
                lot
            )

            valid_lots.append(
                (
                    lot,
                    price,
                    qlt,
                    ptn,
                )
            )

        if not valid_lots:

            print(
                f"SUPABASE SKIP | "
                f"ID={item['id']} | "
                f"no valid buyout prices"
            )

            return

        # ----------------------------------------------------
        # GROUP
        # ----------------------------------------------------

        grouped: Dict[
            Tuple[int, Optional[int]],
            List[int],
        ] = {}

        for (
            _lot,
            price,
            qlt,
            ptn,
        ) in valid_lots:

            key = (
                qlt,
                ptn,
            )

            grouped.setdefault(
                key,
                [],
            ).append(
                price
            )

        # ----------------------------------------------------
        # LOG PARAMETERS
        # ----------------------------------------------------

        qlts = sorted(
            {
                qlt
                for (
                    _lot,
                    _price,
                    qlt,
                    _ptn,
                ) in valid_lots
            }
        )

        ptns = sorted(
            {
                ptn
                for (
                    _lot,
                    _price,
                    _qlt,
                    ptn,
                ) in valid_lots
                if ptn is not None
            }
        )

        print(
            f"AUCTION PARAMS | "
            f"ID={item['id']} | "
            f"qlt={qlts} | "
            f"ptn="
            f"{ptns if ptns else 'NONE'}"
        )

        # ----------------------------------------------------
        # BUILD SUPABASE ROWS
        # ----------------------------------------------------

        rows = []

        for (
            (
                qlt,
                ptn,
            ),
            prices,
        ) in grouped.items():

            min_price = min(
                prices
            )

            rarity = (
                QLT_TO_RARITY.get(
                    qlt
                )
                or item.get(
                    "rarity"
                )
                or "Обычный"
            )

            row = {
                "item_id":
                    item["id"],

                "item_name":
                    item["name"],

                "min_buyout_price":
                    int(min_price),

                "total_lots":
                    int(len(prices)),

                "created_at":
                    datetime.now(
                        timezone.utc
                    ).isoformat(),

                "rarity":
                    rarity,

                "category":
                    item.get(
                        "category",
                        "artefact",
                    ),

                "variant":
                    (
                        str(ptn)
                        if ptn is not None
                        else "unknown"
                    ),

                "buyout_price":
                    int(min_price),
            }

            rows.append(
                row
            )

        # ----------------------------------------------------
        # SAVE
        # ----------------------------------------------------

        try:

            response = (
                supabase
                .table("price_history")
                .insert(rows)
                .execute()
            )

            saved_count = len(
                response.data or rows
            )

            print(
                f"SUPABASE OK | "
                f"price_history | "
                f"ID={item['id']} | "
                f"rows={saved_count}"
            )

        except Exception as exc:

            print(
                f"SUPABASE ERROR | "
                f"price_history | "
                f"ID={item['id']} | "
                f"{exc}"
            )

    # ========================================================
    # COLLECT ONE ITEM
    # ========================================================

    async def collect_item(
        self,
        item: Dict[str, Any],
    ) -> None:

        item_id = item["id"]

        print(
            f"COLLECT | "
            f"ID={item_id} | "
            f"{item['name']}"
        )

        lots = await self.request_auction(
            item_id
        )

        if not lots:

            print(
                f"COLLECT EMPTY | "
                f"ID={item_id}"
            )

            return

        await self.save_history(
            item,
            lots,
        )

        print(
            f"COLLECT OK | "
            f"ID={item_id} | "
            f"lots={len(lots)}"
        )

    # ========================================================
    # COLLECT ALL
    # ========================================================

    async def collect_all(
        self,
    ) -> None:

        # ВАЖНО:
        # Список берётся из LOCAL DATABASE,
        # а НЕ из Supabase.items.

        items = self.database.get_items()

        print(
            f"COLLECT ALL | "
            f"items={len(items)}"
        )

        for index, item in enumerate(
            items,
            1,
        ):

            print(
                f"COLLECT ALL | "
                f"[{index}/{len(items)}] | "
                f"{item['id']} | "
                f"{item['name']}"
            )

            try:

                await self.collect_item(
                    item
                )

            except Exception as exc:

                print(
                    f"COLLECT ERROR | "
                    f"ID={item['id']} | "
                    f"{exc}"
                )

            await asyncio.sleep(
                REQUEST_DELAY
            )

    # ========================================================
    # RUN
    # ========================================================

    async def run(
        self,
    ) -> None:

        # Загружаем локальную официальную БД
        self.database.load()

        # Получаем токен
        await self.get_access_token()

        print(
            "=" * 60
        )

        while True:

            print(
                "COLLECTION CYCLE START"
            )

            # Настройки снайперов
            # остаются в Supabase.
            snipers = (
                await self.load_snipers()
            )

            print(
                f"SNIPERS | "
                f"loaded={len(snipers)}"
            )

            # Основной сбор
            await self.collect_all()

            print(
                "COLLECTION CYCLE END"
            )

            print(
                f"NEXT CYCLE | "
                f"in {COLLECT_INTERVAL}s"
            )

            await asyncio.sleep(
                COLLECT_INTERVAL
            )

    # ========================================================
    # CLOSE
    # ========================================================

    async def close(
        self,
    ) -> None:

        await self.client.aclose()


# ============================================================
# MAIN
# ============================================================

async def main() -> None:

    database = LocalItemDatabase(
        DATABASE_PATH
    )

    collector = AuctionCollector(
        database
    )

    try:

        print(
            "=" * 60
        )

        print(
            "STALZONE AUCTION COLLECTOR"
        )

        print(
            "=" * 60
        )

        print(
            f"LOCAL DATABASE: "
            f"{DATABASE_PATH}"
        )

        print(
            f"COLLECT INTERVAL: "
            f"{COLLECT_INTERVAL}s"
        )

        await collector.run()

    finally:

        await collector.close()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    asyncio.run(
        main()
    )
