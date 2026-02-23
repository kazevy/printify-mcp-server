import pytest
import respx

from src.services.printify import PrintifyService


@pytest.fixture
def printify_api():
    return respx.mock(base_url="https://api.printify.com")


@pytest.fixture
def service():
    return PrintifyService(api_key="test-key", shop_id="12345")
