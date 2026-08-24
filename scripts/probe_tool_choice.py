#!/usr/bin/env python3
"""探针：体检当前 LLM 接口，并验证 Agent loop 改造所需的多工具选择能力。

背景（2026 年上游的两处变化，都直接影响本项目）：

1. 旧模型别名 ``deepseek-chat`` / ``deepseek-reasoner`` 已于 2026-07-24
   停止解析，迁移目标是 ``deepseek-v4-flash``。

2. ``deepseek-v4-flash`` 默认开启思考模式，而思考模式会以 HTTP 400 拒绝
   任何形式的 tool_choice——包括本项目迁移前使用的指定函数形式。关闭方式
   是在请求体里传 ``"thinking": {"type": "disabled"}``。

脚本按顺序回答三个问题：

  第一部分  哪些模型名还能解析？
  第二部分  各种 tool_choice 在思考模式开/关下分别是什么结果？
            （包含 llm.py 实际发送的那一种，用来确认决策路径是真的健康，
            而不是在静默降级到确定性兜底。）
  第三部分  给若干工具时，模型选得对不对、thought 字段稳不稳定？
            这决定 Agent loop 的多工具选择那一步是否成立。

用法：
    python scripts/probe_tool_choice.py

会自动读取 backend/.env；不改动仓库任何状态，总消耗约一两千 token。
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

# 与 config.py 一样读取 backend/.env，这样探针直接复用仓库自身的配置，
# 不需要另外导出环境变量。
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / "backend" / ".env")
except ImportError:
    pass

API_KEY = os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY", "")
BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/") + "/chat/completions"
CONFIGURED_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")

# 依次是：项目配置的模型、迁移目标、更强的那一档、已退役的旧别名。
# 最后一个也要探，是为了让结论建立在实测而不是发布说明上。
CANDIDATE_MODELS = [CONFIGURED_MODEL, "deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat"]

# 两个查询类工具（不消耗游戏时间，可连续调用）和一个行动类工具
# （改变世界，终止本轮）——这正是改造后工具箱要有的形状。
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_weather",
            "description": "Look outside to check the current weather in Valentown. Does not take game time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thought": {"type": "string", "description": "Why you are doing this, one short sentence."}
                },
                "required": ["thought"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_inbox",
            "description": "Read unread letters other residents have sent you. Does not take game time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thought": {"type": "string", "description": "Why you are doing this, one short sentence."}
                },
                "required": ["thought"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_to",
            "description": "Walk somewhere and spend time doing something there. This ends your turn.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thought": {"type": "string", "description": "Why you are doing this, one short sentence."},
                    "action": {"type": "string", "description": "What you will do there, about 10 words."},
                    "destination": {
                        "type": "string",
                        "enum": ["Park.Bench", "Cafe_bar.Counter", "Ron_home.Kitchen"],
                    },
                },
                "required": ["thought", "action", "destination"],
            },
        },
    },
]

# 刻意设计成"理应先查信息再行动"的情境：想去户外，但完全不知道天气。
# 具备多步能力的 agent 会先查，而不是直接走出门。
SCENARIO = (
    "You are Ron Parker in Valentown. It is day 3, 2:00 PM. You are at Ron_home.Living_room.\n"
    "What you just finished: finished lunch at home.\n"
    "You are thinking about spending the afternoon outdoors at the park, "
    "but you have not looked outside yet and have no idea what the weather is like today.\n"
    "Decide what to do next. You may gather information first if that would help you decide."
)

FORCED_FUNCTION = {"type": "function", "function": {"name": "move_to"}}
THINKING_OFF = {"type": "disabled"}


def post(model, tool_choice=None, thinking=None, with_tools=True, max_tokens=512):
    """发一次请求，返回 (status_code, 解析后的响应体或错误文本)。"""
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "messages": [
            {"role": "system", "content": "You are Ron Parker, a resident of a simulated town."},
            {"role": "user", "content": SCENARIO},
        ],
    }
    if with_tools:
        payload["tools"] = TOOLS
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    if thinking is not None:
        payload["thinking"] = thinking

    try:
        response = requests.post(
            BASE_URL,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
            json=payload,
            timeout=90,
        )
    except requests.RequestException as error:
        return None, f"network error: {error}"

    if response.status_code != 200:
        return response.status_code, response.text[:300]
    return 200, response.json()


def extract_tool_call(body):
    """从成功响应里取出第一个 tool call，返回 (name, args) 或 (None, 说明)。"""
    choices = body.get("choices") or []
    message = (choices[0].get("message") if choices else None) or {}
    tool_calls = message.get("tool_calls") or []
    if not tool_calls:
        content = (message.get("content") or "").strip()
        return None, f"no tool call; plain text: {content[:120]!r}"

    function = tool_calls[0].get("function", {})
    name = function.get("name")
    try:
        args = json.loads(function.get("arguments") or "{}")
    except json.JSONDecodeError:
        return None, f"{name} returned malformed JSON arguments"
    return name, args


def probe_models():
    print(f"\n{'=' * 72}\nPART 1 - model availability\n{'-' * 72}")
    print(f"  configured in config.py : {CONFIGURED_MODEL}")
    print(f"  endpoint                : {BASE_URL}\n")

    alive = []
    for model in dict.fromkeys(CANDIDATE_MODELS):
        status, body = post(model, with_tools=False, max_tokens=16)
        if status == 200:
            print(f"  [ALIVE] {model}")
            alive.append(model)
        else:
            print(f"  [DEAD ] {model}  -> HTTP {status}: {str(body)[:160]}")
        time.sleep(0.5)
    return alive


def probe_tool_choice(model):
    print(f"\n{'=' * 72}\nPART 2 - tool_choice support on {model}\n{'-' * 72}")

    cases = [
        ("specific function, thinking default", FORCED_FUNCTION, None, "<- what llm.py sent BEFORE the fix"),
        ("specific function, thinking OFF", FORCED_FUNCTION, THINKING_OFF, "<- what llm.py sends NOW"),
        ("required, thinking default", "required", None, ""),
        ("required, thinking OFF", "required", THINKING_OFF, "<- what the agent loop wants"),
        ("auto, thinking OFF", "auto", THINKING_OFF, "<- fallback if required is unusable"),
        ("omitted, thinking OFF", None, THINKING_OFF, ""),
    ]

    results = {}
    for label, tool_choice, thinking, note in cases:
        status, body = post(model, tool_choice=tool_choice, thinking=thinking)
        if status != 200:
            verdict, ok = f"HTTP {status}: {str(body)[:140]}", False
        else:
            name, args = extract_tool_call(body)
            verdict, ok = (f"called {name}", True) if name else (args, False)
        print(f"  [{'OK  ' if ok else 'FAIL'}] {label:38s} {verdict}")
        if note:
            print(f"         {' ' * 38} {note}")
        results[label] = ok
        time.sleep(0.5)
    return results


def probe_selection_quality(model, tool_choice, thinking, repeats=5):
    print(f"\n{'=' * 72}\nPART 3 - multi-tool selection quality "
          f"(tool_choice={tool_choice!r}, {repeats} runs)\n{'-' * 72}")
    print("  Scenario: wants to go outdoors, has NOT checked the weather.")
    print("  A multi-step agent gathers information first instead of walking straight out.\n")

    picked, thoughts = [], []
    for index in range(repeats):
        status, body = post(model, tool_choice=tool_choice, thinking=thinking)
        if status != 200:
            print(f"  run {index + 1}: HTTP {status}: {str(body)[:120]}")
            continue
        name, args = extract_tool_call(body)
        if not name:
            print(f"  run {index + 1}: {args}")
            continue
        picked.append(name)
        thought = args.get("thought")
        if thought:
            thoughts.append(thought)
        print(f"  run {index + 1}: {name}  thought={thought!r}")
        time.sleep(0.5)

    if not picked:
        return None

    gathered = sum(1 for name in picked if name in {"check_weather", "check_inbox"})
    print(f"\n  gathered info first : {gathered}/{len(picked)}")
    print(f"  thought populated   : {len(thoughts)}/{len(picked)}")
    return {"picked": picked, "gathered": gathered, "thoughts": len(thoughts)}


def main():
    if not API_KEY:
        print("No API key found. Set LLM_API_KEY in backend/.env and re-run.")
        return 1

    alive = probe_models()
    if not alive:
        print("\nNo candidate model responded. Check the key, the base URL, and the model names.")
        return 1

    target = CONFIGURED_MODEL if CONFIGURED_MODEL in alive else alive[0]
    matrix = probe_tool_choice(target)

    if matrix.get("required, thinking OFF"):
        quality = probe_selection_quality(target, "required", THINKING_OFF)
        chosen = "tool_choice='required' + thinking disabled"
    elif matrix.get("auto, thinking OFF"):
        quality = probe_selection_quality(target, "auto", THINKING_OFF)
        chosen = "tool_choice='auto' + thinking disabled + a validation layer"
    else:
        quality, chosen = None, None

    print(f"\n{'=' * 72}\nVERDICT\n{'-' * 72}")
    print(f"  usable model             : {target}")
    print(f"  pre-fix call_tool works  : {'YES' if matrix.get('specific function, thinking default') else 'NO'}")
    print(f"  post-fix call_tool works : {'YES' if matrix.get('specific function, thinking OFF') else 'NO'}")
    print(f"  multi-tool 'required'    : {'YES' if matrix.get('required, thinking OFF') else 'NO'}")
    if quality:
        print(f"  gathered info first      : {quality['gathered']}/{len(quality['picked'])} runs")
        print(f"  thought field populated  : {quality['thoughts']}/{len(quality['picked'])} runs")

    print()
    if chosen:
        print(f"  => {chosen}")
    else:
        print("  => Multi-tool selection unusable here; switch provider, or keep one forced")
        print("     function with an action_type enum inside it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
