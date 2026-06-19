# Classviva Local Assistant

一个本地运行的 Classviva 辅助控制台。它用 Playwright 打开浏览器，读取当前作业页面，调用你自己配置的 OpenAI 兼容模型生成候选答案，并在你审核后填回网页。

项目默认不包含任何 API Key、登录状态或个人作业链接，适合整理后发布到 GitHub。

## 功能概览

- 本地网页前端：启动、提取、求解、视觉求解、审核、填入都在浏览器页面完成。
- Edge 优先：Windows 上优先启动 Microsoft Edge，失败时回退到 Playwright Chromium。
- DOM 提取：从 Classviva 页面读取题目、公式、输入框、下拉框、单选/多选控件。
- MathJax 处理：尽量保留原始 LaTeX，避免公式被读取成一字一行。
- 视觉兜底：遇到图片、图表、SVG、canvas 或题面质量低时，可用视觉模型补全题面。
- 视觉求解：重新截图当前页面，用视觉模型直接解题，同时附带题号、空位数和选项信息。
- 填入保护：填入前会重新检查当前页面输入框，避免拿上一页的输入框 ID 填当前页。
- 答案格式化：全角转半角、`π` 转 `pi`、`√x` 转 `sqrt(x)`，并按 Classviva 常见格式规则清理答案。

## 工作原理

### 提取题目

点击“提取”时，程序主要在本机浏览器里读取页面 DOM，不一定调用 AI。

它会先找到可填写控件，例如：

- 文本框和 textarea
- 下拉框 select
- radio / checkbox
- ID 或 name 中包含 `AnSwEr` 的 Classviva 答案控件

然后根据控件 ID/name 推断题号和空位顺序，再围绕输入框向上查找题目容器。这样不同 Classviva 页面只要答案控件结构相近，通常都能自适应。

### 文本求解

点击“求解”时，程序会把提取到的题面、空位信息和统一答案规则发送给文本模型。每一次点击都会重新调用一次 API，模型不会记住上一次的提示词，所以规则会随请求一起发送。

### 视觉兜底

如果勾选了“视觉兜底”，提取时发现某题包含图片、图表、SVG、canvas，或文字质量偏低，就会调用视觉模型把截图里的题面补充成文字描述。

这一步的目的主要是补全题面，不是最终解题。

### 视觉求解

点击“视觉求解”时，程序会先重新读取当前页面结构，再截取当前页面截图发送给视觉模型。它不是只把前端显示的文本发给模型。

视觉求解请求大致包含：

- 当前页面截图
- 题号
- 每题空位数量
- 下拉框/选择题可用选项
- Classviva 答案填写规则

如果勾选了“视觉兜底”，前端“题目”区域可能会出现图片/图表的文字描述。这是给你检查题面用的；真正的视觉求解仍然看截图。

### 填入网页

点击“填入”不会调用 AI。程序只会把前端“答案”区域里你审核后的答案填入当前 Classviva 页面。

填入前会检查答案绑定的输入框是否还存在。如果你换到了下一页，旧输入框 ID 不存在，程序会按当前页面题号重新绑定，尽量避免“返回了答案但填入 0 个”的问题。

## 安装

建议使用 Python 3.10 或更高版本。

```powershell
cd path\to\classviva-local-assistant
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium              

（如果前端显示依赖ok，且使用edge，则最后一条命令改为python -m pip install -r requirements.txt -i   https://pypi.tuna.tsinghua.edu.cn/simple）
```

如果 `pip install ...` 报 launcher 错误，优先使用：

```powershell
python -m pip install -r requirements.txt
```

不要直接依赖系统里的 `pip.exe`，因为 Windows 上旧 Python 路径失效时容易报错。

## 启动前端

```powershell
python app.py
```

然后打开：

```text
http://127.0.0.1:8765
```

首次运行时，如果没有 `config.py`，程序会从 `config.example.py` 自动复制一份。`config.py` 只保存在本机，包含你的 API Key，不要提交到 GitHub。

前端设置区可以填写：

- 文本 API Key
- 文本 Base URL
- 文本模型
- 视觉 API Key
- 视觉 Base URL
- 视觉模型
- 默认 Classviva 作业链接

保存后会写入本机 `config.py`。密码框保存后会自动清空，前端只显示“key 已保存/未保存”。

## 基本使用

1. 运行 `python app.py`。
2. 打开 `http://127.0.0.1:8765`。
3. 在设置区填入模型配置并保存。
4. 在“作业链接”里填入 Classviva 作业或继续答题页面。
5. 点击“启动”，等待 Edge/Chromium 打开页面。
6. 如需登录，请在打开的浏览器窗口里手动完成登录。
7. 点击“提取”，检查题目和空位数量。
8. 点击“求解”或“视觉求解”。
9. 在“答案”区域人工检查、修改。
10. 确认无误后点击“填入”。

