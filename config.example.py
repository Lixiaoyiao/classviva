"""classviva 本地助手 - 配置文件模板

复制为 config.py 并填入你的信息。config.py 包含密钥，不能提交到公开仓库。
"""

# 文本解题模型配置。兼容 OpenAI Chat Completions 的服务都可以填这里。
DEEPSEEK_API_KEY = "在此填入你的API Key"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-chat"

# 多模态视觉模型配置。用于图片题、图表题、公式/题面提取失败时兜底。
# 如果不用视觉兜底，可以留空 VISION_API_KEY。
VISION_API_KEY = ""
VISION_BASE_URL = "https://api.openai.com/v1"
VISION_MODEL = "gpt-4o-mini"

# classviva 作业页面 URL。可选，不填则每次手动输入。
CLASSVIVA_URL = ""

# 本地前端控制台。
WEB_HOST = "127.0.0.1"
WEB_PORT = 8765

# classviva 网页选择器。不同渲染版本可在这里补充选择器。
SELECTORS = {
    "answer_input": "input:not([type='hidden'])[id*='AnSwEr'], input:not([type='hidden'])[name*='AnSwEr'], textarea[id*='AnSwEr'], textarea[name*='AnSwEr'], select[id*='AnSwEr'], select[name*='AnSwEr']",
    "radio_input": "input[type='radio'][id*='AnSwEr'], input[type='radio'][name*='AnSwEr'], input[type='checkbox'][id*='AnSwEr'], input[type='checkbox'][name*='AnSwEr']",
    "question_block": "div.formulation, div.que, div[class*='que']",
    "question_text": ".qtext, .formulation",
    "submit_btn": "input[type='submit'], button[type='submit']",
    "next_btn": "input[name='next'], input[value*='下一页'], input[value*='next']",
    "answer_id_pattern": r"q(\d+):(\d+)_AnSwEr(\d+)",
}

TIMEOUT = 30000
EXTRACT_WAIT = 5000
WAIT_BETWEEN = 1.5
