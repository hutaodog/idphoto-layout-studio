# HivisionIDPhotos 算法内核可行性调研

调研方式：`git clone --depth 1` 真实克隆到 `_research/hivision`（成功），源码逐文件核实；API 元数据与 issue 经 GitHub REST API 核实；排版算法用本机 Python 3.11 实跑验证。

## 一、结论

**能当内核，但只能当"算法库"，不能当"产品"。** 抠图（ONNX，4 个模型可选）、人脸检测（MTCNN/RetinaFace，全离线）、换底（纯色+渐变+自定义 HEX/RGB）、按毫米/像素裁剪、多尺寸相纸排版、裁剪线、指定 KB 压缩、300DPI 导出——这些我们要的核心算法它全都有，且是 Apache-2.0，可商用闭源集成。风险点四个：

1. **权重不自带也不自动下载**。`human_matting.py` 只按本地路径读 ONNX，文件不存在仅 `print("Checkpoint file not found")` 后继续跑到崩溃；必须我们自己做首次下载/内置到安装包。
2. **上游已停更**。master 最后一次提交 2026-07-03（仅改 README），18 个规格表、5 个相纸预设都写死在 demo 层，106 个 open issue 长期无人处理。要把它当内核等于**永久 fork 自维护**。
3. **依赖锁死 Python 3.10**（`numpy<=1.26.4`，Python 3.13 无 wheel 会触发 Meson 源码编译失败，issue #269），且 `mtcnn-runtime` 会强制拉高 `onnxruntime`（issue #114）。
4. **抠图边缘会被腐蚀**。`hollow_out_fix()` 对 alpha 做 `erode(5x5, iterations=3)`，等于向内收缩约 6px，头发丝细节会被吃掉，这正是"只换背景不动头发"需求的对立面。

## 二、尺寸规格库清单

路径：**`demo/assets/size_list_CN.csv`（不在 hivision/ 包内，在 demo 层！）**，共 **18 种**，只有像素值（300DPI），无毫米字段。解析函数 `demo/utils.py::csv_to_size_list`，元组顺序为 `(height, width)`。

| 中文名 | English | 像素(H×W)@300DPI | 约合毫米 |
|---|---|---|---|
| 一寸 | One inch | 413×295 | 35×25 |
| 二寸 | Two inches | 626×413 | 53×35 |
| 小一寸 | Small one inch | 378×260 | 32×22 |
| 小二寸 | Small two inches | 531×413 | 45×35 |
| 大一寸 | Large one inch | 567×390 | 48×33 |
| 大二寸 | Large two inches | 626×413 | 53×35 |
| 五寸 | Five inches | 1499×1050 | 127×89（相纸） |
| 教师资格证 | Teacher qualification certificate | 413×295 | 35×25 |
| 国家公务员考试 | National civil service exam | 413×295 | 35×25 |
| 初级会计考试 | Primary accounting exam | 413×295 | 35×25 |
| 英语四六级考试 | English CET-4 and CET-6 | 192×144 | 16×12 |
| 计算机等级考试 | Computer level exam | 567×390 | 48×33 |
| 研究生考试 | Graduate entrance exam | 709×531 | 60×45 |
| 社保卡 | Social security card | 441×358 | 37×30 |
| 电子驾驶证 | Electronic driver's license | 378×260 | 32×22 |
| 美国签证 | American visa | 600×600 | 51×51 |
| 日本签证 | Japanese visa | 413×295 | 35×25 |
| 韩国签证 | Korean visa | 531×413 | 45×35 |

**覆盖缺口（重要）**：**无护照规格**（中国护照 33×48mm 只能自定义）；**无申根签证**；**无简历照**；无身份证专用项。美签/日签/韩签有，"二寸"实为 35×53mm（大二寸）而非通行 35×49mm，**数据本身有歧义**。另外 `size_list_EN.csv` 第 7 行 `626,413 ` 带尾随空格，靠 CSV 解析容错。

## 三、关键代码路径与函数签名

