"""每次跑给自己一个版本号：v1、v2、v3……**新的数字更大**。

时间戳目录（``eval_20260826-234138``）机器好排序，人记不住。两周后回头看
"175312 那次"和"185226 那次"差在哪，谁也说不清——而评估的全部价值就在于
两次之间能不能比。

目录长这样，备注可选：

    logs/eval_v7/
    logs/eval_v8_修了递交/
    logs/toolchoice_v3_基线/

⚠️ **版本号只有配上"跑的是哪个 commit"才有意义。**否则它只是个流水号：
v7 和 v8 结果不同，中间改了什么无从查起。所以每个目录里落一份 ``run.json``，
记下命令、commit、以及**工作区脏不脏**——工作区脏的话那个 commit 号并不能
唯一确定跑的是哪份代码，这一点必须写在脸上，不能让人事后误以为可比。
"""

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
LOGS = BACKEND / "logs"

# eval_v12_备注 -> 12。备注里可以有下划线和中文，所以只锚定开头那一段。
_VERSIONED = re.compile(r"^(?P<prefix>[a-z_]+)_v(?P<number>\d+)(?:_.*)?$")


def next_version(prefix, logs_dir=LOGS):
    """下一个版本号 = 现有最大值 + 1。

    只看目录名，不看修改时间——时间会被复制、备份、同步弄乱，名字不会。
    """
    highest = 0
    if logs_dir.exists():
        for entry in logs_dir.iterdir():
            match = _VERSIONED.match(entry.name)
            if match and match.group("prefix") == prefix:
                highest = max(highest, int(match.group("number")))
    return highest + 1


def make_run_dir(prefix, note=None, logs_dir=LOGS):
    """建目录并返回它。备注只做最低限度的清洗——它是给人看的。"""
    name = f"{prefix}_v{next_version(prefix, logs_dir)}"
    if note:
        name += "_" + re.sub(r"[^\w一-鿿-]+", "-", note.strip()).strip("-")
    run_dir = logs_dir / name
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def note_from_argv(argv):
    """``--note`` 得在 import config 之前就知道（目录名要用），而那时候
    argparse 还没跑。所以在这里先摸一眼 argv；真正的解析照旧在 main 里。
    """
    for index, token in enumerate(argv):
        if token.startswith("--note="):
            return token.split("=", 1)[1]
        if token == "--note" and index + 1 < len(argv):
            return argv[index + 1]
    return None


def _git(*args):
    try:
        done = subprocess.run(("git",) + args, cwd=BACKEND, capture_output=True,
                              text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def write_manifest(run_dir, argv, **extra):
    """落一份 run.json：这一次跑的是什么代码、跑的什么命令。

    ``dirty`` 为真时 ``commit`` **不足以确定代码**——跑之前没提交的改动
    不在那个 commit 里。宁可记下来让人皱眉，也不要留一个看起来可比、
    其实不可比的版本号。
    """
    manifest = {
        "version": run_dir.name,
        "started": datetime.now().isoformat(timespec="seconds"),
        "command": " ".join(argv),
        "commit": _git("rev-parse", "--short", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(_git("status", "--porcelain")),
        **extra,
    }
    (run_dir / "run.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
