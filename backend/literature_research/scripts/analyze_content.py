#!/usr/bin/env python3
"""
深度分析模块：对文献进行6维度技术分析
LLM 调用改为 Anthropic Python SDK，无需配置 API_KEY 或 BASE_URL。
"""
import re
import os
import json
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
                    print(f"[analyze_content] 从 settings.json 加载模型: {model}")
                    return model
        except Exception as e:
            print(f"[WARNING] 读取 settings.json 失败: {e}")

    # 优先级2: 环境变量
    env_model = os.environ.get("ANTHROPIC_MODEL")
    if env_model:
        print(f"[analyze_content] 从环境变量加载模型: {env_model}")
        return env_model

    # 默认模型
    default_model = "claude-sonnet-4-20250514"
    print(f"[analyze_content] 使用默认模型: {default_model}")
    return default_model


# Support ANTHROPIC_AUTH_TOKEN as fallback for ANTHROPIC_API_KEY
if not os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("ANTHROPIC_AUTH_TOKEN"):
    os.environ["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_AUTH_TOKEN"]

try:
    import anthropic as _anthropic
    _client = _anthropic.Anthropic()
    _SDK_OK = True
except Exception as _e:
    print(f"[WARNING] Anthropic SDK 初始化失败: {_e}")
    _client = None
    _SDK_OK = False

# 加载模型配置
_ANALYZE_MODEL = _load_model_from_settings()
print(f"[analyze_content] 分析模型: {_ANALYZE_MODEL}")


import time as _time

_LLM_MAX_RETRIES = 3
_LLM_RETRY_BACKOFF = (5, 10, 20)  # 秒


