"""Research report parser service.

Parses 文献调研报告.md markdown files to extract structured paper data
for building hypergraph visualizations.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

RESULT_DIR = Path(__file__).resolve().parent.parent.parent / "literature_research" / "result"

# Regex patterns for header parsing
RE_TIME_RANGE = re.compile(r'\*\*时间范围\*\*:\s*(\d{4}-\d{2}-\d{2})\s*至\s*(\d{4}-\d{2}-\d{2})')
RE_PAPER_COUNT = re.compile(r'\*\*文献数量\*\*:\s*(\d+)\s*篇')
RE_KEYWORDS = re.compile(r'\*\*检索关键词\*\*:\s*(.+)')
RE_GENERATED_AT = re.compile(r'\*\*生成时间\*\*:\s*(.+)')

# Regex for overview table rows: | 序号 | 标题 | 期刊 | IF | 发表日期 | DOI |
RE_TABLE_ROW = re.compile(r'^\|\s*(\d+)\s*\|(.+?)\|(.+?)\|(.+?)\|(.+?)\|(.+?)\|')

# Regex for DOI in markdown link format
RE_DOI_LINK = re.compile(r'\[([^\]]+)\]\(https?://doi\.org/[^\)]+\)')
RE_DOI_PLAIN = re.compile(r'10\.\d{4,}[^\s\|）)]*')

# Regex for author parsing from detailed sections
RE_AUTHOR_ET_AL_TONGXUN = re.compile(r'^(.+?)\s+et\s+al\.\s*[\(（]通讯[:：]\s*(.+?)[\)）]$')
RE_AUTHOR_ET_AL = re.compile(r'^(.+?)\s+et\s+al\.$')

# Regex for PMID from PubMed URL
RE_PMID = re.compile(r'pubmed\.ncbi\.nlm\.nih\.gov/(\d+)')

# Regex for section number
RE_DETAIL_SECTION = re.compile(r'^###\s+(\d+)\.\s+')

# Regex for 基本信息 fields
RE_KEY_AUTHORS = re.compile(r'\*\*核心作者\*\*:\s*(.+)')
RE_MESH = re.compile(r'\*\*MeSH关键词\*\*:\s*(.+)')
RE_JOURNAL_IF = re.compile(r'\*\*期刊\*\*:\s*(.+?)(?:（IF:\s*([\d.]+)）|$)')
RE_PUB_DATE = re.compile(r'\*\*发表日期\*\*:\s*(\d{4}-\d{2}-\d{2})')
RE_AUTHOR_LINE = re.compile(r'\*\*作者\*\*:\s*(.+)')
RE_DOI_LINE = re.compile(r'\*\*DOI\*\*:\s*(.+)')

# Regex for directory name
RE_DIR_NAME = re.compile(r'^(.+?)调研_(\d{4}-\d{2}-\d{2})至(\d{4}-\d{2}-\d{2})$')


@dataclass
class ParsedPaper:
    index: int
    title: str
    journal: str
    impact_factor: float | None  # None when "暂无数据"
    pub_date: str               # "2026-03-30" or "2026-00-00"
    doi: str
    pmid: str
    first_author: str
    corresponding_author: str | None
    key_authors: list[str] = field(default_factory=list)
    mesh_keywords: list[str] = field(default_factory=list)


@dataclass
class ParsedReport:
    topic: str
    generated_at: str
    time_range_start: str
    time_range_end: str
    data_source: str
    keywords: str
    paper_count: int
    papers: list[ParsedPaper] = field(default_factory=list)
    file_path: str = ""


def list_available_reports() -> list[dict]:
    """Scan the result directory for available research reports."""
    reports = []

    if not RESULT_DIR.exists():
        return reports

    for dir_path in sorted(RESULT_DIR.iterdir()):
        if not dir_path.is_dir():
            continue

        m = RE_DIR_NAME.match(dir_path.name)
        if not m:
            continue

        topic = m.group(1)
        start_date = m.group(2)
        end_date = m.group(3)

        # Find the report .md file
        md_files = list(dir_path.glob("*_文献调研报告_*.md"))
        if not md_files:
            continue

        md_file = md_files[0]

        # Quick-parse header for paper count
        paper_count = 0
        try:
            with open(md_file, "r", encoding="utf-8") as f:
                for line in f:
                    mc = RE_PAPER_COUNT.search(line)
                    if mc:
                        paper_count = int(mc.group(1))
                        break
        except Exception:
            pass

        reports.append({
            "topic": topic,
            "time_range_start": start_date,
            "time_range_end": end_date,
            "paper_count": paper_count,
            "file_path": str(md_file),
            "dir_name": dir_path.name,
        })

    return reports


def _parse_author_string(author_str: str) -> tuple[str, str | None]:
    """Parse author string into (first_author, corresponding_author).

    Patterns:
    - "A et al. (通讯: B)" -> (A, B)
    - "A et al." -> (A, None)
    - "A, B" -> (A, B)
    - "A" -> (A, A)
    """
    author_str = author_str.strip()

    # Pattern 1: "First Author et al. (通讯: Corresponding)"
    m = RE_AUTHOR_ET_AL_TONGXUN.match(author_str)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # Pattern 2: "First Author et al." (no corresponding)
    m = RE_AUTHOR_ET_AL.match(author_str)
    if m:
        return m.group(1).strip(), None

    # Pattern 3: "A, B" (two names, comma-separated)
    if "," in author_str:
        parts = [p.strip() for p in author_str.split(",")]
        if len(parts) == 2 and parts[0] and parts[1]:
            return parts[0], parts[1]
        elif parts:
            return parts[0], None

    # Pattern 4: Single author
    if author_str:
        return author_str, author_str

    return "Unknown", None


def parse_report(file_path: str) -> ParsedReport:
    """Parse a 文献调研报告.md file into structured data."""
    path = Path(file_path)

    # Security: validate path is under RESULT_DIR
    try:
        path.resolve().relative_to(RESULT_DIR.resolve())
    except ValueError:
        raise ValueError(f"File path not within allowed directory: {file_path}")

    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")

    # Phase 1: Header metadata
    report = ParsedReport(
        topic="",
        generated_at="",
        time_range_start="",
        time_range_end="",
        data_source="PubMed",
        keywords="",
        paper_count=0,
        file_path=str(path),
    )

    for line in lines[:15]:
        m = RE_TIME_RANGE.search(line)
        if m:
            report.time_range_start = m.group(1)
            report.time_range_end = m.group(2)
        m = RE_PAPER_COUNT.search(line)
        if m:
            report.paper_count = int(m.group(1))
        m = RE_KEYWORDS.search(line)
        if m:
            report.keywords = m.group(1).strip()
            report.topic = report.keywords
        m = RE_GENERATED_AT.search(line)
        if m:
            report.generated_at = m.group(1).strip()

    # Phase 2: Parse overview table for quick IF / date / DOI
    table_papers: dict[int, dict] = {}
    in_table = False
    header_seen = False

    for line in lines:
        if "| 序号 |" in line:
            in_table = True
            header_seen = False
            continue
        if in_table and line.strip().startswith("|---"):
            header_seen = True
            continue
        if in_table and header_seen:
            m = RE_TABLE_ROW.match(line)
            if m:
                idx = int(m.group(1))
                title = m.group(2).strip().rstrip(".")
                journal = m.group(3).strip()
                if_str = m.group(4).strip()
                date_str = m.group(5).strip()
                doi_cell = m.group(6).strip()

                # Parse IF
                impact_factor = None
                if if_str and if_str != "暂无数据":
                    try:
                        impact_factor = float(if_str)
                    except ValueError:
                        pass

                # Parse DOI from cell
                doi = ""
                doi_m = RE_DOI_LINK.search(doi_cell)
                if doi_m:
                    doi = doi_m.group(1).strip()
                elif not doi:
                    doi_m = RE_DOI_PLAIN.search(doi_cell)
                    if doi_m:
                        doi = doi_m.group(0).strip()

                table_papers[idx] = {
                    "index": idx,
                    "title": title,
                    "journal": journal,
                    "impact_factor": impact_factor,
                    "pub_date": date_str,
                    "doi": doi,
                    "pmid": "",
                    "first_author": "",
                    "corresponding_author": None,
                    "key_authors": [],
                    "mesh_keywords": [],
                }
            elif line.strip() and not line.strip().startswith("|"):
                in_table = False

    # Phase 3: Parse detailed sections for author + PMID
    current_section_idx = 0
    in_basic_info = False

    for line in lines:
        # Detect section header: ### N. Title
        m = RE_DETAIL_SECTION.match(line)
        if m:
            current_section_idx = int(m.group(1))
            in_basic_info = False
            continue

        if "#### 基本信息" in line:
            in_basic_info = True
            continue

        if in_basic_info and current_section_idx > 0 and current_section_idx in table_papers:
            paper = table_papers[current_section_idx]

            # Author line
            m = RE_AUTHOR_LINE.search(line)
            if m:
                author_str = m.group(1).strip()
                first, corresponding = _parse_author_string(author_str)
                paper["first_author"] = first
                paper["corresponding_author"] = corresponding

            # PMID from PubMed line
            m = RE_PMID.search(line)
            if m:
                paper["pmid"] = m.group(1)

            # Key authors
            m = RE_KEY_AUTHORS.search(line)
            if m:
                paper["key_authors"] = [a.strip() for a in m.group(1).split(";")]

            # MeSH keywords
            m = RE_MESH.search(line)
            if m:
                paper["mesh_keywords"] = [k.strip() for k in m.group(1).split(";")]

            # DOI from detail (backup if table parse missed it)
            if not paper["doi"]:
                m = RE_DOI_LINE.search(line)
                if m:
                    doi_str = m.group(1).strip()
                    doi_m = RE_DOI_PLAIN.search(doi_str)
                    if doi_m:
                        paper["doi"] = doi_m.group(0).strip()

            # IF from detail (backup)
            if paper["impact_factor"] is None:
                m = RE_JOURNAL_IF.search(line)
                if m and m.group(2):
                    try:
                        paper["impact_factor"] = float(m.group(2))
                    except ValueError:
                        pass

        # End basic info on next section header or deep analysis
        if in_basic_info and ("####" in line and "基本信息" not in line):
            in_basic_info = False

    # Build ParsedPaper objects
    for idx in sorted(table_papers.keys()):
        p = table_papers[idx]
        report.papers.append(ParsedPaper(
            index=p["index"],
            title=p["title"],
            journal=p["journal"],
            impact_factor=p["impact_factor"],
            pub_date=p["pub_date"],
            doi=p["doi"],
            pmid=p["pmid"],
            first_author=p["first_author"] or "Unknown",
            corresponding_author=p["corresponding_author"],
            key_authors=p.get("key_authors", []),
            mesh_keywords=p.get("mesh_keywords", []),
        ))

    return report
