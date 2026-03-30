"""Authentication providers for the MCP server using FastMCP's auth system."""

import hmac
import logging

from fastmcp.server.auth.auth import AccessToken, TokenVerifier

logger = logging.getLogger(__name__)


class AuthMode:
    NONE = "none"
    APIKEY = "apikey"
    ENTRA = "entra"


class ApiKeyTokenVerifier(TokenVerifier):
    """Static API key validation via Bearer token."""

    def __init__(self, expected_token: str) -> None:
        super().__init__()
        self.expected_token = expected_token

    async def verify_token(self, token: str) -> AccessToken | None:
        if hmac.compare_digest(token, self.expected_token):
            return AccessToken(token=token, client_id="apikey-client", scopes=[])
        return None


class EntraIdTokenVerifier(TokenVerifier):
    """Microsoft Entra ID JWT validation for Azure deployment.

    Requires PyJWT and cryptography packages (install with `pip install ".[azure]"`).
    """

    def __init__(self, tenant_id: str, client_id: str) -> None:
        super().__init__()
        self.tenant_id = tenant_id
        self.client_id = client_id

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            import jwt
            from jwt import PyJWKClient
        except ImportError:
            logger.error(
                "PyJWT not installed. Install with: pip install 'ms-knowledge-base[azure]'"
            )
            return None

        try:
            jwks_url = (
                f"https://login.microsoftonline.com/{self.tenant_id}"
                "/discovery/v2.0/keys"
            )
            jwks_client = PyJWKClient(jwks_url, cache_keys=True)
            signing_key = jwks_client.get_signing_key_from_jwt(token)

            decoded = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=f"https://login.microsoftonline.com/{self.tenant_id}/v2.0",
            )
            return AccessToken(
                token=token,
                client_id=decoded.get("azp", "entra-client"),
                scopes=decoded.get("scp", "").split(),
            )
        except Exception as e:
            logger.warning("Entra ID token validation failed: %s", e)
            return None


def create_auth_provider(
    mode: str,
    api_key: str | None = None,
    tenant_id: str | None = None,
    client_id: str | None = None,
) -> TokenVerifier | None:
    """Factory for auth providers based on deployment mode."""
    if mode == AuthMode.NONE:
        return None
    elif mode == AuthMode.APIKEY:
        if not api_key:
            raise ValueError("--auth-token required for apikey auth mode")
        return ApiKeyTokenVerifier(api_key)
    elif mode == AuthMode.ENTRA:
        if not tenant_id or not client_id:
            raise ValueError("--tenant-id and --client-id required for entra auth mode")
        return EntraIdTokenVerifier(tenant_id, client_id)
    else:
        raise ValueError(f"Unknown auth mode: {mode}")
