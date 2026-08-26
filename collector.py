import os
import json
import asyncio
import httpx
from datetime import datetime, timezone
from supabase import create_client, Client

# Настройки окружения
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://your-supabase-project.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "your-supabase-service-role-key")

# Авторизация EXBO API
EXBO_CLIENT_ID = os.getenv("EXBO_CLIENT_ID", "3919")
EXBO_CLIENT_SECRET = os.getenv("EXBO_CLIENT_SECRET", "ayazYFVWHuFnpWBvOAYWWvEDykdntMOgDNNppKTl")
REGION = os.getenv("STALCRAFT_REGION", "RU")

# Эндпоинты EXBO API
AUTH_URL = "https://exbo.net/oauth/token"
BASE_API_URL = f"https://eapi.stalcraft.net/{REGION.lower()}"

DB_BASE_DIR = os.getenv("DB_BASE_DIR", "/app/stalzone-database/ru/items")

# Инициализация Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

COLOR_MAP = {
    "DEFAULT": "Обычный",
    "UNCOMMON": "Необычный",
    "SPECIAL": "Особый",
    "RARE": "Редкий",
    "EXCLUSIVE": "Исключительный",
    "LEGENDARY": "Легендарный",
}

ALL_RARITIES = ["Обычный", "Необычный", "Особый", "Редкий", "Исключительный", "Легендарный"]

RARITY_TO_QLT = {
    "Обычный": 0,
    "Необычный": 1,
    "Особый": 2,
    "Редкий": 3,
    "Исключительный": 4,
    "Легендарный": 5,
}


class ExboAuthManager:
    """Управление авторизацией и получением Bearer-токена EXBO API."""
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None

    async def refresh_token(self, client: httpx.AsyncClient) -> bool:
        print("🔑 Запрос нового access_token от EXBO...", flush=True)
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials"
        }
        try:
            res = await client.post(AUTH_URL, data=payload, timeout=10.0)
            if res.status_code == 200:
                data = res.json()
                self.access_token = data.get("access_token")
                print("✅ Токен EXBO успешно получен!", flush=True)
                return True
            else:
                print(f"❌ Ошибка авторизации EXBO [{res.status_code}]: {res.text}", flush=True)
        except Exception as e:
            print(f"❌ Исключение при получении токена EXBO: {e}", flush=True)
        return False

    async def get_headers(self, client: httpx.AsyncClient) -> dict:
        if not self.access_token:
            await self.refresh_token(client)
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Client-Id": self.client_id
        }


auth_manager = ExboAuthManager(EXBO_CLIENT_ID, EXBO_CLIENT_SECRET)


def parse_variants(item_data: dict) -> list[str]:
    variants = []
    raw_variants = item_data.get("_variants") or item_data.get("variants") or []

    if isinstance(raw_variants, list) and raw_variants:
        for v in raw_variants:
            if isinstance(v, dict):
                level = v.get("level") or v.get("upgrade") or v.get("id")
                if level is not None:
                    variants.append(str(level))
            elif isinstance(v, (int, str)):
                variants.append(str(v))

    return variants if variants else ["0"]


