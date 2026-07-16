"""Shared response-schema tests."""

import pytest
from pydantic import ValidationError

from app.schemas.common import CountResponse, PaginatedResponse
from app.schemas.customer import CustomerSummary


def test_typed_paginated_response(graph):
    page = PaginatedResponse[CustomerSummary](
        items=[graph.customer],
        total=1,
        limit=20,
        offset=0,
    )

    assert isinstance(page.items[0], CustomerSummary)
    assert page.total == 1


@pytest.mark.parametrize(
    "values",
    [
        {"items": [], "total": -1, "limit": 20, "offset": 0},
        {"items": [], "total": 0, "limit": 0, "offset": 0},
        {"items": [], "total": 0, "limit": 20, "offset": -1},
    ],
)
def test_pagination_rejects_invalid_metadata(values):
    with pytest.raises(ValidationError):
        PaginatedResponse[CustomerSummary](**values)


def test_count_response_validation():
    assert CountResponse(count=0).count == 0
    with pytest.raises(ValidationError):
        CountResponse(count=-1)
