# -*- coding: utf-8 -*-
"""全局样式表（扁平 / 浅色 / 少描边）。

集中在这里而不是散落在各个控件里，方便统一调色和统一圆角。

设计上的几条硬规矩（都是踩过的坑）：
1. **只有窗口自己画底色，其它控件一律透明。** 原来写成 `QWidget { background: BG }`，
   而 Qt 的样式表类型选择器会命中所有子类——于是每个 QLabel 都在文字后面糊了一块
   灰底（用户截图反馈"字有灰色的底"）。现在底色只由 QMainWindow / 卡片负责，
   再显式给 QLabel 兜一条 transparent。
2. **按"卡片 + 间距"分层，而不是"框套框"。** 分组标题放在卡片边框**外面**
   （QGroupBox 的 margin-top 里），这样标题不用靠不透明背景去遮边框线，
   也就不需要给它刷底色。
3. 描边统一 1px 浅灰，圆角 8/12，靠留白和字重区分层级，不靠重边框和蓝色药丸标题。
"""
from __future__ import annotations

# ---------------------------------------------------------------- 配色
BG = "#f3f4f7"          # 窗口底色
CARD = "#ffffff"        # 卡片 / 面板
BORDER = "#e7e9ee"      # 卡片描边、分隔线（很浅）
BORDER_STRONG = "#d8dbe3"   # 输入控件描边（比卡片略深，够看见就行）
TEXT = "#1b1f27"
MUTED = "#868d99"       # 次要文字
MUTED_STRONG = "#6b7280"    # 分组标题
PRIMARY = "#2f6fd0"
PRIMARY_HOVER = "#3f7dda"
PRIMARY_PRESSED = "#275fae"
PRIMARY_SOFT = "#eaf1fd"    # 选中态浅底
DANGER = "#d0453a"
WARN = "#c8860a"

RADIUS = 8              # 控件圆角
PANEL_RADIUS = 12       # 卡片圆角
DIALOG_RADIUS = 18      # 弹窗圆角

FONT_STACK = ('"Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", '
              '"Noto Sans CJK SC", sans-serif')


