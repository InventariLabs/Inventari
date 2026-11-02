"""
Seed profiles for Inventari.

Each profile represents a vertical/use-case bundle that can be applied
independently or combined during onboarding.

Available profiles:
    base          -- Neutral defaults: UoM, general storage types (SHELF, SYSTEM)
    food_home     -- Food & home inventory: FREEZER, FRIDGE, PANTRY + food categories
    equipment_wms -- Equipment / WMS: tool rooms, asset storage, IT racks
    clean_core    -- Minimal neutral seed: only base, no domain-specific data
"""

from app.seed_profiles.base import seed_base_all
from app.seed_profiles.clean_core import seed_clean_core
from app.seed_profiles.equipment_wms import seed_equipment_wms
from app.seed_profiles.food_home import seed_food_home

__all__ = [
    'seed_base_all',
    'seed_food_home',
    'seed_equipment_wms',
    'seed_clean_core',
]
