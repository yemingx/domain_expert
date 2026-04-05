"""
Literature Research 模块 - 主入口
支持 FastAPI 直接调用，也可作为 CLI 完整流水线运行。

公开 API：
  - run_research(topic, query, max_papers)  -> dict  （仅 PubMed 检索，不含 LLM）
  - run_full_pipeline(...)                  -> dict  （完整流水线：检索+分析+报告）
"""

import argparse
import json
import logging
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# 把 scripts/ 目录加入导入路径
SCRIPT_DIR = Path(__file__).parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────────
JOURNAL_IF_PATH = Path(__file__).parent / "data" / "journal_if_2024.json"
RESULT_DIR = Path(__file__).parent / "result"


# ── 内部工具 ──────────────────────────────────────────────────────────────────

def _get_proxies() -> Optional[dict]:
    http = os.getenv("HTTP_PROXY", "")
    https = os.getenv("HTTPS_PROXY", "")
    proxies = {}
    if http:
        proxies["http"] = http
    if https:
        proxies["https"] = https
    return proxies or None


def _build_output_dir(topic_name: str, date_str: str) -> Path:
    folder = RESULT_DIR / f"{topic_name}文献调研" / date_str
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# ── 公开 API ──────────────────────────────────────────────────────────────────

def run_research(
    topic: str,
    query: str,
    max_papers: int = 50,
) -> dict:
    """
    仅执行 PubMed 检索，返回原始文献数据（无 LLM 分析）。
    适合 FastAPI 快速响应场景。

    Args:
        topic: 主题关键词
        query: NCBI 检索式
        max_papers: 最大篇数

    Returns:
        {topic, query, total_papers, papers, year_range, unique_institutions, run_at}
    """
    from fetch_papers import fetch_papers, _load_journal_if

    logger.info("run_research: topic=%s, max=%d", topic, max_papers)

    papers = fetch_papers(
        topic=topic,
        query=query,
        days=365,          # 宽松默认值，由 query 中的日期过滤控制
        max_papers=max_papers,
        proxies=_get_proxies(),
    )

    years = [p["year"] for p in papers if p.get("year")]
    institutions: set = set()
    for p in papers:
        institutions.update(p.get("affiliations", []))

    return {
        "topic": topic,
        "query": query,
        "total_papers": len(papers),
        "papers": papers,
        "year_range": {
            "min": min(years) if years else None,
            "max": max(years) if years else None,
        },
        "unique_institutions": len(institutions),
        "run_at": datetime.now().isoformat(),
    }


