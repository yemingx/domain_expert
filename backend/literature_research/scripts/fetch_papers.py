#!/usr/bin/env python3
"""
科研文献检索模块 - 支持任意主题的 PubMed 文献检索
可作为库导入，也可直接从命令行运行
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

# ── 路径设置 ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
SKILL_ROOT = SCRIPT_DIR.parent
JOURNAL_IF_FILE = SKILL_ROOT / "data" / "journal_if_2024.json"

logger = logging.getLogger(__name__)

# ── PubMed API ────────────────────────────────────────────────────────────────
PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

# ── 摘要质量检查配置 ───────────────────────────────────────────────────────────
# 摘要最低字数要求（少于此字数视为不完整）
MIN_ABSTRACT_WORDS = 50
# 不完整句子指示词（以这些词结尾的摘要可能是被截断的）
INCOMPLETE_SENTENCE_INDICATORS = [
    "by", "is", "are", "was", "were", "been", "be", "being",
    "to", "for", "of", "in", "on", "at", "with", "from",
    "the", "a", "an", "and", "or",
    "as", "due to", "because of", "such as",
    "caused by", "mediated by", "associated with",
    "characterized by", "defined as", "known as",
    "通过", "由于", "基于", "作为",
]

# ── 默认配置 ──────────────────────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "topic": "NIPD",
    "topic_name": "无创产前诊断",
    "days": 60,
    "max_papers": 5,
}


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _load_journal_if() -> dict:
    """加载期刊影响因子数据库。"""
    if JOURNAL_IF_FILE.exists():
        with open(JOURNAL_IF_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    logger.warning("期刊IF数据库不存在: %s", JOURNAL_IF_FILE)
    return {}


# LLM 期刊匹配缓存（进程级），避免重复调用
_journal_llm_cache: dict[str, str] = {}


def _llm_match_journal(journal_name: str, if_data: dict) -> str:
    """当精确/大小写匹配均失败时，用 LLM 从 IF 数据库中识别正确期刊。"""
    cache_key = journal_name.strip().lower()
    if cache_key in _journal_llm_cache:
        return _journal_llm_cache[cache_key]

    # ── 预筛选候选期刊（按词重叠过滤，避免把 1w+ 条目全送给 LLM） ──
    query_words = {w for w in cache_key.split() if len(w) > 2}
    if not query_words:
        _journal_llm_cache[cache_key] = "暂无数据"
        return "暂无数据"

    candidates: dict[str, str] = {}
    for k, v in if_data.items():
        k_words = {w for w in k.lower().split() if len(w) > 2}
        if query_words & k_words:
            candidates[k] = v

    if not candidates:
        _journal_llm_cache[cache_key] = "暂无数据"
        return "暂无数据"

    # 候选太多时，要求至少 2 个词重叠
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

    try:
        from utils import _call_llm
    except ImportError:
        _journal_llm_cache[cache_key] = "暂无数据"
        return "暂无数据"

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
            # 精确验证
            if matched in if_data:
                _journal_llm_cache[cache_key] = str(if_data[matched])
                logger.info("LLM 匹配期刊: '%s' → '%s' (IF=%s)",
                            journal_name, matched, if_data[matched])
                return _journal_llm_cache[cache_key]
            # 大小写容错验证
            for k, v in if_data.items():
                if k.lower() == matched.lower():
                    _journal_llm_cache[cache_key] = str(v)
                    logger.info("LLM 匹配期刊: '%s' → '%s' (IF=%s)",
                                journal_name, k, v)
                    return _journal_llm_cache[cache_key]

    logger.info("LLM 未匹配到期刊: '%s'", journal_name)
    _journal_llm_cache[cache_key] = "暂无数据"
    return "暂无数据"


def _get_journal_if(journal_name: str, if_data: dict) -> str:
    """查询期刊影响因子：精确 → 大小写 → LLM 三级匹配。"""
    if not journal_name:
        return "暂无数据"
    jl = journal_name.strip()
    jll = jl.lower()
    # Level 1: 精确匹配
    if jl in if_data:
        return str(if_data[jl])
    # Level 2: 大小写不敏感
    for k, v in if_data.items():
        if k.lower() == jll:
            return str(v)
    # Level 3: LLM 智能匹配（替代原有的子串模糊匹配）
    return _llm_match_journal(jl, if_data)


def _is_abstract_complete(abstract: str) -> tuple[bool, str]:
    """检查摘要是否完整。

    Returns:
        (is_complete, reason): (是否完整, 不完整原因)
    """
    if not abstract or not abstract.strip():
        return False, "摘要为空"

    # 检查字数
    words = abstract.split()
    if len(words) < MIN_ABSTRACT_WORDS:
        return False, f"摘要字数不足 ({len(words)} < {MIN_ABSTRACT_WORDS})"

    # 检查是否以不完整指示词结尾
    abstract_clean = abstract.strip().lower()
    for indicator in INCOMPLETE_SENTENCE_INDICATORS:
        if abstract_clean.endswith(indicator.lower()):
            return False, f"摘要以不完整词结尾: '{indicator}'"

    # 检查是否有成对的括号但未闭合
    if abstract.count("(") != abstract.count(")"):
        return False, "括号未闭合"
    if abstract.count("[") != abstract.count("]"):
        return False, "方括号未闭合"

    # 检查是否以标点符号结尾（正常的句子应该如此）
    if not abstract_clean[-1] in ".!?。！？":
        return False, "摘要不以标点符号结尾"

    return True, ""


def _fetch_complete_abstract(article: ET.Element, doi: Optional[str]) -> tuple[str, list[str]]:
    """获取完整的摘要，尝试多个来源。

    Returns:
        (abstract, sources_tried): (摘要文本, 尝试过的来源列表)
    """
    sources_tried = []

    def _get_from_pubmed_xml() -> str:
        """从 PubMed XML 中提取摘要。"""
        abstract_text = ""
        abstract_elem = article.find(".//Abstract")
        if abstract_elem is not None:
            sections = []
            for te in abstract_elem.findall(".//AbstractText"):
                label = te.get("Label", "")
                content = te.text or ""
                if content.strip():
                    sections.append(f"{label}: {content}" if label else content)
            abstract_text = "\n\n".join(sections)
        return abstract_text

    # 1. 首先尝试 PubMed XML
    abstract = _get_from_pubmed_xml()
    sources_tried.append("PubMed XML")

    is_complete, reason = _is_abstract_complete(abstract)
    if is_complete:
        return abstract, sources_tried

    logger.warning("PubMed XML 摘要不完整 (%s)，尝试回退来源", reason)

    # 2. 尝试 Europe PMC
    if doi:
        abstract = _get_abstract_from_europepmc(doi)
        if abstract:
            sources_tried.append("Europe PMC")
            is_complete, reason = _is_abstract_complete(abstract)
            if is_complete:
                return abstract, sources_tried
            logger.warning("Europe PMC 摘要不完整 (%s)，继续尝试", reason)

        # 3. 尝试浏览器抓取
        abstract = _get_abstract_from_browser(doi)
        if abstract:
            sources_tried.append("Browser scrape")
            is_complete, reason = _is_abstract_complete(abstract)
            if is_complete:
                return abstract, sources_tried
            logger.warning("浏览器抓取摘要不完整 (%s)", reason)

    # 如果所有来源都失败，返回 PubMed XML 的原始结果（即使不完整）
    return _get_from_pubmed_xml(), sources_tried


def _get_abstract_from_europepmc(doi: str) -> Optional[str]:
    """通过 Europe PMC API 获取摘要（第一层回退）。"""
    if not doi:
        return None
    doi = doi.strip()
    if doi.startswith("http"):
        m = re.search(r"10\.\S+$", doi)
        doi = m.group(0) if m else None
        if not doi:
            return None
    try:
        url = (
            f"https://www.ebi.ac.uk/europepmc/webservices/rest/search"
            f"?query=DOI:{doi}&resulttype=core&format=json"
        )
        resp = requests.get(url, headers={"User-Agent": "Literature-Research-Tool/1.0"}, timeout=15)
        if resp.status_code == 200:
            results = resp.json().get("resultList", {}).get("result", [])
            if results:
                abstract = results[0].get("abstractText")
                if abstract:
                    return abstract.strip()
    except Exception as e:
        logger.warning("Europe PMC 获取失败: %s", e)
    return None


def _get_abstract_from_browser(doi: str) -> Optional[str]:
    """通过 Puppeteer 浏览器抓取出版社页面获取摘要（第二层回退）。"""
    if not doi:
        return None
    doi = doi.strip()
    if not doi.startswith("http"):
        doi = f"https://doi.org/{doi}"
    node_script = SCRIPT_DIR / "fetch_doi_abstract.js"
    if not node_script.exists():
        return None
    try:
        import platform
        node_exe = "C:\\Program Files\\nodejs\\node.exe" if platform.system() == "Windows" else "node"
        result = subprocess.run(
            [node_exe, str(node_script), doi],
            capture_output=True, text=True, timeout=40,
            encoding="utf-8", errors="replace",
        )
        out = result.stdout.strip()
        if out.startswith("ABSTRACT_FOUND:"):
            return out[len("ABSTRACT_FOUND:"):]
    except Exception as e:
        logger.warning("浏览器抓取失败: %s", e)
    return None


# ── 核心解析 ──────────────────────────────────────────────────────────────────

def _parse_article(article: ET.Element, if_data: dict) -> Optional[dict]:
    """将一个 PubmedArticle XML 元素解析为 paper 字典。

    注意：不在此处做文章类型或关键词过滤。
    PubMed esearch 已通过检索式过滤，本函数只做解析，避免二次过滤导致结果丢失。
    """
    # 标题
    title_elem = article.find(".//ArticleTitle")
    title = title_elem.text if title_elem is not None and title_elem.text else "No title"

    # DOI & PMID
    doi_elem = article.find(".//ArticleId[@IdType='doi']")
    doi = doi_elem.text if doi_elem is not None else None
    pmid_elem = article.find(".//PMID")
    pmid = pmid_elem.text if pmid_elem is not None else None

    # 摘要（尝试多个来源确保完整性）
    abstract_text, sources_tried = _fetch_complete_abstract(article, doi)
    if len(sources_tried) > 1:
        logger.info("摘要获取: 尝试了 %d 个来源 %s", len(sources_tried), sources_tried)

    # 期刊
    journal_elem = article.find(".//Journal/Title")
    journal = journal_elem.text if journal_elem is not None else "Unknown"

    # 发表日期
    pub_date_elem = article.find(".//PubDate")
    year = month = day = 0
    if pub_date_elem is not None:
        ye = pub_date_elem.find("Year")
        me = pub_date_elem.find("Month")
        de = pub_date_elem.find("Day")
        year = int(ye.text) if ye is not None and ye.text and ye.text.isdigit() else 0
        if me is not None and me.text:
            month_map = {
                "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
            }
            month = (int(me.text) if me.text.isdigit()
                     else month_map.get(me.text.lower()[:3], 0))
        day = int(de.text) if de is not None and de.text and de.text.isdigit() else 0

    # 作者
    authors_meta = []
    author_list = article.find(".//AuthorList")
    if author_list is not None:
        for i, au in enumerate(author_list.findall(".//Author")):
            ln = au.find("LastName")
            fn = au.find("ForeName")
            ini = au.find("Initials")
            if ln is None:
                continue
            last = ln.text or ""
            first = (fn.text if fn is not None else (ini.text if ini is not None else ""))
            full = f"{first} {last}".strip()
            aff_elem = au.find(".//Affiliation")
            email_elem = au.find(".//Email")
            authors_meta.append({
                "name": full,
                "affiliation": aff_elem.text if aff_elem is not None else "",
                "email": email_elem.text if email_elem is not None else "",
                "is_first_author": i == 0,
                "is_corresponding_author": email_elem is not None and bool(email_elem.text),
            })

    first_author = authors_meta[0]["name"] if authors_meta else ""
    corresp_authors = [a["name"] for a in authors_meta if a["is_corresponding_author"]]
    if not corresp_authors and len(authors_meta) > 1:
        corresp_authors = [authors_meta[-1]["name"]]

    n = len(authors_meta)
    key_idx = sorted(set([0, min(1, n - 1), max(0, n - 2), n - 1])) if n > 0 else []
    key_authors = [authors_meta[i]["name"] for i in key_idx]

    if not authors_meta:
        author_display = "Unknown"
    elif len(authors_meta) == 1:
        author_display = authors_meta[0]["name"]
    elif len(authors_meta) == 2:
        author_display = f"{authors_meta[0]['name']}, {authors_meta[1]['name']}"
    elif corresp_authors and corresp_authors[0] != first_author:
        author_display = f"{first_author} et al. (通讯: {corresp_authors[0]})"
    else:
        author_display = f"{first_author} et al."

    affiliations = list({a["affiliation"] for a in authors_meta if a["affiliation"]})

    mesh_terms = []
    for mh in article.findall(".//MeshHeading"):
        desc = mh.find("DescriptorName")
        if desc is not None and desc.get("MajorTopicYN") == "Y":
            mesh_terms.append(desc.text)

    return {
        "pmid": pmid,
        "doi": doi,
        "title": title,
        "title_cn": "",
        "abstract": abstract_text,
        "abstract_cn": "",
        "journal": journal,
        "journal_if": _get_journal_if(journal, if_data),
        "publication_date": f"{year}-{month:02d}-{day:02d}" if year else "",
        "year": year,
        "month": month,
        "authors_meta": authors_meta,
        "author_display": author_display,
        "first_author": first_author,
        "corresponding_authors": corresp_authors,
        "key_authors": key_authors,
        "mesh_keywords": mesh_terms,
        "research_team": affiliations[0][:120] if affiliations else "",
        "affiliations": affiliations,
        # 分析字段（由 analyze_content 填充）
        "technical_route": "",
        "advantages": "",
        "limitations": "",
        "technical_barriers": "",
        "feasibility": "",
        "generalization": "",
    }


# ── 查询辅助 ──────────────────────────────────────────────────────────────────

def _has_pub_type_filter(query: str) -> bool:
    """检测检索式中是否已包含文章类型过滤（兼容 [pt] 和 [Publication Type] 两种格式）。"""
    q = query.lower()
    return any(x in q for x in ["[pt]", "[publication type]", "journal article", "article[pt]"])


def _has_date_filter(query: str) -> bool:
    """检测检索式中是否已包含日期过滤。"""
    return any(x in query for x in ["[Date - Entry]", "[EDat]", "[Date]", "[pdat]"])


def _safe_wrap_query(query: str, extra: str) -> str:
    """在保留顶层 NOT 运算符语义的前提下追加 AND 条件。"""
    inside_quote = False
    last_not_pos = -1
    i = 0
    while i < len(query):
        c = query[i]
        if c == '"':
            inside_quote = not inside_quote
        elif not inside_quote and query[i : i + 5].upper() == " NOT ":
            last_not_pos = i
        i += 1
    if last_not_pos > 0:
        positive_part = query[:last_not_pos].strip()
        negative_part = query[last_not_pos + 5 :].strip()
        return f"({positive_part}) AND ({extra}) NOT {negative_part}"
    else:
        return f"({query}) AND ({extra})"


# ── 公开 API ──────────────────────────────────────────────────────────────────

def fetch_papers(
    topic: str,
    query: str,
    days: int = 60,
    max_papers: int = 10,
    proxies: Optional[dict] = None,
) -> list[dict]:
    """
    检索 PubMed 并返回文献列表（不含 LLM 分析）。

    Args:
        topic: 主题关键词（仅用于日志/显示）
        query: NCBI 检索式
        days: 限定最近 N 天（若 query 中已含日期则忽略）
        max_papers: 最多返回篇数
        proxies: requests 代理字典

    Returns:
        paper 字典列表
    """
    logger.info("PubMed 检索: topic=%s, days=%d, max=%d", topic, days, max_papers)

    # 自动添加日期过滤（若未包含）
    if not _has_date_filter(query):
        query = _safe_wrap_query(query, f'"last {days} days"[EDat]')

    # 添加文章类型过滤（若未包含）
    if not _has_pub_type_filter(query):
        query = _safe_wrap_query(query, "Journal Article[pt] OR Article[pt]")

    # Step 1: 搜索 ID 列表
    search_params = {
        "db": "pubmed",
        "term": query,
        "retmax": max_papers,
        "retmode": "json",
        "sort": "pub_date",
    }
    try:
        resp = requests.get(
            PUBMED_BASE + "esearch.fcgi",
            params=search_params,
            proxies=proxies,
            timeout=30,
        )
        search_data = resp.json()
        id_list = search_data.get("esearchresult", {}).get("idlist", [])
        total = search_data.get("esearchresult", {}).get("count", "0")
        logger.info("检索到 %s 篇，获取前 %d 篇", total, min(len(id_list), max_papers))
    except Exception as e:
        logger.error("PubMed 搜索失败: %s", e)
        return []

    if not id_list:
        return []

    id_list = id_list[:max_papers]
    if_data = _load_journal_if()
    papers = []
    BATCH = 50

    # Step 2: 分批获取详情
    for i in range(0, len(id_list), BATCH):
        batch = id_list[i : i + BATCH]
        batch_num = i // BATCH + 1
        total_batches = (len(id_list) + BATCH - 1) // BATCH
        logger.info("获取第 %d/%d 批 (%d 篇)", batch_num, total_batches, len(batch))
        try:
            resp = requests.get(
                PUBMED_BASE + "efetch.fcgi",
                params={"db": "pubmed", "id": ",".join(batch), "retmode": "xml", "rettype": "abstract"},
                proxies=proxies,
                timeout=60,
            )
            content = resp.content
            content = re.sub(rb"<\?xml[^?]*\?>", b"", content)
            content = re.sub(rb"<!DOCTYPE[^>]*>", b"", content)
            root = ET.fromstring(b"<PubmedArticleSet>" + content + b"</PubmedArticleSet>")
            batch_articles = root.findall(".//PubmedArticle")
            batch_parsed = 0
            for art in batch_articles:
                paper = _parse_article(art, if_data)
                if paper:
                    papers.append(paper)
                    batch_parsed += 1
            if batch_parsed < len(batch_articles):
                logger.warning(
                    "批次 %d: efetch 返回 %d 篇，解析成功 %d 篇，丢弃 %d 篇",
                    batch_num, len(batch_articles), batch_parsed,
                    len(batch_articles) - batch_parsed,
                )
            else:
                logger.info("批次 %d: 全部 %d 篇解析成功", batch_num, batch_parsed)
        except Exception as e:
            logger.error("批次 %d 获取失败 (丢失 %d 篇): %s", batch_num, len(batch), e)

    logger.info("PubMed 返回 %d 个 ID，最终解析 %d 篇文献", len(id_list), len(papers))
    return papers


def build_query(topic: str, days: int, custom_query: Optional[str] = None) -> str:
    """根据 topic 构建 PubMed 检索式（不含日期过滤，由 fetch_papers 添加）。"""
    if custom_query:
        return custom_query
    return f"({topic}[Title/Abstract])"


# ── CLI 入口 ──────────────────────────────────────────────────────────────────

def _main():
    sys.path.insert(0, str(SCRIPT_DIR))
    from utils import translate_text, identify_research_team
    from analyze_content import analyze_paper_content, validate_analysis_complete

    parser = argparse.ArgumentParser(description="科研文献调研工具 - 仅检索和分析")
    parser.add_argument("--topic", required=True, help="PubMed 检索关键词")
    parser.add_argument("--topic-name", default=None, help="主题中文名称")
    parser.add_argument("--days", type=int, default=60, help="检索最近 N 天")
    parser.add_argument("--max-papers", type=int, default=5, help="最大文献数量")
    parser.add_argument("--query", default=None, help="自定义 NCBI 检索式")
    parser.add_argument("--output", default=None, help="输出 JSON 文件路径")
    parser.add_argument("--no-analysis", action="store_true", help="跳过 LLM 分析")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    topic_name = args.topic_name or args.topic
    query = build_query(args.topic, args.days, args.query)

    print(f"{'='*60}")
    print(f"📚 科研文献调研工具")
    print(f"{'='*60}")
    print(f"主题: {topic_name} ({args.topic})")
    print(f"时间范围: 最近 {args.days} 天")
    print(f"{'='*60}")

    papers = fetch_papers(args.topic, query, args.days, args.max_papers)

    if not args.no_analysis:
        for i, paper in enumerate(papers, 1):
            print(f"\n📄 分析文献 {i}/{len(papers)}: {paper['title'][:60]}...")

            # 翻译
            if paper["title"]:
                print("  🔤 翻译标题...")
                paper["title_cn"] = translate_text(paper["title"], type="title")
            if paper["abstract"]:
                print("  🔤 翻译摘要...")
                paper["abstract_cn"] = translate_text(paper["abstract"], type="abstract")

            # 研究团队识别
            paper["research_team"] = identify_research_team(
                paper["author_display"], " ".join(paper["affiliations"])
            )

            # 6维度分析
            print("  🧠 深度分析...")
            analysis = analyze_paper_content(paper["title"], paper["abstract"], paper["journal"])
            if not validate_analysis_complete(analysis):
                import time; time.sleep(3)
                analysis = analyze_paper_content(paper["title"], paper["abstract"], paper["journal"])
            paper.update(analysis)

    result = {
        "topic": args.topic,
        "topic_name": topic_name,
        "query": query,
        "days": args.days,
        "total_papers": len(papers),
        "papers": papers,
        "run_at": datetime.now().isoformat(),
    }

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n✅ 结果已保存: {args.output}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
