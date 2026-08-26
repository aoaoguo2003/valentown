import json
import re
import time

import requests

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from observability import log_llm_call

# 值得用指数退避重试的临时性 HTTP 状态码。
RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504, 529}
MAX_RETRIES = 4
BASE_BACKOFF_SECONDS = 2

# 账户和配置层面的故障。这些**不会自己好**：密钥不对、余额没了、权限不够，
# 再打一万次也是一样的答案。
#
# 天气那边早就有熔断了，这边一直没有，代价是真金白银：一次评估跑到一半
# 账户余额见底（HTTP 402），系统又老老实实打了 1927 次注定失败的请求，
# 空转了将近一小时，还产出了一张三十格全是"模型很差"的记分卡——
# 而真相是后端没钱了。
FATAL_STATUS_CODES = {401, 402, 403}

# DeepSeek v4 系列默认开启思考模式，而思考模式会拒绝任何形式的 tool_choice
# （返回 HTTP 400），本项目的结构化决策恰恰依赖强制函数调用。关掉它同时也
# 省去了这个场景用不上的推理 token 计费。
# 这属于接口兼容性参数而非业务参数，因此在统一出口注入；调用方仍可通过在
# payload 中显式传入 thinking 来覆盖。
THINKING_DISABLED = {"type": "disabled"}


