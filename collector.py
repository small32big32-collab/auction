import os
import time
import asyncio
import logging
import httpx
from supabase import create_client, Client

# Логирование
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# --- Настройки ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://mdursbqpogprwzbhjzxz.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1kdXJzYnFwb2dwcnd6Ymhqenh6Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NzE0MzU5NCwiZXhwIjoyMTAyNzE5NTk0fQ.AXb2IUi3VOY1hNHxrvZUpsk4f6ycGDc2qaC_4zzM1Mo")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8877726623:AAEV6YFhuuBnzKWiJZxwiWM49khiaxazwRE")

# Инициализация Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Вспомогательные функции ---

def load_tracked_items() -> list[dict]:
    """
    Загрузка списка всех отслеживаемых артефактов и предметов Stalzone.
    """
    return [
        {"item_id": "art_sun", "item_name": "Солнце", "category": "Артефакты"},
        {"item_id": "art_goldfish", "item_name": "Золотая рыбка", "category": "Артефакты"},
        {"item_id": "art_soul", "item_name": "Душа", "category": "Артефакты"},
        {"item_id": "art_bubble", "item_name": "Пузырь", "category": "Артефакты"},
        {"item_id": "art_compass", "item_name": "Компас", "category": "Артефакты"},
    ]


def sync_all_items_to_supabase(tracked_items: list[dict]):
    """
    Массовая первичная синхронизация всего каталога с таблицей `items`.
    """
    logger.info(f"🔄 Начинаем синхронизацию {len(tracked_items)} предметов с базой Supabase...")
    unique_db = {}
    
    for item in tracked_items:
        i_id = item["item_id"]
        if i_id not in unique_db:
            unique_db[i_id] = {
                "item_id": i_id,
                # Поле "id" удалено, так как в таблице items используется item_id
                "name": item.get("item_name") or item.get("name") or i_id,
                "category": item.get("category", "Артефакты")
            }

    records = list(unique_db.values())
    batch_size = 500

    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        try:
            supabase.table("items").upsert(batch, on_conflict="item_id").execute()
        except Exception as e:
            logger.error(f"⚠️ Ошибка массовой загрузки предметов в 'items': {e}")

    logger.info("✅ Синхронизация каталога предметов успешно завершена!")


async def send_telegram_notification(user_id: int, text: str):
    """
    Прямая отправка уведомления пользователю через Telegram Bot API.
    """
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": user_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json=payload, timeout=5.0)
        except Exception as e:
            logger.error(f"⚠️ Ошибка отправки уведомления user_id={user_id}: {e}")


# --- Воркеры ---

async def fetch_auction_prices_for_item(item_id: str) -> list[dict]:
    """
    Фоновая имитация/запрос к Stalzone API для получения лотов с аукциона.
    """
    rarities = ["Обычный", "Необычный", "Особый", "Редкий", "Исключительный", "Легендарный"]
    results = []
    
    for r in rarities:
        results.append({
            "item_id": item_id,
            "rarity": r,
            "min_buyout_price": 150000.0,
        })
    return results


async def general_collector_worker(tracked_items: list[dict]):
    """
    Основной цикл сбора цен с аукциона и записи в `price_history`.
    """
    logger.info("🚀 Запуск воркера сбора цен аукциона...")
    
    while True:
        try:
            for item in tracked_items:
                i_id = item["item_id"]
                i_name = item.get("item_name") or item.get("name")
                category = item.get("category", "Артефакты")

                # Получаем текущие лоты с аукциона
                auction_data = await fetch_auction_prices_for_item(i_id)
                
                history_batch = []
                for entry in auction_data:
                    # Безопасное преобразование цены в целое число (bigint), чтобы избежать ошибки 22P02
                    raw_price = entry.get("min_buyout_price")
                    min_price_int = int(float(raw_price)) if raw_price is not None else 0

                    history_batch.append({
                        "item_id": i_id,
                        "item_name": i_name,
                        "rarity": entry.get("rarity", "Обычный"),
                        "category": category,
                        "min_buyout_price": min_price_int
                        # Поле "buyout_price" удалено, так как его нет в таблице price_history
                    })

                if history_batch:
                    try:
                        supabase.table("price_history").insert(history_batch).execute()
                    except Exception as e:
                        logger.error(f"Ошибка сохранения истории цен для {i_id}: {e}")

                await asyncio.sleep(0.1) # Небольшая пауза между предметами

            logger.info("🔄 Полный круг сбора цен завершен. Ожидание перед следующим циклом...")
            await asyncio.sleep(60) # Интервал обновления базы цен (60 сек)

        except Exception as e:
            logger.error(f"⚠️ Ошибка в главном цикле коллектора: {e}")
            await asyncio.sleep(5)


async def sniper_monitoring_worker():
    """
    Воркер проверки снайперов. Сравнивает пороговые цены с последними записями в `price_history`.
    """
    logger.info("🎯 Запуск воркера мониторинга снайперов...")

    while True:
        try:
            snipers_res = supabase.table("user_snipers").select("*").execute()
            snipers = snipers_res.data or []

            if snipers:
                for sniper in snipers:
                    user_id = sniper.get("user_id")
                    item_id = sniper.get("item_id")
                    item_name = sniper.get("item_name", item_id)
                    rarity = sniper.get("rarity", "Обычный")
                    threshold = float(sniper.get("threshold", 0))

                    price_res = (
                        supabase.table("price_history")
                        .select("min_buyout_price")
                        .eq("item_id", item_id)
                        .eq("rarity", rarity)
                        .order("created_at", desc=True)
                        .limit(1)
                        .execute()
                    )

                    if price_res.data:
                        current_price = float(price_res.data[0].get("min_buyout_price") or 0)

                        if 0 < current_price <= threshold:
                            msg = (
                                f"🎯 **СНАЙПЕР СРАБОТАЛ!**\n\n"
                                f"📦 Предмет: **{item_name}**\n"
                                f"✨ Редкость: **{rarity}**\n"
                                f"💰 Порог срабатывания: `{threshold:,.0f} руб.`\n"
                                f"🔥 **Текущая цена на аукционе:** `{current_price:,.0f} руб.`\n\n"
                                f"Срочно заходите в игру для выкупа!"
                            )
                            await send_telegram_notification(user_id, msg)

            await asyncio.sleep(5)

        except Exception as e:
            logger.error(f"⚠️ Ошибка воркера снайперов: {e}")
            await asyncio.sleep(5)


# --- Главная точка входа ---

async def main():
    tracked_items = load_tracked_items()
    logger.info(f"📦 Инициализировано отслеживаемых предметов: {len(tracked_items)}")

    sync_all_items_to_supabase(tracked_items)

    await asyncio.gather(
        general_collector_worker(tracked_items),
        sniper_monitoring_worker(),
        return_exceptions=True
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Коллектор остановлен пользователем.")
