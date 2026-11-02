"""Nutrition helpers for ProductTemplate enrichment."""

_OFF_TO_NUTRITION_INFO: dict[str, str] = {
    'energy_kcal': 'calories_kcal',
    'proteins': 'protein_g',
    'carbohydrates': 'carbs_g',
    'fat': 'fat_g',
    'fiber': 'fiber_g',
    'sugars': 'sugar_g',
    'salt': 'salt_g',
}


def extract_nutrition_info_from_off_metadata(meta_data: dict) -> dict | None:
    """Convert OFF metadata.nutrition dict to ProductTemplate.nutrition_info format.

    Args:
        meta_data: The item meta_data dict (may contain 'nutrition' key from OFF scan).

    Returns:
        nutrition_info dict with canonical keys, or None if no usable data found.
    """
    off_nutrition = meta_data.get('nutrition') if meta_data else None
    if not off_nutrition:
        return None

    result = {
        target: float(off_nutrition[source])
        for source, target in _OFF_TO_NUTRITION_INFO.items()
        if off_nutrition.get(source) is not None
    }
    return result or None
