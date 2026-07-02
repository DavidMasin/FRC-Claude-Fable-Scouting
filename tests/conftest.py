from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def manual_text() -> str:
    return (FIXTURES / "manual_excerpt.txt").read_text()


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class FakeSession:
    """Maps URL substrings to responses; records every request it serves."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.requests: list[dict] = []

    def get(self, url, **kwargs):
        self.requests.append({"url": url, **kwargs})
        for fragment, response in self.routes.items():
            if fragment in url:
                return response
        return FakeResponse(status_code=404)


@pytest.fixture
def fake_session_cls():
    return FakeSession


@pytest.fixture
def fake_response_cls():
    return FakeResponse
