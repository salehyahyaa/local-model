"""Runs bge-small with fastembed. Only the worker process imports this, so the app itself never holds the model."""

from fastembed import TextEmbedding

from src.backend.models.embeddings import MODEL_NAME

BATCH_SIZE = 32


def embed(texts, cache_dir):
    """The model file is downloaded into cache_dir the first time, then read from there."""
    model = TextEmbedding(MODEL_NAME, cache_dir=str(cache_dir))
    return [[float(number) for number in vector] for vector in model.embed(texts, batch_size=BATCH_SIZE)]
