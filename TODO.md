# ЗАДАЧА: PYTHON CLI-ОБЁРТКА ДЛЯ СВЯЗКИ CODEX И OPENCODE

## 1. Цель

Нужно разработать MVP консольного Python-приложения, которое позволяет запускать двух AI coding agents по очереди:

* основной агент — пишет код / выполняет задачу;
* ревьюер — проверяет результат основного агента;
* пользователь вручную управляет циклом:

  * отправить задачу основному агенту;
  * отправить результат ревьюеру;
  * отправить замечания обратно основному агенту;
  * повторять до состояния `OK`.

Приложение должно работать в консоли и иметь удобный интерфейс: меню, панели вывода, историю шагов, понятные статусы выполнения.

На первом этапе не нужно пытаться встраивать родные TUI-интерфейсы Codex/OpenCode. Нужно запускать агентов через CLI-команды в non-interactive режиме.

---

## 2. Основная идея

Приложение запускается командой:

```bash
python -m agent_bridge
```

После запуска пользователь видит консольный интерфейс:

```text
┌───────────────────────────────┬───────────────────────────────┐
│ BUILDER                       │ REVIEWER                      │
│ codex                         │ opencode                      │
│                               │                               │
│ Последний результат агента    │ Последний результат ревьюера  │
└───────────────────────────────┴───────────────────────────────┘

[1] Новая задача
[2] Отправить задачу основному агенту
[3] Отправить результат основного агента ревьюеру
[4] Отправить замечания ревьюера основному агенту
[5] Показать git diff
[6] Запустить тесты
[7] Показать историю
[8] Завершить
```

Пользователь сам выбирает действие. Автоматического бесконечного цикла на MVP не нужно.

---

## 3. Стек

Использовать:

```text
Python 3.11+
rich
textual
python-dotenv
pydantic
typer
```

Назначение библиотек:

* `rich` — красивый вывод, панели, markdown, таблицы;
* `textual` — простой TUI-интерфейс, если будет удобно;
* `python-dotenv` — загрузка `.env`;
* `pydantic` — валидация настроек;
* `typer` — CLI-команды.

Если Textual сильно усложняет MVP, можно начать с Rich + обычное меню через `input()`.

---

## 4. Структура проекта

Сделать такую структуру:

```text
agent-bridge/
  agent_bridge/
    __init__.py
    __main__.py
    app.py

    config.py

    agents/
      __init__.py
      base.py
      codex.py
      opencode.py
      factory.py

    prompts/
      __init__.py
      templates.py

    services/
      runner.py
      git_context.py
      history.py
      workflow.py

    ui/
      __init__.py
      console.py

  .env.example
  requirements.txt
  README.md
```

---

## 5. Настройки через .env

Сделать `.env.example`:

```env
# Рабочая директория проекта, над которым работают агенты
PROJECT_DIR=/path/to/project

# Доступные значения: codex, opencode
BUILDER_AGENT=codex
REVIEWER_AGENT=opencode

# Можно выбрать хоть двух одинаковых агентов:
# BUILDER_AGENT=codex
# REVIEWER_AGENT=codex

# Команды запуска
CODEX_BIN=codex
OPENCODE_BIN=opencode

# Базовые аргументы
CODEX_BASE_ARGS=exec
OPENCODE_BASE_ARGS=run

# OpenCode agent mode
# build — пишет код
# plan — анализирует без правок
OPENCODE_BUILDER_MODE=build
OPENCODE_REVIEWER_MODE=plan

# Таймаут выполнения одной команды в секундах
AGENT_TIMEOUT=1800

# Папка для хранения истории
HISTORY_DIR=.agent-bridge/history

# Команда запуска тестов
TEST_COMMAND=composer test
```

Важно: приложение должно позволять выбирать:

```env
BUILDER_AGENT=codex
REVIEWER_AGENT=opencode
```

или:

```env
BUILDER_AGENT=codex
REVIEWER_AGENT=codex
```

или:

```env
BUILDER_AGENT=opencode
REVIEWER_AGENT=opencode
```

То есть роли и конкретные движки должны быть разделены.

---

## 6. Интерфейс адаптеров

Сделать базовый интерфейс агента.

Файл:

```text
agent_bridge/agents/base.py
```

Пример:

