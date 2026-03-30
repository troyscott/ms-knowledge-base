"""Tests for MCP server authentication."""

import asyncio
import random

import pytest

from ms_knowledge_base.server.auth import (
    ApiKeyTokenVerifier,
    AuthMode,
    create_auth_provider,
)


# --- Unit tests for ApiKeyTokenVerifier ---


class TestApiKeyTokenVerifier:
    """Unit tests for API key token verification."""

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_valid_token_returns_access_token(self):
        verifier = ApiKeyTokenVerifier("secret-key-123")
        result = self._run(verifier.verify_token("secret-key-123"))
        assert result is not None
        assert result.token == "secret-key-123"
        assert result.client_id == "apikey-client"

    def test_invalid_token_returns_none(self):
        verifier = ApiKeyTokenVerifier("secret-key-123")
        result = self._run(verifier.verify_token("wrong-key"))
        assert result is None

    def test_empty_token_returns_none(self):
        verifier = ApiKeyTokenVerifier("secret-key-123")
        result = self._run(verifier.verify_token(""))
        assert result is None

    def test_similar_token_returns_none(self):
        verifier = ApiKeyTokenVerifier("secret-key-123")
        result = self._run(verifier.verify_token("secret-key-124"))
        assert result is None


# --- Unit tests for create_auth_provider factory ---


class TestCreateAuthProvider:
    """Unit tests for the auth provider factory."""

    def test_none_mode_returns_none(self):
        result = create_auth_provider("none")
        assert result is None

    def test_apikey_mode_returns_verifier(self):
        result = create_auth_provider("apikey", api_key="my-key")
        assert isinstance(result, ApiKeyTokenVerifier)

    def test_apikey_mode_requires_token(self):
        with pytest.raises(ValueError, match="--auth-token required"):
            create_auth_provider("apikey")

    def test_entra_mode_requires_ids(self):
        with pytest.raises(ValueError, match="--tenant-id and --client-id"):
            create_auth_provider("entra")

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="Unknown auth mode"):
            create_auth_provider("unknown")


# --- Integration tests: SSE endpoint with auth ---


class MockEmbedder:
    """Mock embedder for auth integration tests."""

    def embed_text(self, text: str) -> list[float]:
        rng = random.Random(hash(text))
        vec = [rng.gauss(0, 1) for _ in range(384)]
        norm = sum(v * v for v in vec) ** 0.5
        return [v / norm for v in vec]

    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        return [self.embed_text(t) for t in texts]


@pytest.fixture
def auth_server(tmp_path):
    """Create a FastMCP server with API key auth enabled."""
    from ms_knowledge_base.db.schema import initialize_db
    from ms_knowledge_base.server.main import create_server

    db_path = tmp_path / "test.db"
    initialize_db(db_path)
    auth = ApiKeyTokenVerifier("test-secret")
    return create_server(db_path, MockEmbedder(), auth=auth)


@pytest.fixture
def noauth_server(tmp_path):
    """Create a FastMCP server with no auth."""
    from ms_knowledge_base.db.schema import initialize_db
    from ms_knowledge_base.server.main import create_server

    db_path = tmp_path / "test.db"
    initialize_db(db_path)
    return create_server(db_path, MockEmbedder(), auth=None)


def _make_client(app):
    """Create an httpx async client for an ASGI app."""
    import httpx

    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_sse_rejects_no_auth(auth_server):
    """SSE endpoint should return 401 without auth header."""
    app = auth_server.http_app(transport="sse")
    async with _make_client(app) as client:
        resp = await client.get("/sse")
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_sse_rejects_wrong_token(auth_server):
    """SSE endpoint should return 401 with wrong Bearer token."""
    app = auth_server.http_app(transport="sse")
    async with _make_client(app) as client:
        resp = await client.get(
            "/sse", headers={"Authorization": "Bearer wrong-token"}
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_sse_accepts_valid_token(auth_server):
    """SSE endpoint should not reject a valid Bearer token.

    We test the /messages/ POST endpoint instead of /sse GET because
    the SSE endpoint opens a persistent stream that hangs in ASGI tests.
    A 405/400 response (not 401) proves the auth layer accepted the token.
    """
    app = auth_server.http_app(transport="sse")
    async with _make_client(app) as client:
        resp = await client.post(
            "/messages/",
            headers={"Authorization": "Bearer test-secret"},
            content="{}",
        )
        # Any response other than 401 means auth passed
        assert resp.status_code != 401


@pytest.mark.asyncio
async def test_noauth_server_allows_all(noauth_server):
    """Server without auth should allow unauthenticated access to messages."""
    app = noauth_server.http_app(transport="sse")
    async with _make_client(app) as client:
        resp = await client.post("/messages/", content="{}")
        assert resp.status_code != 401
