#!/usr/bin/env python3
"""
开源文献 PDF 全文下载模块

下载策略（按成功率排序）：
  1. Unpaywall API    — 最可靠，覆盖 OA 文献
  2. PubMed Central   — PMC 开放获取，通过 PMID 查 PMCID
  3. Europe PMC PDF   — 另一路径
  4. 出版商直接下载   — Springer / Nature / Frontiers / BioRxiv 等
  5. Semantic Scholar — 开放获取 PDF 链接

使用方法：
    from download_pdfs import download_papers_pdf
    results = download_papers_pdf(papers, output_dir="pdfs/")
"""

import logging
import os
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; LiteratureResearchBot/1.0; "
        "+https://github.com/literature-research-tool)"
    )
}
UNPAYWALL_EMAIL = os.getenv("UNPAYWALL_EMAIL", "research@example.com")
TIMEOUT = 30
PDF_MIN_SIZE = 5000  # bytes — 小于此值视为下载失败


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _clean_doi(doi: str) -> str:
    """标准化 DOI：去除 https://doi.org/ 前缀，strip 空白。"""
    doi = doi.strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    return doi


def _safe_filename(doi: str, pmid: str, title: str) -> str:
    """生成安全文件名（不含特殊字符）。"""
    base = doi or pmid or title[:40]
    base = re.sub(r"[^\w\-.]", "_", base)
    return f"{base}.pdf"


def _is_valid_pdf(content: bytes) -> bool:
    """检验内容是否为真正的 PDF 文件。"""
    return len(content) >= PDF_MIN_SIZE and content[:4] == b"%PDF"


def _save_pdf(content: bytes, path: Path) -> bool:
    """保存 PDF 到磁盘，返回是否成功。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        return True
    except Exception as e:
        logger.warning("保存 PDF 失败 %s: %s", path, e)
        return False


def _download_url(url: str, timeout: int = TIMEOUT) -> Optional[bytes]:
    """下载 URL，返回原始字节；失败返回 None。"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if resp.status_code == 200:
            return resp.content
    except Exception as e:
        logger.debug("下载失败 %s: %s", url, e)
    return None


# ── 下载策略 ──────────────────────────────────────────────────────────────────

def _try_unpaywall(doi: str) -> Optional[str]:
    """通过 Unpaywall API 获取 open-access PDF 链接。"""
    if not doi:
        return None
    try:
        url = f"https://api.unpaywall.org/v2/{doi}?email={UNPAYWALL_EMAIL}"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            # 优先 gold OA，其次 best_oa_location
            best = data.get("best_oa_location") or {}
            pdf_url = best.get("url_for_pdf")
            if pdf_url:
                logger.debug("Unpaywall 找到 PDF: %s", pdf_url)
                return pdf_url
            # 遍历所有 OA 位置
            for loc in data.get("oa_locations", []):
                if loc.get("url_for_pdf"):
                    return loc["url_for_pdf"]
    except Exception as e:
        logger.debug("Unpaywall 查询失败 %s: %s", doi, e)
    return None


def _try_pmc(pmid: str) -> Optional[str]:
    """通过 PMID 查找 PMC 开放获取 PDF 链接。"""
    if not pmid:
        return None
    try:
        # Step 1: PMID → PMCID
        link_url = (
            f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"
            f"?dbfrom=pubmed&db=pmc&id={pmid}&retmode=json"
        )
        resp = requests.get(link_url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None

        data = resp.json()
        link_sets = data.get("linksets", [])
        pmcid = None
        for ls in link_sets:
            for db_links in ls.get("linksetdbs", []):
                if db_links.get("dbto") == "pmc" and db_links.get("links"):
                    pmcid = str(db_links["links"][0])
                    break

        if pmcid:
            # Step 2: 构造 PMC PDF URL
            pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid}/pdf/"
            logger.debug("PMC 找到 PDF: %s", pdf_url)
            return pdf_url
    except Exception as e:
        logger.debug("PMC 查询失败 PMID=%s: %s", pmid, e)
    return None


