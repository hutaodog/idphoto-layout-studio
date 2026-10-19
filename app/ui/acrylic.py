# -*- coding: utf-8 -*-
"""窗口毛玻璃（能透出桌面）。

Windows 上"透出桌面的毛玻璃"有三条路子，按优先级依次尝试：

1. `DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE = 38, DWMSBT_TRANSIENTWINDOW)`
   —— Win11 22H2+ 的**官方**做法（就是系统"亚克力"材质）。最稳，跟系统主题一致。
2. `SetWindowCompositionAttribute(ACCENT_ENABLE_ACRYLICBLURBEHIND)`
   —— 老牌的亚克力（Win10 1803 起），效果一样但微软已标为不推荐；Win11 上拖动
   有时会掉帧，所以排在官方接口后面。
3. `SetWindowCompositionAttribute(ACCENT_ENABLE_BLURBEHIND)`
   —— 只有模糊、没有色调，老系统也能用。

三条都不行（非 Windows / 远程桌面 / 系统设置关了透明效果）就返回 "none"，
上层会退化成"窗口背景透明 + 卡片自己刷半透明玻璃"——虽然不模糊桌面，
但仍然是"卡片浮在桌面上"的观感，不会变成一块死白板。

注意：截图（`widget.grab()`）**拍不到** DWM 的模糊效果，只有真看屏幕才有效果。
所以验收脚本能证明"窗口没崩、卡片正常"，模糊效果要靠肉眼确认。
"""
from __future__ import annotations

import ctypes
import sys

# --- SetWindowCompositionAttribute 相关结构 ---
_ACCENT_DISABLED = 0
_ACCENT_ENABLE_BLURBEHIND = 3
_ACCENT_ENABLE_ACRYLICBLURBEHIND = 4

_WCA_ACCENT_POLICY = 19

# --- DWM 相关 ---
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWCP_ROUND = 2
_DWMWCP_ROUNDSMALL = 3

_DWMWA_SYSTEMBACKDROP_TYPE = 38
_DWMSBT_AUTO = 0
_DWMSBT_NONE = 1
_DWMSBT_MAINWINDOW = 2       # Mica，只模糊壁纸
_DWMSBT_TRANSIENTWINDOW = 3  # Acrylic，模糊窗口背后的东西（我们要的）
_DWMSBT_TABBEDWINDOW = 4


def win_build() -> int:
    """Windows 内部版本号（Win11 22H2 = 22621 起才有系统背景材质）。"""
    try:
        return int(sys.getwindowsversion().build)
    except Exception:                                      # noqa: BLE001
        return 0


def supports_backdrop() -> bool:
    """能不能用 Win11 的系统背景材质（亚克力）。

    **必须是非分层窗口**才生效 —— 这是"灰不拉几、圆角外面一个方块"的根因：
    Qt 的 `WA_TranslucentBackground` 会让窗口带上 WS_EX_LAYERED，
    DWM 在分层窗口上不做模糊，只把 AccentPolicy 的色调刷成一块实色，
    于是既不透、圆角外面还多一块方的。
    """
    if not sys.platform.startswith("win"):
        return False
    return win_build() >= 22621


def enable_backdrop(hwnd: int) -> bool:
    """Win11 正确做法：系统亚克力 + 系统圆角（窗口不能是分层的）。"""
    if not hwnd:
        return False
    _extend_frame(hwnd)
    # 让 DWM 自己把窗口四角切成圆角，这样模糊区域也是圆的
    try:
        dwmapi = ctypes.windll.dwmapi
        pref = ctypes.c_int(_DWMWCP_ROUND)
        dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd),
                                     _DWMWA_WINDOW_CORNER_PREFERENCE,
                                     ctypes.byref(pref), ctypes.sizeof(pref))
    except Exception:                                      # noqa: BLE001
        pass
    return _set_backdrop(hwnd, _DWMSBT_TRANSIENTWINDOW)


class _AccentPolicy(ctypes.Structure):
    _fields_ = [("AccentState", ctypes.c_int),
                ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint),      # 0xAABBGGRR
                ("AnimationId", ctypes.c_int)]


class _WinCompAttrData(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_int),
                ("Data", ctypes.c_void_p),
                ("SizeOfData", ctypes.c_size_t)]


def _set_accent(hwnd: int, state: int, tint: tuple, flags: int = 0) -> bool:
    """SetWindowCompositionAttribute 包一层。tint=(r,g,b,a)。"""
    try:
        user32 = ctypes.windll.user32
        r, g, b, a = tint
        # GradientColor 是 0xAABBGGRR
        color = (a << 24) | (b << 16) | (g << 8) | r
        policy = _AccentPolicy(state, flags, color, 0)
        data = _WinCompAttrData(_WCA_ACCENT_POLICY,
                                ctypes.cast(ctypes.pointer(policy), ctypes.c_void_p),
                                ctypes.sizeof(policy))
        res = user32.SetWindowCompositionAttribute(
            ctypes.c_void_p(hwnd), ctypes.byref(data))
        return bool(res)
    except Exception:                                      # noqa: BLE001
        return False


def _set_backdrop(hwnd: int, kind: int) -> bool:
    """DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE)。"""
    try:
        dwmapi = ctypes.windll.dwmapi
        val = ctypes.c_int(kind)
        res = dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), _DWMWA_SYSTEMBACKDROP_TYPE,
            ctypes.byref(val), ctypes.sizeof(val))
        return res == 0                                    # S_OK
    except Exception:                                      # noqa: BLE001
        return False


