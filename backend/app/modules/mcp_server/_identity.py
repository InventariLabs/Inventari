"""Who an MCP tool call acts as, and what it may do.

The identity is established once, by the auth middleware, from the API key's
owner and the key's own permission list. It travels in a contextvar because the
SDK calls a tool handler in a task the middleware has already entered; nothing
about the workspace, the user or the permissions is ever taken from the tool's
arguments.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import UUID

from mcp.server.mcpserver.exceptions import ToolError

from app.core.contracts import UserContextDTO
from app.core.module_sdk import get_current_lang, get_module_error_message

MODULE_NAME = 'mcp_server'


def refusal(code: str, key: str, **kwargs: object) -> ToolError:
    """A tool failure the model should read, named by a stable code.

    The sentence comes from the module's own catalog in the reader's language;
    the code stays in one language so a client can branch on it.
    """
    message = get_module_error_message(MODULE_NAME, key, get_current_lang(), **kwargs)
    return ToolError(f'{code}: {message}')


@dataclass(frozen=True)
class McpIdentity:
    """The authenticated workspace and the key that authenticated it."""

    user: UserContextDTO
    organization_id: UUID
    user_id: UUID
    key_prefix: str

    def require(self, permission: str) -> None:
        """Refuse the call when the key does not hold *permission*.

        The key's list, not its owner's grants: that is what `get_current_user`
        put on the user context (`identity_service._load_user_context`).
        """
        if not self.user.has_permission(permission):
            raise refusal(
                'PERMISSION_REQUIRED',
                'insufficient_permission',
                permission=permission,
            )


_current: ContextVar[McpIdentity | None] = ContextVar('mcp_identity', default=None)


def bind_identity(identity: McpIdentity) -> Token[McpIdentity | None]:
    """Make *identity* the caller of the tool calls in this task."""
    return _current.set(identity)


def reset_identity(token: Token[McpIdentity | None]) -> None:
    _current.reset(token)


def current_identity() -> McpIdentity:
    """The caller of the tool now running, or a readable refusal."""
    identity = _current.get()
    if identity is None:
        raise refusal('NOT_AUTHENTICATED', 'call_without_identity')
    return identity
