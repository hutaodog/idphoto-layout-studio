# vendor 内核修改记录

本项目的算法内核是 [Zeyi-Lin/HivisionIDPhotos](https://github.com/Zeyi-Lin/HivisionIDPhotos)（Apache-2.0），
以 **vendor（内嵌副本）** 方式放在 `app/vendor/hivision/`，不通过 pip 依赖。

**为什么 vendor**：桌面程序需要维护下面这些本地改动，并在版本控制中保留可审查的内核副本。此处不判断上游当前维护状态。

**日常构建**直接使用已提交的 `app/vendor/hivision/`，不需要重新生成。`build_vendor.py` 目前只自动实现PATCH-1至PATCH-4，**尚未自动重放v1.6.7的PATCH-5**；不要直接用它覆盖当前内核。

需要升级上游时，先输出到独立暂存目录，再按本文和版本差异迁移PATCH-5、检查来源与许可并跑回归：

```powershell
git clone --depth 1 https://github.com/Zeyi-Lin/HivisionIDPhotos.git .tmp\upstream
.venv\Scripts\python.exe app\vendor\build_vendor.py --upstream .tmp\upstream --dest .tmp\vendor-stage\hivision
```

脚本的PATCH-1至PATCH-4有字面量断言，上游变动导致失配会报错；这些断言不证明PATCH-5已存在，也不代替处理/裁剪测试。

---

## PATCH-1 · 拆掉 gradio 硬依赖

**文件**：`hivision/plugin/beauty/whitening.py`

**改了什么**：`import gradio as gr` → 包在 `try/except ImportError` 里，失败时 `gr = None`。

**为什么**：`import hivision` 的连锁是
`hivision/__init__.py` → `creator/__init__.py` → `plugin.beauty.handler` → `beauty_tools` → `grind_skin` → `import gradio`。
而 `plugin/beauty/__init__.py` 又会提前 import `beauty_tools`。结果是：**不装 gradio 就 import 不进来**。
`whitening.py` 里 gradio 只在 `if __name__ == "__main__":` 的演示块用到，改成可选导入是安全的。

**验证**：在未安装 gradio 的解释器里 `import hivision` 成功（构建脚本每次都会跑这条断言）。

---

## PATCH-2 · beauty 包改惰性导入

**文件**：`hivision/plugin/beauty/__init__.py`

**改了什么**：`from .beauty_tools import BeautyTools` → 改成模块级 `__getattr__` 惰性导入。

**为什么**：`grind_skin.py` 在**模块级**（不是 `__main__` 保护块里）就执行
`with gr.Blocks(title="Skin Grinding") as iface:` 构建了一个 Gradio 网页界面。
只要它被 import 就会建界面——这既是 import 失败的真凶，也是给桌面程序白背一个 Web 框架的原因。
惰性导入后，只要不调用 `BeautyTools`，`grind_skin` 永远不会被加载。

**验证**：构建脚本断言 `"hivision.plugin.beauty.grind_skin" not in sys.modules`。

---

## PATCH-3 · 中文路径安全的图片读写

**新增文件**：`hivision/_io_compat.py`

**改动文件**：`plugin/beauty/whitening.py`（读 LUT）、`plugin/template/template_calculator.py`（读模板）

**改了什么**：新增 `imread` / `imwrite`（用 `np.fromfile + cv2.imdecode` / `cv2.imencode + tofile`），
并把包内 2 处真实的 `cv2.imread(...)` 调用替换掉。

**为什么**：**`cv2.imread` 在 Windows 上无法处理含中文的路径，且是静默失败（返回 None）**。
实测对照：同一张 `lut_origin.png` 放在 ASCII 路径能读出 `(512, 512, 3)`，放在中文路径读出 `None`；
`np.fromfile + cv2.imdecode` 在中文路径下正常。
本项目的安装目录和用户的照片文件名都可能含中文，这是必踩的坑。

> 附带结论：`onnxruntime.InferenceSession()` **可以**正常加载中文路径下的模型文件（已实测），
> 所以模型不需要挪到临时目录。

---

## PATCH-4 · hollow_out_fix 开关

**文件**：`hivision/creator/human_matting.py`

**改了什么**：两处 `ctx.processing_image = hollow_out_fix(matting_image)` 改成
`_maybe_hollow_out_fix(...)`，并新增该辅助函数：读环境变量 `IDPHOTO_HOLLOW_FIX`，
为 `"0"` 时跳过修补，否则保持上游行为（默认值 `"1"`）。

**为什么**：需要能一键关掉做对比。默认**保持上游行为**——
注意：调研阶段曾判断这个函数会「对 alpha 做 erode 吃掉约 6px 发丝」，**读源码后确认该判断是错的**：
`erode` 只作用在**派生出来的轮廓副本**上，用于保证填充区域落在人像内部；
最终 `a = cv2.add(a, 255 - a_contour)` 的效果是**把人像轮廓内部的半透明空洞补成不透明**，
并不会收缩成品 alpha。因此默认保持开启。
界面上的「启用抠图内部空洞修补」勾选框即对应本开关。

---

## PATCH-5 · 原底色与同源裁剪（v1.6.7）

**文件**：`hivision/creator/context.py`、`creator/__init__.py`、`creator/photo_adjuster.py`。

- `Result`增加可选`original_standard`和`original_source`，每次正常照片处理都携带对应的自动裁剪原图和归一化原图，切换背景模式不必再分割。
- `adjust_photo`在两次裁剪、尺寸归一、上移和水平翻转时同步处理原图，新增第五个返回值`original_standard`；唯一生产调用方同步解包。第二次裁剪不错误地缩放回第一次的尺寸。
- 原图越界时复制边缘像素。开启人脸旋转矫正时，原图与抠图使用相同角度和画布几何；默认桌面流程不启用此可选矫正。
- 应用层`pipeline.py`在同一坐标几何中选择原图BGR或抠图BGRA；手动裁剪直接采样到目标输出尺寸，避免小缩放值分配巨型中间图。无来源/来源尺寸不匹配时报错。
- `Processor`把hollow环境变量的设置、推理和恢复放在同一锁内，异常也恢复原值，避免不同请求相互污染。这是应用层串行化，不是把上游环境变量改成了线程局部参数。

验证：`tests/test_crop_geometry.py`覆盖精确源切片、像素中心、旋转同几何、透明图、输出分配上界和真实并发环境变量恢复；`tests/test_pipeline.py`用实际模型与合成人像检查自动/手动原底色来源；`tests/test_request_flow.py`使用真实QThread和受控推理器检查最新请求/模式及预览导出一致。

限制：来源是长边最多2000像素的归一化图，不承诺逐字节保留原文件；不会自动去除原背景瑕疵。上游再生成脚本尚未包含此补丁，迁移时须人工保留并跑测试。

---

## 我们没有改、但需要知道的上游行为

| 事项 | 说明 | 我们的处理 |
|---|---|---|
| `add_background()` 返回 **float64** | 实测数值范围 0~255，直接交给 `resize_image_to_kb()` 会报 `Cannot handle this data type: (1,1,3), <f8>` | 在 `app/core/pipeline.py` 出口统一 `.astype(np.uint8)`，不改上游 |
| `judge_layout()` 行列写死 `range(1,4)` × `range(1,9)` | **最多只排 3 行**，A4 上 1 寸照只能排 21 张 | 完全不用它的排版，改用自研 `app/core/layout.py`（A4 排 50 张） |
| 官方 `requirements.txt` 漏了 **Pillow** | 但 `human_matting.py` 里 `from PIL import Image` | 我们的 `requirements.txt` 显式写 Pillow |
| 官方 `app.spec` 引用不存在的 `app/web.py` | 打包配置是坏的 | 自己写 `packaging/app.spec` |
| `4R` 预设 = `[1205,1795]` 等于 6 寸、`3R` = `[1051,1500]` 等于 5 寸 | 配置错误 | 不用它的相纸预设，`app/data/paper_specs.json` 自己带 |

---

## 许可证合规

- `app/vendor/LICENSE` —— 上游 Apache-2.0 原文，完整保留。
- 软件内「关于」对话框列出开源组件与许可证。
- 打包产物中**不含** `rmbg-1.4.onnx`（BRIA 非商用授权）、不含 insightface 模型、
  不含 CelebAMask-HQ 衍生的 face-parsing 权重。
- 内置抠图模型只有 `hivision_modnet.onnx`（Apache-2.0，24.7MB，sha256
  `7E0CB9A2A841B426DD0DAF1A788EC398DAB059BC039041D62B15636C0783BC56`）。
- 未复制 LiYing（AGPL-3.0）、sandphoto（GPL-2.0）的任何代码；
  未拷贝 idify（GPL-3.0）的 `spec.json` 文件，只转录了其中的事实性尺寸数据。
- 未打包上游 `plugin/font/青鸟华光简琥珀.ttf`（4MB，仅供其水印功能使用，字体另有授权）。
