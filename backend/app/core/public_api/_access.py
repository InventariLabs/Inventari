"""What a ``core_api`` method does to the data, stated beside the method.

The CoreAPI reference (``docs/subsystems/CORE_API.md``) labels every method
READ or WRITE. The generator used to guess the label from words in the
method's name and docstring, and the guess called a lookup of existing ids a
write ("exist" holds "set") and a rename a read. The label is now declared
here, on the method, and the generator only reads it; a public method that
declares none stops the generator, so a new method cannot reach the reference
unlabelled.

WRITE means the call can change what the database or the file store holds,
or sends something out of the process — a mail, an event, a notification
pushed to a browser. Everything else is READ, including a read that takes
row locks, a render, a computation and a hook registered at import.

Like ``without_org_scope``, the decorators change nothing at runtime beyond
the mark they leave on the function.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

type Access = Literal['READ', 'WRITE']

#: The attribute the mark is kept under, read by the reference generator.
ACCESS_ATTRIBUTE = '__core_api_access__'


def reads[F: Callable[..., Any]](func: F) -> F:
    """Declare that the method leaves the data as it found it."""
    setattr(func, ACCESS_ATTRIBUTE, 'READ')
    return func


def writes[F: Callable[..., Any]](func: F) -> F:
    """Declare that the method can change stored data or send something out."""
    setattr(func, ACCESS_ATTRIBUTE, 'WRITE')
    return func


def declared_access(func: Callable[..., Any]) -> Access | None:
    """The label declared on *func*, or ``None`` when it declares none."""
    access = getattr(func, ACCESS_ATTRIBUTE, None)
    return access if access in ('READ', 'WRITE') else None