STYLESHEET = f"""
/* ---------- 基础：只有窗口画底色，其它一律透明 ---------- */
QWidget {{
    background: transparent;
    color: {TEXT};
    font-family: {FONT_STACK};
    font-size: 13px;
}}
/* 显式兜一条：QLabel 曾经被全局 QWidget 规则糊上灰底 */
QLabel {{ background: transparent; }}

QMainWindow {{ background: {BG}; }}

/* ---------- 菜单栏 / 工具栏 ---------- */
QMenuBar {{
    background: {CARD};
    border-bottom: 1px solid {BORDER};
    padding: 2px 6px;
}}
QMenuBar::item {{ padding: 5px 10px; border-radius: 6px; background: transparent; }}
QMenuBar::item:selected {{ background: {PRIMARY_SOFT}; color: {PRIMARY}; }}
QMenu {{
    background: {CARD}; border: 1px solid {BORDER};
    border-radius: {RADIUS}px; padding: 6px;
}}
QMenu::item {{ padding: 7px 22px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {PRIMARY_SOFT}; color: {PRIMARY}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}

QToolBar {{
    background: {CARD};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px 10px;
    spacing: 4px;
}}
QToolBar QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {RADIUS}px;
    padding: 6px 12px;
    color: {TEXT};
}}
QToolBar QToolButton:hover {{ background: {PRIMARY_SOFT}; color: {PRIMARY}; }}
QToolBar QToolButton:pressed {{ background: #dbe7fa; }}
QToolBar QToolButton:disabled {{ color: #b9bfc9; }}
QToolBar::separator {{ width: 1px; background: {BORDER}; margin: 5px 8px; }}

/* ---------- 分组卡片：标题在边框外面 ---------- */
QGroupBox {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: {PANEL_RADIUS}px;
    margin-top: 32px;              /* 标题带：卡片之间靠它拉开距离（用户反馈"模块离太近"） */
    /* 内容留白交给各分组的 layout contentsMargins，避免 QSS padding 和
       layout margin 叠加成两层间距 */
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 3px;
    top: 9px;                      /* 落在 margin 里，上距卡片下距边框都留出空白 */
    padding: 0;
    background: transparent;       /* 不需要遮边框线，所以不用刷底色 */
    color: {MUTED_STRONG};
    font-weight: 600;
}}

/* ---------- 按钮 ---------- */
QPushButton {{
    background: {CARD};
    border: 1px solid {BORDER_STRONG};
    border-radius: {RADIUS}px;
    padding: 7px 14px;
    color: {TEXT};
}}
QPushButton:hover {{ background: #f7f9fc; border-color: #c6cdd9; }}
QPushButton:pressed {{ background: #eef1f6; }}
QPushButton:disabled {{ color: #b9bfc9; background: #f7f8fa; border-color: {BORDER}; }}

QPushButton#primary {{
    background: {PRIMARY};
    border: 1px solid {PRIMARY};
    color: #ffffff;
    font-weight: 600;
    padding: 9px 20px;
}}
QPushButton#primary:hover {{ background: {PRIMARY_HOVER}; border-color: {PRIMARY_HOVER}; }}
QPushButton#primary:pressed {{ background: {PRIMARY_PRESSED}; border-color: {PRIMARY_PRESSED}; }}
QPushButton#primary:disabled {{ background: #b9c8e0; border-color: #b9c8e0; color: #eef2f8; }}

QPushButton#ghost {{
    background: transparent;
    border: 1px solid {BORDER_STRONG};
    padding: 9px 16px;
}}
QPushButton#ghost:hover {{ background: {PRIMARY_SOFT}; border-color: #bcd0f2; color: {PRIMARY}; }}

/* ---------- 输入控件 ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {CARD};
    border: 1px solid {BORDER_STRONG};
    border-radius: {RADIUS}px;
    padding: 6px 10px;
    min-height: 20px;
    selection-background-color: {PRIMARY};
    selection-color: #ffffff;
}}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{
    border-color: #c6cdd9;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {PRIMARY};
}}
QLineEdit:read-only {{ background: #f7f8fa; color: {MUTED}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    background: #f7f8fa; color: #b9bfc9;
}}

QComboBox::drop-down {{ border: none; width: 24px; }}
/* 箭头不在 QSS 里画：`border` 拼三角这一招在本机渲染出来是一个小方块
   （实测），改成由 widgets.NoWheelComboBox/NoWheelSpinBox 用 QPainter 画。 */
QComboBox::down-arrow {{
    image: none;
    width: 0; height: 0;
    border: none;
    background: transparent;
}}
QComboBox QAbstractItemView {{
    background: {CARD};
    border: 1px solid {BORDER_STRONG};
    border-radius: {RADIUS}px;
    padding: 5px;
    selection-background-color: {PRIMARY_SOFT};
    selection-color: {PRIMARY};
    outline: none;
}}

/* 数字框的上下箭头：做小、做淡，别再糊成一个黑块 */
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    width: 20px;
    background: transparent;
    border: none;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-position: top right; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-position: bottom right; }}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {PRIMARY_SOFT};
}}
/* 上下箭头同样交给 QPainter 画（QSS 的 border 三角在本机渲染成长方形色块） */
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow,
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: none;
    width: 0; height: 0;
    border: none;
    background: transparent;
}}

/* ---------- 滑块 ---------- */
QSlider::groove:horizontal {{
    height: 4px;
    background: #e3e6ec;
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{ background: {PRIMARY}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    width: 12px; height: 12px;
    margin: -6px 0;
    border-radius: 7px;
    background: {CARD};
    border: 2px solid {PRIMARY};
}}
QSlider::handle:horizontal:hover {{ background: {PRIMARY_SOFT}; }}
QSlider::handle:horizontal:pressed {{ background: {PRIMARY}; }}
QSlider::handle:horizontal:disabled {{ border-color: #c9ced8; background: #f2f3f6; }}

/* ---------- 列表 ---------- */
QListWidget {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: {PANEL_RADIUS}px;
    padding: 6px;
    outline: none;
}}
QListWidget::item {{
    padding: 8px 10px;
    border-radius: 7px;
    margin: 1px 0px;
}}
QListWidget::item:hover {{ background: #f5f7fa; }}
QListWidget::item:selected {{ background: {PRIMARY_SOFT}; color: {PRIMARY}; }}

/* ---------- 单复选 ----------
   两条踩过的坑，别改回去：
   1. 选中态**不能改边框宽度**。Qt 的 QSS 里子控件的 width/height 是内容盒，边框是加在外面的：
      没选中 15+1*2=17px、选中 15+4*2=23px，尺寸一跳，23px 的方块配 8px 圆角就渲染成
      "圆角方块"而不是圆点（用户截图里圈出来的就是这个），行高也跟着被撑大。
      现在两种状态几何完全一致，只换颜色。
   2. 要给文字留足高度：min-height 兜住，否则大字号 / 高 DPI 环境下文字底部会被裁掉
      （用户反馈"点排版预览时字体显示不全"）。 */
QRadioButton, QCheckBox {{
    spacing: 8px;
    padding: 3px 0;
    min-height: 20px;
    background: transparent;
}}
QRadioButton::indicator, QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid #c3c9d4;
    background: {CARD};
}}
QRadioButton::indicator {{ border-radius: 9px; }}   /* 大于半边长 -> 正圆 */
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator:hover, QCheckBox::indicator:hover {{ border-color: {PRIMARY}; }}
QRadioButton::indicator:checked {{
    background: {PRIMARY};
    border-color: {PRIMARY};
}}
QCheckBox::indicator:checked {{
    background: {PRIMARY};
    border-color: {PRIMARY};
}}

/* ---------- 滚动条：细一点 ---------- */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px 2px 2px 0; }}
QScrollBar::handle:vertical {{ background: #d3d7de; border-radius: 4px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: #b9c0cc; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 0 2px 2px 2px; }}
QScrollBar::handle:horizontal {{ background: #d3d7de; border-radius: 4px; min-width: 32px; }}
QScrollBar::handle:horizontal:hover {{ background: #b9c0cc; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- 底部操作栏 / 状态栏 ---------- */
QFrame#actionBar {{
    background: {CARD};
    border-top: 1px solid {BORDER};
}}

QStatusBar {{ background: {CARD}; border-top: 1px solid {BORDER}; color: {MUTED}; }}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {MUTED}; font-size: 12px; }}

QProgressBar {{
    background: #e9ecf1; border: none; border-radius: 5px;
    height: 10px; text-align: center; color: {MUTED}; font-size: 10px;
}}
QProgressBar::chunk {{ background: {PRIMARY}; border-radius: 5px; }}

QSplitter::handle {{ background: transparent; width: 10px; }}
QSplitter::handle:hover {{ background: #e3e6ec; border-radius: 5px; }}

QToolTip {{
    background: #2b3242; color: #ffffff; border: none;
    border-radius: {RADIUS}px; padding: 6px 9px;
}}
"""
