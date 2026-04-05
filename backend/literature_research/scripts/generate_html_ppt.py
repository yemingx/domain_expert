#!/usr/bin/env python3
"""
HTML-PPT 版报告生成模块
- 16:9 宽屏比例（1280px × 720px per slide）
- 蓝紫渐变主题 (#003366 → #0066cc → #764ba2)
- 无动画效果，静态展示
- 完整内容显示，无省略号
- 页面结构：封面 → 概览 → 文献（每篇2幻灯片）→ 总结 → 结束
"""

import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_DIM_DEFS = [
    ("technical_route", "技术路线"),
    ("advantages", "技术优势"),
    ("limitations", "技术不足"),
    ("technical_barriers", "技术壁垒"),
    ("feasibility", "落地可行性"),
    ("generalization", "泛化能力"),
]


def validate_papers_for_ppt(papers: list[dict]) -> dict:
    """
    审查论文数据完整性（Layer A：数据级审查）。

    检查每篇论文是否具备 HTML PPT 所需的关键字段：
    - abstract（英文摘要）
    - abstract_cn（中文翻译）
    - 6 个深度分析维度

    Returns:
        {
            "total_papers": int,
            "issues_count": int,
            "issues": list[str],   # 每条描述一个缺失字段
            "ok": bool,            # True 表示无缺失
        }
    """
    issues: list[str] = []
    for i, p in enumerate(papers, 1):
        label = f"Paper {i} [{(p.get('title') or '')[:50]}]"
        if not (p.get("abstract") or "").strip():
            issues.append(f"{label}: 英文摘要 (abstract) 为空")
        if not (p.get("abstract_cn") or "").strip():
            issues.append(f"{label}: 中文翻译 (abstract_cn) 为空")
        for key, label_cn in _DIM_DEFS:
            if not (p.get(key) or "").strip():
                issues.append(f"{label}: {label_cn} ({key}) 为空")
    return {
        "total_papers": len(papers),
        "issues_count": len(issues),
        "issues": issues,
        "ok": len(issues) == 0,
    }


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("\n", "<br>")
    )


def _make_slide(content: str, cls: str = "") -> str:
    """包装为幻灯片容器。"""
    return f'<div class="slide {cls}">{content}</div>\n'


