# MarkdownToHandwrite

由Markdown文本生成手写风格的pdf。

项目内置WebUI。由SDT生成中文笔迹轨迹，两层随机扰动增加真实性。支持LaTeX公式布局，适合实验报告、课程作业等需要手写观感的文档。


## 特性

- **SDT 轨迹渲染**：运行时直接读取内置的笔迹模型，无需 GPU、PyTorch 或 SDT 训练仓库。
- **统一笔画风格**：中文轨迹、字体中心线符号、公式线和表格线使用同一个基础笔宽。
- **两层自然扰动**：支持字符旋转与偏移、平滑路径扰动、弹性形变、基线起伏、笔压变化、起收笔、墨色波动和飞白。
- **二维数学排版**：支持行内及行间公式，支持分式、根式、上下标等格式。
- **丰富的 Markdown 环境**：支持标题、段落、列表、代码块、表格，以及标题、表格和列表中的行内公式。
- **纸张与分页**：支持纯色、横线、方格、点阵以及图片/PDF 背景，可选择标题编号和底部页码。
- **可复现生成**：相同配置、文稿和随机种子会得到相同结果。
- **本地 WebUI**：提供 Markdown 编辑器、多页预览、明暗主题、三档笔迹预设、全部配置参数以及 JSON 导入/导出。
- **命令行接口**：适合脚本、批处理和自动化工作流。

## 快速开始

### 环境要求

- Python 3.10 或更高版本
- Windows、macOS 或 Linux
- 一个现代浏览器，用于 WebUI

### 安装

克隆或下载仓库后，在项目根目录执行：

```bash
python -m venv .venv
```

激活虚拟环境：

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

安装项目：

```bash
python -m pip install --upgrade pip
python -m pip install -e .
```

也可以仅安装依赖并通过源码运行：

```bash
python -m pip install -r requirements.txt
```

## WebUI

安装后启动本地工作台：

```bash
markdown-to-handwrite-web
```

也可仅安装依赖后从源码启动：

```bash
$env:PYTHONPATH='src'
python -m markdown_to_handwrite.web
```

默认地址为 <http://127.0.0.1:8765/>。预览图和 PDF 会写入 `output/webui/`。

可选启动参数：

```text
--host HOST       监听地址，默认 127.0.0.1
--port PORT       监听端口，默认 8765
--no-browser      启动后不自动打开浏览器
```


## 命令行

将示例 Markdown 生成 PDF：

```bash
markdown-to-handwrite examples/report0.md \
  --output output/pdf/report.pdf \
  --config examples/config.json
```

Windows PowerShell 也可以写成一行：

```powershell
markdown-to-handwrite examples/report0.md -o output/pdf/report.pdf -c examples/config.json
```

常用覆盖参数：

```bash
markdown-to-handwrite input.md -o report.pdf \
  --background grid \
  --paper-color "#fffdf0" \
  --ink-color "#17233b" \
  --dpi 300 \
  --seed 42
```

使用自定义图片或 PDF 背景时，需要同时选择 `image` 样式：

```bash
markdown-to-handwrite input.md -o report.pdf \
  --background image \
  --background-image background/实验报告纸.pdf
```

完整帮助：

```bash
markdown-to-handwrite --help
markdown-to-handwrite-web --help
```

## Markdown 示例

```markdown
# 单摆法测定重力加速度

## 实验原理

单摆周期满足 $T=2\pi\sqrt{l/g}$，因此：

$$
g=\frac{4\pi^2l}{T^2}
$$

函数 $f'(x)$ 的导数与乘积 $a\cdot b$ 也可以直接书写。

| 次数 | 摆长 $l/\mathrm{m}$ | 周期 $T/\mathrm{s}$ |
| ---: | ---: | ---: |
| 1 | 0.500 | 1.421 |
| 2 | 0.550 | 1.493 |

![实验装置](figures/device.png)
```

行内公式支持 `$...$` 和 `\(...\)`，行间公式支持 `$$...$$`。行内公式可出现在普通段落、标题、列表和表格单元格中。

Markdown 图片、`<img>`、`<video>` 和 `<iframe>` 只产生指定高度的占位区域，不会读取或绘制外部内容，方便后续手绘、粘贴或单独排版。

## 公式支持范围

当前公式渲染器覆盖常见教学与实验报告场景：

- 分式、根式、二项式、上下标；
- 希腊字母、集合、关系、箭头和常见二元运算符；
- `\sum`、`\prod`、`\int`、`\iint`、`\iiint`、`\lim` 及 `\limits` / `\nolimits`；
- `\bar`、`\overline`、`\underline`、`\vec`、`\hat`、`\tilde`、`\dot`、`\ddot`；
- `matrix`、`pmatrix`、`bmatrix`、`vmatrix`、`cases` 等网格环境；

不支持的命令或错误的括号不会静默变成普通文字：页面会保留空白位置，控制台会输出 `[latex-render-error]` 和对应公式源码。

## 渲染流程

### 字符来源

每个字符依次经过以下路径：

1. SDT 轨迹库中存在字符时，直接重绘在线笔迹；
2. SDT 中没有时，从选定字体轮廓提取中心线轨迹；
3. 中心线提取失败时，回退为字体栅格字形；
4. 整个 SDT 引擎关闭或不可用时，优先回退到 Handright，再回退到 Pillow。

