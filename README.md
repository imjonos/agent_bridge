# Agent Bridge

MVP консольного Python-приложения для последовательного запуска двух AI coding agents: builder и reviewer. UI построен на Textual и использует фиксированные панели, кнопки и рабочую область с редактором задачи.

## Установка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m agent_bridge
```

## Конфигурация

Файл `.env` загружается автоматически.

Если `PROJECT_DIR` не задан, приложение возьмёт текущую директорию запуска как рабочий каталог. Это удобно для alias вроде `agent-bridge`, который вызывается уже внутри нужного проекта.

Пример alias:

```bash
alias agent-bridge='/Users/nos/PycharmProjects/agent_manager/agent-bridge'
```

Пример:

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

Поддерживаемые пары агентов:

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

## Поведение

- `python -m agent_bridge` запускает интерактивный Textual-интерфейс.
- Можно создать alias на wrapper `agent-bridge` и запускать его из директории проекта без `PROJECT_DIR`.
- Builder и reviewer работают через внешние CLI-команды.
- История сессии сохраняется в JSONL.
- Если команда тестов не настроена, пункт меню сообщает об этом.
- Новая задача вводится в текстовом редакторе слева и сохраняется через `F2`.
- Откат последних изменений после запуска агента доступен через `Ctrl+Z`.
- Выход из интерфейса: `Ctrl+Q`.
- `Live output` показывает stdout/stderr агента в реальном времени; stderr и строки с ошибками подсвечиваются красным.
- `Final result` показывает последний завершённый результат builder/reviewer.
- `Usage` показывает количество запусков, длительность и примерную оценку токенов по builder/reviewer.

Можно также вызывать wrapper напрямую:

```bash
/Users/nos/PycharmProjects/agent_manager/agent-bridge
```

## Ограничения MVP

- Нет автоматического бесконечного цикла.
- Нет встроенного TUI Codex/OpenCode.
- Нет web-интерфейса и облачного хранения.
