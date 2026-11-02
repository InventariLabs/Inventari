from typing import Any, Self

from app.core.exceptions import ServiceRejectionError


class ApprovalError(ServiceRejectionError):
    """Raised for business rule violations in approval workflows.

    A keyed refusal: the envelope answers with the key as its ``code``, as
    for every other ``ServiceRejectionError``.
    """

    @classmethod
    def translated(cls, key: str, **params: Any) -> Self:
        """Build the error with its message in the reader's language.

        Every refusal this module raises travels through ``str(exc)`` into an
        HTTP envelope and lands in a toast verbatim — here and in the modules
        that proxy the engine (documents, purchase orders, equipment). An
        English literal at the raise site therefore answers a Polish interface
        in English, which is exactly what it used to do.

        ``ApprovalNotFoundError`` needs no such treatment: routers turn it into
        ``NotFoundException``, which looks its own message up by resource slug.
        """
        return cls(key, **params)


class ApprovalRequiredError(ApprovalError):
    """Raised when an operation requires approval but it's missing (or is REJECTED)."""


class ApprovalStageUnsolvableError(ApprovalError):
    """Raised when a stage nobody could decide is being saved.

    Its own class so the router can answer with its own code: the workflow
    form offers to save the stage anyway, and the screen has to tell this
    refusal from the other conflicts (a pending request, a duplicate target)
    without reading the sentence, which is translated.
    """


class ApprovalScopeChangedError(ApprovalError):
    """Raised when a workflow is switched on against a scope that has moved.

    The switch-on dialog sends the scope it showed; when the owning module's
    settings changed in between, the reader agreed to a rule that is no longer
    the one that would hold. Its own class so the router answers with its own
    code and the dialog can read the new scope and ask again.
    """


class ApprovalScopeRequiredError(ApprovalError):
    """Raised when a workflow is switched on without the scope the reader saw.

    The switch-on guarantee is that nobody brings a workflow into force
    under a rule they were not shown; a caller that sends no
    ``expected_scope`` has not been shown one. Answered 422, naming the field.
    """


class ApprovalNotFoundError(ApprovalError):
    """Raised when a workflow or request lookup yields no result.

    Routers translate this to ``404 Not Found`` so the HTTP layer can
    distinguish missing resources from genuine business-rule conflicts.
    """
