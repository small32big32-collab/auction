from datetime import datetime, timezone
import json
from pathlib import Path
import time
import httpx
from supabase import create_client

SUPABASE_URL = "https://mdursbqpogprwzbhjzxz.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1kdXJzYnFwb2dwcnd6Ymhqenh6Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NzE0MzU5NCwiZXhwIjoyMTAyNzE5NTk0fQ.AXb2IUi3VOY1hNHxrvZUpsk4f6ycGDc2qaC_4zzM1Mo"
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

CLIENT_ID = "3919"
CLIENT_SECRET = "ayazYFVWHuFnpWBvOAYWWvEDykdntMOgDNNppKTl"
AUTH_URL = "https://exbo.net/oauth/token"

BOT_TOKEN = "8877726623:AAEV6YFhuuBnzKWiJZxwiWM49khiaxazwRE"

FETCH_INTERVAL = 900

TARGET_CATEGORIES = {
    "artefact": "Артефакт",
}

QUALITY_MAP = {
    0: "Обычный",
    1: "Необычный",
    2: "Особый",
    3: "Редкий",
    4: "Исключительный",
    5: "Легендарный",
}

# Известные русские наименования редкостей для поиска в infoBlocks
KNOWN_RARITIES = ["Обычный", "Необычный", "Особый", "Редкий", "Исключительный", "Легендарный"]


def extract_rarity_from_json(data: dict) -> str:
    """Извлекает редкость из infoBlocks файла предмета, если она там указана"""
    info_blocks = data.get("infoBlocks", [])
    for block in info_blocks:
        elements = block.get("elements", [])
        for el in elements:
            key_lines = el.get("key", {}).get("lines", {})
            ru_key = key_lines.get("ru", "")
            if ru_key in KNOWN_RARITIES:
                return ru_key
    
    # Резервный поиск по полю color
    color = data.get("color", "").upper()
    if "UNCOMMON" in color: return "Необычный"
    if "SPECIAL" in color: return "Особый"
    if "RARE" in color: return "Редкий"
    if "EXCEPTIONAL" in color: return "Исключительный"
    if "LEGENDARY" in color: return "Легендарный"
    
    return "Обычный"


def load_valuable_items() -> list[dict]:
    base_dir = Path(__file__).parent / "stalzone-database" / "ru" / "items"
    items_list = []
    if not base_dir.exists():
        return items_list

    for cat_folder, cat_name in TARGET_CATEGORIES.items():
        folder_path = base_dir / cat_folder
        if not folder_path.exists():
            continue

        for path in folder_path.rglob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    item_id = data.get("id")
                    lines = data.get("name", {}).get("lines", {})
                    name = lines.get("ru") or lines.get("en") or item_id
                    
                    # Определение редкости прямо из карточки предмета
                    default_rarity = extract_rarity_from_json(data)

                    if item_id and name:
                        items_list.append({
                            "id": item_id,
                            "name": name,
                            "category": cat_name,
                            "default_rarity": default_rarity
                        })
            except Exception:
                continue
    return items_list


def get_exbo_token(client: httpx.Client) -> str | None:
    for _ in range(3):
        try:
            auth_res = client.post(
                AUTH_URL,
                data={
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "grant_type": "client_credentials",
                },
                timeout=10.0,
            )
            if auth_res.status_code == 200:
                return auth_res.json().get("access_token")
        except Exception:
            time.sleep(2)
    return None


