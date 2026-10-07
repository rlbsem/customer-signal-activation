import pytest

from signals.fixtures import seed
from signals.harness import serve
from signals.remote import app
from signals.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "local.sqlite")
    seed(s, 12)
    return s


@pytest.fixture
def remote(tmp_path):
    path = tmp_path / "remote.sqlite"
    with serve(app(path)) as url:
        yield path, url
