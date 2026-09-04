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


# ============================================================
# VALIDATION
# ============================================================

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL is not set")

if not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_KEY is not set")

if not STALCRAFT_CLIENT_ID:
    raise RuntimeError(
        "STALCRAFT_CLIENT_ID is not set"
    )

if not STALCRAFT_CLIENT_SECRET:
    raise RuntimeError(
        "STALCRAFT_CLIENT_SECRET is not set"
    )


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

        return value if value else None

    if isinstance(value, dict):

        lines = value.get("lines")

        if isinstance(lines, dict):

            ru = lines.get("ru")

            if isinstance(ru, str):
                if ru.strip():
                    return ru.strip()

            en = lines.get("en")

            if isinstance(en, str):
                if en.strip():
                    return en.strip()

        ru = value.get("ru")

        if isinstance(ru, str):
            if ru.strip():
                return ru.strip()

        name = value.get("name")

        if isinstance(name, str):
            if name.strip():
                return name.strip()

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

        return value.strip() or "artefact"

    if isinstance(value, list):

        values = []

        for item in value:

            if isinstance(item, str):
                if item.strip():
                    values.append(
                        item.strip()
                    )

        if values:
            return "/".join(values)

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

    if isinstance(obj, dict):

        key = obj.get("key")

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
# RECURSIVE VALUE SEARCH
# ============================================================

