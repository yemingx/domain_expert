#!/usr/bin/env python3
"""
md_to_reports.py — 将文献调研 Markdown 报告转换为多种格式

支持格式:
  • Word  (.docx)  — 双语对照 + 6维分析
  • HTML  阅读版   — 蓝白主题静态网页
  • HTML  PPT版    — 16:9 幻灯片，可浏览器全屏展示
  • PDF   PPT版    — 由 HTML-PPT 通过 Playwright 打印生成

用法 (命令行):
    python md_to_reports.py --input report.md --output-dir ./out
    python md_to_reports.py --input report.md --formats word html html_ppt pdf_ppt

用法 (API):
    from md_to_reports import convert_markdown_to_reports
    results = convert_markdown_to_reports(
        md_path="report.md",
        output_dir="./out",
        topic_name="无创产前诊断",
        date_range="2015-01-01 至 2026-04-05",
    )
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Markdown 解析 ─────────────────────────────────────────────────────────────

_ANALYSIS_KEYS = {
    "1": "technical_route",
    "2": "advantages",
    "3": "limitations",
    "4": "technical_barriers",
    "5": "feasibility",
    "6": "generalization",
}

# 中文标签 → 英文 key 的模糊映射
_LABEL_MAP = {
    "技术路线": "technical_route",
    "technical route": "technical_route",
    "技术优势": "advantages",
    "advantages": "advantages",
    "技术不足": "limitations",
    "limitations": "limitations",
    "技术壁垒": "technical_barriers",
    "technical barrier": "technical_barriers",
    "落地可行性": "feasibility",
    "feasibility": "feasibility",
    "泛化能力": "generalization",
    "generalization": "generalization",
}


def _label_to_key(label: str) -> Optional[str]:
    """将分析维度标签映射到字段名。"""
    label_lower = label.lower().strip()
    for cn, key in _LABEL_MAP.items():
        if cn in label_lower or label_lower in cn:
            return key
    # 按编号匹配 "1." "2." etc.
    m = re.match(r"^(\d)\.", label_lower)
    if m:
        return _ANALYSIS_KEYS.get(m.group(1))
    return None


def parse_markdown(md_text: str) -> list[dict]:
    """
    解析文献调研 Markdown，返回 papers 列表。

    支持两种 Markdown 格式:
    格式A (旧): ## N. <title>  +  ### <section>
    格式B (新): ## 单篇文献详细分析 → ### N. <title>  +  #### <section>

    解析后自动做完整性检查，title 和 abstract 至少有其一才保留。
    """
    papers: list[dict] = []
    lines = md_text.splitlines()

    # ── 自动检测格式 ─────────────────────────────────────────────────────────
    # 格式B 特征: 存在 "### N. <title>" 且 "#### 基本信息"
    has_triple_paper = any(re.match(r"^###\s+\d+\.\s+\S", l) for l in lines)
    has_quad_section = any(re.match(r"^####\s+", l) for l in lines)
    fmt_b = has_triple_paper and has_quad_section

    if fmt_b:
        paper_heading_re = re.compile(r"^###\s+(?:\d+\.\s+)?(.+)$")
        section_heading_re = re.compile(r"^####\s+(.+)$")
        # 格式B 中的 ## 行都是章节分隔符，不是文献标题
        skip_at_level2 = True
    else:
        paper_heading_re = re.compile(r"^##\s+(?:\d+\.\s+)?(.+)$")
        section_heading_re = re.compile(r"^###\s+(.+)$")
        skip_at_level2 = False

    logger.debug("Markdown格式检测: %s", "B (###/####)" if fmt_b else "A (##/###)")

    i = 0
    current: dict | None = None

    def _new_paper(title: str) -> dict:
        return {
            "title": title,
            "title_cn": "",
            "abstract": "",
            "abstract_cn": "",
            "journal": "",
            "journal_if": "",
            "publication_date": "",
            "year": 0,
            "author_display": "",
            "first_author": "",
            "corresponding_authors": [],
            "research_team": "",
            "doi": "",
            "pmid": "",
            "affiliations": [],
            "technical_route": "",
            "advantages": "",
            "limitations": "",
            "technical_barriers": "",
            "feasibility": "",
            "generalization": "",
        }

    def _flush():
        if current:
            for k, v in current.items():
                if isinstance(v, str):
                    current[k] = v.strip()
            papers.append(current)

    section: str | None = None
    buffer: list[str] = []

    # ── section 字段别名 ─────────────────────────────────────────────────────
    _SECTION_ALIAS = {
        "英文摘要": "原文摘要",
        "english abstract": "原文摘要",
        "abstract": "原文摘要",
        "中文翻译": "中文翻译",
        "中文摘要": "中文翻译",
        "深度分析": "深度分析",
        "基本信息": "基本信息",
    }

    def _normalize_section(name: str) -> str:
        nl = name.lower().strip()
        for k, v in _SECTION_ALIAS.items():
            if k in nl:
                return v
        return name

    def _save_buffer():
        if current is None or section is None:
            return
        text = "\n".join(buffer).strip()
        if not text:
            return

        sec = _normalize_section(section)

        if sec == "基本信息":
            for line in buffer:
                line = line.strip().lstrip("- ").strip()
                m = re.match(r"\*\*(.+?)\*\*[：:]\s*(.+)", line)
                if not m:
                    continue
                field, value = m.group(1).strip(), m.group(2).strip()
                if "期刊" in field:
                    # "Nature Medicine（IF: 58.7）" or "Nature Medicine (IF: 58.7)"
                    jm = re.match(r"(.+?)\s*[（(]IF[:：]\s*([^)）]+)[)）]", value)
                    if jm:
                        current["journal"] = jm.group(1).strip()
                        current["journal_if"] = jm.group(2).strip()
                    else:
                        current["journal"] = value
                elif "发表日期" in field or "date" in field.lower():
                    current["publication_date"] = value
                    m2 = re.match(r"(\d{4})", value)
                    if m2:
                        current.setdefault("year", int(m2.group(1)))
                elif "作者" in field and "通讯" not in field:
                    current["author_display"] = value
                    parts = re.split(r"\s+et\s+al\.", value, flags=re.IGNORECASE)
                    current["first_author"] = parts[0].strip()
                    ca_m = re.search(r"通讯[:：]\s*(.+)", value)
                    if ca_m:
                        current["corresponding_authors"] = [ca_m.group(1).strip()]
                elif "研究团队" in field:
                    current["research_team"] = value
                elif field.upper() == "DOI":
                    current["doi"] = value
                elif field.upper() == "PMID":
                    current["pmid"] = value
        elif sec == "原文摘要":
            current["abstract"] = text
        elif sec == "中文翻译":
            current["abstract_cn"] = text
        elif sec == "深度分析":
            for line in buffer:
                line = line.strip()
                m = re.match(r"\*\*(\d+)[.\s]+(.+?)\*\*[：:]\s*(.+)", line)
                if m:
                    key = _ANALYSIS_KEYS.get(m.group(1))
                    if key:
                        current[key] = m.group(3).strip()
                    continue
                m2 = re.match(r"\*\*(.+?)\*\*[：:]\s*(.+)", line)
                if m2:
                    key = _label_to_key(m2.group(1))
                    if key:
                        current[key] = m2.group(2).strip()
        elif section:
            key = _label_to_key(section)
            if key:
                current[key] = text

    skip_words = {"目录", "概览", "总结", "参考文献", "说明", "overview", "summary", "toc",
                  "单篇文献详细分析", "总体行业分析", "发展建议", "文献概览"}

    while i < len(lines):
        line = lines[i]

        # 格式B: ## 行全部跳过（只是章节分隔）
        if skip_at_level2 and re.match(r"^##\s+", line) and not re.match(r"^###", line):
            i += 1
            continue

        pm = paper_heading_re.match(line)
        if pm:
            candidate = pm.group(1).strip()
            if any(w in candidate.lower() for w in skip_words):
                i += 1
                continue

            _save_buffer()
            _flush()
            current = _new_paper(candidate)
            section = None
            buffer = []
            i += 1
            continue

        sm = section_heading_re.match(line)
        if sm and current is not None:
            _save_buffer()
            section = sm.group(1).strip()
            buffer = []
            i += 1
            continue

        if current is not None and section is not None:
            buffer.append(line)

        i += 1

    _save_buffer()
    _flush()

    # ── 完整性检查 ────────────────────────────────────────────────────────────
    before = len(papers)
    papers = _check_papers(papers)
    if len(papers) < before:
        logger.warning("完整性检查: 丢弃 %d 篇内容为空的文献（共解析 %d 篇）",
                       before - len(papers), before)

    logger.info("Markdown 解析完成: %d 篇文献", len(papers))
    return papers


def _check_papers(papers: list[dict]) -> list[dict]:
    """
    完整性检查：过滤掉无实质内容的条目，并记录告警。

    判断标准（满足任一即保留）:
    - title 非空且长度 > 10（排除误匹配的短标题）
    - abstract 非空
    """
    valid = []
    for p in papers:
        title = (p.get("title") or "").strip()
        abstract = (p.get("abstract") or "").strip()
        # 必须有足够长度的标题
        if len(title) <= 10 and not abstract:
            logger.warning("丢弃内容空白条目: title=%r", title[:60])
            continue
        # 有标题但摘要为空时给出告警（保留，但标注）
        if not abstract:
            logger.warning("文献缺少摘要: %r", title[:80])
        valid.append(p)
    return valid


def _extract_meta_from_markdown(md_text: str) -> dict:
    """从 Markdown 文件头部提取 topic_name / date_range / days。"""
    meta = {"topic_name": "", "date_range": "", "days": 0}

    for line in md_text.splitlines()[:20]:
        # "# 无创产前诊断 文献调研报告" → topic
        m = re.match(r"^#\s+(.+?)(?:文献调研报告|最新文献报告|调研报告)?$", line.strip())
        if m and not meta["topic_name"]:
            meta["topic_name"] = m.group(1).strip()

        # "检索关键词: NIPD"
        m2 = re.search(r"检索关键词[:：]\s*(.+)", line)
        if m2 and not meta["topic_name"]:
            meta["topic_name"] = m2.group(1).strip()

        # "最近60天"
        m3 = re.search(r"最近\s*(\d+)\s*天", line)
        if m3:
            meta["days"] = int(m3.group(1))

        # "文献范围: ... 2026-01-17至2026-03-18"
        m4 = re.search(r"(\d{4}[-/]\d{2}[-/]\d{2}).{0,6}(\d{4}[-/]\d{2}[-/]\d{2})", line)
        if m4 and not meta["date_range"]:
            meta["date_range"] = f"{m4.group(1)} 至 {m4.group(2)}"

    return meta


# ── PDF 转换 (Playwright / Puppeteer 备用) ────────────────────────────────────

def _html_to_pdf_playwright(html_path: Path, pdf_path: Path) -> bool:
    """使用 Playwright 逐幻灯片截图后合并为 PDF。

    策略：逐张幻灯片滚动到可见区域后截图，避免 Chromium GPU 光栅化器
    无法渲染页面 Y > ~16384px 以下内容导致截图空白的问题。
    对超过 720px 的幻灯片（摘要过长）动态调整 viewport 高度。

    _DPR=2 → 物理像素 = CSS px × 2；_PDF_DPI=192 → PDF 尺寸 = CSS px。
    """
    _SLIDE_W, _SLIDE_H = 1280, 720
    _DPR = 2
    _PDF_DPI = 96 * _DPR  # 192

    try:
        from playwright.sync_api import sync_playwright
        from PIL import Image as _PILImage
        import io as _io

        html_path = html_path.resolve()  # ensure absolute path for file:// URI
        slide_imgs: list[_PILImage.Image] = []
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(
                viewport={"width": _SLIDE_W, "height": _SLIDE_H},
                device_scale_factor=_DPR,
            )
            page = context.new_page()
            page.goto(html_path.as_uri(), wait_until="networkidle")
            page.wait_for_timeout(500)

            slides = page.query_selector_all(".slide")
            if not slides:
                raise ValueError("HTML PPT 中未找到 .slide 元素")

            cur_vp_h = _SLIDE_H  # 当前 viewport 高度（CSS px）

            for idx, slide in enumerate(slides, 1):
                # ── 1. 先滚动至可见（触发 GPU 渲染） ──────────────────────────
                page.evaluate(
                    "(el) => el.scrollIntoView({block:'start', behavior:'instant'})",
                    slide,
                )
                page.wait_for_timeout(100)

                # ── 2. 测量幻灯片高度（滚动后 bounding_box 为视口相对坐标） ──
                box = slide.bounding_box()
                if not box:
                    logger.warning("Slide %d: bounding_box 为 None，跳过", idx)
                    continue
                actual_h = max(box["height"], _SLIDE_H)

                # ── 3. 若幻灯片高于当前 viewport，则扩展 viewport 并重新滚动 ──
                if actual_h > cur_vp_h:
                    cur_vp_h = int(actual_h) + 10
                    page.set_viewport_size({"width": _SLIDE_W, "height": cur_vp_h})
                    page.evaluate(
                        "(el) => el.scrollIntoView({block:'start', behavior:'instant'})",
                        slide,
                    )
                    page.wait_for_timeout(100)
                    box = slide.bounding_box()
                    if not box:
                        logger.warning("Slide %d: resize 后 bounding_box 为 None，跳过", idx)
                        continue

                # ── 4. 截图（viewport 内截取，坐标均 < viewport 高度） ────────
                img_bytes = page.screenshot(
                    clip={
                        "x": max(0.0, box["x"]),
                        "y": max(0.0, box["y"]),
                        "width": _SLIDE_W,
                        "height": actual_h,
                    },
                    type="png",
                )
                img = _PILImage.open(_io.BytesIO(img_bytes)).convert("RGB")
                slide_imgs.append(img)
                logger.debug("Slide %d: %dx%d CSS px → 截图 %dx%d px",
                             idx, _SLIDE_W, int(actual_h), img.width, img.height)

            browser.close()

        if not slide_imgs:
            raise ValueError("未能截取任何幻灯片截图")

        # ── 合并为 PDF ───────────────────────────────────────────────────────
        slide_imgs[0].save(
            str(pdf_path),
            format="PDF",
            save_all=True,
            append_images=slide_imgs[1:],
            resolution=_PDF_DPI,
        )
        logger.info("PDF 已生成 (幻灯片 × %d 页, %d DPI): %s",
                    len(slide_imgs), _PDF_DPI, pdf_path)
        return True

    except Exception as e:
        logger.warning("Playwright 转换失败: %s", e)
        return False


def _validate_pdf_pages(pdf_path: Path) -> dict:
    """Layer C：PDF 空白页审查。

    用 PyMuPDF 将每页渲染为低分辨率图像，检查像素标准差。
    标准差极低（< 8）表示页面几乎是纯色（空白或渲染失败）。

    Returns:
        {
            "page_count": int,
            "blank_pages": list[int],   # 1-indexed 页码
            "issues_count": int,
            "ok": bool,                 # None 表示 PyMuPDF 不可用
        }
    """
    try:
        import fitz  # PyMuPDF
        import statistics

        blank_pages: list[int] = []
        doc = fitz.open(str(pdf_path))

        for page_num in range(doc.page_count):
            page = doc[page_num]
            # 渲染为低分辨率灰度图（足够检测空白）
            mat = fitz.Matrix(0.25, 0.25)
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
            samples = list(pix.samples)
            if not samples:
                blank_pages.append(page_num + 1)
                continue
            mean = sum(samples) / len(samples)
            variance = sum((x - mean) ** 2 for x in samples) / len(samples)
            std_dev = variance ** 0.5
            if std_dev < 8:  # 几乎纯色 → 空白页
                blank_pages.append(page_num + 1)
                logger.warning("[PDF空白页] 第 %d 页 std_dev=%.1f < 8，疑似空白",
                               page_num + 1, std_dev)

        page_count = doc.page_count
        doc.close()
        return {
            "page_count": page_count,
            "blank_pages": blank_pages,
            "issues_count": len(blank_pages),
            "ok": len(blank_pages) == 0,
        }

    except ImportError:
        logger.debug("PyMuPDF 不可用，跳过 PDF 空白页审查")
        return {"page_count": 0, "blank_pages": [], "issues_count": 0, "ok": None}
    except Exception as e:
        logger.warning("PDF 空白页审查失败: %s", e)
        return {"page_count": 0, "blank_pages": [], "issues_count": 0, "ok": None}


def _html_to_pdf_node(html_path: Path, pdf_path: Path) -> bool:
    """使用 Node.js + Puppeteer 脚本将 HTML-PPT 转换为 PDF。"""
    # 查找 html_to_pdf.js — 优先同目录，其次 ai_assistance 参考目录
    candidates = [
        Path(__file__).parent / "html_to_pdf.js",
        Path(__file__).parent.parent.parent.parent  # repo root
        / "ai_assistance" / "skills" / "literature-research" / "scripts" / "html_to_pdf.js",
    ]
    js_script = next((p for p in candidates if p.exists()), None)
    if not js_script:
        logger.warning("html_to_pdf.js 未找到，跳过 PDF 生成")
        return False

    try:
        import platform
        node_exe = (
            r"C:\Program Files\nodejs\node.exe"
            if platform.system() == "Windows"
            else "node"
        )
        result = subprocess.run(
            [node_exe, str(js_script), str(html_path), str(pdf_path)],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            logger.info("PDF 已生成 (Node.js): %s", pdf_path)
            return True
        logger.warning("Node.js PDF 转换失败 (exit %d): %s", result.returncode, result.stderr[:200])
    except Exception as e:
        logger.warning("Node.js PDF 转换失败: %s", e)
    return False


def _validate_ppt_rendering(html_path: Path) -> dict:
    """Layer B：渲染级审查 — 用 Playwright 加载 HTML PPT，检查每张幻灯片的内容渲染是否完整。

    检查项：
    - .ab-text 元素（中英文摘要框）是否有可见文本
    - .dim-ppt-body 元素（6维度分析框）是否有可见文本

    Returns:
        {
            "slide_count": int,
            "issues_count": int,
            "issues": list[str],
            "ok": bool,            # None 表示 Playwright 不可用
        }
    """
    try:
        from playwright.sync_api import sync_playwright

        issues: list[str] = []
        slide_count = 0

        html_path = html_path.resolve()  # ensure absolute path for file:// URI
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.goto(html_path.as_uri(), wait_until="networkidle")
            page.wait_for_timeout(300)

            slides = page.query_selector_all(".slide")
            slide_count = len(slides)

            for idx, slide in enumerate(slides, 1):
                # 检查摘要框
                ab_texts = slide.query_selector_all(".ab-text")
                for j, ab in enumerate(ab_texts, 1):
                    text = (ab.inner_text() or "").strip()
                    if not text:
                        issues.append(f"Slide {idx}: 摘要框 #{j} 内容为空")

                # 检查 6 维度分析框
                dim_bodies = slide.query_selector_all(".dim-ppt-body")
                for j, dim in enumerate(dim_bodies, 1):
                    text = (dim.inner_text() or "").strip()
                    if not text or text == "待分析":
                        issues.append(f"Slide {idx}: 分析框 #{j} 内容为空或占位符")

            browser.close()

        return {
            "slide_count": slide_count,
            "issues_count": len(issues),
            "issues": issues,
            "ok": len(issues) == 0,
        }

    except Exception as e:
        logger.warning("PPT 渲染审查失败（Playwright 不可用或出错）: %s", e)
        return {"slide_count": 0, "issues_count": 0, "issues": [], "ok": None}


def _generate_pdf_ppt(html_ppt_path: Path, pdf_path: Path) -> bool:
    """将 HTML-PPT 转换为 PDF，自动选择可用方式。"""
    # 优先 Playwright，其次 Node/Puppeteer
    if _html_to_pdf_playwright(html_ppt_path, pdf_path):
        return True
    if _html_to_pdf_node(html_ppt_path, pdf_path):
        return True
    logger.error("PDF 生成失败: 需要 Playwright 或 Node.js + Puppeteer")
    return False


# ── 主转换函数 ────────────────────────────────────────────────────────────────

def convert_markdown_to_reports(
    md_path: str | Path,
    output_dir: str | Path | None = None,
    topic_name: str = "",
    date_range: str = "",
    days: int = 0,
    formats: list[str] | None = None,
) -> dict[str, str | None]:
    """
    将文献调研 Markdown 文件转换为多种格式报告。

    Args:
        md_path:    输入 Markdown 文件路径
        output_dir: 输出目录（默认与 md_path 同目录）
        topic_name: 主题名称（如 "无创产前诊断"），留空则从 Markdown 自动提取
        date_range: 时间范围字符串，留空则从 Markdown 自动提取
        days:       检索天数，0 则从 Markdown 自动提取
        formats:    生成格式列表 ["word", "html", "html_ppt", "pdf_ppt"]
                    默认全部生成

    Returns:
        {"word": path_or_None, "html": ..., "html_ppt": ..., "pdf_ppt": ...}
    """
    md_path = Path(md_path)
    if not md_path.exists():
        raise FileNotFoundError(f"Markdown 文件不存在: {md_path}")

    output_dir = Path(output_dir) if output_dir else md_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    if formats is None:
        formats = ["word", "html", "html_ppt", "pdf_ppt"]
    formats = [f.lower() for f in formats]

    # 读取并解析 Markdown
    md_text = md_path.read_text(encoding="utf-8", errors="replace")
    meta = _extract_meta_from_markdown(md_text)

    topic_name = topic_name or meta.get("topic_name") or md_path.stem
    date_range = date_range or meta.get("date_range") or ""
    days = days or meta.get("days") or 0

    papers = parse_markdown(md_text)
    if not papers:
        raise ValueError(f"Markdown 解析结果为空，请检查文件格式: {md_path}")

    logger.info("解析到 %d 篇文献，主题: %s，日期: %s", len(papers), topic_name, date_range)

    # 文件名前缀
    stem = md_path.stem  # e.g. "NIPD_文献调研报告_2026-04-05"
    results: dict[str, str | None] = {
        "word": None, "html": None, "html_ppt": None, "pdf_ppt": None
    }

    # 将 scripts/ 目录加入 sys.path，以便导入 generate_* 模块
    scripts_dir = Path(__file__).parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    # ── Word ──────────────────────────────────────────────────────────────────
    if "word" in formats:
        try:
            from generate_word import create_word_report
            word_path = output_dir / f"{stem}.docx"
            success, msg = create_word_report(
                papers=papers,
                output_path=str(word_path),
                topic_name=topic_name,
                date_range=date_range,
                auto_fix=False,  # data already enriched in run_job(); skip LLM re-calls
            )
            if success:
                results["word"] = str(word_path)
                logger.info("Word 报告已生成: %s", word_path)
            else:
                logger.error("Word 生成失败: %s", msg)
        except Exception as e:
            logger.error("Word 生成失败: %s", e, exc_info=True)

    # ── HTML 阅读版 ────────────────────────────────────────────────────────────
    if "html" in formats:
        try:
            from generate_html import generate_html_report
            html_path = output_dir / f"{stem}_阅读版.html"
            generate_html_report(
                papers=papers,
                output_path=str(html_path),
                topic_name=topic_name,
                date_range=date_range,
                days=days,
            )
            results["html"] = str(html_path)
            logger.info("HTML 阅读版已生成: %s", html_path)
        except Exception as e:
            logger.error("HTML 生成失败: %s", e)

    # ── HTML PPT 版 ────────────────────────────────────────────────────────────
    html_ppt_path = None
    if "html_ppt" in formats or "pdf_ppt" in formats:
        try:
            from generate_html_ppt import generate_ppt_html_report
            html_ppt_path = output_dir / f"{stem}_ppt.html"
            generate_ppt_html_report(
                papers=papers,
                output_path=str(html_ppt_path),
                topic_name=topic_name,
                date_range=date_range,
                days=days,
            )
            if "html_ppt" in formats:
                results["html_ppt"] = str(html_ppt_path)
            logger.info("HTML PPT 版已生成: %s", html_ppt_path)

            # ── Layer B：渲染审查 ──────────────────────────────────────────────
            render_report = _validate_ppt_rendering(html_ppt_path)
            if render_report["ok"] is True:
                logger.info("[PPT渲染审查] 通过：%d 张幻灯片，0 个问题",
                            render_report["slide_count"])
            elif render_report["ok"] is False:
                logger.warning("[PPT渲染审查] 发现 %d 个问题（共 %d 张幻灯片）",
                               render_report["issues_count"], render_report["slide_count"])
                for issue in render_report["issues"]:
                    logger.warning("[PPT渲染审查]  - %s", issue)
        except Exception as e:
            logger.error("HTML PPT 生成失败: %s", e)

    # ── PDF PPT 版 ─────────────────────────────────────────────────────────────
    if "pdf_ppt" in formats and html_ppt_path and html_ppt_path.exists():
        pdf_path = output_dir / f"{stem}_ppt.pdf"
        ok = _generate_pdf_ppt(html_ppt_path, pdf_path)
        if ok and pdf_path.exists():
            results["pdf_ppt"] = str(pdf_path)

            # ── Layer C：PDF 空白页审查 ────────────────────────────────────────
            pdf_report = _validate_pdf_pages(pdf_path)
            if pdf_report["ok"] is True:
                logger.info("[PDF空白页审查] 通过：%d 页，0 个空白页",
                            pdf_report["page_count"])
            elif pdf_report["ok"] is False:
                logger.warning("[PDF空白页审查] 发现 %d 个空白页（共 %d 页）: 页码 %s",
                               pdf_report["issues_count"], pdf_report["page_count"],
                               pdf_report["blank_pages"])

    return results


# ── CLI ───────────────────────────────────────────────────────────────────────

def _main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(
        description="将文献调研 Markdown 报告转换为 Word / HTML / HTML-PPT / PDF-PPT"
    )
    parser.add_argument("--input", "-i", required=True, help="输入 Markdown 文件路径")
    parser.add_argument("--output-dir", "-o", default=None, help="输出目录（默认与输入文件同目录）")
    parser.add_argument("--topic-name", default="", help="主题名称（留空则从 Markdown 自动提取）")
    parser.add_argument("--date-range", default="", help="时间范围字符串（留空则自动提取）")
    parser.add_argument(
        "--formats", "-f",
        nargs="+",
        default=["word", "html", "html_ppt", "pdf_ppt"],
        choices=["word", "html", "html_ppt", "pdf_ppt"],
        help="要生成的格式（可多选，默认全部）",
    )
    parser.add_argument(
        "--dump-json",
        action="store_true",
        help="将解析出的 papers 列表保存为 JSON（用于调试）",
    )
    args = parser.parse_args()

    results = convert_markdown_to_reports(
        md_path=args.input,
        output_dir=args.output_dir,
        topic_name=args.topic_name,
        date_range=args.date_range,
        formats=args.formats,
    )

    if args.dump_json:
        md_path = Path(args.input)
        md_text = md_path.read_text(encoding="utf-8", errors="replace")
        papers = parse_markdown(md_text)
        json_path = (Path(args.output_dir) if args.output_dir else md_path.parent) / "papers_parsed.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(papers, f, ensure_ascii=False, indent=2)
        print(f"Papers JSON: {json_path}")

    print("\n=== 生成结果 ===")
    for fmt, path in results.items():
        icon = "[OK]" if path else "[--]"
        print(f"  {icon} {fmt:<10} {path or '(未生成)'}")


if __name__ == "__main__":
    _main()
