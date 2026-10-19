# -*- coding: utf-8 -*-
"""内核封装：把 vendor 化的 HivisionIDPhotos 包成稳定接口。

本模块负责三件上游没做好的事：
1. 出口统一 .astype(np.uint8) —— add_background() 返回 float64，直接交给下游会报错。
2. 全幅抠图（res.matting）单独返回，供手动微调反复重裁，不必重跑模型。
3. 关掉 hollow_out_fix 的开关（默认保持上游行为，见 build_vendor.py 的 PATCH-4）。
"""
from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from .io_compat import hex_to_bgr, to_uint8
from .specs import PhotoSpec, SpecLibrary

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR_DIR = os.path.join(APP_DIR, "vendor")
if VENDOR_DIR not in sys.path:
    sys.path.insert(0, VENDOR_DIR)


class PipelineError(RuntimeError):
    """内核处理失败（例如照片里检测不到人脸）。"""


@dataclass
class ManualTransform:
    """手动微调参数。全部是相对量，换尺寸也不用重设。"""
    zoom: float = 1.0          # 相对自动构图的缩放
    offset_x: float = 0.0      # 水平平移，单位=输出宽度的比例
    offset_y: float = 0.0      # 垂直平移，单位=输出高度的比例
    rotate: float = 0.0        # 旋转角度（度）
    head_ratio: float = 0.55   # 人脸高度 / 输出高度的期望值
    center_y: float = 0.42     # 人脸中心落在输出高度的比例位置

    def as_dict(self) -> Dict:
        return {"zoom": self.zoom, "offset_x": self.offset_x,
                "offset_y": self.offset_y, "rotate": self.rotate,
                "head_ratio": self.head_ratio, "center_y": self.center_y}

    @classmethod
    def from_dict(cls, d: Optional[Dict]) -> "ManualTransform":
        d = d or {}
        return cls(**{k: float(v) for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ProcessResult:
    standard_bgr: np.ndarray        # 成品证件照（已合成底色）；bg 为空时是 RGBA
    standard_rgba: np.ndarray       # 内核直出的裁剪结果（未合成底色），换底色时复用它，不必重跑模型
    matting_bgra: np.ndarray        # 全幅抠图，供手动微调
    face: Optional[dict]
    spec: PhotoSpec
    bg: Optional[str]

    @property
    def size(self) -> Tuple[int, int]:
        h, w = self.standard_bgr.shape[:2]
        return (w, h)

    @property
    def face_rect(self) -> Optional[Tuple[int, int, int, int]]:
        """(x, y, w, h) —— 从内核的 face dict 里取出人脸框。"""
        if not self.face:
            return None
        r = self.face.get("rectangle") if isinstance(self.face, dict) else None
        if not r:
            return None
        return tuple(int(v) for v in r[:4])


def _rect_sub_pix(img: np.ndarray, size, center):
    """cv2.getRectSubPix 只支持 1/3 通道，4 通道要拆开分别取再合并。"""
    import cv2
    if img.ndim == 2 or img.shape[2] in (1, 3):
        return cv2.getRectSubPix(img, size, center)
    return cv2.merge([cv2.getRectSubPix(c, size, center) for c in cv2.split(img)])


def crop_to_spec(matting_bgra: np.ndarray, spec: PhotoSpec, face_rect, t: ManualTransform,
                 bg_bgr: Tuple[int, int, int] = (255, 255, 255)) -> np.ndarray:
    """按手动参数从全幅抠图里重新裁一张证件照（不重跑模型，毫秒级）。"""
    import cv2

    W, H = spec.px_size
    img = matting_bgra
    if img is None or img.size == 0:
        raise PipelineError("抠图结果为空，无法裁剪")

    if face_rect is None:
        fh = img.shape[0] * 0.35
        cx, cy = img.shape[1] / 2.0, img.shape[0] * 0.35
    else:
        x, y, fw, fh = face_rect
        cx, cy = x + fw / 2.0, y + fh / 2.0

    if abs(t.rotate) > 0.01:
        M = cv2.getRotationMatrix2D((cx, cy), t.rotate, 1.0)
        img = cv2.warpAffine(img, M, (img.shape[1], img.shape[0]),
                             flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    win_h = max(8.0, fh / max(0.05, t.head_ratio) / max(0.05, t.zoom))
    win_w = max(8.0, win_h * W / H)

    ccx = cx + t.offset_x * win_w
    ccy = cy + (0.5 - t.center_y) * win_h + t.offset_y * win_h

    patch = _rect_sub_pix(img, (int(round(win_w)), int(round(win_h))), (ccx, ccy))
    patch = cv2.resize(patch, (W, H), interpolation=cv2.INTER_AREA)

    alpha = patch[:, :, 3:4].astype(np.float32) / 255.0
    rgb = patch[:, :, :3].astype(np.float32)
    bg = np.array(bg_bgr, np.float32).reshape(1, 1, 3)
    out = rgb * alpha + bg * (1.0 - alpha)
    return np.clip(out, 0, 255).astype(np.uint8)


class Processor:
    """内核单例封装。内部加锁，保证后台线程串行调用 onnxruntime。"""

    _lock = threading.Lock()
    _creator = None
    _model_name = None

    def __init__(self, model: str = "hivision_modnet", lib: Optional[SpecLibrary] = None):
        self.model = model
        self.lib = lib or SpecLibrary.load()

    # ---------- 内部 ----------
    def _ensure_creator(self):
        if Processor._creator is not None and Processor._model_name == self.model:
            return Processor._creator
        from hivision import IDCreator
        creator = IDCreator()
        if self.model == "modnet_photographic_portrait_matting":
            from hivision.creator.human_matting import (
                extract_human_modnet_photographic_portrait_matting as handler,
            )
            creator.matting_handler = handler
        Processor._creator = creator
        Processor._model_name = self.model
        return creator

    @staticmethod
    def _weights_candidates() -> List[str]:
        """按「上游实际会用哪个路径」优先列出候选目录。

        上游 human_matting.py 是用 `os.path.dirname(__file__)` 拼权重路径的，
        打包后 hivision 包会被放到 _MEIPASS 顶层（而不是 app/vendor 下），
        所以必须跟着已导入模块的真实位置走，不能写死源码目录。
        """
        dirs: List[str] = []
        try:
            import hivision.creator as _c
            dirs.append(os.path.join(os.path.dirname(os.path.abspath(_c.__file__)), "weights"))
        except Exception:                                    # noqa: BLE001
            pass
        base = getattr(sys, "_MEIPASS", None)
        if base:
            dirs.append(os.path.join(base, "hivision", "creator", "weights"))
        dirs.append(os.path.join(VENDOR_DIR, "hivision", "creator", "weights"))
        return dirs

    @classmethod
    def weights_path(cls) -> str:
        dirs = cls._weights_candidates()
        for d in dirs:
            p = os.path.join(d, "hivision_modnet.onnx")
            if os.path.exists(p):
                return p
        return os.path.join(dirs[0], "hivision_modnet.onnx")

    @classmethod
    def weights_ready(cls) -> bool:
        p = cls.weights_path()
        return os.path.exists(p) and os.path.getsize(p) > 1024 * 1024

    # ---------- 对外 ----------
    def process(self, image_bgr: np.ndarray, spec: PhotoSpec, bg: Optional[str] = "white",
                hollow_fix: bool = True, face_alignment: bool = False,
                beauty: Optional[Dict[str, int]] = None) -> ProcessResult:
        """跑一次完整流程：抠图 + 人脸检测 + 自动构图裁剪 + 换底色。约 0.3 秒（纯 CPU）。"""
        if image_bgr is None or image_bgr.size == 0:
            raise PipelineError("输入图片为空")
        if not self.weights_ready():
            raise PipelineError(
                "抠图模型缺失：%s\n请先运行 scripts\\download_weights.ps1 或 app\\vendor\\build_vendor.py"
                % self.weights_path())

        os.environ["IDPHOTO_HOLLOW_FIX"] = "1" if hollow_fix else "0"
        compose = dict(self.lib.default_compose)
        compose.update(spec.compose or {})
        beauty = beauty or {}

        creator = self._ensure_creator()
        with Processor._lock:
            try:
                res = creator(
                    image_bgr,
                    size=spec.hw,
                    head_measure_ratio=float(compose.get("head_measure_ratio", 0.2)),
                    head_height_ratio=float(compose.get("head_height_ratio", 0.45)),
                    head_top_range=tuple(compose.get("head_top_range", (0.12, 0.1))),
                    face_alignment=face_alignment,
                    whitening_strength=int(beauty.get("whitening", 0)),
                    brightness_strength=int(beauty.get("brightness", 0)),
                    contrast_strength=int(beauty.get("contrast", 0)),
                    sharpen_strength=int(beauty.get("sharpen", 0)),
                    saturation_strength=int(beauty.get("saturation", 0)),
                )
            except Exception as e:      # 内核的异常类型不稳定，统一转成 PipelineError
                raise PipelineError("内核处理失败：%s" % e) from e

        standard_rgba = res.standard
        standard = standard_rgba
        if bg:
            standard = self.compose(standard_rgba, bg)

        return ProcessResult(standard_bgr=standard, standard_rgba=standard_rgba,
                             matting_bgra=res.matting, face=res.face,
                             spec=spec, bg=bg)

    def compose(self, rgba_or_bgr: np.ndarray, bg: str) -> np.ndarray:
        """把抠图结果合成到指定底色上（毫秒级，换底色时用它，不重跑模型）。"""
        color = self.lib.color(bg)
        if rgba_or_bgr is None:
            raise PipelineError("没有可合成的图像")
        if rgba_or_bgr.ndim == 3 and rgba_or_bgr.shape[2] == 4:
            from hivision.utils import add_background
            return to_uint8(add_background(rgba_or_bgr, bgr=hex_to_bgr(color.hex),
                                           mode="pure_color"))
        return to_uint8(rgba_or_bgr)

    def recompose(self, result: ProcessResult, bg: str) -> np.ndarray:
        """换底色（不重跑模型）。手动微调过的结果请改用 recrop 重新裁。"""
        return self.compose(result.standard_rgba, bg)

    def recrop(self, result: ProcessResult, transform: ManualTransform,
               spec: Optional[PhotoSpec] = None) -> np.ndarray:
        """用手动参数重裁。毫秒级，可挂在滑块回调上。"""
        spec = spec or result.spec
        bg_bgr = (255, 255, 255)
        if result.bg:
            bg_bgr = hex_to_bgr(self.lib.color(result.bg).hex)
        return crop_to_spec(result.matting_bgra, spec, result.face_rect, transform, bg_bgr)


def load_photo(path: str) -> np.ndarray:
    """路径安全地读一张用户照片（BGR）。"""
    from .io_compat import imread
    img = imread(path, 1)
    if img is None:
        raise PipelineError("读不到图片：%s\n（若文件名含中文或特殊字符，本程序已做兼容；"
                            "仍失败请确认文件未损坏）" % path)
    return img
