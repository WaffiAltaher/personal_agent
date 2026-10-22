import httplib2
import pytest
from googleapiclient.errors import HttpError
from agent.graph import _should_retry


@pytest.mark.parametrize("status, transient", [
    (429, True), (500, True), (502, True), (503, True),
    (400, False), (401, False), (403, False), (404, False),
])
def test_only_429_and_5xx_http_errors_are_transient(status, transient):
    error = HttpError(httplib2.Response({"status": str(status)}), b"")
    assert _should_retry(error) is transient
