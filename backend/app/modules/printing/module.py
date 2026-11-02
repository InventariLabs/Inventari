from typing import Any

from app.core.define_module import define_module
from app.core.label_rendering import register_label_renderers
from app.core.module_sdk import register_api_key_scope

from .router import router


def _render_single(label: Any, **kwargs: Any) -> bytes:
    from .services.label_print_service import generate_label_png

    return generate_label_png(label, **kwargs)


def _render_batch(labels: Any, **kwargs: Any) -> bytes:
    from .services.label_print_service import generate_label_batch_png

    return generate_label_batch_png(labels, **kwargs)


# Registered at import, not from a startup hook: Core answers label requests
# through this registry, and a request can arrive before any per-module startup
# hook has run. The thunks import lazily, so Pillow and the QR stack are still
# paid for only on the first label actually rendered.
register_label_renderers(single=_render_single, batch=_render_batch)

# A key issued with the ``printing`` scope (a Raspberry Pi next to the
# printer) reaches the endpoints that guard the agent's permission and nothing
# else. Registered at import for the same reason as the renderers:
# authentication runs on the very first request.
register_api_key_scope('printing', ('printing:agent',))

module = define_module(router=router)
