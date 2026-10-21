# -*- coding: utf-8 -*-
"""更新器测试（**全程不联网**）。

思路：网络层用 `file://` URL + 本地假数据顶替 GitHub；覆盖动作在临时目录里真跑一遍。
要守住的性质：
1. 版本比较不能错（1.6.0 > 1.5.8 > 1.5.10 这种坑）；
2. release JSON 解析出 tag / 说明 / 资产（含 sha256 digest）；
3. 按打包形式挑资产（单文件 → onefile.exe，文件夹 → portable.zip，源码 → 不动）；
4. 下载会校验大小与 sha256，对不上要报错**并且不留下半成品**；
5. 覆盖只在旧进程退出后发生，且**只覆盖不删除**（用户自己的 输出/ 不能丢）。
"""
import json
import os
import zipfile

import pytest

from app.core import updater as up

SAMPLE_RELEASE = {
    "tag_name": "v9.9.9",
    "name": "v9.9.9 · 测试版",
    "body": "## 更新内容\n- 修复了一个假问题",
    "html_url": "https://example.invalid/releases/tag/v9.9.9",
    "assets": [
        {"name": "idphoto-v9.9.9-onefile.exe", "size": 12,
         "browser_download_url": "https://example.invalid/onefile.exe",
         "digest": "sha256:" + "a" * 64},
        {"name": "idphoto-v9.9.9-portable.zip", "size": 34,
         "browser_download_url": "https://example.invalid/portable.zip"},
    ],
}


# ------------------------------------------------------------------ 版本
@pytest.mark.parametrize("remote,local,newer", [
    ("v1.6.0", "1.5.8", True),
    ("1.5.8", "1.5.8", False),
    ("v1.5.9", "1.5.8", True),
    ("v1.5.10", "1.5.8", True),      # 字符串比较会错，元组比较才对
    ("v1.4.99", "1.5.0", False),
    ("v2", "1.9.9", True),
    ("1.6.0-beta", "1.5.8", True),   # 后缀忽略
])
def test_version_comparison(remote, local, newer):
    assert up.is_newer(remote, local) is newer


def test_parse_version_handles_garbage():
    assert up.parse_version("") == (0,)
    assert up.parse_version("v1.6") == (1, 6, 0)
    assert up.parse_version("abc") == (0,)


# ------------------------------------------------------------------ 解析 Release
def test_parse_release_extracts_everything():
    info = up.parse_release(SAMPLE_RELEASE)
    assert info.version == "9.9.9"
    assert info.tag == "v9.9.9"
    assert "假问题" in info.notes
    assert len(info.assets) == 2
    one = info.asset_named("-onefile.exe")
    assert one and one.sha256 == "a" * 64 and one.size == 12
    assert info.asset_named("-portable.zip").sha256 == ""     # 没有 digest 也不炸


def test_pick_asset_follows_build_kind():
    info = up.parse_release(SAMPLE_RELEASE)
    assert up.pick_asset(info, "single").name.endswith("-onefile.exe")
    assert up.pick_asset(info, "folder").name.endswith("-portable.zip")
    assert up.pick_asset(info, "source") is None              # 源码运行不自动更新


# ------------------------------------------------------------------ 下载与校验
@pytest.fixture()
def local_file(tmp_path):
    """造一个"远端文件"并用 file:// 暴露出去（urlopen 支持，不联网）。"""
    def make(name, data: bytes):
        p = tmp_path / name
        p.write_bytes(data)
        return p, p.as_uri()
    return make


def test_download_verifies_size_and_sha(local_file, tmp_path):
    data = b"hello update" * 100
    src, uri = local_file("asset.bin", data)
    dest = str(tmp_path / "out" / "asset.bin")
    seen = []
    got = up.download(uri, dest, size=len(data), sha256=up.sha256_file(str(src)),
                      progress=lambda d, t: seen.append((d, t)), mirrors=("",))
    assert got == dest and os.path.getsize(dest) == len(data)
    assert seen and seen[-1][0] == len(data)