def _try_europe_pmc(doi: str, pmid: str) -> Optional[str]:
    """通过 Europe PMC 查找全文 PDF。"""
    try:
        query = f"DOI:{doi}" if doi else f"EXT_ID:{pmid} SRC:MED"
        url = (
            f"https://www.ebi.ac.uk/europepmc/webservices/rest/search"
            f"?query={query}&resulttype=core&format=json&pageSize=1"
        )
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            results = resp.json().get("resultList", {}).get("result", [])
            if results:
                r = results[0]
                pmcid = r.get("pmcid")
                if pmcid:
                    pdf_url = f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmcid}&blobtype=pdf"
                    return pdf_url
    except Exception as e:
        logger.debug("Europe PMC 查询失败: %s", e)
    return None


def _try_publisher_direct(doi: str) -> list[str]:
    """根据 DOI 前缀尝试出版商直接下载链接。"""
    if not doi:
        return []

    candidates = []
    doi_lower = doi.lower()
    doi_suffix = doi.split("/", 1)[-1] if "/" in doi else doi

    # bioRxiv / medRxiv  (10.1101 prefix covers both preprint servers)
    if "biorxiv" in doi_lower or "medrxiv" in doi_lower or doi.startswith("10.1101"):
        candidates.append(f"https://www.biorxiv.org/content/{doi}.full.pdf")
        candidates.append(f"https://www.medrxiv.org/content/{doi}.full.pdf")

    # Frontiers
    if "frontiersin.org" in doi_lower or doi.startswith("10.3389"):
        candidates.append(f"https://www.frontiersin.org/articles/{doi}/pdf")

    # PLOS journals
    if doi.startswith("10.1371"):
        candidates.append(f"https://journals.plos.org/plosone/article/file?id={doi}&type=printable")

    # PeerJ
    if doi.startswith("10.7717"):
        candidates.append(f"https://peerj.com/articles/{doi_suffix}.pdf")

    # eLife
    if doi.startswith("10.7554"):
        candidates.append(f"https://elifesciences.org/articles/{doi_suffix}/download")

    # BMC (BioMed Central) — open access
    if doi.startswith("10.1186"):
        candidates.append(f"https://bmcbioinformatics.biomedcentral.com/counter/pdf/{doi}")

    # Nature (open-access articles)
    if doi.startswith("10.1038"):
        candidates.append(f"https://www.nature.com/articles/{doi_suffix}.pdf")

    # Springer OA
    if doi.startswith("10.1007"):
        candidates.append(f"https://link.springer.com/content/pdf/{doi}.pdf")

    # Generic: try doi.org redirect + /pdf suffix
    candidates.append(f"https://doi.org/{doi}")

    return candidates


def _try_semantic_scholar(doi: str, pmid: str) -> Optional[str]:
    """通过 Semantic Scholar API 查找开放获取 PDF。"""
    try:
        paper_id = f"DOI:{doi}" if doi else f"PMID:{pmid}"
        url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}?fields=openAccessPdf"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            oa_pdf = data.get("openAccessPdf") or {}
            pdf_url = oa_pdf.get("url")
            if pdf_url:
                logger.debug("Semantic Scholar 找到 PDF: %s", pdf_url)
                return pdf_url
    except Exception as e:
        logger.debug("Semantic Scholar 查询失败: %s", e)
    return None


# ── 主入口 ────────────────────────────────────────────────────────────────────

