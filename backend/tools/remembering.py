"""主动检索自己的记忆。

改造前记忆是**被动注入**的：每次决策都盲目塞进最相关的若干条，不管这次
用不用得上。这里把它变成模型**主动发起**的查询——由模型自己判断"这件事
需要回想吗、该回想什么"。
"""

from tools.base import THOUGHT_FIELD, accept, reject


# --- recall：不占用游戏时间，属于决定之前的准备动作 -----------------

RECALL_PARAMETERS = {
    "type": "object",
    "properties": {
        "thought": THOUGHT_FIELD,
        "query": {
            "type": "string",
            "description": (
                "What you are trying to remember, in a few words. "
                "For example: 'Adam being ill', 'my last talk with Ella'."
            ),
        },
    },
    "required": ["thought", "query"],
}

RECALL_LIMIT = 8


def handle_recall(agent, args, world=None):
    """按查询词检索自己的自传式记忆。

    改造前记忆是**被动注入**的：每次决策都盲目塞进最相关的 12 条，
    不管这次决策用不用得上。这里把它变成模型**主动发起**的查询——
    模型自己判断"这件事我需要回想吗、该回想什么"。

    两个收益：不需要记忆的决策不再白付那部分 token；而"决定查什么"
    这个判断本身，就是单步反应式 agent 做不到的事。

    查不到东西是正常结果而不是失败：空手而归也是一条有效的
    observation，模型据此就该停止翻记忆、改用别的办法。
    """
    query = str((args or {}).get("query") or "").strip()
    if not query:
        return reject("empty_query", "You did not say what you were trying to remember.")

    records = agent.memory.get_memories(agent_name=agent.name)
    if not records:
        return accept(f"You try to recall {query!r}, but nothing comes to mind.", memories=[])

    from memory.retrieval import retriever

    top = retriever.retrieve(
        records,
        query=query,
        current_day=agent.memory.current_life_day,
        top_k=RECALL_LIMIT,
    )
    if not top:
        return accept(f"You try to recall {query!r}, but nothing comes to mind.", memories=[])

    lines = [record.content for record in top]
    body = "\n".join(f"- {line}" for line in lines)
    return accept(f"Thinking back on {query!r}, you remember:\n{body}", memories=lines)
