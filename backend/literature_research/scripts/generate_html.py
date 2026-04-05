#!/usr/bin/env python3
"""
HTML 阅读版报告生成模块
- 蓝白渐变主题 (#003366 → #0066cc)
- 响应式布局，支持移动端
- 统计概览卡片
- 左右分栏摘要（英文 / 中文）
- 6维度分析卡片网格（3列布局）
- 纯 HTML+CSS，单文件即可查看
"""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


def _escape(text: str) -> str:
    """HTML 转义。"""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("\n", "<br>")
    )


def _dim_card(key: str, label: str, content: str, icon: str) -> str:
    content = content or "待分析"
    return f"""
      <div class="dim-card">
        <div class="dim-header">
          <span class="dim-icon">{icon}</span>
          <span class="dim-label">{label}</span>
        </div>
        <div class="dim-body">{_escape(content)}</div>
      </div>"""


def generate_html_report(
    papers: list[dict],
    output_path: str,
    topic_name: str,
    date_range: str,
    days: int = 0,
    topic_keyword: str = "",
) -> None:
    """
    生成 HTML 阅读版报告。

    Args:
        papers: 文献列表
        output_path: 输出文件路径
        topic_name: 主题中文名
        date_range: 时间范围字符串
        days: 检索天数
        topic_keyword: 检索关键词
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    total = len(papers)

    # 统计
    complete_count = sum(
        1 for p in papers
        if p.get("abstract") and p.get("abstract_cn") and p.get("technical_route")
    )
    completeness_pct = int(complete_count / total * 100) if total else 0

    # ── CSS ──────────────────────────────────────────────────────────────────
    css = """
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', Arial, sans-serif;
      background: #f0f4f8;
      color: #2c3e50;
      line-height: 1.7;
    }
    /* ── Header ── */
    .site-header {
      background: linear-gradient(135deg, #003366 0%, #0055aa 60%, #0066cc 100%);
      color: #fff;
      padding: 48px 40px 36px;
      text-align: center;
    }
    .site-header h1 { font-size: 2rem; font-weight: 700; margin-bottom: 8px; }
    .site-header .subtitle { font-size: 0.95rem; opacity: 0.85; }
    /* ── Stats ── */
    .stats-bar {
      display: flex;
      justify-content: center;
      flex-wrap: wrap;
      gap: 16px;
      padding: 24px 20px;
      background: #fff;
      border-bottom: 1px solid #e2e8f0;
    }
    .stat-card {
      text-align: center;
      padding: 14px 28px;
      border-radius: 12px;
      background: linear-gradient(135deg, #eef4ff, #dbeafe);
      min-width: 130px;
    }
    .stat-card .num {
      font-size: 1.8rem;
      font-weight: 700;
      color: #003366;
    }
    .stat-card .lbl { font-size: 0.8rem; color: #64748b; margin-top: 2px; }
    /* ── Container ── */
    .container { max-width: 1200px; margin: 0 auto; padding: 32px 20px; }
    /* ── Section ── */
    .section-title {
      font-size: 1.25rem;
      font-weight: 700;
      color: #003366;
      border-left: 4px solid #0066cc;
      padding-left: 12px;
      margin: 32px 0 16px;
    }
    /* ── Overview Table ── */
    .overview-table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
    .overview-table th {
      background: #003366;
      color: #fff;
      padding: 10px 12px;
      text-align: left;
    }
    .overview-table td { padding: 9px 12px; border-bottom: 1px solid #e2e8f0; }
    .overview-table tr:nth-child(even) td { background: #f7faff; }
    .overview-table tr:hover td { background: #eef4ff; }
    .overview-table a { color: #0066cc; text-decoration: none; }
    .overview-table a:hover { text-decoration: underline; }
    /* ── Paper Card ── */
    .paper-card {
      background: #fff;
      border-radius: 14px;
      box-shadow: 0 2px 12px rgba(0,51,102,0.08);
      margin-bottom: 32px;
      overflow: hidden;
    }
    .paper-card-header {
      background: linear-gradient(90deg, #003366, #005599);
      color: #fff;
      padding: 16px 20px;
    }
    .paper-card-header .paper-idx {
      font-size: 0.75rem;
      opacity: 0.8;
      margin-bottom: 4px;
    }
    .paper-card-header .paper-title { font-size: 1rem; font-weight: 600; }
    .paper-card-header .paper-title-cn { font-size: 0.88rem; opacity: 0.85; margin-top: 4px; }
    .paper-card-body { padding: 20px; }
    /* ── Info Table ── */
    .info-table { width: 100%; border-collapse: collapse; font-size: 0.87rem; margin-bottom: 16px; }
    .info-table td { padding: 6px 10px; border-bottom: 1px solid #e2e8f0; }
    .info-table td:first-child {
      font-weight: 600;
      color: #003366;
      width: 100px;
      background: #f0f6ff;
    }
    /* ── Abstract Columns ── */
    .abstract-cols {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      margin: 16px 0;
    }
    @media (max-width: 700px) {
      .abstract-cols { grid-template-columns: 1fr; }
    }
    .abstract-box {
      background: #f7faff;
      border: 1px solid #d6e4f7;
      border-radius: 10px;
      padding: 14px;
      font-size: 0.87rem;
    }
    .abstract-box .ab-label {
      font-weight: 700;
      color: #003366;
      margin-bottom: 8px;
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    /* ── Dimensions Grid ── */
    .dims-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
      margin-top: 16px;
    }
    @media (max-width: 900px) { .dims-grid { grid-template-columns: repeat(2, 1fr); } }
    @media (max-width: 580px) { .dims-grid { grid-template-columns: 1fr; } }
    .dim-card {
      border: 1px solid #d6e4f7;
      border-radius: 10px;
      overflow: hidden;
    }
    .dim-header {
      background: linear-gradient(90deg, #003366, #0055aa);
      color: #fff;
      padding: 8px 12px;
      font-size: 0.82rem;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .dim-icon { font-size: 1rem; }
    .dim-body {
      padding: 10px 12px;
      font-size: 0.84rem;
      background: #f7faff;
      min-height: 60px;
    }
    /* ── Footer ── */
    .site-footer {
      text-align: center;
      padding: 24px;
      font-size: 0.8rem;
      color: #94a3b8;
      border-top: 1px solid #e2e8f0;
      margin-top: 32px;
    }
    """

    # ── Stats bar ────────────────────────────────────────────────────────────
    stats_html = f"""
    <div class="stats-bar">
      <div class="stat-card"><div class="num">{total}</div><div class="lbl">文献总数</div></div>
      <div class="stat-card"><div class="num">{days or '—'}</div><div class="lbl">检索天数</div></div>
      <div class="stat-card"><div class="num">6</div><div class="lbl">分析维度</div></div>
      <div class="stat-card"><div class="num">{completeness_pct}%</div><div class="lbl">内容完整度</div></div>
    </div>"""

    # ── Overview table ────────────────────────────────────────────────────────
    overview_rows = ""
    for i, p in enumerate(papers, 1):
        title = _escape(p.get("title", "")[:70])
        title_cn = _escape(p.get("title_cn", "")[:50])
        journal = _escape(p.get("journal", ""))
        if_val = p.get("journal_if", "—")
        pub_date = p.get("publication_date", "—")
        doi = p.get("doi", "")
        doi_cell = f'<a href="https://doi.org/{doi}" target="_blank">{doi[:35]}</a>' if doi else "—"
        title_display = title + (f"<br><small style='color:#64748b'>{title_cn}</small>" if title_cn else "")
        overview_rows += f"""
        <tr>
          <td>{i}</td>
          <td>{title_display}</td>
          <td>{journal}<br><small>IF: {if_val}</small></td>
          <td>{pub_date}</td>
          <td style="font-size:0.78rem">{doi_cell}</td>
        </tr>"""

    overview_html = f"""
    <div class="section-title">文献概览</div>
    <div style="overflow-x:auto">
      <table class="overview-table">
        <thead>
          <tr>
            <th>#</th><th>标题</th><th>期刊 / IF</th><th>发表日期</th><th>DOI</th>
          </tr>
        </thead>
        <tbody>{overview_rows}</tbody>
      </table>
    </div>"""

    # ── Paper cards ───────────────────────────────────────────────────────────
    dim_defs = [
        ("technical_route", "技术路线", "🔬"),
        ("advantages", "技术优势", "✅"),
        ("limitations", "技术不足", "⚠️"),
        ("technical_barriers", "技术壁垒", "🔒"),
        ("feasibility", "落地可行性", "🏭"),
        ("generalization", "泛化能力", "🌐"),
    ]

    papers_html = '<div class="section-title">单篇文献详细分析</div>'
    for i, p in enumerate(papers, 1):
        title = _escape(p.get("title", ""))
        title_cn = _escape(p.get("title_cn", ""))
        abstract = _escape(p.get("abstract", "（无摘要）"))
        abstract_cn = _escape(p.get("abstract_cn", "（无翻译）"))
        journal = _escape(p.get("journal", ""))
        if_val = p.get("journal_if", "—")
        pub_date = p.get("publication_date", "—")
        author_display = _escape(p.get("author_display", ""))
        doi = p.get("doi", "")
        pmid = p.get("pmid", "")

        info_rows = f"""
          <tr><td>期刊</td><td>{journal}（IF: {if_val}）</td></tr>
          <tr><td>发表日期</td><td>{pub_date}</td></tr>
          <tr><td>作者</td><td>{author_display}</td></tr>
        """
        if doi:
            info_rows += f'<tr><td>DOI</td><td><a href="https://doi.org/{doi}" target="_blank">{doi}</a></td></tr>'
        if pmid:
            info_rows += f'<tr><td>PubMed</td><td><a href="https://pubmed.ncbi.nlm.nih.gov/{pmid}/" target="_blank">PMID: {pmid}</a></td></tr>'

        dim_cards = "".join(
            _dim_card(k, label, p.get(k, ""), icon)
            for k, label, icon in dim_defs
        )

        papers_html += f"""
    <div class="paper-card" id="paper-{i}">
      <div class="paper-card-header">
        <div class="paper-idx">文献 {i} / {total}</div>
        <div class="paper-title">{title}</div>
        {'<div class="paper-title-cn">' + title_cn + '</div>' if title_cn else ''}
      </div>
      <div class="paper-card-body">
        <table class="info-table"><tbody>{info_rows}</tbody></table>
        <div class="abstract-cols">
          <div class="abstract-box">
            <div class="ab-label">英文摘要</div>
            <div>{abstract}</div>
          </div>
          <div class="abstract-box">
            <div class="ab-label">中文翻译</div>
            <div>{abstract_cn}</div>
          </div>
        </div>
        <div style="font-weight:700;color:#003366;margin:16px 0 8px;font-size:0.92rem">深度分析（6维度）</div>
        <div class="dims-grid">{dim_cards}</div>
      </div>
    </div>"""

    # ── Full HTML ─────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{topic_name} 文献调研报告</title>
  <style>{css}</style>
</head>
<body>
  <header class="site-header">
    <h1>{topic_name} 文献调研报告</h1>
    <div class="subtitle">
      时间范围：{date_range} &nbsp;|&nbsp; 数据来源：PubMed
      {'&nbsp;|&nbsp; 关键词：' + _escape(topic_keyword) if topic_keyword else ''}
      &nbsp;|&nbsp; 生成时间：{now_str}
    </div>
  </header>

  {stats_html}

  <div class="container">
    {overview_html}
    {papers_html}
  </div>

  <footer class="site-footer">
    由 Literature Research Module 自动生成 &nbsp;|&nbsp; 数据来源：PubMed &amp; Europe PMC
  </footer>
</body>
</html>"""

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _main():
    parser = argparse.ArgumentParser(description="生成 HTML 阅读版报告")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--topic-name", default="未命名主题")
    parser.add_argument("--date-range", default="")
    parser.add_argument("--days", type=int, default=0)
    parser.add_argument("--topic-keyword", default="")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)
    papers = data if isinstance(data, list) else data.get("papers", [])

    generate_html_report(
        papers, args.output, args.topic_name,
        args.date_range, args.days, args.topic_keyword,
    )
    print(f"✅ HTML 阅读版报告已生成: {args.output}")


if __name__ == "__main__":
    _main()
