"""
BimBim Telegram Bot — aiogram 3.x
Админ управляет сессиями нейронки через Telegram.
"""

import os
import logging

import httpx
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, CommandObject
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder

from dotenv import load_dotenv

from bimbim import SessionManager, get_system_prompt, update_system_prompt

load_dotenv()

# ─── Config ──────────────────────────────────────────────
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_IDS_RAW = os.getenv("ADMIN_TG_ID", "")
ADMIN_IDS: list[int] = []
for x in ADMIN_IDS_RAW.split(","):
    x = x.strip()
    if x.isdigit():
        ADMIN_IDS.append(int(x))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ─── Globals ─────────────────────────────────────────────
sm = SessionManager()
router = Router()
pending_rename: dict[int, str] = {}  # user_id → session_id
pending_prompt: set[int] = set()  # user_id — ждёт новый текст промпта


# ─── Admin guard ─────────────────────────────────────────
async def admin_required(message: Message) -> bool:
    if message.from_user.id in ADMIN_IDS:
        return True
    await message.answer("Пошёл нахуй, чмо")
    return False


def _build_session_keyboard(show_delete: bool = False) -> InlineKeyboardBuilder:
    """Собрать клавиатуру со всеми сессиями.
    show_delete — добавить кнопки ✏️ и 🗑️ для каждой сессии.
    """
    builder = InlineKeyboardBuilder()
    for sid, short, name, _ in sm.list_sessions():
        marker = "✅" if sid == sm.current_session_id else ""
        label = f"{marker} {name}".strip()
        builder.button(text=label, callback_data=f"switch:{sid}")
        if show_delete and sid != sm.current_session_id:
            builder.button(text="✏️", callback_data=f"rename:{sid}")
            builder.button(text="🗑️", callback_data=f"delete:{sid}")
        builder.row()  # каждая сессия на отдельной строке
    builder.button(text="➕ Новая сессия", callback_data="new")
    return builder


# ─── /start ──────────────────────────────────────────────
@router.message(Command("start"))
async def cmd_start(message: Message):
    if not await admin_required(message):
        return

    s = sm.current
    await message.answer(
        "👋 *BimBim бот*\n\n"
        f"🧠 Модель: `{s.model}`\n"
        f"💬 Сообщений: `{len(s.messages)}`\n\n"
        "*/sessions* — список сессий\n"
        "*/switch* — меню переключения\n"
        "*/new* — новая сессия\n"
        "*/rename* — переименовать текущую\n"
        "*/set_model* `<model>` — сменить модель\n"
        "*/set_key* `<key>` — сменить API-ключ\n"
        "*/prompt* — показать системный промпт\n"
        "*/set_prompt* — изменить системный промпт\n"
        "*/status* — статус\n"
        "*/help* — справка\n\n"
        "Просто отправь сообщение — нейронка ответит",
        parse_mode="Markdown",
    )


# ─── /new ────────────────────────────────────────────────
@router.message(Command("new"))
async def cmd_new(message: Message):
    if not await admin_required(message):
        return
    s = sm.create()
    await message.answer(f"✨ Новая сессия: *{s.name}*", parse_mode="Markdown")


# ─── /sessions ───────────────────────────────────────────
@router.message(Command("sessions"))
async def cmd_sessions(message: Message):
    if not await admin_required(message):
        return

    lines = []
    for sid, short, name, created in sm.list_sessions():
        marker = "✅" if sid == sm.current_session_id else "  "
        s = sm.sessions[sid]
        lines.append(f"{marker} *{name}* — {len(s.messages)} сообщ.")

    builder = _build_session_keyboard(show_delete=True)
    await message.answer(
        f"📂 *Сессии ({len(sm.sessions)})*\n\n" + "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=builder.as_markup(),
    )


# ─── /switch (inline menu) ───────────────────────────────
@router.message(Command("switch"))
async def cmd_switch(message: Message):
    if not await admin_required(message):
        return

    s = sm.current
    builder = _build_session_keyboard()

    await message.answer(
        f"📂 *Выбери сессию:*\n\n✅ Текущая: *{s.name}*\n💬 {len(s.messages)} сообщ.",
        parse_mode="Markdown",
        reply_markup=builder.as_markup(),
    )


