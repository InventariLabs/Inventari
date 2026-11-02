"""HTTP mapping for this module's two service exceptions.

Eight endpoints repeated the same two ``except`` clauses. They cannot use
``app.core.exceptions.map_service_errors``: ``ApprovalError`` subclasses
``ValueError``, which that decorator maps to 400 — but half of these
endpoints have always answered 409 for a workflow conflict, and
``ApprovalNotFoundError`` (also a subclass) has to win over its base to stay
a 404.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from app.core.exceptions import (
    AppException,
    ConflictException,
    NotFoundException,
    refusal_code,
    refusal_exception,
)

from .exceptions import (
    ApprovalError,
    ApprovalNotFoundError,
    ApprovalScopeChangedError,
    ApprovalScopeRequiredError,
    ApprovalStageUnsolvableError,
)

T = TypeVar('T')


def map_approval_errors(
    resource: str, *, conflict: bool = False
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Map approval failures to HTTP: 404 for *resource*, 400 (or 409) otherwise.

    ``conflict=True`` is for the endpoints where a broken business rule means
    "the state says no" — creating a second workflow for a target type, or a
    request for something already under approval.
    """

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except ApprovalNotFoundError as exc:
                raise NotFoundException(resource=resource) from exc
            except ApprovalStageUnsolvableError as exc:
                # A refusal with a way past it: the form may save the stage
                # anyway, so the code has to arrive intact rather than as the
                # generic approval conflict.
                raise ConflictException(
                    code='APPROVAL_STAGE_UNSOLVABLE', message=str(exc)
                ) from exc
            except ApprovalScopeChangedError as exc:
                # The dialog that sent the scope re-reads it and asks again;
                # it tells this conflict from the others by the code.
                raise ConflictException(
                    code='APPROVAL_SCOPE_CHANGED', message=str(exc)
                ) from exc
            except ApprovalScopeRequiredError as exc:
                raise AppException(
                    status_code=422, code='APPROVAL_SCOPE_REQUIRED', message=str(exc)
                ) from exc
            except ApprovalError as exc:
                if conflict:
                    raise ConflictException(
                        code=refusal_code(exc, 'APPROVAL_ERROR'),
                        message=str(exc),
                    ) from exc
                raise refusal_exception(exc) from exc

        return wrapper

    return decorate