| 文件 | 函数/常量 | 签名要点 |
|---|---|---|
| `hivision/creator/__init__.py:52` | `IDCreator.__call__` | `(image, size=(413,295), change_bg_only=False, crop_only=False, head_measure_ratio=0.2, head_height_ratio=0.45, head_top_range=(0.12,0.1), face=None, whitening/brightness/contrast/sharpen/saturation_strength=0, face_alignment=False, horizontal_flip=False) -> Result`；`size` 为 `(h,w)` |
| `hivision/creator/layout_calculator.py:78` | `generate_layout_array(input_height, input_width, LAYOUT_WIDTH=1795, LAYOUT_HEIGHT=1205)` | 返回 `(typography_arr, typography_rotate)`；间距硬编码：照片间 30px、边距 50/70px；**行列数不可传参，自动求最优** |
| `hivision/creator/layout_calculator.py:118` | `generate_layout_image(input_image, typography_arr, typography_rotate, width=295, height=413, crop_line=False, LAYOUT_WIDTH=1795, LAYOUT_HEIGHT=1205)` | `crop_line=True` 画 1px 浅灰(200,200,200) 裁剪线 |
| `hivision/creator/context.py:14/103` | `Params` / `Result` | `Result.standard/.hd/.matting/.face` |
| `hivision/creator/choose_handler.py:5/12` | `HUMAN_MATTING_MODELS` / `FACE_DETECT_MODELS` | 抠图 4 选 1；人脸 3 选 1 |
| `hivision/creator/human_matting.py:20/79-131/135` | `WEIGHTS` / `extract_human_*` / `hollow_out_fix` | 权重路径字典；alpha 腐蚀修补 |
| `hivision/utils.py:286` | `add_background(input_image, bgr=(0,0,0), mode="pure_color")` | mode: `pure_color` / `updown_gradient` / center 渐变 |
| `hivision/utils.py:35` | `resize_image_to_kb(input_image, output_image_path=None, target_size_kb=100, dpi=300)` | 二分 quality 逼近目标 KB |
| `hivision/utils.py:11` | `save_image_dpi_to_bytes(image, output_image_path=None, dpi=300)` | 写 DPI |
| `demo/processor.py:228` | 毫米换算 | `int(mm / 25.4 * 300)`，自定义尺寸支持毫米 |
| `demo/locales.py:721` | `print_switch["shape"]` | `[[1205,1795],[1051,1500],[2479,3508],[1051,1500],[1205,1795]]` |

**相纸（实测）**：UI 预设 `["六寸","五寸","A4","3R","4R"]`，默认**六寸**，顺序 `(HEIGHT, WIDTH)`。画布恒为 300DPI。**函数层支持任意相纸**——我实跑传入 7寸 1500×2100 成功，1 寸照排 **18 张**。实测排片数：

| 相纸 | 一寸 | 二寸 | 美签 | 社保卡 | 考研 |
|---|---|---|---|---|---|
| 五寸 1051×1500 | 6 | 4 | 2 | 9 | 2(转置) |
| 六寸 1205×1795 | 9 | 4 | 2 | 9 | 3(转置) |
| A4 2479×3508 | 21 | 15 | 9 | 24 | 12 |
| 7寸 1500×2100 | 18 | 9(转置) | 6 | 18 | 4(转置) |

**注意**：`3R` 与 `4R` 在 `shape` 里分别是 `[1051,1500]` 和 `[1205,1795]`，即 3R=五寸、4R=六寸，**4R 疑似配置错误**（4R 通常 102×152mm）。

## 四、依赖与安装步骤

`requirements.txt`（源码确认）：`opencv-python>=4.8.1.78`、`onnxruntime>=1.15.0`、`numpy<=1.26.4`、`requests`、`mtcnn-runtime`、`tqdm`、`starlette`。
`requirements-app.txt`：`gradio>=4.43.0`、`fastapi`。

**结论：不需要 torch，纯 CPU 走 onnxruntime。** 仅 `birefnet-v1-lite` 想 GPU 才需 torch+CUDA（README 声明）。除 opencv/onnxruntime 外全是纯 Python 小包，安装体积主要是 onnxruntime（~200MB 量级，**未实测**）＋所选权重。

