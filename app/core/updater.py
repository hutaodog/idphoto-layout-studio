# -*- coding: utf-8 -*-
"""检查更新 / 下载 / 自我替换（**不依赖 Qt**，方便单测）。

工作方式（和用户诉求对应："检测到新版本 → 点击更新 → 自动从 GitHub 下载"）：

1. **查**：GET `api.github.com/repos/hutaodog/idphoto-layout-studio/releases/latest`，
   取 `tag_name`（如 `v1.6.0`）、`body`（更新说明）、`assets[]`（含大小与 `digest` 的 sha256）。
   直连不通时按 `MIRRORS` 里的代理前缀重试（国内常连不上 api.github.com）。
2. **比**：`is_newer(远端, 本地)` —— 本地版本来自 `app.__version__`。
3. **下**：按"当前是哪种打包形式"挑资产（单文件 / 便携 zip），流式下载并显示进度，
   下载完**校验大小 + sha256**（GitHub Release API 的 `digest` 字段就是 sha256）。
4. **装**：**不自己覆盖自己**（Windows 锁着正在运行的 exe）。做法是把下载好的新版本
   复制到 `_update/`，写一份 `apply.json`，然后启动**新版本自己的 exe** 并带上
   `--apply-update <apply.json>`；本进程随即退出。新进程等的就是这个退出，然后：
   * 单文件版：把新 exe 拷到目标位置（tmp + os.replace，尽量原子）；
   * 文件夹版 / 安装版：把解压好的新内容覆盖到程序目录（**只覆盖不删除**，用户自己的
     `输出/`、`_update/` 都保留），再重新启动程序。
5. 清理：`_update/` 里正在运行的 exe 删不掉，所以改名后留给下次启动清理
   （`cleanup_stale()`）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO = "hutaodog/idphoto-layout-studio"
API_LATEST = "https://api.github.com/repos/%s/releases/latest" % REPO
RELEASES_PAGE = "https://github.com/%s/releases/latest" % REPO

# GitHub 在部分网络下连不上/很慢，按顺序回退到这些公共反代（与 download_weights.ps1 一致）
MIRRORS: Tuple[str, ...] = ("", "https://gh-proxy.com/", "https://ghfast.top/",
                            "https://ghproxy.net/")

UA = "idphoto-layout-studio-updater/1.0 (+https://github.com/%s)" % REPO
CHUNK = 256 * 1024
UPDATE_DIR_NAME = "_update"
STATE_FILE_NAME = ".update_state.json"
CHECK_INTERVAL_S = 24 * 3600        # 启动时自动检查的间隔（24 小时）

_FROZEN = bool(getattr(sys, "frozen", False))


class UpdateCancelled(Exception):
    """用户中途取消了下载/更新。"""


# ============================================================== 版本号
def parse_version(text: str) -> Tuple[int, ...]:
    """`v1.6.0` / `1.6` / `1.6.0-beta` → (1, 6, 0)。

    只取前三段数字，忽略后缀；解析不出来就当 (0,)。
    """
    m = re.search(r"(\d+(?:\.\d+)*)", str(text or ""))
    if not m:
        return (0,)
    parts = [int(p) for p in m.group(1).split(".")[:3]]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(remote: str, local: str) -> bool:
    """远端版本是否比本地新（严格大于）。"""
    return parse_version(remote) > parse_version(local)


# ============================================================== 数据模型
@dataclass
class Asset:
    name: str
    url: str
    size: int = 0
    sha256: str = ""

    @property
    def mb(self) -> float:
        return round(self.size / 1048576.0, 1)


@dataclass
class ReleaseInfo:
    version: str
    tag: str = ""
    name: str = ""
    notes: str = ""
    page_url: str = RELEASES_PAGE
    assets: List[Asset] = field(default_factory=list)

    def asset_named(self, suffix: str) -> Optional[Asset]:
        for a in self.assets:
            if a.name.lower().endswith(suffix.lower()):
                return a
        return None


@dataclass
class UpdatePlan:
    """一次更新的执行计划（会被写成 apply.json 交给新进程）。"""
    mode: str                        # "replace-exe" | "extract-copy"
    staging: str                     # _update 目录
    target_dir: str                  # 程序目录
    target_exe: str                  # 需要重启的程序 exe
    payload: str                     # 新 exe 或解压后的目录
    version: str = ""
    created: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {"mode": self.mode, "staging": self.staging,
                "target_dir": self.target_dir, "target_exe": self.target_exe,
                "payload": self.payload, "version": self.version,
                "created": self.created}

    @classmethod
    def from_dict(cls, d: Dict) -> "UpdatePlan":
        return cls(mode=d["mode"], staging=d["staging"], target_dir=d["target_dir"],
                   target_exe=d["target_exe"], payload=d["payload"],
                   version=d.get("version", ""), created=d.get("created", 0.0))


# ============================================================== 当前安装形态
def app_dir() -> str:
    if _FROZEN:
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build_kind() -> str:
    """当前是哪种打包形式：single（单文件）/ folder（文件夹版）/ source（源码运行）。"""
    if not _FROZEN:
        return "source"
    meipass = getattr(sys, "_MEIPASS", "")
    if not meipass:
        return "folder"
    # 文件夹版：_MEIPASS 就是 exe 旁边的 _internal；单文件版：_MEIPASS 在临时目录里
    return "folder" if os.path.dirname(os.path.abspath(meipass)) == app_dir() else "single"


def is_installed() -> bool:
    """是不是用安装包装的（程序目录里有 Inno Setup 的卸载器）。"""
    try:
        return any(n.lower().startswith("unins") and n.lower().endswith(".exe")
                   for n in os.listdir(app_dir()))
    except OSError:
        return False


def update_dir() -> str:
    return os.path.join(app_dir(), UPDATE_DIR_NAME)


# ============================================================== 状态（自动检查开关等）
def state_path() -> str:
    """状态文件放程序目录；不可写就放日志目录（paths.log_dir 会兜底）。"""
    d = app_dir()
    try:
        probe = os.path.join(d, ".w")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
    except Exception:                                      # noqa: BLE001
        from .paths import log_dir
        d = log_dir()
    return os.path.join(d, STATE_FILE_NAME)


def load_state() -> Dict:
    defaults = {"auto_check": True, "last_check": 0.0, "skipped": ""}
    try:
        with open(state_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            defaults.update({k: data[k] for k in defaults if k in data})
    except Exception:                                      # noqa: BLE001
        pass
    return defaults


def save_state(**kw) -> Dict:
    st = load_state()
    st.update(kw)
    try:
        with open(state_path(), "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
    except Exception:                                      # noqa: BLE001
        pass
    return st


def should_auto_check(state: Optional[Dict] = None) -> bool:
    """启动时该不该自动查一次（开关打开 + 距上次检查超过 24 小时）。"""
    st = state if state is not None else load_state()
    if not st.get("auto_check", True):
        return False
    return (time.time() - float(st.get("last_check") or 0)) > CHECK_INTERVAL_S


# ============================================================== 网络
def _get(url: str, timeout: float) -> bytes:
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    with urlopen(req, timeout=timeout) as resp:            # noqa: S310 (固定 https 地址)
        return resp.read()


def fetch_latest(timeout: float = 20.0, url: str = API_LATEST,
                 mirrors: Sequence[str] = MIRRORS) -> ReleaseInfo:
    """取 latest release 信息；直连失败按镜像前缀重试。"""
    errors = []
    for prefix in mirrors:
        target = (prefix + url) if prefix else url
        try:
            raw = _get(target, timeout)
            return parse_release(json.loads(raw.decode("utf-8")))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as e:
            errors.append("%s -> %r" % (target, e))
    raise URLError("检查更新失败（直连和镜像都不通）：\n" + "\n".join(errors[-3:]))


def parse_release(payload: Dict) -> ReleaseInfo:
    """把 GitHub release JSON 转成 ReleaseInfo（顺带兼容没有 digest 的老接口）。"""
    tag = str(payload.get("tag_name") or payload.get("name") or "")
    assets: List[Asset] = []
    for a in payload.get("assets") or []:
        digest = str(a.get("digest") or "")
        sha = digest.split(":", 1)[1] if digest.lower().startswith("sha256:") else ""
        assets.append(Asset(name=str(a.get("name") or ""),
                            url=str(a.get("browser_download_url") or ""),
                            size=int(a.get("size") or 0), sha256=sha))
    return ReleaseInfo(version=tag.lstrip("vV"),
                       tag=tag,
                       name=str(payload.get("name") or tag),
                       notes=str(payload.get("body") or ""),
                       page_url=str(payload.get("html_url") or RELEASES_PAGE),
                       assets=assets)


def pick_asset(info: ReleaseInfo, kind: Optional[str] = None) -> Optional[Asset]:
    """按当前打包形式挑要下的资产。

    * 单文件版 → `-onefile.exe`
    * 文件夹版 / 安装版 → `-portable.zip`（覆盖解压即可，安装版的 unins* 会保留）
    * 源码运行 → 不自动更新（返回 None，由 UI 提示去 Release 页面）
    """
    kind = kind or build_kind()
    if kind == "source":
        return None
    want = "-onefile.exe" if kind == "single" else "-portable.zip"
    asset = info.asset_named(want)
    if asset is None and info.assets:                      # 名字对不上时退而求其次
        asset = info.assets[0]
    return asset


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def download(url: str, dest: str, size: int = 0, sha256: str = "",
             progress: Optional[Callable[[int, int], None]] = None,
             timeout: float = 60.0, mirrors: Sequence[str] = MIRRORS,
             should_stop: Optional[Callable[[], bool]] = None) -> str:
    """下载并校验（大小 + sha256）。progress(已下字节, 总字节)；总字节未知时为 0。

    直连失败会按镜像前缀重试；校验不通过会删掉半成品再抛异常；
    `should_stop()` 返回 True 时抛 `UpdateCancelled`（UI 的"取消"用）。
    """
    os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
    errors = []
    for prefix in mirrors:
        target = (prefix + url) if prefix else url
        try:
            req = Request(target, headers={"User-Agent": UA})
            with urlopen(req, timeout=timeout) as resp:    # noqa: S310
                total = int(resp.headers.get("Content-Length") or size or 0)
                done = 0
                with open(dest, "wb") as f:
                    while True:
                        if should_stop and should_stop():
                            raise UpdateCancelled("已取消下载")
                        block = resp.read(CHUNK)
                        if not block:
                            break
                        f.write(block)
                        done += len(block)
                        if progress:
                            progress(done, total)
            got = os.path.getsize(dest)
            if size and got != size:
                raise ValueError("大小不对：%d != %d" % (got, size))
            if sha256:
                actual = sha256_file(dest)
                if actual.lower() != sha256.lower():
                    raise ValueError("sha256 不对：%s != %s" % (actual, sha256))
            return dest
        except UpdateCancelled:
            try:
                os.remove(dest)
            except OSError:
                pass
            raise
        except Exception as e:                             # noqa: BLE001
            errors.append("%s -> %r" % (target, e))
            try:
                os.remove(dest)
            except OSError:
                pass
    raise URLError("下载失败（直连和镜像都不通）：\n" + "\n".join(errors[-3:]))


# ============================================================== 准备（下载 + 解压 + 写计划）
def prepare_update(info: ReleaseInfo, kind: Optional[str] = None,
                   progress: Optional[Callable[[int, int], None]] = None,
                   mirrors: Sequence[str] = MIRRORS,
                   should_stop: Optional[Callable[[], bool]] = None) -> UpdatePlan:
    """下载资产、解压（zip）、写 apply.json，返回更新计划。

    调用方拿到计划后：`spawn_applier(plan)` 启动新版本进程，然后退出自己。
    """
    kind = kind or build_kind()
    asset = pick_asset(info, kind)
    if asset is None:
        raise ValueError("源码运行不自动更新，请到 %s 手动下载" % RELEASES_PAGE)

    staging = update_dir()
    os.makedirs(staging, exist_ok=True)
    dest = os.path.join(staging, asset.name)
    download(asset.url, dest, size=asset.size, sha256=asset.sha256,
             progress=progress, mirrors=mirrors, should_stop=should_stop)

    target_dir = app_dir()
    me = os.path.abspath(sys.executable) if _FROZEN else \
        os.path.join(target_dir, "app", "main.py")
    if kind == "single":
        new_exe = os.path.join(staging, "new.exe")
        shutil.copyfile(dest, new_exe)
        plan = UpdatePlan(mode="replace-exe", staging=staging,
                          target_dir=target_dir, target_exe=me,
                          payload=new_exe, version=info.version)
    else:
        staged = os.path.join(staging, "staged")
        if os.path.isdir(staged):
            shutil.rmtree(staged, ignore_errors=True)
        os.makedirs(staged, exist_ok=True)
        if asset.name.lower().endswith(".zip"):
            with zipfile.ZipFile(dest) as zf:
                zf.extractall(staged)
        else:
            shutil.copyfile(dest, os.path.join(staged, asset.name))
        plan = UpdatePlan(mode="extract-copy", staging=staging,
                          target_dir=target_dir, target_exe=me,
                          payload=staged, version=info.version)

    with open(os.path.join(staging, "apply.json"), "w", encoding="utf-8") as f:
        json.dump(plan.to_dict(), f, ensure_ascii=False, indent=2)
    return plan


def applier_exe(plan: UpdatePlan) -> str:
    """该用哪个 exe 来执行"等旧进程退出 → 覆盖 → 重启"。"""
    if plan.mode == "replace-exe":
        return plan.payload                       # 就是新版本自己的单文件 exe
    root = plan.payload
    for name in sorted(os.listdir(root)):
        if name.lower().endswith(".exe") and not name.lower().startswith("unins"):
            return os.path.join(root, name)
    raise FileNotFoundError("解压后的目录里找不到 exe：%s" % root)


def spawn_applier(plan: UpdatePlan, old_pid: int = 0) -> subprocess.Popen:
    """启动新版本进程执行覆盖，然后调用方应该马上退出。

    `old_pid` 是"当前正在运行的进程"，新进程会等它退出再覆盖文件。
    """
    exe = applier_exe(plan)
    cfg = os.path.join(plan.staging, "apply.json")
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200   # DETACHED | NEW_PROCESS_GROUP
    argv = [exe, "--apply-update", cfg, "--old-pid", str(int(old_pid or 0))]
    return subprocess.Popen(argv, close_fds=True, **kwargs)


# ============================================================== 落地（在新进程里跑）
def wait_for_pid(pid: int, timeout: float = 120.0) -> bool:
    """等旧进程退出。pid<=0 视为没有旧进程，直接返回 True。"""
    if pid <= 0:
        return True
    end = time.time() + timeout
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x00100000
        while time.time() < end:
            handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
            if not handle:
                return True                                # 已经没了（或没权限）
            try:
                # WAIT_OBJECT_0 = 0 → 已退出
                if kernel32.WaitForSingleObject(handle, 300) == 0:
                    return True
            finally:
                kernel32.CloseHandle(handle)
            time.sleep(0.2)
        return False
    while time.time() < end:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.2)
    return False


def _copy_tree(src: str, dst: str) -> List[str]:
    """把 src 覆盖拷到 dst（**只覆盖，不删除** dst 里已有的东西）。返回拷贝的文件列表。"""
    copied = []
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target_root = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target_root, exist_ok=True)
        for name in files:
            s = os.path.join(root, name)
            t = os.path.join(target_root, name)
            tmp = t + ".new"
            shutil.copyfile(s, tmp)
            os.replace(tmp, t)                             # 尽量原子
            copied.append(t)
    return copied


def apply_plan(plan: UpdatePlan, old_pid: int = 0, timeout: float = 120.0) -> Dict:
    """真正的覆盖动作（在新版本进程里执行）。返回结果字典，便于 CLI 打印/测试断言。

    约定：`error` 表示**更新本身没做成**；`restart_error` 表示"覆盖成功了但没拉起来"
    （这时应该告诉用户"已更新，请手动打开"，而不是当失败）。
    """
    result = {"waited": False, "mode": plan.mode, "copied": [], "restarted": False,
              "error": "", "restart_error": ""}
    try:
        result["waited"] = wait_for_pid(old_pid, timeout)
        if not result["waited"]:
            result["error"] = "旧版本进程没在 %d 秒内退出" % int(timeout)
            return result
        if plan.mode == "replace-exe":
            target = plan.target_exe
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
            tmp = target + ".new"
            shutil.copyfile(plan.payload, tmp)
            os.replace(tmp, target)
            result["copied"] = [target]
        else:
            result["copied"] = _copy_tree(plan.payload, plan.target_dir)
    except Exception as e:                                 # noqa: BLE001
        result["error"] = "%r" % (e,)
        return result
    # 重启（先起，再清理由它占着的临时目录）
    try:
        if os.path.exists(plan.target_exe):
            kwargs = {}
            if os.name == "nt":
                kwargs["creationflags"] = 0x00000008
            subprocess.Popen([plan.target_exe], close_fds=True, cwd=plan.target_dir,
                             **kwargs)
            result["restarted"] = True
    except Exception as e:                                 # noqa: BLE001
        result["restart_error"] = "%r" % (e,)
    try:
        shutil.rmtree(plan.staging, ignore_errors=True)
    except Exception:                                      # noqa: BLE001
        pass
    return result


def cleanup_stale() -> int:
    """清掉上次更新留下的临时文件（正在运行的 exe 当时删不掉）。

    返回清掉的条目数。启动时调用一次即可。
    """
    removed = 0
    base = app_dir()
    try:
        names = list(os.listdir(base))
    except OSError:
        return 0
    for name in names:
        if name == UPDATE_DIR_NAME or name.startswith(UPDATE_DIR_NAME + "_old"):
            p = os.path.join(base, name)
            try:
                shutil.rmtree(p)
                removed += 1
            except Exception:                              # noqa: BLE001
                pass                                       # 还占着就下次再清
    for name in names:
        if name.endswith(".new"):
            try:
                os.remove(os.path.join(base, name))
                removed += 1
            except OSError:
                pass
    return removed
