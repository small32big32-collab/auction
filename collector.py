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

KNOWN_RARITIES = ["Обычный", "Необычный", "Особый", "Редкий", "Исключительный", "Легендарный"]


def extract_lot_rarity(lot: dict, default_rarity: str = "Обычный") -> str:
    """Извлекает редкость конкретного лота аукциона с проверкой дополнительного блока additional"""
    if not isinstance(lot, dict):
        return default_rarity

    possible_sources = [
        lot.get("additional"),
        lot,
        lot.get("item"),
        lot.get("item", {}).get("additional") if isinstance(lot.get("item"), dict) else None,
    ]

    for source in possible_sources:
        if isinstance(source, dict):
            for key in ["qlt", "quality", "rarity", "tier"]:
                val = source.get(key)
                if val is not None:
                    try:
                        q_int = int(val)
                        if q_int in QUALITY_MAP:
                            return QUALITY_MAP[q_int]
                    except (ValueError, TypeError):
                        if str(val) in KNOWN_RARITIES:
                            return str(val)

    return default_rarity


def extract_rarity_from_json(data: dict, file_path: Path) -> str:
    """Извлечение дефолтной редкости из файла шаблона предмета"""
    try:
        if isinstance(data, dict):
            info_blocks = data.get("infoBlocks")
            if isinstance(info_blocks, list):
                for block in info_blocks:
                    if isinstance(block, dict):
                        elements = block.get("elements")
                        if isinstance(elements, list):
                            for el in elements:
                                if isinstance(el, dict):
                                    key_dict = el.get("key")
                                    if isinstance(key_dict, dict):
                                        key_str = str(key_dict.get("key", ""))
                                        if "quality" in key_str or "rarity" in key_str:
                                            lines = key_dict.get("lines")
                                            if isinstance(lines, dict):
                                                ru_text = lines.get("ru", "")
                                                if ru_text in KNOWN_RARITIES:
                                                    return ru_text

                                    val_dict = el.get("value")
                                    if isinstance(val_dict, dict):
                                        lines = val_dict.get("lines")
                                        if isinstance(lines, dict):
                                            ru_val = lines.get("ru", "")
                                            if ru_val in KNOWN_RARITIES:
                                                return ru_val

            color = str(data.get("color", "")).upper()
            if "UNCOMMON" in color: return "Необычный"
            if "SPECIAL" in color: return "Особый"
            if "RARE" in color: return "Редкий"
            if "EXCEPTIONAL" in color: return "Исключительный"
            if "LEGENDARY" in color: return "Легендарный"
    except Exception:
        pass

    path_str = str(file_path).lower()
    if "uncommon" in path_str or "необыч" in path_str: return "Необычный"
    if "special" in path_str or "особ" in path_str: return "Особый"
    if "rare" in path_str or "редк" in path_str: return "Редкий"
    if "exceptional" in path_str or "исключ" in path_str: return "Исключительный"
    if "legendary" in path_str or "легенд" in path_str: return "Легендарный"

    return "Обычный"


def load_valuable_items() -> list[dict]:
    print(f"🔍 Рабочая директория: {Path.cwd()}")
    print(f"🔍 Директория файла: {Path(__file__).parent}")

    possible_paths = [
        Path("/app/stalzone-database/ru/items"),
        Path("/app/auction/stalzone-database/ru/items"),
        Path(__file__).parent / "stalzone-database" / "ru" / "items",
        Path(__file__).parent / "auction" / "stalzone-database" / "ru" / "items",
        Path.cwd() / "stalzone-database" / "ru" / "items",
        Path.cwd() / "auction" / "stalzone-database" / "ru" / "items",
        Path.cwd().parent / "stalzone-database" / "ru" / "items",
    ]

    base_dir = None
    for p in possible_paths:
        if p.exists():
            base_dir = p
            break

    items_list = []
    if not base_dir:
        print("⚠️ ОШИБКА: Папка 'stalzone-database' не найдена ни по одному из путей!")
        return items_list

    print(f"✅ База данных найдена: {base_dir}")

    for cat_folder, cat_name in TARGET_CATEGORIES.items():
        folder_path = base_dir / cat_folder
        if not folder_path.exists():
            continue

        subfolders = [x for x in folder_path.iterdir() if x.is_dir()]

        json_files = []
        for sub in subfolders:
            if sub.name == "_variants":
                continue
            for file_path in sub.glob("*.json"):
                json_files.append(file_path)

        print(f"📄 Найдено основных JSON-файлов предметов в категории '{cat_folder}': {len(json_files)}")

        success_count = 0
        for path in json_files:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                    if not isinstance(data, dict):
                        continue

                    item_id = path.stem

                    name = None
                    name_block = data.get("name")
                    if isinstance(name_block, dict):
                        lines = name_block.get("lines")
                        if isinstance(lines, dict):
                            name = lines.get("ru") or lines.get("en")
                    elif isinstance(name_block, str):
                        name = name_block

                    if not name:
                        name = item_id

                    default_rarity = extract_rarity_from_json(data, path)

                    items_list.append({
                        "id": item_id,
                        "name": name,
                        "category": cat_name,
                        "default_rarity": default_rarity
                    })
                    success_count += 1
            except Exception as e:
                print(f"⚠️ Ошибка чтения {path.name}: {e}")
                continue

        print(f"✅ Успешно загружено предметов в категории '{cat_folder}': {success_count}")

    print(f"📦 Итого сформировано элементов в списке: {len(items_list)}")
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
                        rarity_name = extract_lot_rarity(lot, item.get("default_rarity", "Обычный"))

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
    print("🔄 Старт процесса инициализации коллектора...")
    cached_items = load_valuable_items()
    print(f"✅ Инициализация завершена. Загружено предметов: {len(cached_items)}")

    while True:
        try:
            collect_iteration(cached_items)
        except Exception as e:
            print(f"⚠️ Ошибка в итерации сбора: {e}")

        print(f"💤 Ожидание следующего сбора ({FETCH_INTERVAL // 60} минут)...")
        time.sleep(FETCH_INTERVAL)
