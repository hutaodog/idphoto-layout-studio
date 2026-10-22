# -*- coding: utf-8 -*-
"""抠图模型（`hivision_modnet.onnx`）的定位 / 首次启动下载 / 就位。

为什么要单独一个模块：**便携版和安装版都不带模型**（25MB 二进制不适合进仓库，
`scripts/download_weights.ps1` 是给开发者的），普通用户第一次双击时必须能自己下下来，
否则只会看到「抠图模型缺失」。

三个位置要分清：
* **上游真正会读的位置**：`<hivision 包目录>/creator/weights/hivision_modnet.onnx`
  （上游 `human_matting.py` 用 `os.path.dirname(__file__)` 硬拼，改不了）；
* **单文件版的坑**：`_MEIPASS` 是每次启动重新解压的临时目录，下到那里等于每次都白下 ——
  所以模型要**长期存在** `<程序目录>/模型/`，每次启动再拷到上游读的位置；
* **安装版 / 文件夹版**：`_MEIPASS` 就是 `<程序目录>/_internal`，同样走"缓存 + 拷贝"这一套，
  这样自动更新覆盖程序文件时模型也不会丢。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import time
from typing import Callable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MODEL_NAME = "hivision_modnet.onnx"
MODEL_SIZE = 25888609
MODEL_SHA256 = "7e0cb9a2a841b426dd0daf1a788ec398dab059bc039041d62b15636c0783bc56"
MODEL_URL = ("https://github.com/Zeyi-Lin/HivisionIDPhotos/releases/download/"
             "pretrained-model/hivision_modnet.onnx")
# 和下载更新包一样：直连 GitHub Release 在某些网络会 SSL 中断，按顺序回退公共反代
MIRRORS: Tuple[str, ...] = ("", "https://gh-proxy.com/", "https://ghfast.top/",
                            "https://ghproxy.net/")
CHUNK = 256 * 1024
CACHE_DIR_NAME = "模型"          # <程序目录>/模型/hivision_modnet.onnx
UA = "idphoto-layout-studio/weights-downloader"


class WeightsError(Exception):
    """下载 / 校验 / 放置失败。"""


class WeightsCancelled(Exception):
    """用户取消了下载。"""


# ---------------------------------------------------------------- 路径
def app_dir() -> str:
    """程序目录 —— **统一走 paths.app_dir()**。

    以前这里自己写了 dirname(dirname(__file__))，在源码运行时算出来是 <项目>\app
    而不是项目根（少了一级），于是模型缓存被丢进 pp\模型\。别在这里另起一套。
    """
    from ..paths import app_dir as _paths_app_dir
    return _paths_app_dir()


def cache_dir() -> str:
    """长期存放模型的目录（程序目录下，不碰 C 盘）。"""
    return os.path.join(app_dir(), CACHE_DIR_NAME)


def cache_path() -> str:
    return os.path.join(cache_dir(), MODEL_NAME)


def target_path() -> str:
    """上游实际会去读的路径：`<hivision 包>/creator/weights/hivision_modnet.onnx`。"""
    try:
        import hivision.creator as _creator
        base = os.path.dirname(os.path.abspath(_creator.__file__))
    except Exception:                                      # noqa: BLE001
        base = os.path.join(app_dir(), "_internal", "hivision", "creator")
        if not os.path.isdir(base):
            base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "vendor", "hivision", "creator")
    return os.path.join(base, "weights", MODEL_NAME)


def _ok(path: str) -> bool:
    """文件存在且大小对得上（不验 sha256，启动路径上别做 I/O 密集的事）。"""
    try:
        return os.path.getsize(path) == MODEL_SIZE
    except OSError:
        return False


def in_place() -> bool:
    """上游读的位置上已有模型。"""
    return _ok(target_path())


def cached() -> bool:
    return _ok(cache_path())


def needs_download() -> bool:
    """要不要弹"首次启动下载模型"那个窗口。"""
    return not in_place() and not cached()


def ensure_placed() -> bool:
    """把缓存里的模型拷到上游读的位置。已有就什么都不做。

    返回 True 表示现在可以用了。
    """
    target = target_path()
    if _ok(target):
        return True
    src = cache_path()
    if not _ok(src):
        return False
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp = target + ".part"
        shutil.copyfile(src, tmp)
        os.replace(tmp, target)                            # 尽量原子
        return True
    except Exception:                                      # noqa: BLE001
        return False


# ---------------------------------------------------------------- 下载
def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def download(progress: Optional[Callable[[int, int], None]] = None,
             should_stop: Optional[Callable[[], bool]] = None,
             mirrors: Optional[Sequence[str]] = None, timeout: float = 60.0) -> str:
    """下载模型到缓存目录并校验大小 + sha256，然后放到上游读的位置。

    `progress(已下字节, 总字节)`。返回模型路径。
    """
    mirrors = MIRRORS if mirrors is None else mirrors     # 别把 MIRRORS 当默认参数（定义时求值）
    os.makedirs(cache_dir(), exist_ok=True)
    dest = cache_path()
    errors: List[str] = []
    for prefix in mirrors:
        url = (prefix + MODEL_URL) if prefix else MODEL_URL
        try:
            req = Request(url, headers={"User-Agent": UA})
            with urlopen(req, timeout=timeout) as resp:     # noqa: S310
                total = int(resp.headers.get("Content-Length") or MODEL_SIZE)
                done = 0
                with open(dest, "wb") as f:
                    while True:
                        if should_stop and should_stop():
                            raise WeightsCancelled("已取消下载")
                        block = resp.read(CHUNK)
                        if not block:
                            break
                        f.write(block)
                        done += len(block)
                        if progress:
                            progress(done, total)
            got = os.path.getsize(dest)
            if got != MODEL_SIZE:
                raise ValueError("大小不对：%d != %d" % (got, MODEL_SIZE))
            if sha256_file(dest).lower() != MODEL_SHA256:
                raise ValueError("sha256 校验失败")
            if not ensure_placed():
                raise WeightsError("模型下好了，但没法放到程序目录：%s" % target_path())
            return target_path()
        except WeightsCancelled:
            try:
                os.remove(dest)
            except OSError:
                pass
            raise
        except Exception as e:                              # noqa: BLE001
            errors.append("%s -> %s" % (url, e))
            try:
                os.remove(dest)
            except OSError:
                pass
    raise WeightsError("模型下载失败（直连和镜像都不通）：\n" + "\n".join(errors[-3:]))


# ---------------------------------------------------------------- 文案
def human_size(n: float) -> str:
    if n < 1024:
        return "%d B" % n
    for unit in ("KB", "MB", "GB"):
        n /= 1024.0
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit)
    return "%.1f GB" % n


def human_eta(seconds: float) -> str:
    if seconds <= 0 or seconds != seconds or seconds > 86400:   # NaN / 太大
        return "—"
    s = int(round(seconds))
    if s < 60:
        return "%d 秒" % s
    if s < 3600:
        return "%d 分 %02d 秒" % (s // 60, s % 60)
    return "%d 小时 %d 分" % (s // 3600, (s % 3600) // 60)


class SpeedMeter:
    """滑动窗口测速 + 估算剩余时间（第一次调用只记录基线）。"""

    def __init__(self, window: float = 2.0):
        self.window = window
        self._samples: List[Tuple[float, int]] = []

    def push(self, done: int, total: int = 0, now: Optional[float] = None) -> Tuple[float, float]:
        """返回 (字节/秒, 剩余秒数)；样本不足时速度为 0、剩余为 -1。"""
        t = time.monotonic() if now is None else now
        self._samples.append((t, done))
        while len(self._samples) > 2 and t - self._samples[0][0] > self.window:
            self._samples.pop(0)
        if len(self._samples) < 2:
            return 0.0, -1.0
        t0, d0 = self._samples[0]
        dt = t - t0
        if dt <= 0:
            return 0.0, -1.0
        speed = max(0.0, (done - d0) / dt)
        if total > 0 and speed > 0:
            return speed, max(0.0, (total - done) / speed)
        return speed, -1.0


def progress_text(done: int, total: int, speed: float = 0.0, eta: float = -1.0,
                  prefix: str = "") -> str:
    """拼一行「已下/总量 · 速度 · 剩余」。下载窗口和更新窗口共用。"""
    parts = []
    if total > 0:
        parts.append("%s / %s" % (human_size(done), human_size(total)))
    else:
        parts.append(human_size(done))
    if speed > 0:
        parts.append("%s/s" % human_size(speed))
        if eta >= 0:
            parts.append("剩 %s" % human_eta(eta))
    elif done <= 0:
        parts.append("正在连接…")
    return (prefix + "　".join(parts)) if prefix else "　".join(parts)
