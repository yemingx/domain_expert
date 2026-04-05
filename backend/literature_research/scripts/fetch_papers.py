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


def _get_journal_if(journal_name: str, if_data: dict) -> str:
    """查询期刊影响因子，支持精确/大小写/模糊三级匹配。"""
    if not journal_name:
        return "暂无数据"
    jl = journal_name.strip()
    jll = jl.lower()
    if jl in if_data:
        return str(if_data[jl])
    for k, v in if_data.items():
        if k.lower() == jll:
            return str(v)
    for k, v in if_data.items():
        kl = k.lower()
        if (kl in jll or jll in kl) and len(kl) > 5 and len(jll) > 5:
            return str(v)
    return "暂无数据"


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

    # 摘要（支持结构化多节）
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

    # 摘要回退：Europe PMC → 浏览器
    if not abstract_text and doi:
        abstract_text = (_get_abstract_from_europepmc(doi)
                         or _get_abstract_from_browser(doi)
                         or "")

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
