import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from supabase import create_client

# 1. Инициализация Supabase
# ВАЖНО: значений по умолчанию больше нет — старые ключи были скомпрометированы
# (лежали в открытом коде), их нужно РОТИРОВАТЬ в Supabase/Telegram и задать заново
# только через переменные окружения Railway.
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "SUPABASE_URL и SUPABASE_KEY должны быть заданы через переменные окружения "
        "(Railway → Variables). Хардкод секретов в коде убран из соображений безопасности."
    )

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# 2. Глобальное объявление приложения (СТРОГО на верхнем уровне файла!)
app = FastAPI(title="Stalzone Auction API")

DEFAULT_LICENSE_DAYS = int(os.getenv("DEFAULT_LICENSE_DAYS", "30"))


# --- Схемы данных ---

class SniperCreate(BaseModel):
    user_id: int
    license_key: Optional[str] = None
    item_id: str
    item_name: str
    rarity: str
    threshold: float

class SniperUpdate(BaseModel):
    threshold: float

class LicenseGenerate(BaseModel):
    telegram_id: int
    days: Optional[int] = None


# --- Проверка и привязка лицензии ---
#
# ВАЖНО: раньше здесь был универсальный ключ "STALZONE-STARS-KEY-DEMO", который
# всегда считался валидным для ЛЮБОГО пользователя и никогда не истекал — по сути,
# бесплатный доступ для всех, кто его узнал. Он убран. Каждый ключ теперь уникален
# и выдаётся через /licenses/generate (см. ниже).

def verify_license_key(license_key: str, telegram_id: Optional[int] = None) -> str:
    """
    Возвращает:
      "ok"          - ключ валиден (и привязан к telegram_id, если он передан)
      "invalid"     - ключ не найден, деактивирован или просрочен
      "bound_other" - ключ уже привязан к другому Telegram-аккаунту
    """
    if not license_key:
        return "invalid"
    clean_key = license_key.strip()

    try:
        res = (
            supabase.table("licenses")
            .select("id, is_active, expires_at, telegram_id")
            .eq("key", clean_key)
            .execute()
        )
    except Exception as e:
        print(f"⚠️ Ошибка проверки ключа: {e}")
        return "invalid"

    if not res.data:
        return "invalid"

    row = res.data[0]
    if not row.get("is_active"):
        return "invalid"

    expires_at_str = row.get("expires_at")
    if expires_at_str:
        expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expires_at:
            return "invalid"

    if telegram_id is None:
        # Привязка не требуется для этого вызова — достаточно, что ключ валиден.
        return "ok"

    bound_id = row.get("telegram_id")

    if bound_id is None:
        # Ключ ещё никому не принадлежит — привязываем к текущему аккаунту при первом входе.
        try:
            supabase.table("licenses").update({"telegram_id": telegram_id}).eq("id", row["id"]).execute()
        except Exception as e:
            print(f"⚠️ Ошибка привязки ключа к telegram_id={telegram_id}: {e}")
            return "invalid"
        return "ok"

    if int(bound_id) != int(telegram_id):
        return "bound_other"

    return "ok"


def _require_license(license_key: str, telegram_id: Optional[int] = None):
    """Поднимает корректную HTTPException в зависимости от результата проверки."""
    status = verify_license_key(license_key, telegram_id)
    if status == "bound_other":
        raise HTTPException(status_code=409, detail="Этот ключ уже привязан к другому Telegram-аккаунту.")
    if status != "ok":
        raise HTTPException(status_code=403, detail="Неверный или просроченный ключ.")


def _fetch_all_rows(table: str, columns: str, page_size: int = 1000) -> list:
    """
    Пагинированная выгрузка ВСЕХ строк таблицы (а не только первых ~10000),
    чтобы каталог не обрезался молча при росте базы.
    """
    rows: list = []
    start = 0
    while True:
        res = supabase.table(table).select(columns).range(start, start + page_size - 1).execute()
        chunk = res.data or []
        rows.extend(chunk)
        if len(chunk) < page_size:
            break
        start += page_size
    return rows


# --- Корневой роут для проверки работоспособности Railway ---

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Stalzone Auction API Running"}


# --- Выдача лицензий (вызывается ботом после подтверждённой оплаты) ---

@app.post("/licenses/generate")
@app.post("/api/v1/licenses/generate")
def generate_license(data: LicenseGenerate):
    """
    Создаёт новый уникальный ключ, сразу привязанный к telegram_id покупателя.
    Заменяет прежний общий демо-ключ, который был доступен всем бесплатно.
    """
    days = data.days or DEFAULT_LICENSE_DAYS
    new_key = f"STZ-{secrets.token_hex(8).upper()}"
    expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

    payload = {
        "key": new_key,
        "is_active": True,
        "expires_at": expires_at,
        "telegram_id": data.telegram_id,
    }
    try:
        supabase.table("licenses").insert(payload).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка создания ключа: {e}")

    return {"status": "success", "key": new_key, "expires_at": expires_at}


