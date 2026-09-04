import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field
from supabase import create_client


# ============================================================
# НАСТРОЙКИ
# ============================================================

# Ключи можно оставить в файле, как ты просил.
# Если переменная окружения существует — используется она.
SUPABASE_URL = os.getenv(
    "SUPABASE_URL",
    "https://mdursbqpogprwzbhjzxz.supabase.co"
)

SUPABASE_KEY = os.getenv(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1kdXJzYnFwb2dwcnd6Ymhqenh6Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NzE0MzU5NCwiZXhwIjoyMTAyNzE5NTk0fQ.AXb2IUi3VOY1hNHxrvZUpsk4f6ycGDc2qaC_4zzM1Mo"
)

# Внутренний ключ для запросов бота к административному
# endpoint генерации лицензии.
#
# Придумай свою строку и поставь одинаковую:
# 1) здесь
# 2) в bot.py
INTERNAL_API_KEY = os.getenv(
    "INTERNAL_API_KEY",
    "GOIDA_ZAPRET"
)

DEFAULT_LICENSE_DAYS = int(
    os.getenv("DEFAULT_LICENSE_DAYS", "30")
)


# ============================================================
# SUPABASE
# ============================================================

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "Не настроены SUPABASE_URL / SUPABASE_KEY"
    )

if SUPABASE_KEY == "ВСТАВЬ_СЮДА_СВОЙ_SUPABASE_KEY":
    print(
        "⚠️ ВНИМАНИЕ: SUPABASE_KEY ещё не вставлен в main.py"
    )

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="Stalzone Auction API",
    version="2.0"
)


# ============================================================
# МОДЕЛИ
# ============================================================

class SniperCreate(BaseModel):
    user_id: int
    license_key: str
    item_id: str
    item_name: str
    rarity: str = "Обычный"
    threshold: float = Field(gt=0)


class SniperUpdate(BaseModel):
    threshold: float = Field(gt=0)


class LicenseGenerate(BaseModel):
    telegram_id: int
    days: Optional[int] = None


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def clean_license_key(value: Optional[str]) -> str:
    if not value:
        return ""

    return value.strip()


def clean_item_id(value: str) -> str:
    return str(value).strip()


def clean_rarity(value: Optional[str]) -> str:
    if not value:
        return "Обычный"

    value = value.strip()

    if not value or value == "None":
        return "Обычный"

    return value


def verify_license_key(
    license_key: str,
    telegram_id: Optional[int] = None
) -> str:
    """
    Возвращает:

    ok
        Ключ существует, активен и не просрочен.

    invalid
        Ключ не найден, выключен или просрочен.

    bound_other
        Ключ привязан к другому Telegram ID.
    """

    license_key = clean_license_key(license_key)

    if not license_key:
        return "invalid"

    try:
        response = (
            supabase
            .table("licenses")
            .select(
                "id, key, is_active, expires_at, telegram_id"
            )
            .eq("key", license_key)
            .limit(1)
            .execute()
        )

    except Exception as e:
        print(
            f"⚠️ Ошибка проверки лицензии: {e}"
        )
        return "invalid"

    if not response.data:
        return "invalid"

    license_row = response.data[0]

    # --------------------------------------------------------
    # Активность
    # --------------------------------------------------------

    if not license_row.get("is_active"):
        return "invalid"

    # --------------------------------------------------------
    # Срок действия
    # --------------------------------------------------------

    expires_at_str = license_row.get("expires_at")

    if expires_at_str:

        try:
            expires_at = datetime.fromisoformat(
                str(expires_at_str).replace(
                    "Z",
                    "+00:00"
                )
            )

            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(
                    tzinfo=timezone.utc
                )

            if datetime.now(timezone.utc) >= expires_at:

                # Автоматически выключаем просроченную лицензию.
                try:
                    (
                        supabase
                        .table("licenses")
                        .update({"is_active": False})
                        .eq("id", license_row["id"])
                        .execute()
                    )
                except Exception:
                    pass

                return "invalid"

        except Exception as e:
            print(
                f"⚠️ Ошибка разбора expires_at: {e}"
            )

            return "invalid"

    # --------------------------------------------------------
    # Проверка Telegram ID
    # --------------------------------------------------------

    if telegram_id is None:
        return "ok"

    bound_id = license_row.get("telegram_id")

    # Ключ ещё не привязан.
    if bound_id is None:

        try:
            (
                supabase
                .table("licenses")
                .update({
                    "telegram_id": telegram_id
                })
                .eq("id", license_row["id"])
                .execute()
            )

            return "ok"

        except Exception as e:

            print(
                f"⚠️ Ошибка привязки лицензии: {e}"
            )

            return "invalid"

    # Ключ уже привязан.
    try:
        if int(bound_id) != int(telegram_id):
            return "bound_other"
    except (TypeError, ValueError):
        return "invalid"

    return "ok"


