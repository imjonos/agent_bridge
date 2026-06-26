from __future__ import annotations

import typer

from .config import SettingsError, load_settings
from .services.history import HistoryService
from .services.workflow import Workflow
from .agents.factory import create_agent
from .ui.console import ConsoleApp

cli = typer.Typer(add_completion=False, invoke_without_command=True)


def run_interactive() -> None:
    settings = load_settings()
    history = HistoryService(settings.history_path())
    builder = create_agent(settings.builder_agent, "builder", settings)
    reviewer = create_agent(settings.reviewer_agent, "reviewer", settings)
    workflow = Workflow(settings=settings, builder=builder, reviewer=reviewer, history=history)
    ConsoleApp(settings=settings, workflow=workflow, history=history).run()


@cli.callback(invoke_without_command=True)
def run_cli(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        try:
            run_interactive()
        except SettingsError as exc:
            typer.secho(f"Ошибка конфигурации: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from exc
        except Exception as exc:
            typer.secho(f"Ошибка запуска: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from exc


def main_entry() -> None:
    cli()


def main() -> None:
    main_entry()
