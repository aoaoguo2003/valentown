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
