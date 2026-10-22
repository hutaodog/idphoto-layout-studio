# -*- coding: utf-8 -*-
"""把打包好的更新文件推到**自建更新节点**（用户自己的服务器）。

为什么用 Python 而不是 scp：Windows 自带 OpenSSH **不支持命令行传密码**，
而 `paramiko` 既能用密码也能用公钥，还能顺手装公钥、跑远程命令、校验结果。

用法（在项目根目录）：

    # 第一次（还没有公钥时）：用密码推 + 顺手把本机公钥装上去
    $env:SSH_PASS = '你的密码'
    .\\.venv\\Scripts\\python.exe scripts\\push_update_node.py --install-key

    # 以后（已装公钥，不再需要密码）
    .\\.venv\\Scripts\\python.exe scripts\\push_update_node.py

    # 只推某个版本 / 只推指定文件
    .\\.venv\\Scripts\\python.exe scripts\\push_update_node.py --src 成品软件\\update
    .\\.venv\\Scripts\\python.exe scripts\\push_update_node.py --only update.json

做的事：
1. 连服务器（优先公钥，没配才用 `SSH_PASS` 环境变量里的密码）；
2. 建远端目录（默认 `/www/wwwroot/pofuwuqi.cn/update`），把 `成品软件\\update\\` 里的文件
   一个个推上去（大文件走 `cat >` 流式写，比 SFTP 快不少，带进度）；
3. `chmod 644` + 有 `www` 用户就 `chown www:www`（nginx 以 www 运行）；
4. **自检**：从公网拉一次 `<base>/update.json`，确认 200、JSON 合法、版本号对得上。

节点地址（默认 `http://8.133.208.128/update/`）必须让程序能**匿名**读到 ——
这就是为什么不用云盘面板而用站点根目录下的静态目录。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DEFAULTS = {
    "host": "8.133.208.128",
    "port": 22,
    "user": "root",
    "remote_dir": "/www/wwwroot/pofuwuqi.cn/update",
    "base_url": "http://8.133.208.128/update/",
    "key": os.path.join(os.path.expanduser("~"), ".ssh", "id_ed25519"),
}


def log(msg: str) -> None:
    print(msg, flush=True)


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%.1f GB" % n


def connect(args):
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    key_path = os.path.expanduser(args.key)
    password = os.environ.get("SSH_PASS", "")
    tried = []
    if os.path.exists(key_path) and not args.password_only:
        try:
            client.connect(args.host, port=args.port, username=args.user,
                           key_filename=key_path, timeout=25,
                           allow_agent=False, look_for_keys=False)
            log("已用公钥登录：%s@%s（%s）" % (args.user, args.host, key_path))
            return client
        except Exception as e:                              # noqa: BLE001
            tried.append("公钥失败：%r" % (e,))
    if not password:
        raise SystemExit("没有可用的登录方式：\n  " + "\n  ".join(tried or
                         ["公钥不存在：" + key_path]) +
                         "\n请设置 SSH_PASS 环境变量，或用 --install-key 先装公钥。")
    client.connect(args.host, port=args.port, username=args.user,
                   password=password, timeout=25, allow_agent=False,
                   look_for_keys=False)
    log("已用密码登录：%s@%s" % (args.user, args.host))
    return client


def run(client, cmd: str, timeout: float = 120.0) -> str:
    _in, out, err = client.exec_command(cmd, timeout=timeout)
    text = out.read().decode("utf-8", "replace")
    etext = err.read().decode("utf-8", "replace").strip()
    if etext:
        log("    [stderr] " + etext[:300])
    return text


def install_key(client, key_path: str) -> None:
    """把本机公钥装到服务器上，以后就不用密码了。"""
    pub = key_path + ".pub"
    if not os.path.exists(pub):
        log("!! 找不到公钥 %s（先 ssh-keygen -t ed25519）" % pub)
        return
    line = open(pub, encoding="utf-8").read().strip()
    run(client, "mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys "
                "&& chmod 600 ~/.ssh/authorized_keys")
    exists = run(client, "grep -cF %s ~/.ssh/authorized_keys || true" % _shquote(line))
    if exists.strip() not in ("", "0"):
        log("公钥已经装过了 ✓")
        return
    run(client, "printf '%%s\\n' %s >> ~/.ssh/authorized_keys" % _shquote(line))
    log("公钥已装到 ~/.ssh/authorized_keys ✓（以后不用密码了）")


def _shquote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def upload_stream(client, local: str, remote: str, size: int) -> None:
    """用 `cat > 远端文件` 流式上传：一个 TCP 流，比 SFTP 一堆小请求快。"""
    chan = client.get_transport().open_session()
    chan.settimeout(300)
    chan.exec_command("cat > %s" % _shquote(remote))
    sent = 0
    t0 = time.time()
    last = 0.0
    with open(local, "rb") as f:
        while True:
            block = f.read(1024 * 1024)
            if not block:
                break
            chan.sendall(block)
            sent += len(block)
            now = time.time()
            if now - last > 0.6 or sent == size:
                last = now
                speed = sent / max(now - t0, 1e-6)
                pct = (100.0 * sent / size) if size else 0.0
                log("    %5.1f%%  %s / %s  %s/s" % (
                    pct, human(sent), human(size), human(speed)))
    chan.shutdown_write()
    rc = chan.recv_exit_status()
    if rc != 0:
        raise RuntimeError("远端写入失败，退出码 %s" % rc)


def verify(base_url: str, expect_version: str) -> bool:
    from urllib.request import Request, urlopen

    url = base_url.rstrip("/") + "/update.json"
    for i in range(3):
        try:
            req = Request(url, headers={"User-Agent": "push-update-node/1.0",
                                        "Cache-Control": "no-cache"})
            with urlopen(req, timeout=20) as resp:           # noqa: S310
                raw = resp.read()
            data = json.loads(raw.decode("utf-8"))
            ver = str(data.get("version") or "")
            log("自检：%s → HTTP 200，版本 %s，%d 个资产" % (
                url, ver, len(data.get("assets") or [])))
            if expect_version and ver != expect_version:
                log("   !! 版本对不上（期望 %s）" % expect_version)
                return False
            return True
        except Exception as e:                              # noqa: BLE001
            if i == 2:
                log("自检失败：%s -> %r" % (url, e))
                return False
            time.sleep(2)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(ROOT, "成品软件", "update"),
                    help="本地目录（默认 成品软件\\update，由 make_update_manifest.py 生成）")
    ap.add_argument("--host", default=os.environ.get("SSH_HOST", DEFAULTS["host"]))
    ap.add_argument("--port", type=int, default=int(os.environ.get("SSH_PORT",
                                                                   DEFAULTS["port"])))
    ap.add_argument("--user", default=os.environ.get("SSH_USER", DEFAULTS["user"]))
    ap.add_argument("--remote-dir", default=DEFAULTS["remote_dir"])
    ap.add_argument("--base-url", default=DEFAULTS["base_url"])
    ap.add_argument("--key", default=DEFAULTS["key"], help="私钥路径（默认 ~/.ssh/id_ed25519）")
    ap.add_argument("--password-only", action="store_true", help="只用密码（忽略公钥）")
    ap.add_argument("--install-key", action="store_true", help="顺手把本机公钥装到服务器")
    ap.add_argument("--only", default="", help="只推这些文件（逗号分隔）")
    ap.add_argument("--skip-verify", action="store_true", help="跳过公网自检")
    args = ap.parse_args()

    if not os.path.isdir(args.src):
        log("!! 本地目录不存在：%s\n先跑 scripts\\make_update_manifest.py" % args.src)
        return 1
    names = sorted(os.listdir(args.src))
    if args.only:
        want = [n.strip() for n in args.only.split(",") if n.strip()]
        names = [n for n in names if n in want]
    files = [os.path.join(args.src, n) for n in names
             if os.path.isfile(os.path.join(args.src, n))]
    if not files:
        log("!! 没有要推的文件")
        return 1

    expect = ""
    mani = os.path.join(args.src, "update.json")
    if os.path.exists(mani):
        try:
            expect = str(json.load(open(mani, encoding="utf-8")).get("version") or "")
        except Exception:                                   # noqa: BLE001
            pass
    total = sum(os.path.getsize(p) for p in files)
    log("准备推送 %d 个文件（%s）→ %s:%s" % (
        len(files), human(total), args.host, args.remote_dir))

    client = connect(args)
    try:
        if args.install_key:
            install_key(client, os.path.expanduser(args.key))
        run(client, "mkdir -p %s" % _shquote(args.remote_dir))
        for path in files:
            name = os.path.basename(path)
            size = os.path.getsize(path)
            remote = args.remote_dir.rstrip("/") + "/" + name
            log("  -> %s（%s）" % (name, human(size)))
            upload_stream(client, path, remote, size)
            run(client, "chmod 644 %s" % _shquote(remote))
        # nginx 以 www 跑，文件归 www 更稳妥（有 www 用户才 chown）
        run(client, "id www >/dev/null 2>&1 && chown -R www:www %s || true"
                    % _shquote(args.remote_dir))
        run(client, "chmod 755 %s" % _shquote(args.remote_dir))
        log("远端目录内容：")
        log(run(client, "ls -lh %s" % _shquote(args.remote_dir)))
    finally:
        client.close()

    if not args.skip_verify:
        log("")
        if not verify(args.base_url, expect):
            log("节点文件推上去了，但公网自检没过 —— 检查一下站点根目录/防火墙。")
            return 1
        log("完成 ✓ 程序下次检查更新就会给这个节点测速了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
