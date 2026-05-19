"""Telegram bot command handlers."""

from __future__ import annotations

import contextlib
import logging
from typing import cast

from sqlalchemy import select
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from verre.config import get_settings
from verre.crypto import Cipher, EncryptionError
from verre.db import session_scope
from verre.leaderboard import LeaderboardClient, LeaderboardError
from verre.models import ApiKey, MirroredPosition, TrackedLeader, User

logger = logging.getLogger(__name__)

START_TEXT = (
    "👋 *Verre* — копитрейдинг с Binance Futures Leaderboard.\n\n"
    "Бот зеркалит позиции выбранных топ-трейдеров на твой Binance аккаунт.\n\n"
    "⚠️ *Дисклеймер:* копитрейдинг — это высокий риск. Прошлые результаты не "
    "гарантируют будущих. Ты сам отвечаешь за любые убытки. По умолчанию бот "
    "работает в режиме *dry-run* — только присылает уведомления, не открывает "
    "реальные ордера.\n\n"
    "🛡 API-ключи Binance создавай *без права вывода средств*.\n\n"
    "Команды:\n"
    "/setkeys `<api_key> <api_secret>` — задать ключи Binance\n"
    "/keys — статус ключей\n"
    "/track `<encryptedUid> [name]` — копировать трейдера\n"
    "/untrack `<encryptedUid>` — прекратить\n"
    "/list — список отслеживаемых\n"
    "/size `<percent>` — % баланса на сделку (0.01–100)\n"
    "/spotmirror `on|off` — копировать LONG perp в спот\n"
    "/mode `dryrun|live` — переключить режим\n"
    "/status — текущие настройки\n"
    "/positions — мои скопированные позиции\n"
    "/stop — закрыть все скопированные позиции\n"
    "/help — справка"
)


def _is_allowed(update: Update) -> bool:
    allowed = get_settings().allowed_telegram_ids
    if not allowed:
        return True
    user = update.effective_user
    return user is not None and user.id in allowed


async def _get_or_create_user(telegram_id: int, username: str | None) -> User:
    async with session_scope() as session:
        stmt = select(User).where(User.telegram_id == telegram_id)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            row = User(telegram_id=telegram_id, username=username)
            session.add(row)
            await session.flush()
            await session.refresh(row)
        elif username and row.username != username:
            row.username = username
        return row


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    if update.effective_user is not None:
        await _get_or_create_user(update.effective_user.id, update.effective_user.username)
    msg = update.effective_message
    if msg is not None:
        await msg.reply_text(START_TEXT, parse_mode=ParseMode.MARKDOWN)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    msg = update.effective_message
    if msg is not None:
        await msg.reply_text(START_TEXT, parse_mode=ParseMode.MARKDOWN)


async def setkeys_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update) or update.effective_user is None:
        return
    msg = update.effective_message
    if msg is None:
        return
    args = context.args or []
    if len(args) < 2:
        await msg.reply_text(
            "Использование: /setkeys <api_key> <api_secret>\n\n"
            "⚠️ Создавай ключи на Binance без права вывода. После отправки удали "
            "сообщение из чата."
        )
        return
    api_key, api_secret = args[0], args[1]
    try:
        cipher = Cipher(get_settings().encryption_key)
    except EncryptionError as exc:
        await msg.reply_text(f"❌ Шифрование не настроено: {exc}")
        return
    enc_key = cipher.encrypt(api_key)
    enc_secret = cipher.encrypt(api_secret)
    user = await _get_or_create_user(update.effective_user.id, update.effective_user.username)
    async with session_scope() as session:
        existing = (
            await session.execute(select(ApiKey).where(ApiKey.user_id == user.id))
        ).scalar_one_or_none()
        if existing is None:
            session.add(ApiKey(user_id=user.id, encrypted_key=enc_key, encrypted_secret=enc_secret))
        else:
            existing.encrypted_key = enc_key
            existing.encrypted_secret = enc_secret
    with contextlib.suppress(Exception):
        await msg.delete()
    await msg.chat.send_message(
        "✅ Ключи сохранены (зашифрованы локально). Сообщение с ключами удалено."
    )