def _call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 4000) -> str:
    """调用 Anthropic SDK 进行分析，带指数退避重试（最多 3 次）。"""
    if not _SDK_OK or _client is None:
        print("[WARNING] SDK 不可用，跳过分析")
        return ""
    last_err = ""
    for attempt in range(_LLM_MAX_RETRIES):
        try:
            msg = _client.messages.create(
                model=_ANALYZE_MODEL,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            # 处理不同类型的 content blocks (TextBlock, ThinkingBlock, etc.)
            for block in msg.content:
                if hasattr(block, 'text') and block.text:
                    return block.text.strip()
                elif hasattr(block, 'thinking') and block.thinking:
                    # ThinkingBlock - 跳过，继续找 TextBlock
                    continue
            # 如果没有找到 text 属性，返回空字符串
            print(f"[WARNING] LLM 响应中没有找到文本内容")
            return ""
        except Exception as e:
            last_err = str(e)
            err_lower = last_err.lower()
            # 认证失败不重试
            if "authentication" in err_lower or "invalid x-api-key" in err_lower:
                print(f"[WARNING] LLM 认证失败，不重试: {e}")
                return ""
            if attempt == _LLM_MAX_RETRIES - 1:
                break
            wait = _LLM_RETRY_BACKOFF[attempt]
            print(f"[WARNING] LLM 分析调用失败 ({attempt+1}/{_LLM_MAX_RETRIES})，{wait}s 后重试: {e}")
            _time.sleep(wait)
    print(f"[WARNING] LLM 分析调用最终失败（已重试 {_LLM_MAX_RETRIES} 次）: {last_err}")
    return ""


def extract_corresponding_author(article_xml):
    """从PubMed XML中提取通讯作者信息"""
    try:
        authors = article_xml.findall(".//Author")
        for author in authors:
            affiliations = author.findall(".//Affiliation")
            for aff in affiliations:
                if aff.text and ("corresponding" in aff.text.lower() or "correspondence" in aff.text.lower()):
                    lastname = author.find("LastName")
                    firstname = author.find("ForeName")
                    if lastname is not None and lastname.text:
                        if firstname is not None and firstname.text:
                            return f"{firstname.text} {lastname.text}"
                        return lastname.text
        if authors:
            last_author = authors[-1]
            lastname = last_author.find("LastName")
            firstname = last_author.find("ForeName")
            if lastname is not None and lastname.text:
                if firstname is not None and firstname.text:
                    return f"{firstname.text} {lastname.text}"
                return lastname.text
        return "未明确标注"
    except Exception:
        return "提取失败"


_SYSTEM_PROMPT = """你是一位专业的生物医学领域技术分析师。请对学术论文进行深度技术分析。

必须严格按照以下6个维度分别输出，每个维度单独成段：

【技术路线】
分析核心原理、实验方法、检测流程

【技术优势】
分析性能指标、技术优点、创新点

【技术不足】
分析局限性、适用场景限制、潜在问题

【技术壁垒】
分析样本处理、算法、监管、专利等难点

【落地可行性】
分析临床阶段、成本、政策、市场前景

【泛化能力】
分析疾病谱扩展、人群适用性、迁移能力

要求：
1. 每个维度必须独立成段，用【维度名】作为标题
2. 内容简洁凝练，每段50-80字，突出重点
3. 不要出现markdown特殊符号
4. 6个维度都必须有内容，不能为空
5. 使用简洁的语言，避免冗长描述
6. 根据论文实际内容进行分析，不要局限于特定领域"""


def analyze_paper_content(title, abstract, journal):
    """对单篇文献进行深度分析（6维度）"""
    _empty = {k: "摘要缺失，无法分析" for k in
              ("technical_route", "advantages", "limitations",
               "technical_barriers", "feasibility", "generalization")}
    _failed = {k: "分析失败" for k in _empty}

    if not abstract or abstract == "无摘要":
        return _empty

    user_prompt = (
        f"论文标题：{title}\n"
        f"期刊：{journal}\n"
        f"摘要：{abstract}\n\n"
        "请按上述6个维度进行深度分析，确保每个维度都有具体内容。"
    )

    analysis_text = _call_llm(_SYSTEM_PROMPT, user_prompt)
    if not analysis_text:
        return _failed

    analysis = parse_analysis_dimensions(analysis_text)

    # 一次重试
    if not validate_analysis_complete(analysis):
        print("[WARNING] 分析不完整，重试...")
        retry_system = _SYSTEM_PROMPT + "\n\n重要：必须确保6个维度都有具体内容，不能省略任何维度。"
        analysis_text2 = _call_llm(retry_system, user_prompt)
        if analysis_text2:
            analysis = parse_analysis_dimensions(analysis_text2)

    return analysis


def parse_analysis_dimensions(text):
    """解析6维度分析结果"""
    text = text.replace('**', '').replace('*', '').replace('#', '').replace('`', '')

    analysis = {
        "technical_route": "",
        "advantages": "",
        "limitations": "",
        "technical_barriers": "",
        "feasibility": "",
        "generalization": "",
    }
    dimension_map = {
        "技术路线": "technical_route",
        "技术优势": "advantages",
        "技术不足": "limitations",
        "技术壁垒": "technical_barriers",
        "落地可行性": "feasibility",
        "泛化能力": "generalization",
    }

    pattern = r'【(.*?)】\s*\n?\s*(.*?)(?=【|$)'
    matches = re.findall(pattern, text, re.DOTALL)

    for dim_name, content in matches:
        dim_key = dimension_map.get(dim_name.strip())
        if dim_key and content.strip():
            content = ' '.join(content.strip().split())
            analysis[dim_key] = content

    # 按行解析备用
    if not any(analysis.values()):
        lines = text.split('\n')
        current_dim = None
        content_buffer = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            for cn_name, en_key in dimension_map.items():
                if cn_name in line and len(line) < 20:
                    if current_dim and content_buffer:
                        analysis[current_dim] = ' '.join(content_buffer)
                        content_buffer = []
                    current_dim = en_key
                    break
            else:
                if current_dim and len(line) > 10:
                    content_buffer.append(line)
        if current_dim and content_buffer:
            analysis[current_dim] = ' '.join(content_buffer)

    for key in analysis:
        if not analysis[key]:
            analysis[key] = "该维度分析内容待补充"

    return analysis


def validate_analysis_complete(analysis):
    """验证分析是否完整（6个维度都有实质内容）"""
    required = ["technical_route", "advantages", "limitations",
                "technical_barriers", "feasibility", "generalization"]
    for dim in required:
        content = analysis.get(dim, "")
        if not content or content in ("", "分析失败", "该维度分析内容待补充", "摘要缺失，无法分析"):
            return False
        if len(content) < 30:
            return False
    return True


def check_report_completeness(papers):
    """检查报告完整性，返回问题列表"""
    issues = []
    for i, paper in enumerate(papers, 1):
        if not paper.get("title") or paper.get("title") == "无标题":
            issues.append(f"文献{i}: 标题缺失")
        abstract = paper.get("abstract", "")
        if not abstract or abstract == "无摘要":
            issues.append(f"文献{i}: 摘要缺失")
        elif len(abstract) < 200:
            issues.append(f"文献{i}: 摘要过短（{len(abstract)}字符）")
        if not paper.get("abstract_cn"):
            issues.append(f"文献{i}: 中文翻译缺失")
        for field in ("technical_route", "advantages", "limitations",
                      "technical_barriers", "feasibility", "generalization"):
            content = paper.get(field, "")
            if not content or content in ("", "分析失败", "该维度分析内容待补充"):
                issues.append(f"文献{i}: {field} 分析不完整")
            elif len(content) < 30:
                issues.append(f"文献{i}: {field} 内容过短")
    return issues