- 克隆：**已实测成功**（`git clone --depth 1`，工作区 27.2MB，不含权重）。
- 装依赖：**未实测**，来自 README：`pip install -r requirements.txt` + `pip install -r requirements-app.txt`。**必须 Python 3.10**（README 声明"主要测试在 3.10"，实测本机 3.11 也可导入 cv2；但 `numpy<=1.26.4` 在 3.13 上无 wheel，issue #269 实测报 Meson 编译失败）。
- **本机实测**：Python 3.11.8，`cv2`/`numpy`/`PIL` 已有，`onnxruntime`/`mtcnn` 缺失 → 因此 `import hivision` 在 `human_matting.py:12` 即 `ModuleNotFoundError: onnxruntime`。**想跑通必须先装 onnxruntime + 放权重。**
- **权重（手动，不自动下载）**，放 `hivision/creator/weights/`：
  - `hivision_modnet.onnx` 24.7MB（纯色换底适配更好，推荐）
  - `modnet_photographic_portrait_matting.onnx` 24.7MB
  - `rmbg-1.4.onnx` 176.2MB（HF briaai/RMBG-1.4，需重命名）
  - `birefnet-v1-lite.onnx` 224MB（精度最好，CPU 6.2GB 内存）
  - `retinaface-resnet50.onnx` → `hivision/creator/retinaface/weights/`（可选，MTCNN 默认免下载）
  - 脚本：`python scripts/download_model.py --models hivision_modnet`
  - **国内镜像：官方给出 SwanHub** `https://swanhub.co/ZeYiLin/HivisionIDPhotos_models/tree/main`（README 声明）。我们也应把权重内置进安装包，彻底规避联网。
- **性能（README 声明，未实测）**：MODNet+mtcnn 内存 410MB / 0.207s；MODNet+retinaface 0.571s；birefnet+retinaface 6.20GB / 7.063s。CPU 单张约 **0.2～0.6 秒**量级。issue #255 有用户在 4090 上跑 birefnet 仍需 7 秒。

## 五、换底色能力

**六色预设**（`demo/assets/color_list_CN.csv`，源码确认）：蓝色 `628bce`、白色 `ffffff`、红色 `d74532`、黑色 `000000`、深蓝色 `4b6190`、浅灰色 `f2f0f0`。
**支持自定义 HEX 与 RGB**（`demo/locales.py:190`：`["自定义(RGB)", "自定义(HEX)"]`），另含"美式证件照"及**自定义背景图** `add_background_with_image()`。
**渐变支持**：`pure_color` / `上下渐变（白色）` / `中心渐变（白色）`（`demo/locales.py:321`）。注意渐变仅以给定色对**白色**做渐变，非任意两色。
**边缘质量**：合成公式 `(b-b2)*a/255 + b2`，alpha 直接线性混合，无羽化/无 matting refine。且 `hollow_out_fix()` 强制 `erode(5x5, iterations=3)` 收缩 alpha，**头发丝会明显缺损**。要满足"只换背景不动头发"，需自行替换为 `hivision_modnet`/birefnet 并**去掉或减弱 hollow_out_fix 的腐蚀**。

## 六、交付形态

- **Gradio Web UI**：`app.py` + `demo/`（中文界面已内建，`demo/locales.py` 含 zh/en/ja/ko）。注意 `gradio>=4.43.0` 无上限，Gradio 6 下 `show_api` 参数已移除会启动崩溃（issue #275、#287，2026-08 仍在报）。
- **FastAPI**：`deploy_api.py`，8 个 endpoint，全部 `Form` 表单：
  - `POST /idphoto`（`input_image`|`input_image_base64`、`height=413`、`width=295`、`human_matting_model`、`face_detect_model`、`hd`、`dpi=300`、`face_align`、`whitening_strength`、`head_measure_ratio`、`head_height_ratio`、`top_distance_max/min`、`brightness/contrast/sharpen/saturation_strength`）
  - `POST /human_matting`、`/add_background`（`color`、`kb`、`render`）、`/generate_layout_photos`（`height`、`width`、`kb`、`dpi`）、`/idphoto_crop`、`/watermark`、`/set_kb`
