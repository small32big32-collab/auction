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

FETCH_INTERVAL = 900

TARGET_CATEGORIES = {
    "armor": "Броня",
    "artefact": "Артефакт",
}

# Соответствие цифрового качества EXBO текстовым редкостям
QUALITY_MAP = {
    0: "Обычный",
    1: "Необычный",
    2: "Особый",
    3: "Редкий",
    4: "Исключительный",
    5: "Легендарный",
}


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

          if item_id and name:
            items_list.append(
                {"id": item_id, "name": name, "category": cat_name}
            )
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


def collect_iteration(items: list[dict]):
  if not items:
    return

  with httpx.Client(timeout=10.0, follow_redirects=True) as client:
    token = get_exbo_token(client)
    if not token:
      print("⚠️ Не удалось получить OAuth-токен, пропускаем итерацию.")
      return

    headers = {"Authorization": f"Bearer {token}"}
    print(
        f"\n--- Сбор цен по выкупу ({time.strftime('%H:%M:%S')}) ---"
    )

    # Возьмем для отладки первый же предмет со списком лотов
    debug_printed = False

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

          # Отладочный вывод для понимания структуры первого попавшегося лота
          if not debug_printed:
            print(f"🔍 DEBUG ЛОТ ПРЕДМЕТА [{item['name']}]: {lots[0]}")
            debug_printed = True

          rarity_data = {}
          for lot in lots:
            # Пытаемся найти поле качества в разных возможных вариациях API
            qlt = (
                lot.get("qlt")
                if lot.get("qlt") is not None
                else lot.get("quality")
            )
            if qlt is None and "item" in lot:
              qlt = lot["item"].get("qlt") or lot["item"].get("quality", 0)
            if qlt is None:
              qlt = 0

            rarity_name = QUALITY_MAP.get(int(qlt), "Обычный")

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

        elif res.status_code == 429:
          print(
              "⚠️ Слишком много запросов (Rate Limit), ждем 5 секунд..."
          )
          time.sleep(5)
      except Exception as e:
        print(f"⚠️ Ошибка по предмету {item['name']} ({item_id}): {e}")

      time.sleep(0.3)


if __name__ == "__main__":
  print("🔄 Загрузка локальной базы предметов (Броня и Артефакты)...")
  cached_items = load_valuable_items()
  print(f"✅ Загружено предметов: {len(cached_items)}")

  while True:
    try:
      collect_iteration(cached_items)
    except Exception as e:
      print(f"⚠️ Ошибка в итерации сбора: {e}")

    print(f"💤 Ожидание следующего сбора ({FETCH_INTERVAL // 60} минут)...")
    time.sleep(FETCH_INTERVAL)
