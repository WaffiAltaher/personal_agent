# src/agent/tools/transient.py
"""
Which tool failures are transient: worth retrying, because waiting may fix them.

A local tool returns "Error: ..." for a failure the model should read and act on, but raises a
transient one (`if is_transient(e): raise`), so the graph's retry (agent.graph.retry_tool_call)
sees it: a read is retried with backoff, a Write action is reported as "may have gone through".
"""

from googleapiclient.errors import HttpError


def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True  # network-level blips
    if isinstance(exc, HttpError):
        # 429 Too Many Requests and 5xx server errors are transient.
        # 4xx (except 429) are permanent — wrong credentials, not found, etc.
        return exc.status_code == 429 or exc.status_code >= 500
    return False
