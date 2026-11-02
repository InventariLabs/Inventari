"""
Inventari Shell Plus - Developer Experience (DX) Tool
===================================================

This script provides an interactive Python REPL for the Inventari backend,
heavily inspired by Django's `shell_plus`. It is designed to make database
inspection and debugging as frictionless as possible for open-source contributors
and self-hosters.

Key Features:
- 🚀 Auto-Imports: Automatically discovers and imports all SQLAlchemy models
  (from Core and all installed Modules) into the local namespace.
- 🗄️ Ready DB Session: Provides a pre-configured, connected `db` session object.
- 🎨 IPython Support: Automatically uses IPython if installed for syntax
  highlighting, magic commands, and tab-completion.
- 🤫 Silent Mode: Suppresses verbose SQLAlchemy engine logs by default for a
  cleaner REPL experience.

Usage:
    docker compose exec backend python shell.py

    # Inside the shell:
    > db.query(Item).count()
    > user = db.query(User).first()
"""

import os
import sys
import warnings

warnings.warn(
    'shell.py is deprecated. Use: python manage.py shell',
    DeprecationWarning,
    stacklevel=1,
)

# Add the project root to the python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging  # noqa: E402

from app.database import Base, SessionLocal  # noqa: E402

# Disable verbose logging in shell
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)


def _get_all_models():
    """Dynamically find all SQLAlchemy models registered in Base.metadata"""
    models = {}
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        models[cls.__name__] = cls
    return models


def main():
    print('Loading FastAPI Shell Plus...')

    # 1. Setup DB Session
    db = SessionLocal()

    # 2. Prepare namespace with default variables
    namespace = {
        'db': db,
        'SessionLocal': SessionLocal,
    }

    # 3. Auto-import all models (like Django shell_plus)
    # Ensure models are loaded by importing them

    # Also load models from modules
    try:
        import app.core.module_registry  # noqa: F401 - ensures modules are loaded
        # This forces loading all module models
    except ImportError:
        pass

    db_models = _get_all_models()
    namespace.update(db_models)

    # 4. Print banner
    print('\n' + '=' * 50)
    print('🚀 Inventari Shell Plus')
    print('=' * 50)
    print('Available variables:')
    print('  \033[92mdb\033[0m: Database Session')
    print(
        f'  \033[96mModels ({len(db_models)})\033[0m: {", ".join(sorted(db_models.keys()))[:100]}...'
    )
    print('\nExamples:')
    print('  > db.query(Item).count()')
    print('  > user = db.query(User).first()')
    print('=' * 50 + '\n')

    # 5. Start the best available interactive shell
    try:
        # Try IPython first for the best experience (colors, autocomplete)
        import IPython
        from traitlets.config import Config

        c = Config()
        c.TerminalInteractiveShell.confirm_exit = False
        IPython.start_ipython(argv=[], user_ns=namespace, config=c)
    except ImportError:
        # Fallback to standard python shell
        import code
        import readline

        readline.parse_and_bind('tab: complete')
        code.interact(local=namespace)


if __name__ == '__main__':
    main()
