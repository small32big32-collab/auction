import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from supabase import create_client, Client


# ============================================================
# CONFIG
# ============================================================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# ВАЖНО:
# Именно эти названия используются в Railway Variables
STALCRAFT_CLIENT_ID = os.getenv("STALCRAFT_CLIENT_ID")
STALCRAFT_CLIENT_SECRET = os.getenv("STALCRAFT_CLIENT_SECRET")

TOKEN_URL = "https://exbo.net/oauth/token"
AUCTION_URL = "https://eapi.stalcraft.net/ru/auction"

DATABASE_PATH = Path(
    os.getenv(
        "STALZONE_DATABASE_PATH",
        "/app/stalzone-database/ru/items/artefact",
    )
)

COLLECT_INTERVAL = int(os.getenv("COLLECT_INTERVAL", "300"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "0.15"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "30"))
REQUEST_RETRIES = int(os.getenv("REQUEST_RETRIES", "3"))


# ============================================================
# CHECK CONFIG
# ============================================================

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL is not set")

if not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_KEY is not set")

if not STALCRAFT_CLIENT_ID:
    raise RuntimeError("STALCRAFT_CLIENT_ID is not set")

if not STALCRAFT_CLIENT_SECRET:
    raise RuntimeError("STALCRAFT_CLIENT_SECRET is not set")


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

    # Возможные текстовые значения
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
    Безопасно превращает значение в строку.

    Особенность STALZONE database:
    name может быть объектом:
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
        return value.strip() or None

    if isinstance(value, dict):
        lines = value.get("lines")

        if isinstance(lines, dict):
            ru = lines.get("ru")
            if isinstance(ru, str) and ru.strip():
                return ru.strip()

            en = lines.get("en")
            if isinstance(en, str) and en.strip():
                return en.strip()

        value_ru = value.get("ru")
        if isinstance(value_ru, str) and value_ru.strip():
            return value_ru.strip()

        value_name = value.get("name")
        if isinstance(value_name, str) and value_name.strip():
            return value_name.strip()

    return None


def detect_json_rarity(obj: Any) -> Optional[str]:
    """
    Ищет редкость в JSON официальной базы.
    """

    if isinstance(obj, dict):

        key = obj.get("key")

        if isinstance(key, str):
            rarity = QUALITY_KEY_TO_RARITY.get(key)

            if rarity:
                return rarity

        color = obj.get("color")

        if isinstance(color, str):
            rarity = COLOR_TO_RARITY.get(color.upper())

            if rarity:
                return rarity

        for value in obj.values():
            rarity = detect_json_rarity(value)

            if rarity:
                return rarity

    elif isinstance(obj, list):

        for value in obj:
            rarity = detect_json_rarity(value)

            if rarity:
                return rarity

    return None


def get_json_name(data: Dict[str, Any]) -> Optional[str]:
    """
    Получает русское название предмета.
    """

    name = data.get("name")

    result = normalize_string(name)

    if result:
        return result

    return normalize_string(data.get("title"))


# ============================================================
# LOCAL ITEM DATABASE
# ============================================================

