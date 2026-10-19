# -*- coding: utf-8 -*-
"""桌面程序入口。

直接运行：  python app/main.py
打包后：    证件照排版助手.exe
"""
from __future__ import annotations

import os
import sys
import threading
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _excepthook(etype, value, tb):
    """未捕获异常：既写日志也给弹窗，避免打包后双击闪退什么都没有。

    日志写到**程序自己的目录**（`.logs\错误日志.txt`），不往 C 盘用户目录丢。
    """
    text = "".join(traceback.format_exception(etype, value, tb))
    try:
        from .paths import crash_log_path
        log = crash_log_path()
        with open(log, "a", encoding="utf-8") as f:
            f.write(text + "\n" + "-" * 60 + "\n")
    except Exception:
        log = None
    sys.stderr.write(text)
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance() is not None:
            QMessageBox.critical(None, "证件照排版助手 · 出错了",
                                 "%s\n\n详细信息已写入：\n%s" % (value, log or "(写入失败)"))
    except Exception:
        pass


def setup_streams() -> None:
    """窗口模式（console=False）下 sys.stdout / sys.stderr 会是 None，
    而上游内核里有大量 print()，不兜住会直接抛 AttributeError 导致闪退。
    这里把输出接到**程序目录下的日志文件**，既安全又能事后排查，也不碰 C 盘。"""
    target = None
    try:
        from .paths import log_dir
        target = open(os.path.join(log_dir(), "run.log"), "a",
                      encoding="utf-8", buffering=1)
    except Exception:                                     # noqa: BLE001
        try:
            target = open(os.devnull, "w")
        except Exception:                                 # noqa: BLE001
            target = None
    if target is not None:
        if sys.stdout is None:
            sys.stdout = target
        if sys.stderr is None:
            sys.stderr = target


def close_splash(timeout: float = 2.5) -> None:
    """关闭 PyInstaller 的启动画面（如果这次构建带了启动画面）。

    两个背景，决定了这里的写法：
    1. 启动画面**不会自己消失**，必须在 Python 侧显式调用 pyi_splash.close()。
       用户反馈的"启动窗口一直搁那儿不消失"就是漏了这一步。
    2. 但 close() 要和引导程序做一次进程间握手，握手被环境挡住时会**永久阻塞**
       （实测：沙箱里解压 6 秒就完成了，主窗口却永远不出现）。

    所以这里放到守护线程里执行并设超时：最坏情况只是启动图多留一会儿，
    绝不会把整个程序拖死。当前打包**没有启用启动画面**，这个函数是防御性保留。
    """
    def _worker() -> None:
        try:
            import pyi_splash  # type: ignore
            pyi_splash.close()
        except Exception:                                 # noqa: BLE001
            pass

    try:
        t = threading.Thread(target=_worker, name="close-splash", daemon=True)
        t.start()
        t.join(max(0.1, timeout))
    except Exception:                                     # noqa: BLE001
        pass


def apply_chinese_font(app) -> str:
    """显式挑一个能显示中文的字体。

    Qt6 不再自带字体，某些环境（精简系统、无字体数据库的离屏模式）会退化成方框，
    所以这里主动按优先级挑一个系统中文字体，挑不到就保持默认。
    """
    from PySide6.QtGui import QFont, QFontDatabase
    try:
        families = set(QFontDatabase.families())
    except Exception:                                     # noqa: BLE001
        return ""
    for name in ("Microsoft YaHei UI", "Microsoft YaHei", "微软雅黑",
                 "PingFang SC", "Noto Sans CJK SC", "Source Han Sans SC",
                 "SimHei", "SimSun", "Arial Unicode MS"):
        if name in families:
            app.setFont(QFont(name, 9))
            return name
    return ""