class LLMClient:
    """适用于任意兼容 OpenAI 接口的对话客户端（默认使用 DeepSeek）。

    支持用于对话/反思的纯文本回复，以及用于结构化决策
    （下一步行动规划）的强制函数调用。
    """

    # 账户级故障是**进程级**的：换个居民、换座小镇、换道题都不会好。
    # 所以熔断也开在类上，而不是每个实例各记各的——七个居民各持有一个
    # 客户端，实例级的熔断等于要各自撞一次墙才生效。
    #
    # ⚠️ 熔断之后仍然返回 None 而不是抛异常：线上那条路必须保持
    # "模型不可用就走确定性兜底"，模拟不能卡住。批量跑的那条路
    # （dry_run / evals）自己去读 ``fatal_error`` 决定要不要停。
    fatal_error = None

    @classmethod
    def clear_fatal_error(cls):
        """测试和"充值之后接着跑"用。"""
        cls.fatal_error = None

    def __init__(self):
        self.api_key = LLM_API_KEY
        self.base_url = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"
        self.model = LLM_MODEL
        # 上一次调用花了多少 token。预算只能**事后**记账——花了多少要等
        # 接口回来才知道。
        # ⚠️ 挂在**实例**上：每个居民各持一个客户端，一次决策只在一个线程
        # 里跑，所以不会串。挂类上就会被并发的另一个居民覆盖。
        self.last_usage = {}

    def _build_messages(self, agent_name, context, memory=None):
        memory_context = ""
        if memory:
            memory_context = "\n\nRelevant memory:\n" + "\n".join(f"- {mem}" for mem in memory)
        return [
            {
                "role": "system",
                "content": f"You are {agent_name}, a character in a multi-agent virtual town simulation."
            },
            {
                "role": "user",
                "content": f"{context}{memory_context}"
            }
        ]

    def _post_with_retries(self, agent_name, payload):
        """发送请求体，对临时性失败进行重试；返回第一个候选的
        message 字典，若请求最终失败则返回 None。

        每种结果（成功、空、失败、跳过）都会通过 ``log_llm_call``
        记录为结构化追踪日志。"""
        payload.setdefault("thinking", THINKING_DISABLED)
        call_kind = "tool" if payload.get("tools") else "text"

        if LLMClient.fatal_error:
            # 熔断已开：不再白打注定失败的请求。仍然记一条日志，
            # 否则"这一格为什么全是兜底"在追踪文件里查无对证。
            log_llm_call({
                "agent_name": agent_name,
                "call_kind": call_kind,
                "model": payload.get("model"),
                "status": "circuit_open",
                "error": LLMClient.fatal_error,
                "attempts": 0,
                "latency_ms": 0,
            })
            return None

        if not self.api_key:
            print("LLM_API_KEY is not set. Skipping LLM request.")
            log_llm_call({
                "agent_name": agent_name,
                "call_kind": call_kind,
                "model": payload.get("model"),
                "prompt": payload.get("messages"),
                "status": "skipped",
                "error": "no_api_key",
                "attempts": 0,
                "latency_ms": 0,
            })
            return None

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        last_error = None
        last_status = None
        usage = None
        message = None
        status = "failed"
        attempts = 0
        started = time.monotonic()

        for attempt in range(MAX_RETRIES):
            attempts = attempt + 1
            try:
                response = requests.post(self.base_url, headers=headers, json=payload, timeout=60)
                last_status = response.status_code
                if response.status_code == 200:
                    body = response.json()
                    usage = body.get("usage") or {}
                    choices = body.get("choices") or []
                    message = (choices[0].get("message") if choices else None) or None
                    status = "success" if message else "empty"
                    break

                last_error = f"status {response.status_code}: {response.text}"
                if response.status_code in FATAL_STATUS_CODES:
                    LLMClient.fatal_error = last_error
                    print(f"\n!! LLM 不可用，而且不会自己好：{last_error}")
                    print("   已拉闸，后续请求不再发出。\n")
                    break
                if response.status_code not in RETRYABLE_STATUS_CODES:
                    break
            except requests.RequestException as error:
                last_error = str(error)

            if attempt < MAX_RETRIES - 1:
                backoff = BASE_BACKOFF_SECONDS * (2 ** attempt)
                print(f"LLM request transient failure ({last_error}); retrying in {backoff}s.")
                time.sleep(backoff)

        latency_ms = int((time.monotonic() - started) * 1000)

        response_for_log = None
        if message is not None:
            if call_kind == "tool":
                tool_calls = message.get("tool_calls") or []
                response_for_log = tool_calls[0].get("function", {}).get("arguments") if tool_calls else None
            else:
                response_for_log = message.get("content")

        log_llm_call({
            "agent_name": agent_name,
            "call_kind": call_kind,
            "model": payload.get("model"),
            "prompt": payload.get("messages"),
            "response": response_for_log,
            "status": status,
            "http_status": last_status,
            "attempts": attempts,
            "latency_ms": latency_ms,
            "prompt_tokens": (usage or {}).get("prompt_tokens"),
            "completion_tokens": (usage or {}).get("completion_tokens"),
            "total_tokens": (usage or {}).get("total_tokens"),
            "error": None if status == "success" else last_error,
        })
        self.last_usage = dict(usage or {})

        if status == "failed":
            print(f"LLM request failed after {attempts} attempt(s): {last_error}")
        return message  # 成功时返回 message 字典；失败/为空时返回 None

    def rate_importance(self, agent_name, memory_text, fallback=4):
        """按 1-10 分制评估一段记忆有多深刻/重要。

        日常琐事（吃饭、走去另一个房间）得分低；情感上或社交上
        重要的事件（一次推心置腹的谈话、一次冲突、一个里程碑）得分高。
        返回整数分数；若 LLM 不可用或回复无法解析，则返回 ``fallback``。"""
        context = (
            "On a scale of 1 to 10, rate how poignant the following memory is. "
            "1 is purely mundane (brushing teeth, walking to another room, a "
            "routine meal); 10 is extremely significant (a heartfelt or tense "
            "conversation, a conflict, a milestone, a strong emotional moment).\n"
            f"Memory: \"{memory_text}\"\n"
            "Respond with a single integer from 1 to 10 and nothing else."
        )
        reply = self.get_response(agent_name, context)
        if not reply:
            return fallback
        match = re.search(r"\d+", reply)
        if not match:
            return fallback
        return max(1, min(10, int(match.group())))

    def get_response(self, agent_name, context, memory=None):
        """自由文本补全，用于对话和反思。"""
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "temperature": 0.8,
            "messages": self._build_messages(agent_name, context, memory)
        }
        message = self._post_with_retries(agent_name, payload)
        if not message:
            return None
        return (message.get("content") or "").strip() or None

    def call_tools(self, agent_name, context, tool_schemas, memory=None):
        """让模型从一组工具里**自己挑一个**调用，返回 ``{"name", "args"}``。

        ``tool_choice`` 用 ``"required"``：必须调用某个工具，但**选哪个由
        模型决定**。改造前这里写死成 ``{"type": "function", "name": "move_to"}``，
        模型只是在填一张表——"选择工具"这个动作根本不存在。那条单步老路
        连同挂在它上面的旧评估已经一起删掉了，现在只剩这一条决策路径。

        注意 DeepSeek 的思考模式会拒绝任何 tool_choice，所以本类统一在
        ``_post_with_retries`` 里关掉了思考模式（见 THINKING_DISABLED）。
        """
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "temperature": 0.7,
            "messages": self._build_messages(agent_name, context, memory),
            "tools": tool_schemas,
            "tool_choice": "required"
        }
        message = self._post_with_retries(agent_name, payload)
        if not message:
            return None

        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            return None

        function = tool_calls[0].get("function", {})
        name = function.get("name")
        if not name:
            return None

        try:
            args = json.loads(function.get("arguments") or "{}")
        except json.JSONDecodeError:
            print(f"LLM tool call returned malformed JSON arguments: {function.get('arguments')!r}")
            return None
        return {"name": name, "args": args if isinstance(args, dict) else {}}