def test_download_rejects_bad_sha_and_cleans_up(local_file, tmp_path):
    src, uri = local_file("asset.bin", b"payload")
    dest = str(tmp_path / "asset.bin")
    with pytest.raises(Exception):
        up.download(uri, dest, sha256="b" * 64, mirrors=("",))
    assert not os.path.exists(dest), "sha256 不对时必须删掉半成品"


def test_download_rejects_wrong_size(local_file, tmp_path):
    src, uri = local_file("asset.bin", b"payload")
    dest = str(tmp_path / "asset.bin")
    with pytest.raises(Exception):
        up.download(uri, dest, size=9999, mirrors=("",))
    assert not os.path.exists(dest)


def test_fetch_latest_survives_bad_mirrors(tmp_path, monkeypatch):
    payload = json.dumps(SAMPLE_RELEASE).encode()
    p = tmp_path / "latest.json"
    p.write_bytes(payload)
    uri = p.as_uri()
    # 第一个"镜像"是坏路径，第二个才对 —— 必须能走下来
    info = up.fetch_latest(url=uri, mirrors=("http://127.0.0.1:1/", ""))
    assert info.version == "9.9.9"


# ------------------------------------------------------------------ 状态
def test_state_roundtrip_and_auto_check_gate(monkeypatch, tmp_path):
    monkeypatch.setattr(up, "state_path", lambda: str(tmp_path / "st.json"))
    st = up.load_state()
    assert st["auto_check"] is True and st["last_check"] == 0
    assert up.should_auto_check(st) is True
    up.save_state(last_check=up.time.time())
    assert up.should_auto_check(up.load_state()) is False     # 24 小时内不再查
    up.save_state(auto_check=False)
    assert up.should_auto_check(up.load_state()) is False     # 关掉就永不自动查
    up.save_state(auto_check=True, last_check=0)
    assert up.should_auto_check(up.load_state()) is True


# ------------------------------------------------------------------ 准备 + 落地
def _make_zip(path, files):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)


def test_prepare_and_apply_extract_copy(tmp_path, monkeypatch):
    """文件夹版：下载 zip → 解压 → 覆盖到"程序目录"（只覆盖，不删用户的 输出/）。"""
    fake_zip = tmp_path / "portable.zip"
    _make_zip(fake_zip, {"app.exe": b"NEW-EXE", "lib/data.txt": b"NEW-DATA"})
    staging = tmp_path / "app" / "_update"
    target = tmp_path / "app"
    (target / "输出").mkdir(parents=True)
    (target / "输出" / "我的照片.jpg").write_bytes(b"KEEP")
    (target / "lib").mkdir()
    (target / "lib" / "data.txt").write_bytes(b"OLD")
    (target / "lib" / "only_old.txt").write_bytes(b"OLD-ONLY")

    monkeypatch.setattr(up, "app_dir", lambda: str(target))
    info = up.parse_release({"tag_name": "v9.9.9", "assets": [
        {"name": "x-v9.9.9-portable.zip", "size": fake_zip.stat().st_size,
         "browser_download_url": fake_zip.as_uri()}]})
    plan = up.prepare_update(info, kind="folder", mirrors=("",))
    assert plan.mode == "extract-copy"
    assert os.path.exists(os.path.join(plan.payload, "app.exe"))
    assert json.load(open(os.path.join(staging, "apply.json"), encoding="utf-8"))

    res = up.apply_plan(plan, old_pid=0)
    assert res["error"] == "", res
    assert (target / "app.exe").read_bytes() == b"NEW-EXE"
    assert (target / "lib" / "data.txt").read_bytes() == b"NEW-DATA"
    assert (target / "lib" / "only_old.txt").exists(), "覆盖模式不许删用户的旧文件"
    assert (target / "输出" / "我的照片.jpg").read_bytes() == b"KEEP"
    assert not os.path.exists(staging), "落地后应清掉 _update"


