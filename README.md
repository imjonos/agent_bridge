# Agent Bridge

Консольное Python-приложение для ручного workflow между двумя AI coding agents:

- `builder` выполняет задачу и вносит изменения в проект;
- `reviewer` проверяет результат builder и возвращает `OK` либо замечания;
- пользователь сам запускает следующий шаг, ревью, исправление, тесты, diff и откат.

UI построен на Textual: слева находится редактор текущей задачи и история сессии, справа отображается live output активного процесса. В верхней панели видны статус, выбранная пара агентов, проект, таймаут, язык и команда тестов.

## Требования

- Python 3.11+
- Установленные CLI выбранных агентов: `codex` и/или `opencode`
- Рабочий проект, в котором будут запускаться агенты

## Установка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Запуск из директории приложения:

```bash
python -m agent_bridge
```

Или через wrapper:

```bash
./agent-bridge
```

Wrapper сначала использует `.venv/bin/python` рядом с собой, а если виртуальное окружение не найдено, берёт `python3` или значение переменной `PYTHON`.

## Конфигурация

Файл `.env` загружается автоматически. Если `PROJECT_DIR` не задан, используется текущая директория запуска. Это удобно для alias, который вызывается уже внутри нужного проекта.

Пример alias:

```bash
alias agent-bridge='/Users/nos/PycharmProjects/agent_manager/agent-bridge'
```

После этого можно перейти в целевой проект и запустить:

```bash
cd /path/to/project
agent-bridge
```

Пример `.env`:

```env
# PROJECT_DIR необязателен, по умолчанию используется текущая директория
PROJECT_DIR=/path/to/project
BUILDER_AGENT=codex
REVIEWER_AGENT=opencode
CODEX_BIN=codex
OPENCODE_BIN=opencode
CODEX_BASE_ARGS=exec
OPENCODE_BASE_ARGS=run
OPENCODE_BUILDER_MODE=build
OPENCODE_REVIEWER_MODE=plan
AGENT_TIMEOUT=1800
HISTORY_DIR=.agent-bridge/history
TEST_COMMAND=composer test
```

Поддерживаемые пары агентов задаются через роли, поэтому можно комбинировать движки:

```env
BUILDER_AGENT=codex
REVIEWER_AGENT=opencode
```

```env
BUILDER_AGENT=codex
REVIEWER_AGENT=codex
```

```env
BUILDER_AGENT=opencode
REVIEWER_AGENT=opencode
```

`HISTORY_DIR` может быть абсолютным путём или относительным путём внутри `PROJECT_DIR`.

## Поведение

- `python -m agent_bridge` запускает интерактивный Textual-интерфейс.
- Можно создать alias на wrapper `agent-bridge` и запускать его из директории проекта без `PROJECT_DIR`.
- Builder и reviewer работают через внешние CLI-команды.
- История сессии сохраняется в JSONL в `HISTORY_DIR`.
- Перед запуском агента создаётся rollback-снимок в `.agent-bridge/rollback` внутри рабочего проекта.
- Если команда тестов не настроена, пункт тестов сообщает об этом.
- `Live output` показывает stdout/stderr агента в реальном времени; stderr и строки с ошибками подсвечиваются красным.
- `Timeline` показывает события текущей сессии и последние результаты.
- Верхняя панель `Usage` показывает количество запусков, длительность и оценку токенов по builder/reviewer.

## Горячие клавиши

- `F2` — сохранить текущую задачу.
- `F5` — запустить следующий логический шаг: builder, reviewer или исправление по замечаниям.
- `F6` — остановить активный процесс.
- `Ctrl+B` — запустить builder.
- `Ctrl+R` — отправить результат builder на review.
- `Ctrl+D` — показать `git diff`.
- `Ctrl+T` — запустить `TEST_COMMAND`.
- `Ctrl+Z` — откатить последние изменения по rollback-снимку.
- `Ctrl+L` — очистить журнал активности.
- `Ctrl+G` — переключить язык интерфейса.
- `Ctrl+N` — начать новую задачу.
- `Ctrl+Q` — выйти из интерфейса.

## Ограничения MVP

- Нет автоматического бесконечного цикла.
- Нет встроенного TUI Codex/OpenCode.
- Нет web-интерфейса и облачного хранения.
