"""HTTP 层：前端和这套后端之间的契约。

```
routes.py   Flask 路由。两段锁：取世界快照 / 提交决策
```

⚠️ 这里**不 re-export ``app``**。导入 ``routes`` 会顺带建七个居民、读存档、
初始化记忆库——那是启动，不是导入一个包该干的事。要 app 就明写
``from api.routes import app``。

``persistence.py``（进度与对话的存档读写，现在混在 routes.py 里）还没拆出来。
"""