def test_prepare_and_apply_replace_exe(tmp_path, monkeypatch):
    """单文件版：把新 exe 覆盖到目标路径（先写 .new 再 os.replace）。"""
    target = tmp_path / "app"
    target.mkdir()
    exe = target / "证件照排版助手.exe"
    exe.write_bytes(b"OLD-EXE")
    new_exe = tmp_path / "new-onefile.exe"
    new_exe.write_bytes(b"NEW-EXE-BINARY")

    monkeypatch.setattr(up, "app_dir", lambda: str(target))
    monkeypatch.setattr(up, "_FROZEN", True)          # 模块级常量，得单独打补丁
    monkeypatch.setattr(up.sys, "frozen", True, raising=False)
    monkeypatch.setattr(up.sys, "executable", str(exe), raising=False)
    monkeypatch.setattr(up.sys, "_MEIPASS", str(tmp_path / "tmpmei"), raising=False)
    info = up.parse_release({"tag_name": "v9.9.9", "assets": [
        {"name": "x-v9.9.9-onefile.exe", "size": new_exe.stat().st_size,
         "browser_download_url": new_exe.as_uri()}]})
    plan = up.prepare_update(info, kind="single", mirrors=("",))
    assert plan.mode == "replace-exe"
    res = up.apply_plan(plan, old_pid=0)
    assert res["error"] == "", res            # 更新本身成功
    assert exe.read_bytes() == b"NEW-EXE-BINARY"
    # 假 exe 拉不起来，只能记在 restart_error 上（"已更新、请手动打开"）
    assert res["restarted"] is False and res["restart_error"]


def test_apply_reports_error_when_old_process_never_exits(tmp_path):
    plan = up.UpdatePlan(mode="replace-exe", staging=str(tmp_path / "st"),
                         target_dir=str(tmp_path), target_exe=str(tmp_path / "x.exe"),
                         payload=str(tmp_path / "new.exe"), version="9.9.9")
    (tmp_path / "new.exe").write_bytes(b"x")
    res = up.apply_plan(plan, old_pid=os.getpid(), timeout=0.6)   # 自己肯定不退出
    assert res["error"], "等不到旧进程退出要如实报错，不能装作成功"
    assert not res["restarted"]


def test_wait_for_pid_zero_is_noop():
    assert up.wait_for_pid(0, timeout=0.1) is True


def test_cleanup_stale_removes_leftovers(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "app_dir", lambda: str(tmp_path))
    (tmp_path / "_update").mkdir()
    (tmp_path / "_update" / "x.bin").write_bytes(b"x")
    (tmp_path / "_update_old_123").mkdir()
    (tmp_path / "app.exe.new").write_bytes(b"x")
    (tmp_path / "keep.exe").write_bytes(b"x")
    removed = up.cleanup_stale()
    assert removed == 3, removed
    assert not (tmp_path / "_update").exists()
    assert (tmp_path / "keep.exe").exists()


# ------------------------------------------------------------------ 无界面落地入口
def test_run_apply_update_cli_entry(tmp_path, monkeypatch):
    """`--apply-update` 那个无界面入口真跑一遍：覆盖成功 → 返回 0 → 写更新日志。"""
    from app import main as app_main

    target = tmp_path / "app"
    (target / "输出").mkdir(parents=True)
    (target / "输出" / "keep.jpg").write_bytes(b"KEEP")
    staged = tmp_path / "_update" / "staged"
    staged.mkdir(parents=True)
    (staged / "app.exe").write_bytes(b"NEW")
    cfg = tmp_path / "_update" / "apply.json"
    plan = up.UpdatePlan(mode="extract-copy", staging=str(tmp_path / "_update"),
                         target_dir=str(target),
                         target_exe=str(target / "app.exe"), payload=str(staged),
                         version="9.9.9")
    cfg.write_text(json.dumps(plan.to_dict()), encoding="utf-8")

    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr("app.paths.app_dir", lambda: str(tmp_path))
    code = app_main.run_apply_update(str(cfg), old_pid=0)
    assert code == 0
    assert (target / "app.exe").read_bytes() == b"NEW"
    assert (target / "输出" / "keep.jpg").read_bytes() == b"KEEP", "不许动用户的数据"
    # 日志写在**被更新的程序目录**里（applier 自己所在的 _update 会被删掉）
    log = target / ".logs" / "更新日志.txt"
    assert log.exists() and "copied" in log.read_text(encoding="utf-8")
    assert not (target / ".logs" / "更新失败.txt").exists(), "成功了不该留失败记号"