# ─── Callback: переключить сессию ────────────────────────
@router.callback_query(lambda c: c.data and c.data.startswith("switch:"))
async def cb_switch(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Пошёл нахуй", show_alert=True)
        return

    session_id = callback.data.split(":", 1)[1]
    session = sm.sessions.get(session_id)
    if not session:
        await callback.answer("Сессия не найдена", show_alert=True)
        return

    if session_id == sm.current_session_id:
        await callback.answer("Уже активна")
        return

    sm.switch(session_id)
    await callback.message.edit_text(
        f"✅ Переключился на *{session.name}*",
        parse_mode="Markdown",
    )
    await callback.answer()


# ─── Callback: удалить сессию ────────────────────────────
@router.callback_query(lambda c: c.data and c.data.startswith("delete:"))
async def cb_delete(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Пошёл нахуй", show_alert=True)
        return

    session_id = callback.data.split(":", 1)[1]
    session = sm.sessions.get(session_id)
    if not session:
        await callback.answer("Сессия не найдена", show_alert=True)
        return

    if sm.delete(session_id):
        await callback.message.edit_text(
            f"🗑️ Сессия *{session.name}* удалена",
            parse_mode="Markdown",
        )
    else:
        await callback.answer("Нельзя удалить единственную сессию", show_alert=True)
    await callback.answer()


# ─── Callback: переименовать (запросить имя) ────────────
@router.callback_query(lambda c: c.data and c.data.startswith("rename:"))
async def cb_rename(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Пошёл нахуй", show_alert=True)
        return

    session_id = callback.data.split(":", 1)[1]
    session = sm.sessions.get(session_id)
    if not session:
        await callback.answer("Сессия не найдена", show_alert=True)
        return

    pending_rename[callback.from_user.id] = session_id
    await callback.message.edit_text(
        f"✏️ Отправь новое имя для сессии *{session.name}*",
        parse_mode="Markdown",
    )
    await callback.answer()


# ─── Callback: новая сессия ──────────────────────────────
@router.callback_query(lambda c: c.data == "new")
async def cb_new(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Пошёл нахуй", show_alert=True)
        return

    s = sm.create()
    await callback.message.edit_text(
        f"✨ Новая сессия: *{s.name}*",
        parse_mode="Markdown",
    )
    await callback.answer()


# ─── /rename ─────────────────────────────────────────────
@router.message(Command("rename"))
async def cmd_rename(message: Message, command: CommandObject):
    if not await admin_required(message):
        return

    args = (command.args or "").strip().split(maxsplit=1)

    if len(args) == 1:
        # /rename <new_name> — переименовать текущую
        new_name = args[0].strip()
        if not new_name:
            await message.answer("Укажи новое имя: `/rename Главная`", parse_mode="Markdown")
            return
        old = sm.current.name
        sm.rename(sm.current_session_id, new_name)
        await message.answer(f"✏️ Сессия *{old}* → *{new_name}*", parse_mode="Markdown")

    elif len(args) == 2:
        # /rename <id> <new_name> — переименовать по ID
        prefix, new_name = args
        matched = _find_session(prefix)
        if matched is None:
            await message.answer(f"❌ Сессия `{prefix}` не найдена", parse_mode="Markdown")
            return
        old = sm.sessions[matched].name
        sm.rename(matched, new_name)
        await message.answer(f"✏️ Сессия *{old}* → *{new_name}*", parse_mode="Markdown")
    else:
        await message.answer(
            "Укажи новое имя:\n"
            "`/rename Главная` — переименовать текущую\n"
            "`/rename abc12 Новая` — переименовать по ID",
            parse_mode="Markdown",
        )


# ─── /delete ─────────────────────────────────────────────
@router.message(Command("delete"))
async def cmd_delete(message: Message, command: CommandObject):
    if not await admin_required(message):
        return

    prefix = (command.args or "").strip()
    if not prefix:
        await message.answer("Укажи ID сессии: `/delete abc12345`", parse_mode="Markdown")
        return

    matched = _find_session(prefix)
    if matched is None:
        await message.answer(f"❌ Сессия `{prefix}...` не найдена", parse_mode="Markdown")
        return

    name = sm.sessions[matched].name
    if sm.delete(matched):
        await message.answer(f"🗑️ Сессия *{name}* удалена", parse_mode="Markdown")
    else:
        await message.answer("❌ Нельзя удалить единственную сессию. Сначала создай новую.")


# ─── /set_model ──────────────────────────────────────────
@router.message(Command("set_model"))
async def cmd_set_model(message: Message, command: CommandObject):
    if not await admin_required(message):
        return

    model = (command.args or "").strip()
    if not model:
        await message.answer(
            "Укажи модель: `/set_model openai/gpt-4o`\n"
            "Или `/set_model deepseek/deepseek-chat`",
            parse_mode="Markdown",
        )
        return

    sm.current.model = model
    sm.save()
    await message.answer(f"🧠 Модель изменена на `{model}`", parse_mode="Markdown")


# ─── /set_key ────────────────────────────────────────────
@router.message(Command("set_key"))
async def cmd_set_key(message: Message, command: CommandObject):
    if not await admin_required(message):
        return

    key = (command.args or "").strip()
    if not key:
        await message.answer("Укажи API-ключ: `/set_key sk-or-...`", parse_mode="Markdown")
        return

    sm.current.api_key = key
    sm.save()
    await message.answer("🔑 API-ключ обновлён (только для текущей сессии)")


# ─── /prompt ────────────────────────────────────────────
@router.message(Command("prompt"))
async def cmd_prompt(message: Message):
    if not await admin_required(message):
        return

    prompt_text = get_system_prompt()
    # если длинный — режем, показываем длину
    if len(prompt_text) > 3500:
        preview = prompt_text[:3500]
        await message.answer(
            f"📄 *Системный промпт* ({len(prompt_text)} симв.)\n\n"
            f"{preview}...\n\n"
            f"_Первые 3500 символов. Всего {len(prompt_text)}._",
            parse_mode="Markdown",
        )
    else:
        await message.answer(
            f"📄 *Системный промпт* ({len(prompt_text)} симв.)\n\n{prompt_text}",
            parse_mode="Markdown",
        )


# ─── /set_prompt ─────────────────────────────────────────
@router.message(Command("set_prompt"))
async def cmd_set_prompt(message: Message, command: CommandObject):
    if not await admin_required(message):
        return

    text = (command.args or "").strip()
    if text:
        if not text.strip():
            await message.answer("❌ Промпт не может быть пустым")
            return
        update_system_prompt(text)
        sm.current.messages[0]["content"] = text  # применяем к текущей сессии
        sm.save()
        preview = text[:100].replace("\n", " ")
        await message.answer(
            f"✅ Системный промпт обновлён (текущая сессия обновлена)!\n\n{preview}...",
            parse_mode=None,
        )
    else:
        # без аргументов — ждём текст следующим сообщением
        pending_prompt.add(message.from_user.id)
        await message.answer(
            "✏️ Отправь новый текст системного промпта\n"
            "(или /cancel чтобы отменить)",
            parse_mode="Markdown",
        )


# ─── /cancel ─────────────────────────────────────────────
@router.message(Command("cancel"))
async def cmd_cancel(message: Message):
    if not await admin_required(message):
        return

    uid = message.from_user.id
    cleared = False
    if uid in pending_rename:
        del pending_rename[uid]
        cleared = True
    if uid in pending_prompt:
        pending_prompt.discard(uid)
        cleared = True

    if cleared:
        await message.answer("✅ Отменено")
    else:
        await message.answer("❌ Нет активных ожиданий")


# ─── /status ─────────────────────────────────────────────
@router.message(Command("status"))
async def cmd_status(message: Message):
    if not await admin_required(message):
        return

    s = sm.current
    await message.answer(
        "📊 *Статус*\n\n"
        f"🆔 Сессия: *{s.name}* (`{s.session_id[:8]}...`)\n"
        f"🧠 Модель: `{s.model}`\n"
        f"💬 Сообщений: `{len(s.messages)}`\n"
        f"📅 Создана: `{s.created_at[:19]}`\n"
        f"🔄 Обновлена: `{s.updated_at[:19]}`",
        parse_mode="Markdown",
    )


# ─── Текст → нейронка / переименование ───────────────────
@router.message(F.text)
async def handle_text(message: Message):
    if not await admin_required(message):
        return

    user_id = message.from_user.id
    user_text = message.text.strip()
    if not user_text:
        return

    # ── если ожидается новый системный промпт ──
    if user_id in pending_prompt:
        pending_prompt.discard(user_id)
        if not user_text:
            await message.answer("❌ Промпт не может быть пустым. Попробуй ещё раз или /cancel")
            return
        update_system_prompt(user_text)
        sm.current.messages[0]["content"] = user_text  # применяем к текущей сессии
        sm.save()
        preview = user_text[:100].replace("\n", " ")
        await message.answer(
            f"✅ Системный промпт обновлён (текущая сессия обновлена)!\n\n{preview}...",
            parse_mode=None,
        )
        return

    # ── если ожидается имя для переименования ──
    if user_id in pending_rename:
        session_id = pending_rename.pop(user_id)
        session = sm.sessions.get(session_id)
        if session:
            old = session.name
            sm.rename(session_id, user_text)
            await message.answer(f"✏️ *{old}* → *{user_text}*", parse_mode="Markdown")
        else:
            await message.answer("❌ Сессия уже удалена")
        return

    # ── иначе — в нейронку ──
    await message.answer("🤔 Думаю...")

    try:
        async with httpx.AsyncClient() as client:
            data = await sm.current.ask(client, user_text)
        sm.save()
    except Exception as e:
        await message.answer(f"❌ Ошибка: `{e}`", parse_mode="Markdown")
        return

    if data is None:
        await message.answer("❌ Пустой ответ от нейронки")
        return

    reply = data["choices"][0]["message"]["content"]
    tokens = data["usage"]["total_tokens"]
    provider = data.get("provider", "?")

    if len(reply) > 3900:
        parts = [reply[i : i + 3900] for i in range(0, len(reply), 3900)]
        for part in parts:
            await message.answer(part, parse_mode=None)
        await message.answer(f"⚡ {tokens} tokens · {provider}")
    else:
        await message.answer(reply, parse_mode=None)
        await message.answer(f"⚡ {tokens} tokens · {provider}")


# ─── /help ────────────────────────────────────────────────
@router.message(Command("help"))
async def cmd_help(message: Message):
    if not await admin_required(message):
        return
    await message.answer(
        "📖 *Команды*\n\n"
        "*/start* — приветствие\n"
        "*/sessions* — список сессий (с кнопками)\n"
        "*/switch* — меню выбора сессии\n"
        "*/new* — новая сессия\n"
        "*/rename* — переименовать текущую сессию\n"
        "*/delete* `<id>` — удалить сессию\n"
        "*/set_model* `<model>` — сменить модель ИИ\n"
        "*/set_key* `<key>` — сменить API-ключ\n"
        "*/prompt* — показать системный промпт\n"
        "*/set_prompt* — изменить системный промпт\n"
        "*/cancel* — отменить ожидание (переименование / промпт)\n"
        "*/status* — информация о текущей сессии\n"
        "*/help* — эта справка",
        parse_mode="Markdown",
    )


# ─── Helper ──────────────────────────────────────────────
def _find_session(prefix: str) -> str | None:
    """Найти полный ID сессии по префиксу."""
    prefix = prefix.rstrip(".")
    for sid in sm.sessions:
        if sid.startswith(prefix):
            return sid
    return None


# ─── Main ────────────────────────────────────────────────
async def main():
    if not BOT_TOKEN:
        logging.error("TELEGRAM_BOT_TOKEN не задан в .env")
        return
    if not ADMIN_IDS:
        logging.error("ADMIN_TG_ID не задан в .env (формат: 12345, 67890)")
        return

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    dp = Dispatcher()
    dp.include_router(router)

    logging.info("BimBim бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
