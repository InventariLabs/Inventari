import importlib.util
from typing import Any

from fastapi import APIRouter

from app.core.define_module import define_module

from ._settings import SELF_APPROVE_SETTING


def _get_router() -> APIRouter:
    from .router import router

    return router


def _settings_schema() -> dict[str, Any]:
    return {
        'type': 'object',
        'properties': {
            SELF_APPROVE_SETTING: {
                'type': 'boolean',
                'default': False,
                'title': 'Admins may approve their own requests',
                'title_key': 'approvals:settings.allowAdminSelfApprove',
                'description_key': 'approvals:settings.allowAdminSelfApproveDescription',
                'description': (
                    'Off by default: an approval step exists to put a second '
                    'person on the decision. Turn it on when the admin is the '
                    'only approver and the workflow would otherwise deadlock.'
                ),
            },
        },
        'additionalProperties': False,
    }


def _default_settings() -> dict[str, Any]:
    return {SELF_APPROVE_SETTING: False}


def _gate_warehouse_documents() -> None:
    """Put this module's gate on the warehouse's documents.

    The warehouse asks a pre-post check of every module before it confirms a
    document and before it moves its stock; ours holds a document that needs
    an approval and refuses to post one that has none (``document_gate``).
    The decision on a request then moves the document through the warehouse's
    API. Registered with the contributions, once every module is discovered,
    and only where the warehouse is installed: the engine runs without it.
    """
    if importlib.util.find_spec('app.modules.warehouse') is None:
        return
    from app.modules.warehouse.warehouse_api import warehouse_api

    from .approvals_api import approvals_api
    from .document_gate import (
        MODULE,
        follow_document_decision,
        gate_document_async,
        withdraw_request_async,
    )

    warehouse_api.register_pre_post_check(
        MODULE, gate_document_async, on_withdrawn=withdraw_request_async
    )
    approvals_api.register_target_decision_listener(
        'document', follow_document_decision
    )


# Lazy router: pass a placeholder to define_module, then override register_routes
# to avoid triggering the full import chain (router → services → models) at
# module-discovery time.  This prevents double table registration with
# pytest's --import-mode=importlib.
_placeholder = APIRouter()
module = define_module(
    router=_placeholder, register_contributions_hook=_gate_warehouse_documents
)
module.register_routes = _get_router  # type: ignore[method-assign]
module.get_settings_schema = _settings_schema  # type: ignore[method-assign]
module.get_default_settings = _default_settings  # type: ignore[method-assign]
