"""记分卡排版：把一堆跑出来的格子摆成一张能横着看的表。

两条规矩：

**判据和行为分两列摆。**"做到没有"来自场景的 judge（只看世界状态），
"撞了几次墙"来自 observability 的指标。混成一个分数，就再也说不清
一次失败是因为想错了还是因为世界不让。

**每格都要标样本量。**判据一过就早停，所以达成得快的格子行为样本少。
6 次决策算出来的 5% 和 60 次算出来的 5%，不标出来长得一模一样。
"""


def _pct(value):
    return "  —  " if value is None else f"{value * 100:5.1f}%"


def _mark(row_or_passed):
    """记分卡上那一列。

    三种失败要分得开，否则整张表就开始说谎：

        ERR   模型一次都没成功应答过 —— 量的是后端，不是模型
        ✗⏱    跑到决策上限才结束 —— 是**没跑完**，不是做不到
        ✗     真的做不到

    第二种是真跑里踩出来的：errand 那条链 11:05 约好 12:00 见面、对方
    11:20 已经动身，而评估在 11:30 掐断了。差三十分钟游戏时间，
    在记分卡上和"一环都没走"长得一模一样。
    """
    if not isinstance(row_or_passed, dict):
        if row_or_passed is None:
            return " · "
        return " ✓ " if row_or_passed else " ✗ "

    row = row_or_passed
    if not row.get("usable", True):
        return "ERR"
    if row["passed"] is None:
        return " · "
    if row["passed"]:
        return " ✓ "
    return " ✗⏱" if row.get("stopped_because") == "decision limit" else " ✗ "


def _progress(row):
    """走到第几环。

    第一张记分卡的教训：``errand`` 十四格全 ✗，而其中一格已经把药买到手
    （六环走了五环），另一格一个改变世界的动作都没有——**记分卡上一模一样**。
    二元判据在多环任务上区分不出任何东西，那一整列就白跑了。
    """
    stages = row.get("stages") or []
    if not stages:
        return "  —  "
    return f"{len(row.get('reached') or [])}/{len(stages)}"


def format_scorecard(rows):
    """rows 是 runner 跑出来的每一格。"""
    out = []
    add = out.append

    add("=" * 100)
    add("SCORECARD")
    add("=" * 100)
    add(f"{'scenario':<12}{'ablation':<19}{'pass':>5}{'decisions':>11}"
        f"{'progress':>10}{'calls':>7}{'invalid':>9}{'refused':>9}{'replan':>9}{'wasted':>9}")
    add("-" * 100)

    for row in rows:
        metrics = row["metrics"]
        replan = metrics["replanning"]["rate"]
        add(
            f"{row['scenario']:<12}{row['ablation']:<19}"
            f"{_mark(row):>5}"
            f"{row['decisions']:>11}"
            f"{_progress(row):>10}"
            f"{metrics['calls']:>7}"
            f"{_pct(metrics['invalid_calls']['rate']):>9}"
            f"{_pct(metrics['environment_refusals']['rate']):>9}"
            f"{_pct(replan):>9}"
            f"{_pct(metrics['wasted_turns']['rate']):>9}"
        )

    add("-" * 100)
    add("  pass     场景判据，只看世界状态（· = 控制组，没有判据）")
    add("           ✗⏱ = 跑到决策上限才结束，是没跑完不是做不到；ERR = 后端挂了，量的不是模型")
    add("  progress 走到第几环 —— 二元判据看不出卡在哪一步，这一列才看得出")
    add("  calls   这一格总共发生了多少次工具调用 —— **行为百分比的样本量**")
    add("  invalid 模型自己的错：编工具名 / 重复问 / 超次数")
    add("  refused 世界说不行：关门 / 人不在 / 钱不够。这不是错，是环境在工作")
    add("  replan  被拒之后换招的比例。single-step 那行永远是 — （只有一步）")
    add("  wasted  想满步数还没做出动作、只能兜底的轮次占比")

    add("")
    add("详情")
    for row in rows:
        add(f"  {row['scenario']}/{row['ablation']}  "
            f"[{row['stopped_because']}, {row['wall_seconds']:.0f}s]")
        add(f"    {row['detail']}")
        stages, reached = row.get("stages") or [], set(row.get("reached") or [])
        if stages:
            add("    " + "  ".join(
                f"{'✓' if s in reached else '✗'}{s}" for s in stages))
        change = row["metrics"]["world_change"]
        add(f"    真正改变世界的轮次 {change['turns']}/{row['decisions']}"
            f"  {change['by_tool'] or '（一次都没有）'}")
        invented = row["metrics"]["invented_tools"]
        if invented:
            add(f"    模型编出来的工具名 {invented}")

    return "\n".join(out)


def format_cost_table(rows):
    """成本单独一张表。

    不并进上面那张，是因为两者来自**两份日志**：动作日志一步一条，
    LLM 日志一次请求一条——重试会多几次，兜底则一次都不发。
    硬凑成一行会让人以为它们是同一批样本。
    """
    out = ["", "=" * 88, "COST", "=" * 88,
           f"{'scenario':<12}{'ablation':<19}{'llm calls':>10}{'retries':>9}"
           f"{'tokens':>10}{'tok/decision':>14}{'p90 latency':>13}"]
    out.append("-" * 88)

    for row in rows:
        cost = row.get("cost") or {}
        if not cost.get("calls"):
            out.append(f"{row['scenario']:<12}{row['ablation']:<19}"
                       f"{'（这一格没有 LLM 日志）':>10}")
            continue
        total = cost["tokens"]["total"]
        per_decision = round(total / row["decisions"]) if row["decisions"] else 0
        p90 = cost["latency_ms"]["p90"]
        out.append(
            f"{row['scenario']:<12}{row['ablation']:<19}"
            f"{cost['calls']:>10}{cost['retries']:>9}{total:>10}"
            f"{per_decision:>14}{(str(p90) + 'ms') if p90 else '—':>13}"
        )

    out.append("-" * 88)
    grand = sum((row.get("cost") or {}).get("tokens", {}).get("total", 0) for row in rows)
    out.append(f"  整张表一共烧掉 {grand} tokens")
    return "\n".join(out)


def format_comparison(rows):
    """同一道题的基线 vs 各消融，只看最关心的两个数。

    ⚠️ **废格整个不进这张表。**对照表是这套评估最终要拿出去讲的东西；
    一格如果量的是后端而不是模型，让它以 ✗ 的身份站在这里，
    结论就直接错了。宁可少一行，也不能多一行假的。
    """
    usable = [row for row in rows if row.get("usable", True)]
    dropped = len(rows) - len(usable)

    by_scenario = {}
    for row in usable:
        by_scenario.setdefault(row["scenario"], []).append(row)

    out = ["", "=" * 100, "基线 vs 消融 —— 关掉一个能力，这道题还做得成吗", "=" * 100]
    if dropped:
        out.append(f"  ⚠️ 有 {dropped} 格模型一次都没成功应答过，量的是后端不是模型，已剔除")
    for scenario, group in by_scenario.items():
        baseline = next((r for r in group if r["ablation"] == "none"), None)
        others = [r for r in group if r["ablation"] != "none"]
        if not others:
            continue
        base_mark = _mark(baseline) if baseline else " ? "
        base_steps = baseline["decisions"] if baseline else "?"
        out.append(f"\n  {scenario}    基线 {base_mark} （{base_steps} 次决策）")
        for row in others:
            out.append(f"      {row['ablation']:<19}{_mark(row)}"
                       f"  {row['decisions']:>3} 次决策    {row['headline']}")
    return "\n".join(out)