## 模型配置

本项目使用 OpenAI Python SDK，只要服务商兼容 Chat Completions 接口，通常都可以配置。

### DeepSeek 示例

```python
DEEPSEEK_API_KEY = "你的 key"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-v4-pro"
```

### OpenAI 示例

```python
VISION_API_KEY = "你的 key"
VISION_BASE_URL = "https://api.openai.com/v1"
VISION_MODEL = "gpt-5.5"
```

### DashScope / 千问示例

中国内地常用 OpenAI 兼容地址：

```text
https://dashscope.aliyuncs.com/compatible-mode/v1
```

国际站常用 OpenAI 兼容地址：

```text
https://dashscope-intl.aliyuncs.com/compatible-mode/v1
```

模型名区分大小写，并取决于账号地域、权限和免费额度。常见可尝试模型包括：

(主播这里推荐文本使用deepseek-v4-pro，视觉使用qwen3.7-plus，当然使用后者视觉求解时可能很慢，有钱的可以改成一些国外AI的快速版
不过deepseek多模态更新了我估计会立刻抛弃千问)

- 文本：`qwen-plus`、`qwen-max`、`qwen3.7-max`
- 视觉：`qwen3.7-plus`、`qwen3.5-plus`、`qwen-vl-max`

如果出现 `model_not_found`，优先检查模型名是否全小写、账号是否有权限、Base URL 是否对应正确地域。

官方参考：

- [DashScope OpenAI 兼容接口](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)
- [DashScope 模型列表](https://help.aliyun.com/zh/model-studio/models)
- [DashScope 视觉模型](https://help.aliyun.com/zh/model-studio/vision)

## 命令行模式

前端是推荐入口。项目仍保留命令行入口，方便调试：

```powershell
python main.py
```

指定链接：

```powershell
python main.py --url "https://..."
```

强制使用视觉截图求解：

```powershell
python main.py --vision
```

页面结构调试：

```powershell
python main.py --selectors
```

## 项目结构

```text
app.py              本地网页控制台后端
browser.py          Playwright 浏览器启动、截图、填入、当前页重绑定
extractor.py        自适应题目提取、MathJax/LaTeX 处理、质量评分
formatter.py        答案格式化和 Classviva 字符规范处理
main.py             命令行入口
prompts.py          文本/视觉共享提示词和答案填写规则
solver.py           文本模型求解
vision.py           视觉兜底和视觉求解
web/                前端页面
config.example.py   配置模板，不含真实 key
requirements.txt    Python 依赖
LICENSE             开源许可证
```

## 隐私和开源检查

不要提交这些内容：

- `config.py`
- `browser_profile/`
- `__pycache__/`
- `classviva_results_*.json`
- `classviva_r*.png`
- `page.png`
- `.env`
- 任何真实 API Key、Cookie、登录态、作业尝试链接、截图或答题记录

`.gitignore` 已默认忽略这些文件。发布前仍建议再检查一遍：

```powershell
rg -n "sk-|api_key|API_KEY|token|sesskey|password|attempt=" .
```

如果使用本项目运行过真实 Classviva 页面，`browser_profile/` 里可能包含登录状态。这个目录必须删除或排除。

## 常见问题

### `ModuleNotFoundError: No module named 'playwright'`

说明依赖没装到当前 Python。运行：

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
```

### `pip install` 报 launcher 错误

通常是 Windows 上旧 Python 路径残留。使用：

```powershell
python -m pip install -r requirements.txt
```

### 视觉求解时前端出现图片文字描述

这是正常现象。勾选“视觉兜底”时，程序会把图片/图表转写成文字并刷新到“题目”区域，方便你检查题面。视觉求解本身仍然会发送当前页面截图。

如果想尽量纯截图求解，可以取消勾选“视觉兜底”，再点“视觉求解”。

### 返回了答案但填入 0 个

通常是页面已经换页，旧答案绑定的是上一页输入框。当前版本会在填入前重新绑定当前页输入框。如果仍然出现，先点“提取”刷新当前页，再点“求解/视觉求解”和“填入”。

### 数学答案格式不被 Classviva 接受

Classviva 对格式比较严格。常见要求：

- `pi`，不要写 `π`
- `sqrt(x)`，不要写 `√x`
- `theta`，不要写 `θ`
- `a/b` 表示分数
- `x^2` 表示幂
- 不存在写 `DNE`

更多规则集中在 `prompts.py` 和 `formatter.py`。

## 免责声明

本项目是本地自动化和学习辅助工具。请遵守课程、平台、学校和相关网站的使用规则。模型生成内容可能错误，填入和提交前必须由使用者自行审核。
