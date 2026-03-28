"""Authentication middleware for the MCP server."""

import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class AuthMode:
    NONE = "none"
    APIKEY = "apikey"
    ENTRA = "entra"


class ApiKeyMiddleware:
    """Simple Bearer token validation for testing/staging."""

    def __init__(self, expected_token: str) -> None:
        self.expected_token = expected_token

    def validate(self, request: Any) -> bool:
        auth_header = request.headers.get("Authorization", "")
        return auth_header == f"Bearer {self.expected_token}"


class EntraIdMiddleware:
    """Microsoft Entra ID JWT validation for Azure deployment.

    Requires PyJWT and cryptography packages (install with `pip install ".[azure]"`).
    """

    def __init__(self, tenant_id: str, client_id: str) -> None:
        self.tenant_id = tenant_id
        self.client_id = client_id
        self._jwks_cache: dict | None = None
        self._jwks_fetched_at: float = 0
        self._jwks_ttl: float = 86400  # 24 hours

    def validate(self, request: Any) -> bool:
        """Validate JWT from Authorization: Bearer <token> header."""
        try:
            import jwt
            from jwt import PyJWKClient
        except ImportError:
            logger.error(
                "PyJWT not installed. Install with: pip install 'ms-knowledge-base[azure]'"
            )
            return False

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return False

        token = auth_header[7:]

        try:
            jwks_client = self._get_jwks_client()
            signing_key = jwks_client.get_signing_key_from_jwt(token)

            decoded = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=f"https://login.microsoftonline.com/{self.tenant_id}/v2.0",
            )
            return True
        except Exception as e:
            logger.warning("Entra ID token validation failed: %s", e)
            return False

    def _get_jwks_client(self):
        from jwt import PyJWKClient

        jwks_url = (
            f"https://login.microsoftonline.com/{self.tenant_id}"
            "/discovery/v2.0/keys"
        )
        return PyJWKClient(jwks_url, cache_keys=True)


def create_auth_middleware(
    mode: str,
    api_key: str | None = None,
    tenant_id: str | None = None,
    client_id: str | None = None,
) -> ApiKeyMiddleware | EntraIdMiddleware | None:
    """Factory for auth middleware based on deployment mode."""
    if mode == AuthMode.NONE:
        return None
    elif mode == AuthMode.APIKEY:
        if not api_key:
            raise ValueError("--auth-token required for apikey auth mode")
        return ApiKeyMiddleware(api_key)
    elif mode == AuthMode.ENTRA:
        if not tenant_id or not client_id:
            raise ValueError("--tenant-id and --client-id required for entra auth mode")
        return EntraIdMiddleware(tenant_id, client_id)
    else:
        raise ValueError(f"Unknown auth mode: {mode}")
