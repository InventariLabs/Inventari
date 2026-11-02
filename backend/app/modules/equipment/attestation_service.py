"""Asset Attestation service — campaign lifecycle, token management, email dispatch.

This module is a facade re-exporting the implementation from sub-modules.
Public API is preserved; existing import paths keep working.
"""

from ._attestation_campaigns import (
    cancel_campaign,
    complete_campaign,
    create_campaign,
    delete_campaign,
    get_campaign,
    get_campaign_detail,
    launch_campaign,
    list_campaigns,
    send_reminders,
)
from ._attestation_responses import (
    confirm_response,
    dispute_response,
    get_public_response,
    get_response_by_token,
)
from ._attestation_scheduler import (
    run_attestation_reminder_self_contained,
    run_scheduled_reminder_check_async,
)

__all__ = [
    'cancel_campaign',
    'complete_campaign',
    'confirm_response',
    'create_campaign',
    'delete_campaign',
    'dispute_response',
    'get_campaign',
    'get_campaign_detail',
    'get_public_response',
    'get_response_by_token',
    'launch_campaign',
    'list_campaigns',
    'run_attestation_reminder_self_contained',
    'run_scheduled_reminder_check_async',
    'send_reminders',
]