def download_single_paper_pdf(
    doi: str,
    pmid: str,
    title: str,
    output_dir: str,
    delay: float = 1.0,
) -> dict:
    """
    尝试下载单篇文献的开放获取 PDF。

    Returns:
        {
            "doi": str,
            "pmid": str,
            "title": str,
            "status": "success" | "not_available" | "failed",
            "pdf_path": str | None,
            "source": str,
            "reason": str,
        }
    """
    result = {
        "doi": doi,
        "pmid": pmid,
        "title": title,
        "status": "not_available",
        "pdf_path": None,
        "source": "",
        "reason": "No open-access PDF found",
    }

    doi = _clean_doi(doi) if doi else ""
    out_path = Path(output_dir) / _safe_filename(doi, pmid, title)

    # 如果已存在，跳过下载
    if out_path.exists() and out_path.stat().st_size >= PDF_MIN_SIZE:
        result.update({"status": "success", "pdf_path": str(out_path), "source": "cached"})
        return result

    pdf_url = None
    source_name = ""

    # ── 策略 1: Unpaywall ────────────────────────────────────────────────────
    if doi:
        pdf_url = _try_unpaywall(doi)
        if pdf_url:
            source_name = "unpaywall"

    # ── 策略 2: PubMed Central ───────────────────────────────────────────────
    if not pdf_url and pmid:
        pdf_url = _try_pmc(pmid)
        if pdf_url:
            source_name = "pmc"

    # ── 策略 3: Europe PMC ────────────────────────────────────────────────────
    if not pdf_url:
        pdf_url = _try_europe_pmc(doi, pmid)
        if pdf_url:
            source_name = "europe_pmc"

    # ── 策略 4: Semantic Scholar ──────────────────────────────────────────────
    if not pdf_url:
        pdf_url = _try_semantic_scholar(doi, pmid)
        if pdf_url:
            source_name = "semantic_scholar"

    # ── 尝试下载找到的链接 ─────────────────────────────────────────────────────
    if pdf_url:
        time.sleep(delay)
        content = _download_url(pdf_url)
        if content and _is_valid_pdf(content):
            if _save_pdf(content, out_path):
                result.update({
                    "status": "success",
                    "pdf_path": str(out_path),
                    "source": source_name,
                    "reason": f"Downloaded from {source_name}",
                })
                return result
        else:
            logger.debug("下载链接无效 PDF 内容: %s", pdf_url)

    # ── 策略 5: 出版商直接下载 ───────────────────────────────────────────────
    for candidate_url in _try_publisher_direct(doi):
        time.sleep(delay * 0.5)
        content = _download_url(candidate_url)
        if content and _is_valid_pdf(content):
            if _save_pdf(content, out_path):
                result.update({
                    "status": "success",
                    "pdf_path": str(out_path),
                    "source": "publisher_direct",
                    "reason": f"Downloaded from {candidate_url}",
                })
                return result

    result["reason"] = "Article not available in open access"
    return result


def download_papers_pdf(
    papers: list[dict],
    output_dir: str,
    delay: float = 1.5,
    max_downloads: Optional[int] = None,
) -> list[dict]:
    """
    批量下载文献 PDF。

    Args:
        papers: 文献列表（每条包含 doi, pmid, title）
        output_dir: PDF 保存目录
        delay: 每次下载间隔秒数（避免触发速率限制）
        max_downloads: 最多下载篇数（None = 全部尝试）

    Returns:
        下载结果列表，与 papers 一一对应
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    results = []

    targets = papers[:max_downloads] if max_downloads else papers
    success_count = 0

    logger.info("开始下载 %d 篇文献 PDF → %s", len(targets), output_dir)

    for i, paper in enumerate(targets, 1):
        doi = paper.get("doi", "") or ""
        pmid = paper.get("pmid", "") or ""
        title = paper.get("title", "") or f"paper_{i}"

        logger.info("[%d/%d] %s", i, len(targets), title[:60])

        res = download_single_paper_pdf(doi, pmid, title, output_dir, delay=delay)
        results.append(res)

        if res["status"] == "success":
            success_count += 1
            logger.info("  ✅ 下载成功 (%s)", res["source"])
        else:
            logger.info("  ⚠️  %s", res["reason"])

    logger.info(
        "PDF 下载完成: %d/%d 成功", success_count, len(targets)
    )
    return results


def attach_pdf_paths_to_papers(papers: list[dict], download_results: list[dict]) -> list[dict]:
    """将下载结果附加回 papers 列表。"""
    result_map = {
        (r.get("doi", ""), r.get("pmid", "")): r
        for r in download_results
    }
    for paper in papers:
        key = (paper.get("doi", ""), paper.get("pmid", ""))
        res = result_map.get(key)
        if res:
            paper["pdf_path"] = res.get("pdf_path")
            paper["pdf_status"] = res.get("status")
            paper["pdf_source"] = res.get("source")
    return papers


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="批量下载开放获取 PDF")
    parser.add_argument("--input", required=True, help="papers JSON 文件")
    parser.add_argument("--output", default="./pdfs", help="PDF 保存目录")
    parser.add_argument("--delay", type=float, default=1.5, help="每次下载间隔秒")
    parser.add_argument("--max", type=int, default=None, help="最多下载篇数")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)
    papers = data if isinstance(data, list) else data.get("papers", [])

    results = download_papers_pdf(papers, args.output, args.delay, args.max)
    success = sum(1 for r in results if r["status"] == "success")
    print(f"\n✅ 下载完成: {success}/{len(results)} 篇成功")
    for r in results:
        icon = "✅" if r["status"] == "success" else "❌"
        print(f"  {icon} [{r['source']}] {r['title'][:50]}")