- **Docker**：有。`Dockerfile`（`python:3.10-slim`）+ `docker-compose.yml`（7860 Gradio / 8080 API），镜像 `linzeyi/hivision_idphotos`。注意 Dockerfile 里的 `libgl1-mesa-glx` 在 Debian trixie 已无安装候选，构建会失败（issue #265）。
- **第三方桌面 GUI**：`zhaoyun0071/HivisionIDPhotos-windows-GUI`（196★，"解压即用"，但 `pushed_at` 停在 2024-09-03，已不跟进上游）。另有社区 C++ 版 `zjkhahah/HivisionIDPhotos-cpp`。
- **打包**：根目录 `app.spec`（PyInstaller）**引用了不存在的 `app/web.py`**，且 `datas` 指向 `hivisionai`/`size_list_CN.csv` 等不存在路径 → **打包配置是坏的，不能直接用，需重写**。

## 七、图片压缩导出

- 指定 KB：`resize_image_to_kb(input_image, output_image_path, target_size_kb, dpi)`，二分 quality 逼近；API `/set_kb`（`kb=50`）。**已源码确认**。
- DPI：`save_image_dpi_to_bytes(..., dpi=300)`，`/add_background`、`/generate_layout_photos` 均可传 `dpi`；`demo/processor.py` 中默认导出走 `dpi=300`。
- 格式：**PNG 与 JPG 均可**（`demo/locales.py` 有 JPEG 下载选项 `jpeg_format_option`，`processor.py` 分支 `dpi=300` 写 JPG）。**无** WebP。

## 八、Windows CPU 安装真实痛点（均为 issue 实证）

| 问题 | issue |
|---|---|
| `numpy<=1.26.4` 在 Python 3.13 无 wheel，触发 Meson 源码编译，报找不到 cl/gcc，最终 `cv2` 缺失 | **#269**（open） |
| `mtcnn-runtime` 自动装高版本 onnxruntime，覆盖 `onnxruntime-gpu==1.18.0` | **#114** |
| `pip install -r requirements.txt` 找不到 `onnxruntime>=1.15.0` | **#168**（closed） |
| Win7 + Python 3.8 `onnxruntime_pybind11_state` DLL load failed，降级 1.15.0/1.15.1 均无效 | **#238**（open） |
| 权重下载不完整 → `INVALID_PROTOBUF: Protobuf parsing failed`（多人踩坑，9 条评论） | **#16**、**#267** |
| 4090 上 birefnet 单张仍要 7 秒 | **#255**（open） |
| Gradio 6 移除 `show_api`，Windows 上 `python app.py` 直接 TypeError | **#275**（open，6 个 👍）、**#287** |
| Windows + Python 3.13 Gradio 页面全白 | **#261** |
| 想要 exe 不知道怎么编译 | **#222**（open，0 回复） |

**核心坑**：Python 版本与 `mtcnn-runtime` 的 onnxruntime 版本冲突是最高频问题。**建议方案**：锁定 Python 3.10 + 固定 onnxruntime 版本 + 权重内置，绕开全部下载与版本问题。CPU 单张 0.2～0.6s 完全够用，**不要碰 birefnet**（6.2GB 内存）。

## 九、它【没有】的能力（必须我们自研）

