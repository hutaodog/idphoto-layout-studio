# -*- coding: utf-8 -*-
"""用户设置（持久化到程序目录下的 `settings.json`，**不碰 C 盘**）。

目前只有两件事：
* `out_dir` —— 用户自定义的输出目录。选过一次之后**重启也记得**；
  目录被删掉/不可写时自动退回默认（程序目录下的「输出」），不会卡在坏路径上。
* `update_sources` —— 自定义更新源（静态 `update.json` 的 URL 列表）。
  和 GitHub 一起参与测速，谁的延迟低用谁（见 `core/updater.py`）。

为方便手改，文件是缩进过的 UTF-8 JSON；写失败不抛异常（设置丢了不该让程序起不来）。
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

# 默认的自定义更新源：把 update.json 和更新包放到这个目录即可参与测速。
# （云盘面板要登录才能列目录，所以这里指的是**静态可匿名访问**的目录；
#   路径可以按实际部署改，改 settings.json 里的 update_sources 也行。）
DEFAULT_UPDATE_SOURCES: List[str] = [
    "http://8.133.208.128/update/update.json",
]

DEFAULTS: Dict[str, Any] = {
    "out_dir": "",
    "update_sources": list(DEFAULT_UPDATE_SOURCES),
}


def _base_dir() -> str:
    """设置文件放哪：程序目录；不可写就退到日志目录（paths.log_dir 会兜底）。"""
    from .paths import app_dir, log_dir
    d = app_dir()
    try:
        probe = os.path.join(d, ".w_settings")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return d
    except Exception:                                      # noqa: BLE001
        return log_dir()


def settings_path() -> str:
    return os.path.join(_base_dir(), "settings.json")


def load() -> Dict[str, Any]:
    data = dict(DEFAULTS)
    try:
        with open(settings_path(), "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            for k in DEFAULTS:
                if k in raw:
                    data[k] = raw[k]
    except Exception:                                      # noqa: BLE001
        pass
    if not isinstance(data.get("update_sources"), list):
        data["update_sources"] = list(DEFAULT_UPDATE_SOURCES)
    data["update_sources"] = [str(u) for u in data["update_sources"] if str(u).strip()]
    return data


def save(**kw) -> Dict[str, Any]:
    data = load()
    data.update({k: v for k, v in kw.items() if k in DEFAULTS})
    try:
        with open(settings_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:                                      # noqa: BLE001
        pass
    return data


# ---------------------------------------------------------------- 输出目录
def get_out_dir() -> str:
    """用户设过的输出目录；不可用（被删/没权限）就返回空串，让调用方用默认值。"""
    d = str(load().get("out_dir") or "").strip()
    if not d:
        return ""
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".write_probe")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return d
    except Exception:                                      # noqa: BLE001
        return ""


def set_out_dir(path: str) -> None:
    save(out_dir=str(path or "").strip())


# ---------------------------------------------------------------- 更新源
def get_update_sources() -> List[str]:
    return list(load().get("update_sources") or [])


def set_update_sources(urls: List[str]) -> None:
    save(update_sources=[str(u).strip() for u in urls if str(u).strip()])


def add_update_source(url: str) -> List[str]:
    url = (url or "").strip()
    urls = get_update_sources()
    if url and url not in urls:
        urls.append(url)
        set_update_sources(urls)
    return urls
