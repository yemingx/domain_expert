"""
enrich_semantic_scholar.py — Semantic Scholar API 文献数据富化

为每篇文献补充以下字段:
  citation_count            int    S2 总引用数
  influential_citation_count int   S2 高影响力引用数
  s2_paper_id               str    Semantic Scholar 内部 ID
  s2_url                    str    https://www.semanticscholar.org/paper/{id}
  s2_authors                list   S2 作者对象（含 authorId，可用于去重）
  references                list   本文引用的文献（出引）
  citations_in              list   引用本文的文献（入引）

references / citations_in 每条格式:
  {
    "title":         str,
    "year":          int,
    "doi":           str | None,
    "pmid":          str | None,
    "s2_paper_id":   str | None,
    "url":           str | None,   # Semantic Scholar 页面
    "citation_count": int,
    "journal":       str,
    "authors":       list[str]     # 前 3 位作者姓名
  }

用法:
    from enrich_semantic_scholar import enrich_papers_with_semantic_scholar
    papers = enrich_papers_with_semantic_scholar(papers, api_key="", fetch_network=True)
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import urllib.request
import urllib.error
import json as _json

logger = logging.getLogger(__name__)

# ── 常量 ─────────────────────────────────────────────────────────────────────

_S2_BASE = "https://api.semanticscholar.org/graph/v1"

# Phase 1 批量查询字段（不含嵌套引用列表）
_BATCH_FIELDS = (
    "paperId,"
    "citationCount,"
    "influentialCitationCount,"
    "authors,"
    "externalIds,"
    "publicationVenue,"
    "isOpenAccess,"
    "openAccessPdf"
)

# Phase 2 引用/被引列表的子字段
_GRAPH_FIELDS = (
    "paperId,"
    "externalIds,"
    "title,"
    "year,"
    "citationCount,"
    "publicationVenue,"
    "authors"
)


# ── HTTP 工具 ─────────────────────────────────────────────────────────────────

import os as _os

def _build_opener() -> urllib.request.OpenerDirector:
    """构建 HTTP opener，自动读取环境变量代理配置。

    优先级：
    1. 环境变量 HTTPS_PROXY / HTTP_PROXY（由 .env 或 OS 设置）
    2. 无代理（直连）
    """
    proxy_url = (
        _os.environ.get("HTTPS_PROXY")
        or _os.environ.get("https_proxy")
        or _os.environ.get("HTTP_PROXY")
        or _os.environ.get("http_proxy")
        or ""
    )
    if proxy_url:
        proxy_handler = urllib.request.ProxyHandler({
            "http": proxy_url,
            "https": proxy_url,
        })
        logger.debug("[S2] 使用代理: %s", proxy_url)
    else:
        proxy_handler = urllib.request.ProxyHandler({})  # 禁用系统代理，直连

    return urllib.request.build_opener(proxy_handler)


_S2_MAX_RETRIES = 3
_S2_RETRY_BACKOFF = (2, 4, 8)   # 每次重试等待秒数
# 可重试的 HTTP 状态码：限流 / 服务端抖动
_S2_RETRYABLE_CODES = {429, 500, 502, 503, 504}


def _http_get(url: str, headers: dict) -> Optional[dict]:
    """带指数退避重试的 GET 请求（最多 3 次）。"""
    for attempt in range(_S2_MAX_RETRIES):
        opener = _build_opener()
        req = urllib.request.Request(url, headers=headers)
        try:
            with opener.open(req, timeout=15) as resp:
                return _json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code not in _S2_RETRYABLE_CODES or attempt == _S2_MAX_RETRIES - 1:
                logger.warning("S2 GET %s → HTTP %d (attempt %d/%d)",
                               url.split("?")[0], e.code, attempt + 1, _S2_MAX_RETRIES)
                return None
            wait = _S2_RETRY_BACKOFF[attempt]
            logger.warning("S2 GET HTTP %d，%ds 后重试 (%d/%d)…",
                           e.code, wait, attempt + 1, _S2_MAX_RETRIES)
            time.sleep(wait)
        except Exception as e:
            if attempt == _S2_MAX_RETRIES - 1:
                logger.warning("S2 GET failed (attempt %d/%d): %s",
                               attempt + 1, _S2_MAX_RETRIES, e)
                return None
            wait = _S2_RETRY_BACKOFF[attempt]
            logger.warning("S2 GET 网络抖动，%ds 后重试 (%d/%d): %s",
                           wait, attempt + 1, _S2_MAX_RETRIES, e)
            time.sleep(wait)
    return None


def _http_post(url: str, body: dict, headers: dict) -> Optional[list]:
    """带指数退避重试的 POST 请求（最多 3 次）。"""
    data = _json.dumps(body).encode("utf-8")
    for attempt in range(_S2_MAX_RETRIES):
        opener = _build_opener()
        req = urllib.request.Request(
            url, data=data,
            headers={**headers, "Content-Type": "application/json"},
        )
        try:
            with opener.open(req, timeout=30) as resp:
                return _json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code not in _S2_RETRYABLE_CODES or attempt == _S2_MAX_RETRIES - 1:
                logger.warning("S2 POST %s → HTTP %d (attempt %d/%d)",
                               url, e.code, attempt + 1, _S2_MAX_RETRIES)
                return None
            wait = _S2_RETRY_BACKOFF[attempt]
            logger.warning("S2 POST HTTP %d，%ds 后重试 (%d/%d)…",
                           e.code, wait, attempt + 1, _S2_MAX_RETRIES)
            time.sleep(wait)
        except Exception as e:
            if attempt == _S2_MAX_RETRIES - 1:
                logger.warning("S2 POST failed (attempt %d/%d): %s",
                               attempt + 1, _S2_MAX_RETRIES, e)
                return None
            wait = _S2_RETRY_BACKOFF[attempt]
            logger.warning("S2 POST 网络抖动，%ds 后重试 (%d/%d): %s",
                           wait, attempt + 1, _S2_MAX_RETRIES, e)
            time.sleep(wait)
    return None


# ── 数据格式化 ────────────────────────────────────────────────────────────────

def _format_paper_stub(p: dict) -> dict:
    """将 S2 返回的 paper 对象格式化为统一的引用条目。"""
    ext = p.get("externalIds") or {}
    doi = ext.get("DOI") or ext.get("doi")
    pmid = str(ext.get("PubMed") or ext.get("PMID") or "") or None
    s2_id = p.get("paperId") or ""
    venue = p.get("publicationVenue") or {}
    journal = venue.get("name") or ""
    authors_raw = p.get("authors") or []
    author_names = [a.get("name", "") for a in authors_raw[:3] if a.get("name")]
    return {
        "title": p.get("title") or "",
        "year": p.get("year") or 0,
        "doi": doi,
        "pmid": pmid,
        "s2_paper_id": s2_id or None,
        "url": f"https://www.semanticscholar.org/paper/{s2_id}" if s2_id else None,
        "citation_count": p.get("citationCount") or 0,
        "journal": journal,
        "authors": author_names,
    }


# ── Phase 1: 批量查询基本指标 ─────────────────────────────────────────────────

def _batch_query(paper_ids: list[str], headers: dict, batch_size: int = 500) -> dict[str, dict]:
    """批量查询 S2 paper 基本指标，返回 {s2_lookup_id: result} 映射。"""
    results: dict[str, dict] = {}
    url = f"{_S2_BASE}/paper/batch?fields={_BATCH_FIELDS}"

    for i in range(0, len(paper_ids), batch_size):
        chunk = paper_ids[i:i + batch_size]
        logger.info("[S2] 批量查询 %d-%d / %d 篇", i + 1, i + len(chunk), len(paper_ids))
        resp = _http_post(url, {"ids": chunk}, headers)
        if not resp:
            continue
        for item, orig_id in zip(resp, chunk):
            if item and item.get("paperId"):
                results[orig_id] = item
        if i + batch_size < len(paper_ids):
            time.sleep(1.1)  # 批次间延迟

    return results


# ── Phase 2: 逐篇查询引用网络 ─────────────────────────────────────────────────

def _fetch_references(s2_paper_id: str, headers: dict, limit: int = 50) -> list[dict]:
    """查询本文引用的文献列表（出引）。"""
    url = f"{_S2_BASE}/paper/{s2_paper_id}/references?fields={_GRAPH_FIELDS}&limit={limit}"
    data = _http_get(url, headers)
    if not data:
        return []
    return [
        _format_paper_stub(item.get("citedPaper", {}))
        for item in (data.get("data") or [])
        if item.get("citedPaper", {}).get("paperId")
    ]


def _fetch_citations(s2_paper_id: str, headers: dict, limit: int = 50) -> list[dict]:
    """查询引用本文的文献列表（入引）。"""
    url = f"{_S2_BASE}/paper/{s2_paper_id}/citations?fields={_GRAPH_FIELDS}&limit={limit}"
    data = _http_get(url, headers)
    if not data:
        return []
    return [
        _format_paper_stub(item.get("citingPaper", {}))
        for item in (data.get("data") or [])
        if item.get("citingPaper", {}).get("paperId")
    ]


# ── 主入口 ────────────────────────────────────────────────────────────────────

def enrich_papers_with_semantic_scholar(
    papers: list[dict],
    api_key: str = "",
    rate_limit_delay: float = 1.1,
    max_refs_per_paper: int = 50,
    fetch_network: bool = True,
    network_limit: int = 100,
) -> list[dict]:
    """
    用 Semantic Scholar API 富化文献列表。

    Args:
        papers:             文献列表（每个 dict 至少有 doi 或 pmid）
        api_key:            S2 API Key（可选；无则限速 1 req/s；有则 10 req/s）
        rate_limit_delay:   无 API Key 时请求间隔（秒），默认 1.1
        max_refs_per_paper: 每篇文献最多拉取多少条引用/被引
        fetch_network:      是否拉取引用网络（references / citations_in）
        network_limit:      仅当语料库 <= 此值时才拉取引用网络（避免超时）

    Returns:
        原地修改后的 papers 列表
    """
    if not papers:
        return papers

    headers: dict[str, str] = {"Accept": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
        rate_limit_delay = min(rate_limit_delay, 0.15)  # 10 req/s with key

    # ── 构造 S2 查询 ID 列表 ──────────────────────────────────────────────────
    # 优先 DOI，其次 PMID；记录 paper 索引 → lookup_id 的映射
    idx_to_id: dict[int, str] = {}
    for i, p in enumerate(papers):
        doi = (p.get("doi") or "").strip().lstrip("https://doi.org/").lstrip("doi.org/")
        pmid = str(p.get("pmid") or "").strip()
        if doi:
            idx_to_id[i] = f"DOI:{doi}"
        elif pmid:
            idx_to_id[i] = f"PMID:{pmid}"
        else:
            logger.debug("Paper %d: 无 DOI/PMID，跳过 S2 查询", i)

    if not idx_to_id:
        logger.warning("[S2] 所有文献均无 DOI/PMID，跳过 Semantic Scholar 富化")
        return papers

    lookup_ids = list(idx_to_id.values())
    logger.info("[S2] Phase 1: 批量查询 %d 篇文献的基本指标", len(lookup_ids))

    # ── Phase 1: 批量拉取基本指标 ─────────────────────────────────────────────
    batch_results = _batch_query(lookup_ids, headers)
    found = len(batch_results)
    logger.info("[S2] Phase 1 完成: %d / %d 篇匹配", found, len(lookup_ids))

    # 将 Phase 1 结果写回 papers
    for i, lookup_id in idx_to_id.items():
        item = batch_results.get(lookup_id)
        if not item:
            continue
        p = papers[i]
        s2_id = item.get("paperId", "")
        p["citation_count"] = item.get("citationCount") or 0
        p["influential_citation_count"] = item.get("influentialCitationCount") or 0
        p["s2_paper_id"] = s2_id
        p["s2_url"] = f"https://www.semanticscholar.org/paper/{s2_id}" if s2_id else ""
        # S2 作者列表（含 authorId）
        p["s2_authors"] = [
            {"name": a.get("name", ""), "authorId": a.get("authorId", "")}
            for a in (item.get("authors") or [])
        ]
        # 若 S2 提供更完整的期刊名称，可选择性补充（不覆盖已有值）
        venue = (item.get("publicationVenue") or {})
        if venue.get("name") and not p.get("journal"):
            p["journal"] = venue["name"]

    # ── Phase 2: 逐篇拉取引用网络 ─────────────────────────────────────────────
    do_network = fetch_network and len(papers) <= network_limit
    if fetch_network and not do_network:
        logger.info(
            "[S2] Phase 2 跳过：语料库 %d 篇 > network_limit %d（仅保留 citation_count）",
            len(papers), network_limit,
        )

    if do_network:
        # 只处理 Phase 1 成功匹配的文献
        eligible = [(i, p) for i, p in enumerate(papers) if p.get("s2_paper_id")]
        logger.info("[S2] Phase 2: 拉取 %d 篇文献的引用网络", len(eligible))

        for seq, (i, p) in enumerate(eligible, 1):
            s2_id = p["s2_paper_id"]
            logger.debug("[S2] Phase 2 [%d/%d] %s", seq, len(eligible), p.get("title", "")[:50])

            refs = _fetch_references(s2_id, headers, limit=max_refs_per_paper)
            time.sleep(rate_limit_delay)

            cits = _fetch_citations(s2_id, headers, limit=max_refs_per_paper)
            time.sleep(rate_limit_delay)

            p["references"] = refs
            p["citations_in"] = cits

            if seq % 10 == 0:
                logger.info("[S2] Phase 2 进度: %d / %d", seq, len(eligible))

        logger.info("[S2] Phase 2 完成")

    # 确保所有 papers 都有这几个字段（避免下游 KeyError）
    for p in papers:
        p.setdefault("citation_count", 0)
        p.setdefault("influential_citation_count", 0)
        p.setdefault("s2_paper_id", "")
        p.setdefault("s2_url", "")
        p.setdefault("s2_authors", [])
        p.setdefault("references", [])
        p.setdefault("citations_in", [])

    total_cited = sum(p.get("citation_count", 0) for p in papers)
    logger.info(
        "[S2] 富化完成: %d 篇，总引用数 %d，平均 %.1f",
        len(papers), total_cited, total_cited / len(papers) if papers else 0,
    )
    return papers
