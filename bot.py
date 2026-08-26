import os
import asyncio
import uuid
import httpx
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import LabeledPrice
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Используем переменные окружения, с запасными значениями для локального запуска
BOT_TOKEN = os.getenv("BOT_TOKEN", "8877726623:AAEV6YFhuuBnzKWiJZxwiWM49khiaxazwRE")
API_BASE_URL = os.getenv("API_BASE_URL", "https://server-auth-7cw9.onrender.com/api/login")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

CATEGORY_NAMES = {
    "artifacts": "Артефакты",
    "armor": "Броня",
}


class UserSession(StatesGroup):
  waiting_for_key = State()
  in_menu = State()
  waiting_invoice = State()
  waiting_for_sniper_threshold = State()  # Ожидание ввода целевой цены для снайпера


# Хранилище активных снайперов: { user_id: {"key": str, "item_id": str, "item_name": str, "rarity": str, "threshold": float} }
active_snipers = {}


# Главное меню (с учетом авторизации)
async def show_main_menu(message_or_callback, edit=False, has_key=False):
  builder = InlineKeyboardBuilder()
  
  if has_key:
    builder.button(text="📂 Каталог предметов", callback_data="back_to_cats")
    builder.button(text="🎯 Настроить снайпер цен", callback_data="sniper_menu")
    builder.button(text="🔑 Сменить ключ", callback_data="start_enter_key")
  else:
    builder.button(text="💳 Купить доступ (Platega)", callback_data="buy_platega")
    builder.button(text="⭐ Купить за Звезды", callback_data="buy_stars")
    builder.button(text="🔑 Ввести ключ", callback_data="start_enter_key")
    builder.button(text="📄 Пользовательское соглашение", url="https://telegra.ph/Polzovatelskoe-soglashenie-08-25-64")
    builder.button(text="🔒 Политика конфиденциальности", url="https://telegra.ph/Politika-konfidencialnosti-08-25-84")
  
  builder.adjust(1)

  text = (
      "👋 **Stalzone Auction Bot**\n\n"
      "Добро пожаловать! Выберите нужный пункт меню:"
  )
  
  if edit:
    await message_or_callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
  else:
    await message_or_callback.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
  data = await state.get_data()
  invoice_msg_id = data.get("invoice_msg_id")
  if invoice_msg_id:
    try:
      await bot.delete_message(chat_id=message.chat.id, message_id=invoice_msg_id)
    except Exception:
      pass

  await state.clear()
  await show_main_menu(message, edit=False, has_key=False)


@dp.message(Command("key"))
async def cmd_key(message: types.Message, state: FSMContext):
  data = await state.get_data()
  invoice_msg_id = data.get("invoice_msg_id")
  if invoice_msg_id:
    try:
      await bot.delete_message(chat_id=message.chat.id, message_id=invoice_msg_id)
    except Exception:
      pass

  await state.clear()
  builder = InlineKeyboardBuilder()
  builder.button(text="⬅️ Назад в меню", callback_data="back_to_main")
  builder.adjust(1)
  
  await message.answer("🔑 Введите ваш лицензионный ключ:", reply_markup=builder.as_markup())
  await state.set_state(UserSession.waiting_for_key)


@dp.callback_query(F.data == "start_enter_key")
async def process_start_enter_key(callback: types.CallbackQuery, state: FSMContext):
  builder = InlineKeyboardBuilder()
  builder.button(text="⬅️ Назад в меню", callback_data="back_to_main")
  builder.adjust(1)
  
  await callback.message.edit_text("🔑 Введите ваш лицензионный ключ:", reply_markup=builder.as_markup())
  await state.set_state(UserSession.waiting_for_key)
  await callback.answer()


@dp.callback_query(F.data == "back_to_main")
async def process_back_to_main(callback: types.CallbackQuery, state: FSMContext):
  data = await state.get_data()
  invoice_msg_id = data.get("invoice_msg_id")
  if invoice_msg_id:
    try:
      await bot.delete_message(chat_id=callback.message.chat.id, message_id=invoice_msg_id)
    except Exception:
      pass

  license_key = data.get("license_key")
  has_key = bool(license_key)

  await state.clear()
  if has_key:
    await state.update_data(license_key=license_key)
    await state.set_state(UserSession.in_menu)

  try:
    await callback.message.delete()
  except Exception:
    pass
  
  await show_main_menu(callback.message, edit=False, has_key=has_key)
  await callback.answer()


