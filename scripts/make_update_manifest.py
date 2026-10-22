# -*- coding: utf-8 -*-
"""把打包好的产物整理成"自建更新节点"需要的文件（update.json + 三个更新包）。

用法（打包完成之后跑）：
    .\\.venv\\Scripts\\python.exe scripts\\make_update_manifest.py
    .\\.venv\\Scripts\\python.exe scripts\\make_update_manifest.py --notes-file _tmp\\release_notes.md

产物：`成品软件\\update\\` 目录，里面是
    update.json                                   ← 程序按这个判断有没有新版本
    idphoto-layout-studio-v<版本>-portable.zip
    idphoto-layout-studio-v<版本>-setup.exe
    idphoto-layout-studio-v<版本>-onefile.exe
把这个目录里的东西整份上传到你的服务器（默认 `http://8.133.208.128/update/`）就行 ——
程序的「检查更新」会同时给 GitHub 和你这个节点测速，谁快用谁。

注意：
* 文件名必须是 `-portable.zip` / `-setup.exe` / `-onefile.exe` 结尾（程序按后缀挑包）；
* update.json 里写的是**相对路径**，整目录搬走不用改内容；
* 一定要能让程序**匿名**读到（云盘面板需要登录的话，请放到静态目录或用直链）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BASE = "idphoto-layout-studio-v%s-%s"
# 中文产物名 → ASCII 名（和 GitHub Release 上的资产名保持一致）
PATTERNS = [
    ("portable", ("_portable_", "portable")),
    ("setup", ("_安装版_", "setup")),
    ("onefile", ("_v", "onefile")),
]


def read_version() -> str:
    from app import __version__
    return __version__


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(256 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def find_artifacts(src_dir: str, version: str) -> dict:
    """在成品目录里找到三个产物，返回 {kind: 源路径}。

    单文件版的 exe 在被打包脚本"标准名"时是不带版本号的（`证件照排版助手.exe`），
    所以不能只看名字里有没有版本号：除了 zip（便携版）和带"安装版/setup"的 exe，
    其余 exe 就按单文件版处理（带版本号的那个优先）。
    """
    found = {}
    exes = []
    for name in os.listdir(src_dir):
        low = name.lower()
        p = os.path.join(src_dir, name)
        if not os.path.isfile(p):
            continue
        if low.endswith(".zip") and ("portable" in low or "便携" in name):
            found.setdefault("portable", p)
        elif low.endswith(".exe") and ("安装" in name or "setup" in low or "unins" in low):
            if "unins" not in low:
                found.setdefault("setup", p)
        elif low.endswith(".exe"):
            exes.append(p)
    if exes:
        with_ver = [p for p in exes if version in os.path.basename(p)]
        found.setdefault("onefile", sorted(with_ver or exes)[0])
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(ROOT, "成品软件"),
                    help="打包产物所在目录（默认 成品软件）")
    ap.add_argument("--out", default=os.path.join(ROOT, "成品软件", "update"),
                    help="输出目录（默认 成品软件\\update）")
    ap.add_argument("--version", default="", help="版本号（默认读 app/__init__.py）")
    ap.add_argument("--notes-file", default="", help="更新说明（Markdown 文件）")
    ap.add_argument("--notes", default="", help="更新说明（直接给文本，优先于 --notes-file）")
    ap.add_argument("--page-url", default="", help="「打开下载页面」跳转的地址")
    args = ap.parse_args()

    version = args.version or read_version()
    artifacts = find_artifacts(args.src, version)
    if not artifacts:
        print("!! 在 %s 里没找到打包产物，先跑 scripts\\package_release.ps1" % args.src)
        return 1

    os.makedirs(args.out, exist_ok=True)
    notes = args.notes
    if not notes and args.notes_file and os.path.exists(args.notes_file):
        notes = open(args.notes_file, encoding="utf-8").read()
    if not notes:
        notes = "## v%s\n\n（没有提供更新说明）" % version

    assets = []
    for kind, src in sorted(artifacts.items()):
        name = BASE % (version, kind + (".zip" if kind == "portable" else ".exe"))
        dst = os.path.join(args.out, name)
        shutil.copyfile(src, dst)
        size = os.path.getsize(dst)
        sha = sha256_of(dst)
        assets.append({"name": name, "url": name, "size": size, "sha256": sha})
        print("  %-46s %8.1f MB  %s" % (name, size / 1048576.0, sha[:16]))

    manifest = {
        "version": version,
        "tag": "v" + version,
        "name": "v%s" % version,
        "notes": notes,
        "page_url": args.page_url or
        "https://github.com/hutaodog/idphoto-layout-studio/releases/tag/v%s" % version,
        "assets": assets,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    out_json = os.path.join(args.out, "update.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print()
    print("update.json -> %s" % out_json)
    print("把 %s 里的全部文件上传到你的节点目录（默认 http://8.133.208.128/update/），" % args.out)
    print("确认能匿名访问 http://8.133.208.128/update/update.json 即可。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
