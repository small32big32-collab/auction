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

# Все 6 градаций редкости артефактов
ALL_RARITIES = [
    "Обычный",
    "Необычный",
    "Особый",
    "Редкий",
    "Исключительный",
    "Легендарный"
]


def initialize_items_database():
    """Рекурсивно сканирует директорию с базой данных и формирует список для отслеживания всех 6 редкостей."""
    print("🚀 Старт процесса инициализации коллектора...")
    print(f"🔍 Рабочая директория: {os.getcwd()}")
    print(f"🔍 Директория файла: {os.path.dirname(os.path.abspath(__file__))}")

    if not os.path.exists(DB_BASE_DIR):
        print(f"❌ База данных не найдена по пути: {DB_BASE_DIR}")
        return []

    print(f"✅ База данных найдена: {DB_BASE_DIR}")

    raw_items = []
    
    # Рекурсивный поиск всех .json файлов во всех подпапках DB_BASE_DIR
    for root, _, files in os.walk(DB_BASE_DIR):
        for filename in files:
            if filename.endswith(".json"):
                filepath = os.path.join(root, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        
                        # Проверяем категорию (если поле присутствуют в JSON)
                        category = data.get("category") or data.get("type", "")
                        
                        # Если категория артефакт или файл находится в папке artefact / не размечен
                        if not category or category in ["artefact", "artifacts", "Артефакт"] or "artefact" in root.lower():
                            raw_items.append(data)
                except Exception as e:
                    print(f"⚠️ Ошибка чтения файла {filename}: {e}")

    print(f"📄 Найдено и успешно загружено предметов в категории 'artefact': {len(raw_items)}")

    tracked_items = []
    rarity_stats = {r: 0 for r in ALL_RARITIES}

    for item in raw_items:
        item_id = item.get("id") or item.get("item_id")
        
        # Получаем наименование предмета из структуры локализации или поля name
        if isinstance(item.get("name"), dict):
            item_name = item.get("name", {}).get("lines", {}).get("ru", item_id)
        else:
            item_name = item.get("name", item_id)

        if not item_id:
            continue

        for rarity in ALL_RARITIES:
            tracked_items.append({
                "item_id": item_id,
                "item_name": item_name,
                "category": "artefact",
                "rarity": rarity
            })
            rarity_stats[rarity] += 1

    print(f"📊 Распределение редкостей в БД: {rarity_stats}")
    print(f"📌 Итого сформировано элементов в списке: {len(tracked_items)}")
    print(f"✅ Инициализация завершена. Загружено предметов: {len(tracked_items)}")

    return tracked_items


async def fetch_auction_price(client: httpx.AsyncClient, item_id: str, rarity: str) -> tuple[float | None, int]:
    """Запрашивает минимальную цену выкупа и количество лотов из API аукциона."""
    try:
        url = f"{STALZONE_AUCTION_API}/{item_id}"
        params = {"rarity": rarity}
        res = await client.get(url, params=params, timeout=10.0)

        if res.status_code == 200:
            data = res.json()
            lots = data.get("lots", [])
            if not lots:
                return None, 0

            buyout_prices = [lot.get("buyout_price") or lot.get("price") for lot in lots if lot.get("buyout_price") or lot.get("price")]
            if buyout_prices:
                return min(buyout_prices), len(lots)

    except Exception:
        pass

    return None, 0


async def save_to_supabase(item_id: str, item_name: str, rarity: str, category: str, min_price: float, total_lots: int):
    """Записывает точечный снимок цен в таблицу price_history."""
    try:
        payload = {
            "item_id": item_id,
            "item_name": item_name,
            "rarity": rarity,
            "category": category,
            "min_buyout_price": min_price,
            "total_lots": total_lots,
            "created_at": datetime.utcnow().isoformat()
        }
        supabase.table("price_history").insert(payload).execute()
    except Exception as e:
        print(f"⚠️ Ошибка сохранения в Supabase [{item_name} - {rarity}]: {e}")


async def run_collector_cycle(tracked_items: list[dict]):
    """Запускает один полный круг парсинга по всем предметам и редкостям."""
    now_str = datetime.now().strftime("%H:%M:%S")
    print(f"\n--- Сбор цен по выкупу (Артефакты) [{now_str}] ---")

    async with httpx.AsyncClient() as client:
        for item in tracked_items:
            item_id = item["item_id"]
            item_name = item["item_name"]
            rarity = item["rarity"]

            min_price, total_lots = await fetch_auction_price(client, item_id, rarity)

            if min_price is not None:
                print(f"[+] [Артефакт] {item_name} ({rarity}): выкуп {min_price:,.0f} руб. (лотов: {total_lots})")
                await save_to_supabase(
                    item_id=item_id,
                    item_name=item_name,
                    rarity=rarity,
                    category=item["category"],
                    min_price=min_price,
                    total_lots=total_lots
                )

            await asyncio.sleep(0.1)


async def main():
    tracked_items = initialize_items_database()
    if not tracked_items:
        print("❌ Не найдено предметов для отслеживания. Завершение работы.")
        return

    while True:
        try:
            await run_collector_cycle(tracked_items)
        except Exception as e:
            print(f"⚠️ Ошибка в главном цикле коллектора: {e}")
        
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
