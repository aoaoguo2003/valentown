"""版本号：v1、v2、v3……新的数字更大。

这层东西本身很简单，值得测的是**两件容易出错、出错了还不报错**的事：
编号会不会踩到已有的目录（踩到就覆盖掉上一次的结果），以及 ``run.json``
会不会在工作区脏的时候还宣称自己可比。
"""

import json

from evals.run_dir import make_run_dir, next_version, note_from_argv, write_manifest


def test_the_first_run_is_v1(tmp_path):
    assert next_version("eval", tmp_path) == 1


def test_each_run_gets_a_bigger_number(tmp_path):
    (tmp_path / "eval_v1").mkdir()
    (tmp_path / "eval_v2").mkdir()

    assert next_version("eval", tmp_path) == 3


def test_a_note_does_not_hide_the_number(tmp_path):
    (tmp_path / "eval_v7_修了递交").mkdir()

    assert next_version("eval", tmp_path) == 8


def test_numbering_is_by_name_not_by_order_on_disk(tmp_path):
    """**编号要接着最大的走，不是接着最新的走。**目录会被复制、备份、
    同步——修改时间靠不住，名字靠得住。漏了这一点就会覆盖旧结果。"""
    (tmp_path / "eval_v9").mkdir()
    (tmp_path / "eval_v3").mkdir()

    assert next_version("eval", tmp_path) == 10


def test_two_kinds_of_run_count_separately(tmp_path):
    (tmp_path / "eval_v5").mkdir()

    assert next_version("toolchoice", tmp_path) == 1


def test_old_timestamp_directories_do_not_confuse_it(tmp_path):
    (tmp_path / "eval_20260826-234138").mkdir()

    assert next_version("eval", tmp_path) == 1


def test_making_a_run_dir_creates_it(tmp_path):
    run_dir = make_run_dir("eval", "修了递交", logs_dir=tmp_path)

    assert run_dir.is_dir()
    assert run_dir.name == "eval_v1_修了递交"


def test_a_note_with_spaces_and_slashes_still_makes_a_usable_name(tmp_path):
    run_dir = make_run_dir("eval", "fix: give/item 窗口", logs_dir=tmp_path)

    assert run_dir.is_dir()
    for bad in "/\\: ":
        assert bad not in run_dir.name


# --- --note 要赶在 argparse 之前拿到 -------------------------------------------

def test_the_note_is_found_before_argparse_runs():
    assert note_from_argv(["--repeats", "2", "--note", "基线"]) == "基线"
    assert note_from_argv(["--note=基线"]) == "基线"
    assert note_from_argv(["--repeats", "2"]) is None
    assert note_from_argv(["--note"]) is None          # 忘了写值，别炸


# --- run.json：版本号只有配上 commit 才有意义 -------------------------------------

def test_the_manifest_records_what_code_was_run(tmp_path):
    run_dir = make_run_dir("eval", logs_dir=tmp_path)

    write_manifest(run_dir, ["python", "-m", "evals.runner", "--repeats", "2"],
                   model="deepseek-v4-flash")
    saved = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))

    assert saved["version"] == "eval_v1"
    assert saved["command"] == "python -m evals.runner --repeats 2"
    assert saved["model"] == "deepseek-v4-flash"
    assert "dirty" in saved, "脏不脏必须写在脸上——脏的时候 commit 号定位不了代码"
    assert "commit" in saved


# --- 空号要还回去 -------------------------------------------------------------

def test_an_empty_run_dir_is_reclaimed_on_exit(tmp_path):
    """``evals.runner`` 在 import 时就建目录（``LLM_TRACE_FILE`` 必须赶在
    config 之前定下来），所以**光是 import 一次就烧掉一个版本号**——
    实际发生过，v13/v14 两个空目录就是这么来的。

    空号让序列说谎：看着像跑过，其实什么都没产出。
    """
    from evals.run_dir import _discard_if_empty

    run_dir = make_run_dir("eval", logs_dir=tmp_path)
    assert run_dir.is_dir()

    _discard_if_empty(run_dir)

    assert not run_dir.exists()
    assert next_version("eval", tmp_path) == 1, "号要还回去，下一次还是 v1"


def test_a_run_that_produced_something_is_kept(tmp_path):
    from evals.run_dir import _discard_if_empty

    run_dir = make_run_dir("eval", logs_dir=tmp_path)
    (run_dir / "rows.jsonl").write_text("{}\n", encoding="utf-8")

    _discard_if_empty(run_dir)

    assert run_dir.is_dir()


def test_reclaiming_never_raises_on_the_way_out(tmp_path):
    """退出路径上炸一下会掩盖真正的错误——目录早没了也得安静收场。"""
    from evals.run_dir import _discard_if_empty

    _discard_if_empty(tmp_path / "never-existed")


def test_untracked_files_do_not_count_as_dirty(tmp_path, monkeypatch):
    """``dirty`` 只看**已跟踪**文件。

    第一版把未跟踪的也算进去，于是工作区里随便躺着一份别的东西（实际发生
    过：一份 89MB 的演讲稿）就让每一次跑都挂上"不可归因"。**一个永远亮着
    的警告灯等于没有警告灯**——真出问题时没人会当回事。
    """
    import evals.run_dir as run_dir

    seen = []

    def fake_git(*args):
        seen.append(args)
        if args[:2] == ("status", "--porcelain"):
            # 已跟踪的干净，未跟踪的有两个
            return "" if "--untracked-files=no" in args else "?? a.pptx\n?? b.png"
        return "abc1234"

    monkeypatch.setattr(run_dir, "_git", fake_git)
    saved = run_dir.write_manifest(tmp_path, ["x"])

    assert saved["dirty"] is False, "只有未跟踪文件时，commit 号仍然定位得了代码"
    assert saved["untracked"] == 2
    assert ("status", "--porcelain", "--untracked-files=no") in seen


def test_a_real_edit_still_shows_up_as_dirty(tmp_path, monkeypatch):
    import evals.run_dir as run_dir

    def fake_git(*args):
        if args[:2] == ("status", "--porcelain"):
            return " M backend/world/goals.py"
        return "abc1234"

    monkeypatch.setattr(run_dir, "_git", fake_git)

    assert run_dir.write_manifest(tmp_path, ["x"])["dirty"] is True
