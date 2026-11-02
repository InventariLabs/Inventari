"""CLI utilities and shared bootstrap logic."""

import os

import typer
from rich.console import Console

console = Console()

#: Names an operator can give ``INVENTARI_ENV`` to say "this install is for
#: testing" when it runs with ``DEBUG`` off, as a staging copy does.
DISPOSABLE_ENVIRONMENTS = ('development', 'staging')


class NotDisposableError(RuntimeError):
    """The install did not say it is for development, testing or staging."""


def check_disposable_install(
    action: str, *, allowed: tuple[str, ...] = DISPOSABLE_ENVIRONMENTS
) -> None:
    """Raise unless the install says its data may be thrown away.

    Production is the install that says nothing: its compose sets ``DEBUG`` off
    and no ``INVENTARI_ENV``, so the guard asks for a positive answer — ``DEBUG``
    or ``TESTING`` on, or ``INVENTARI_ENV`` naming one of *allowed*, with
    ``ENVIRONMENT`` read as its alias — instead of looking for the word
    "production". An install that does say production, on either name, is
    refused whatever else is on. *action* finishes the sentence "This command
    …" in the refusal.
    """
    from app.config import settings

    # INVENTARI_ENV is the name (.env.example documents it); ENVIRONMENT is an
    # alias kept for a stack that already carries that word. Both decisions
    # below read this one resolved value, and the name wins when both are set.
    env = os.environ.get('INVENTARI_ENV')
    said = env if env is not None else os.environ.get('ENVIRONMENT', '')
    if said.lower() in ('production', 'prod'):
        reason = f'this install says it is {said!r}'
    elif settings.DEBUG or settings.TESTING or said.lower() in allowed:
        return
    else:
        if env is not None:
            named = repr(env)
        elif said:
            named = f'not set; the ENVIRONMENT alias is {said!r}'
        else:
            named = 'not set'
        reason = (
            f'DEBUG is {settings.DEBUG}, TESTING is {settings.TESTING} and '
            f'INVENTARI_ENV is {named}'
        )
    raise NotDisposableError(
        f'This command {action}, so it runs only where DEBUG or TESTING is on '
        f'or INVENTARI_ENV is one of: {", ".join(allowed)}. Here {reason}.'
    )


def guard_disposable_install(action: str) -> None:
    """`check_disposable_install` for a command: print the refusal and exit 1."""
    try:
        check_disposable_install(action)
    except NotDisposableError as exc:
        console.print(f'[bold red]ERROR:[/] {exc}')
        raise typer.Exit(code=1) from exc


def bootstrap_db():
    """Initialize database connection. Call lazily — only when a command needs DB."""
    from app.core.module_registry import module_registry

    module_registry.discover_modules()
