"""目录结构本身的测试：存档在哪、谁能 import 谁。

这些不是功能测试，是**架构约束**。它们守的两件事都有过真实教训：

  ① 分包时四份存档跟着模块搬进了子包，240 个测试全绿——因为测试一律用
     ``tmp_path``，没有一个验过真实路径。是 ``git status`` 里冒出来一个
     ``backend/world/economy.json`` 才暴露的。

  ② 依赖方向一旦回流就会出环。``world/`` 曾经反过来 import ``tools``，
     逼得 ``SHOP_OWNERS`` 复制成两份"必须保持一致"。

这个文件不 import 任何被测模块的运行时对象（只读源码 + 读常量），
所以它不受别处 fixture 改动模块属性的影响。
"""

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent


def _top_level_imports(path):
    """一个文件在**模块顶层**import 了哪些顶层包。

    只看顶层——函数内部的延迟 import 是这个代码库解耦的常规手段
    （``tools/movement.py`` 就在函数里才 import ``world.snapshot``），
    它不构成加载期的环。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in tree.body:                      # 只遍历顶层语句
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


# --- 存档路径 ---------------------------------------------------------------

def test_every_saved_file_still_lives_in_the_backend_root():
    """存档路径不能跟着模块搬家。

    路径统一由 ``config.DATA_DIR`` 给出——**模块会搬家，config.py 不会**。
    """
    from agents.state import STATE_DIR
    from config import DATA_DIR
    from memory.memory_system import MEMORY_BANK_DIR
    from memory.persona_store import PERSONA_DIR
    from world.economy import ECONOMY_FILE
    from world.goals import GOALS_FILE
    from world.mailbox import MAILBOX_FILE

    for path in (ECONOMY_FILE, GOALS_FILE, MAILBOX_FILE):
        assert path.parent == DATA_DIR, f"{path} 不在 backend/ 根下了"
    assert STATE_DIR.parent == DATA_DIR, f"{STATE_DIR} 不在 backend/ 根下了"

    # 记忆库和 persona 本来就住在 memory/ 包里——那是它们的家，不是搬走的。
    for path in (MEMORY_BANK_DIR, PERSONA_DIR):
        assert path.parent == DATA_DIR / "memory", f"{path} 位置变了"


# --- 依赖方向 ---------------------------------------------------------------

# 从下往上：world -> tools -> runtime -> api。每一层顶层只能 import 它下面的。
UPPER_LAYERS = {"tools", "runtime", "api", "agents", "memory"}


@pytest.mark.parametrize("path", sorted((BACKEND / "world").glob("*.py")), ids=lambda p: p.name)
def test_world_never_imports_upwards(path):
    """``world/`` 是地基，顶层不能 import 任何上层包。

    它一旦回流就会出环：``tools/__init__.py`` 顶层要 ``world.economy``，
    ``world`` 里再 import ``tools`` 就转回去了。
    """
    offenders = _top_level_imports(path) & UPPER_LAYERS
    assert not offenders, f"world/{path.name} 顶层 import 了上层包 {sorted(offenders)}"


def test_the_world_package_init_stays_empty():
    """``world/__init__.py`` 一个 import 都不能有。

    ``tools/__init__.py`` 顶层的 ``from world.economy import SHOP_OWNERS``
    会先跑一遍它；它若 import 了 ``tools``（哪怕只为 re-export 一个常量），
    整个后端就起不来。
    """
    tree = ast.parse((BACKEND / "world" / "__init__.py").read_text(encoding="utf-8"))
    imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert not imports, "world/__init__.py 里出现了 import——这会把 tools 拖成环"


@pytest.mark.parametrize("path", sorted((BACKEND / "tools").glob("*.py")), ids=lambda p: p.name)
def test_tools_never_import_the_runtime(path):
    """工具是被循环调用的，不能反过来认识循环。"""
    offenders = _top_level_imports(path) & {"runtime", "api"}
    assert not offenders, f"tools/{path.name} 顶层 import 了 {sorted(offenders)}"


def test_shop_owners_is_defined_exactly_once():
    """曾经它被复制成两份，注释写着"两处必须保持一致"——那是环逼出来的。

    环没了，重复也该没。同一个东西两处维护，给一处加字段另一处就开始说谎。
    """
    definitions = [
        path.name
        for path in BACKEND.rglob("*.py")
        if "__pycache__" not in path.parts
        and "\nSHOP_OWNERS = {" in path.read_text(encoding="utf-8")
    ]
    assert definitions == ["economy.py"], f"SHOP_OWNERS 定义在了 {definitions}"
