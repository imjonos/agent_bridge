# Agent Bridge

Agent Bridge is a console Python application for running a manual workflow between two AI coding agents:

- `builder` performs the task and changes the project;
- `reviewer` checks the builder result and returns `OK` or review notes;
- the user manually starts each next step, review pass, fix pass, test run, diff check, and rollback.

The UI is built with Textual. The left side contains the current task editor and session timeline, while the right side shows live output from the active process. The top panel shows status, selected agent pair, project path, timeout, language, and test command.

## Requirements

- Python 3.11+
- Installed CLI tools for the selected agents: `codex` and/or `opencode`
- A target project where the agents will run

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Run from the application directory:

```bash
python -m agent_bridge
```

Or run through the wrapper:

```bash
./agent-bridge
```

The wrapper uses the local `.venv/bin/python` first. If the virtual environment is not available, it falls back to `python3` or the `PYTHON` environment variable.

## Configuration

The `.env` file is loaded automatically. If `PROJECT_DIR` is not set, Agent Bridge uses the current working directory. This is useful when an alias is executed from inside the target project.

Alias example through the Python module:

```bash
alias agent-bridge='PYTHONPATH=/path/to/agent_manager /path/to/agent_manager/.venv/bin/python -m agent_bridge'
```

To keep the alias across terminal sessions, add it to your shell configuration:

```bash
echo "alias agent-bridge='PYTHONPATH=/path/to/agent_manager /path/to/agent_manager/.venv/bin/python -m agent_bridge'" >> ~/.zshrc
source ~/.zshrc
```

Then open the target project and run:

```bash
cd /path/to/project
agent-bridge
```

Example `.env`:

```env
# PROJECT_DIR is optional. The current working directory is used by default.
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

Supported agent pairs are role-based, so the same engine can be used for both roles:

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

`HISTORY_DIR` can be an absolute path or a path relative to `PROJECT_DIR`.

## Behavior

- `python -m agent_bridge` starts the interactive Textual UI.
- You can create an `agent-bridge` alias and run it from a project directory without setting `PROJECT_DIR`.
- Builder and reviewer run through external CLI commands.
- Session history is stored as JSONL in `HISTORY_DIR`.
- A rollback snapshot is created in `.agent-bridge/rollback` inside the target project before an agent run.
- If `TEST_COMMAND` is not configured, the test action reports that explicitly.
- `Live output` shows agent stdout/stderr in real time. Stderr and error-looking lines are highlighted in red.
- `Timeline` shows current session events and recent results.
- The top `Usage` panel shows run count, duration, and token estimates per builder/reviewer.

## Keyboard Shortcuts

- `F2` — save the current task.
- `F5` — run the next logical step: builder, reviewer, or fix pass.
- `F6` — stop the active process.
- `Ctrl+B` — run builder.
- `Ctrl+R` — send the builder result to reviewer.
- `Ctrl+D` — show `git diff`.
- `Ctrl+T` — run `TEST_COMMAND`.
- `Ctrl+Z` — roll back the latest changes using a rollback snapshot.
- `Ctrl+L` — clear the activity log.
- `Ctrl+G` — switch the UI language.
- `Ctrl+N` — start a new task.
- `Ctrl+Q` — quit the UI.

## Roadmap

- Add support for more AI coding agents beyond Codex and OpenCode.
- Add more workflow automation options while keeping manual control available.
- Improve history browsing and project-level reporting.
