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

# 自定义更新源（静态 update.json）：默认给的是用户自己的节点，可在 settings.json 里改/加。
# 这类静态源**不走 gh-proxy**（那些代理只对 GitHub 有用）。
DEFAULT_SOURCE_NAME = "自建节点"

UA = "idphoto-layout-studio-updater/1.0 (+https://github.com/%s)" % REPO
CHUNK = 256 * 1024
UPDATE_DIR_NAME = "_update"
STATE_FILE_NAME = ".update_state.json"
CHECK_INTERVAL_S = 24 * 3600        # 启动时自动检查的间隔（24 小时）
PROBE_TIMEOUT_S = 8.0               # 单源测速超时
SLOW_PROBE_MS = 4000.0              # 超过这个延迟就提示"网络较慢"

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
    source: str = ""                 # 这次从哪个源下的（写进更新日志，方便排查）
    latency_ms: float = 0.0

    def to_dict(self) -> Dict:
        return {"mode": self.mode, "staging": self.staging,
                "target_dir": self.target_dir, "target_exe": self.target_exe,
                "payload": self.payload, "version": self.version,
                "created": self.created, "source": self.source,
                "latency_ms": self.latency_ms}

    @classmethod
    def from_dict(cls, d: Dict) -> "UpdatePlan":
        return cls(mode=d["mode"], staging=d["staging"], target_dir=d["target_dir"],
                   target_exe=d["target_exe"], payload=d["payload"],
                   version=d.get("version", ""), created=d.get("created", 0.0),
                   source=d.get("source", ""),
                   latency_ms=float(d.get("latency_ms") or 0.0))


# ============================================================== 当前安装形态
def app_dir() -> str:
    """程序目录 —— **统一走 paths.app_dir()**（打包后是 exe 所在目录）。"""
    from ..paths import app_dir as _paths_app_dir
    return _paths_app_dir()


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
    req = Request(url, headers={"User-Agent": UA,
                                "Accept": "application/json, */*",
                                "Cache-Control": "no-cache"})
    with urlopen(req, timeout=timeout) as resp:            # noqa: S310 (地址来自常量/设置)
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


# ============================================================== 更新源 + 测速
@dataclass
class Source:
    """一个更新源。

    * `kind="github"`  → url 是 GitHub 的 releases/latest API；
      资产地址就是 `browser_download_url`，下载时还可以套 gh-proxy 反代。
    * `kind="manifest"`→ url 是一个**静态** JSON（见 `parse_manifest`），
      通常放在自己的服务器/对象存储上；资产地址支持相对路径。
    """
    name: str
    kind: str
    url: str

    @property
    def is_github(self) -> bool:
        return self.kind == "github"

    def __str__(self) -> str:                              # 界面上直接显示
        return self.name


@dataclass
class SourceResult:
    source: Source
    latency_ms: float = 0.0
    info: Optional[ReleaseInfo] = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.info is not None and not self.error


@dataclass
class BestRelease:
    """权衡之后选中的源 + 它的 release 信息。"""
    info: ReleaseInfo
    source: Source
    latency_ms: float
    candidates: List[SourceResult] = field(default_factory=list)

    @property
    def latency_text(self) -> str:
        return "%d ms" % int(self.latency_ms)


def default_sources(extra: Optional[Sequence[str]] = None) -> List[Source]:
    """GitHub + GitHub 镜像 + 设置里的自定义静态源（`update_sources` 里的 URL）。

    **为什么要带一个 GitHub 镜像源**：GitHub 的 API 未登录时限流 60 次/小时/IP，
    超了直接 403 —— 实测在家用网络里连续检查几次就会撞上。gh-proxy 能正常代理这个 API
    （实测 1.5s 左右拿到 tag），所以把它也当成一个"源"一起测速，直连被限流时还有得用。
    """
    sources = [Source("GitHub", "github", API_LATEST)]
    try:
        sources.append(Source("GitHub 镜像", "github", MIRRORS[1] + API_LATEST))
    except IndexError:                                     # 理论上不会发生
        pass
    urls = list(extra or [])
    if not urls:
        try:
            from . import settings
            urls = settings.get_update_sources()
        except Exception:                                  # noqa: BLE001
            urls = []
    for i, url in enumerate(urls):
        url = str(url or "").strip()
        if not url:
            continue
        if url.endswith("/releases/latest") or url == API_LATEST:
            continue
        sources.append(Source("%s %d" % (DEFAULT_SOURCE_NAME, i + 1)
                              if len(urls) > 1 else DEFAULT_SOURCE_NAME,
                              "manifest", url))
    return sources