SDT 模式下，字体主要负责字符边界、排版宽度，以及英文、数字和缺失数学符号的中心线形状；内置中文轨迹的笔迹形状不会被字体轮廓替换。

### 字体回退

字体链按以下规则构建：

1. 显式设置 `handwriting.font_path` 或 `handwriting.math_font_path` 时，优先使用该字体；
2. 未设置首选字体时，先使用项目 `font/` 目录中排序第一的可用字体；
3. 随后依次加入 `handwriting.fallback_font_path`、其余本地字体和系统兼容字体。

程序会逐字符选择第一个包含该字形的字体，并把不同字体的字符对齐到共享基线。`font/` 中纯数字文件名会按数值顺序排列，例如 `1.ttf → 2.ttf → 10.ttf`。

### 两层扰动

| 层级 | 负责内容 | 作用范围 |
|---|---|---|
| 字体与字号 | 字符尺寸、排版度量、非 SDT 字符的中心线形状 | 正文、标题、代码、公式 |
| SDT 轨迹 | 轨迹来源、统一基础笔宽、抗锯齿 | 中文、中心线符号、公式线、表格线 |
| 字形扰动 | 旋转、偏移、路径扰动、弹性形变、基线起伏 | 字符及文字/公式图块 |
| 墨迹扰动 | 笔压、起收笔、整体粗细、浓淡和飞白 | 字符、公式线、表格线 |

位置和整体粗细扰动使用零均值正态分布，并限制在三倍标准差内，减少极端随机值造成的裁切、粘连或异常偏移。

## 配置

配置文件采用 JSON，未提供的字段使用 [默认配置](src/markdown_to_handwrite/config.py)。完整示例见 [examples/config.json](examples/config.json)。

最小配置示例：

```json
{
  "page": {
    "dpi": 300
  },
  "background": {
    "style": "lined",
    "paper_color": "#fffdf4"
  },
  "handwriting": {
    "body_font_pt": 16,
    "math_font_pt": 16,
    "sdt_stroke_width": 16,
    "seed": 2026
  },
  "layout": {
    "show_page_numbers": false
  }
}
```

主要配置组：

| 配置组 | 内容 |
|---|---|
| `page` | 纸张尺寸、DPI 和页边距 |
| `background` | 纸张样式、背景素材、辅助线和颜色 |
| `handwriting` | 字体、字号、SDT 轨迹、笔宽、字形与墨迹扰动 |
| `layout` | 标题编号、段落与公式间距、表格、图片占位和页码 |

建议通过 WebUI 调整参数并导出 JSON；这样可以避免手写字段名，也能看到每个参数的中文说明和合法范围。

几个容易混淆的参数：

- `sdt_stroke_width` 是 SDT 模式下唯一的基础笔宽，同时控制字符、公式线和表格线。
- `stroke_weight_base_scale` 只校准 Handright/Pillow 回退字体，不改变 SDT 基础笔宽。
- `perturb_y_sigma_px` 控制正文字符垂直偏移；`math_perturb_y_sigma_ratio` 独立控制公式字符，并按主字符或上下标各自的字号计算。
- `background.image` 仅在 `background.style` 为 `image` 时使用。
- `show_page_numbers` 关闭后既不绘制页码，也不预留页脚空间。

## 项目结构

```text
src/markdown_to_handwrite/
├── assets/              # 内置 SDT 轨迹包
├── webui/               # 无前端构建步骤的本地 WebUI
├── cli.py               # 命令行入口
├── config.py            # 默认配置与 JSON 加载
├── handwriting.py       # 字体回退与两层笔迹扰动
├── markdown_parser.py   # Markdown 与行内公式解析
├── math_renderer.py     # 二维公式布局与几何符号
├── renderer.py          # 页面排版、表格、分页与 PDF 输出
└── sdt_renderer.py      # SDT 坐标读取和轨迹重绘

examples/                # 示例 Markdown 与配置
font/                    # 本地字体候选
background/              # 背景图片或 PDF
tests/                   # 单元与回归测试
```

## 测试

安装项目后运行：

```bash
python -m unittest discover -s tests
```

测试覆盖 Markdown 解析、字体回退、SDT 渲染、笔迹随机性、公式布局、分页、背景、WebUI 配置和 PDF 生成。

## 已知限制

- 公式渲染器只实现常用 LaTeX 子集，不支持宏包、自定义命令和完整 TeX 排版。
- 图片和 HTML 媒体目前只生成占位区域。
- 内置 6763 字轨迹主要覆盖常用中文字符；扩展字符会使用字体中心线或字体栅格回退。
- 字体的字形完整度、度量和轮廓质量会影响英文、数字与数学符号效果。
- 高 DPI、长文档和较高超采样倍率会显著增加生成时间和内存占用。


## 致谢

- [dailenson/SDT](https://github.com/dailenson/SDT)：中文在线笔迹生成与个性化研究基础。
- [Eyjafjallaaa/HandwriteCraft](https://github.com/Eyjafjallaaa/HandwriteCraft)：手写文档生成和 WebUI 设计参考。
- [Handright](https://pypi.org/project/handright/)：SDT 不可用时的回退手写渲染方案。
- `hfmath`：二维数学盒式布局思路参考。
## License

项目原创源代码采用 MIT License，详见 [LICENSE](LICENSE)。
