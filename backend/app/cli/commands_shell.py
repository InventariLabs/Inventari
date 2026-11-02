from rich.console import Console

console = Console()


def shell_command():
    """Open interactive Inventari Shell Plus (IPython)."""
    # Reuse the existing shell.py main() which handles
    # model auto-import, db session setup, and IPython/fallback
    import shell

    shell.main()
