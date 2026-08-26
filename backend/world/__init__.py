"""世界：小镇里有什么、规则是什么。数据 + 原子操作。

```
clock.py      时间文本 <-> 分钟数。整个包最底层，谁都能安全 import
locations.py  地理与居民名册（ALLOWED_DESTINATIONS 就是 move_to 的取值范围）
economy.py    钱 + 货 + 店铺。**故意不拆成 inventory + economy**——
              买东西要同时改五样，用两把锁做一件原子的事除了部分失败
              还会死锁。原子性边界决定模块边界。
weather.py    天气。这个项目唯一的真外部依赖
goals.py      任务与约定。共享的承诺账本，约定给双方各建一条
snapshot.py   把上面这些装配成一份给模型看的世界快照。唯一的装配点
```

⚠️ **这个文件必须保持空的**，一个 import 都不能加。

``tools/__init__.py`` 顶层要 ``from world.economy import SHOP_OWNERS``，
这会先跑一遍本文件。本文件若 import 了 ``tools``（哪怕只是为了 re-export
一个常量），就会绕回 ``tools/__init__.py``——**循环导入，整个后端起不来**。

空着的代价是调用方得写全 ``from world.snapshot import World``；
换来的是这个包可以被任何人从任何地方安全导入。
"""
