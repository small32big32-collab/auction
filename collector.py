import os
import json
import asyncio
import httpx
from datetime import datetime
from supabase import create_client, Client

# Конфигурация окружения
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://your-supabase-project.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "your-supabase-service-role-key")
STALZONE_AUCTION_API = os.getenv("STALZONE_AUCTION_API", "https://api.stalzone.ru/auction")
DB_BASE_DIR = os.getenv("DB_BASE_DIR", "/app/stalzone-database/ru/items")

# Инициализация Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Маппинг цветов из JSON в русские названия редкостей
COLOR_MAP = {
    "DEFAULT": "Обычный",
    "UNCOMMON": "Необычный",
    "SPECIAL": "Особый",
    "RARE": "Редкий",
    "EXCLUSIVE": "Исключительный",
    "LEGENDARY": "Легендарный",
}

ALL_RARITIES = ["Обычный", "Необычный", "Особый", "Редкий", "Исключительный", "Легендарный"]


def parse_variants(item_data: dict) -> list[str]:
    """Извлекает уровни заточки/варианты из поля _variants."""
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
    """Рекурсивно сканирует JSON-файлы, связывает редкости по color и варианты заточки."""
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
        raw_color = str(item.get("color", "")).upper()
        detected_rarity = COLOR_MAP.get(raw_color)
        rarities_to_apply = [detected_rarity] if detected_rarity else ALL_RARITIES

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
    """Запрашивает минимальную цену выкупа с учетом редкости и заточки."""
    try:
        url = f"{STALZONE_AUCTION_API}/{item_id}"
        params = {"rarity": rarity, "variant": variant}
        res = await client.get(url, params=params, timeout=10.0)

        if res.status_code == 200:
            data = res.json()
            lots = data.get("lots", [])
            if not lots:
                return None, 0

            buyout_prices = [
                lot.get("buyout_price") or lot.get("price") 
                for lot in lots 
                if lot.get("buyout_price") or lot.get("price")
            ]
            if buyout_prices:
                return min(buyout_prices), len(lots)
        else:
            print(f"⚠️ API [{item_id}] ответил со статусом {res.status_code}", flush=True)

    except Exception as e:
        print(f"⚠️ Ошибка запроса API [{item_id}]: {e}", flush=True)

    return None, 0


async def save_to_supabase(item_id: str, item_name: str, rarity: str, category: str, variant: str, min_price: float, total_lots: int):
    """Записывает точечный снимок цен в таблицу price_history."""
    try:
        payload = {
            "item_id": item_id,
            "item_name": item_name,
            "rarity": rarity,
            "category": category,
            "variant": variant,
            "min_buyout_price": min_price,
            "total_lots": total_lots,
            "created_at": datetime.utcnow().isoformat()
        }
        supabase.table("price_history").insert(payload).execute()
    except Exception as e:
        print(f"⚠️ Ошибка сохранения в Supabase [{item_name} - {rarity} +{variant}]: {e}", flush=True)


async def run_collector_cycle(tracked_items: list[dict]):
    """Запускает один полный круг опроса аукциона."""
    now_str = datetime.now().strftime("%H:%M:%S")
    print(f"\n--- Сбор цен по выкупу [{now_str}] ---", flush=True)

    async with httpx.AsyncClient() as client:
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

            await asyncio.sleep(0.1)


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