def run_full_pipeline(
    topic: str,
    topic_name: str,
    days: int = 60,
    max_papers: int = 5,
    custom_query: Optional[str] = None,
    output_dir: Optional[str] = None,
    generate_word: bool = True,
    generate_html: bool = True,
    generate_html_ppt: bool = True,
    convert_pdf: bool = True,
    download_pdfs: bool = True,
    pdf_delay: float = 1.5,
    auto_fix: bool = True,
) -> dict:
    """
    完整文献调研流水线：检索 → 翻译 → 深度分析 → 多格式报告生成。

    Args:
        topic: PubMed 检索关键词
        topic_name: 主题中文名称
        days: 检索最近 N 天
        max_papers: 最大文献数量
        custom_query: 自定义 NCBI 检索式（覆盖 topic 关键词）
        output_dir: 指定输出目录（默认 result/{topic_name}文献调研/YYYY-MM-DD/）
        generate_word: 是否生成 Word 报告
        generate_html: 是否生成 HTML 阅读版
        generate_html_ppt: 是否生成 HTML-PPT 版
        convert_pdf: 是否将 HTML-PPT 转换为 PDF（需要 Node.js + Puppeteer）
        auto_fix: 是否自动修复不完整内容

    Returns:
        {
            topic, topic_name, papers, output_dir,
            files: {markdown, word, html, html_ppt, pdf},
            stats: {...}
        }
    """
    from fetch_papers import fetch_papers, build_query
    from utils import translate_text, identify_research_team
    from analyze_content import analyze_paper_content, validate_analysis_complete, check_report_completeness
    from generate_report import generate_markdown_report, save_markdown
    from generate_html import generate_html_report
    from generate_html_ppt import generate_ppt_html_report

    logger.info("=== 开始完整文献调研流水线 ===")
    logger.info("主题: %s (%s), 天数: %d, 最多: %d 篇", topic_name, topic, days, max_papers)

    # ── 时间范围 ──────────────────────────────────────────────────────────────
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    date_str = end_date.strftime("%Y-%m-%d")
    date_range = f"{start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}"

    # ── 输出目录 ──────────────────────────────────────────────────────────────
    if output_dir:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = _build_output_dir(topic_name, date_str)
    logger.info("输出目录: %s", out_dir)

    # ── Step 1: PubMed 检索 ───────────────────────────────────────────────────
    query = custom_query or build_query(topic, days)
    papers = fetch_papers(
        topic=topic,
        query=query,
        days=days,
        max_papers=max_papers,
        proxies=_get_proxies(),
    )

    if not papers:
        logger.warning("未找到相关文献")
        return {
            "topic": topic, "topic_name": topic_name,
            "papers": [], "output_dir": str(out_dir),
            "files": {}, "stats": {"total": 0},
        }

    # ── Step 2: LLM 分析（翻译 + 6维度深度分析）──────────────────────────────
    for i, paper in enumerate(papers, 1):
        logger.info("[%d/%d] 分析: %s", i, len(papers), paper["title"][:60])

        # 翻译标题
        if paper.get("title"):
            paper["title_cn"] = translate_text(paper["title"], type="title")

        # 翻译摘要
        if paper.get("abstract"):
            paper["abstract_cn"] = translate_text(paper["abstract"], type="abstract")

        # 研究团队识别
        paper["research_team"] = identify_research_team(
            paper.get("author_display", ""),
            " ".join(paper.get("affiliations", [])),
        )

        # 6维度深度分析
        analysis = analyze_paper_content(
            paper["title"], paper.get("abstract", ""), paper.get("journal", "")
        )
        if not validate_analysis_complete(analysis):
            logger.warning("分析不完整，等待重试...")
            time.sleep(3)
            analysis = analyze_paper_content(
                paper["title"], paper.get("abstract", ""), paper.get("journal", "")
            )
        paper.update(analysis)

    # ── 完整性检查 ────────────────────────────────────────────────────────────
    issues = check_report_completeness(papers)
    if issues:
        logger.warning("发现 %d 个完整性问题", len(issues))
        for issue in issues[:10]:
            logger.warning("  - %s", issue)
    else:
        logger.info("所有文献内容完整")

    # ── 保存原始数据 JSON ──────────────────────────────────────────────────────
    json_path = out_dir / "papers_complete.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "topic": topic, "topic_name": topic_name,
            "query": query, "days": days,
            "date_range": date_range,
            "total_papers": len(papers),
            "papers": papers,
            "run_at": datetime.now().isoformat(),
        }, f, ensure_ascii=False, indent=2)
    logger.info("JSON 数据已保存: %s", json_path)

    files: dict[str, str] = {"json": str(json_path)}
    fname_base = f"{topic_name}最新文献报告_{start_date.strftime('%Y-%m-%d')}至{end_date.strftime('%Y-%m-%d')}"
    html_base = f"{topic_name}文献调研报告_{start_date.strftime('%Y-%m-%d')}至{end_date.strftime('%Y-%m-%d')}"

    # ── Step 3: Markdown 报告 ─────────────────────────────────────────────────
    md_path = out_dir / f"{fname_base}.md"
    content = generate_markdown_report(papers, topic_name, date_range, days, topic)
    save_markdown(content, str(md_path))
    files["markdown"] = str(md_path)
    logger.info("Markdown 报告已生成: %s", md_path)

    # ── Step 4: Word 报告 ─────────────────────────────────────────────────────
    if generate_word:
        try:
            from generate_word import create_word_report
            word_path = out_dir / f"{fname_base}.docx"
            success, msg = create_word_report(
                papers, str(word_path), topic_name, date_range, auto_fix=auto_fix
            )
            if success:
                files["word"] = str(word_path)
                logger.info("Word 报告已生成: %s", word_path)
            else:
                logger.warning("Word 报告生成失败: %s", msg)
        except Exception as e:
            logger.warning("Word 报告生成异常: %s", e)

    # ── Step 5: HTML 阅读版 ───────────────────────────────────────────────────
    if generate_html:
        try:
            html_path = out_dir / f"{html_base}.html"
            generate_html_report(papers, str(html_path), topic_name, date_range, days, topic)
            files["html"] = str(html_path)
            logger.info("HTML 阅读版已生成: %s", html_path)
        except Exception as e:
            logger.warning("HTML 报告生成异常: %s", e)

    # ── Step 5b: PDF 全文下载 ─────────────────────────────────────────────────
    if download_pdfs:
        try:
            from download_pdfs import download_papers_pdf, attach_pdf_paths_to_papers
            pdf_dir = str(out_dir / "pdfs")
            logger.info("开始下载开放获取 PDF → %s", pdf_dir)
            dl_results = download_papers_pdf(papers, pdf_dir, delay=pdf_delay)
            papers = attach_pdf_paths_to_papers(papers, dl_results)
            success_count = sum(1 for r in dl_results if r["status"] == "success")
            logger.info("PDF 下载完成: %d/%d 篇成功", success_count, len(dl_results))
            files["pdf_downloads"] = {
                "dir": pdf_dir,
                "total": len(dl_results),
                "success": success_count,
                "results": dl_results,
            }
            # 重新保存 JSON（含 pdf_path 字段）
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump({
                    "topic": topic, "topic_name": topic_name,
                    "query": query, "days": days,
                    "date_range": date_range,
                    "total_papers": len(papers),
                    "papers": papers,
                    "run_at": datetime.now().isoformat(),
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("PDF 下载异常: %s", e)

    # ── Step 6: HTML-PPT 版 ───────────────────────────────────────────────────
    if generate_html_ppt:
        try:
            html_ppt_path = out_dir / f"{html_base}_ppt.html"
            generate_ppt_html_report(papers, str(html_ppt_path), topic_name, date_range, days, topic)
            files["html_ppt"] = str(html_ppt_path)
            logger.info("HTML-PPT 版已生成: %s", html_ppt_path)

            # ── Step 7: HTML-PPT → PDF ────────────────────────────────────────
            if convert_pdf:
                pdf_path = out_dir / f"{html_base}_ppt.pdf"
                node_script = SCRIPT_DIR / "html_to_pdf.js"
                if node_script.exists():
                    node_exe = "C:\\Program Files\\nodejs\\node.exe" if platform.system() == "Windows" else "node"
                    result = subprocess.run(
                        [node_exe, str(node_script), str(html_ppt_path), str(pdf_path)],
                        capture_output=True, text=True, timeout=300,
                    )
                    if result.returncode == 0:
                        files["pdf"] = str(pdf_path)
                        logger.info("PDF 已生成: %s", pdf_path)
                    else:
                        logger.warning("PDF 转换失败: %s", result.stderr[:200])
                else:
                    logger.info("html_to_pdf.js 不存在，跳过 PDF 转换")
        except Exception as e:
            logger.warning("HTML-PPT/PDF 生成异常: %s", e)

    # ── 返回结果 ──────────────────────────────────────────────────────────────
    years = [p["year"] for p in papers if p.get("year")]
    return {
        "topic": topic,
        "topic_name": topic_name,
        "total_papers": len(papers),
        "papers": papers,
        "output_dir": str(out_dir),
        "files": files,
        "stats": {
            "total": len(papers),
            "date_range": date_range,
            "year_range": {
                "min": min(years) if years else None,
                "max": max(years) if years else None,
            },
            "completeness_issues": len(issues),
        },
        "run_at": datetime.now().isoformat(),
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="科研文献调研完整流水线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 基础用法
  python research.py --topic "CRISPR" --topic-name "基因编辑" --days 30

  # 指定最大文献数，自定义检索式
  python research.py --topic "Organoid" --topic-name "类器官" --days 90 --max-papers 5

  # 仅检索，不生成报告
  python research.py --topic "AI Medicine" --topic-name "AI医学" --search-only
        """,
    )
    parser.add_argument("--topic", required=True, help="PubMed 检索关键词")
    parser.add_argument("--topic-name", default=None, help="主题中文名称")
    parser.add_argument("--days", type=int, default=60, help="检索最近 N 天（默认60）")
    parser.add_argument("--max-papers", type=int, default=5, help="最大文献数量（默认5）")
    parser.add_argument("--query", default=None, help="自定义 NCBI 检索式")
    parser.add_argument("--output", default=None, help="指定输出目录")
    parser.add_argument("--search-only", action="store_true", help="仅检索，不做 LLM 分析和报告生成")
    parser.add_argument("--no-word", action="store_true", help="不生成 Word 报告")
    parser.add_argument("--no-html", action="store_true", help="不生成 HTML 报告")
    parser.add_argument("--no-pdf", action="store_true", help="不转换 PDF")
    parser.add_argument("--no-fix", action="store_true", help="不自动修复不完整内容")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    topic_name = args.topic_name or args.topic

    if args.search_only:
        from fetch_papers import fetch_papers, build_query
        query = build_query(args.topic, args.days, args.query)
        papers = fetch_papers(args.topic, query, args.days, args.max_papers)
        print(json.dumps({
            "topic": args.topic, "topic_name": topic_name,
            "total": len(papers), "papers": papers,
        }, ensure_ascii=False, indent=2))
    else:
        result = run_full_pipeline(
            topic=args.topic,
            topic_name=topic_name,
            days=args.days,
            max_papers=args.max_papers,
            custom_query=args.query,
            output_dir=args.output,
            generate_word=not args.no_word,
            generate_html=not args.no_html,
            generate_html_ppt=not args.no_html,
            convert_pdf=not args.no_pdf,
            auto_fix=not args.no_fix,
        )

        print("\n" + "=" * 60)
        print(f"✅ 任务完成！文献总数: {result['stats']['total']}")
        print(f"📂 输出目录: {result['output_dir']}")
        for fmt, path in result.get("files", {}).items():
            print(f"  [{fmt.upper()}] {Path(path).name}")
        print("=" * 60)
