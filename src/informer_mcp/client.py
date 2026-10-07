# src/informer_mcp/client.py
"""Thin async HTTP client for Informer API v2."""

import httpx

from informer_mcp.config import InformerSettings


class InformerError(Exception):
    """An Informer API failure, worded for the MCP client (and the model) to read."""


class InformerClient:
    def __init__(self, settings: InformerSettings):
        self._settings = settings

    async def get(self, path: str, params: dict | None = None) -> dict:
        headers = {
            "Apikey": self._settings.api_key,
            "Securitycode": self._settings.security_code,
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(base_url=self._settings.base_url, headers=headers, timeout=30) as http:
            response = await http.get(path, params=params)
        if response.status_code == 401:
            raise InformerError(
                "Informer rejected the credentials (HTTP 401). "
                "Check the INFORMER_API_KEY and INFORMER_SECURITY_CODE settings "
                f"(and INFORMER_BASE_URL, currently {self._settings.base_url})."
            )
        if response.is_error:
            raise InformerError(f"Informer returned HTTP {response.status_code} for {path}: {_error_text(response)}")
        return response.json()


def _error_text(response: httpx.Response) -> str:
    try:
        error = response.json().get("error")
    except ValueError:
        return response.text
    return "; ".join(error) if isinstance(error, list) else str(error)