def selftest(out_dir: str, image: str = "") -> int:
    """打包产物的自检：不弹界面，验证「规格库能读、权重在、模型能推理、能出图、dpi 写得对」。

    打包后是窗口程序（没有控制台），所以结果写进 JSON 文件，并用退出码表示成败。
    用法：证件照排版助手.exe --selftest <输出目录> [--image <照片路径>]
    """
    import json
    import time

    report = {"ok": False, "steps": []}
    os.makedirs(out_dir, exist_ok=True)
    out_json = os.path.join(out_dir, "selftest.json")

    def step(name, fn):
        t0 = time.time()
        try:
            value = fn()
            report["steps"].append({"step": name, "ok": True,
                                    "seconds": round(time.time() - t0, 3),
                                    "detail": value if isinstance(
                                        value, (str, int, float, bool, type(None))) else str(value)})
            return value
        except Exception as e:                            # noqa: BLE001
            import traceback
            report["steps"].append({"step": name, "ok": False,
                                    "seconds": round(time.time() - t0, 3),
                                    "error": "%r" % (e,),
                                    "trace": traceback.format_exc()[-800:]})
            return None

    report["frozen"] = bool(getattr(sys, "frozen", False))
    report["executable"] = sys.executable
    report["version"] = __import__("app").__version__

    def check_specs():
        from app.core.specs import SpecLibrary
        lib = SpecLibrary.load()
        lib.require()
        return "%d 条规格 / %d 种相纸 / %d 种底色" % (len(lib.photos), len(lib.papers),
                                                      len(lib.colors))
    step("加载规格库", check_specs)

    def check_weights():
        from app.core.pipeline import Processor
        p = Processor.weights_path()
        if not Processor.weights_ready():
            raise RuntimeError("权重缺失：%s" % p)
        return "%s (%d 字节)" % (p, os.path.getsize(p))
    step("定位抠图权重", check_weights)

    def check_kernel_import():
        from app.core.pipeline import VENDOR_DIR
        if VENDOR_DIR not in sys.path:
            sys.path.insert(0, VENDOR_DIR)
        import hivision
        assert "hivision.plugin.beauty.grind_skin" not in sys.modules
        return "hivision ok（未拉起 grind_skin）：%s" % os.path.dirname(hivision.__file__)
    step("导入内核", check_kernel_import)

    if image and os.path.exists(image):
        def run_pipeline():
            from app.core.pipeline import Processor, load_photo
            from app.core.specs import SpecLibrary
            lib = SpecLibrary.load()
            proc = Processor(lib=lib)
            img = load_photo(image)
            spec = lib.photo("cn_yicun")
            res = proc.process(img, spec, bg="blue")
            if res.size != spec.px_size:
                raise RuntimeError("出图尺寸不对：%s != %s" % (res.size, spec.px_size))
            from app.core.exporter import printed_mm, read_dpi, save_image
            p = os.path.join(out_dir, "selftest_一寸_蓝底.jpg")
            rep = save_image(res.standard_bgr, p, dpi=spec.dpi, target_kb=40)
            dpi_rb = read_dpi(p)
            if dpi_rb != (spec.dpi, spec.dpi):
                raise RuntimeError("dpi 回读不对：%s" % (dpi_rb,))
            mm = printed_mm(p)
            if mm and (abs(mm[0] - spec.mm[0]) > 0.2 or abs(mm[1] - spec.mm[1]) > 0.2):
                raise RuntimeError("打印尺寸不对：%.2f×%.2fmm" % mm)
            report["single_photo"] = p
            return "%d×%dpx  %.1fKB  dpi=%s  打印 %.2f×%.2fmm" % (
                spec.px[0], spec.px[1], rep.kb, dpi_rb, mm[0], mm[1])
        step("跑通抠图→换底→裁剪→导出", run_pipeline)

        def run_layout():
            from app.core.exporter import save_image
            from app.core.layout import plan_for_spec, render_layout
            from app.core.pipeline import Processor, load_photo
            from app.core.specs import SpecLibrary
            lib = SpecLibrary.load()
            img = load_photo(image)
            paper = lib.paper("6inch")
            # 物理尺寸相同的规格（一寸 / 身份证 26×32 之类）张数必须对得上，
            # 而且都要跟"照片物理块 = 规格毫米"这条对上（v1.5.3 修的单位混用 bug）
            counts = {}
            plan = None
            for sid in ("cn_yicun", "cn_idcard", "cn_dayicun"):
                spec = lib.photo(sid)
                plan = plan_for_spec(paper, spec)
                counts[sid] = plan.count
            if counts["cn_yicun"] != 12:
                raise RuntimeError("一寸排 6 寸应为 12 张，实得 %d（dpi=%d）"
                                   % (counts["cn_yicun"],
                                      lib.photo("cn_yicun").dpi))
            spec = lib.photo("cn_yicun")
            plan = plan_for_spec(paper, spec)
            block_mm = (plan.block_px[0] / plan.dpi * 25.4, plan.block_px[1] / plan.dpi * 25.4)
            if abs(block_mm[1] - 146.0) > 1.0:
                raise RuntimeError("一寸 3×4 的整块高度应为 146mm，实得 %.1fmm" % block_mm[1])
            res = Processor(lib=lib).process(img, spec, bg="white")
            canvas = render_layout(res.standard_bgr, plan, crop_line="cross")
            p = os.path.join(out_dir, "selftest_6寸排版.jpg")
            save_image(canvas, p, dpi=plan.dpi)      # dpi 必须与排版时一致
            report["layout_photo"] = p
            return "%s；各规格张数 %s -> %s" % (plan.summary(), counts, p)
        step("跑通排版", run_layout)
    else:
        report["steps"].append({"step": "跑通抠图→换底→裁剪→导出", "ok": None,
                                "detail": "未提供 --image，跳过模型相关检查"})

    report["ok"] = all(s["ok"] for s in report["steps"] if s["ok"] is not None)
    try:
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except Exception:                                     # noqa: BLE001
        pass
    try:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except Exception:                                     # noqa: BLE001
        pass
    return 0 if report["ok"] else 1


