"""Unit tests for nutrition helper — OFF metadata → nutrition_info mapping."""

from app.services.items.nutrition import extract_nutrition_info_from_off_metadata


class TestExtractNutritionInfoFromOffMetadata:
    """Tests for OFF metadata → nutrition_info key mapping."""

    def test_returns_none_when_metadata_is_empty(self):
        assert extract_nutrition_info_from_off_metadata({}) is None

    def test_returns_none_when_nutrition_key_missing(self):
        assert extract_nutrition_info_from_off_metadata({'off_enriched': True}) is None

    def test_returns_none_when_nutrition_dict_is_empty(self):
        assert extract_nutrition_info_from_off_metadata({'nutrition': {}}) is None

    def test_maps_energy_kcal_to_calories_kcal(self):
        meta = {'nutrition': {'energy_kcal': 350.0}}
        result = extract_nutrition_info_from_off_metadata(meta)
        assert result is not None
        assert result['calories_kcal'] == 350.0

    def test_maps_all_standard_keys(self):
        meta = {
            'nutrition': {
                'energy_kcal': 250.0,
                'proteins': 10.5,
                'carbohydrates': 30.0,
                'fat': 8.0,
                'fiber': 3.5,
                'sugars': 5.0,
                'salt': 0.8,
            }
        }
        result = extract_nutrition_info_from_off_metadata(meta)
        assert result == {
            'calories_kcal': 250.0,
            'protein_g': 10.5,
            'carbs_g': 30.0,
            'fat_g': 8.0,
            'fiber_g': 3.5,
            'sugar_g': 5.0,
            'salt_g': 0.8,
        }

    def test_skips_none_values(self):
        meta = {
            'nutrition': {
                'energy_kcal': 200.0,
                'proteins': None,
                'carbohydrates': 40.0,
            }
        }
        result = extract_nutrition_info_from_off_metadata(meta)
        assert result is not None
        assert 'protein_g' not in result
        assert result['calories_kcal'] == 200.0
        assert result['carbs_g'] == 40.0

    def test_ignores_non_nutrition_off_keys(self):
        """nova_group, nutrient_levels etc. should not end up in nutrition_info."""
        meta = {
            'nutrition': {
                'energy_kcal': 100.0,
                'nova_group': 3,
                'nutrient_levels': {'fat': 'high'},
            }
        }
        result = extract_nutrition_info_from_off_metadata(meta)
        assert result is not None
        assert 'nova_group' not in result
        assert 'nutrient_levels' not in result

    def test_converts_integer_values_to_float(self):
        meta = {'nutrition': {'energy_kcal': 350, 'proteins': 8}}
        result = extract_nutrition_info_from_off_metadata(meta)
        assert result is not None
        assert isinstance(result['calories_kcal'], float)
        assert isinstance(result['protein_g'], float)

    def test_returns_none_when_only_non_mapped_keys(self):
        meta = {'nutrition': {'nova_group': 3, 'nutrient_levels': {}}}
        result = extract_nutrition_info_from_off_metadata(meta)
        assert result is None
