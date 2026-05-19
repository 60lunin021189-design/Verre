# Verre

Telegram-бот для копирования сделок топовых трейдеров с **Binance Futures
Leaderboard**. Зеркалит открытие и закрытие позиций на твой Binance-аккаунт,
опционально дублирует LONG-перпы покупкой токенов на споте.

> ⚠️ **Дисклеймер.** Копитрейдинг — это очень высокий риск. Прошлые результаты
> топ-трейдеров **не гарантируют** будущих. Бот может ошибаться, биржа может
> поменять API. Никогда не запускай в `live` режиме сумму, потерю которой не
> готов пережить. По умолчанию бот стартует в `dryrun` — никаких реальных
> ордеров не размещается, только уведомления в Telegram.

## Возможности

- Источник сигналов — публичный **Binance Futures Leaderboard**
  (`/bapi/futures/v*/public/future/leaderboard/...`). По `encryptedUid`
  отслеживаются открытые позиции топ-трейдеров.
- Исполнение — Binance API (USDⓈ-M Futures + Spot) через `python-binance` на
  собственном аккаунте пользователя.
- Telegram-интерфейс на `python-telegram-bot` v21 (async).
- Шифрование API-ключей в локальном SQLite (Fernet/AES-128 + HMAC-SHA256).
- Режимы `dryrun` (по умолчанию) и `live` с подтверждением.
- Spot-mirror: при открытии LONG-перпа покупается токен на споте; при закрытии
  LONG — продаётся.

## Архитектура

```
┌───────────────┐  poll   ┌─────────────────────┐
│  Binance      │◄────────┤  LeaderboardClient  │
│  Leaderboard  │         └──────────┬──────────┘
└───────────────┘                    │ positions
                                     ▼
                            ┌────────────────┐
                            │   CopyEngine   │
                            │ (diff + size)  │
                            └───┬────────┬───┘
                       orders   │        │ DB updates
                                ▼        ▼
                      ┌────────────────┐ ┌──────────────┐
                      │ BinanceTrader  │ │   SQLite     │
                      │ (futures+spot) │ │ (mirror state)│
                      └────────────────┘ └──────────────┘
                                ▲
                                │ notifications
                                ▼
                       ┌─────────────────┐
                       │ Telegram Bot    │
                       └─────────────────┘
```

## Установка

Требуется Python 3.11+.

```bash
git clone https://github.com/60lunin021189-design/Verre.git
cd Verre
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Настройка

1. **Telegram-бот.** Создай бота в [@BotFather](https://t.me/BotFather) и скопируй
   токен.
2. **Binance API-ключи.** В разделе *API Management* создай новый ключ. Включи:
   - ✅ Enable Reading
   - ✅ Enable Spot & Margin Trading
   - ✅ Enable Futures
   - ❌ **Withdraw** — оставь выключенным.
3. **Ключ шифрования.** Сгенерируй Fernet-ключ для хранения Binance-ключей
   локально:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
4. Создай файл `.env` (см. `.env.example`) и впиши:
   ```dotenv
   TELEGRAM_BOT_TOKEN=123456:ABCDEF
   VERRE_ENCRYPTION_KEY=<сгенерированный_ключ>
   VERRE_DB_PATH=verre.db
   # необязательно: ограничить, кто может пользоваться ботом
   VERRE_ALLOWED_TELEGRAM_IDS=123456789
   ```

## Запуск

```bash
verre
# либо
python -m verre
```

Бот запустит long polling Telegram, поллер лидерборда (каждые 20 сек по
умолчанию) и будет реагировать на команды.

## Команды бота

| Команда | Описание |
|---|---|
| `/start` / `/help` | приветствие, дисклеймер, список команд |
| `/setkeys <api_key> <api_secret>` | сохранить Binance API-ключ/секрет (шифрованно) |
| `/keys` | проверить, что ключи установлены |
| `/track <encryptedUid> [name]` | начать копировать трейдера |
| `/untrack <encryptedUid>` | прекратить копировать |
| `/list` | список отслеживаемых |
| `/search <nickname>` | найти трейдера на лидерборде |
| `/size <percent>` | какой % USDT-баланса использовать на одну сделку (0.01–100; default 1) |
| `/spotmirror on|off` | копировать LONG-перпы в спот |
| `/mode dryrun|live` | переключить режим (`dryrun` — только уведомления, `live` — реальные ордера) |
| `/status` | текущие настройки |
| `/positions` | мои скопированные позиции |
| `/stop` | очистить локальное состояние скопированных позиций |

## Где взять `encryptedUid`?

Открой страницу трейдера на
<https://www.binance.com/en/copy-trading/lead-details/...> — в URL после
`/lead-details/` идёт `encryptedUid`. Либо используй команду `/search`.

## Безопасность

- Ключи Binance хранятся в SQLite в зашифрованном виде. Ключ шифрования читается
  только из переменной окружения `VERRE_ENCRYPTION_KEY` — *не коммить его*.
- Создавай Binance-ключи **без права вывода**. Бот в этом режиме физически не
  может вывести средства с твоего аккаунта.
- По умолчанию бот в `dryrun` режиме. Чтобы перейти к реальным ордерам, нужна
  явная команда `/mode live`.
- `VERRE_ALLOWED_TELEGRAM_IDS` позволяет ограничить, кто может использовать
  бота. Если переменная пуста, бот отвечает любому пользователю (для приватного
  деплоя на одну машину это нормально, для публичной — нет).

## Разработка

```bash
# линт
ruff check .
ruff format --check .
# типы
mypy verre
# тесты
pytest -q
```

## Roadmap (не в первом PR)

- Поддержка изменения размера позиции у лидера (сейчас отслеживаются только
  открытие/закрытие).
- Учёт реального исполненного количества и средней цены ордера (для более
  точной отчётности).
- Веб-дашборд статистики PnL.
- Несколько бирж (Bybit, OKX) через единый интерфейс.
- Stop-loss / take-profit для скопированных позиций.

## Лицензия

MIT.
