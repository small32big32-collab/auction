import json
from pathlib import Path
import httpx

CLIENT_ID = "3919"
CLIENT_SECRET = "ayazYFVWHuFnpWBvOAYWWvEDykdntMOgDNNppKTl"
AUTH_URL = "https://exbo.net/oauth/token"

ITEM_ID = "04yr"


def get_item_name_local(item_id: str) -> str:
  """Ищет предмет в локально клонированном репозитории stalzone-database."""
  base_dir = Path(__file__).parent / "stalzone-database" / "ru" / "items"

  if not base_dir.exists():
    return "Папка stalzone-database еще не скачалась"

  for path in base_dir.rglob(f"{item_id}.json"):
    try:
      with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        return (
            data.get("name", {}).get("lines", {}).get("ru")
            or data.get("name", {}).get("value")
            or item_id
        )
    except Exception:
      pass
  return "Предмет не найден в локальной базе"


with httpx.Client(timeout=15.0) as client:
  try:
    # 1. Авторизация
    auth_res = client.post(
        AUTH_URL,
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "client_credentials",
        },
    )
    access_token = auth_res.json().get("access_token")

    # 2. Быстрое чтение названия с диска
    item_name = get_item_name_local(ITEM_ID)

    # 3. Запрос лотов аукциона Stalzone
    headers = {"Authorization": f"Bearer {access_token}"}
    auction_url = f"https://eapi.stalzone.com/ru/auction/{ITEM_ID}/lots"
    params = {"limit": 5, "offset": 0, "sort": "buyout_price", "order": "asc"}

    auction_res = client.get(auction_url, headers=headers, params=params)

    if auction_res.status_code == 200:
      data = auction_res.json()
      print("=" * 45)
      print(f" Предмет: {item_name}")
      print(f" Всего лотов на аукционе: {data.get('total', 0)}")
      print("=" * 45)
      print(f"{'№':<3} | {'Кол-во':<7} | {'Старт':<10} | {'Выкуп':<10}")
      print("-" * 45)

      for idx, lot in enumerate(data.get("lots", []), start=1):
        amount = lot.get("amount", 1)
        start = f"{lot.get('startPrice', 0):,}".replace(",", " ")
        buyout = f"{lot.get('buyoutPrice', 0):,}".replace(",", " ")
        print(f"{idx:<3} | {amount:<7} | {start:<10} | {buyout:<10}")
      print("-" * 45)
    else:
      print("Ошибка аукциона:", auction_res.text)

  except Exception as e:
    print(f"Ошибка выполнения: {e}")