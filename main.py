from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from supabase import create_client

SUPABASE_URL = "https://mdursbqpogprwzbhjzxz.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1kdXJzYnFwb2dwcnd6Ymhqenh6Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NzE0MzU5NCwiZXhwIjoyMTAyNzE5NTk0fQ.AXb2IUi3VOY1hNHxrvZUpsk4f6ycGDc2qaC_4zzM1Mo"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
app = FastAPI(title="Stalzone Auction API")


class SniperCreate(BaseModel):
  user_id: int
  license_key: Optional[str] = None
  item_id: str
  item_name: str
  rarity: str
  threshold: float


def verify_license_key(license_key: str) -> bool:
  if not license_key:
    return False
  clean_key = license_key.strip()
  try:
    res = (
        supabase.table("licenses")
        .select("is_active")
        .eq("key", clean_key)
        .execute()
    )
    print(f"DEBUG: Проверка ключа '{clean_key}' -> Результат БД: {res.data}")
    if res.data and res.data[0].get("is_active") is True:
      return True
    return False
  except Exception as e:
    print(f"DEBUG EXCEPTION: {e}")
    return False


# --- Эндпоинты для товаров и истории ---


@app.get("/api/v1/items/{license_key}")
@app.get("/api/login/items/{license_key}")
def get_items_by_key(license_key: str):
  if not verify_license_key(license_key):
    raise HTTPException(
        status_code=403, detail="Неверный или просроченный ключ."
    )

  items = (
      supabase.table("price_history")
      .select("item_id, item_name, rarity, category")
      .execute()
  )

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
          "name": row.get("item_name") or i_id,
          "rarity": rarity,
          "category": row.get("category") or "Разное",
      }

  return {"status": "success", "data": list(unique_items.values())}


@app.get("/api/v1/history/{license_key}/{item_id}")
@app.get("/api/login/history/{license_key}/{item_id}")
def get_history_by_key(license_key: str, item_id: str):
  if not verify_license_key(license_key):
    raise HTTPException(
        status_code=403, detail="Неверный или просроченный ключ."
    )

  history = (
      supabase.table("price_history")
      .select("*")
      .eq("item_id", item_id.strip())
      .order("created_at", desc=True)
      .limit(10)
      .execute()
  )
  return {"status": "success", "data": history.data}


# --- Эндпоинты для работы со снайперами ---


@app.post("/api/v1/snipers")
@app.post("/api/login/snipers")
def create_sniper(data: SniperCreate):
  payload = {
      "user_id": data.user_id,  # int8 в PostgreSQL
      "license_key": data.license_key,
      "item_id": data.item_id,
      "item_name": data.item_name,
      "rarity": data.rarity,
      "threshold": data.threshold,
  }

  try:
    res = supabase.table("user_snipers").insert(payload).execute()
    return {"status": "success", "data": res.data}
  except Exception as e:
    print(f"DEBUG SNIPER ERROR: {e}")
    raise HTTPException(
        status_code=500, detail=f"Ошибка сохранения в user_snipers: {e}"
    )


@app.get("/api/v1/snipers/{user_id}")
@app.get("/api/login/snipers/{user_id}")
def get_snipers(user_id: int):
  try:
    res = (
        supabase.table("user_snipers")
        .select("*")
        .eq("user_id", user_id)
        .execute()
    )
    return {"status": "success", "data": res.data}
  except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/v1/snipers/{user_id}")
@app.delete("/api/login/snipers/{user_id}")
def delete_snipers(user_id: int):
  try:
    res = supabase.table("user_snipers").delete().eq("user_id", user_id).execute()
    return {"status": "success", "data": res.data}
  except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))