def send_telegram_notification(user_id: int, text: str):
    """Отправка уведомления пользователю в Telegram"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(url, json={
                "chat_id": user_id,
                "text": text,
                "parse_mode": "Markdown"
            })
    except Exception as e:
        print(f"⚠️ Ошибка отправки уведомления в Telegram для {user_id}: {e}")


def check_user_snipers(item_id: str, rarity_name: str, current_price: float, total_lots: int):
    """Проверка активных снайперов в Supabase для конкретного предмета и редкости"""
    try:
        res = supabase.table("user_snipers").select("*").eq("item_id", item_id).eq("rarity", rarity_name).execute()
        snipers = res.data
        if not snipers:
            return

        for sniper in snipers:
            threshold = float(sniper["threshold"])
            if current_price <= threshold:
                user_id = sniper["user_id"]
                item_name = sniper["item_name"]
                
                msg = (
                    f"🔥 **ВНИМАНИЕ! СНАЙПЕР СРАБОТАЛ!** 🔥\n\n"
                    f"📦 Предмет: *{item_name}* (`{rarity_name}`)\n"
                    f"📉 Текущая цена: **{current_price:,.0f} руб.** (Ваш порог: {threshold:,.0f} руб.)\n"
                    f"📊 Доступно лотов: {total_lots}\n"
                    f"🕒 Время: `{time.strftime('%Y-%m-%d %H:%M')}`"
                )
                
                send_telegram_notification(user_id, msg)
                supabase.table("user_snipers").delete().eq("id", sniper["id"]).execute()
    except Exception as e:
        print(f"⚠️ Ошибка проверки снайперов: {e}")


def collect_iteration(items: list[dict]):
    if not items:
        return

    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        token = get_exbo_token(client)
        if not token:
            print("⚠️ Не удалось получить OAuth-токен, пропускаем итерацию.")
            return

        headers = {"Authorization": f"Bearer {token}"}
        print(f"\n--- Сбор цен по выкупу (Артефакты) [{time.strftime('%H:%M:%S')}] ---")

        for item in items:
            item_id = item["id"]
            try:
                auction_url = f"https://eapi.stalzone.com/ru/auction/{item_id}/lots"
                res = client.get(
                    auction_url,
                    headers=headers,
                    params={"limit": 50, "sort": "buyout_price", "order": "asc"},
                )

                if res.status_code == 200:
                    data = res.json()
                    lots = data.get("lots", [])

                    if not lots:
                        continue

                    rarity_data = {}
                    for lot in lots:
                        # 1. Попытка вытащить качество из самого лота
                        qlt = (
                            lot.get("qlt")
                            if lot.get("qlt") is not None
                            else lot.get("quality")
                        )
                        if qlt is None and "item" in lot:
                            qlt = lot["item"].get("qlt") or lot["item"].get("quality")

                        # 2. Если в лоте качества нет, берем сгенерированное из файла предмета
                        if qlt is not None:
                            rarity_name = QUALITY_MAP.get(int(qlt), item.get("default_rarity", "Обычный"))
                        else:
                            rarity_name = item.get("default_rarity", "Обычный")

                        price = lot.get("buyoutPrice") or lot.get("startPrice", 0)
                        if price > 0:
                            if rarity_name not in rarity_data:
                                rarity_data[rarity_name] = {"min_price": price, "count": 0}
                            rarity_data[rarity_name]["count"] += 1
                            if price < rarity_data[rarity_name]["min_price"]:
                                rarity_data[rarity_name]["min_price"] = price

                    for r_name, info in rarity_data.items():
                        row = {
                            "item_id": item_id,
                            "item_name": item["name"],
                            "rarity": r_name,
                            "category": item["category"],
                            "min_buyout_price": info["min_price"],
                            "total_lots": info["count"],
                        }
                        supabase.table("price_history").insert(row).execute()
                        
                        print(
                            f"[+] [{item['category']}] {item['name']} ({r_name}): выкуп"
                            f" {info['min_price']:,} руб."
                        )

                        check_user_snipers(item_id, r_name, info["min_price"], info["count"])

                elif res.status_code == 429:
                    print("⚠️ Слишком много запросов (Rate Limit), ждем 5 секунд...")
                    time.sleep(5)
            except Exception as e:
                print(f"⚠️ Ошибка по предмету {item['name']} ({item_id}): {e}")

            time.sleep(0.3)


if __name__ == "__main__":
    print("🔄 Загрузка локальной базы предметов (Только Артефакты)...")
    cached_items = load_valuable_items()
    print(f"✅ Загружено предметов: {len(cached_items)}")

    while True:
        try:
            collect_iteration(cached_items)
        except Exception as e:
            print(f"⚠️ Ошибка в итерации сбора: {e}")

        print(f"💤 Ожидание следующего сбора ({FETCH_INTERVAL // 60} минут)...")
        time.sleep(FETCH_INTERVAL)