# --- Эндпоинты для товаров и цен ---

@app.get("/items/{license_key}")
@app.get("/api/v1/items/{license_key}")
@app.get("/api/login/items/{license_key}")
def get_items_by_key(license_key: str, telegram_id: Optional[int] = None, limit: Optional[int] = 10000):
    _require_license(license_key, telegram_id)

    try:
        res_items = _fetch_all_rows("items", "*")
        if res_items:
            return {"status": "success", "data": res_items}
    except Exception as e:
        print(f"⚠️ Ошибка обращения к таблице items: {e}")

    try:
        rows = _fetch_all_rows("price_history", "item_id, item_name, rarity, category")
        unique_items = {}
        for row in rows:
            i_id = row.get("item_id")
            rarity = row.get("rarity") or "Обычный"
            if rarity == "None":
                rarity = "Обычный"

            composite_key = f"{i_id}_{rarity}"

            if i_id and composite_key not in unique_items:
                unique_items[composite_key] = {
                    "item_id": i_id,
                    "id": i_id,
                    "name": row.get("item_name") or i_id,
                    "rarity": rarity,
                    "category": row.get("category") or "Разное"
                }

        return {"status": "success", "data": list(unique_items.values())}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки каталога: {e}")


@app.get("/items/{item_id}/price")
@app.get("/api/v1/items/{item_id}/price")
def get_item_price(item_id: str, rarity: str = "Обычный", license_key: Optional[str] = None):
    try:
        res = (
            supabase.table("price_history")
            .select("min_buyout_price, item_name")
            .eq("item_id", item_id.strip())
            .eq("rarity", rarity.strip())
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if res.data and len(res.data) > 0:
            return {
                "min_price": res.data[0].get("min_buyout_price"),
                "item_name": res.data[0].get("item_name") or item_id
            }
    except Exception as e:
        print(f"⚠️ Ошибка получения цены: {e}")

    return {"min_price": None, "item_name": item_id}


@app.get("/history/{license_key}/{item_id}")
@app.get("/api/v1/history/{license_key}/{item_id}")
@app.get("/api/login/history/{license_key}/{item_id}")
def get_history_by_key(license_key: str, item_id: str):
    if not verify_license_key(license_key):
        raise HTTPException(status_code=403, detail="Неверный или просроченный ключ.")

    history = supabase.table("price_history") \
        .select("*") \
        .eq("item_id", item_id.strip()) \
        .order("created_at", desc=True) \
        .limit(10) \
        .execute()
    return {"status": "success", "data": history.data}


# --- Эндпоинты для работы со снайперами ---

@app.post("/snipers")
@app.post("/api/v1/snipers")
@app.post("/api/login/snipers")
def create_sniper(data: SniperCreate):
    payload = {
        "user_id": data.user_id,
        "license_key": data.license_key,
        "item_id": data.item_id,
        "item_name": data.item_name,
        "rarity": data.rarity,
        "threshold": data.threshold
    }
    try:
        res = supabase.table("user_snipers").insert(payload).execute()
        return {"status": "success", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения снайпера: {e}")


@app.get("/snipers/{user_id}")
@app.get("/api/v1/snipers/{user_id}")
@app.get("/api/login/snipers/{user_id}")
def get_snipers(user_id: int):
    try:
        res = supabase.table("user_snipers").select("*").eq("user_id", user_id).execute()
        return {"status": "success", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/snipers/{sniper_id}")
@app.patch("/api/v1/snipers/{sniper_id}")
@app.patch("/api/login/snipers/{sniper_id}")
def update_sniper_threshold(sniper_id: str, data: SniperUpdate):
    try:
        res = supabase.table("user_snipers").update({"threshold": data.threshold}).eq("id", sniper_id).execute()
        return {"status": "success", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/snipers/single/{sniper_id}")
@app.delete("/api/v1/snipers/single/{sniper_id}")
@app.delete("/api/login/snipers/single/{sniper_id}")
def delete_single_sniper(sniper_id: str):
    try:
        res = supabase.table("user_snipers").delete().eq("id", sniper_id).execute()
        return {"status": "success", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/snipers/{user_id}")
@app.delete("/api/v1/snipers/{user_id}")
@app.delete("/api/login/snipers/{user_id}")
def delete_all_user_snipers(user_id: int):
    try:
        res = supabase.table("user_snipers").delete().eq("user_id", user_id).execute()
        return {"status": "success", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