def require_license(
    license_key: str,
    telegram_id: Optional[int] = None
):
    """
    Проверяет лицензию и выбрасывает HTTP ошибку,
    если доступ запрещён.
    """

    status = verify_license_key(
        license_key,
        telegram_id
    )

    if status == "bound_other":
        raise HTTPException(
            status_code=409,
            detail=(
                "Этот ключ уже привязан "
                "к другому Telegram-аккаунту."
            )
        )

    if status != "ok":
        raise HTTPException(
            status_code=403,
            detail="Неверный или просроченный ключ."
        )


def require_internal_api_key(
    x_internal_api_key: Optional[str]
):
    """
    Защита внутренних административных запросов.
    """

    if not INTERNAL_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="INTERNAL_API_KEY не настроен."
        )

    if (
        not x_internal_api_key
        or not secrets.compare_digest(
            x_internal_api_key,
            INTERNAL_API_KEY
        )
    ):
        raise HTTPException(
            status_code=401,
            detail="Недействительный внутренний API ключ."
        )


def fetch_all_rows(
    table: str,
    columns: str = "*",
    page_size: int = 1000
) -> list:

    rows = []
    start = 0

    while True:

        response = (
            supabase
            .table(table)
            .select(columns)
            .range(
                start,
                start + page_size - 1
            )
            .execute()
        )

        chunk = response.data or []

        rows.extend(chunk)

        if len(chunk) < page_size:
            break

        start += page_size

    return rows


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def read_root():

    return {
        "status": "ok",
        "message": "Stalzone Auction API Running",
        "version": "2.0"
    }


@app.get("/health")
@app.get("/api/health")
def health():

    return {
        "status": "ok"
    }


# ============================================================
# ЛИЦЕНЗИИ
# ============================================================

@app.post("/licenses/generate")
@app.post("/api/v1/licenses/generate")
def generate_license(
    data: LicenseGenerate,
    x_internal_api_key: Optional[str] = Header(
        default=None
    )
):
    """
    Создание лицензии.

    ВАЖНО:
    endpoint защищён INTERNAL_API_KEY.

    Его должен использовать bot.py после успешной оплаты.
    """

    require_internal_api_key(
        x_internal_api_key
    )

    if data.telegram_id <= 0:
        raise HTTPException(
            status_code=400,
            detail="Некорректный telegram_id."
        )

    days = (
        data.days
        if data.days is not None
        else DEFAULT_LICENSE_DAYS
    )

    if days <= 0 or days > 3650:
        raise HTTPException(
            status_code=400,
            detail="Количество дней должно быть от 1 до 3650."
        )

    # --------------------------------------------------------
    # Генерируем уникальный ключ.
    # --------------------------------------------------------

    for _ in range(10):

        new_key = (
            "STZ-"
            + secrets.token_hex(8).upper()
        )

        try:

            existing = (
                supabase
                .table("licenses")
                .select("id")
                .eq("key", new_key)
                .limit(1)
                .execute()
            )

            if not existing.data:
                break

        except Exception as e:

            raise HTTPException(
                status_code=500,
                detail=(
                    f"Ошибка проверки уникальности ключа: {e}"
                )
            )

    else:

        raise HTTPException(
            status_code=500,
            detail="Не удалось создать уникальный ключ."
        )

    expires_at = (
        datetime.now(timezone.utc)
        + timedelta(days=days)
    ).isoformat()

    payload = {
        "key": new_key,
        "is_active": True,
        "expires_at": expires_at,
        "telegram_id": data.telegram_id
    }

    try:

        response = (
            supabase
            .table("licenses")
            .insert(payload)
            .execute()
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Ошибка создания лицензии: {e}"
        )

    return {
        "status": "success",
        "key": new_key,
        "expires_at": expires_at,
        "data": response.data
    }


# ============================================================
# КАТАЛОГ
# ============================================================

