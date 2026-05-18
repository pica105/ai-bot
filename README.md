# BimBim 🤖

Telegram-бот для общения с OpenRouter AI через несколько сессий.

## Возможности

- **Несколько сессий** — создавай, переключай, переименовывай и удаляй диалоги
- **Любая модель** — смени модель одной командой (`/set_model`)
- **Системный промпт** — правишь на лету прямо в телеграме (`/set_prompt`)
- **Админ-контроль** — ботом управляете только вы (и те, кого вы добавили)

## Быстрый старт

```bash
git clone git@github.com:pica105/ai-bot.git
cd ai-bot
pip install -r requirements.txt
```

Скопируй `.env.example` в `.env` и заполни:

```bash
cp .env.example .env
```

Обязательные переменные:

| Переменная | Описание |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен от [@BotFather](https://t.me/BotFather) |
| `ADMIN_TG_ID` | Твой Telegram ID (можно списком через запятую) |
| `OPENROUTER_API_KEY` | API-ключ от [OpenRouter](https://openrouter.ai/) |

## Запуск

```bash
python bot.py
```

## Команды

| Команда | Описание |
|---|---|
| `/start` | Приветствие |
| `/sessions` | Список сессий с кнопками |
| `/switch` | Выбор сессии через меню |
| `/new` | Новая сессия |
| `/rename <имя>` | Переименовать текущую сессию |
| `/delete <id>` | Удалить сессию |
| `/set_model <model>` | Сменить модель (например `openai/gpt-4o`) |
| `/set_key <key>` | Сменить API-ключ |
| `/prompt` | Показать системный промпт |
| `/set_prompt` | Изменить системный промпт |
| `/status` | Информация о текущей сессии |
| `/cancel` | Отменить ожидание |
| `/help` | Справка |

## Структура

```
├── bimbim.py          # Ядро: сессии, SessionManager, CLI-режим
├── bot.py             # Telegram-бот (aiogram 3.x)
├── system_prompt.md   # Системный промпт, можно менять
├── requirements.txt   # Зависимости
├── .env               # Конфиг (секреты)
└── sessions.json      # Сессии (создаётся автоматически)
```

## CLI-режим

```bash
python bimbim.py
```

Запускает консольную версию без телеграма.
