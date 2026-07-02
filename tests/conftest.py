from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def manual_text() -> str:
    return (FIXTURES / "manual_excerpt.txt").read_text()
