from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from supabase import create_client

SUPABASE_URL = "https://mdursbqpogprwzbhjzxz.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1kdXJzYnFwb2dwcnd6Ymhqenh6Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NzE0MzU5NCwiZXhwIjoyMTAyNzE5NTk0fQ.AXb2IUi3VOY1hNHxrvZUpsk4f6ycGDc2qaC_4zzM1Mo"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
app = FastAPI(title="Stalzone Auction API")


def verify_license_key(license_key: str) -> bool:
  """Упрощенная проверка ключа для отладки."""
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


@app.get("/api/v1/items/{license_key}")
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
    if i_id and i_id not in unique_items:
      rarity = row.get("rarity")
      if not rarity or rarity == "None":
        rarity = "Обычный"

      unique_items[i_id] = {
          "item_id": i_id,
          "name": row.get("item_name") or i_id,
          "rarity": rarity,
          "category": row.get("category") or "Разное",
      }

  return {"status": "success", "data": list(unique_items.values())}


@app.get("/api/v1/history/{license_key}/{item_id}")
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