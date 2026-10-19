# 02 · 同类开源项目与 AI 模型许可证尽调

> 调研方式：`Invoke-WebRequest` 直连 raw.githubusercontent.com / huggingface.co / api.github.com 读取**许可证原文**；`git clone --depth 1` 到 `_research/` 读**源码原文**。
> 每条结论标注证据级别：**[源码]** = 读过源码；**[许可证原文]** = 读过 LICENSE/模型卡原始文本；**[README]** = 仅读 README/二手资料。
> 调研日：本会话。GitHub star 数为抓取时快照。

---

## 一、项目尽调表（star ≥ 200 的证件照/抠图相关仓库）

### A. 证件照 / 排版 主赛道

| 项目 | ★ | 语言 | 许可证 | 能复用什么 | 不能复用什么 | 结论 |
|---|---|---|---|---|---|---|
| [Zeyi-Lin/HivisionIDPhotos](https://github.com/Zeyi-Lin/HivisionIDPhotos) | 21.6k | Python | **Apache-2.0** [许可证原文] | 全部代码（商用可闭源）。抠图+人脸检测+构图裁剪+DPI/压缩+排版+美颜+API/Gradio/CLI，已自带 PyInstaller 打包描述 | 无代码限制。**但权重另算**：`rmbg-1.4.onnx` 非商用；默认 MTCNN 模型需自查 | **本项目最优内核**，见任务 C-1 |
| [aoguai/LiYing](https://github.com/aoguai/LiYing) | 3.7k | Python | **AGPL-3.0** [许可证原文] | 仅可借鉴思路与参数（人脸占比 0.30/顶部留白 0.175、肩线算旋转角、4R=1205×1795 等常数） | 任何代码/数据文件（含 `data/size_zh.csv`、`data/color_zh.csv`）。AGPL §5c 要求**整体作品以 AGPL 授权**；§6 要求随二进制提供对应源码 | 闭源/给朋友分发**不可取代码**；参数思路可合法借鉴 |
| [zhbhun/idify](https://github.com/zhbhun/idify) | 1.1k | TypeScript | **GPL-3.0**（README 写 "GPL License"；仓库**无 LICENSE 文件**，GitHub 侦测 + README 声明）[源码+README] | 思路：浏览器内 `onnxruntime-web` 跑抠图 + `smartcrop` 构图 | 代码本身（GPL-3.0）。**且实际抠图内核依赖 `@zhbhun/background-removal`，它是 img.ly 的 [imgly/background-removal-js](https://github.com/imgly/background-removal-js) 的再发布 → AGPL-3.0** [许可证原文]，叠加后传染性更重 | 只当产品形态参考。**它完全没有相纸排版功能** |
| [gmajian/sandphoto](https://github.com/gmajian/sandphoto) | 887 | PHP | **GPL-2.0** [许可证原文] | 算法思路（见下）。`phototype.txt` 的**事实性尺寸数据**（各国证件照 cm 尺寸）可自行转录 | PHP 代码（GPL-2.0 传染）。作品带 `www.sandcomp.com` 水印 | 排版算法极简，**自己重写 60 行即可**，无需抄代码 |
| [liuxiaojun666/certificate-photo](https://github.com/liuxiaojun666/certificate-photo) | 674 | JavaScript | **GPL-3.0** | 仅思路（微信小程序架构） | 代码 | 只能借鉴 |
| [no1xuan/HivisionIDPhotos-wechat-weapp](https://github.com/no1xuan/HivisionIDPhotos-wechat-weapp) | 545 | Java | **无 LICENSE** | 无（默认保留所有权利） | 全部代码，法律上不可复用 | ⚠️ 无许可证 = 不能用 |
| [seasonSH/DocFace](https://github.com/seasonSH/DocFace) | 376 | Python | **MIT** | 可商用。但它是**证件照人脸 1:1 比对**（TF，2018 停更） | — | 与"排版/抠图"无关，不相关 |
| [soulerror/HivisionIDPhotos-Uniapp](https://github.com/soulerror/HivisionIDPhotos-Uniapp) | 241 | TypeScript | **无 LICENSE** | 无 | 全部 | ⚠️ 不能用 |
| [dpar39/ppp](https://github.com/dpar39/ppp) | 219 | C++ | **GPL-3.0** | 思路（Qt 证件照工具） | 代码 | 只能借鉴 |
| [zhaoyun0071/HivisionIDPhotos-windows-GUI](https://github.com/zhaoyun0071/HivisionIDPhotos-windows-GUI) | 196 | - | **无 LICENSE** | 只能当"Windows 打包可行性"证据 | 代码 | ⚠️ 不能用（但它证明 Hivision 能做成 Windows 绿色版） |
| [AIFSH/HivisionIDPhotos-ComfyUI](https://github.com/AIFSH/HivisionIDPhotos-ComfyUI) | 196 | Python | **Apache-2.0** | 可复用（Hivision 官方生态封装） | — | 有价值，ComfyUI 集成参考 |
| [pangxiaobin/image-matting](https://github.com/pangxiaobin/image-matting) | 1.7k | Vue | **NOASSERTION**（自定义受限条款） | 只能借鉴"抠图+压缩+证件照"打包的产品形态 | 代码（NOASSERTION 通常含禁止商用/仅学习） | ⚠️ 需人工读原文，默认按不可商用处理 |
| [xiaoowuu/CertificateCamera](https://github.com/xiaoowuu/CertificateCamera) | 256 | Java | **无 LICENSE** | 无 | 全部 | ⚠️ 不能用 |

### B. 抠图 / 人像分割 赛道（排版无关，但影响内核选型）

| 项目 | ★ | 语言 | 许可证 | 分类 | 结论 |
|---|---|---|---|---|---|
| [danielgatis/rembg](https://github.com/danielgatis/rembg) | 25.1k | Python | **MIT**（`LICENSE.txt`）[许可证原文] | 🟢 可直接复用代码 | 代码 MIT 可闭源商用；**但权重各自独立授权**（见模型表） |
| [imgly/background-removal-js](https://github.com/imgly/background-removal-js) | 7.4k | TypeScript | **AGPL-3.0** [许可证原文] | 🔴 不可闭源 | 浏览器抠图最强，但 AGPL |
| [ZHKKKe/MODNet](https://github.com/ZHKKKe/MODNet) | 4.4k | Python | **Apache-2.0** [许可证原文] | 🟢 可直接复用代码+权重 | 实时人像抠图，CPU 友好，**本项目首选抠图模型** |
| [xuebinqin/U-2-Net](https://github.com/xuebinqin/U-2-Net) | 9k+ | Python | **Apache-2.0** [许可证原文] | 🟢 可直接复用 | 老牌，边缘比 MODNet 糊 |
| [xuebinqin/DIS](https://github.com/xuebinqin/DIS) | 1k+ | Python | **Apache-2.0**（`LICENSE.md`）[许可证原文] | 🟢 可直接复用 | 即 rembg 的 `isnet-general-use` 来源 |
| [ZhengPeng7/BiRefNet](https://github.com/ZhengPeng7/BiRefNet) | 2k+ | Python | **MIT** [许可证原文] + 权重 HF `license: mit` [模型卡原文] | 🟢 可直接复用代码+权重 | 精度最高，CPU 7s 级；含 `BiRefNet_HR-matting` 抠发丝专用权重 |
| [facebookresearch/segment-anything](https://github.com/facebookresearch/segment-anything) | 50k | Python | **Apache-2.0** [许可证原文] | 🟢 可直接复用 | 交互式分割，非自动抠图，做"手动修边"有价值 |
| [facebookresearch/sam2](https://github.com/facebookresearch/sam2) | 10k+ | Python | **Apache-2.0** [许可证原文] | 🟢 可直接复用 | 同上，视频版 |
| [MarcoForte/closed-form-matting](https://github.com/MarcoForte/closed-form-matting) | 444 | Python | **MIT** [许可证原文] | 🟢 可直接复用 | 经典 alpha matting，做发丝精修兜底 |
| [zllrunning/face-parsing.PyTorch](https://github.com/zllrunning/face-parsing.PyTorch) | 2.6k | Python | **MIT**（代码）[许可证原文] | 🟡 代码可复用，**权重受限** | 权重训练于 CelebAMask-HQ（非商用数据集），见风险表 |
| [PeterL1n/RobustVideoMatting](https://github.com/PeterL1n/RobustVideoMatting) | 9.6k | Python | **GPL-3.0** | 🔴 | 只能借鉴 |
| [1038lab/ComfyUI-RMBG](https://github.com/1038lab/ComfyUI-RMBG) | 2.2k | Python | **GPL-3.0** | 🔴 | 只能借鉴 |
| [addyosmani/bg-remove](https://github.com/addyosmani/bg-remove) | 1k | TypeScript | **MIT** | 🟢 | 纯前端抠图 UI 参考 |

---

## 二、模型许可证表

许可证原文核对结果（✅=读过 LICENSE/HF 模型卡原文；⚠️=README/二手）：

| 模型 | 许可证 | 能否商用 | 体积 | CPU 推理量级 | 中文证件照推荐度 | 证据 |
|---|---|---|---|---|---|---|
| **MODNet**（`modnet_photographic_portrait_matting`） | **Apache-2.0**（代码+权重同协议） | ✅ 能 | **24.7 MB** ONNX | **0.21 s**（512×715，M1 Max CPU）| ⭐⭐⭐⭐⭐ **首选** | ✅ LICENSE + README + Hivision 实测表 |
| **hivision_modnet**（Hivision 自训） | 随 HivisionIDPhotos **Apache-2.0** | ✅ 能（建议在 README 中自行确认权重条款） | 24.7 MB | 同上 | ⭐⭐⭐⭐⭐ 纯色换底适配更好 | ⚠️ 仓库 README（权重本体无独立 LICENSE 文件） |
| **BiRefNet**（general / HR-matting） | **MIT** | ✅ 能 | 224 MB～1 GB | ~7.1 s（512×715）| ⭐⭐⭐⭐ 精度最高，做"高清精修档" | ✅ LICENSE + HF `license: mit` |
| **isnet-general-use**（DIS） | **Apache-2.0**（`LICENSE.md`） | ✅ 能 | **170.4 MB** | 1～2 s | ⭐⭐⭐⭐ 边缘优于 u2net | ✅ DIS LICENSE + HTTP HEAD |
| **u2net**（U-2-Net） | **Apache-2.0** | ✅ 能 | 167.8 MB | 1～2 s | ⭐⭐⭐ 偏糊 | ✅ LICENSE + HTTP HEAD 实测 |
| **BRIA RMBG-1.4** | `bria-rmbg-1.4`（custom，"source-available model for **non-commercial use**"，商用需向 BRIA 购买）| ❌ **不能** | 176 MB | ~1～2 s | ⛔ **禁用** | ✅ HF 模型卡原文：*"RMBG v1.4 is available as a source-available model for non-commercial use. To purchase a commercial license..."* |
| **BRIA RMBG-2.0** | `bria-rmbg-2.0`，license_link = **CC-BY-NC-4.0**，gated | ❌ **不能**（非商业：个人/学术/非营利） | ~1.02 GB ONNX | 3～10 s | ⛔ **禁用** | ✅ HF API cardData + rembg README 明示"requires a paid agreement for commercial use" |
| **rembg（工具）** | **MIT** | ✅ 能（代码） | — | — | ⭐⭐⭐⭐ 工程封装好 | ✅ `LICENSE.txt` |
| **SAM / SAM2** | **Apache-2.0** | ✅ 能 | 375 MB～2.4 GB | 慢（秒～十秒级） | ⭐⭐ 交互式修边可用，不适合主链路 | ✅ LICENSE |
| **MTCNN**（ipazc/mtcnn） | **MIT** | ✅ 能 | ~2 MB | **毫秒级** | ⭐⭐⭐⭐ 快但精度一般 | ✅ LICENSE |
| **RetinaFace**（biubug6/Pytorch_Retinaface） | **MIT**（文件名是 `LICENSE.MIT`，不是 `LICENSE` —— 网上"RetinaFace 无许可证"的说法是错的） | ✅ 能 | ResNet50 ~109 MB / MobileNet0.25 ~1.7 M 参数 | ~0.57 s | ⭐⭐⭐⭐ 精度高，Hivision 可选 | ✅ `LICENSE.MIT` 原文 + GitHub API `path=LICENSE.MIT` |
| **insightface** | **代码 MIT，但模型/训练数据明确非商用** | ❌ **模型不能商用** | — | — | ⛔ 人脸识别链路禁用 | ✅ README 原文：*"The training data ... (and the models trained with these data) are available for **non-commercial research purposes only**. Both manual-downloading models from our github repo and auto-downloading models ... follow the above license policy"* |
| **MediaPipe Face Detection** | **Apache-2.0** | ✅ 能 | ~0.2 MB tflite | 毫秒级 | ⭐⭐⭐⭐⭐ 最轻量，适合"实时取景对位" | ✅ LICENSE |
| **face_alignment**（1adrianb） | **BSD-3-Clause** | ✅ 能 | 中 | 快 | ⭐⭐⭐ 关键点用 | ✅ LICENSE |
| **face-parsing.PyTorch（BiSeNet）** | 代码 **MIT**，但**权重训练于 CelebAMask-HQ** | ❌ **权重不能商用**（数据集明确非商用） | ~50 MB | ~0.1 s | ⭐⭐ 只能自用；商用需自行在商用数据集上重训 BiSeNet | ✅ 代码 LICENSE + CelebAMask-HQ README 原文 |
| **YOLOv8n-pose**（LiYing 用） | **AGPL-3.0**（Ultralytics 双许可） | ❌ 闭源商用需买 Ultralytics 商业许可 | ~13 MB | 快 | ⛔ **避开**，改用 MediaPipe Pose 或 OpenCV | ⚠️ 二手（Ultralytics 许可政策，共识性事实） |
| closed-form-matting | **MIT** | ✅ 能 | 纯算法 | 0.5～2 s | ⭐⭐⭐⭐ 发丝精修兜底 | ✅ LICENSE |

> **性能实测数据来自 HivisionIDPhotos README 在 M1 Max 上的官方测试**（非本机复测）：MODNet+mtcnn 410 MB 内存 / 0.207 s；MODNet+retinaface 0.571 s；birefnet-v1-lite+retinaface 6.20 GB 内存 / 7.063 s。

---

## 三、任务 A 细节（源码级核实）

### 1. aoguai/LiYing 到底做了什么 [源码]
模块清单（`src/tool/`）：
- **人像识别**：`yolov8_detector.py`（YOLOv8n-pose，出人体框+肩/髋关键点）、`YuNet.py`（OpenCV YuNet 人脸检测）、`RetinaFaceDetector.py`（可选换 RetinaFace）、`SkinRetouch.py` + `onnx_skin_retouching/`（磨皮/美颜，内含 face_detector.onnx）
- **抠图换底**：`ImageSegmentation.py`（ONNX Runtime 跑 RMBG-1.4/2.0，preprocess = /255 后 mean0.5/std1.0，postprocess 做 min-max 归一化再 `paste` 合成 RGBA）
- **裁剪构图**：`ImageProcessor.py::_get_photo_crop_coordinates` — **人脸框高占比 `face_height_ratio=0.30`、头顶留白 `top_margin_ratio=0.175`**，裁剪框中心对齐人脸中心 X、顶部锚定人脸框 Y
- **旋转矫正**：`compute_rotation_angle()` 用左右肩关键点算旋转角
- **排版**：`PhotoSheetGenerator.py` — **5 寸相纸 (1050,1500)@300dpi**，参数 `rows/cols/rotate/add_crop_lines/layout_position(0-8 九宫格锚点)/photos_spacing`，裁剪线是**每张照片画黑色矩形框 + 一个外框**
- **压缩**：`agpic.py`（mozjpeg 无损优化 / pngquant / WebP / 目标 KB 与 KB 区间二分调质量）
- **规格库**：`data/size_zh.csv`（GBK）含约 40 种中国证件照规格（一寸 295×413、二寸 413×579/626、身份证 358×441@350dpi、社保 358×441、驾照 260×378、各国签证、A4/3R/4R 相纸）+ `data/color_zh.csv` 10 种底色 RGB
- **GUI**：**有** —— `src/webui/app.py`（75 KB，Gradio Blocks，中英双语 i18n，批量上传/批量下载）
- **架构**：CLI（click）+ Gradio WebUI 双入口；ONNX Runtime；提供 PyInstaller 打包（`run_*.bat`，README 提供 Windows 7 SP1/10 已测的免安装包，但**不含模型**，模型需自行下载）

**AGPL-3.0 对闭源/自用分发的含义**（法律要点，非法律意见）：
- 自用、不向他人提供 → AGPL 的"convey"义务不触发，**自己改着用没问题**。
- 给朋友（把 exe 或源码发出去）→ 构成 §6 "convey 非源码形式"，必须**同时提供完整对应源码**（含你自己的修改），且 §5c 要求**整体作品以 AGPL-3.0 授权**。=> 你的界面代码也得开源。
- 若做成联机服务 → §13 要求向网络用户提供源码。
- **叠加风险**：LiYing 默认抠图模型是 **RMBG-1.4/2.0（非商用）**，即使你愿意开源，也**不能商用**；且 `yolov8n-pose` 属 Ultralytics AGPL 生态。所以 LiYing 这条线是"AGPL + 非商用权重 + AGPL 权重"三重锁。

### 2. zhbhun/idify [源码]
- 浏览器内 onnxruntime-web 跑抠图，`packages/common/src/stores/SegmentStore.ts` 调用 `@zhbhun/background-removal`（= img.ly `background-removal-js` 的私有再发布，**AGPL-3.0**）；默认模型路径是 **unpkg CDN**（`https://unpkg.com/@zhbhun/background-removal@1.0.8/dist/`），首次使用**必须联网**下载，缓存后（`downloaded` 标志）才可离线。
- 本地资产：`packages/mobile/public/assets/background-removal/` 有 ~7 个 10 MB `.onnx` + 多个 9～18 MB `.wasm`（onnxruntime-web 不同 SIMD/线程变体 + 量化模型），共 ~157 MB —— **移动端（Capacitor Android）是离线打包的**。
- **它没有任何相纸排版代码**（grep `paper/sheet/layout` 只命中 UI 组件 `LayoutBox`）。它的价值是 `packages/common/src/config/spec.json`（575 KB）—— **约 100 个国家的护照/签证/身份证规格 + `minHeadHeight`/`minHeadOffset` 比例规则 + 600 DPI 像素尺寸**，是很好的规格数据参考（但要按 GPL-3.0 处理）。

### 3. gmajian/sandphoto 排版算法 [源码]
`sandphoto.inc` 全文仅 ~200 行，算法：
- 常量：`CM_PER_INCH=2.54`、`DPI=300`；cm→px 用 `floor(cm*300/2.54)`
- 间距 **`GAP=5` 像素**（固定）
- **不转置**：`wn=floor(W/(tw+GAP))`、`hn=floor(H/(th+GAP))`
- **转置**：`wn2=floor(H/(tw+GAP))`、`hn2=floor(W/(th+GAP))`；若 `wn2*hn2 > wn*hn` 则**旋转相纸**（`rotate_container()`）并采用转置布局
- 居中：`w_start=(W - wn*(tw+GAP) + GAP)/2`，H 同理
- 裁源图：按 `ratio1=w/tw, ratio2=h/th` 较大者取中心裁剪（等比填充+居中）
- **无裁剪线**；输出 JPEG quality=100，带 `www.sandcomp.com` 水印；`phototype.txt` 用 GBK 编码列出证件尺寸与相纸尺寸
- 另有 `preview.php` 生成 500×500 内缩略图
- **结论：算法思路可自由借鉴（数学本身不受版权保护），但 PHP 代码受 GPL-2.0 约束。自己用 C#/TS/Rust 重写 60 行完全等价，且能做得更好（可变间距、裁剪线、7 寸）。**

### 4. HivisionIDPhotos 生态 [源码 + README]
官方在 README 列出/社区贡献：
- [HivisionIDPhotos-ComfyUI](https://github.com/AIFSH/HivisionIDPhotos-ComfyUI)（196★，**Apache-2.0**）— ComfyUI 工作流
- [HivisionIDPhotos-wechat-weapp](https://github.com/no1xuan/HivisionIDPhotos-wechat-weapp)（545★，**无 LICENSE**）— JAVA 后端+小程序
- [HivisionIDPhotos-Uniapp](https://github.com/soulerror/HivisionIDPhotos-Uniapp)（241★，**无 LICENSE**）
- [HivisionIDPhotos-windows-GUI](https://github.com/zhaoyun0071/HivisionIDPhotos-windows-GUI)（196★，**无 LICENSE**）— 解压即用 Windows 客户端
- [HivisionIDPhotos-web](https://github.com/jkm199/HivisionIDPhotos-web)、[ai-idphoto](https://github.com/wmlcjj/ai-idphoto)、[HivisionIDPhotos-cpp](https://github.com/zjkhahah/HivisionIDPhotos-cpp)（C++ 重写，社区贡献）
- 官方自身提供 **`app.spec`（PyInstaller 打包配置，入口 `app/web.py`，内置 `hivision_modnet.onnx` + `size_list_CN.csv`）**、`deploy_api.py`（REST API）、Docker 镜像 `linzeyi/hivision_idphotos`、在线 Demo（HF Spaces / ModelScope / 魔搭）
- **关键：官方 Windows 打包路径已经验证可行**，且 `hivision/creator/__init__.py` 的 `IDCreator` 是干净的 Apache-2.0 内核，回调点（`before_all/after_matting/after_detect/after_all`）留得很适合二次开发

### 5. 排版算法参数对照表 [源码，三处交叉验证]

| 项目 | 相纸 | 画布(px)@300dpi | 照片间距 | 边距 | 自动旋转取最多 | 裁剪线 | 布局锚点 |
|---|---|---|---|---|---|---|---|
| HivisionIDPhotos `layout_calculator.py` | 6 寸 4R | 1795 × 1205（参数化，可传任意） | 30 px | 水平 70 / 垂直 50 px | ✅ 比较转置/不转置张数取大 | ✅ 浅灰 `(200,200,200)` 1px，**贯穿整张相纸的横竖延长线** | 居中 |
| LiYing `PhotoSheetGenerator.py` | 5 寸 3R | 1050 × 1500 | `photos_spacing` 可变 | 由 layout_position 决定 | ✅ 有 `rotate` 开关 | ✅ **每张画黑矩形** + 一个大外框 | 九宫格 0–8 |
| sandphoto `sandphoto.inc` | 6 寸（可传） | 按 cm 换算 | 固定 5 px | 居中 | ✅ 张数比较 | ❌ 无 | 居中 |

标准相纸像素表（300 DPI，可自行验证）：3R 5寸 = 1051×1500（8.9×12.7cm）；4R 6寸 = 1205×1795（10.2×15.2cm）；5R 7寸 = 1500×2102（12.7×17.8cm）；A4 = 2480×3508；8寸 6R = 1795×2402；10寸 8R = 2402×3000。

---

## 四、任务 C 的三个明确回答

### C-1：HivisionIDPhotos（Apache-2.0）当内核 + 自己写界面，是不是最优解？

**是，但要限定"内核"的含义 —— 最优点法是「Hivision 内核（Python 进程/CLI）+ 原生界面」，不是「重写一遍」。**

| 方案 | 许可 | 体积 | 开发量 | 结论 |
|---|---|---|---|---|
| **A. Hivision 后端 + C#/WPF 或 Tauri 前端**（Python 用 PyInstaller 打包成 sidecar exe，通过 REST/stdio 通信）| ✅ 全绿（Apache-2.0，自写界面可闭源） | ~150–300 MB（含 onnxruntime + 模型） | 低（内核 0 工作量） | ⭐ **推荐**。官方 `app.spec` 已验证 PyInstaller 可打包；`deploy_api.py` 已提供 REST 接口，前端直接调 |
| B. 纯前端 onnxruntime-web + Tauri/Electron | ⚠️ 抠图模型必须自选 | ~60–120 MB | 中高 | 可行但**不划算**：可商用的浏览器抠图权重只有 MODNet（Apache-2.0）/ BiRefNet（MIT），BiRefNet 在 wasm 上 7 s+ 不可接受；MODNet 质量不如 isnet；且 600 DPI 排版、RAW/EXIF、批量打印在浏览器里全是坑 |
| C. Tauri + Rust + ONNX Runtime 原生 | ✅ | ~30–80 MB | **最高**（人脸检测/裁剪/排版/压缩全要自己写 rust） | 除非你追求极致小体积，否则不划算 |
| D. 直接用 LiYing（AGPL）+ 改界面 | ❌ AGPL 传染 + 非商用权重 | — | 低 | ⛔ 排除 |

**注意三个"必须自己改"的点**（Hivision 现成的不能直接用）：
1. **默认排版只有 6 寸 4R 与 5 寸**（2024.11.20 起支持六寸/五寸/A4/3R/4R 五种），**7 寸 5R 需自己加**（`generate_layout_array` 的 `LAYOUT_WIDTH/HEIGHT` 是参数，改一行即可）。
2. **`hivision_modnet.onnx` 的权重许可证没有独立文件**，分发前建议在 README/关于页写明来源与 Apache-2.0 归属；若不确定，直接换用 MODNet 官方权重 `modnet_photographic_portrait_matting.onnx`（Apache-2.0 明确）。
3. **绝对不要把 `rmbg-1.4.onnx` / RMBG-2.0 打进安装包** —— 那是"非商用"权重。同理 **MTCNN**（Hivision 默认人脸检测）建议换成 **MediaPipe Face Detection（Apache-2.0，~0.2 MB，毫秒级）** 或 OpenCV YuNet（Apache-2.0）。

### C-2：有没有现成的"5/6/7 寸相纸排版 + 裁剪线"可以直接抄？

**没有可以直接抄代码的（许可证干净 + 覆盖 5/6/7 寸 + 有裁剪线，三者同时满足的项目不存在）。但算法本身 60 行，自己写最优。**

| 候选 | 5/6/7 寸 | 裁剪线 | 许可证 | 能否抄代码 |
|---|---|---|---|---|
| HivisionIDPhotos `layout_calculator.py` | 5/6 寸 ✅，7 寸 ❌ | ✅ | Apache-2.0 | ✅ **能抄**（唯一法律允许的） |
| LiYing `PhotoSheetGenerator.py` | 仅 5 寸 | ✅ | AGPL-3.0 | ❌ |
| sandphoto `sandphoto.inc` | 6 寸，可传参 | ❌ | GPL-2.0 | ❌ |
| idify | ❌ 无排版功能 | — | GPL-3.0 | ❌ |

**推荐做法**：把三家的参数（间距/边距/居中/自动旋转/裁剪线）作为"思路"重新实现一版参数化的 `PaperLayout`，输入 `paperW_cm/paperH_cm/gap_mm/margin_mm/photoW_px/photoH_px/dpi`，输出 `(positions[], rotated)`；裁剪线用 **Hivision 的贯穿式延长线**（打印裁剪更准）+ **LiYing 的每张包围框**（视觉更清楚）二选一或都提供开关。

### C-3：换底色的发丝边缘质量瓶颈在哪？业界怎么做？

**瓶颈有四个（按影响排序）：**
1. **掩膜分辨率不足** → MODNet 推理固定 512×512，上采样到 295×413 或 600 DPI 时边缘出现台阶与"白边"。`ImageSegmentation.postprocess_image` 只做 `Image.BILINEAR` 直接放大，这是 LiYing/Hivision 的共同弱点。
2. **半透明发丝被判成背景** → 抠图是二值/软分割，发丝间隙的真实 alpha 在 0.2–0.8 之间，被抹成 0 或 1，发丝"断掉"。
3. **色彩溢出（color spill）** → 原背景（尤其绿幕/灰墙）的颜色混进发丝像素，换白底后发丝发灰/发绿。
4. **合成方式** → 直接 `paste(mask=alpha)` 会把半透明像素与原底色按错误方式混合，产生光晕（halo）。

**业界常用三档做法：**
- **① trimap + alpha matting（质量最好）**：用 MODNet/BiRefNet 的软掩膜，经形态学 `erode/dilate` 生成三段 trimap（前景 1 / 未知带 / 背景 0），再跑 **closed-form matting（MIT）** 或 KNN/LBDM 在未知带上求解真实 alpha。**开源可直接用：[MarcoForte/closed-form-matting](https://github.com/MarcoForte/closed-form-matting)（MIT）**。这条路线能把发丝质量拉高一档，代价是 0.5–2 s。
- **② face parsing 引导（最便宜，但本项目有许可证障碍）**：`face-parsing.PyTorch`（BiSeNet，**代码 MIT**）出 hair/skin/cloth 语义图，只在 **hair 区域**放开软 alpha 并做精细化，非发区域走硬阈值。**但权重训练于 CelebAMask-HQ，该数据集明确"non-commercial research purposes only"且禁止商用"any portion of derived data"，所以权重在商用场景不可用**。替代：自行在商用数据集上重训 BiSeNet，或直接用 isnet/BiRefNet 的软掩膜 + guided filter 达到相近效果。
- **③ 引导滤波 / 掩膜精修（工程性价比最高）**：用原图当引导图跑 **Guided Filter / joint bilateral** 对低分掩膜上采样，OpenCV `ximgproc.guidedFilter`（Apache-2.0）和 `cv2.ximgproc` 都有现成实现。这一步能同时解决瓶颈 1 和部分瓶颈 3，**成本几乎为零，强烈建议先做**。

**开源现成的"高质量方案"排序（可直接用 → 需改造）：**
1. `isnet-general-use`（Apache-2.0，rembg 内置，176 MB）—— 比 u2net 边缘明显好，CPU 1–2 s，商用无忧。
2. `BiRefNet_HR-matting`（**MIT，含专门 matting 权重**）—— 目前开源最强发丝质量，CPU ~7 s，适合"高清档"按钮。
3. `MODNet`（Apache-2.0，24.7 MB，0.2 s）—— 主链路实时档。
4. **组合拳（推荐架构）**：MODNet 出快掩膜做实时预览 → 用户点"精修"时切 BiRefNet_HR-matting + guided filter + closed-form matting → 合成阶段做 **spill suppression**（在边界带用 `alpha * fg + (1-alpha) * (bg - spill_estimate)`）并在发丝带做 1–2 px 的高斯羽化。
5. ⛔ **RMBG-1.4/2.0 虽然质量好，但非商用，本项目不可用**——这是最容易踩的坑（LiYing 和 rembg 的默认模型都是它）。

---

## 五、许可证风险速查（必须避开的坑）

| 坑 | 具体条款 | 出处 |
|---|---|---|
| 🔴 **RMBG-1.4** 来源可用 | "source-available model for **non-commercial use**"，商用须购买 | HF 模型卡原文 |
| 🔴 **RMBG-2.0** 是 rembg **默认模型** | `license_name: bria-rmbg-2.0`，`license_link: creativecommons.org/licenses/by-nc/4.0`，gated（需勾选"非商业"） | HF API cardData |
| 🔴 **insightface** 代码 MIT 但模型非商用 | ① "models trained with these data are available for **non-commercial research purposes only**" ② "Both manual-downloading models from our github repo and auto-downloading models (with our python-library) follow the above license policy" ③ "For open-sourced face recognition models (e.g., **buffalo_l** package), please contact **recognition-oss-pack@insightface.ai** for licensing"<br>**注意：insightface 仓库根本没有 LICENSE 文件**，MIT 只在 README 正文里声明 | insightface README 原文 |
| 🔴 **rembg 的默认模型现在是 `bria-rmbg` = RMBG-2.0 = CC BY-NC 4.0** | 直接 `pip install rembg` + 默认调用就落到非商用权重上。rembg README 自己警告："Model weights carry their own licenses, **independent of rembg's MIT license** — check the linked source before using any model commercially." | rembg README + HTTP HEAD（976.9 MB） |
| 🟡 **刷新认知：RMBG-2.0 的架构就是 BiRefNet** | HF 页面 JSON：`config.architectures = ["BiRefNet"]` => 用 **MIT 的 BiRefNet 官方权重可以获得同等能力且完全可商用**；RMBG-1.4 则基于 IS-Net/DIS（上游 Apache-2.0） | HF 页面 JSON 原文 |
| 🟡 **face-parsing 的 ONNX 再分发全部有雷** | `Xenova/face-parsing`、`jonathandinu/face-parsing`（19.8 万下载）**没有任何 license 标签** => 默认保留所有权利；`litert-community/BiSeNet-Face-Parsing-LiteRT` 自称 MIT，但那是再分发者单方面的声明，底层权重仍源自 CelebAMask-HQ | HF 页面元数据 |
| 🔴 **LiYing** 是 AGPL-3.0 **且** 用 RMBG + YOLOv8(AGPL) | §5c 整体 AGPL；权重非商用 | LICENSE 原文 + README |
| 🟡 **idify** 无 LICENSE 文件，README 称 GPL；实际抠图内核是 img.ly AGPL-3.0 | 双重 copyleft | README + npm registry + img.ly LICENSE.md 原文 |
| 🔴 **face-parsing 权重**训练于 CelebAMask-HQ | 数据集**明确非商用**：<br>"The CelebAMask-HQ dataset is available for **non-commercial research purposes** only."<br>"You agree **not to** reproduce, duplicate, copy, sell, trade, resell or exploit for any commercial purposes, any portion of the images **and any portion of derived data**."<br>"The use of this software is RESTRICTED to **non-commercial research and educational purposes**."<br>=> **BiSeNet 人脸解析权重（derived data）商用禁用**；代码 MIT 但权重是另一回事 | CelebAMask-HQ README「Dataset Agreement」原文 |
| 🟡 **Hivision 生态多个 GUI/小程序仓库无 LICENSE** | 默认"保留所有权利"，法律上不可复用 | GitHub API `license: null` |
| 🟢 **安全区** | Apache-2.0：HivisionIDPhotos、MODNet、U-2-Net、DIS/isnet、SAM/SAM2、MediaPipe、OpenCV；MIT：BiRefNet、rembg(代码)、MTCNN、RetinaFace、face-parsing(代码)、closed-form-matting | 均为 LICENSE 原文核实 |

---

## 六、引用 URL

**仓库**
- https://github.com/Zeyi-Lin/HivisionIDPhotos （Apache-2.0）
- https://github.com/aoguai/LiYing （AGPL-3.0）
- https://github.com/zhbhun/idify （GPL-3.0，无 LICENSE 文件）
- https://github.com/gmajian/sandphoto （GPL-2.0）
- https://github.com/imgly/background-removal-js （AGPL-3.0）· https://raw.githubusercontent.com/imgly/background-removal-js/main/LICENSE.md
- https://www.npmjs.com/package/@zhbhun/background-removal · https://registry.npmjs.org/@zhbhun/background-removal/latest
- https://github.com/ZHKKKe/MODNet （Apache-2.0）· https://raw.githubusercontent.com/ZHKKKe/MODNet/master/LICENSE
- https://github.com/ZhengPeng7/BiRefNet （MIT）· https://raw.githubusercontent.com/ZhengPeng7/BiRefNet/main/LICENSE
- https://huggingface.co/ZhengPeng7/BiRefNet · https://huggingface.co/ZhengPeng7/BiRefNet_HR-matting
- https://huggingface.co/briaai/RMBG-1.4 · https://huggingface.co/briaai/RMBG-2.0 · https://huggingface.co/api/models/briaai/RMBG-2.0
- https://bria.ai/bria-huggingface-model-license-agreement/
- https://creativecommons.org/licenses/by-nc/4.0/deed.en
- https://github.com/danielgatis/rembg （MIT）· https://raw.githubusercontent.com/danielgatis/rembg/main/LICENSE.txt
- https://github.com/xuebinqin/U-2-Net （Apache-2.0）· https://github.com/xuebinqin/DIS （Apache-2.0）
- https://github.com/facebookresearch/segment-anything · https://github.com/facebookresearch/sam2 （Apache-2.0）
- https://github.com/deepinsight/insightface （代码 MIT / 模型非商用）
- https://github.com/ipazc/mtcnn （MIT）· https://github.com/biubug6/Pytorch_Retinaface （MIT）
- https://github.com/google-ai-edge/mediapipe （Apache-2.0）· https://github.com/1adrianb/face-alignment （BSD-3-Clause）
- https://github.com/zllrunning/face-parsing.PyTorch （MIT）· https://github.com/switchablenorms/CelebAMask-HQ
- https://github.com/MarcoForte/closed-form-matting （MIT）
- https://github.com/PeterL1n/RobustVideoMatting （GPL-3.0）· https://github.com/1038lab/ComfyUI-RMBG （GPL-3.0）
- https://github.com/AIFSH/HivisionIDPhotos-ComfyUI （Apache-2.0）
- https://github.com/zhaoyun0071/HivisionIDPhotos-windows-GUI · https://github.com/no1xuan/HivisionIDPhotos-wechat-weapp · https://github.com/soulerror/HivisionIDPhotos-Uniapp （均无 LICENSE）
- https://github.com/ted-piotrowski/webcam-passport-photo （MIT）· https://github.com/seasonSH/DocFace （MIT）· https://github.com/dpar39/ppp （GPL-3.0）
- https://github.com/pangxiaobin/image-matting （NOASSERTION）

**源码文件（已 clone 到 `_research/`）**
- `_research/HivisionIDPhotos/hivision/creator/layout_calculator.py`、`photo_adjuster.py`、`context.py`、`__init__.py`、`human_matting.py`、`app.spec`
- `_research/LiYing/src/tool/PhotoSheetGenerator.py`、`ImageProcessor.py`、`ImageSegmentation.py`、`PhotoRequirements.py`、`data/size_zh.csv`、`data/color_zh.csv`、`src/webui/app.py`
- `_research/sandphoto/sandphoto.inc`、`phototype.txt`、`sandphoto.js`
- `_research/idify/packages/common/src/stores/SegmentStore.ts`、`config/spec.json`、`packages/*/package.json`

---

## 七、证据级别声明

| 结论 | 级别 |
|---|---|
| Hivision/LiYing/sandphoto/idify 的功能、架构、排版算法、参数常数 | **读源码核实**（clone 后逐文件读） |
| MODNet、BiRefNet、U-2-Net、DIS、rembg、MTCNN、RetinaFace、face-alignment、face-parsing、SAM、SAM2、MediaPipe、closed-form-matting、img.ly 的许可证 | **读 LICENSE 原文核实** |
| RMBG-1.4 / RMBG-2.0 非商用条款、BiRefNet 权重 MIT | **读 HuggingFace 模型卡 / API cardData 原文核实** |
| insightface "模型非商用" | **读 README 原文核实** |
| LiYing 的 AGPL 法律解释（convey / §5c / §6 / §13） | 基于 **LICENSE 原文**的解读，**非法律意见** |
| 各模型 CPU 推理耗时、内存 | **HivisionIDPhotos README 官方实测表（M1 Max）**，非本机复测 |
| 模型体积（24.7 MB / 176 MB / 224 MB / 1.02 GB） | **Hivision README + rembg README**（二手，未下载称重） |
| YOLOv8n-pose 的 AGPL/Ultralytics 双许可 | **README/二手，未读 LICENSE 原文** |
| CelebAMask-HQ 数据集条款 | **已核实（读 README「Dataset Agreement」原文）**：非商用研究专用，禁止商用利用任何衍生数据 |
| `hivision_modnet.onnx` 权重的独立授权 | **未核实**（发布页 403；建议自行在 release 页确认或直接换 MODNet 官方权重） |
| GitHub star 数 | 抓取时 API 快照 |
| 各 ONNX 权重**精确体积**（u2net 167.8 MB / isnet-general-use 170.4 MB / birefnet-general 927.6 MB / birefnet-general-lite 213.6 MB / bria-rmbg 976.9 MB / RMBG-1.4 onnx 167.99 MB / MODNet onnx 24.69 MB / BiRefNet safetensors 423.88 MB / SAM1 357.61 MB）| **HTTP HEAD Content-Length + HF tree API 实测** |

---

## 八、补充：rembg 内置模型白名单（按许可证逐个核实）

> 若选用 rembg 作为工程封装，**必须显式指定模型**，否则默认落到非商用权重上。

```bash
# ✅ 可商用（显式指定）
rembg i -m u2net              input.jpg out.png   # Apache-2.0, 167.8 MB
rembg i -m isnet-general-use  input.jpg out.png   # Apache-2.0, 170.4 MB  ← 推荐默认
rembg i -m birefnet-general   input.jpg out.png   # MIT,        927.6 MB
rembg i -m birefnet-general-lite input.jpg out.png# MIT,        213.6 MB  ← 精度/体积平衡点
rembg i -m u2net_human_seg    input.jpg out.png   # Apache-2.0, 167.8 MB
rembg i -m u2net_cloth_seg    input.jpg out.png   # MIT,        168.0 MB
rembg i -m sam                input.jpg out.png   # Apache-2.0, 95.2+8.3 MB
rembg i -m isnet-anime        input.jpg out.png   # Apache-2.0, 167.9 MB（动漫，无关）
rembg i -m silueta            input.jpg out.png   # Apache-2.0 推断（较弱证据）, 42.1 MB

# ❌ 非商用 —— 千万别用
rembg i                      input.jpg out.png   # 默认 = bria-rmbg = RMBG-2.0 = CC BY-NC 4.0
rembg i -m bria-rmbg         input.jpg out.png   # 同上，976.9 MB，非商用
```

**三个因文件名而生的"许可证误判"（已逐一读原文推翻）：**

| 项目 | 真实许可证文件名 | 常见的错误结论 |
|---|---|---|
| danielgatis/rembg | `LICENSE.txt`（并非 `LICENSE`） | "rembg 无许可证" ❌ |
| biubug6/Pytorch_Retinaface | `LICENSE.MIT`（并非 `LICENSE`） | "RetinaFace 无许可证，不可用" ❌ |
| xuebinqin/DIS | `LICENSE.md`（并非 `LICENSE`） | "DIS 无许可证" ❌ |

**结论：三者实际都是 MIT / Apache-2.0，可商用。**

> 另注：BRIA 在 RMBG-1.4 模型卡里引用的许可协议 URL（`bria.ai/bria-huggingface-model-license-agreement/`）**现已 404**，RMBG-2.0 的 README raw 抓取返回 **401**（gated）。因此**无法读到 BRIA 协议的完整条款正文**，但其"非商用"结论在 HuggingFace 第一方元数据里表述明确、无歧义。