1. **7 寸相纸预设**：函数层可用（我实测 1500×2100 排 18 张），但 UI/`shape` 表没有，需自己加配置项。
2. **自定义行数/列数/间距**：`judge_layout` 把间距(30px)、边距(50/70px)和 3 行 / 8 列上限全写死，`generate_layout_array` 不暴露这些参数 → 要自由排版**必须改源码或重写**。
3. **手动微调人脸位置**：只有 `head_measure_ratio`(0.2)、`head_height_ratio`(0.45)、`head_top_range`(0.12,0.1) 三个全局比例参数，**没有拖拽/交互式微调**，也没有"重新裁剪"回路。
4. **批量处理**：全代码库无 batch 逻辑（已 grep 确认），仅单张 API。
5. **裁剪线可定制**：`crop_line` 只有 bool，颜色/粗细/是否出血线写死为 1px `(200,200,200)`。
6. **安装包/桌面壳**：`app.spec` 已损坏；无 Windows 安装器、无中文原生的桌面 UI（Gradio 是网页）。
7. **规格库可直接用**：18 条规格在 **demo 层 CSV**，不在 Python 包里；缺护照/申根/简历照，毫米字段需我们自己补。
8. **边缘羽化/发丝级 matting refine**：无，且现有 `hollow_out_fix` 反而伤发丝。
9. **中文字体已内置**（`hivision/plugin/font/青鸟华光简琥珀.ttf`）但仅用于水印，非印刷排版。

## 十、引用 URL

- 仓库主 API：https://api.github.com/repos/Zeyi-Lin/HivisionIDPhotos
- 仓库主页：https://github.com/Zeyi-Lin/HivisionIDPhotos
- 权重下载脚本：https://raw.githubusercontent.com/Zeyi-Lin/HivisionIDPhotos/master/scripts/download_model.py
- 尺寸表 CN：https://raw.githubusercontent.com/Zeyi-Lin/HivisionIDPhotos/master/demo/assets/size_list_CN.csv
- 尺寸表 EN：https://raw.githubusercontent.com/Zeyi-Lin/HivisionIDPhotos/master/demo/assets/size_list_EN.csv
- 底色表 CN：https://raw.githubusercontent.com/Zeyi-Lin/HivisionIDPhotos/master/demo/assets/color_list_CN.csv
- 排版算法：https://raw.githubusercontent.com/Zeyi-Lin/HivisionIDPhotos/master/hivision/creator/layout_calculator.py
- 抠图实现：https://raw.githubusercontent.com/Zeyi-Lin/HivisionIDPhotos/master/hivision/creator/human_matting.py
- 换底/压缩：https://raw.githubusercontent.com/Zeyi-Lin/HivisionIDPhotos/master/hivision/utils.py
- 核心编排：https://raw.githubusercontent.com/Zeyi-Lin/HivisionIDPhotos/master/hivision/creator/__init__.py
- API 服务：https://raw.githubusercontent.com/Zeyi-Lin/HivisionIDPhotos/master/deploy_api.py
- hover 模型权重（release）：https://github.com/Zeyi-Lin/HivisionIDPhotos/releases/download/pretrained-model/hivision_modnet.onnx
- MODNet 权重：https://github.com/Zeyi-Lin/HivisionIDPhotos/releases/download/pretrained-model/modnet_photographic_portrait_matting.onnx
- BiRefNet 权重：https://github.com/ZhengPeng7/BiRefNet/releases/download/v1/BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx
- RMBG-1.4 权重：https://huggingface.co/briaai/RMBG-1.4/resolve/main/onnx/model.onnx
- 国内镜像（SwanHub）：https://swanhub.co/ZeYiLin/HivisionIDPhotos_models/tree/main
- issues：#16 #114 #168 #222 #238 #255 #261 #265 #267 #269 #275 #287
  - https://github.com/Zeyi-Lin/HivisionIDPhotos/issues/269
  - https://github.com/Zeyi-Lin/HivisionIDPhotos/issues/114
  - https://github.com/Zeyi-Lin/HivisionIDPhotos/issues/238
  - https://github.com/Zeyi-Lin/HivisionIDPhotos/issues/275
  - https://github.com/Zeyi-Lin/HivisionIDPhotos/issues/255
  - https://github.com/Zeyi-Lin/HivisionIDPhotos/issues/265
  - https://github.com/Zeyi-Lin/HivisionIDPhotos/issues/222
- 第三方 Windows GUI：https://github.com/zhaoyun0071/HivisionIDPhotos-windows-GUI
- 社区 C++ 版：https://github.com/zjkhahah/HivisionIDPhotos-cpp
- 许可证 Apache-2.0：https://github.com/Zeyi-Lin/HivisionIDPhotos/blob/master/LICENSE
