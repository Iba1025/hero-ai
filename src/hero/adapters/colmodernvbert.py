"""ColModernVBERT embedder — real Embedder Protocol implementation (DEC-2).

Uses colpali-engine's ColModernVBert model for multi-vector patch embeddings.
Small (~250M params), CPU-viable. Default dev model per spec §1.

Model download: first run downloads ~500MB from HuggingFace Hub.
Cache: uses HF_HOME / TRANSFORMERS_CACHE env vars (default ~/.cache/huggingface).
"""

from __future__ import annotations

import io
from typing import Any

import torch
from colpali_engine.models import ColModernVBert, ColModernVBertProcessor
from PIL import Image


class ColModernVBertEmbedder:
    """Embedder Protocol implementation using ColModernVBert.

    Produces multi-vector (late-interaction) patch embeddings for page images
    and queries, compatible with Qdrant MaxSim multivector collections.
    """

    model_id: str = "ModernVBERT/colmodernvbert"

    def __init__(
        self,
        model_name: str = "ModernVBERT/colmodernvbert",
        device: str | None = None,
    ) -> None:
        self.model_id = model_name
        self._device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._model: Any = (
            ColModernVBert.from_pretrained(
                model_name,
                torch_dtype=torch.float32 if self._device == "cpu" else torch.float16,
            )
            .to(self._device)
            .eval()
        )
        self._processor: Any = ColModernVBertProcessor.from_pretrained(model_name)

    def embed_page(self, image: bytes) -> list[list[float]]:
        """Multi-vector patch embeddings for a page image."""
        pil_image = Image.open(io.BytesIO(image)).convert("RGB")
        return self._embed_images([pil_image])[0]

    def embed_pages_batch(self, images: list[bytes]) -> list[list[list[float]]]:
        """Batch embed multiple page images. Used by ingestion."""
        pil_images = [Image.open(io.BytesIO(img)).convert("RGB") for img in images]
        return self._embed_images(pil_images)

    def embed_query(self, text: str) -> list[list[float]]:
        """Multi-vector query embeddings."""
        inputs = self._processor.process_queries([text]).to(self._device)
        with torch.no_grad():
            outputs = self._model(**inputs)
        # Shape: (1, num_tokens, embed_dim) → list of vectors
        vectors = outputs[0].cpu().float().tolist()
        return vectors  # type: ignore[no-any-return]

    def _embed_images(self, pil_images: list[Any]) -> list[list[list[float]]]:
        """Embed a batch of PIL images → list of multi-vector embeddings."""
        inputs = self._processor.process_images(pil_images).to(self._device)
        with torch.no_grad():
            outputs = self._model(**inputs)
        # Shape: (batch, num_patches, embed_dim)
        result: list[list[list[float]]] = []
        for i in range(len(pil_images)):
            vectors = outputs[i].cpu().float().tolist()
            result.append(vectors)
        return result