async def keys_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update) or update.effective_user is None:
        return
    msg = update.effective_message
    if msg is None:
        return
    user = await _get_or_create_user(update.effective_user.id, update.effective_user.username)
    async with session_scope() as session:
        row = (
            await session.execute(select(ApiKey).where(ApiKey.user_id == user.id))
        ).scalar_one_or_none()
    if row is None:
        await msg.reply_text("Ключи не заданы. /setkeys <api_key> <api_secret>")
    else:
        await msg.reply_text(
            f"Ключи сохранены (с {row.created_at:%Y-%m-%d %H:%M UTC}). "
            "Сами значения не показываются по соображениям безопасности."
        )


async def track_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update) or update.effective_user is None:
        return
    msg = update.effective_message
    if msg is None:
        return
    args = context.args or []
    if not args:
        await msg.reply_text("Использование: /track <encryptedUid> [имя]")
        return
    uid = args[0]
    nickname = " ".join(args[1:]) if len(args) > 1 else None
    user = await _get_or_create_user(update.effective_user.id, update.effective_user.username)
    async with session_scope() as session:
        existing = (
            await session.execute(
                select(TrackedLeader).where(
                    TrackedLeader.user_id == user.id, TrackedLeader.leader_uid == uid
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            await msg.reply_text("Уже отслеживается.")
            return
        session.add(TrackedLeader(user_id=user.id, leader_uid=uid, nickname=nickname))
    label = nickname or uid[:10] + "…"
    await msg.reply_text(f"✅ Начал отслеживать {label}.")


async def untrack_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update) or update.effective_user is None:
        return
    msg = update.effective_message
    if msg is None:
        return
    args = context.args or []
    if not args:
        await msg.reply_text("Использование: /untrack <encryptedUid>")
        return
    uid = args[0]
    user = await _get_or_create_user(update.effective_user.id, update.effective_user.username)
    async with session_scope() as session:
        row = (
            await session.execute(
                select(TrackedLeader).where(
                    TrackedLeader.user_id == user.id, TrackedLeader.leader_uid == uid
                )
            )
        ).scalar_one_or_none()
        if row is None:
            await msg.reply_text("Такой трейдер не отслеживался.")
            return
        await session.delete(row)
    await msg.reply_text("✅ Прекратил отслеживание.")


async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update) or update.effective_user is None:
        return
    msg = update.effective_message
    if msg is None:
        return
    user = await _get_or_create_user(update.effective_user.id, update.effective_user.username)
    async with session_scope() as session:
        rows = (
            (await session.execute(select(TrackedLeader).where(TrackedLeader.user_id == user.id)))
            .scalars()
            .all()
        )
    if not rows:
        await msg.reply_text("Список пуст. /track <encryptedUid>")
        return
    lines = ["📋 Отслеживаемые трейдеры:"]
    for r in rows:
        lines.append(f"• `{r.leader_uid}`" + (f" — {r.nickname}" if r.nickname else ""))
    await msg.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def size_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update) or update.effective_user is None:
        return
    msg = update.effective_message
    if msg is None:
        return
    args = context.args or []
    if not args:
        await msg.reply_text("Использование: /size <percent>  (например, /size 1.5)")
        return
    try:
        pct = float(args[0])
    except ValueError:
        await msg.reply_text("Не похоже на число.")
        return
    if not 0.01 <= pct <= 100:
        await msg.reply_text("Допустимый диапазон: 0.01–100 %.")
        return
    user = await _get_or_create_user(update.effective_user.id, update.effective_user.username)
    async with session_scope() as session:
        row = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        row.size_percent = pct
    await msg.reply_text(f"✅ Размер позиции = {pct}% от баланса.")


