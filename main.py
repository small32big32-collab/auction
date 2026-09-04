import os
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from supabase import create_client

# Настройки Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://mdursbqpogprwzbhjzxz.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1kdXJzYnFwb2dwcnd6Ymhqenh6Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NzE0MzU5NCwiZXhwIjoyMTAyNzE5NTk0fQ.AXb2IUi3VOY1hNHxrvZUpsk4f6ycGDc2qaC_4zzM1Mo")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
app = FastAPI(title="Stalzone Auction API")


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


# --- Функция проверки лицензии ---

def verify_license_key(license_key: str) -> bool:
    """Проверяет активность ключа и срок его действия с учётом таблицы licenses."""
    if not license_key:
        return False
    clean_key = license_key.strip()
    
    # Резервный/демо ключ для тестов
    if clean_key == "STALZONE-STARS-KEY-DEMO":
        return True
        
    try:
        res = (
            supabase.table("licenses")
            .select("is_active, expires_at")
            .eq("key", clean_key)
            .execute()
        )
        
        if res.data and len(res.data) > 0:
            row = res.data[0]
            
            # 1. Проверка флага активности
            if not row.get("is_active"):
                return False
            
            # 2. Проверка срока действия (expires_at)
            expires_at_str = row.get("expires_at")
            if expires_at_str:
                # Конвертируем строку с таймзоной в объект datetime и сравниваем с текущим временем
                expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) > expires_at:
                    return False
                    
            return True
            
        return False
    except Exception as e:
        print(f"⚠️ Ошибка проверки ключа: {e}")
        return False


# --- Эндпоинты для товаров и цен ---

@app.get("/items/{license_key}")
@app.get("/api/v1/items/{license_key}")
@app.get("/api/login/items/{license_key}")
def get_items_by_key(license_key: str, telegram_id: Optional[int] = None, limit: Optional[int] = 10000):
    if not verify_license_key(license_key):
        raise HTTPException(status_code=403, detail="Неверный или просроченный ключ.")

    # 1. Попытка загрузить из основной таблицы предметов с снятием лимита 1000 строк
    try:
        res_items = supabase.table("items").select("*").range(0, 9999).execute()
        if res_items.data and len(res_items.data) > 0:
            return {"status": "success", "data": res_items.data}
    except Exception as e:
        print(f"⚠️ Ошибка обращения к таблице items: {e}")

    # 2. Резервный сбор уникальных артефактов из истории цен (до 10000 записей)
    try:
        items = supabase.table("price_history").select("item_id, item_name, rarity, category").range(0, 9999).execute()
        unique_items = {}
        for row in items.data:
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
