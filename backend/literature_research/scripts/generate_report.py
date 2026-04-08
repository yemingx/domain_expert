#!/usr/bin/env python3
"""
Markdown 报告生成模块 - 通用主题版本
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


def generate_markdown_report(
    papers: list[dict],
    topic_name: str,
    date_range: str,
    days: int,
    topic_keyword: str = "",
) -> str:
    """
    生成 Markdown 格式文献调研报告。

    Args:
        papers: 文献列表（已含翻译和6维度分析）
        topic_name: 主题中文名称
        date_range: 时间范围字符串，如 "2026-01-01 至 2026-04-04"
        days: 检索天数
        topic_keyword: PubMed 检索关键词

    Returns:
        Markdown 字符串
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []

    # ── 封面 ──────────────────────────────────────────────────────────────────
    lines += [
        f"# {topic_name}最新文献调研报告",
        "",
        f"**生成时间**: {now_str}",
        f"**时间范围**: {date_range}（近{days}天）",
        f"**数据来源**: PubMed",
        f"**检索关键词**: {topic_keyword or topic_name}",
        f"**文献数量**: {len(papers)} 篇",
        "",
        "---",
        "",
    ]

    # ── 目录 ──────────────────────────────────────────────────────────────────
    lines += [
        "## 目录",
        "",
        "1. [文献概览](#文献概览)",
        "2. [单篇文献详细分析](#单篇文献详细分析)",
        "3. [参考文献](#参考文献)",
        "",
        "---",
        "",
    ]

    # ── 文献概览表 ────────────────────────────────────────────────────────────
    lines += [
        "## 文献概览",
        "",
        f"本次共检索到 {len(papers)} 篇 {topic_name} 相关核心文献：",
        "",
        "| 序号 | 标题 | 期刊 | IF | 发表日期 | DOI |",
        "|------|------|------|----|----------|-----|",
    ]
    for i, p in enumerate(papers, 1):
        title = p.get("title", "")[:55] + ("..." if len(p.get("title", "")) > 55 else "")
        journal = p.get("journal", "")[:30]
        if_val = p.get("journal_if", "—")
        pub_date = p.get("publication_date", "—")
        doi = p.get("doi", "")
        doi_cell = f"[{doi[:30]}](https://doi.org/{doi})" if doi else "—"
        lines.append(f"| {i} | {title} | {journal} | {if_val} | {pub_date} | {doi_cell} |")
    lines += ["", "---", ""]

    # ── 单篇分析 ──────────────────────────────────────────────────────────────
    lines += ["## 单篇文献详细分析", ""]
    for i, p in enumerate(papers, 1):
        title = p.get("title", "")
        title_cn = p.get("title_cn", "")
        doi = p.get("doi", "")
        pmid = p.get("pmid", "")
        journal = p.get("journal", "")
        if_val = p.get("journal_if", "暂无数据")
        pub_date = p.get("publication_date", "—")
        author_display = p.get("author_display", "")
        abstract = p.get("abstract", "")
        abstract_cn = p.get("abstract_cn", "")

        lines += [
            f"### {i}. {title}",
            "",
        ]
        if title_cn:
            lines += [f"**中文标题**: {title_cn}", ""]

        lines += [
            "#### 基本信息",
            "",
            f"- **期刊**: {journal}（IF: {if_val}）",
            f"- **发表日期**: {pub_date}",
            f"- **作者**: {author_display}",
        ]
        if doi:
            lines += [
                f"- **DOI**: {doi}",
                f"- **原文链接**: [https://doi.org/{doi}](https://doi.org/{doi})",
            ]
        if pmid:
            lines.append(f"- **PubMed**: [https://pubmed.ncbi.nlm.nih.gov/{pmid}/](https://pubmed.ncbi.nlm.nih.gov/{pmid}/)")
        key_authors = p.get("key_authors") or []
        if key_authors:
            lines.append(f"- **核心作者**: {'; '.join(key_authors)}")
        mesh = p.get("mesh_keywords") or []
        if mesh:
            lines.append(f"- **MeSH关键词**: {'; '.join(mesh)}")
        lines.append("")

        # 摘要 — 始终写入两个 section，缺失时用占位符
        lines += ["#### 英文摘要", "", abstract or "（暂无摘要）", ""]
        lines += ["#### 中文翻译", "", abstract_cn or "（暂无翻译）", ""]

        # 6维度分析 — 始终写入 section，缺失字段用"待分析"占位
        dims = [
            ("technical_route", "技术路线"),
            ("advantages", "技术优势"),
            ("limitations", "技术不足"),
            ("technical_barriers", "技术壁垒"),
            ("feasibility", "落地可行性"),
            ("generalization", "泛化能力"),
        ]
        lines += ["#### 深度分析（6维度）", ""]
        for key, label in dims:
            content = p.get(key, "").strip() or "待分析"
            lines += [f"**{label}**: {content}", ""]

        lines += ["---", ""]

    # ── 参考文献 ──────────────────────────────────────────────────────────────
    lines += ["## 参考文献", ""]
    for i, p in enumerate(papers, 1):
        author = p.get("author_display", "")
        title = p.get("title", "")
        journal = p.get("journal", "")
        pub_date = p.get("publication_date", "")
        doi = p.get("doi", "")
        ref = f"[{i}] {author}. {title}. *{journal}*. {pub_date}."
        if doi:
            ref += f" DOI: [{doi}](https://doi.org/{doi})"
        lines.append(ref)
        lines.append("")

    return "\n".join(lines)


def save_markdown(content: str, output_path: str) -> None:
    """写入 Markdown 文件。"""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _main():
    parser = argparse.ArgumentParser(description="生成文献调研 Markdown 报告")
    parser.add_argument("--input", required=True, help="papers JSON 文件路径")
    parser.add_argument("--output", required=True, help="输出 Markdown 文件路径")
    parser.add_argument("--topic-name", default="未命名主题", help="主题中文名称")
    parser.add_argument("--topic-keyword", default="", help="检索关键词")
    parser.add_argument("--days", type=int, default=60, help="检索天数")
    parser.add_argument("--date-range", default="", help="时间范围字符串")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    papers = data if isinstance(data, list) else data.get("papers", [])
    date_range = args.date_range or f"最近{args.days}天"

    content = generate_markdown_report(
        papers, args.topic_name, date_range, args.days, args.topic_keyword
    )
    save_markdown(content, args.output)
    print(f"✅ Markdown 报告已生成: {args.output}")


if __name__ == "__main__":
    _main()