# --- ОПЛАТА ЧЕРЕЗ PLATEGA ---
@dp.callback_query(F.data == "buy_platega")
async def process_buy_platega(callback: types.CallbackQuery, state: FSMContext):
  data = await state.get_data()
  invoice_msg_id = data.get("invoice_msg_id")
  if invoice_msg_id:
    try:
      await bot.delete_message(chat_id=callback.message.chat.id, message_id=invoice_msg_id)
    except Exception:
      pass
  await state.clear()

  user_id = callback.from_user.id
  headers = {
      "Authorization": f"Bearer {PLATEGA_API_KEY}",
      "Content-Type": "application/json"
  }
  payload = {
      "amount": 299.00,
      "currency": "RUB",
      "order_id": str(uuid.uuid4()),
      "description": "Подписка Stalzone Auction Bot (30 дней)",
      "telegram_id": user_id
  }

  async with httpx.AsyncClient() as client:
    try:
      res = await client.post(PLATEGA_API_URL, json=payload, headers=headers)
      if res.status_code == 200:
        resp_data = res.json()
        payment_url = resp_data.get("payment_url") or resp_data.get("url")
        
        builder = InlineKeyboardBuilder()
        builder.button(text="🔗 Оплатить", url=payment_url)
        builder.button(text="⬅️ Назад в меню", callback_data="back_to_main")
        builder.adjust(1)
        
        await callback.message.edit_text(
            "💳 Ссылка на оплату успешно создана:",
            reply_markup=builder.as_markup()
        )
      else:
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад в меню", callback_data="back_to_main")
        await callback.message.edit_text("⚠️ Не удалось создать платеж через Platega.", reply_markup=builder.as_markup())
    except Exception as e:
      builder = InlineKeyboardBuilder()
      builder.button(text="⬅️ Назад в меню", callback_data="back_to_main")
      await callback.message.edit_text(f"⚠️ Ошибка связи с платежным шлюзом: {e}", reply_markup=builder.as_markup())
  
  await callback.answer()


# --- ОПЛАТА ЧЕРЕЗ TELEGRAM STARS ---
@dp.callback_query(F.data == "buy_stars")
async def process_buy_stars(callback: types.CallbackQuery, state: FSMContext):
  prices = [LabeledPrice(label="Доступ к Stalzone Auction (30 дней)", amount=150)]
  
  builder = InlineKeyboardBuilder()
  builder.button(text="⬅️ Назад в меню", callback_data="back_to_main")
  builder.adjust(1)

  await callback.message.edit_text(
      "⭐ Счет на оплату через Telegram Stars:", 
      reply_markup=builder.as_markup()
  )
  
  invoice_message = await callback.message.answer_invoice(
      title="Лицензионный ключ Stalzone Auction",
      description="Месячный доступ к закрытой базе данных аукциона.",
      payload="monthly_sub_key",
      currency="XTR",
      prices=prices,
  )
  
  await state.update_data(invoice_msg_id=invoice_message.message_id)
  await callback.answer()


@dp.pre_checkout_query()
async def pre_checkout_query(pre_checkout_query: types.PreCheckoutQuery):
  await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@dp.message(F.successful_payment)
async def on_successful_payment(message: types.Message, state: FSMContext):
  data = await state.get_data()
  invoice_msg_id = data.get("invoice_msg_id")
  if invoice_msg_id:
    try:
      await bot.delete_message(chat_id=message.chat.id, message_id=invoice_msg_id)
    except Exception:
      pass

  new_key = f"STZ-{str(uuid.uuid4())[:8].upper()}"
  
  async with httpx.AsyncClient() as client:
    try:
      await client.post(f"{API_BASE_URL}/register_key", json={"key": new_key, "days": 30})
    except Exception as e:
      print(f"Ошибка сохранения ключа: {e}")

  builder = InlineKeyboardBuilder()
  builder.button(text="⬅️ Назад в меню", callback_data="back_to_main")
  builder.adjust(1)

  text = (
      "🎉 **Оплата через Telegram Stars прошла успешно!**\n\n"
      f"Ваш лицензионный ключ: `{new_key}`\n\n"
      "Скопируйте его и введите командой /key для доступа."
  )
  await message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
  await state.clear()


