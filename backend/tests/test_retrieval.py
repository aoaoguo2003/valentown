"""Unit tests for three-factor memory retrieval. A keyword-based stub embedder
keeps these offline and deterministic (no model download)."""

from memory.memory_system import MemoryRecord
from retrieval import MemoryRetriever, _cosine, _minmax

# Stub embedding space: three independent topic axes.
TOPICS = {
    "food": ("eat", "lunch", "food", "kitchen", "market", "hungry"),
    "social": ("chat", "neighbor", "talk", "friend", "social"),
    "sleep": ("sleep", "rest", "bed", "tired"),
}


class StubEmbedder:
    """Maps text to a 3-d topic vector by keyword presence; truly available."""

    def available(self):
        return True

    def _vector(self, text):
        low = text.lower()
        return [float(any(word in low for word in words)) for words in TOPICS.values()]

    def embed_docs(self, texts):
        return [self._vector(text) for text in texts]

    def embed_query(self, text):
        return self._vector(text)


class UnavailableEmbedder:
    def available(self):
        return False

    def embed_docs(self, texts):
        return None

    def embed_query(self, text):
        return None


def _record(content, importance, life_day):
    return MemoryRecord(content, "action", importance, agent_name="Ron Parker", life_day=life_day)


def test_cosine_and_minmax_basics():
    assert _cosine([1, 0], [1, 0]) == 1.0
    assert _cosine([1, 0], [0, 1]) == 0.0
    assert _minmax([5, 5, 5]) == [0.5, 0.5, 0.5]          # constant -> neutral
    assert _minmax([0, 5, 10]) == [0.0, 0.5, 1.0]


def test_relevance_steers_retrieval_by_topic():
    retriever = MemoryRetriever(embedder=StubEmbedder(), weights=(1.0, 1.0, 1.0))
    records = [
        _record("ate lunch at the kitchen", importance=5, life_day=5),
        _record("chatted with my neighbor", importance=5, life_day=5),
        _record("bought food at the market", importance=5, life_day=5),
    ]

    food_top = retriever.retrieve(records, query="I need to eat some food", current_day=5, top_k=1)
    assert "food" in food_top[0].content or "lunch" in food_top[0].content

    social_top = retriever.retrieve(records, query="I want to chat with a friend", current_day=5, top_k=1)
    assert "neighbor" in social_top[0].content


def test_relevance_weight_lifts_relevant_over_more_recent():
    # Under equal weights the recency edge of the newer memory exactly offsets
    # the relevance edge of the older one (a property of min-max over two items),
    # so they tie. Raising the relevance weight must break that in its favour.
    records = [
        _record("chatted with my neighbor", importance=5, life_day=6),   # most recent, irrelevant
        _record("ate lunch at the kitchen", importance=5, life_day=5),   # older, relevant
    ]

    tie = MemoryRetriever(embedder=StubEmbedder(), weights=(1.0, 1.0, 1.0))
    top_tie = tie.retrieve(records, query="hungry, need food", current_day=6, top_k=1)
    assert "neighbor" in top_tie[0].content  # tie -> stable order keeps the newer one

    relevance_first = MemoryRetriever(embedder=StubEmbedder(), weights=(1.0, 1.0, 3.0))
    top_rel = relevance_first.retrieve(records, query="hungry, need food", current_day=6, top_k=1)
    assert "lunch" in top_rel[0].content  # higher relevance weight surfaces the on-topic memory


def test_falls_back_to_recency_when_embedder_unavailable():
    retriever = MemoryRetriever(embedder=UnavailableEmbedder())
    records = [
        _record("newest", importance=1, life_day=9),
        _record("older", importance=9, life_day=2),
    ]
    top = retriever.retrieve(records, query="anything", current_day=9, top_k=2)
    # Falls back to the incoming newest-first order, ignoring embeddings.
    assert [r.content for r in top] == ["newest", "older"]


def test_empty_records_returns_empty():
    retriever = MemoryRetriever(embedder=StubEmbedder())
    assert retriever.retrieve([], query="x", current_day=1, top_k=5) == []