async def spotmirror_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update) or update.effective_user is None:
        return
    msg = update.effective_message
    if msg is None:
        return
    args = context.args or []
    if not args or args[0].lower() not in {"on", "off"}:
        await msg.reply_text("Использование: /spotmirror on|off")
        return
    enabled = args[0].lower() == "on"
    user = await _get_or_create_user(update.effective_user.id, update.effective_user.username)
    async with session_scope() as session:
        row = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        row.spot_mirror_enabled = enabled
    await msg.reply_text(
        f"✅ Spot mirror = {'on' if enabled else 'off'}.\n"
        "Когда трейдер открывает LONG perp — бот покупает токен на споте; при "
        "закрытии LONG — продаёт."
        if enabled
        else "Spot mirror выключен."
    )


async def mode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update) or update.effective_user is None:
        return
    msg = update.effective_message
    if msg is None:
        return
    args = context.args or []
    if not args or args[0].lower() not in {"dryrun", "live"}:
        await msg.reply_text("Использование: /mode dryrun|live")
        return
    new_mode = args[0].lower()
    user = await _get_or_create_user(update.effective_user.id, update.effective_user.username)
    async with session_scope() as session:
        row = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        row.mode = new_mode
    if new_mode == "live":
        await msg.reply_text(
            "⚠️ Включён LIVE режим. Реальные ордера будут размещаться на твоём "
            "Binance аккаунте.\nПерейти обратно: /mode dryrun"
        )
    else:
        await msg.reply_text("✅ Режим: dry-run (только уведомления).")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update) or update.effective_user is None:
        return
    msg = update.effective_message
    if msg is None:
        return
    user = await _get_or_create_user(update.effective_user.id, update.effective_user.username)
    async with session_scope() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        key_row = (
            await session.execute(select(ApiKey).where(ApiKey.user_id == user.id))
        ).scalar_one_or_none()
        leaders = (
            (await session.execute(select(TrackedLeader).where(TrackedLeader.user_id == user.id)))
            .scalars()
            .all()
        )
    await msg.reply_text(
        "⚙️ Статус:\n"
        f"  Режим: {u.mode}\n"
        f"  Размер: {u.size_percent}%\n"
        f"  Spot mirror: {'on' if u.spot_mirror_enabled else 'off'}\n"
        f"  API ключи: {'заданы' if key_row else 'нет'}\n"
        f"  Отслеживаемых трейдеров: {len(leaders)}"
    )


async def positions_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update) or update.effective_user is None:
        return
    msg = update.effective_message
    if msg is None:
        return
    user = await _get_or_create_user(update.effective_user.id, update.effective_user.username)
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(MirroredPosition).where(MirroredPosition.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
    if not rows:
        await msg.reply_text("Скопированных позиций нет.")
        return
    lines = ["📊 Скопированные позиции:"]
    for r in rows:
        lines.append(
            f"• [{r.market}] {r.symbol} {r.position_side} qty={r.quantity:.6f} "
            f"entry={r.entry_price:.6f}"
        )
    await msg.reply_text("\n".join(lines))


async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update) or update.effective_user is None:
        return
    msg = update.effective_message
    if msg is None:
        return
    user = await _get_or_create_user(update.effective_user.id, update.effective_user.username)
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(MirroredPosition).where(MirroredPosition.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            await session.delete(r)
    await msg.reply_text(
        f"🛑 Удалил {len(rows)} запис(и/ей) о скопированных позициях из БД.\n"
        "Если ты в live режиме, закрывай реальные позиции вручную на Binance."
    )


async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    msg = update.effective_message
    if msg is None:
        return
    args = context.args or []
    if not args:
        await msg.reply_text("Использование: /search <nickname>")
        return
    keyword = " ".join(args)
    async with LeaderboardClient(timeout=get_settings().leaderboard_timeout) as client:
        try:
            results = await client.search(keyword)
        except LeaderboardError as exc:
            await msg.reply_text(f"❌ Поиск не удался: {exc}")
            return
    if not results:
        await msg.reply_text("Ничего не нашлось.")
        return
    lines = ["🔎 Найдено:"]
    for item in results[:10]:
        uid = cast(str, item.get("encryptedUid", ""))
        nick = cast(str, item.get("nickName", "?"))
        roi = item.get("roi") or item.get("pnl")
        lines.append(f"• {nick}\n  uid=`{uid}`\n  metric={roi}")
    await msg.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
