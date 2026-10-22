# -*- coding: utf-8 -*-
"""用户设置的持久化测试：输出目录要"选一次、重启还记得"。

这条是用户明确提的需求："用户设置完之后，即使退出软件，也还是那个路径，路径都不变。"
所以除了"存得下、读得出"，还要守住两条边界：
1. 用户把目录删了 / 盘拔了 → 自动退回默认，不能卡在坏路径上；
2. 设置文件写不进去（目录只读）→ 不能让程序起不来。
"""
import json
import os

import pytest

from app.core import settings as st


@pytest.fixture()
def isolated(monkeypatch, tmp_path):
    """把设置文件指到临时目录，别污染真实的 settings.json。"""
    monkeypatch.setattr(st, "settings_path", lambda: str(tmp_path / "settings.json"))
    return tmp_path


def test_out_dir_is_remembered(isolated):
    out = isolated / "我的输出"
    st.set_out_dir(str(out))
    # 换个"会话"再读：模拟重启
    assert st.get_out_dir() == str(out)
    assert json.loads((isolated / "settings.json").read_text(encoding="utf-8"))["out_dir"] \
        == str(out)


def test_out_dir_falls_back_when_the_folder_is_gone(isolated, tmp_path):
    gone = tmp_path / "被删掉的目录"
    st.set_out_dir(str(gone))
    assert st.get_out_dir() == str(gone)          # 建得出来，能用
    # 把它删掉、并且让它在"父目录不存在"的情况下也无法重建
    import shutil
    shutil.rmtree(gone)
    blocked = tmp_path / "不可写" / "输出"
    st.set_out_dir(str(blocked))
    (tmp_path / "不可写").write_text("我是文件不是目录", encoding="utf-8")
    assert st.get_out_dir() == "", "目录建不出来时应该返回空串，让调用方用默认值"


def test_empty_out_dir_means_default(isolated):
    st.set_out_dir("")
    assert st.get_out_dir() == ""


def test_update_sources_default_and_persist(isolated):
    urls = st.get_update_sources()
    assert urls, "默认应该带一个自建节点"
    assert all(u.startswith("http") for u in urls)

    st.set_update_sources(["http://a/update.json", "  ", "http://b/update.json"])
    assert st.get_update_sources() == ["http://a/update.json", "http://b/update.json"]

    st.add_update_source("http://c/update.json")
    assert "http://c/update.json" in st.get_update_sources()
    # 重复添加不产生重复项
    st.add_update_source("http://c/update.json")
    assert st.get_update_sources().count("http://c/update.json") == 1


def test_broken_settings_file_does_not_crash(isolated):
    (isolated / "settings.json").write_text("{ 这不是 json", encoding="utf-8")
    data = st.load()
    assert data["out_dir"] == "" and data["update_sources"], "坏文件要退回默认值"
