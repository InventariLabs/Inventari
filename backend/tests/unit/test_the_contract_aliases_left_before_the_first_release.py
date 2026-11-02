"""The alias surface cut before the first release is gone, and stays gone.

The contracts gate is additive-only, so a re-added field passes the snapshot
diff silently: nothing in it records that the name was retired. The window
these aliases were held for protected consumers outside the repository, and
before 0.11.0 there are none — the first release is what starts the
obligation. This is where a late re-introduction is caught.
"""

import app.core.contracts as contracts
from app.core.contracts import (
    ConsumptionStatsDTO,
    CostSummaryDTO,
    RotationAnalysisDTO,
    StorageTypeCreateDTO,
)
from app.modules.warehouse.schemas import DocumentLineCreate, DocumentListResponse


def test_the_analytics_twins_are_gone():
    assert 'waste_rate' not in ConsumptionStatsDTO.model_fields
    assert 'waste_event_rate' in ConsumptionStatsDTO.model_fields
    assert 'waste_percentage' not in CostSummaryDTO.model_fields
    assert 'waste_value_percentage' in CostSummaryDTO.model_fields
    assert 'average_rotation_days' not in RotationAnalysisDTO.model_fields
    assert 'median_rotation_days' not in RotationAnalysisDTO.model_fields
    assert 'average_stock_age_days' in RotationAnalysisDTO.model_fields
    assert 'median_stock_age_days' in RotationAnalysisDTO.model_fields


def test_the_storage_type_create_dto_takes_no_organization():
    assert 'organization_id' not in StorageTypeCreateDTO.model_fields


def test_the_consumerless_activity_dtos_are_gone():
    assert not hasattr(contracts, 'ActivityDayDTO')
    assert not hasattr(contracts, 'ActivityTimelineDTO')


def test_the_document_list_answers_one_key():
    assert 'documents' not in DocumentListResponse.model_fields
    assert 'documents' not in DocumentListResponse.model_computed_fields


def test_a_document_line_names_its_expected_quantity():
    assert 'quantity' not in DocumentLineCreate.model_fields
    assert DocumentLineCreate.model_fields['expected_quantity'].is_required()