def find_value_recursive(
    obj: Any,
    keys: Tuple[str, ...],
) -> Any:
    """
    Рекурсивно ищет ключи в JSON.

    Например:
        additional -> ptn
        additional -> qlt

    Это нужно потому, что auction lot может иметь
    характеристики не на верхнем уровне.
    """

    if isinstance(obj, dict):

        for key in keys:

            if key in obj:

                value = obj.get(key)

                if value is not None:
                    return value

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
# LOCAL DATABASE
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

        files = list(
            self.database_path.rglob(
                "*.json"
            )
        )

        print(
            f"LOCAL DB | JSON files: "
            f"{len(files)}"
        )

        main_files = []
        variant_files = []

        for file_path in files:

            if "_variants" in file_path.parts:
                variant_files.append(
                    file_path
                )
            else:
                main_files.append(
                    file_path
                )

        # Сначала основные предметы
        for file_path in main_files:

            self.load_main_item(
                file_path
            )

        # Затем варианты
        for file_path in variant_files:

            self.load_variant(
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

        except Exception as e:

            print(
                f"LOCAL DB | "
                f"ERROR reading "
                f"{file_path}: {e}"
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
            "color": data.get(
                "color"
            ),
            "path": str(
                file_path
            ),
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

        except Exception:
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
    # GET
    # --------------------------------------------------------

    def get_items(
        self,
    ) -> List[Dict[str, Any]]:

        return list(
            self.items.values()
        )

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

                data = response.json()

                token = data.get(
                    "access_token"
                )

                if not token:

                    raise RuntimeError(
                        "access_token missing"
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
                    f"{e}"
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
    # AUCTION REQUEST
    # ========================================================

    async def request_auction(
        self,
        item_id: str,
    ) -> Optional[Any]:

        if not self.access_token:

            await self.get_access_token()

        url = (
            f"{AUCTION_BASE_URL}"
            f"/RU/auction/"
            f"{item_id}/lots"
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

                        return response.json()

                    except Exception as e:

                        print(
                            f"AUCTION JSON ERROR | "
                            f"ID={item_id} | "
                            f"{e}"
                        )

                        return None

                # ------------------------------------------------
                # 404
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

                    headers[
                        "Authorization"
                    ] = (
                        "Bearer "
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

                    wait_time = to_int(
                        retry_after
                    )

                    if (
                        wait_time is None
                        or wait_time <= 0
                    ):
                        wait_time = 2

                    print(
                        f"RATE LIMIT | "
                        f"ID={item_id} | "
                        f"sleep={wait_time}s"
                    )

                    await asyncio.sleep(
                        wait_time
                    )

                    continue

                # ------------------------------------------------
                # OTHER
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
                    f"ID={item_id}"
                )

                if attempt < REQUEST_RETRIES:

                    await asyncio.sleep(
                        attempt
                    )

            except Exception as e:

                print(
                    f"AUCTION EXCEPTION | "
                    f"ID={item_id} | "
                    f"{e}"
                )

                if attempt < REQUEST_RETRIES:

                    await asyncio.sleep(
                        attempt
                    )

        return None

    # ========================================================
    # LOTS
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
                if isinstance(
                    x,
                    dict,
                )
            ]

        if not isinstance(
            data,
            dict,
        ):
            return []

        for key in (
            "lots",
            "auctions",
            "data",
        ):

            value = data.get(
                key
            )

            if isinstance(
                value,
                list,
            ):

                return [
                    x
                    for x in value
                    if isinstance(
                        x,
                        dict,
                    )
                ]

        return []

    # ========================================================
    # QLT
    # ========================================================

    @staticmethod
    def get_qlt(
        lot: Dict[str, Any],
    ) -> int:

        value = find_value_recursive(
            lot,
            (
                "qlt",
            ),
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

        value = find_value_recursive(
            lot,
            (
                "ptn",
            ),
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
        ВАЖНО:
        Не ищем произвольное число рекурсивно.

        Иначе можно случайно получить 0,
        amount или другое число из структуры лота.

        Приоритет:
            buyoutPrice
            buyout_price
            buyout
        """

        # ----------------------------------------------------
        # buyoutPrice
        # ----------------------------------------------------

        if "buyoutPrice" in lot:

            value = lot.get(
                "buyoutPrice"
            )

            if isinstance(
                value,
                dict,
            ):

                for key in (
                    "amount",
                    "price",
                    "value",
                ):

                    result = to_int(
                        value.get(key)
                    )

                    if (
                        result is not None
                        and result > 0
                    ):
                        return result

            else:

                result = to_int(
                    value
                )

                if (
                    result is not None
                    and result > 0
                ):
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

            if (
                result is not None
                and result > 0
            ):
                return result

        # ----------------------------------------------------
        # buyout
        # ----------------------------------------------------

        if "buyout" in lot:

            value = lot.get(
                "buyout"
            )

            if isinstance(
                value,
                dict,
            ):

                for key in (
                    "amount",
                    "price",
                    "value",
                ):

                    result = to_int(
                        value.get(key)
                    )

                    if (
                        result is not None
                        and result > 0
                    ):
                        return result

            else:

                result = to_int(
                    value
                )

                if (
                    result is not None
                    and result > 0
                ):
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

        price = (
            self.extract_buyout_price(
                lot
            )
        )

        # Лоты без корректной цены
        # не учитываем.
        if (
            price is None
            or price <= 0
        ):
            return None

        qlt = self.get_qlt(
            lot
        )

        ptn = self.get_ptn(
            lot
        )

        return {
            "qlt": qlt,
            "ptn": ptn,
            "price": price,
        }

    # ========================================================
    # COLLECT ITEM
    # ========================================================

    async def collect_item(
        self,
        item: Dict[str, Any],
    ) -> None:

        item_id = item[
            "id"
        ]

        item_name = (
            item.get(
                "name"
            )
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

        raw_lots = (
            self.extract_lots(
                data
            )
        )

        print(
            f"AUCTION LOTS | "
            f"ID={item_id} | "
            f"received={len(raw_lots)}"
        )

        parsed_lots = []

        for lot in raw_lots:

            parsed = self.parse_lot(
                lot
            )

            if parsed:

                parsed_lots.append(
                    parsed
                )

        # ----------------------------------------------------
        # DEBUG
        # ----------------------------------------------------

        ptn_values = [
            lot["ptn"]
            for lot in parsed_lots
            if lot["ptn"] is not None
        ]

        qlt_values = [
            lot["qlt"]
            for lot in parsed_lots
        ]

        if ptn_values:

            print(
                f"AUCTION PARAMS | "
                f"ID={item_id} | "
                f"qlt={sorted(set(qlt_values))} | "
                f"ptn={sorted(set(ptn_values))}"
            )

        else:

            print(
                f"AUCTION PARAMS | "
                f"ID={item_id} | "
                f"qlt={sorted(set(qlt_values))} | "
                f"ptn=NONE"
            )

        if not parsed_lots:

            print(
                f"COLLECT | "
                f"ID={item_id} | "
                f"no valid lots"
            )

            return

        # ----------------------------------------------------
        # PTN LOCAL MATCH
        # ----------------------------------------------------

        self.debug_ptn_mapping(
            item_id,
            ptn_values,
        )

        # ----------------------------------------------------
        # GROUP
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # SAVE
        # ----------------------------------------------------

        for (
            qlt,
            ptn,
        ), prices in groups.items():

            rarity = (
                QLT_TO_RARITY.get(
                    qlt
                )
                or item.get(
                    "rarity"
                )
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
                total_lots=len(
                    prices
                ),
            )

        print(
            f"COLLECT OK | "
            f"ID={item_id} | "
            f"lots={len(parsed_lots)} | "
            f"groups={len(groups)}"
        )

    # ========================================================
    # SAVE
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
            item.get(
                "name"
            )
            or item_id
        )

        category = (
            item.get(
                "category"
            )
            or "artefact"
        )

        variant = (
            str(ptn)
            if ptn is not None
            else "unknown"
        )

        min_price = to_int(
            min_price
        )

        now = datetime.now(
            timezone.utc
        ).isoformat()

        row = {
            "item_id":
                item_id,

            "item_name":
                item_name,

            "min_buyout_price":
                min_price,

            "total_lots":
                int(total_lots),

            "created_at":
                now,

            "rarity":
                rarity,

            "category":
                category,

            "variant":
                variant,

            "buyout_price":
                min_price,
        }

        try:

            (
                supabase
                .table(
                    "price_history"
                )
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
                f"min={min_price} | "
                f"lots={total_lots}"
            )

        except Exception as e:

            print(
                f"SUPABASE ERROR | "
                f"ID={item_id} | "
                f"{e}"
            )

    # ========================================================
    # PTN DEBUG
    # ========================================================

    def debug_ptn_mapping(
        self,
        item_id: str,
        ptn_values: List[int],
    ) -> None:

        if not ptn_values:
            return

        local_variants = (
            self.database.get_variants(
                item_id
            )
        )

        if not local_variants:
            return

        result = []

        for ptn in sorted(
            set(ptn_values)
        ):

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
                .table(
                    "user_snipers"
                )
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

        items = (
            self.database.get_items()
        )

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
                item.get(
                    "name"
                )
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

    database = LocalItemDatabase(
        DATABASE_PATH
    )

    database.load()

    if not database.items:

        raise RuntimeError(
            "No items found in local database"
        )

    collector = AuctionCollector(
        database
    )

    try:

        await collector.get_access_token()

        while True:

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

                collector.access_token = None

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