```python
from dataclasses import dataclass
from typing import Protocol


@dataclass
class AgentResult:
    agent_name: str
    role: str
    prompt: str
    stdout: str
    stderr: str
    returncode: int
    duration_sec: float

    @property
    def text(self) -> str:
        return self.stdout.strip()


class AgentAdapter(Protocol):
    name: str
    role: str

    def run(self, prompt: str) -> AgentResult:
        ...
```

Каждый адаптер должен:

* принимать prompt;
* запускать внешний CLI-процесс;
* возвращать stdout/stderr/returncode;
* не падать без понятной ошибки;
* уважать `PROJECT_DIR`;
* уважать timeout.

---

## 7. Адаптер Codex

Файл:

```text
agent_bridge/agents/codex.py
```

Поведение:

* запускать Codex через `codex exec`;
* передавать prompt как аргумент или через stdin;
* возвращать финальный stdout;
* stderr сохранять отдельно.

Примерная команда:

```bash
codex exec "текст задачи"
```

Адаптер должен собирать команду из настроек:

```python
[CODEX_BIN, *CODEX_BASE_ARGS.split(), prompt]
```

На MVP не надо парсить JSON. Достаточно обычного stdout.

---

## 8. Адаптер OpenCode

Файл:

```text
agent_bridge/agents/opencode.py
```

Поведение:

* запускать OpenCode через `opencode run`;
* для reviewer использовать mode `plan`;
* для builder использовать mode `build`;
* возвращать stdout/stderr/returncode.

Примерная команда:

```bash
opencode run --agent plan "проверь изменения"
```

или:

```bash
opencode run --agent build "выполни задачу"
```

Адаптер должен учитывать роль:

```python
if role == "reviewer":
    agent_mode = OPENCODE_REVIEWER_MODE
else:
    agent_mode = OPENCODE_BUILDER_MODE
```

---

## 9. Фабрика агентов

Файл:

```text
agent_bridge/agents/factory.py
```

Сделать фабрику:

```python
def create_agent(agent_type: str, role: str, settings: Settings) -> AgentAdapter:
    if agent_type == "codex":
        return CodexAgent(role=role, settings=settings)

    if agent_type == "opencode":
        return OpenCodeAgent(role=role, settings=settings)

    raise ValueError(f"Unsupported agent type: {agent_type}")
```

Фабрика должна позволять создать:

```python
builder = create_agent(settings.builder_agent, "builder", settings)
reviewer = create_agent(settings.reviewer_agent, "reviewer", settings)
```

---

## 10. Workflow

Сделать сервис:

```text
agent_bridge/services/workflow.py
```

Он должен хранить текущее состояние:

```python
current_task: str | None
last_builder_result: AgentResult | None
last_reviewer_result: AgentResult | None
status: str
```

Основные методы:

```python
set_task(text: str)
run_builder()
send_builder_to_reviewer()
send_review_back_to_builder()
show_history()
approve()
```

---

## 11. Prompt-шаблоны

Файл:

```text
agent_bridge/prompts/templates.py
```

Сделать шаблоны.

### Builder initial prompt

```text
Ты основной агент-разработчик.

Задача:
{task}

Работай в проекте. Вноси изменения аккуратно.
После выполнения кратко напиши:
1. Что изменено.
2. Какие файлы затронуты.
3. Как проверить результат.
4. Есть ли риски или незавершённые места.
```

### Reviewer prompt

```text
Ты агент-ревьюер.

Проверь результат работы основного агента.

Исходная задача:
{task}

Ответ основного агента:
{builder_output}

Git status:
{git_status}

Git diff:
{git_diff}

Твоя задача:
1. Найти ошибки в логике.
2. Найти баги.
3. Проверить соответствие исходной задаче.
4. Найти лишние или опасные изменения.
5. Проверить, не нужно ли добавить тесты.
6. Дать конкретные правки.

Если всё хорошо, ответь строго:
OK

Если есть проблемы, верни список замечаний и конкретные инструкции для исправления.
```

### Fix prompt

```text
Ты основной агент-разработчик.

Ревьюер проверил твою работу и оставил замечания.

Исходная задача:
{task}

Замечания ревьюера:
{review_output}

Текущий git status:
{git_status}

Текущий git diff:
{git_diff}

Исправь замечания.
После исправления кратко напиши:
1. Что исправлено.
2. Какие файлы изменены.
3. Как проверить результат.
4. Остались ли спорные моменты.
```

---

## 12. Git context

Файл:

```text
agent_bridge/services/git_context.py
```

Сделать функции:

```python
get_git_status(project_dir: str) -> str
get_git_diff(project_dir: str) -> str
```

