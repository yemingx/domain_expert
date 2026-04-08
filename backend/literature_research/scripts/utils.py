#!/usr/bin/env python3
"""
工具模块：大模型翻译、期刊IF查询、团队识别
LLM 调用改为 Anthropic Python SDK，无需配置 API_KEY 或 BASE_URL。
"""
import os
import json
import re
from pathlib import Path


def _load_model_from_settings() -> str:
    """从 ~/.claude/settings.json 读取模型配置，如果没有则从环境读取。"""
    # 优先级1: ~/.claude/settings.json
    claude_settings_path = Path.home() / ".claude" / "settings.json"
    if claude_settings_path.exists():
        try:
            with open(claude_settings_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                env_vars = data.get("env", {})
                if "ANTHROPIC_MODEL" in env_vars:
                    model = env_vars["ANTHROPIC_MODEL"]
                    print(f"[OK] 从 settings.json 加载模型: {model}")
                    return model
        except Exception as e:
            print(f"[WARNING] 读取 settings.json 失败: {e}")

    # 优先级2: 环境变量
    env_model = os.environ.get("ANTHROPIC_MODEL")
    if env_model:
        print(f"[OK] 从环境变量加载模型: {env_model}")
        return env_model

    # 默认模型
    default_model = "claude-sonnet-4-20250514"
    print(f"[OK] 使用默认模型: {default_model}")
    return default_model


# Load env vars from ~/.claude/settings.json (ANTHROPIC_AUTH_TOKEN, ANTHROPIC_BASE_URL, etc.)
def _load_settings_env():
    p = Path.home() / ".claude" / "settings.json"
    if p.exists():
        try:
            data = json.load(open(p, encoding='utf-8'))
            for k, v in data.get("env", {}).items():
                if k not in os.environ:
                    os.environ[k] = v
        except Exception:
            pass

_load_settings_env()

# Support ANTHROPIC_AUTH_TOKEN as fallback for ANTHROPIC_API_KEY
if not os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("ANTHROPIC_AUTH_TOKEN"):
    os.environ["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_AUTH_TOKEN"]

try:
    import anthropic as _anthropic
    _kwargs: dict = {}
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        _kwargs["auth_token"] = os.environ["ANTHROPIC_AUTH_TOKEN"]
    elif os.environ.get("ANTHROPIC_API_KEY"):
        _kwargs["api_key"] = os.environ["ANTHROPIC_API_KEY"]
    if os.environ.get("ANTHROPIC_BASE_URL"):
        _kwargs["base_url"] = os.environ["ANTHROPIC_BASE_URL"]
    _client = _anthropic.Anthropic(**_kwargs)
    _SDK_OK = True
except Exception as _e:
    print(f"[WARNING] Anthropic SDK 初始化失败: {_e}")
    _client = None
    _SDK_OK = False

# 加载模型配置（翻译和分析使用相同模型，支持 DashScope 等代理）
_LLM_MODEL = _load_model_from_settings()

# 为保持兼容性，同时定义两个变量（使用相同值）
_TRANSLATE_MODEL = _LLM_MODEL
_ANALYZE_MODEL = _LLM_MODEL

print(f"[OK] LLM 模型配置: translate={_TRANSLATE_MODEL}, analyze={_ANALYZE_MODEL}")


import time as _time
import subprocess as _subprocess

_LLM_MAX_RETRIES = 3
_LLM_RETRY_BACKOFF = (5, 10, 20)  # 秒


def _call_llm(system_prompt: str, user_prompt: str,
              model: str = _ANALYZE_MODEL, max_tokens: int = 2000) -> str:
    """通过 claude CLI 调用 LLM（代理只允许 Claude Code CLI），带重试。"""
    prompt = f"[SYSTEM]\n{system_prompt}\n\n[USER]\n{user_prompt}"
    for attempt in range(_LLM_MAX_RETRIES):
        try:
            import platform as _platform
            _claude_cmd = "claude.cmd" if _platform.system() == "Windows" else "claude"
            proc = _subprocess.run(
                [_claude_cmd, "--print"],
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
            result = proc.stdout.strip()
            if result:
                return result
            if proc.stderr:
                print(f"[WARNING] claude CLI stderr: {proc.stderr[:200]}")
        except Exception as e:
            print(f"[WARNING] LLM 调用失败 ({attempt+1}/{_LLM_MAX_RETRIES}): {e}")
        if attempt < _LLM_MAX_RETRIES - 1:
            _time.sleep(_LLM_RETRY_BACKOFF[attempt])
    print(f"[WARNING] LLM 调用最终失败（已重试 {_LLM_MAX_RETRIES} 次）")
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


# LLM 期刊匹配缓存
_journal_llm_cache: dict[str, str] = {}


def _llm_match_journal_util(journal_name: str) -> str:
    """当精确/大小写匹配均失败时，用 LLM 从 IF 数据库中识别正确期刊。"""
    cache_key = journal_name.strip().lower()
    if cache_key in _journal_llm_cache:
        return _journal_llm_cache[cache_key]

    query_words = {w for w in cache_key.split() if len(w) > 2}
    if not query_words:
        _journal_llm_cache[cache_key] = "暂无数据"
        return "暂无数据"

    candidates: dict[str, str] = {}
    for k, v in JOURNAL_IF.items():
        k_words = {w for w in k.lower().split() if len(w) > 2}
        if query_words & k_words:
            candidates[k] = v

    if not candidates:
        _journal_llm_cache[cache_key] = "暂无数据"
        return "暂无数据"

    if len(candidates) > 50:
        refined = {}
        for k, v in candidates.items():
            k_words = {w for w in k.lower().split() if len(w) > 2}
            if len(query_words & k_words) >= 2:
                refined[k] = v
        if refined:
            candidates = refined

    candidate_list = "\n".join(
        f"- {k}" for k in list(candidates.keys())[:50]
    )

    system_prompt = "你是学术期刊名称匹配专家。"
    user_prompt = (
        f"请判断期刊「{journal_name}」对应候选列表中的哪本期刊。\n\n"
        f"候选期刊：\n{candidate_list}\n\n"
        "要求：\n"
        "- 如果找到匹配，只输出候选列表中对应的完整期刊名称（必须与列表中的完全一致）\n"
        '- 如果没有匹配，只输出「无」\n'
        "- 不要输出任何解释"
    )

    result = _call_llm(system_prompt, user_prompt, max_tokens=200)

    if result:
        matched = result.strip().strip("\"'")
        if matched and matched != "无":
            if matched in JOURNAL_IF:
                _journal_llm_cache[cache_key] = JOURNAL_IF[matched]
                return _journal_llm_cache[cache_key]
            for k, v in JOURNAL_IF.items():
                if k.lower() == matched.lower():
                    _journal_llm_cache[cache_key] = v
                    return _journal_llm_cache[cache_key]

    _journal_llm_cache[cache_key] = "暂无数据"
    return "暂无数据"


def get_journal_if(journal_name):
    """获取期刊影响因子（基于2024JCR数据）：精确 → 大小写 → LLM 三级匹配。"""
    if not journal_name:
        return "暂无数据"

    journal_clean = journal_name.strip()
    journal_lower = journal_clean.lower()

    # Level 1: 精确匹配
    if journal_clean in JOURNAL_IF:
        return JOURNAL_IF[journal_clean]
    # Level 2: 大小写不敏感
    for journal, if_value in JOURNAL_IF.items():
        if journal.lower() == journal_lower:
            return if_value
    # Level 3: LLM 智能匹配（替代原有的子串模糊匹配）
    return _llm_match_journal_util(journal_clean)


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
