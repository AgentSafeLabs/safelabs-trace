import pytest

from safelabs_trace.writer import TraceWriter
from tests.helpers import SALT


@pytest.fixture
def writer(tmp_path):
    return TraceWriter(tmp_path / "run.jsonl", salt=SALT)
