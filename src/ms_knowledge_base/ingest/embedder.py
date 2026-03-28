"""Sentence-transformers embedding wrapper."""

from sentence_transformers import SentenceTransformer


class Embedder:
    """Wraps a sentence-transformers model for single and batch encoding."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        """Load the sentence-transformers model (CPU only)."""
        self.model = SentenceTransformer(model_name, device="cpu")

    def embed_text(self, text: str) -> list[float]:
        """Embed a single text string. Used for queries."""
        embedding = self.model.encode(text, normalize_embeddings=True)
        return embedding.tolist()

    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """Embed multiple texts efficiently. Used for ingestion."""
        embeddings = self.model.encode(
            texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False
        )
        return [e.tolist() for e in embeddings]
