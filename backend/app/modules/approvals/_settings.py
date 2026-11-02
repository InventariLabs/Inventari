"""Organization-level settings of the approvals module.

Kept free of model and service imports: ``module.py`` reads it at discovery
time, and pulling the router/service/model chain in there registers the tables
twice under pytest's ``--import-mode=importlib``.
"""

# Lets an admin decide on a request they raised themselves. Off by default —
# separation of duties is the reason an approval step exists at all. Small
# organizations where the admin is the only approver turn it on knowingly.
SELF_APPROVE_SETTING = 'allow_admin_self_approve'
