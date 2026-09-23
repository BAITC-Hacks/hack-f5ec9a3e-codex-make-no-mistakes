import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def app(request):
    from evaluation.contracts import load_app

    calculate = load_app()
    if calculate is None:
        if request.config.getoption("--require-app"):
            pytest.fail("app_not_implemented")
        pytest.skip("app_not_implemented")
    return calculate
