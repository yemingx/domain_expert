#!/usr/bin/env python3
"""
工具模块：大模型翻译、期刊IF查询、团队识别
LLM 调用改为 Anthropic Python SDK，无需配置 API_KEY 或 BASE_URL。
"""
import os
import json
import re

try:
    import anthropic as _anthropic
    _client = _anthropic.Anthropic()  # 自动从 keychain/env 读取认证
    _SDK_OK = True
except Exception as _e:
    print(f"[WARNING] Anthropic SDK 初始化失败: {_e}")
    _client = None
    _SDK_OK = False

# 翻译模型（快速/低成本）
_TRANSLATE_MODEL = "claude-haiku-4-5-20251001"
# 分析模型（高质量）
_ANALYZE_MODEL = "claude-sonnet-4-6"


def _call_llm(system_prompt: str, user_prompt: str,
              model: str = _ANALYZE_MODEL, max_tokens: int = 2000) -> str:
    """调用 Anthropic SDK，返回文本。失败返回空字符串。"""
    if not _SDK_OK or _client is None:
        print("[WARNING] SDK 不可用，跳过 LLM 调用")
        return ""
    try:
        msg = _client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        print(f"[WARNING] LLM 调用失败: {e}")
        return ""


# 加载2024JCR期刊IF数据库
JOURNAL_IF = {}
JOURNAL_IF_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'journal_if_2024.json')

try:
    if os.path.exists(JOURNAL_IF_FILE):
        with open(JOURNAL_IF_FILE, 'r', encoding='utf-8') as f:
            JOURNAL_IF = json.load(f)
        print(f"[OK] 已加载 {len(JOURNAL_IF)} 条期刊IF数据（2024JCR）")
    else:
        print(f"[WARNING] 期刊IF数据库文件不存在: {JOURNAL_IF_FILE}")
except Exception as e:
    print(f"[WARNING] 加载期刊IF数据库失败: {e}")

# 知名研究团队数据库
RESEARCH_TEAMS = {
    "lo y m": "卢煜明团队（香港中文大学）",
    "lu y m": "卢煜明团队（香港中文大学）",
    "yu ming lo": "卢煜明团队（香港中文大学）",
    "xie y": "谢夷明团队",
    "zhang x": "张学团队（中国医学科学院）",
    "wang h": "王俊团队（华大基因）",
    "yin y": "尹烨团队（华大基因）",
    "bgI": "华大研究院",
    "beijing genomics institute": "华大研究院",
    "huada": "华大研究院",
    "shanghai jiao tong": "上海交通大学医学院团队",
    "fudan university": "复旦大学团队",
    "tsinghua university": "清华大学团队",
    "peking university": "北京大学团队",
    "chinese academy of sciences": "中国科学院团队",
    "zhongshan hospital": "中山医院团队",
    "xiehe hospital": "协和医院团队",
    "xiangya hospital": "湘雅医院团队",
    "west china hospital": "华西医院团队"
}


def translate_text(text, type="title"):
    """调用 Claude (Haiku) 翻译文本（标题或摘要）。"""
    if not text or text in ("无标题", "无摘要"):
        return ""

    system_prompt = (
        "你是专业的医学翻译专家，擅长翻译产前诊断、遗传学、分子生物学领域的学术文献。\n"
        "翻译要求：\n"
        "1. 专业术语准确，符合国内医学行业规范\n"
        "2. 语句通顺流畅，符合中文表达习惯\n"
        "3. 标题翻译简洁明了，摘要翻译完整准确\n"
        "4. 对于结构化摘要（含 Background/Methods/Results/Conclusion 等章节），保留章节标题并逐段翻译\n"
        "5. 确保所有章节都被翻译，不要遗漏任何部分\n"
        "6. 只输出最终翻译结果，不要输出备选翻译、术语说明、关键词解释等额外内容"
    )

    if type == "title":
        user_prompt = f"请将以下学术论文标题翻译成中文，只输出翻译结果：\n{text}"
    else:
        user_prompt = (
            "请将以下学术论文摘要翻译成中文。"
            "如果是结构化摘要，请保留所有章节标题并逐段完整翻译，确保不遗漏任何章节：\n\n"
            + text
        )

    translated = _call_llm(system_prompt, user_prompt,
                           model=_TRANSLATE_MODEL, max_tokens=4000)
    if not translated:
        return ""

    # 移除多余注释
    for marker in ("术语说明", "术语解释", "关键词解释", "备选翻译"):
        if marker in translated:
            translated = translated.split(marker)[0].strip()

    return translated


def get_journal_if(journal_name):
    """获取期刊影响因子（基于2024JCR数据）。"""
    if not journal_name:
        return "暂无数据"

    journal_clean = journal_name.strip()
    journal_lower = journal_clean.lower()

    if journal_clean in JOURNAL_IF:
        return JOURNAL_IF[journal_clean]
    for journal, if_value in JOURNAL_IF.items():
        if journal.lower() == journal_lower:
            return if_value
    for journal, if_value in JOURNAL_IF.items():
        jl = journal.lower()
        if jl in journal_lower or journal_lower in jl:
            if len(jl) > 5 and len(journal_lower) > 5:
                return if_value
    return "暂无数据"


def identify_research_team(authors, affiliation_text=""):
    """识别论文所属研究团队。"""
    text = f"{authors} {affiliation_text}".lower()

    for team_key, team_name in RESEARCH_TEAMS.items():
        if team_key.lower() in text:
            return team_name

    if "china" in text or "chinese" in text:
        if "shanghai" in text:
            if "jiao tong" in text or "renji" in text or "xinhua" in text:
                return "上海交大系统团队"
            if "fudan" in text or "huashan" in text or "zhongshan" in text:
                return "复旦大学系统团队"
        if "beijing" in text:
            if "peking university" in text or "beida" in text:
                return "北京大学系统团队"
            if "tsinghua" in text:
                return "清华大学团队"
            if "chinese academy of sciences" in text or "cas" in text:
                return "中科院团队"
        if "guangzhou" in text or "guangdong" in text:
            if "sun yat-sen" in text or "zhongshan" in text:
                return "中山大学系统团队"
        if "hangzhou" in text or "zhejiang" in text:
            if "zhejiang university" in text:
                return "浙江大学团队"
            if "bgI" in text or "huada" in text:
                return "华大研究院杭州分院团队"
        if "wuhan" in text:
            if "wuhan university" in text or "tongji" in text or "xiehe" in text:
                return "武汉大学/华中科技大学团队"
        if "xian" in text or "shaanxi" in text:
            if "jiaotong" in text:
                return "西安交通大学团队"

    return "未识别到知名团队"


def extract_affiliation(article_xml):
    """从XML中提取单位信息。"""
    try:
        affiliations = article_xml.findall(".//Affiliation")
        if affiliations:
            return " ".join([aff.text for aff in affiliations if aff.text])
        return ""
    except Exception:
        return ""