@dp.message(UserSession.waiting_for_key)
async def process_key_input(message: types.Message, state: FSMContext):
  license_key = message.text.strip()

  url = f"{API_BASE_URL}{license_key}"
  print(f"DEBUG: Отправка запроса проверки ключа на URL: {url}")

  async with httpx.AsyncClient() as client:
    try:
      res = await client.get(url)
      print(f"DEBUG: Ответ сервера — Status: {res.status_code}, Body: {res.text}")

      if res.status_code == 200:
        await state.update_data(license_key=license_key)
        await state.set_state(UserSession.in_menu)
        await message.answer("✅ Ключ принят!")
        await show_main_menu(message, edit=False, has_key=True)
      else:
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад в меню", callback_data="back_to_main")
        await message.answer(
            f"❌ Неверный или просроченный ключ (Код {res.status_code}). Попробуйте еще раз:",
            reply_markup=builder.as_markup()
        )
    except Exception as e:
      print(f"DEBUG EXCEPTION: Ошибка запроса к API: {e}")
      await message.answer(f"⚠️ Ошибка сервера: {e}")


async def show_categories(message_or_callback, license_key: str, edit=False):
  async with httpx.AsyncClient() as client:
    try:
      res = await client.get(f"{API_BASE_URL}/items/{license_key}")
      if res.status_code == 200:
        items = res.json().get("data", [])
        if not items:
          msg = "⚠️ В базе пока нет предметов."
          builder = InlineKeyboardBuilder()
          builder.button(text="⬅️ Назад в меню", callback_data="back_to_main")
          if edit:
            await message_or_callback.message.edit_text(msg, reply_markup=builder.as_markup())
          else:
            await message_or_callback.answer(msg, reply_markup=builder.as_markup())
          return

        raw_categories = list(set(i.get("category", "Разное") for i in items))

        builder = InlineKeyboardBuilder()
        for cat in raw_categories:
          display_name = CATEGORY_NAMES.get(cat, cat)
          builder.button(text=f"📁 {display_name}", callback_data=f"cat_{cat}")
        
        builder.button(text="⬅️ В главное меню", callback_data="back_to_main")
        builder.adjust(1)

        text = "📂 **Выберите категорию:**"
        if edit:
          await message_or_callback.message.edit_text(
              text, reply_markup=builder.as_markup(), parse_mode="Markdown"
          )
        else:
          await message_or_callback.answer(
              text, reply_markup=builder.as_markup(), parse_mode="Markdown"
          )
    except Exception as e:
      print(f"Error: {e}")


@dp.callback_query(F.data == "back_to_cats")
async def process_back_to_cats(callback: types.CallbackQuery, state: FSMContext):
  data = await state.get_data()
  license_key = data.get("license_key")
  if license_key:
    await show_categories(callback, license_key, edit=True)
  await callback.answer()


@dp.callback_query(F.data.startswith("cat_"))
async def process_category_click(callback: types.CallbackQuery, state: FSMContext):
  data = await state.get_data()
  license_key = data.get("license_key")
  if not license_key:
    await callback.message.answer("⚠️ Сначала введите ключ с помощью команды /key")
    return

  category_name = callback.data.replace("cat_", "")

  async with httpx.AsyncClient() as client:
    try:
      res = await client.get(f"{API_BASE_URL}/items/{license_key}")
      if res.status_code == 200:
        items = res.json().get("data", [])
        filtered_items = [i for i in items if i.get("category", "Разное") == category_name]

        unique_items = {}
        for item in filtered_items:
          name = item.get("name")
          item_id = item.get("item_id")
          if name and item_id and name not in unique_items:
            unique_items[name] = item_id

        builder = InlineKeyboardBuilder()
        for name, item_id in unique_items.items():
          builder.button(
              text=f"📦 {name}",
              callback_data=f"item_{item_id}",
          )
        builder.adjust(1)
        builder.row(
            types.InlineKeyboardButton(
                text="⬅️ Назад к категориям", callback_data="back_to_cats"
            )
        )

        display_cat = CATEGORY_NAMES.get(category_name, category_name)
        await callback.message.edit_text(
            f"📦 **Категория: {display_cat}**\nВыберите предмет для просмотра:",
            reply_markup=builder.as_markup(),
            parse_mode="Markdown",
        )
    except Exception as e:
      await callback.answer(f"Ошибка: {e}")
  await callback.answer()


@dp.callback_query(F.data.startswith("item_"))
async def process_item_click(callback: types.CallbackQuery, state: FSMContext):
  data = await state.get_data()
  license_key = data.get("license_key")
  if not license_key:
    await callback.message.answer("⚠️ Сначала введите ключ с помощью команды /key")
    return

  item_id = callback.data.replace("item_", "")

  async with httpx.AsyncClient() as client:
    try:
      res = await client.get(f"{API_BASE_URL}/history/{license_key}/{item_id}")
      if res.status_code == 200:
        history_data = res.json().get("data", [])
        if not history_data:
          await callback.message.answer("Предмет не найден в базе данных.")
          await callback.answer()
          return

        item_name = history_data[0].get("item_name", item_id)
        rarities = list(set(i.get("rarity", "Обычный") for i in history_data))

        builder = InlineKeyboardBuilder()
        for rarity in rarities:
          builder.button(
              text=f"✨ {rarity}",
              callback_data=f"rarity_{item_id}_{rarity}",
          )
        builder.button(text="⬅️ Назад к категориям", callback_data="back_to_cats")
        builder.adjust(1)

        await callback.message.edit_text(
            f"📦 **{item_name}**\n\nВыберите доступную редкость:",
            reply_markup=builder.as_markup(),
            parse_mode="Markdown",
        )
    except Exception as e:
      await callback.message.answer(f"Ошибка: {e}")
  await callback.answer()


