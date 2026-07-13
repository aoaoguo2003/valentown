"""斯坦福风格的三因子记忆检索。

针对给定情境，通过组合三个信号来为 agent 的记忆排序，每个信号都会先在
候选池中做 min-max 归一化，再按权重加总：

    score = w_recency * recency + w_importance * importance + w_relevance * relevance

  * recency（近因性）：自记忆形成以来经过的天数的指数衰减。
  * importance（重要性）：每条记忆上由 LLM 判定并存储的重要程度评分（1-10）。
  * relevance（相关性）：记忆内容与当前查询之间的余弦相似度，
                使用本地 embedding 模型计算（fastembed，BAAI/bge-small-en-v1.5）。

Embedding 在本地计算，并按记忆内容做缓存。如果 embedding 模型无法加载，
检索会优雅降级为按近因性排序，确保模拟不会对其产生硬依赖。
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
    """归一化到 [0, 1] 区间；如果所有值都相同，则统一映射为中性值 0.5，
    以避免影响排序结果。"""
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5 for _ in values]
    return [(value - lo) / (hi - lo) for value in values]


class FastEmbedder:
    """按需惰性加载的本地 embedder，并带有以内容为键的缓存。

    模型只有在第一次真正调用 embed 时才会被加载，因此仅导入本模块
    （例如运行离线单元测试时）不会触发任何下载或加载行为。"""

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
        except Exception as error:  # noqa: BLE001 - 任何加载失败都应优雅降级
            print(f"Embedder unavailable ({error}); retrieval falls back to recency.")
            self._unavailable = True
            return False

    def available(self):
        return self._ensure_model()

    def embed_docs(self, texts):
        """对记忆内容做 embedding，并按文本缓存。返回向量列表，或在失败时返回 None。"""
        missing = [text for text in texts if text not in self._cache]
        if missing:
            if not self._ensure_model():
                return None
            for text, vector in zip(missing, self._model.embed(missing)):
                self._cache[text] = [float(value) for value in vector]
        return [self._cache[text] for text in texts]

    def embed_query(self, text):
        """对一次性的情境查询做 embedding（不缓存）。返回一个向量，或在失败时返回 None。"""
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
        # records 从 get_memories() 传入时已经按最新优先的顺序排好。
        return list(records[:top_k])

    def retrieve(self, records, query, current_day, top_k=12):
        """返回与 ``query`` 在 ``current_day`` 情境下最相关的 top_k 条记录。"""
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

        # 稳定排序：分数相同的记录保持传入时的最新优先顺序。
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [record for _, record in scored[:top_k]]


# 共享单例：整个进程使用同一个 embedder/模型实例和缓存。
retriever = MemoryRetriever()