def probe_and_fetch(source: Source, timeout: float = PROBE_TIMEOUT_S) -> SourceResult:
    """请求一次源，返回 (延迟, 解析结果)。**一次请求同时完成"测速"和"取版本"**。"""
    t0 = time.perf_counter()
    try:
        raw = _get(source.url, timeout)
        latency = (time.perf_counter() - t0) * 1000.0
        payload = json.loads(raw.decode("utf-8", "replace"))
        if source.is_github:
            info = parse_release(payload)
        else:
            info = parse_manifest(payload, base_url=source.url)
        if not info.version:
            return SourceResult(source, latency, None, "源里没有版本号")
        return SourceResult(source, latency, info, "")
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as e:
        return SourceResult(source, (time.perf_counter() - t0) * 1000.0, None,
                            "%s: %s" % (type(e).__name__, e))


def probe_sources(sources: Sequence[Source],
                  timeout: float = PROBE_TIMEOUT_S) -> List[SourceResult]:
    """并发探测所有源（别串起来等，慢源会把快的拖死）。"""
    from concurrent.futures import ThreadPoolExecutor

    if not sources:
        return []
    with ThreadPoolExecutor(max_workers=min(4, len(sources))) as pool:
        futures = [pool.submit(probe_and_fetch, s, timeout) for s in sources]
        return [f.result() for f in futures]


def fetch_latest_best(sources: Optional[Sequence[Source]] = None,
                      timeout: float = PROBE_TIMEOUT_S) -> BestRelease:
    """所有源一起测速，挑**延迟最低且确实报出版本号**的那个。

    一个源挂了不影响别的；全挂才抛错（错误信息里带上每个源的原因）。
    """
    srcs = list(sources or default_sources())
    results = probe_sources(srcs, timeout)
    healthy = [r for r in results if r.ok]
    if not healthy:
        detail = "\n".join("  %s -> %s" % (r.source.name, r.error or "无数据")
                           for r in results) or "  （没有配置任何源）"
        raise URLError("检查更新失败：所有更新源都不通\n" + detail)
    # 延迟低的优先；延迟相同则版本高的优先
    healthy.sort(key=lambda r: (r.latency_ms, -parse_version(r.info.version)[0]))
    best = healthy[0]
    return BestRelease(info=best.info, source=best.source,
                       latency_ms=best.latency_ms, candidates=results)


