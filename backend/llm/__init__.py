"""模型客户端：这个项目和大模型之间唯一的接触面。

```
client.py   OpenAI 兼容接口：多工具选择、自由文本、重要性打分、重试退避
```

所有请求都汇到 ``_post_with_retries`` 一个出口，追踪日志和
``thinking: disabled`` 都在那里统一注入——DeepSeek v4 的思考模式会拒绝
任何 ``tool_choice``（HTTP 400）。
"""

from llm.client import LLMClient  # noqa: F401  （re-export）

__all__ = ["LLMClient"]
