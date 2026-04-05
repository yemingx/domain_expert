"""
后端功能测试套件

运行方式：
    cd backend
    python -m pytest tests/ -v

或者直接运行本文件做快速验证：
    cd backend
    python tests/test_modules.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── 路径设置 ──────────────────────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).parent.parent
LR_SCRIPT_DIR = BACKEND_DIR / "literature_research" / "scripts"

sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(LR_SCRIPT_DIR))
sys.path.insert(0, str(BACKEND_DIR / "literature_research"))


# ══════════════════════════════════════════════════════════════════════════════
# 1. PDF 下载模块测试
# ══════════════════════════════════════════════════════════════════════════════

class TestPdfDownload(unittest.TestCase):

    def setUp(self):
        from download_pdfs import _clean_doi, _safe_filename, _is_valid_pdf
        self._clean_doi = _clean_doi
        self._safe_filename = _safe_filename
        self._is_valid_pdf = _is_valid_pdf

    def test_clean_doi(self):
        self.assertEqual(
            self._clean_doi("https://doi.org/10.1038/s41586-021-03819-2"),
            "10.1038/s41586-021-03819-2",
        )
        self.assertEqual(
            self._clean_doi("  10.1016/j.cell.2021.01.001  "),
            "10.1016/j.cell.2021.01.001",
        )

    def test_safe_filename(self):
        name = self._safe_filename("10.1038/test", "", "")
        self.assertTrue(name.endswith(".pdf"))
        self.assertNotIn("/", name)

    def test_is_valid_pdf(self):
        self.assertTrue(self._is_valid_pdf(b"%PDF" + b"x" * 5000))
        self.assertFalse(self._is_valid_pdf(b"<html>not a pdf</html>"))
        self.assertFalse(self._is_valid_pdf(b"%PDF" + b"x" * 100))  # too small

    def test_publisher_direct_urls(self):
        from download_pdfs import _try_publisher_direct
        urls = _try_publisher_direct("10.1371/journal.pone.0123456")
        self.assertTrue(any("plos" in u.lower() for u in urls))

        urls_biorxiv = _try_publisher_direct("10.1101/2021.01.01.123456")
        self.assertTrue(any("biorxiv" in u for u in urls_biorxiv))

    @patch("download_pdfs.requests.get")
    def test_unpaywall_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "best_oa_location": {"url_for_pdf": "https://example.com/paper.pdf"}
        }
        mock_get.return_value = mock_resp
        from download_pdfs import _try_unpaywall
        url = _try_unpaywall("10.1038/test")
        self.assertEqual(url, "https://example.com/paper.pdf")

    @patch("download_pdfs.requests.get")
    def test_unpaywall_not_oa(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"best_oa_location": None, "oa_locations": []}
        mock_get.return_value = mock_resp
        from download_pdfs import _try_unpaywall
        url = _try_unpaywall("10.1016/paywalled")
        self.assertIsNone(url)

    @patch("download_pdfs.requests.get")
    def test_pmc_lookup(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "linksets": [{
                "linksetdbs": [{"dbto": "pmc", "links": [12345678]}]
            }]
        }
        mock_get.return_value = mock_resp
        from download_pdfs import _try_pmc
        url = _try_pmc("38000000")
        self.assertIsNotNone(url)
        self.assertIn("PMC12345678", url)

    def test_download_single_paper_not_available(self):
        """Papers with no DOI/PMID should return not_available gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from download_pdfs import download_single_paper_pdf
            # Mock all external calls to return None
            with patch("download_pdfs._try_unpaywall", return_value=None), \
                 patch("download_pdfs._try_pmc", return_value=None), \
                 patch("download_pdfs._try_europe_pmc", return_value=None), \
                 patch("download_pdfs._try_semantic_scholar", return_value=None), \
                 patch("download_pdfs._download_url", return_value=None):
                result = download_single_paper_pdf("", "", "Test Paper", tmpdir, delay=0)
                self.assertEqual(result["status"], "not_available")
                self.assertIsNone(result["pdf_path"])

    def test_download_single_paper_success(self):
        """Simulate a successful PDF download via Unpaywall."""
        fake_pdf = b"%PDF-1.4" + b"\x00" * 6000
        with tempfile.TemporaryDirectory() as tmpdir:
            from download_pdfs import download_single_paper_pdf
            with patch("download_pdfs._try_unpaywall", return_value="https://fake.com/paper.pdf"), \
                 patch("download_pdfs._download_url", return_value=fake_pdf):
                result = download_single_paper_pdf(
                    "10.1038/test", "12345", "Test Paper", tmpdir, delay=0
                )
                self.assertEqual(result["status"], "success")
                self.assertIsNotNone(result["pdf_path"])
                self.assertTrue(Path(result["pdf_path"]).exists())

    def test_batch_download(self):
        """batch download returns one result per paper."""
        fake_pdf = b"%PDF-1.4" + b"\x00" * 6000
        papers = [
            {"doi": "10.1038/s41586-001", "pmid": "111", "title": "Paper A"},
            {"doi": "10.1038/s41586-002", "pmid": "222", "title": "Paper B"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            from download_pdfs import download_papers_pdf
            with patch("download_pdfs._try_unpaywall", return_value="https://fake.com/p.pdf"), \
                 patch("download_pdfs._download_url", return_value=fake_pdf):
                results = download_papers_pdf(papers, tmpdir, delay=0)
                self.assertEqual(len(results), 2)
                self.assertTrue(all(r["status"] == "success" for r in results))


# ══════════════════════════════════════════════════════════════════════════════
# 2. 向量库 topic 过滤测试
# ══════════════════════════════════════════════════════════════════════════════

class TestVectorStoreTopic(unittest.TestCase):

    def setUp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.tmpdir = tmpdir
        # Create a fresh temp dir that persists for this test
        import tempfile as _t
        self._td = _t.TemporaryDirectory()
        self.tmpdir = self._td.name

        # Patch settings to use temp dir
        with patch("app.services.vector_store.settings") as mock_settings:
            mock_settings.vector_db_path = self.tmpdir
            from app.services.vector_store import VectorStoreService
            self.vs = VectorStoreService.__new__(VectorStoreService)
            self.vs.db_path = os.path.join(self.tmpdir, "test.db")
            self.vs._init_db()

    def tearDown(self):
        self._td.cleanup()

    def _add_test_chunks(self):
        """Add test chunks for two different topics."""
        self.vs.add_chunks(
            [{"content": "CRISPR gene editing breakthrough 2023", "level": "section", "section_type": "abstract", "page_start": 1, "page_end": 1}],
            paper_id="paper_crispr_1",
            paper_metadata={"title": "CRISPR Paper 1", "year": 2023},
            topic="CRISPR",
        )
        self.vs.add_chunks(
            [{"content": "Prenatal diagnosis noninvasive fetal DNA", "level": "section", "section_type": "abstract", "page_start": 1, "page_end": 1}],
            paper_id="paper_nipd_1",
            paper_metadata={"title": "NIPD Paper 1", "year": 2022},
            topic="NIPD",
        )
        self.vs.add_chunks(
            [{"content": "organoid culture 3D tissue", "level": "section", "section_type": "abstract", "page_start": 1, "page_end": 1}],
            paper_id="paper_organoid_1",
            paper_metadata={"title": "Organoid Paper 1", "year": 2024},
            topic="Organoid",
        )

    def test_add_and_query_with_topic_filter(self):
        self._add_test_chunks()
        # Query without filter — should return all
        all_results = self.vs.query("gene editing", n_results=10)
        self.assertGreater(len(all_results), 0)

        # Query with topic filter
        crispr_results = self.vs.query("CRISPR gene editing", n_results=10,
                                       where_filter={"topic": "CRISPR"})
        self.assertTrue(all(r.get("topic") == "CRISPR" for r in crispr_results))

    def test_list_topics(self):
        self._add_test_chunks()
        topics = self.vs.list_topics()
        topic_names = [t["topic"] for t in topics]
        self.assertIn("CRISPR", topic_names)
        self.assertIn("NIPD", topic_names)
        self.assertIn("Organoid", topic_names)

    def test_multi_topic_filter(self):
        self._add_test_chunks()
        results = self.vs.query("paper", n_results=20,
                                where_filter={"topics": ["CRISPR", "NIPD"]})
        for r in results:
            self.assertIn(r.get("topic"), ["CRISPR", "NIPD"])

    def test_delete_by_topic(self):
        self._add_test_chunks()
        deleted = self.vs.delete_by_topic("CRISPR")
        self.assertGreater(deleted, 0)
        topics_after = [t["topic"] for t in self.vs.list_topics()]
        self.assertNotIn("CRISPR", topics_after)

    def test_topic_persists_after_upsert(self):
        """Upserting the same chunk should preserve topic."""
        self._add_test_chunks()
        # Re-add same chunk
        self.vs.add_chunks(
            [{"content": "CRISPR gene editing updated content", "level": "section", "section_type": "abstract", "page_start": 1, "page_end": 1}],
            paper_id="paper_crispr_1",
            paper_metadata={"title": "CRISPR Paper 1 Updated", "year": 2023},
            topic="CRISPR",
        )
        results = self.vs.query("CRISPR", n_results=5, where_filter={"topic": "CRISPR"})
        self.assertTrue(len(results) > 0)


# ══════════════════════════════════════════════════════════════════════════════
# 3. fetch_papers 模块测试
# ══════════════════════════════════════════════════════════════════════════════

class TestFetchPapers(unittest.TestCase):

    def test_build_query_default(self):
        from fetch_papers import build_query
        q = build_query("CRISPR", 30)
        self.assertIn("CRISPR", q)

    def test_build_query_custom(self):
        from fetch_papers import build_query
        custom = "NIPD[Title/Abstract] AND 2024[Date]"
        q = build_query("NIPD", 60, custom_query=custom)
        self.assertEqual(q, custom)

    def test_parse_article_skips_review(self):
        import xml.etree.ElementTree as ET
        from fetch_papers import _parse_article
        xml_str = """<PubmedArticle>
          <MedlineCitation>
            <PMID>12345</PMID>
            <Article>
              <ArticleTitle>A review of CRISPR techniques</ArticleTitle>
              <PublicationTypeList>
                <PublicationType>Review</PublicationType>
              </PublicationTypeList>
              <Abstract><AbstractText>This is a review.</AbstractText></Abstract>
              <Journal><Title>Nature Reviews</Title></Journal>
              <AuthorList></AuthorList>
            </Article>
          </MedlineCitation>
          <PubmedData>
            <ArticleIdList>
              <ArticleId IdType="doi">10.1038/test</ArticleId>
            </ArticleIdList>
          </PubmedData>
        </PubmedArticle>"""
        root = ET.fromstring(xml_str)
        paper = _parse_article(root, {})
        self.assertIsNone(paper)  # Should be filtered out (Review type)

    def test_parse_journal_if(self):
        from fetch_papers import _get_journal_if
        # With empty database, should return "暂无数据"
        result = _get_journal_if("Nature", {})
        self.assertEqual(result, "暂无数据")

        # With data
        if_data = {"Nature": "57.9", "CELL": "64.5"}
        result = _get_journal_if("Nature", if_data)
        self.assertEqual(result, "57.9")

        # Case-insensitive
        result = _get_journal_if("nature", if_data)
        self.assertEqual(result, "57.9")

    @patch("fetch_papers.requests.get")
    def test_fetch_papers_empty_result(self, mock_get):
        """When PubMed returns no IDs, fetch_papers returns []."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"esearchresult": {"idlist": [], "count": "0"}}
        mock_get.return_value = mock_resp

        from fetch_papers import fetch_papers
        result = fetch_papers("TEST", "TEST[Title]", days=7, max_papers=5)
        self.assertEqual(result, [])


# ══════════════════════════════════════════════════════════════════════════════
# 4. literature_research_service 测试
# ══════════════════════════════════════════════════════════════════════════════

class TestResearchService(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        with patch("app.services.literature_research_service.RESEARCH_DIR",
                   Path(self._td.name)):
            from app.services.literature_research_service import LiteratureResearchService
            self.service = LiteratureResearchService()

    def tearDown(self):
        self._td.cleanup()

    def test_create_job(self):
        job = self.service.create_job("CRISPR", "CRISPR[Title/Abstract]", max_papers=5)
        self.assertEqual(job.status, "pending")
        self.assertEqual(job.topic, "CRISPR")
        self.assertNotEqual(job.job_id, "")

    def test_get_job(self):
        job = self.service.create_job("NIPD", "NIPD[Title]", max_papers=3)
        retrieved = self.service.get_job(job.job_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.job_id, job.job_id)

    def test_delete_pending_job(self):
        job = self.service.create_job("Test", "Test[Title]")
        deleted = self.service.delete_job(job.job_id)
        self.assertTrue(deleted)
        self.assertIsNone(self.service.get_job(job.job_id))

    def test_cannot_delete_running_job(self):
        job = self.service.create_job("Test", "Test[Title]")
        job.status = "running"
        with self.assertRaises(ValueError):
            self.service.delete_job(job.job_id)

    def test_import_to_kb_with_topic(self):
        """Verify import tags chunks with job topic."""
        job = self.service.create_job("CRISPR", "CRISPR[Title]")
        job.status = "completed"
        job.papers = [
            {
                "pmid": "99999",
                "doi": "10.1038/test",
                "title": "CRISPR paper",
                "abstract": "This is a CRISPR abstract.",
                "authors_meta": [{"name": "Alice Smith"}],
                "affiliations": ["MIT"],
                "year": 2023,
                "journal": "Nature",
            }
        ]

        mock_vs = MagicMock()
        mock_vs.add_chunks.return_value = ["chunk_001", "chunk_002", "chunk_003"]

        count = self.service.import_to_knowledge_base(job.job_id, mock_vs)

        self.assertGreater(count, 0)
        # Verify topic was passed
        call_kwargs = mock_vs.add_chunks.call_args
        self.assertEqual(call_kwargs.kwargs.get("topic") or call_kwargs[1].get("topic"), "CRISPR")

    def test_paper_to_chunks_structure(self):
        paper = {
            "pmid": "11111",
            "title": "Test paper title",
            "abstract": "This is the abstract text.",
            "authors_meta": [{"name": "Bob"}],
            "affiliations": ["Harvard"],
            "first_author": "Bob",
            "corresponding_authors": ["Bob"],
        }
        chunks = self.service._paper_to_chunks(paper)
        self.assertGreater(len(chunks), 0)
        section_types = [c.get("section_type") for c in chunks]
        self.assertIn("title", section_types)
        self.assertIn("abstract", section_types)


# ══════════════════════════════════════════════════════════════════════════════
# 5. 报告生成模块测试
# ══════════════════════════════════════════════════════════════════════════════

class TestReportGeneration(unittest.TestCase):

    SAMPLE_PAPERS = [
        {
            "title": "CRISPR-Cas9 enables precise genome editing",
            "title_cn": "CRISPR-Cas9实现精确基因组编辑",
            "abstract": "We demonstrate efficient and precise genome editing using CRISPR-Cas9 in human cells.",
            "abstract_cn": "我们展示了在人类细胞中使用CRISPR-Cas9进行高效精确基因组编辑。",
            "journal": "Nature Biotechnology",
            "journal_if": "46.9",
            "publication_date": "2024-01-15",
            "year": 2024,
            "author_display": "Zhang F et al.",
            "doi": "10.1038/nbt.test",
            "pmid": "12345678",
            "research_team": "Broad Institute",
            "technical_route": "利用CRISPR-Cas9核酸酶切割靶DNA，通过同源重组修复引入精确突变。",
            "advantages": "特异性高，脱靶率低，操作简便，成本低廉。",
            "limitations": "大片段插入效率较低，在分裂细胞中效果更好。",
            "technical_barriers": "递送系统、免疫反应、脱靶效应的检测。",
            "feasibility": "已进入临床试验阶段，治疗遗传性血液病。",
            "generalization": "可扩展至多种细胞类型和疾病模型。",
        }
    ]

    def test_generate_markdown(self):
        from generate_report import generate_markdown_report
        md = generate_markdown_report(
            self.SAMPLE_PAPERS, "基因编辑", "2024-01-01 至 2024-04-04", 90, "CRISPR"
        )
        self.assertIn("基因编辑", md)
        self.assertIn("CRISPR-Cas9", md)
        self.assertIn("技术路线", md)
        self.assertIn("10.1038/nbt.test", md)

    def test_generate_html(self):
        from generate_html import generate_html_report
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "report.html")
            generate_html_report(self.SAMPLE_PAPERS, out, "基因编辑", "2024-01-01 至 2024-04-04", 90)
            self.assertTrue(os.path.exists(out))
            content = Path(out).read_text(encoding="utf-8")
            self.assertIn("<!DOCTYPE html>", content)
            self.assertIn("CRISPR", content)

    def test_generate_html_ppt(self):
        from generate_html_ppt import generate_ppt_html_report
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "report_ppt.html")
            generate_ppt_html_report(self.SAMPLE_PAPERS, out, "基因编辑", "2024-01-01 至 2024-04-04", 90)
            self.assertTrue(os.path.exists(out))
            content = Path(out).read_text(encoding="utf-8")
            self.assertIn("slide", content)
            self.assertIn("1280px", content)

    def test_generate_markdown_saves_file(self):
        from generate_report import generate_markdown_report, save_markdown
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "report.md")
            content = generate_markdown_report(
                self.SAMPLE_PAPERS, "Test", "2024-01-01 至 2024-04-04", 90
            )
            save_markdown(content, out)
            self.assertTrue(os.path.exists(out))


# ══════════════════════════════════════════════════════════════════════════════
# 6. Hypergraph 构建测试
# ══════════════════════════════════════════════════════════════════════════════

class TestHypergraphBuild(unittest.TestCase):

    SAMPLE_PAPERS = [
        {
            "pmid": "1001",
            "title": "Paper Alpha",
            "year": 2022,
            "journal": "Nature",
            "authors": [
                {"name": "Alice Smith", "affiliation": "MIT", "is_first_author": True, "is_corresponding_author": True},
                {"name": "Bob Jones", "affiliation": "MIT", "is_first_author": False, "is_corresponding_author": False},
            ],
            "citation_count": 50,
        },
        {
            "pmid": "1002",
            "title": "Paper Beta",
            "year": 2023,
            "journal": "Cell",
            "authors": [
                {"name": "Charlie Brown", "affiliation": "Harvard", "is_first_author": True, "is_corresponding_author": False},
                {"name": "Alice Smith", "affiliation": "MIT", "is_first_author": False, "is_corresponding_author": True},
            ],
            "citation_count": 30,
        },
    ]

    def _get_build_fn(self):
        """Import the hypergraph builder from endpoints."""
        from app.api.endpoints import _build_hypergraph_from_papers
        return _build_hypergraph_from_papers

    def test_nodes_built_correctly(self):
        fn = self._get_build_fn()
        hg = fn(self.SAMPLE_PAPERS)
        self.assertIn("nodes", hg)
        self.assertIn("hyperedges", hg)
        # Authors
        author_names = [a["name"] for a in hg["nodes"]["authors"]]
        self.assertIn("Alice Smith", author_names)
        self.assertIn("Bob Jones", author_names)

    def test_coauthor_tracking(self):
        fn = self._get_build_fn()
        hg = fn(self.SAMPLE_PAPERS)
        # Alice Smith appears in both papers — should have coauthors
        alice = next((a for a in hg["nodes"]["authors"] if a["name"] == "Alice Smith"), None)
        self.assertIsNotNone(alice)
        self.assertGreater(len(alice.get("coauthors", [])), 0)

    def test_institutions_extracted(self):
        fn = self._get_build_fn()
        hg = fn(self.SAMPLE_PAPERS)
        inst_names = [i["name"] for i in hg["nodes"]["institutions"]]
        self.assertTrue(any("MIT" in n for n in inst_names))

    def test_hyperedges_contain_coauthorship(self):
        fn = self._get_build_fn()
        hg = fn(self.SAMPLE_PAPERS)
        types = [e["type"] for e in hg["hyperedges"]]
        self.assertIn("coauthorship", types)
        self.assertIn("authorship", types)
        self.assertIn("temporal", types)


# ══════════════════════════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════════════════════════

def run_all_tests():
    """Run all tests and print a summary."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_classes = [
        TestPdfDownload,
        TestVectorStoreTopic,
        TestFetchPapers,
        TestResearchService,
        TestReportGeneration,
        TestHypergraphBuild,
    ]

    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
