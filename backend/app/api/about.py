"""The instance's legal notices, for the in-app About screen.

AGPL-3.0 §5(d) asks an interactive interface to show them, §13 asks a
modified version served over a network to offer its source. The version and
the licence come from ``pyproject.toml``, the source link from the
instance's configuration.
"""

from fastapi import APIRouter, Depends

from app.config import UPSTREAM_SOURCE_CODE_URL, settings
from app.core.contracts import UserContextDTO
from app.core.deps import get_current_user_context
from app.core.version import get_platform_license, get_platform_version
from app.schemas.about import AboutResponse

router = APIRouter()

_LICENSE_URL = 'https://www.gnu.org/licenses/agpl-3.0.html'


@router.get('', response_model=AboutResponse)
async def get_about(
    _current_user: UserContextDTO = Depends(get_current_user_context),
) -> AboutResponse:
    """Name, version, licence and source link of this installation."""
    return AboutResponse(
        name='Inventari',
        version=get_platform_version(),
        license=get_platform_license(),
        license_url=_LICENSE_URL,
        # A blank line in .env means "not set", not "no source".
        source_code_url=settings.SOURCE_CODE_URL.strip() or UPSTREAM_SOURCE_CODE_URL,
    )
