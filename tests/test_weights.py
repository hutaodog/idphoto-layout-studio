# -*- coding: utf-8 -*-
"""模型下载 / 放置 / 文案格式化测试（全程不联网）。

要点：
1. 首次启动的判定（`needs_download`）必须准：在缓存里、在上游位置、都没有，三种情况；
2. 单文件版的坑：`_MEIPASS` 每次重来，所以模型要放**缓存目录**，启动时再拷到上游位置；
3. 下载要校验大小和 sha256，错了不留半成品；
4. 速度/剩余时间的文案不能出现 "-1 秒" 这种鬼东西。
"""
import hashlib
import os

import pytest

from app.core import weights as w


def _fake_model(tmp_path, size=4096):
    p = tmp_path / "fake_model.onnx"
    p.write_bytes(os.urandom(size))
    return p


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """把"程序目录/缓存/上游位置"全部指到临时目录，并把模型地址换成 file://。"""
    appdir = tmp_path / "app"
    appdir.mkdir()
    up = tmp_path / "upstream" / "weights"
    up.mkdir(parents=True)

    model = _fake_model(tmp_path, size=4096)
    data = model.read_bytes()
    monkeypatch.setattr(w, "app_dir", lambda: str(appdir))
    monkeypatch.setattr(w, "target_path", lambda: str(up / w.MODEL_NAME))
    monkeypatch.setattr(w, "MODEL_URL", model.as_uri())
    monkeypatch.setattr(w, "MODEL_SIZE", len(data))
    monkeypatch.setattr(w, "MODEL_SHA256", hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(w, "MIRRORS", ("",))
    return {"appdir": appdir, "aup": up / w.MODEL_NAME, "data": data, "model": model}


def test_needs_download_and_placement(sandbox):
    assert w.needs_download() is True
    assert w.in_place() is False and w.cached() is False

    # 下载（file:// 顶替 GitHub）→ 落到缓存 + 拷到上游位置
    seen = []
    target = w.download(progress=lambda d, t: seen.append((d, t)))
    assert target == str(sandbox["aup"])
    assert os.path.getsize(target) == len(sandbox["data"])
    assert seen and seen[-1] == (len(sandbox["data"]), len(sandbox["data"]))
    assert w.in_place() is True and w.cached() is True
    assert w.needs_download() is False
    assert (sandbox["appdir"] / w.CACHE_DIR_NAME / w.MODEL_NAME).exists()


def test_ensure_placed_copies_cache_to_upstream(sandbox):
    """单文件版每次启动都要重放：缓存有、上游位置空 → 拷过去即可。"""
    w.download()
    os.remove(sandbox["aup"])
    assert w.in_place() is False
    assert w.cached() is True
    assert w.ensure_placed() is True
    assert w.in_place() is True


def test_download_rejects_bad_size_and_leaves_nothing(sandbox, monkeypatch):
    monkeypatch.setattr(w, "MODEL_SIZE", 999999)      # 期望值改错 → 校验必须失败
    with pytest.raises(w.WeightsError):
        w.download()
    assert not w.cache_path() or not os.path.exists(w.cache_path())


def test_download_rejects_bad_sha(sandbox, monkeypatch):
    monkeypatch.setattr(w, "MODEL_SHA256", "0" * 64)
    with pytest.raises(w.WeightsError):
        w.download()
    assert not os.path.exists(w.cache_path())


def test_download_can_be_cancelled(sandbox):
    with pytest.raises(w.WeightsCancelled):
        w.download(should_stop=lambda: True)
    assert not os.path.exists(w.cache_path()), "取消后不能留下半成品"


def test_human_size_and_eta():
    assert w.human_size(512) == "512 B"
    assert w.human_size(1536).endswith("KB")
    assert w.human_size(25 * 1024 * 1024) == "25.0 MB"
    assert w.human_eta(8) == "8 秒"
    assert w.human_eta(0) == "—"
    assert w.human_eta(-1) == "—"
    assert w.human_eta(75) == "1 分 15 秒"
    assert "分" in w.human_eta(3700)


def test_speed_meter_reports_speed_and_eta():
    m = w.SpeedMeter()
    assert m.push(0, 1000, now=100.0) == (0.0, -1.0)     # 只有一个样本：还不知道
    speed, eta = m.push(500, 1000, now=101.0)
    assert abs(speed - 500.0) < 1, speed
    assert abs(eta - 1.0) < 0.1, eta                    # 还剩 500 / 500 = 1 秒
    text = w.progress_text(500, 1000, speed, eta)
    assert "MB/s" not in text and "/s" in text
    assert "剩" in text


def test_progress_text_before_any_speed():
    # 已经开始下、但还测不出速度：只显示已下大小，不要瞎写"正在连接"
    text = w.progress_text(123, 0)
    assert "123" in text and "连接" not in text
    # 一个字节都还没下：才显示"正在连接"
    text2 = w.progress_text(0, 0, 0.0, -1.0)
    assert "正在连接" in text2