def main() -> int:
    setup_streams()
    sys.excepthook = _excepthook

    argv = sys.argv[1:]
    if "--selftest" in argv:
        i = argv.index("--selftest")
        if len(argv) > i + 1 and not argv[i + 1].startswith("-"):
            out = argv[i + 1]
        else:
            from .paths import log_dir
            out = os.path.join(log_dir(), "selftest")   # 放程序目录，不碰 C 盘
        img = ""
        if "--image" in argv:
            j = argv.index("--image")
            if len(argv) > j + 1:
                img = argv[j + 1]
        return selftest(out, img)
    if "--version" in argv:
        from app import __version__
        print(__version__)
        return 0

    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        sys.stderr.write("缺少 PySide6，请先运行 scripts\\setup_env.ps1\n")
        return 1

    from app import APP_NAME, __version__
    from app.core.pipeline import Processor
    from app.core.specs import SpecLibrary
    from app.ui.main_window import MainWindow

    qapp = QApplication(sys.argv)
    qapp.setApplicationName(APP_NAME)
    qapp.setApplicationVersion(__version__)
    # 应用级图标：任务栏、Alt+Tab、窗口图标都用 app/resources/icon.ico
    # （用户指定的图标源图在 app/resources/icon_source.png，由 scripts\make_icon.py 转成 ico）
    try:
        from app.ui.chrome import app_icon
        icon = app_icon()
        if not icon.isNull():
            qapp.setWindowIcon(icon)
    except Exception:                                     # noqa: BLE001
        pass
    apply_chinese_font(qapp)

    try:
        lib = SpecLibrary.load()
        lib.require()
    except Exception as e:                                # noqa: BLE001
        close_splash()
        QMessageBox.critical(None, APP_NAME, "规格库加载失败：%s" % e)
        return 2

    try:
        win = MainWindow(lib)
        win.show()
    finally:
        # 无论成功与否都要把启动画面收掉，否则它会一直挂在屏幕上（用户实测反馈）
        close_splash()

    if not Processor.weights_ready():
        win.status.showMessage("抠图模型缺失，请先运行 scripts\\download_weights.ps1")

    return qapp.exec()


if __name__ == "__main__":
    sys.exit(main())
