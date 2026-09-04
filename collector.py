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

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

TOKEN_URL = "https://exbo.net/oauth/token"
AUCTION_URL = "https://eapi.stalcraft.net/ru/auction"

DATABASE_PATH = Path(
    os.getenv(
        "STALZONE_DATABASE_PATH",
        "/app/stalzone-database/ru/items/artefact"
    )
)

COLLECT_INTERVAL = int(os.getenv("COLLECT_INTERVAL", "300"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "0.15"))

REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "30"))
REQUEST_RETRIES = int(os.getenv("REQUEST_RETRIES", "3"))


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

    "UNCOMMON": "Необычный",
    "SPECIAL": "Особый",
    "RARE": "Редкий",
    "EXCLUSIVE": "Исключительный",
    "LEGENDARY": "Легендарный",
}


# ============================================================
# HELPERS
# ============================================================

def safe_int(value: Any) -> Optional[int]:
    """Безопасно преобразовать значение в int."""
    if value is None:
        return None

    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def normalize_string(value: Any) -> Optional[str]:
    """Безопасно получить строку."""
    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()
        return value if value else None

    return str(value)


# ============================================================
# LOCAL ITEM DATABASE
# ============================================================

class LocalItemDatabase:
    """
    Локальная официальная база STALZONE.

    Именно она является MASTER SOURCE предметов.

    Структура примерно такая:

    artefact/
        thermal/
            gy10.json
            _variants/
                gy10/
                    1.json
                    5.json
                    6.json
                    ...
    """

    def __init__(self, root: Path):
        self.root = root

        # item_id -> основной JSON
        self.items: Dict[str, Dict[str, Any]] = {}

        # item_id -> список JSON вариантов
        self.variants: Dict[str, Dict[str, Path]] = {}

        self._load()

    # --------------------------------------------------------
    # LOAD
    # --------------------------------------------------------

    def _load(self) -> None:
        if not self.root.exists():
            raise FileNotFoundError(
                f"STALZONE database not found: {self.root}"
            )

        json_files = list(self.root.rglob("*.json"))

        print(
            f"LOCAL DB | scanning: {self.root} | "
            f"json_files={len(json_files)}"
        )

        for path in json_files:
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                print(
                    f"LOCAL DB | JSON ERROR | "
                    f"{path} | {e}"
                )
                continue

            if not isinstance(data, dict):
                continue

            item_id = normalize_string(data.get("id"))

            if not item_id:
                continue

            # ------------------------------------------------
            # _variants/<item_id>/<N>.json
            # ------------------------------------------------

            parts = path.parts

            if "_variants" in parts:
                try:
                    variants_index = parts.index("_variants")

                    if variants_index + 2 < len(parts):
                        variant_item_id = parts[variants_index + 1]
                        variant_file = parts[variants_index + 2]

                        variant_number = Path(
                            variant_file
                        ).stem

                        if variant_item_id == item_id:
                            self.variants.setdefault(
                                item_id,
                                {}
                            )[variant_number] = path

                            continue

                except Exception:
                    pass

            # ------------------------------------------------
            # MAIN ITEM JSON
            # ------------------------------------------------

            if item_id not in self.items:
                self.items[item_id] = {
                    "id": item_id,
                    "name": data.get("name", item_id),
                    "color": data.get("color"),
                    "category": data.get("category"),
                    "path": path,
                    "data": data,
                }

        print(
            f"LOCAL DB | loaded items={len(self.items)} | "
            f"items_with_variants={len(self.variants)}"
        )

    # --------------------------------------------------------
    # PUBLIC
    # --------------------------------------------------------

    def get_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        return self.items.get(item_id)

    def get_all_items(self) -> List[Dict[str, Any]]:
        return list(self.items.values())

    def get_item_ids(self) -> List[str]:
        return list(self.items.keys())

    def get_variants(self, item_id: str) -> Dict[str, Path]:
        return self.variants.get(item_id, {})

    def has_variant(self, item_id: str, ptn: Any) -> bool:
        if ptn is None:
            return False

        ptn_str = str(ptn)

        return ptn_str in self.variants.get(item_id, {})

    def get_variant_file(
        self,
        item_id: str,
        ptn: Any
    ) -> Optional[Path]:
        if ptn is None:
            return None

        return self.variants.get(item_id, {}).get(str(ptn))

    # --------------------------------------------------------
    # RARITY
    # --------------------------------------------------------

    def detect_json_rarity(
        self,
        obj: Any
    ) -> Optional[str]:
        """
        Рекурсивно ищет core.quality.* в JSON.
        """

        if isinstance(obj, dict):

            key = obj.get("key")

            if isinstance(key, str):
                rarity = QUALITY_KEY_TO_RARITY.get(key)

                if rarity:
                    return rarity

            for value in obj.values():
                rarity = self.detect_json_rarity(value)

                if rarity:
                    return rarity

        elif isinstance(obj, list):

            for value in obj:
                rarity = self.detect_json_rarity(value)

                if rarity:
                    return rarity

        return None

    def get_local_rarity(
        self,
        item: Dict[str, Any]
    ) -> Optional[str]:

        data = item.get("data", {})

        # 1. quality key
        rarity = self.detect_json_rarity(data)

        if rarity:
            return rarity

        # 2. color
        color = normalize_string(
            item.get("color")
        )

        if color:
            return COLOR_TO_RARITY.get(
                color.upper()
            )

        return None

    # --------------------------------------------------------
    # DEBUG VARIANTS
    # --------------------------------------------------------

    def log_item_variants(
        self,
        item_id: str
    ) -> None:

        variants = self.get_variants(item_id)

        if not variants:
            return

        values = sorted(
            variants.keys(),
            key=lambda x: (
                int(x) if x.isdigit() else 999999,
                x
            )
        )

        print(
            f"LOCAL VARIANTS | "
            f"ID={item_id} | "
            f"ptn=[{', '.join(values)}]"
        )