def _extend_frame(hwnd: int) -> None:
    """把 DWM 边框延伸进整个客户区 —— DWM 的系统背景材质要先有这一步才铺得出来。"""
    try:
        class _MARGINS(ctypes.Structure):
            _fields_ = [("cLeftWidth", ctypes.c_int), ("cRightWidth", ctypes.c_int),
                        ("cTopHeight", ctypes.c_int), ("cBottomHeight", ctypes.c_int)]

        dwmapi = ctypes.windll.dwmapi
        m = _MARGINS(-1, -1, -1, -1)
        dwmapi.DwmExtendFrameIntoClientArea(ctypes.c_void_p(hwnd), ctypes.byref(m))
    except Exception:                                      # noqa: BLE001
        pass


def enable_glass(hwnd: int, tint: tuple = (255, 255, 255, 205),
                 layered: bool = False) -> str:
    """给窗口挂上毛玻璃，返回实际生效的方式。

    **layered=True（Qt 半透明无边框窗口）时不能走 DWM backdrop**：
    那条路在分层窗口上不会模糊，DWM 只会把色调刷成一块实色 ——
    这就是之前"灰不拉几、圆角外面多一个方块"的原因。
    分层窗口上要用老的 SCA 亚克力（`ACCENT_ENABLE_ACRYLICBLURBEHIND`），
    实测在这台 Win11 上能把桌面真正虚化透进来。

    tint 是亚克力的色调。默认很亮的白 + 高 alpha（205），得到"白色磨砂玻璃"；
    alpha 调低会更透、桌面颜色更容易渗进来（那就发灰了）。
    """
    if not sys.platform.startswith("win") or not hwnd:
        return "none"

    _extend_frame(hwnd)

    if not layered:
        # 非分层窗口：优先用 Win11 官方材质（跟系统主题一致、性能最好）
        try:
            dwmapi = ctypes.windll.dwmapi
            pref = ctypes.c_int(_DWMWCP_ROUND)
            dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd),
                                         _DWMWA_WINDOW_CORNER_PREFERENCE,
                                         ctypes.byref(pref), ctypes.sizeof(pref))
        except Exception:                                  # noqa: BLE001
            pass
        if _set_backdrop(hwnd, _DWMSBT_TRANSIENTWINDOW):
            return "dwm-acrylic"

    # 分层窗口（以及上面失败的情况）：SCA 亚克力
    if _set_accent(hwnd, _ACCENT_ENABLE_ACRYLICBLURBEHIND, tint):
        return "sca-acrylic"

    # 只有模糊
    if _set_accent(hwnd, _ACCENT_ENABLE_BLURBEHIND, tint):
        return "sca-blur"

    return "none"


def disable_glass(hwnd: int) -> None:
    if not hwnd:
        return
    _set_backdrop(hwnd, _DWMSBT_NONE)
    _set_accent(hwnd, _ACCENT_DISABLED, (0, 0, 0, 0))


def set_round_corners(hwnd: int, small: bool = False) -> bool:
    """让 **DWM 把窗口本身切圆角**（分层窗口也吃这一套）。

    为什么不用 SetWindowRgn（本机实测的结论，别再改回去）：
    对 `WA_TranslucentBackground` 的无边框窗口，`SetWindowRgn` 虽然返回成功、
    `GetWindowRgn` 也查得到那块圆角区域，**但合成出来的画面一点没被裁** ——
    SCA 亚克力是 DWM 按窗口矩形铺的一整块，圆角那四个角照样是白乎乎的直角。
    实测对比（同一台机器、同一个窗口，抓屏看左上角）：
        · 只有 SetWindowRgn            -> 四角依旧是直角
        · 只有 DWMWA_WINDOW_CORNER_PREFERENCE -> 四角真的圆了，还顺带来一圈窗口阴影
    所以现在圆角一律走 DWM；SetWindowRgn 只当老系统的兜底。
    """
    if not sys.platform.startswith("win") or not hwnd:
        return False
    if win_build() < 22000:                            # Win11 之前没有这个属性
        return False
    try:
        dwmapi = ctypes.windll.dwmapi
        val = ctypes.c_int(_DWMWCP_ROUNDSMALL if small else _DWMWCP_ROUND)
        res = dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), _DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(val), ctypes.sizeof(val))
        if res != 0:
            return False
        # 背景材质那条路要 DWM 边框延伸进客户区，圆角才跟着铺满；这里顺带做一次
        _extend_frame(hwnd)
        return True
    except Exception:                                  # noqa: BLE001
        return False


def apply_round_region(hwnd: int, w: int, h: int, radius: int) -> bool:
    """把**窗口本身**裁成圆角。

    为什么非做不可：亚克力是 DWM 按**窗口矩形**铺的一整块方块；Qt 里再怎么画圆角描边，
    也只是盖在方块上面 —— 表现就是用户说的"四周还是直角、里面又套着一个圆角"。
    用 SetWindowRgn 把窗口区域切成圆角之后，连那层亚克力一起被裁圆了。
    """
    if not sys.platform.startswith("win") or not hwnd or w <= 0 or h <= 0:
        return False
    try:
        gdi32 = ctypes.windll.gdi32
        user32 = ctypes.windll.user32
        rgn = gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, radius * 2, radius * 2)
        if not rgn:
            return False
        # 区域交给系统托管，之后不要自己 DeleteObject
        user32.SetWindowRgn(ctypes.c_void_p(hwnd), rgn, True)
        return True
    except Exception:                                      # noqa: BLE001
        return False