Команды:

```bash
git status --short
git diff
```

Если проект не является git-репозиторием — вернуть понятное сообщение, не падать.

---

## 13. Запуск тестов

Файл:

```text
agent_bridge/services/runner.py
```

Сделать функцию:

```python
run_shell_command(command: str, cwd: str, timeout: int) -> CommandResult
```

Через неё запускать:

```env
TEST_COMMAND=composer test
```

Если команда пустая — пункт меню «Запустить тесты» должен сказать, что команда не настроена.

---

## 14. История

На MVP достаточно хранить историю в JSONL.

Папка:

```text
.agent-bridge/history/
```

Файл сессии:

```text
2026-06-25_12-30-00.jsonl
```

Каждая запись:

```json
{
  "timestamp": "2026-06-25T12:30:00",
  "type": "builder_result",
  "agent": "codex",
  "role": "builder",
  "prompt": "...",
  "stdout": "...",
  "stderr": "...",
  "returncode": 0,
  "duration_sec": 32.4
}
```

Типы событий:

```text
task_created
builder_result
reviewer_result
fix_result
test_result
approved
error
```

---

## 15. UI MVP

Сначала можно сделать простой Rich-интерфейс.

Файл:

```text
agent_bridge/ui/console.py
```

Нужно реализовать:

```text
- красивый заголовок;
- вывод текущей конфигурации;
- две панели: Builder и Reviewer;
- меню действий;
- markdown-вывод ответов;
- цветовые статусы:
  - running;
  - success;
  - error;
  - waiting;
```

Главное меню:

```text
1. Ввести новую задачу
2. Запустить Builder
3. Отправить результат Builder → Reviewer
4. Отправить замечания Reviewer → Builder
5. Показать git diff
6. Запустить тесты
7. Показать историю текущей сессии
8. Очистить экран
9. Выход
```

Для длинного ввода задачи сделать многострочный ввод.

Например:

```text
Введите задачу. Завершите ввод строкой:
.END
```

---

## 16. Обработка ошибок

Нужно обработать:

* не найден `codex`;
* не найден `opencode`;
* агент завершился с ненулевым кодом;
* timeout;
* пустой prompt;
* не указан `PROJECT_DIR`;
* директория проекта не существует;
* неизвестный тип агента в `.env`;
* нет результата builder, но пользователь нажал отправку на review;
* нет результата reviewer, но пользователь нажал отправку обратно builder.

Ошибки должны показываться в интерфейсе и писаться в историю.

---

## 17. README

В README описать:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m agent_bridge
```

Также описать примеры конфигурации.

### Codex + OpenCode

```env
BUILDER_AGENT=codex
REVIEWER_AGENT=opencode
```

### Codex + Codex

```env
BUILDER_AGENT=codex
REVIEWER_AGENT=codex
```

### OpenCode + OpenCode

```env
BUILDER_AGENT=opencode
REVIEWER_AGENT=opencode
```

---

## 18. Ограничения MVP

На первом этапе НЕ делать:

* полноценное desktop-приложение;
* встраивание родных TUI Codex/OpenCode;
* автоматический бесконечный цикл без участия пользователя;
* сложный web-интерфейс;
* авторизацию;
* облачное хранение;
* параллельный запуск нескольких агентов;
* редактирование файлов внутри самой оболочки.

---

## 19. Критерии готовности

MVP считается готовым, если:

1. Приложение запускается через:

```bash
python -m agent_bridge
```

2. Настройки читаются из `.env`.

3. Можно выбрать пары агентов:

```text
codex + opencode
codex + codex
opencode + opencode
```

4. Можно ввести задачу.

5. Можно запустить основного агента.

6. Можно отправить результат основного агента ревьюеру.

7. Можно отправить замечания ревьюера обратно основному агенту.

8. Можно посмотреть `git diff`.

9. Можно запустить команду тестов из `.env`.

10. История сохраняется в JSONL.

11. Ошибки внешних CLI-команд не ломают приложение.

---

## 20. Финальная цель MVP

Получить простой локальный инструмент:

```text
один агент пишет код → второй агент делает ревью → человек управляет циклом → история сохраняется
```

Инструмент должен быть расширяемым, чтобы позже добавить:

* Claude Code;
* Gemini CLI;
* локальные модели;
* desktop-интерфейс;
* автоматический цикл до `OK`;
* SQLite;
* экспорт отчёта по сессии.