class LocalItemDatabase:
    """
    Официальная STALZONE database является ИСТОЧНИКОМ
    списка предметов.

    Supabase.items здесь НЕ используется для получения списка.
    """

    def __init__(self, database_path: Path):
        self.database_path = database_path

        # item_id -> информация об основном предмете
        self.items: Dict[str, Dict[str, Any]] = {}

        # item_id -> список локальных вариантов
        self.variants: Dict[str, Dict[int, Dict[str, Any]]] = {}

    def load(self) -> None:
        print(f"LOCAL DB | scanning: {self.database_path}")

        if not self.database_path.exists():
            raise RuntimeError(
                f"Local database not found: {self.database_path}"
            )

        json_files = list(self.database_path.rglob("*.json"))

        print(f"LOCAL DB | JSON files: {len(json_files)}")

        for file_path in json_files:

            try:
                with file_path.open(
                    "r",
                    encoding="utf-8",
                ) as f:
                    data = json.load(f)

            except Exception as e:
                print(
                    f"LOCAL DB | ERROR reading {file_path}: {e}"
                )
                continue

            if not isinstance(data, dict):
                continue

            item_id = data.get("id")

            if not isinstance(item_id, str):
                continue

            item_id = item_id.strip()

            if not item_id:
                continue

            # ------------------------------------------------
            # ВАРИАНТ
            # /_variants/<item_id>/<N>.json
            # ------------------------------------------------

            parts = file_path.parts

            if "_variants" in parts:

                try:
                    variants_index = parts.index("_variants")

                    if (
                        variants_index + 2 < len(parts)
                        and parts[variants_index + 1] == item_id
                    ):
                        filename = file_path.stem

                        if filename.isdigit():
                            variant_number = int(filename)

                            self.variants.setdefault(
                                item_id,
                                {},
                            )[variant_number] = data

                            continue

                except Exception:
                    pass

            # ------------------------------------------------
            # ОСНОВНОЙ ITEM
            # ------------------------------------------------

            name = get_json_name(data)

            rarity = detect_json_rarity(data)

            color = data.get("color")

            self.items[item_id] = {
                "id": item_id,
                "name": name or item_id,
                "rarity": rarity,
                "color": color,
                "path": str(file_path),
            }

        print(
            f"LOCAL DB | unique items: {len(self.items)}"
        )

        print(
            f"LOCAL DB | items with variants: {len(self.variants)}"
        )

    def get_items(self) -> List[Dict[str, Any]]:
        return list(self.items.values())

    def get_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        return self.items.get(item_id)

    def has_variant(
        self,
        item_id: str,
        ptn: int,
    ) -> bool:
        return ptn in self.variants.get(item_id, {})

    def get_variants(
        self,
        item_id: str,
    ) -> List[int]:
        return sorted(
            self.variants.get(item_id, {}).keys()
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

        self.access_token: Optional[str] = None

        self.client = httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT,
        )

    # --------------------------------------------------------
    # TOKEN
    # --------------------------------------------------------

    async def get_access_token(self) -> str:

        payload = {
            "grant_type": "client_credentials",
            "client_id": STALCRAFT_CLIENT_ID,
            "client_secret": STALCRAFT_CLIENT_SECRET,
        }

        for attempt in range(1, REQUEST_RETRIES + 1):

            try:

                response = await self.client.post(
                    TOKEN_URL,
                    data=payload,
                )

                if response.status_code != 200:
                    print(
                        f"TOKEN ERROR | "
                        f"HTTP {response.status_code} | "
                        f"{response.text[:500]}"
                    )

                    if attempt < REQUEST_RETRIES:
                        await asyncio.sleep(attempt)

                    continue

                data = response.json()

                token = data.get("access_token")

                if not token:
                    raise RuntimeError(
                        "OAuth response does not contain access_token"
                    )

                self.access_token = token

                print("TOKEN OK")

                return token

            except Exception as e:

                print(
                    f"TOKEN EXCEPTION | attempt={attempt} | {e}"
                )

                if attempt < REQUEST_RETRIES:
                    await asyncio.sleep(attempt)

        raise RuntimeError(
            "Unable to obtain STALCRAFT access token"
        )

    # --------------------------------------------------------
    # AUCTION REQUEST
    # --------------------------------------------------------

    async def request_auction(
        self,
        item_id: str,
    ) -> Optional[Dict[str, Any]]:

        if not self.access_token:
            await self.get_access_token()

        params = {
            "itemId": item_id,
            "limit": 200,
        }

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }

        for attempt in range(1, REQUEST_RETRIES + 1):

            try:

                response = await self.client.get(
                    AUCTION_URL,
                    params=params,
                    headers=headers,
                )

                # ------------------------------------------------
                # TOKEN EXPIRED
                # ------------------------------------------------

                if response.status_code in (401, 403):

                    print(
                        f"AUCTION AUTH ERROR | "
                        f"ID={item_id} | "
                        f"HTTP {response.status_code}"
                    )

                    self.access_token = None

                    await self.get_access_token()

                    headers["Authorization"] = (
                        f"Bearer {self.access_token}"
                    )

                    continue

                # ------------------------------------------------
                # SUCCESS
                # ------------------------------------------------

                if response.status_code == 200:

                    try:
                        data = response.json()
                    except Exception:
                        print(
                            f"AUCTION JSON ERROR | ID={item_id}"
                        )
                        return None

                    return data

                print(
                    f"AUCTION ERROR | "
                    f"ID={item_id} | "
                    f"HTTP {response.status_code} | "
                    f"{response.text[:300]}"
                )

                if attempt < REQUEST_RETRIES:
                    await asyncio.sleep(attempt)

            except Exception as e:

                print(
                    f"AUCTION EXCEPTION | "
                    f"ID={item_id} | "
                    f"attempt={attempt} | {e}"
                )

                if attempt < REQUEST_RETRIES:
                    await asyncio.sleep(attempt)

        return None

    # --------------------------------------------------------
    # QLT
    # --------------------------------------------------------

    @staticmethod
    def get_qlt(lot: Dict[str, Any]) -> int:

        value = lot.get("qlt")

        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    # --------------------------------------------------------
    # PTN
    # --------------------------------------------------------

    @staticmethod
    def get_ptn(
        lot: Dict[str, Any],
    ) -> Optional[int]:

        value = lot.get("ptn")

        if value is None:
            return None

        try:
            return int(value)

        except (TypeError, ValueError):
            return None

    # --------------------------------------------------------
    # PRICE
    # --------------------------------------------------------

    @staticmethod
    def extract_buyout_price(
        lot: Dict[str, Any],
    ) -> Optional[int]:

        candidates = [
            lot.get("buyoutPrice"),
            lot.get("buyout"),
            lot.get("price"),
        ]

        for value in candidates:

            if isinstance(value, dict):
                value = value.get("amount")

            try:

                if value is not None:
                    return int(round(float(value)))

            except (TypeError, ValueError):
                continue

        return None

    # --------------------------------------------------------
    # PARSE LOT
    # --------------------------------------------------------

    def parse_lot(
        self,
        lot: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:

        if not isinstance(lot, dict):
            return None

        qlt = self.get_qlt(lot)
        ptn = self.get_ptn(lot)
        price = self.extract_buyout_price(lot)

        if price is None:
            return None

        return {
            "qlt": qlt,
            "ptn": ptn,
            "price": price,
        }

    # --------------------------------------------------------
    # EXTRACT LOTS
    # --------------------------------------------------------

    @staticmethod
    def extract_lots(
        data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:

        if not isinstance(data, dict):
            return []

        # Основной ожидаемый вариант
        lots = data.get("lots")

        if isinstance(lots, list):
            return lots

        # Некоторые ответы API могут использовать "auctions"
        auctions = data.get("auctions")

        if isinstance(auctions, list):
            return auctions

        return []

    # --------------------------------------------------------
    # COLLECT ONE ITEM
    # --------------------------------------------------------

    async def collect_item(
        self,
        item: Dict[str, Any],
    ) -> None:

        item_id = item["id"]
        item_name = item.get("name") or item_id

        print(
            f"COLLECT | ID={item_id} | {item_name}"
        )

        data = await self.request_auction(item_id)

        if data is None:
            print(
                f"COLLECT | ID={item_id} | no data"
            )
            return

        raw_lots = self.extract_lots(data)

        parsed_lots = []

        for lot in raw_lots:

            parsed = self.parse_lot(lot)

            if parsed:
                parsed_lots.append(parsed)

        if not parsed_lots:

            print(
                f"COLLECT | ID={item_id} | lots=0"
            )

            await self.save_history(
                item=item,
                rarity=item.get("rarity") or "Обычный",
                ptn=None,
                min_price=None,
                total_lots=0,
            )

            return

        # ----------------------------------------------------
        # ГРУППИРОВКА ПО QLT + PTN
        # ----------------------------------------------------

        groups: Dict[
            Tuple[int, Optional[int]],
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
            ).append(lot["price"])

        # ----------------------------------------------------
        # SAVE
        # ----------------------------------------------------

        for (qlt, ptn), prices in groups.items():

            if qlt in QLT_TO_RARITY:
                rarity = QLT_TO_RARITY[qlt]
            else:
                rarity = item.get("rarity") or "Обычный"

            min_price = min(prices)

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

    # --------------------------------------------------------
    # SAVE SUPABASE
    # --------------------------------------------------------

    async def save_history(
        self,
        item: Dict[str, Any],
        rarity: str,
        ptn: Optional[int],
        min_price: Optional[int],
        total_lots: int,
    ) -> None:

        item_id = item["id"]
        item_name = item.get("name") or item_id

        # В текущей схеме price_history нет отдельного ptn.
        # Поэтому сохраняем ptn в существующее поле variant.
        variant = (
            str(ptn)
            if ptn is not None
            else "unknown"
        )

        row = {
            "item_id": item_id,
            "item_name": item_name,
            "min_buyout_price": (
                int(min_price)
                if min_price is not None
                else None
            ),
            "total_lots": int(total_lots),
            "rarity": rarity,
            "category": "artefact",
            "variant": variant,
            "buyout_price": (
                int(min_price)
                if min_price is not None
                else None
            ),
        }

        try:

            result = (
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
                f"min={min_price} | "
                f"lots={total_lots}"
            )

        except Exception as e:

            print(
                f"SUPABASE ERROR | "
                f"price_history | "
                f"ID={item_id} | "
                f"error={e}"
            )

    # --------------------------------------------------------
    # PTN DEBUG
    # --------------------------------------------------------

    def debug_ptn_mapping(
        self,
        item_id: str,
        ptn_values: List[Optional[int]],
    ) -> None:

        local_variants = self.database.get_variants(
            item_id
        )

        if not local_variants:
            return

        valid_ptn = sorted(
            {
                ptn
                for ptn in ptn_values
                if ptn is not None
            }
        )

        if not valid_ptn:
            return

        result = []

        for ptn in valid_ptn:

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

    # --------------------------------------------------------
    # MONITOR SNIPERS
    # --------------------------------------------------------

    async def monitor_snipers(self) -> None:

        try:

            result = (
                supabase
                .table("user_snipers")
                .select("*")
                .execute()
            )

            snipers = result.data or []

            print(
                f"SNIPERS | loaded={len(snipers)}"
            )

            # Здесь пока только загрузка настроек.
            # Логика уведомлений может работать отдельно.

        except Exception as e:

            print(
                f"SNIPERS ERROR | {e}"
            )

    # --------------------------------------------------------
    # COLLECT ALL
    # --------------------------------------------------------

    async def collect_all(self) -> None:

        items = self.database.get_items()

        print(
            f"COLLECT ALL | items={len(items)}"
        )

        for index, item in enumerate(
            items,
            start=1,
        ):

            print(
                f"COLLECT ALL | "
                f"[{index}/{len(items)}] | "
                f"{item['id']} | "
                f"{item.get('name')}"
            )

            try:

                await self.collect_item(item)

            except Exception as e:

                print(
                    f"COLLECT ERROR | "
                    f"ID={item['id']} | "
                    f"{e}"
                )

            await asyncio.sleep(
                REQUEST_DELAY
            )

    # --------------------------------------------------------
    # CLOSE
    # --------------------------------------------------------

    async def close(self) -> None:
        await self.client.aclose()


# ============================================================
# MAIN
# ============================================================

async def main():

    print("=" * 60)
    print("STALZONE AUCTION COLLECTOR")
    print("=" * 60)

    print(
        f"LOCAL DATABASE: {DATABASE_PATH}"
    )

    database = LocalItemDatabase(
        DATABASE_PATH
    )

    database.load()

    if not database.items:
        raise RuntimeError(
            "No items found in local STALZONE database"
        )

    collector = AuctionCollector(
        database
    )

    try:

        # Получаем токен заранее
        await collector.get_access_token()

        while True:

            print()
            print("=" * 60)
            print("COLLECTION CYCLE START")
            print("=" * 60)

            try:

                await collector.monitor_snipers()

                await collector.collect_all()

            except Exception as e:

                print(
                    f"CYCLE ERROR | {e}"
                )

                # Если проблема с токеном —
                # пробуем получить новый в следующем цикле.
                collector.access_token = None

            print()
            print(
                f"CYCLE FINISHED | "
                f"sleep={COLLECT_INTERVAL}s"
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
        asyncio.run(main())

    except KeyboardInterrupt:

        print(
            "COLLECTOR STOPPED"
        )
