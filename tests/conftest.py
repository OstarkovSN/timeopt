import pytest
from timeopt.db import get_connection, create_schema


@pytest.fixture
def conn():
    """In-memory SQLite DB with schema, torn down after each test."""
    c = get_connection(":memory:")
    create_schema(c)
    yield c
    c.close()