@dp.callback_query(F.data.startswith("rarity_"))
async def process_rarity_click(callback: types.CallbackQuery, state: FSMContext):
  data = await state.get_data()
  license_key = data.get("license_key")
  if not license_key:
    return

  parts = callback.data.replace("rarity_", "", 1).rsplit("_", 1)
  if len(parts) != 2:
    await callback.answer("Ошибка данных")
    return
  
  item_id, selected_rarity = parts[0], parts[1]

  async with httpx.AsyncClient() as client:
    try:
      res = await client.get(f"{API_BASE_URL}/history/{license_key}/{item_id}")
      if res.status_code == 200:
        history_data = res.json().get("data", [])
        
        filtered = [
            i for i in history_data 
            if i.get("rarity") == selected_rarity
        ]

        if not filtered:
          await callback.message.answer("Нет данных для этой редкости.")
          await callback.answer()
          return

        item_name = filtered[0].get("item_name", item_id)

        lines = [
            f"📊 **История выкупа: {item_name}**",
            f"🔹 Редкость: **{selected_rarity}**\n",
        ]
        for row in filtered[:5]:
          date_str = row["created_at"][:16].replace("T", " ")
          price = f"{row['min_buyout_price']:,}".replace(",", " ")
          lines.append(
              f"• `{date_str}` — **{price} руб.** ({row.get('total_lots', 0)} лотов)"
          )

        builder = InlineKeyboardBuilder()
        builder.button(text="🎯 Поставить снайпер на эту редкость", callback_data=f"set_sniper_{item_id}_{selected_rarity}")
        builder.button(text="⬅️ Назад к выбору редкости", callback_data=f"item_{item_id}")
        builder.adjust(1)

        await callback.message.edit_text("\n".join(lines), reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
      await callback.message.answer(f"Ошибка: {e}")
  await callback.answer()


# --- ЛОГИКА СНАЙПЕРА ЦЕН ---

@dp.callback_query(F.data.startswith("set_sniper_"))
async def process_set_sniper(callback: types.CallbackQuery, state: FSMContext):
  parts = callback.data.replace("set_sniper_", "", 1).rsplit("_", 1)
  if len(parts) != 2:
    await callback.answer("Ошибка настройки снайпера")
    return
  
  item_id, selected_rarity = parts[0], parts[1]
  data = await state.get_data()
  license_key = data.get("license_key")

  async with httpx.AsyncClient() as client:
    try:
      res = await client.get(f"{API_BASE_URL}/history/{license_key}/{item_id}")
      if res.status_code == 200:
        history_data = res.json().get("data", [])
        item_name = history_data[0].get("item_name", item_id) if history_data else item_id
      else:
        item_name = item_id
    except Exception:
      item_name = item_id

  await state.update_data(
      sniper_item_id=item_id, 
      sniper_item_name=item_name, 
      sniper_rarity=selected_rarity
  )
  await state.set_state(UserSession.waiting_for_sniper_threshold)

  builder = InlineKeyboardBuilder()
  builder.button(text="⬅️ В главное меню", callback_data="back_to_main")
  builder.adjust(1)

  await callback.message.edit_text(
      f"🎯 **Настройка снайпера для:** `{item_name}` (`{selected_rarity}`)\n\n"
      "Введите желаемую **максимальную цену** (в рублях цифрой),\n"
      "при падении цены до которой или ниже вы получите мгновенное уведомление:",
      reply_markup=builder.as_markup(),
      parse_mode="Markdown"
  )
  await callback.answer()


@dp.message(UserSession.waiting_for_sniper_threshold)
async def process_sniper_threshold_input(message: types.Message, state: FSMContext):
  try:
    threshold = float(message.text.strip().replace(",", "."))
  except ValueError:
    await message.answer("❌ Пожалуйста, введите корректное число (например: 15000 или 15000.50):")
    return

  data = await state.get_data()
  license_key = data.get("license_key")
  item_id = data.get("sniper_item_id")
  item_name = data.get("sniper_item_name")
  selected_rarity = data.get("sniper_rarity")
  user_id = message.from_user.id

  active_snipers[user_id] = {
      "key": license_key,
      "item_id": item_id,
      "item_name": item_name,
      "rarity": selected_rarity,
      "threshold": threshold
  }

  await state.set_state(UserSession.in_menu)
  await state.update_data(sniper_item_id=None, sniper_item_name=None, sniper_rarity=None)

  builder = InlineKeyboardBuilder()
  builder.button(text="📂 В каталог", callback_data="back_to_cats")
  builder.button(text="🏠 Главное меню", callback_data="back_to_main")
  builder.adjust(1)

  await message.answer(
      f"✅ **Снайпер успешно активирован!**\n\n"
      f"📦 Предмет: *{item_name}* (`{selected_rarity}`)\n"
      f"🎯 Целевая цена: **{threshold:,.0f} руб.**\n\n"
      f"Мы проверяем рынок и пришлем вам уведомление, как только цена опустится ниже.",
      reply_markup=builder.as_markup(),
      parse_mode="Markdown"
  )


@dp.callback_query(F.data == "sniper_menu")
async def process_sniper_menu(callback: types.CallbackQuery, state: FSMContext):
  user_id = callback.from_user.id
  builder = InlineKeyboardBuilder()
  
  if user_id in active_snipers:
    s = active_snipers[user_id]
    text = (
        "🎯 **Ваш активный снайпер:**\n\n"
        f"📦 Предмет: *{s['item_name']}* (`{s['rarity']}`)\n"
        f"🎯 Порог цены: **{s['threshold']:,.0f} руб.**"
    )
    builder.button(text="❌ Отменить снайпер", callback_data="cancel_sniper")
  else:
    text = "🎯 У вас пока нет активных снайперов цен.\nВыберите предмет в каталоге, чтобы настроить его."

  builder.button(text="⬅️ В главное меню", callback_data="back_to_main")
  builder.adjust(1)

  await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
  await callback.answer()


@dp.callback_query(F.data == "cancel_sniper")
async def process_cancel_sniper(callback: types.CallbackQuery, state: FSMContext):
  user_id = callback.from_user.id
  if user_id in active_snipers:
    del active_snipers[user_id]
  
  await callback.message.edit_text("❌ Снайпер успешно удален.")
  data = await state.get_data()
  license_key = data.get("license_key")
  await show_main_menu(callback, edit=False, has_key=bool(license_key))
  await callback.answer()


async def price_sniper_background_loop():
  while True:
    await asyncio.sleep(60)
    if not active_snipers:
      continue

    async with httpx.AsyncClient() as client:
      for user_id, sniper in list(active_snipers.items()):
        license_key = sniper["key"]
        item_id = sniper["item_id"]
        target_rarity = sniper["rarity"]
        threshold = sniper["threshold"]

        try:
          res = await client.get(f"{API_BASE_URL}/history/{license_key}/{item_id}")
          if res.status_code == 200:
            history_data = res.json().get("data", [])
            if history_data:
              matching_rows = [
                  row for row in history_data 
                  if row.get("rarity") == target_rarity
              ]
              if matching_rows:
                latest = matching_rows[0]
                current_price = latest.get("min_buyout_price", 0)
                
                if current_price <= threshold:
                  date_str = latest.get("created_at", "")[:16].replace("T", " ")
                  lots = latest.get("total_lots", 0)
                  
                  text = (
                      f"🔥 **ВНИМАНИЕ! СНАЙПЕР СРАБОТАЛ!** 🔥\n\n"
                      f"📦 Предмет: *{sniper['item_name']}* (`{target_rarity}`)\n"
                      f"📉 Текущая цена: **{current_price:,.0f} руб.** (Ваш порог: {threshold:,.0f} руб.)\n"
                      f"📊 Доступно лотов: {lots}\n"
                      f"🕒 Время: `{date_str}`"
                  )
                  
                  builder = InlineKeyboardBuilder()
                  builder.button(text="🏠 В главное меню", callback_data="back_to_main")
                  builder.adjust(1)

                  await bot.send_message(user_id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")
                  del active_snipers[user_id]
        except Exception as e:
          print(f"Ошибка в фоновой задаче снайпера для user {user_id}: {e}")


async def main():
  asyncio.create_task(price_sniper_background_loop())
  print("Бот запущен со встроенным снайпером цен и выбором редкости!")
  await dp.start_polling(bot)


if __name__ == "__main__":
  asyncio.run(main())
