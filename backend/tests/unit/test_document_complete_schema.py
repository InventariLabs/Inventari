from app.modules.warehouse.schemas import DocumentComplete


def test_a_confirmation_alone_is_a_valid_completion_body() -> None:
    body = DocumentComplete(unit_confirmed_over_template=True)

    assert body.lines == []
    assert body.unit_confirmed_over_template is True
