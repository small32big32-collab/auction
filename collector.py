import os
import json
import asyncio
import httpx
from datetime import datetime, timezone
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

EXBO_CLIENT_ID = os.getenv("EXBO_CLIENT_ID", "")
EXBO_CLIENT_SECRET = os.getenv("EXBO_CLIENT_SECRET", "")
REGION = os.getenv("STALCRAFT_REGION", "RU")

AUTH_URL = "https://exbo.net/oauth/token"
BASE_API_URL = f"https://eapi.stalcraft.net/{REGION.lower()}"

DB_BASE_DIR = os.getenv("DB_BASE_DIR", "/app/stalzone-database/ru/items")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

ALL_RARITIES = ["Обычный", "Необычный", "Особый", "Редкий", "Исключительный", "Легендарный"]
RARITY_TO_QLT = {"Обычный": 0, "Необычный": 1, "Особый": 2, "Редкий": 3, "Исключительный": 4, "Легендарный": 5}

# Множество для защиты от зацикливания повторных уведомлений воркера
triggered_snipers_cache = set()

class ExboAuthManager:
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
        except Exception as e:
            print(f"❌ Ошибка токена EXBO: {e}", flush=True)
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
                except Exception:
                    pass

    tracked_items = []
    for item in raw_items:
        item_id = item.get("id") or item.get("item_id")
        if not item_id:
            continue
        item_name = item.get("name", {}).get("lines", {}).get("ru", item_id) if isinstance(item.get("name"), dict) else item.get("name", item_id)
        item_variants = parse_variants(item)

        for rarity in ALL_RARITIES:
            for variant in item_variants:
                tracked_items.append({
                    "item_id": item_id,
                    "item_name": item_name,
                    "category": "Артефакт",
                    "rarity": rarity,
                    "variant": variant
                })
    return tracked_items

async def fetch_auction_price_direct(client: httpx.AsyncClient, item_id: str, rarity: str, variant: str = "0") -> tuple[float | None, int]:
    url = f"{BASE_API_URL}/auction/{item_id}/lots"
    params = {"limit": 200, "sort": "buyout_price", "order": "asc", "additional": "true"}

    try:
        headers = await auth_manager.get_headers(client)
        res = await client.get(url, params=params, headers=headers, timeout=10.0)

        if res.status_code == 401:
            if await auth_manager.refresh_token(client):
                headers = await auth_manager.get_headers(client)
                res = await client.get(url, params=params, headers=headers, timeout=10.0)

        if res.status_code == 200:
            lots = res.json().get("lots", [])
            if not lots:
                return None, 0

            target_qlt = RARITY_TO_QLT.get(rarity, 0)
            buyout_prices = []

            for lot in lots:
                add_data = lot.get("additional") or lot.get("info") or {}
                lot_qlt = add_data.get("qlt", add_data.get("quality", 0))
                lot_upg = str(add_data.get("upg", add_data.get("upgrade", add_data.get("level", 0))))

                if int(lot_qlt) == target_qlt and lot_upg == str(variant):
                    price = lot.get("buyoutPrice") or lot.get("buyout_price") or lot.get("startPrice")
                    if price and price > 0:
                        buyout_prices.append(price)

            if buyout_prices:
                return min(buyout_prices), len(buyout_prices)
    except Exception as e:
        print(f"⚠️ Ошибка прямого запроса EXBO API [{item_id}]: {e}", flush=True)

    return None, 0

async def send_telegram_notification(client: httpx.AsyncClient, user_id: int, item_name: str, rarity: str, min_price: float, threshold: float):
    text = (
        f"🎯 **СНАЙПЕР СРАБОТАЛ!**\n\n"
        f"📦 Предмет: **{item_name}** (`{rarity}`)\n"
        f"💰 Прямая цена в EXBO API: **{min_price:,.0f} руб.**\n"
        f"🎯 Ваш порог: **{threshold:,.0f} руб.**\n\n"
        f"⚡ Поспешите забрать лот!"
    )
    tg_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": user_id, "text": text, "parse_mode": "Markdown"}
    
    try:
        await client.post(tg_url, json=payload, timeout=5.0)
        print(f"🔔 Сообщение успешно отправлено пользователю {user_id}", flush=True)
    except Exception as e:
        print(f"⚠️ Ошибка отправки в Telegram: {e}", flush=True)

async def sniper_monitoring_worker():
    print("🚀 Запущен независимый воркер снайперов (Прямой опрос EXBO API)...", flush=True)
    
    async with httpx.AsyncClient() as client:
        while True:
            try:
                res = supabase.table("user_snipers").select("*").execute()
                snipers = res.data or []

                if snipers:
                    for sniper in snipers:
                        s_id = sniper.get("id")
                        item_id = sniper.get("item_id")
                        rarity = sniper.get("rarity", "Обычный")
                        threshold = float(sniper.get("threshold", 0))
                        user_id = sniper.get("user_id")
                        item_name = sniper.get("item_name", item_id)

                        min_price, _ = await fetch_auction_price_direct(client, item_id, rarity, variant="0")

                        if min_price is not None:
                            if min_price <= threshold and user_id:
                                # Предотвращение дубликатов уведомлений
                                if s_id not in triggered_snipers_cache:
                                    await send_telegram_notification(client, user_id, item_name, rarity, min_price, threshold)
                                    triggered_snipers_cache.add(s_id)
                            else:
                                # Если цена выросла обратно, сбрасываем флаг для следующего падения
                                triggered_snipers_cache.discard(s_id)

                        await asyncio.sleep(0.3)
                else:
                    print("🎯 [Снайпер-Воркер] Активных снайперов нет.", flush=True)

            except Exception as e:
                print(f"⚠️ Ошибка в снайпер-воркере: {e}", flush=True)

            await asyncio.sleep(10)

async def general_collector_worker(tracked_items: list[dict]):
    async with httpx.AsyncClient() as client:
        while True:
            total = len(tracked_items)
            for idx, item in enumerate(tracked_items, start=1):
                min_price, total_lots = await fetch_auction_price_direct(client, item["item_id"], item["rarity"], item["variant"])
                
                if min_price is not None:
                    try:
                        payload = {
                            "item_id": item["item_id"],
                            "item_name": item["item_name"],
                            "rarity": item["rarity"],
                            "category": item["category"],
                            "variant": item["variant"],
                            "min_buyout_price": min_price,
                            "total_lots": total_lots,
                            "created_at": datetime.now(timezone.utc).isoformat()
                        }
                        supabase.table("price_history").insert(payload).execute()
                    except Exception as e:
                        print(f"⚠️ Ошибка сохранения в БД для {item['item_id']}: {e}", flush=True)

                await asyncio.sleep(0.2)

            await asyncio.sleep(60)

async def main():
    tracked_items = initialize_items_database()
    print(f"📦 Инициализировано предметов для сбора: {len(tracked_items)}", flush=True)
    
    await asyncio.gather(
        sniper_monitoring_worker(),
        general_collector_worker(tracked_items)
    )

if __name__ == "__main__":
    asyncio.run(main())
