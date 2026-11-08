"""Тесты работают на временных базах и без нейросети: так они быстрые и воспроизводимые."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["MM_DATA_DIR"] = tempfile.mkdtemp(prefix="mm-tests-")
os.environ["MM_USE_TRANSFORMER"] = "0"
os.environ["MM_COLLECT_INTERVAL_MINUTES"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import seed  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def seeded_database():
    seed.seed(with_synthetic=True)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client