# ============================================================
# AUCTION COLLECTOR
# ============================================================

class AuctionCollector:

    def __init__(
        self,
        local_db: LocalItemDatabase,
        supabase: Client
    ):
        self.local_db = local_db
        self.supabase = supabase

        self.access_token: Optional[str] = None

    # --------------------------------------------------------
    # TOKEN
    # --------------------------------------------------------

    async def get_access_token(
        self
    ) -> Optional[str]:

        if not CLIENT_ID or not CLIENT_SECRET:
            print(
                "TOKEN ERROR | "
                "CLIENT_ID / CLIENT_SECRET not configured"
            )
            return None

        payload = {
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        }

        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT
            ) as client:

                response = await client.post(
                    TOKEN_URL,
                    data=payload
                )

                response.raise_for_status()

                data = response.json()

                token = data.get("access_token")

                if not token:
                    print(
                        "TOKEN ERROR | "
                        "access_token missing"
                    )
                    return None

                self.access_token = token

                print("TOKEN OK")

                return token

        except Exception as e:
            print(
                f"TOKEN ERROR | {e}"
            )

            return None

    # --------------------------------------------------------
    # AUCTION REQUEST
    # --------------------------------------------------------

    async def request_auction(
        self,
        item_id: str
    ) -> Optional[Dict[str, Any]]:

        if not self.access_token:
            token = await self.get_access_token()

            if not token:
                return None

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }

        params = {
            "itemId": item_id,
            "limit": 200,
        }

        for attempt in range(1, REQUEST_RETRIES + 1):

            try:
                async with httpx.AsyncClient(
                    timeout=REQUEST_TIMEOUT
                ) as client:

                    response = await client.get(
                        AUCTION_URL,
                        headers=headers,
                        params=params
                    )

                    if response.status_code == 401:
                        print(
                            f"AUCTION | ID={item_id} | "
                            f"401 -> refreshing token"
                        )

                        self.access_token = None

                        if await self.get_access_token():
                            continue

                        return None

                    response.raise_for_status()

                    data = response.json()

                    print(
                        f"AUCTION OK | "
                        f"ID={item_id} | "
                        f"status={response.status_code}"
                    )

                    return data

            except Exception as e:

                print(
                    f"AUCTION ERROR | "
                    f"ID={item_id} | "
                    f"attempt={attempt}/{REQUEST_RETRIES} | "
                    f"{e}"
                )

                if attempt < REQUEST_RETRIES:
                    await asyncio.sleep(
                        attempt * 1.0
                    )

        return None

    # --------------------------------------------------------
    # LOT EXTRACTION
    # --------------------------------------------------------

    @staticmethod
    def extract_lots(
        data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:

        if not isinstance(data, dict):
            return []

        possible_keys = (
            "lots",
            "data",
            "items",
            "auctions",
        )

        for key in possible_keys:

            value = data.get(key)

            if isinstance(value, list):
                return [
                    x for x in value
                    if isinstance(x, dict)
                ]

        return []

    # --------------------------------------------------------
    # QLT
    # --------------------------------------------------------

    @staticmethod
    def get_qlt(
        lot: Dict[str, Any]
    ) -> Optional[int]:

        additional = lot.get("additional")

        if isinstance(additional, dict):

            value = additional.get("qlt")

            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    pass

        value = lot.get("qlt")

        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass

        return None

    # --------------------------------------------------------
    # PTN
    # --------------------------------------------------------

    @staticmethod
    def get_ptn(
        lot: Dict[str, Any]
    ) -> Optional[int]:

        """
        PTN берём ТОЛЬКО из данных аукциона.

        Если ptn отсутствует — возвращаем None.

        Никаких попыток угадать ptn по локальному
        _variants здесь нет.
        """

        additional = lot.get("additional")

        if isinstance(additional, dict):

            value = additional.get("ptn")

            if value is not None:

                try:
                    return int(value)

                except (TypeError, ValueError):
                    pass

        value = lot.get("ptn")

        if value is not None:

            try:
                return int(value)

            except (TypeError, ValueError):
                pass

        return None

    # --------------------------------------------------------
    # BUYOUT
    # --------------------------------------------------------

    @staticmethod
    def extract_buyout_price(
        lot: Dict[str, Any]
    ) -> Optional[int]:

        """
        Берём именно цену выкупа.

        startPrice намеренно НЕ используем.
        """

        additional = lot.get("additional")

        candidates = [
            lot.get("buyoutPrice"),
            lot.get("buyout_price"),
            lot.get("buyout"),
        ]

        if isinstance(additional, dict):

            candidates.extend([
                additional.get("buyoutPrice"),
                additional.get("buyout_price"),
                additional.get("buyout"),
            ])

        for value in candidates:

            price = safe_int(value)

            if price is not None:
                return price

        return None

    # --------------------------------------------------------
    # LOT INFO
    # --------------------------------------------------------

    def parse_lot(
        self,
        lot: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:

        qlt = self.get_qlt(lot)

        ptn = self.get_ptn(lot)

        price = self.extract_buyout_price(lot)

        if price is None:
            return None

        rarity = QLT_TO_RARITY.get(
            qlt,
            "Обычный"
        )

        return {
            "qlt": qlt,
            "rarity": rarity,
            "ptn": ptn,
            "price": price,
        }

    # --------------------------------------------------------
    # DEBUG PTN
    # --------------------------------------------------------

    def debug_ptn_mapping(
        self,
        item_id: str,
        lot_info: Dict[str, Any]
    ) -> None:

        ptn = lot_info.get("ptn")
        qlt = lot_info.get("qlt")

        if ptn is None:
            return

        variant_file = (
            self.local_db.get_variant_file(
                item_id,
                ptn
            )
        )

        exists = variant_file is not None

        print(
            f"PTN CHECK | "
            f"ID={item_id} | "
            f"qlt={qlt} | "
            f"ptn={ptn} | "
            f"_variants/{ptn}.json="
            f"{'YES' if exists else 'NO'}"
            f"{f' | file={variant_file}' if exists else ''}"
        )

    # --------------------------------------------------------
    # STATISTICS
    # --------------------------------------------------------

    def collect_item_statistics(
        self,
        item_id: str,
        lots: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:

        item = self.local_db.get_item(
            item_id
        )

        if not item:
            return []

        item_name = normalize_string(
            item.get("name")
        ) or item_id

        groups: Dict[
            Tuple[str, Optional[int]],
            List[int]
        ] = {}

        ptn_counts: Dict[int, int] = {}

        unknown_ptn_counts: Dict[str, int] = {}

        for lot in lots:

            parsed = self.parse_lot(lot)

            if not parsed:
                continue

            rarity = parsed["rarity"]
            ptn = parsed["ptn"]
            price = parsed["price"]

            key = (
                rarity,
                ptn
            )

            groups.setdefault(
                key,
                []
            ).append(price)

            if ptn is not None:
                ptn_counts[ptn] = (
                    ptn_counts.get(ptn, 0) + 1
                )
            else:
                unknown_ptn_counts[rarity] = (
                    unknown_ptn_counts.get(
                        rarity,
                        0
                    ) + 1
                )

            self.debug_ptn_mapping(
                item_id,
                parsed
            )

        # ----------------------------------------------------
        # PTN SUMMARY
        # ----------------------------------------------------

        if ptn_counts:

            summary = []

            for ptn in sorted(
                ptn_counts.keys()
            ):

                count = ptn_counts[ptn]

                exists = self.local_db.has_variant(
                    item_id,
                    ptn
                )

                marker = (
                    "MATCH"
                    if exists
                    else "NO_LOCAL_VARIANT"
                )

                summary.append(
                    f"{ptn}={count}[{marker}]"
                )

            print(
                f"PTN SUMMARY | "
                f"ID={item_id} | "
                f"{' | '.join(summary)}"
            )

        # ----------------------------------------------------
        # BUILD RESULTS
        # ----------------------------------------------------

        results = []

        for (
            rarity,
            ptn
        ), prices in groups.items():

            if not prices:
                continue

            min_price = min(prices)

            if ptn is None:
                ptn_value = "unknown"
            else:
                ptn_value = str(ptn)

            results.append({
                "item_id": item_id,
                "item_name": item_name,
                "rarity": rarity,
                "ptn": ptn_value,
                "min_buyout_price": min_price,
                "total_lots": len(prices),
            })

        return results

    # --------------------------------------------------------
    # SAVE HISTORY
    # --------------------------------------------------------

    async def save_price_history(
        self,
        statistics: Dict[str, Any]
    ) -> bool:

        item_id = statistics["item_id"]

        item_name = statistics["item_name"]

        rarity = statistics["rarity"]

        ptn = statistics.get("ptn")

        min_price = safe_int(
            statistics.get(
                "min_buyout_price"
            )
        )

        total_lots = safe_int(
            statistics.get(
                "total_lots"
            )
        )

        if min_price is None:
            print(
                f"SUPABASE SKIP | "
                f"ID={item_id} | "
                f"invalid price"
            )

            return False

        if total_lots is None:
            total_lots = 0

        # ----------------------------------------------------
        # IMPORTANT:
        # Пока в таблице есть старое поле variant,
        # используем его для хранения PTN.
        #
        # После добавления отдельного ptn можно заменить
        # "variant" -> "ptn".
        # ----------------------------------------------------

        payload = {
            "item_id": item_id,
            "item_name": item_name,
            "min_buyout_price": min_price,
            "total_lots": total_lots,
            "rarity": rarity,
            "category": "Артефакт",
            "variant": str(ptn),
            "buyout_price": min_price,
        }

        try:

            response = (
                self.supabase
                .table("price_history")
                .insert(payload)
                .execute()
            )

            print(
                f"SUPABASE OK | "
                f"price_history | "
                f"ID={item_id} | "
                f"{rarity} | "
                f"ptn={ptn} | "
                f"min={min_price} | "
                f"lots={total_lots}"
            )

            return True

        except Exception as e:

            print(
                f"SUPABASE ERROR | "
                f"price_history | "
                f"ID={item_id} | "
                f"ptn={ptn} | "
                f"{e}"
            )

            return False

    # --------------------------------------------------------
    # COLLECT ONE ITEM
    # --------------------------------------------------------

    async def collect_item(
        self,
        item: Dict[str, Any]
    ) -> None:

        item_id = item["id"]

        item_name = (
            normalize_string(
                item.get("name")
            )
            or item_id
        )

        print(
            f"COLLECT | "
            f"ID={item_id} | "
            f"name={item_name}"
        )

        data = await self.request_auction(
            item_id
        )

        if data is None:
            return

        lots = self.extract_lots(
            data
        )

        if not lots:

            print(
                f"COLLECT | "
                f"ID={item_id} | "
                f"lots=0"
            )

            return

        print(
            f"COLLECT | "
            f"ID={item_id} | "
            f"lots={len(lots)}"
        )

        statistics = (
            self.collect_item_statistics(
                item_id,
                lots
            )
        )

        if not statistics:
            print(
                f"COLLECT | "
                f"ID={item_id} | "
                f"no valid statistics"
            )

            return

        for stat in statistics:

            await self.save_price_history(
                stat
            )

            await asyncio.sleep(
                REQUEST_DELAY
            )

    # --------------------------------------------------------
    # MONITOR SNIPERS
    # --------------------------------------------------------

    async def monitor_snipers(self) -> None:

        try:

            response = (
                self.supabase
                .table("user_snipers")
                .select("*")
                .execute()
            )

            rows = response.data or []

            print(
                f"SNIPERS | "
                f"loaded={len(rows)}"
            )

            for row in rows:

                item_id = normalize_string(
                    row.get("item_id")
                )

                if not item_id:
                    continue

                if not self.local_db.get_item(
                    item_id
                ):

                    print(
                        f"SNIPER WARNING | "
                        f"ID={item_id} "
                        f"NOT IN LOCAL OFFICIAL DB"
                    )

        except Exception as e:

            print(
                f"SNIPERS ERROR | {e}"
            )

    # --------------------------------------------------------
    # ONE CYCLE
    # --------------------------------------------------------

    async def run_cycle(self) -> None:

        items = (
            self.local_db.get_all_items()
        )

        print(
            "=" * 70
        )

        print(
            f"COLLECT CYCLE | "
            f"items={len(items)}"
        )

        print(
            "=" * 70
        )

        # Проверяем пользовательские настройки
        await self.monitor_snipers()

        for index, item in enumerate(
            items,
            start=1
        ):

            print(
                f"[{index}/{len(items)}] "
                f"ID={item['id']} | "
                f"{item.get('name', item['id'])}"
            )

            self.local_db.log_item_variants(
                item["id"]
            )

            try:

                await self.collect_item(
                    item
                )

            except Exception as e:

                print(
                    f"ITEM ERROR | "
                    f"ID={item['id']} | "
                    f"{e}"
                )

            await asyncio.sleep(
                REQUEST_DELAY
            )

        print(
            "COLLECT CYCLE | DONE"
        )


# ============================================================
# MAIN
# ============================================================

async def main():

    print(
        "=" * 70
    )

    print(
        "STALZONE AUCTION COLLECTOR"
    )

    print(
        "=" * 70
    )

    print(
        f"LOCAL DB: {DATABASE_PATH}"
    )

    print(
        f"COLLECT INTERVAL: "
        f"{COLLECT_INTERVAL}s"
    )

    # --------------------------------------------------------
    # ENV
    # --------------------------------------------------------

    if not SUPABASE_URL:
        raise RuntimeError(
            "SUPABASE_URL is not configured"
        )

    if not SUPABASE_KEY:
        raise RuntimeError(
            "SUPABASE_KEY is not configured"
        )

    # --------------------------------------------------------
    # LOCAL DATABASE
    # --------------------------------------------------------

    local_db = LocalItemDatabase(
        DATABASE_PATH
    )

    # --------------------------------------------------------
    # SUPABASE
    # --------------------------------------------------------

    supabase = create_client(
        SUPABASE_URL,
        SUPABASE_KEY
    )

    # --------------------------------------------------------
    # COLLECTOR
    # --------------------------------------------------------

    collector = AuctionCollector(
        local_db=local_db,
        supabase=supabase
    )

    # --------------------------------------------------------
    # LOOP
    # --------------------------------------------------------

    while True:

        try:

            await collector.run_cycle()

        except Exception as e:

            print(
                f"MAIN ERROR | {e}"
            )

        print(
            f"NEXT CYCLE IN "
            f"{COLLECT_INTERVAL} SECONDS"
        )

        await asyncio.sleep(
            COLLECT_INTERVAL
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

        print(
            "COLLECTOR STOPPED"
        )
