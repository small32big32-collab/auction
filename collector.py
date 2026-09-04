import asyncio
import json
import os
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

# ВАЖНО:
# Активные лоты находятся по:
# /RU/auction/{item_id}/lots
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


# ============================================================
# CONFIG VALIDATION
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

def normalize_string(value: Any) -> Optional[str]:
    """
    Безопасно получает строковое значение.

    Для STALZONE database name обычно имеет вид:

    {
        "key": "...",
        "lines": {
            "ru": "Название"
        }
    }
    """

    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()

        return value if value else None

    if isinstance(value, dict):

        lines = value.get("lines")

        if isinstance(lines, dict):

            ru = lines.get("ru")

            if isinstance(ru, str) and ru.strip():
                return ru.strip()

            en = lines.get("en")

            if isinstance(en, str) and en.strip():
                return en.strip()

        ru = value.get("ru")

        if isinstance(ru, str) and ru.strip():
            return ru.strip()

        name = value.get("name")

        if isinstance(name, str) and name.strip():
            return name.strip()

    return None


def normalize_category(value: Any) -> str:
    """
    Приводит category к строке.
    """

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, list):

        values = [
            str(x).strip()
            for x in value
            if x is not None
        ]

        return "/".join(
            x for x in values if x
        )

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


def detect_json_rarity(
    obj: Any,
) -> Optional[str]:
    """
    Рекурсивно ищет редкость в официальном JSON.

    ВАЖНО:
    Проверяем key только если это str.
    Это предотвращает ошибку:

        TypeError: unhashable type: 'dict'
    """

    if isinstance(obj, dict):

        key = obj.get("key")

        if isinstance(key, str):

            rarity = QUALITY_KEY_TO_RARITY.get(
                key
            )

            if rarity:
                return rarity

        color = obj.get("color")

        if isinstance(color, str):

            rarity = COLOR_TO_RARITY.get(
                color.upper()
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


def to_int(
    value: Any,
) -> Optional[int]:

    if value is None:
        return None

    if isinstance(value, bool):
        return None

    try:
        return int(
            round(
                float(value)
            )
        )

    except (
        TypeError,
        ValueError,
    ):
        return None


# ============================================================
# LOCAL ITEM DATABASE
# ============================================================

class LocalItemDatabase:
    """
    Локальная официальная STALZONE database.

    ИМЕННО ОНА является источником списка предметов.

    Supabase.items здесь НЕ используется.
    """

    def __init__(
        self,
        database_path: Path,
    ):

        self.database_path = database_path

        # item_id -> основная информация
        self.items: Dict[
            str,
            Dict[str, Any],
        ] = {}

        # item_id -> {
        #     ptn: json
        # }
        self.variants: Dict[
            str,
            Dict[int, Dict[str, Any]],
        ] = {}

    # --------------------------------------------------------
    # LOAD
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

        json_files = list(
            self.database_path.rglob(
                "*.json"
            )
        )

        print(
            f"LOCAL DB | JSON files: "
            f"{len(json_files)}"
        )

        # ----------------------------------------------------
        # Сначала основные JSON
        # ----------------------------------------------------

        main_files = []
        variant_files = []

        for file_path in json_files:

            if "_variants" in file_path.parts:
                variant_files.append(
                    file_path
                )
            else:
                main_files.append(
                    file_path
                )

        # ----------------------------------------------------
        # MAIN ITEMS
        # ----------------------------------------------------

        for file_path in main_files:

            self._load_main_item(
                file_path
            )

        # ----------------------------------------------------
        # VARIANTS
        # ----------------------------------------------------

        for file_path in variant_files:

            self._load_variant(
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
    # LOAD MAIN ITEM
    # --------------------------------------------------------

    def _load_main_item(
        self,
        file_path: Path,
    ) -> None:

        try:

            with file_path.open(
                "r",
                encoding="utf-8",
            ) as f:

                data = json.load(f)

        except Exception as e:

            print(
                f"LOCAL DB | "
                f"ERROR reading {file_path}: "
                f"{e}"
            )

            return

        if not isinstance(
            data,
            dict,
        ):
            return

        item_id = data.get("id")

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

        color = data.get(
            "color"
        )

        category = normalize_category(
            data.get("category")
        )

        self.items[item_id] = {
            "id": item_id,
            "name": name or item_id,
            "rarity": rarity,
            "color": color,
            "category": category,
            "path": str(file_path),
        }

    # --------------------------------------------------------
    # LOAD VARIANT
    # --------------------------------------------------------

    def _load_variant(
        self,
        file_path: Path,
    ) -> None:

        try:

            parts = file_path.parts

            variants_index = parts.index(
                "_variants"
            )

            if (
                variants_index + 2
                >= len(parts)
            ):
                return

            item_id = parts[
                variants_index + 1
            ]

            filename = file_path.stem

            if not filename.isdigit():
                return

            ptn = int(filename)

        except Exception:
            return

        try:

            with file_path.open(
                "r",
                encoding="utf-8",
            ) as f:

                data = json.load(f)

        except Exception as e:

            print(
                f"LOCAL DB | "
                f"ERROR reading variant "
                f"{file_path}: {e}"
            )

            return

        if not isinstance(
            data,
            dict,
        ):
            return

        json_id = data.get("id")

        if (
            isinstance(json_id, str)
            and json_id != item_id
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
    # GET ITEM
    # --------------------------------------------------------

    def get_item(
        self,
        item_id: str,
    ) -> Optional[Dict[str, Any]]:

        return self.items.get(
            item_id
        )

    # --------------------------------------------------------
    # HAS VARIANT
    # --------------------------------------------------------

    def has_variant(
        self,
        item_id: str,
        ptn: int,
    ) -> bool:

        return ptn in (
            self.variants.get(
                item_id,
                {},
            )
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
            ),
        )

    # ========================================================
    # TOKEN
    # ========================================================

    async def get_access_token(
        self,
    ) -> str:

        payload = {
            "grant_type": "client_credentials",
            "client_id": STALCRAFT_CLIENT_ID,
            "client_secret": STALCRAFT_CLIENT_SECRET,
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

                if response.status_code != 200:

                    print(
                        f"TOKEN ERROR | "
                        f"HTTP "
                        f"{response.status_code} | "
                        f"{response.text[:500]}"
                    )

                    if attempt < REQUEST_RETRIES:

                        await asyncio.sleep(
                            attempt
                        )

                    continue

                try:

                    data = response.json()

                except Exception as e:

                    print(
                        f"TOKEN JSON ERROR | "
                        f"{e}"
                    )

                    continue

                token = data.get(
                    "access_token"
                )

                if not token:

                    raise RuntimeError(
                        "OAuth response does "
                        "not contain access_token"
                    )

                self.access_token = token

                print(
                    "TOKEN OK"
                )

                return token

            except Exception as e:

                print(
                    f"TOKEN EXCEPTION | "
                    f"attempt={attempt} | "
                    f"{type(e).__name__}: {e}"
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
    # REQUEST AUCTION
    # ========================================================

    async def request_auction(
        self,
        item_id: str,
    ) -> Optional[Dict[str, Any]]:

        if not self.access_token:

            await self.get_access_token()

        # ====================================================
        # ПРАВИЛЬНЫЙ ENDPOINT
        #
        # /RU/auction/{item_id}/lots
        # ====================================================

        url = (
            f"{AUCTION_BASE_URL}"
            f"/RU/auction/{item_id}/lots"
        )

        params = {
            "limit": 200,
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

                        data = response.json()

                    except Exception as e:

                        print(
                            f"AUCTION JSON ERROR | "
                            f"ID={item_id} | "
                            f"{e}"
                        )

                        return None

                    print(
                        f"AUCTION OK | "
                        f"ID={item_id}"
                    )

                    return data

                # ------------------------------------------------
                # 404
                # ------------------------------------------------
                # Не повторяем запрос.
                # Переходим к следующему предмету.
                # ------------------------------------------------

                if response.status_code == 404:

                    print(
                        f"AUCTION 404 | "
                        f"ID={item_id} | "
                        f"skip"
                    )

                    return None

                # ------------------------------------------------
                # AUTH
                # ------------------------------------------------

                if response.status_code in (
                    401,
                    403,
                ):

                    print(
                        f"AUCTION AUTH ERROR | "
                        f"ID={item_id} | "
                        f"HTTP "
                        f"{response.status_code}"
                    )

                    self.access_token = None

                    await self.get_access_token()

                    headers["Authorization"] = (
                        f"Bearer "
                        f"{self.access_token}"
                    )

                    continue

                # ------------------------------------------------
                # RATE LIMIT
                # ------------------------------------------------

                if response.status_code == 429:

                    retry_after = (
                        response.headers.get(
                            "Retry-After"
                        )
                    )

                    try:

                        wait_time = float(
                            retry_after
                        )

                    except (
                        TypeError,
                        ValueError,
                    ):

                        wait_time = 2.0

                    print(
                        f"AUCTION RATE LIMIT | "
                        f"ID={item_id} | "
                        f"sleep={wait_time}s"
                    )

                    await asyncio.sleep(
                        wait_time
                    )

                    continue

                # ------------------------------------------------
                # OTHER ERROR
                # ------------------------------------------------

                print(
                    f"AUCTION ERROR | "
                    f"ID={item_id} | "
                    f"HTTP "
                    f"{response.status_code} | "
                    f"{response.text[:500]}"
                )

                if attempt < REQUEST_RETRIES:

                    await asyncio.sleep(
                        attempt
                    )

            except httpx.TimeoutException:

                print(
                    f"AUCTION TIMEOUT | "
                    f"ID={item_id} | "
                    f"attempt={attempt}"
                )

                if attempt < REQUEST_RETRIES:

                    await asyncio.sleep(
                        attempt
                    )

            except Exception as e:

                print(
                    f"AUCTION EXCEPTION | "
                    f"ID={item_id} | "
                    f"attempt={attempt} | "
                    f"{type(e).__name__}: {e}"
                )

                if attempt < REQUEST_RETRIES:

                    await asyncio.sleep(
                        attempt
                    )

        return None

    # ========================================================
    # QLT
    # ========================================================

    @staticmethod
    def get_qlt(
        lot: Dict[str, Any],
    ) -> int:

        value = lot.get(
            "qlt"
        )

        result = to_int(
            value
        )

        if result is None:
            return -1

        return result

    # ========================================================
    # PTN
    # ========================================================

    @staticmethod
    def get_ptn(
        lot: Dict[str, Any],
    ) -> Optional[int]:

        value = lot.get(
            "ptn"
        )

        return to_int(
            value
        )

    # ========================================================
    # BUYOUT PRICE
    # ========================================================

    @staticmethod
    def extract_buyout_price(
        lot: Dict[str, Any],
    ) -> Optional[int]:
        """
        Получает цену выкупа.

        Поддерживает основные варианты структуры API.
        """

        # ----------------------------------------------------
        # buyoutPrice
        # ----------------------------------------------------

        if "buyoutPrice" in lot:

            value = lot.get(
                "buyoutPrice"
            )

            if isinstance(value, dict):

                for key in (
                    "amount",
                    "price",
                    "value",
                ):

                    if key in value:

                        result = to_int(
                            value.get(key)
                        )

                        if result is not None:
                            return result

            else:

                result = to_int(
                    value
                )

                if result is not None:
                    return result

        # ----------------------------------------------------
        # buyout_price
        # ----------------------------------------------------

        if "buyout_price" in lot:

            result = to_int(
                lot.get(
                    "buyout_price"
                )
            )

            if result is not None:
                return result

        # ----------------------------------------------------
        # buyout
        # ----------------------------------------------------

        if "buyout" in lot:

            value = lot.get(
                "buyout"
            )

            if isinstance(value, dict):

                for key in (
                    "amount",
                    "price",
                    "value",
                ):

                    if key in value:

                        result = to_int(
                            value.get(key)
                        )

                        if result is not None:
                            return result

            else:

                result = to_int(
                    value
                )

                if result is not None:
                    return result

        # ----------------------------------------------------
        # price
        # ----------------------------------------------------

        if "price" in lot:

            result = to_int(
                lot.get(
                    "price"
                )
            )

            if result is not None:
                return result

        return None

    # ========================================================
    # PARSE LOT
    # ========================================================

    def parse_lot(
        self,
        lot: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:

        if not isinstance(
            lot,
            dict,
        ):
            return None

        qlt = self.get_qlt(
            lot
        )

        ptn = self.get_ptn(
            lot
        )

        price = self.extract_buyout_price(
            lot
        )

        if price is None:
            return None

        return {
            "qlt": qlt,
            "ptn": ptn,
            "price": price,
        }

    # ========================================================
    # EXTRACT LOTS
    # ========================================================

    @staticmethod
    def extract_lots(
        data: Any,
    ) -> List[Dict[str, Any]]:

        if isinstance(
            data,
            list,
        ):

            return [
                x
                for x in data
                if isinstance(x, dict)
            ]

        if not isinstance(
            data,
            dict,
        ):

            return []

        # Обычный ответ
        lots = data.get(
            "lots"
        )

        if isinstance(
            lots,
            list,
        ):

            return [
                x
                for x in lots
                if isinstance(x, dict)
            ]

        # Запасной вариант
        auctions = data.get(
            "auctions"
        )

        if isinstance(
            auctions,
            list,
        ):

            return [
                x
                for x in auctions
                if isinstance(x, dict)
            ]

        # Ещё один возможный вариант
        data_list = data.get(
            "data"
        )

        if isinstance(
            data_list,
            list,
        ):

            return [
                x
                for x in data_list
                if isinstance(x, dict)
            ]

        return []

    # ========================================================
    # COLLECT ONE ITEM
    # ========================================================

    async def collect_item(
        self,
        item: Dict[str, Any],
    ) -> None:

        item_id = item["id"]

        item_name = (
            item.get("name")
            or item_id
        )

        print(
            f"COLLECT | "
            f"ID={item_id} | "
            f"{item_name}"
        )

        data = await self.request_auction(
            item_id
        )

        if data is None:

            print(
                f"COLLECT | "
                f"ID={item_id} | "
                f"no data"
            )

            return

        raw_lots = self.extract_lots(
            data
        )

        if not raw_lots:

            print(
                f"COLLECT | "
                f"ID={item_id} | "
                f"lots=0"
            )

            # Сохраняем информацию о том,
            # что предмет проверен, но лотов нет.
            await self.save_history(
                item=item,
                rarity=(
                    item.get("rarity")
                    or "Обычный"
                ),
                ptn=None,
                min_price=None,
                total_lots=0,
            )

            return

        parsed_lots = []

        for lot in raw_lots:

            parsed = self.parse_lot(
                lot
            )

            if parsed is not None:

                parsed_lots.append(
                    parsed
                )

        if not parsed_lots:

            print(
                f"COLLECT | "
                f"ID={item_id} | "
                f"no valid prices"
            )

            return

        # ====================================================
        # PTN DEBUG
        # ====================================================

        self.debug_ptn_mapping(
            item_id,
            [
                lot["ptn"]
                for lot in parsed_lots
            ],
        )

        # ====================================================
        # GROUP
        #
        # qlt + ptn
        # ====================================================

        groups: Dict[
            Tuple[
                int,
                Optional[int],
            ],
            List[int],
        ] = {}

        for lot in parsed_lots:

            key = (
                lot["qlt"],
                lot["ptn"],
            )

            groups.setdefault(
                key,
                [],
            ).append(
                lot["price"]
            )

        # ====================================================
        # SAVE GROUPS
        # ====================================================

        for (
            qlt,
            ptn,
        ), prices in groups.items():

            rarity = QLT_TO_RARITY.get(
                qlt
            )

            if rarity is None:

                rarity = (
                    item.get("rarity")
                    or "Обычный"
                )

            min_price = min(
                prices
            )

            await self.save_history(
                item=item,
                rarity=rarity,
                ptn=ptn,
                min_price=min_price,
                total_lots=len(prices),
            )

        print(
            f"COLLECT OK | "
            f"ID={item_id} | "
            f"lots={len(parsed_lots)} | "
            f"groups={len(groups)}"
        )

    # ========================================================
    # SAVE HISTORY
    # ========================================================

    async def save_history(
        self,
        item: Dict[str, Any],
        rarity: str,
        ptn: Optional[int],
        min_price: Optional[int],
        total_lots: int,
    ) -> None:

        item_id = item[
            "id"
        ]

        item_name = (
            item.get("name")
            or item_id
        )

        category = (
            item.get("category")
            or "artefact"
        )

        # ----------------------------------------------------
        # В текущей таблице price_history есть:
        #
        # variant
        #
        # но отдельного ptn нет.
        #
        # Поэтому пока записываем ptn туда.
        # ----------------------------------------------------

        if ptn is None:

            variant = "unknown"

        else:

            variant = str(
                ptn
            )

        min_price_int = (
            to_int(min_price)
        )

        row = {
            "item_id": item_id,
            "item_name": item_name,

            "min_buyout_price":
                min_price_int,

            "total_lots":
                int(total_lots),

            "rarity":
                rarity,

            "category":
                category,

            "variant":
                variant,

            "buyout_price":
                min_price_int,
        }

        try:

            (
                supabase
                .table("price_history")
                .insert(row)
                .execute()
            )

            print(
                f"SUPABASE OK | "
                f"price_history | "
                f"ID={item_id} | "
                f"{item_name} | "
                f"rarity={rarity} | "
                f"ptn={variant} | "
                f"min={min_price_int} | "
                f"lots={total_lots}"
            )

        except Exception as e:

            print(
                f"SUPABASE ERROR | "
                f"price_history | "
                f"ID={item_id} | "
                f"error={e}"
            )

    # ========================================================
    # PTN DEBUG
    # ========================================================

    def debug_ptn_mapping(
        self,
        item_id: str,
        ptn_values: List[
            Optional[int]
        ],
    ) -> None:

        local_variants = (
            self.database.get_variants(
                item_id
            )
        )

        if not local_variants:
            return

        unique_ptn = sorted(
            {
                ptn
                for ptn in ptn_values
                if ptn is not None
            }
        )

        if not unique_ptn:
            return

        result = []

        for ptn in unique_ptn:

            if self.database.has_variant(
                item_id,
                ptn,
            ):

                result.append(
                    f"{ptn}=MATCH"
                )

            else:

                result.append(
                    f"{ptn}=NO_LOCAL_VARIANT"
                )

        print(
            f"PTN MAP | "
            f"ID={item_id} | "
            f"{' | '.join(result)}"
        )

    # ========================================================
    # SNIPERS
    # ========================================================

    async def monitor_snipers(
        self,
    ) -> None:

        try:

            result = (
                supabase
                .table("user_snipers")
                .select("*")
                .execute()
            )

            snipers = (
                result.data
                or []
            )

            print(
                f"SNIPERS | "
                f"loaded={len(snipers)}"
            )

        except Exception as e:

            print(
                f"SNIPERS ERROR | "
                f"{e}"
            )

    # ========================================================
    # COLLECT ALL
    # ========================================================

    async def collect_all(
        self,
    ) -> None:

        items = self.database.get_items()

        total = len(
            items
        )

        print(
            f"COLLECT ALL | "
            f"items={total}"
        )

        for index, item in enumerate(
            items,
            start=1,
        ):

            item_id = item[
                "id"
            ]

            item_name = (
                item.get("name")
                or item_id
            )

            print(
                f"COLLECT ALL | "
                f"[{index}/{total}] | "
                f"{item_id} | "
                f"{item_name}"
            )

            try:

                await self.collect_item(
                    item
                )

            except Exception as e:

                print(
                    f"COLLECT ERROR | "
                    f"ID={item_id} | "
                    f"{type(e).__name__}: "
                    f"{e}"
                )

            await asyncio.sleep(
                REQUEST_DELAY
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

async def main():

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

    # --------------------------------------------------------
    # LOCAL DATABASE
    # --------------------------------------------------------

    database = LocalItemDatabase(
        DATABASE_PATH
    )

    database.load()

    if not database.items:

        raise RuntimeError(
            "No items found in local "
            "STALZONE database"
        )

    # --------------------------------------------------------
    # COLLECTOR
    # --------------------------------------------------------

    collector = AuctionCollector(
        database
    )

    try:

        # ----------------------------------------------------
        # TOKEN
        # ----------------------------------------------------

        await collector.get_access_token()

        # ----------------------------------------------------
        # MAIN LOOP
        # ----------------------------------------------------

        while True:

            print()
            print(
                "=" * 60
            )
            print(
                "COLLECTION CYCLE START"
            )
            print(
                "=" * 60
            )

            try:

                await collector.monitor_snipers()

                await collector.collect_all()

            except Exception as e:

                print(
                    f"CYCLE ERROR | "
                    f"{type(e).__name__}: "
                    f"{e}"
                )

                # На следующем цикле
                # получим новый токен.
                collector.access_token = None

            print()
            print(
                "=" * 60
            )

            print(
                f"CYCLE FINISHED | "
                f"sleep={COLLECT_INTERVAL}s"
            )

            print(
                "=" * 60
            )

            await asyncio.sleep(
                COLLECT_INTERVAL
            )

    finally:

        await collector.close()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print(
            "COLLECTOR STOPPED"
        )