@app.get("/items/{license_key}")
@app.get("/api/v1/items/{license_key}")
@app.get("/api/login/items/{license_key}")
def get_items_by_key(
    license_key: str,
    telegram_id: Optional[int] = None,
    limit: Optional[int] = 10000
):

    require_license(
        license_key,
        telegram_id
    )

    if limit is None:
        limit = 10000

    limit = max(
        1,
        min(limit, 10000)
    )

    # --------------------------------------------------------
    # Сначала нормальная таблица items.
    # --------------------------------------------------------

    try:

        rows = fetch_all_rows(
            "items",
            "*"
        )

        if rows:

            return {
                "status": "success",
                "data": rows[:limit]
            }

    except Exception as e:

        print(
            f"⚠️ Ошибка загрузки items: {e}"
        )

    # --------------------------------------------------------
    # Запасной вариант — price_history.
    # --------------------------------------------------------

    try:

        history_rows = fetch_all_rows(
            "price_history",
            "item_id, item_name, rarity, category"
        )

        unique_items = {}

        for row in history_rows:

            item_id = row.get("item_id")

            if not item_id:
                continue

            rarity = clean_rarity(
                row.get("rarity")
            )

            composite_key = (
                f"{item_id}_{rarity}"
            )

            if composite_key not in unique_items:

                unique_items[composite_key] = {
                    "item_id": item_id,
                    "id": item_id,
                    "name": (
                        row.get("item_name")
                        or item_id
                    ),
                    "rarity": rarity,
                    "category": (
                        row.get("category")
                        or "Разное"
                    )
                }

        return {
            "status": "success",
            "data": list(
                unique_items.values()
            )[:limit]
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Ошибка загрузки каталога: {e}"
        )


# ============================================================
# ЦЕНА ПРЕДМЕТА
# ============================================================

@app.get("/items/{item_id}/price")
@app.get("/api/v1/items/{item_id}/price")
def get_item_price(
    item_id: str,
    rarity: str = "Обычный",
    license_key: Optional[str] = None,
    telegram_id: Optional[int] = None
):
    """
    Получение последней сохранённой цены.

    Теперь лицензия обязательна.
    """

    if not license_key:
        raise HTTPException(
            status_code=401,
            detail="Необходимо передать license_key."
        )

    require_license(
        license_key,
        telegram_id
    )

    item_id = clean_item_id(
        item_id
    )

    rarity = clean_rarity(
        rarity
    )

    if not item_id:
        raise HTTPException(
            status_code=400,
            detail="item_id не может быть пустым."
        )

    try:

        response = (
            supabase
            .table("price_history")
            .select(
                "min_buyout_price, item_name, rarity, created_at"
            )
            .eq("item_id", item_id)
            .eq("rarity", rarity)
            .order(
                "created_at",
                desc=True
            )
            .limit(1)
            .execute()
        )

        if response.data:

            row = response.data[0]

            return {
                "status": "success",
                "min_price": row.get(
                    "min_buyout_price"
                ),
                "item_name": (
                    row.get("item_name")
                    or item_id
                ),
                "rarity": (
                    row.get("rarity")
                    or rarity
                ),
                "created_at": row.get(
                    "created_at"
                )
            }

    except Exception as e:

        print(
            f"⚠️ Ошибка получения цены: {e}"
        )

    return {
        "status": "success",
        "min_price": None,
        "item_name": item_id,
        "rarity": rarity
    }


# ============================================================
# ИСТОРИЯ
# ============================================================

@app.get("/history/{license_key}/{item_id}")
@app.get("/api/v1/history/{license_key}/{item_id}")
@app.get("/api/login/history/{license_key}/{item_id}")
def get_history_by_key(
    license_key: str,
    item_id: str,
    telegram_id: Optional[int] = None,
    limit: int = 10
):

    require_license(
        license_key,
        telegram_id
    )

    item_id = clean_item_id(
        item_id
    )

    limit = max(
        1,
        min(limit, 100)
    )

    try:

        response = (
            supabase
            .table("price_history")
            .select("*")
            .eq("item_id", item_id)
            .order(
                "created_at",
                desc=True
            )
            .limit(limit)
            .execute()
        )

        return {
            "status": "success",
            "data": response.data or []
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Ошибка получения истории: {e}"
        )


# ============================================================
# СНАЙПЕРЫ
# ============================================================

@app.post("/snipers")
@app.post("/api/v1/snipers")
@app.post("/api/login/snipers")
def create_sniper(
    data: SniperCreate,
    telegram_id: Optional[int] = None
):
    """
    Создаёт снайпер только для владельца лицензии.
    """

    require_license(
        data.license_key,
        telegram_id
    )

    if data.user_id <= 0:
        raise HTTPException(
            status_code=400,
            detail="Некорректный user_id."
        )

    item_id = clean_item_id(
        data.item_id
    )

    item_name = data.item_name.strip()

    rarity = clean_rarity(
        data.rarity
    )

    if not item_id:
        raise HTTPException(
            status_code=400,
            detail="item_id не может быть пустым."
        )

    if not item_name:
        item_name = item_id

    payload = {
        "user_id": data.user_id,
        "license_key": clean_license_key(
            data.license_key
        ),
        "item_id": item_id,
        "item_name": item_name,
        "rarity": rarity,
        "threshold": float(
            data.threshold
        )
    }

    try:

        response = (
            supabase
            .table("user_snipers")
            .insert(payload)
            .execute()
        )

        return {
            "status": "success",
            "data": response.data
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=(
                f"Ошибка сохранения снайпера: {e}"
            )
        )


