"""评估：这套 Agent 做得好不好。

和 ``observability/`` 的分工是一条硬线：

    observability   发生了什么。不需要知道题目，随便一份日志都能算
    evals           做得好不好。必须对着题目和判据才判得了

还没写的（下一步）：

```
scenarios.py   场景注册表：每条 = seed(埋一个起因) + judge(看世界状态判成败)
runner.py      跑 场景 x 消融 x 重复，出记分卡
report.py      记分卡排版
```

判据只看世界状态——``holdings(Adam)['cold_medicine'] > 0``——不看模型
怎么说自己做到了。
"""
