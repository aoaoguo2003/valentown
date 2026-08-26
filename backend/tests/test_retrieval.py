"""三因子记忆检索的单元测试。使用基于关键词的桩（stub）嵌入器，
使测试保持离线且结果确定（无需下载模型）。"""

from memory.memory_system import MemoryRecord
from memory.retrieval import MemoryRetriever, _cosine, _minmax

# 桩嵌入空间：三个相互独立的主题轴。
TOPICS = {
    "food": ("eat", "lunch", "food", "kitchen", "market", "hungry"),
    "social": ("chat", "neighbor", "talk", "friend", "social"),
    "sleep": ("sleep", "rest", "bed", "tired"),
}


class StubEmbedder:
    """根据关键词是否出现，将文本映射为一个三维主题向量；始终视为可用。"""

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
    assert _minmax([5, 5, 5]) == [0.5, 0.5, 0.5]          # 恒定值 -> 中性结果
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
    # 在权重相等的情况下，较新记忆在“近期性”上的优势恰好被较旧记忆在
    # “相关性”上的优势抵消（这是对两条记录做 min-max 归一化时的特性），
    # 因此二者打平。提高相关性权重必须打破这种平局，使相关的一方胜出。
    records = [
        _record("chatted with my neighbor", importance=5, life_day=6),   # 最新，但不相关
        _record("ate lunch at the kitchen", importance=5, life_day=5),   # 较旧，但相关
    ]

    tie = MemoryRetriever(embedder=StubEmbedder(), weights=(1.0, 1.0, 1.0))
    top_tie = tie.retrieve(records, query="hungry, need food", current_day=6, top_k=1)
    assert "neighbor" in top_tie[0].content  # 打平时 -> 稳定排序保留较新的一条

    relevance_first = MemoryRetriever(embedder=StubEmbedder(), weights=(1.0, 1.0, 3.0))
    top_rel = relevance_first.retrieve(records, query="hungry, need food", current_day=6, top_k=1)
    assert "lunch" in top_rel[0].content  # 更高的相关性权重使主题相符的记忆胜出


def test_falls_back_to_recency_when_embedder_unavailable():
    retriever = MemoryRetriever(embedder=UnavailableEmbedder())
    records = [
        _record("newest", importance=1, life_day=9),
        _record("older", importance=9, life_day=2),
    ]
    top = retriever.retrieve(records, query="anything", current_day=9, top_k=2)
    # 回退为按传入顺序的“最新优先”排序，忽略嵌入向量。
    assert [r.content for r in top] == ["newest", "older"]


def test_empty_records_returns_empty():
    retriever = MemoryRetriever(embedder=StubEmbedder())
    assert retriever.retrieve([], query="x", current_day=1, top_k=5) == []