# ============================================================
# ПОЛУЧЕНИЕ СНАЙПЕРОВ ПОЛЬЗОВАТЕЛЯ
# ============================================================

@app.get("/snipers/{user_id}")
@app.get("/api/v1/snipers/{user_id}")
@app.get("/api/login/snipers/{user_id}")
def get_snipers(
    user_id: int,
    license_key: Optional[str] = None,
    telegram_id: Optional[int] = None
):

    if not license_key:
        raise HTTPException(
            status_code=401,
            detail="Необходимо передать license_key."
        )

    require_license(
        license_key,
        telegram_id
    )

    try:

        response = (
            supabase
            .table("user_snipers")
            .select("*")
            .eq("user_id", user_id)
            .eq(
                "license_key",
                clean_license_key(
                    license_key
                )
            )
            .execute()
        )

        return {
            "status": "success",
            "data": response.data or []
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Ошибка получения снайперов: {e}"
        )


# ============================================================
# ОБНОВЛЕНИЕ СНАЙПЕРА
# ============================================================

@app.patch("/snipers/{sniper_id}")
@app.patch("/api/v1/snipers/{sniper_id}")
@app.patch("/api/login/snipers/{sniper_id}")
def update_sniper_threshold(
    sniper_id: str,
    data: SniperUpdate,
    license_key: Optional[str] = None,
    telegram_id: Optional[int] = None
):

    if not license_key:
        raise HTTPException(
            status_code=401,
            detail="Необходимо передать license_key."
        )

    require_license(
        license_key,
        telegram_id
    )

    license_key = clean_license_key(
        license_key
    )

    # Сначала убеждаемся, что снайпер принадлежит
    # именно этому ключу.
    try:

        existing = (
            supabase
            .table("user_snipers")
            .select("*")
            .eq("id", sniper_id)
            .eq(
                "license_key",
                license_key
            )
            .limit(1)
            .execute()
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Ошибка поиска снайпера: {e}"
        )

    if not existing.data:

        raise HTTPException(
            status_code=404,
            detail="Снайпер не найден."
        )

    try:

        response = (
            supabase
            .table("user_snipers")
            .update({
                "threshold": float(
                    data.threshold
                )
            })
            .eq("id", sniper_id)
            .eq(
                "license_key",
                license_key
            )
            .execute()
        )

        return {
            "status": "success",
            "data": response.data
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=(
                f"Ошибка обновления снайпера: {e}"
            )
        )


# ============================================================
# УДАЛЕНИЕ ОДНОГО СНАЙПЕРА
# ============================================================

@app.delete("/snipers/single/{sniper_id}")
@app.delete("/api/v1/snipers/single/{sniper_id}")
@app.delete("/api/login/snipers/single/{sniper_id}")
def delete_single_sniper(
    sniper_id: str,
    license_key: Optional[str] = None,
    telegram_id: Optional[int] = None
):

    if not license_key:
        raise HTTPException(
            status_code=401,
            detail="Необходимо передать license_key."
        )

    require_license(
        license_key,
        telegram_id
    )

    license_key = clean_license_key(
        license_key
    )

    try:

        existing = (
            supabase
            .table("user_snipers")
            .select("id")
            .eq("id", sniper_id)
            .eq(
                "license_key",
                license_key
            )
            .limit(1)
            .execute()
        )

        if not existing.data:

            raise HTTPException(
                status_code=404,
                detail="Снайпер не найден."
            )

        response = (
            supabase
            .table("user_snipers")
            .delete()
            .eq("id", sniper_id)
            .eq(
                "license_key",
                license_key
            )
            .execute()
        )

        return {
            "status": "success",
            "data": response.data
        }

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=(
                f"Ошибка удаления снайпера: {e}"
            )
        )


# ============================================================
# УДАЛЕНИЕ ВСЕХ СНАЙПЕРОВ ПОЛЬЗОВАТЕЛЯ
# ============================================================

@app.delete("/snipers/{user_id}")
@app.delete("/api/v1/snipers/{user_id}")
@app.delete("/api/login/snipers/{user_id}")
def delete_all_user_snipers(
    user_id: int,
    license_key: Optional[str] = None,
    telegram_id: Optional[int] = None
):

    if not license_key:
        raise HTTPException(
            status_code=401,
            detail="Необходимо передать license_key."
        )

    require_license(
        license_key,
        telegram_id
    )

    license_key = clean_license_key(
        license_key
    )

    try:

        response = (
            supabase
            .table("user_snipers")
            .delete()
            .eq("user_id", user_id)
            .eq(
                "license_key",
                license_key
            )
            .execute()
        )

        return {
            "status": "success",
            "data": response.data
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=(
                f"Ошибка удаления снайперов: {e}"
            )
        )


# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
