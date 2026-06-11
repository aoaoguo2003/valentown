"""Stanford-style three-factor memory retrieval.

Ranks an agent's memories for a given situation by combining three signals,
each min-max normalised across the candidate pool and then weighted:

    score = w_recency * recency + w_importance * importance + w_relevance * relevance

  * recency   : exponential decay over lived days since the memory was formed.
  * importance: the LLM-judged poignancy stored on each memory (1-10).
  * relevance : cosine similarity between the memory and the current query,
                using local embeddings (fastembed, BAAI/bge-small-en-v1.5).

Embeddings are computed locally and cached by memory content. If the embedding
model cannot be loaded, retrieval degrades gracefully to plain recency order so
the simulation never depends on it.
"""

import math

from config import (
    EMBED_MODEL,
    RETRIEVAL_ENABLED,
    RETRIEVAL_RECENCY_DECAY,
    RETRIEVAL_W_IMPORTANCE,
    RETRIEVAL_W_RECENCY,
    RETRIEVAL_W_RELEVANCE,
)


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _minmax(values):
    """Normalise to [0, 1]; a constant factor maps to a neutral 0.5 so it does
    not distort the ranking."""
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5 for _ in values]
    return [(value - lo) / (hi - lo) for value in values]


class FastEmbedder:
    """Lazily-loaded local embedder with a content-keyed cache.

    The model is only loaded on first real embed call, so importing this module
    (and running offline unit tests) never downloads or loads anything."""

    def __init__(self, model_name=EMBED_MODEL):
        self.model_name = model_name
        self._model = None
        self._cache = {}
        self._unavailable = False

    def _ensure_model(self):
        if self._model is not None:
            return True
        if self._unavailable:
            return False
        try:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(self.model_name)
            return True
        except Exception as error:  # noqa: BLE001 - any load failure degrades gracefully
            print(f"Embedder unavailable ({error}); retrieval falls back to recency.")
            self._unavailable = True
            return False

    def available(self):
        return self._ensure_model()

    def embed_docs(self, texts):
        """Embed memory contents, caching by text. Returns vectors or None."""
        missing = [text for text in texts if text not in self._cache]
        if missing:
            if not self._ensure_model():
                return None
            for text, vector in zip(missing, self._model.embed(missing)):
                self._cache[text] = [float(value) for value in vector]
        return [self._cache[text] for text in texts]

    def embed_query(self, text):
        """Embed a one-off situational query (not cached). Returns a vector or None."""
        if not self._ensure_model():
            return None
        vector = next(iter(self._model.embed([text])))
        return [float(value) for value in vector]


class MemoryRetriever:
    def __init__(self, embedder=None, weights=None, decay=RETRIEVAL_RECENCY_DECAY):
        self.embedder = embedder if embedder is not None else FastEmbedder()
        w_recency, w_importance, w_relevance = weights or (
            RETRIEVAL_W_RECENCY,
            RETRIEVAL_W_IMPORTANCE,
            RETRIEVAL_W_RELEVANCE,
        )
        self.w_recency = w_recency
        self.w_importance = w_importance
        self.w_relevance = w_relevance
        self.decay = decay

    def _recency_fallback(self, records, top_k):
        # Records arrive already sorted newest-first from get_memories().
        return list(records[:top_k])

    def retrieve(self, records, query, current_day, top_k=12):
        """Return the top_k records most relevant to ``query`` for ``current_day``."""
        if not records:
            return []
        if not RETRIEVAL_ENABLED or not self.embedder.available():
            return self._recency_fallback(records, top_k)

        doc_vectors = self.embedder.embed_docs([record.content for record in records])
        query_vector = self.embedder.embed_query(query)
        if doc_vectors is None or query_vector is None:
            return self._recency_fallback(records, top_k)

        relevance = [_cosine(query_vector, vector) for vector in doc_vectors]
        recency = [
            self.decay ** max(0, current_day - (record.life_day or current_day))
            for record in records
        ]
        importance = [float(record.importance or 0) for record in records]

        norm_rel = _minmax(relevance)
        norm_rec = _minmax(recency)
        norm_imp = _minmax(importance)

        scored = []
        for index, record in enumerate(records):
            score = (
                self.w_recency * norm_rec[index]
                + self.w_importance * norm_imp[index]
                + self.w_relevance * norm_rel[index]
            )
            scored.append((score, record))

        # Stable sort: ties keep the incoming newest-first order.
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [record for _, record in scored[:top_k]]


# Shared singleton: one embedder/model and cache for the whole process.
retriever = MemoryRetriever()
