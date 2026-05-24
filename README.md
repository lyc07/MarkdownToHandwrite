# Markdown 手写实验报告生成器

这个项目把一份 Markdown 实验报告排成接近 LaTeX 风格的 A4 PDF，并把正文、公式和表格渲染成手写效果。Markdown 中的图片不会被绘制，程序会为图片保留空白占位区域，方便后续手绘或粘贴。

## 功能

- 支持标题、段落、列表、代码块、公式、Markdown 表格和图片占位。
- 使用 `handright` 作为首选手写渲染引擎，无法渲染时自动回退到 Pillow 扰动手写。
- 参考 `hfmath` 的二维盒式布局思路，将展示公式和行内数学片段中的分式、根式、上下标和横线按 LaTeX 结构排版后再用配置字体书写。
- 支持常用希腊字母、积分/求和/集合与关系符号、可选根指数、`\hat`/`\dot` 等重音、`\binom`，以及 `matrix`/`cases` 矩阵类环境。
- 公式包含不支持的 LaTeX 命令或括号错误时，报告中保留空白位置，并在控制台打印对应的 `[latex-render-error]` 源码提示。
- 按 A4 页面、较宽页边距、分级标题、页码和留白进行类 LaTeX 排版。
- 可自定义背景：纯白、横线纸、方格纸、点阵纸，或指定图片/PDF 作为背景。
- 可自定义字体、墨水颜色、纸张颜色、线条颜色、图片占位高度和随机种子。
- 默认按照项目 `font/` 目录中的编号选择字体，如 `1.ttf -> 2.ttf -> 3.ttf`；当前示例会自动首先使用 `font/1.ttf`。
- 当靠前的编号字体缺少数字或公式字形时，会继续尝试后续编号字体，再使用系统兼容字体补充缺失字符。
- 默认会优先发现项目 `background/` 目录内的背景资源，当前示例使用扫描得到的实验报告纸 PDF。
- Markdown 中可以照常输入中文标点，书写输出会统一转换为西文半角标点。

## 安装

推荐在项目根目录安装依赖：

```powershell
python -m pip install -r requirements.txt
```

本工作区已经尝试并成功安装了依赖到 `.codex_deps`，直接用下面的命令也可以运行：

```powershell
$env:PYTHONPATH='src'
python -m handwritten_report examples/report.md -o output/pdf/sample_report.pdf -c examples/config.json
```

也可以安装为命令行工具：

```powershell
python -m pip install -e .
handwritten-report examples/report.md -o output/pdf/sample_report.pdf -c examples/config.json
```

## Markdown 写法

```markdown
# 实验名称

## 实验原理

单摆周期公式为 $T = 2\pi\sqrt{l/g}$。

$$
g = \frac{4\pi^2 l}{T^2}
$$

| 次数 | 摆长 l/m | 周期 T/s |
| --- | ---: | ---: |
| 1 | 0.50 | 1.42 |

![装置示意图](figures/device.png)
```

图片语法只会产生空白区域，不会读取或绘制图片文件。

## 配置

配置文件使用 JSON。示例见 [examples/config.json](examples/config.json)。

常用字段：

- `background.style`: `plain`、`lined`、`grid`、`dot`
- `background.image`: 背景图片或 PDF 路径，设置后优先使用该文件；PDF 多页时会按报告页序循环使用
- `background.auto_discover`: 未设置 `image` 时是否自动寻找项目 `background/` 目录下的背景文件
- `background.paper_color`: 纸张底色
- `handwriting.font_path`: 可选的首选手写字体路径；未指定时按照 `font/1.ttf`、`font/2.ttf` 等编号顺序选择
- `handwriting.fallback_font_path`: 可选的指定回退字体；未指定时按后续编号字体继续补字，最后回退到系统字体
- `handwriting.ink_color`: 墨水颜色
- `layout.image_placeholder_height_mm`: 图片占位高度
- `layout.number_sections`: 是否自动给标题编号

## 命令行

```powershell
python -m handwritten_report input.md -o report.pdf -c config.json
```

可覆盖配置：

```powershell
python -m handwritten_report input.md -o report.pdf --background grid --paper-color "#fffdf0" --ink-color "#24345c" --seed 42
```

指定扫描报告纸背景：

```powershell
python -m handwritten_report input.md -o report.pdf --background-image "background/扫描_f972498d011548b383f908d9b1a7fc0e.pdf"
```