def parse_manifest(payload: Dict, base_url: str = "") -> ReleaseInfo:
    """解析自定义静态源的 `update.json`。

    ```json
    {
      "version": "1.6.1",
      "notes": "更新说明（Markdown）",
      "page_url": "https://github.com/.../releases/tag/v1.6.1",
      "assets": [
        {"name": "idphoto-layout-studio-v1.6.1-portable.zip",
         "url": "idphoto-layout-studio-v1.6.1-portable.zip",   // 相对路径也行
         "size": 137101385, "sha256": "…"}
      ]
    }
    ```
    为了宽容，也认 `assets` 里用 `browser_download_url` / `digest` 的写法（和 GitHub 一样）。
    """
    from urllib.parse import urljoin

    version = str(payload.get("version") or payload.get("tag_name") or "").lstrip("vV")
    assets: List[Asset] = []
    for a in payload.get("assets") or []:
        raw_url = str(a.get("url") or a.get("browser_download_url") or "")
        digest = str(a.get("digest") or "")
        sha = str(a.get("sha256") or "")
        if not sha and digest.lower().startswith("sha256:"):
            sha = digest.split(":", 1)[1]
        assets.append(Asset(name=str(a.get("name") or ""),
                            url=urljoin(base_url, raw_url) if raw_url else "",
                            size=int(a.get("size") or 0), sha256=sha))
    return ReleaseInfo(version=version,
                       tag=str(payload.get("tag") or ("v" + version if version else "")),
                       name=str(payload.get("name") or ("v" + version if version else "")),
                       notes=str(payload.get("notes") or payload.get("body") or ""),
                       page_url=str(payload.get("page_url") or payload.get("html_url")
                                    or RELEASES_PAGE),
                       assets=assets)


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
                   should_stop: Optional[Callable[[], bool]] = None,
                   source_name: str = "", latency_ms: float = 0.0) -> UpdatePlan:
    """下载资产、解压（zip）、写 apply.json，返回更新计划。

    调用方拿到计划后：`spawn_applier(plan)` 启动新版本进程，然后退出自己。
    `mirrors` 只对 GitHub 资产有意义（公共反代）；自建静态源传 `("",)`。
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
                          payload=new_exe, version=info.version,
                          source=source_name, latency_ms=latency_ms)
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
                          payload=staged, version=info.version,
                          source=source_name, latency_ms=latency_ms)

    with open(os.path.join(staging, "apply.json"), "w", encoding="utf-8") as f:
        json.dump(plan.to_dict(), f, ensure_ascii=False, indent=2)
    return plan


def prepare_update_best(sources: Optional[Sequence[Source]] = None,
                        kind: Optional[str] = None,
                        progress: Optional[Callable[[int, int], None]] = None,
                        should_stop: Optional[Callable[[], bool]] = None,
                        timeout: float = PROBE_TIMEOUT_S,
                        best: Optional[BestRelease] = None):
    """测速 → 用**延迟最低的源**下载；它要是失败就按延迟顺序换下一个源。

    返回 (UpdatePlan, BestRelease)。
    """
    best = best or fetch_latest_best(sources, timeout)
    order = sorted([r for r in best.candidates if r.ok], key=lambda r: r.latency_ms)
    if not order:
        order = [SourceResult(best.source, best.latency_ms, best.info, "")]
    errors = []
    for r in order:
        try:
            plan = prepare_update(
                r.info, kind=kind, progress=progress, should_stop=should_stop,
                mirrors=MIRRORS if r.source.is_github else ("",),
                source_name=r.source.name, latency_ms=r.latency_ms)
            return plan, BestRelease(info=r.info, source=r.source,
                                     latency_ms=r.latency_ms,
                                     candidates=best.candidates)
        except UpdateCancelled:
            raise
        except Exception as e:                             # noqa: BLE001
            errors.append("%s（%d ms）-> %s" % (r.source.name, int(r.latency_ms), e))
    raise URLError("下载失败：所有更新源都没成功\n" + "\n".join(errors))


def applier_exe(plan: UpdatePlan) -> str:
    """该用哪个 exe 来执行"等旧进程退出 → 覆盖 → 重启"。"""
    if plan.mode == "replace-exe":
        return plan.payload                       # 就是新版本自己的单文件 exe
    root = plan.payload
    for name in sorted(os.listdir(root)):
        if name.lower().endswith(".exe") and not name.lower().startswith("unins"):
            return os.path.join(root, name)
    raise FileNotFoundError("解压后的目录里找不到 exe：%s" % root)


def spawn_applier(plan: UpdatePlan, old_pid: int = 0, ui: bool = False,
                  geom: Optional[Tuple[int, int, int, int]] = None) -> subprocess.Popen:
    """启动新版本进程执行覆盖，然后调用方应该马上退出。

    `old_pid` 是"当前正在运行的进程"，新进程会等它退出再覆盖文件。
    `ui=True` 时新版本会**弹一个进度窗口**（"正在合并 → 更新完成"），
    `geom=(x, y, w, h)` 让那个窗口出现在旧窗口的位置，看起来像同一个窗口在继续。
    """
    exe = applier_exe(plan)
    cfg = os.path.join(plan.staging, "apply.json")
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200   # DETACHED | NEW_PROCESS_GROUP
        if ui:
            # 本进程此刻是前台窗口，有权把"抢焦点"的许可转授给马上要起来的合并进程；
            # 否则它的小窗会被 Windows 的前台锁按在浏览器后面（用户只会觉得"没反应"）。
            try:
                import ctypes
                ctypes.windll.user32.AllowSetForegroundWindow(-1)   # ASFW_ANY
            except Exception:                              # noqa: BLE001
                pass
    argv = [exe, "--apply-update", cfg, "--old-pid", str(int(old_pid or 0))]
    if ui:
        argv.append("--ui")
        if geom:
            argv += ["--geom", "%d,%d,%d,%d" % geom]
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


def _copy_tree(src: str, dst: str,
               progress: Optional[Callable[[int, int], None]] = None) -> List[str]:
    """把 src 覆盖拷到 dst（**只覆盖，不删除** dst 里已有的东西）。返回拷贝的文件列表。

    `progress(已完成文件数, 总文件数)`：合并进度条用（先数一遍，再逐个拷）。
    """
    plan: List[tuple] = []
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target_root = dst if rel == "." else os.path.join(dst, rel)
        for name in files:
            plan.append((os.path.join(root, name), target_root, name))
    total = len(plan)
    copied: List[str] = []
    for i, (s, target_root, name) in enumerate(plan):
        os.makedirs(target_root, exist_ok=True)
        t = os.path.join(target_root, name)
        tmp = t + ".new"
        try:
            shutil.copyfile(s, tmp)
            os.replace(tmp, t)                             # 尽量原子
        except Exception:                                  # noqa: BLE001
            # 单个文件拷不动（被占用/权限）不能连累整体，清掉半成品继续
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        copied.append(t)
        if progress:
            progress(i + 1, total)
    return copied


def apply_plan(plan: UpdatePlan, old_pid: int = 0, timeout: float = 120.0,
               progress: Optional[Callable[[int, int], None]] = None) -> Dict:
    """真正的覆盖动作（在新版本进程里执行）。返回结果字典，便于 CLI 打印/测试断言。

    约定：`error` 表示**更新本身没做成**；`restart_error` 表示"覆盖成功了但没拉起来"
    （这时应该告诉用户"已更新，请手动打开"，而不是当失败）。
    `progress(已完成文件数, 总文件数)` 给"正在合并"那个窗口用。
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
            if progress:
                progress(0, 1)
            tmp = target + ".new"
            shutil.copyfile(plan.payload, tmp)
            os.replace(tmp, target)
            result["copied"] = [target]
            if progress:
                progress(1, 1)
        else:
            result["copied"] = _copy_tree(plan.payload, plan.target_dir, progress)
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
