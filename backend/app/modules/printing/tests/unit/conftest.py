"""
Configuration for printing module tests.

This conftest.py makes the printing module tests self-contained and independent.
Fixtures needed across modules are imported on demand from the main conftest.py.
"""


# Re-export commonly used fixtures from main conftest if needed
# For now, printing tests are primarily unit tests and don't require DB fixtures
