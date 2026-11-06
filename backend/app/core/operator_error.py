"""The refusal whose reader is the operator at a terminal, not a user.

Process start, a ``manage.py`` command and manifest or seed-profile
validation refuse in sentences meant for whoever runs the command or reads
the log: which variable to set, which flag to pass. No request reaches them,
so they are not the translated refusals a toast shows, and they do not belong
to the family of reader-facing ``ValueError`` sentences the rejection ledger
counts.

A ``ValueError`` subclass on purpose: every caller that already catches
``ValueError`` around these checks (the CLI printing the message, the module
loader degrading a module) keeps doing so unchanged. ``reader_facing = False``
is the runtime half of the classification: if one ever escaped into a request,
the 400 handler would answer with the generic sentence and log the real one.

Kept free of imports so ``app.config`` can raise it.
"""

from __future__ import annotations


class OperatorError(ValueError):
    """A refusal written for an operator; never shown to an application user."""

    reader_facing = False