def initialize_items_database():
    print("🚀 Старт процесса инициализации коллектора...", flush=True)

    if not os.path.exists(DB_BASE_DIR):
        print(f"❌ База данных не найдена по пути: {DB_BASE_DIR}", flush=True)
        return []

    raw_items = []
    for root, _, files in os.walk(DB_BASE_DIR):
        for filename in files:
            if filename.endswith(".json"):
                filepath = os.path.join(root, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        category = data.get("category") or data.get("type", "")
                        
                        if not category or category in ["artefact", "artifacts", "Артефакт"] or "artefact" in root.lower():
                            raw_items.append(data)
                except Exception as e:
                    print(f"⚠️ Ошибка чтения файла {filename}: {e}", flush=True)

    print(f"📄 Загружено исходных артефактов из JSON: {len(raw_items)}", flush=True)

    tracked_items = []
    for item in raw_items:
        item_id = item.get("id") or item.get("item_id")
        if not item_id:
            continue

        if isinstance(item.get("name"), dict):
            item_name = item.get("name", {}).get("lines", {}).get("ru", item_id)
        else:
            item_name = item.get("name", item_id)

        item_variants = parse_variants(item)

        # Всегда генерируем комбинации для всех 6 редкостей каждого артефакта
        rarities_to_apply = ALL_RARITIES

        for rarity in rarities_to_apply:
            for variant in item_variants:
                tracked_items.append({
                    "item_id": item_id,
                    "item_name": item_name,
                    "category": "Артефакт",
                    "rarity": rarity,
                    "variant": variant
                })

    print(f"📌 Итого сформировано комбинаций для отслеживания: {len(tracked_items)}", flush=True)
    print("✅ Инициализация завершена.", flush=True)

    return tracked_items


async def fetch_auction_price(client: httpx.AsyncClient, item_id: str, rarity: str, variant: str) -> tuple[float | None, int]:
    url = f"{BASE_API_URL}/auction/{item_id}/lots"
    params = {
        "limit": 200,
        "sort": "buyout_price",
        "order": "asc",
        "additional": "true"
    }

    try:
        headers = await auth_manager.get_headers(client)
        res = await client.get(url, params=params, headers=headers, timeout=10.0)

        # Если токен истек, обновляем и повторяем запрос
        if res.status_code == 401:
            print("🔄 Токен истек, обновляем...", flush=True)
            if await auth_manager.refresh_token(client):
                headers = await auth_manager.get_headers(client)
                res = await client.get(url, params=params, headers=headers, timeout=10.0)

        if res.status_code == 200:
            data = res.json()
            lots = data.get("lots", [])
            if not lots:
                return None, 0

            target_qlt = RARITY_TO_QLT.get(rarity, 0)
            buyout_prices = []

            for lot in lots:
                add_data = lot.get("additional") or lot.get("info") or {}
                
                # Качество (редкость): qlt / quality
                lot_qlt = add_data.get("qlt", add_data.get("quality", 0))
                # Заточка (уровень): upg / upgrade / level
                lot_upg = str(add_data.get("upg", add_data.get("upgrade", add_data.get("level", 0))))

                # Фильтрация по точной редкости и заточке
                if int(lot_qlt) == target_qlt and lot_upg == str(variant):
                    price = lot.get("buyoutPrice") or lot.get("buyout_price") or lot.get("startPrice")
                    if price and price > 0:
                        buyout_prices.append(price)

            if buyout_prices:
                return min(buyout_prices), len(buyout_prices)

        elif res.status_code != 404:
            print(f"⚠️ API [{item_id}] статус {res.status_code}: {res.text}", flush=True)

    except Exception as e:
        print(f"⚠️ Ошибка запроса API [{item_id}]: {e}", flush=True)

    return None, 0


async def save_to_supabase(item_id: str, item_name: str, rarity: str, category: str, variant: str, min_price: float, total_lots: int):
    try:
        payload = {
            "item_id": item_id,
            "item_name": item_name,
            "rarity": rarity,
            "category": category,
            "variant": variant,
            "min_buyout_price": min_price,
            "total_lots": total_lots,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        supabase.table("price_history").insert(payload).execute()
    except Exception as e:
        print(f"⚠️ Ошибка сохранения в Supabase [{item_name}]: {e}", flush=True)


async def run_collector_cycle(tracked_items: list[dict]):
    now_str = datetime.now().strftime("%H:%M:%S")
    print(f"\n--- Сбор цен по выкупу [{now_str}] ---", flush=True)

    async with httpx.AsyncClient() as client:
        # Предварительная проверка авторизации
        if not await auth_manager.get_headers(client):
            print("❌ Пропуск цикла: не удалось получить токен EXBO.", flush=True)
            return

        for idx, item in enumerate(tracked_items):
            item_id = item["item_id"]
            item_name = item["item_name"]
            rarity = item["rarity"]
            variant = item["variant"]

            if idx % 50 == 0:
                print(f"🔄 Прогресс сбора: {idx}/{len(tracked_items)} предметов обработано...", flush=True)

            min_price, total_lots = await fetch_auction_price(client, item_id, rarity, variant)

            if min_price is not None:
                var_str = f" +{variant}" if variant != "0" else ""
                print(f"[+] [Артефакт] {item_name}{var_str} ({rarity}): выкуп {min_price:,.0f} руб. (лотов: {total_lots})", flush=True)
                
                await save_to_supabase(
                    item_id=item_id,
                    item_name=item_name,
                    rarity=rarity,
                    category=item["category"],
                    variant=variant,
                    min_price=min_price,
                    total_lots=total_lots
                )

            # Ограничение частоты запросов к EXBO (Rate Limit)
            await asyncio.sleep(0.2)


async def main():
    tracked_items = initialize_items_database()
    if not tracked_items:
        print("❌ Не найдено предметов для отслеживания. Завершение работы.", flush=True)
        return

    while True:
        try:
            await run_collector_cycle(tracked_items)
        except Exception as e:
            print(f"⚠️ Ошибка в главном цикле коллектора: {e}", flush=True)
        
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
