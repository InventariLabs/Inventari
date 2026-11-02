"""The in-memory page builder, which keeps ``total`` honest.

A list that stays small is read whole by its service and sliced by the
endpoint. The page must report the count of *all* rows and the position of
*this* page, not the length of the slice — a screen that says "51-100 of 300"
reads those two numbers.
"""

from __future__ import annotations

from app.schemas.pagination import PaginatedResponse


class TestFromFullList:
    def test_the_first_page_reports_the_total_and_has_more(self):
        page = PaginatedResponse[int].from_full_list(
            list(range(300)), offset=0, limit=50
        )

        assert page.items == list(range(50))
        assert page.total == 300
        assert page.offset == 0
        assert page.limit == 50
        assert page.has_more is True

    def test_a_deep_page_slices_at_the_offset(self):
        page = PaginatedResponse[int].from_full_list(
            list(range(300)), offset=250, limit=100
        )

        assert page.items == list(range(250, 300))
        assert page.total == 300
        assert page.offset == 250
        assert page.has_more is False

    def test_the_last_full_page_has_no_more(self):
        page = PaginatedResponse[int].from_full_list(
            list(range(100)), offset=50, limit=50
        )

        assert page.has_more is False
        assert page.total == 100

    def test_an_offset_past_the_end_answers_an_empty_page(self):
        page = PaginatedResponse[int].from_full_list([1, 2, 3], offset=10, limit=5)

        assert page.items == []
        assert page.total == 3
        assert page.has_more is False

    def test_an_empty_list(self):
        page = PaginatedResponse[int].from_full_list([], offset=0, limit=50)

        assert page.items == []
        assert page.total == 0
        assert page.has_more is False