def generate_ppt_html_report(
    papers: list[dict],
    output_path: str,
    topic_name: str,
    date_range: str,
    days: int = 0,
    topic_keyword: str = "",
) -> None:
    """
    生成 HTML-PPT 版报告（16:9 幻灯片布局）。
    """
    # ── Layer A：数据完整性审查 ────────────────────────────────────────────────
    vr = validate_papers_for_ppt(papers)
    if not vr["ok"]:
        logger.warning("[PPT数据审查] %d 个字段缺失（共 %d 篇论文）",
                       vr["issues_count"], vr["total_papers"])
        for issue in vr["issues"]:
            logger.warning("[PPT数据审查]  - %s", issue)
    else:
        logger.info("[PPT数据审查] 通过：%d 篇论文，所有字段完整", vr["total_papers"])

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    total = len(papers)

    css = """
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #f0f4f8;
      font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', Arial, sans-serif;
      color: #1a202c;
    }
    /* ── 幻灯片容器 ── */
    .slide {
      width: 1280px;
      min-height: 720px;
      margin: 24px auto;
      position: relative;
      page-break-after: always;
      display: flex;
      flex-direction: column;
      box-shadow: 0 4px 24px rgba(0,51,102,0.12);
    }
    /* ── 封面 ── */
    .slide-cover {
      background: linear-gradient(135deg, #003366 0%, #0055aa 55%, #0066cc 100%);
      justify-content: center;
      align-items: center;
      text-align: center;
      padding: 60px;
      color: #fff;
    }
    .slide-cover .cover-tag {
      font-size: 0.85rem;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      opacity: 0.82;
      margin-bottom: 20px;
    }
    .slide-cover h1 {
      font-size: 2.6rem;
      font-weight: 800;
      line-height: 1.3;
      margin-bottom: 24px;
      text-shadow: 0 2px 12px rgba(0,0,0,0.2);
    }
    .slide-cover .cover-meta {
      font-size: 1rem;
      opacity: 0.88;
      line-height: 2;
    }
    /* ── 通用幻灯片 ── */
    .slide-page {
      background: #ffffff;
      border: 1px solid #d6e4f7;
    }
    .slide-header {
      background: linear-gradient(90deg, #003366, #0055aa);
      padding: 14px 32px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-shrink: 0;
    }
    .slide-header .slide-title {
      font-size: 1.15rem;
      font-weight: 700;
      color: #fff;
    }
    .slide-header .slide-num {
      font-size: 0.8rem;
      color: rgba(255,255,255,0.7);
    }
    .slide-body {
      flex: 1 0 auto;
      padding: 24px 32px;
      background: #fff;
    }
    /* ── 概览幻灯片 ── */
    .overview-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.82rem;
      margin-top: 12px;
    }
    .overview-table th {
      background: #003366;
      color: #fff;
      padding: 10px 12px;
      text-align: left;
      font-weight: 600;
    }
    .overview-table td {
      padding: 9px 12px;
      border-bottom: 1px solid #d6e4f7;
      color: #2d3748;
      vertical-align: top;
    }
    .overview-table tr:nth-child(even) td { background: #f7faff; }
    .overview-table a { color: #0055aa; text-decoration: none; }
    /* ── 文献详情：第1张（基本信息 + 摘要） ── */
    .paper-info-grid {
      display: grid;
      grid-template-columns: 260px 1fr;
      gap: 20px;
    }
    .info-panel {
      background: #f7faff;
      border: 1px solid #d6e4f7;
      border-radius: 10px;
      padding: 16px;
      font-size: 0.82rem;
    }
    .info-panel .info-row { margin-bottom: 12px; }
    .info-panel .info-label {
      font-size: 0.72rem;
      color: #0055aa;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      margin-bottom: 3px;
    }
    .info-panel .info-val { color: #2d3748; line-height: 1.5; }
    .abstract-panel { display: flex; flex-direction: column; gap: 12px; }
    .abstract-box-ppt {
      background: #f7faff;
      border: 1px solid #d6e4f7;
      border-radius: 10px;
      padding: 14px;
    }
    .abstract-box-ppt .ab-lang {
      font-size: 0.7rem;
      color: #003366;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 8px;
    }
    .abstract-box-ppt .ab-text {
      font-size: 0.8rem;
      color: #4a5568;
      line-height: 1.6;
    }
    /* ── 文献详情：第2张（6维度分析） ── */
    .dims-ppt-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      grid-template-rows: repeat(2, 1fr);
      gap: 14px;
      height: 100%;
    }
    .dim-ppt-card {
      background: #f7faff;
      border: 1px solid #d6e4f7;
      border-radius: 10px;
      padding: 14px;
      display: flex;
      flex-direction: column;
    }
    .dim-ppt-header {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 10px;
    }
    .dim-ppt-icon { font-size: 1.1rem; }
    .dim-ppt-label {
      font-size: 0.8rem;
      font-weight: 700;
      color: #003366;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .dim-ppt-body {
      font-size: 0.8rem;
      color: #4a5568;
      line-height: 1.6;
      flex: 1;
    }
    /* ── 总结幻灯片 ── */
    .summary-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
      height: 100%;
    }
    .summary-box {
      background: #f7faff;
      border: 1px solid #d6e4f7;
      border-radius: 12px;
      padding: 20px;
    }
    .summary-box h3 {
      font-size: 0.9rem;
      color: #003366;
      font-weight: 700;
      margin-bottom: 12px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .summary-box ul { list-style: none; padding: 0; }
    .summary-box ul li {
      font-size: 0.82rem;
      color: #4a5568;
      padding: 6px 0;
      border-bottom: 1px solid #d6e4f7;
      display: flex;
      align-items: flex-start;
      gap: 8px;
    }
    .summary-box ul li::before { content: "▸"; color: #0055aa; flex-shrink: 0; }
    /* ── 结束幻灯片 ── */
    .slide-end {
      background: linear-gradient(135deg, #003366 0%, #0066cc 100%);
      justify-content: center;
      align-items: center;
      text-align: center;
      color: #fff;
    }
    .slide-end h2 { font-size: 2rem; font-weight: 700; margin-bottom: 16px; }
    .slide-end p { font-size: 1rem; opacity: 0.85; }
    /* ── 打印 / PDF ── */
    @page {
      size: 1280px 720px;
      margin: 0;
    }
    @media print {
      html, body { background: #f0f4f8; width: 1280px; margin: 0; padding: 0; }
      .slide {
        margin: 0;
        width: 1280px;
        min-height: 720px;
        height: 720px;
        page-break-after: always;
        page-break-inside: avoid;
        box-shadow: none;
        overflow: hidden;
      }
    }
    """

    slides_html = ""
    slide_total = 1 + total * 2 + 1  # cover(1) + papers×2 + end(1)

    # ── 封面 ─────────────────────────────────────────────────────────────────
    slides_html += _make_slide(f"""
      <div class="cover-tag">文献调研报告 · Literature Research</div>
      <h1>{_escape(topic_name)}</h1>
      <div class="cover-meta">
        时间范围：{_escape(date_range)}<br>
        {"关键词：" + _escape(topic_keyword) + "<br>" if topic_keyword else ""}
        文献数量：{total} 篇 &nbsp;·&nbsp; 数据来源：PubMed<br>
        生成时间：{now_str}
      </div>
    """, "slide-cover")

    slide_idx = 1

    # ── 文献详情（每篇2张幻灯片） ────────────────────────────────────────────
    dim_defs = [
        ("technical_route", "技术路线", "🔬"),
        ("advantages", "技术优势", "✅"),
        ("limitations", "技术不足", "⚠️"),
        ("technical_barriers", "技术壁垒", "🔒"),
        ("feasibility", "落地可行性", "🏭"),
        ("generalization", "泛化能力", "🌐"),
    ]

    for i, p in enumerate(papers, 1):
        title = _escape(p.get("title", ""))
        title_cn = _escape(p.get("title_cn", ""))
        journal = _escape(p.get("journal", ""))
        if_val = p.get("journal_if", "—")
        pub_date = p.get("publication_date", "—")
        author_display = _escape(p.get("author_display", ""))
        doi = p.get("doi", "")
        pmid = p.get("pmid", "")
        abstract = _escape(p.get("abstract", ""))
        abstract_cn = _escape(p.get("abstract_cn", ""))

        doi_link = f'<a href="https://doi.org/{doi}" target="_blank" style="color:#0055aa">{doi}</a>' if doi else "—"
        pmid_link = f'<a href="https://pubmed.ncbi.nlm.nih.gov/{pmid}/" target="_blank" style="color:#0055aa">PMID: {pmid}</a>' if pmid else ""

        # 第1张：基本信息 + 摘要
        slide_idx += 1
        paper_slide1 = f"""
      <div class="slide-header">
        <span class="slide-title">文献 {i}/{total} · 基本信息 &amp; 摘要</span>
        <span class="slide-num">{slide_idx} / {slide_total}</span>
      </div>
      <div class="slide-body">
        <div style="font-size:1.1rem;font-weight:700;color:#003366;margin-bottom:10px">{title}</div>
        {'<div style="font-size:0.88rem;color:#4a5568;margin-bottom:14px">' + title_cn + '</div>' if title_cn else ''}
        <div class="paper-info-grid">
          <div class="info-panel">
            <div class="info-row">
              <div class="info-label">期刊</div>
              <div class="info-val">{journal}<br><span style="color:#0055aa">IF: {if_val}</span></div>
            </div>
            <div class="info-row">
              <div class="info-label">发表日期</div>
              <div class="info-val">{pub_date}</div>
            </div>
            <div class="info-row">
              <div class="info-label">作者</div>
              <div class="info-val">{author_display}</div>
            </div>
            <div class="info-row">
              <div class="info-label">DOI</div>
              <div class="info-val" style="font-size:0.75rem">{doi_link}</div>
            </div>
            {'<div class="info-row"><div class="info-label">PubMed</div><div class="info-val" style="font-size:0.75rem">' + pmid_link + '</div></div>' if pmid_link else ''}
          </div>
          <div class="abstract-panel">
            <div class="abstract-box-ppt">
              <div class="ab-lang">English Abstract</div>
              <div class="ab-text">{abstract}</div>
            </div>
            <div class="abstract-box-ppt">
              <div class="ab-lang">中文翻译</div>
              <div class="ab-text">{abstract_cn}</div>
            </div>
          </div>
        </div>
      </div>
        """
        slides_html += _make_slide(paper_slide1, "slide-page")

        # 第2张：6维度分析
        slide_idx += 1
        dim_cards = ""
        for key, label, icon in dim_defs:
            content = _escape(p.get(key, "") or "待分析")
            dim_cards += f"""
          <div class="dim-ppt-card">
            <div class="dim-ppt-header">
              <span class="dim-ppt-icon">{icon}</span>
              <span class="dim-ppt-label">{label}</span>
            </div>
            <div class="dim-ppt-body">{content}</div>
          </div>"""

        paper_slide2 = f"""
      <div class="slide-header">
        <span class="slide-title">文献 {i}/{total} · 深度分析（6维度）</span>
        <span class="slide-num">{slide_idx} / {slide_total}</span>
      </div>
      <div class="slide-body">
        <div style="font-size:1.1rem;font-weight:700;color:#003366;margin-bottom:12px">{title}</div>
        <div class="dims-ppt-grid">{dim_cards}</div>
      </div>
        """
        slides_html += _make_slide(paper_slide2, "slide-page")

    # ── 结束幻灯片 ────────────────────────────────────────────────────────────
    slides_html += _make_slide(f"""
      <h2>感谢阅览</h2>
      <p>{topic_name} 文献调研报告</p>
      <p style="margin-top:16px;font-size:0.9rem;opacity:0.65">
        数据来源：PubMed &amp; Europe PMC &nbsp;|&nbsp; 生成时间：{now_str}
      </p>
    """, "slide-end")

    # ── 完整 HTML ─────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{topic_name} 文献调研报告 PPT 版</title>
  <style>{css}</style>
</head>
<body>
{slides_html}
</body>
</html>"""

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _main():
    import argparse

    parser = argparse.ArgumentParser(description="生成 HTML-PPT 版报告")
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

    generate_ppt_html_report(
        papers, args.output, args.topic_name,
        args.date_range, args.days, args.topic_keyword,
    )
    print(f"✅ HTML-PPT 版报告已生成: {args.output}")


if __name__ == "__main__":
    _main()
