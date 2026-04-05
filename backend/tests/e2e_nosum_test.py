"""
E2E test for Literature Research feature - NOSUM variant.
Tests that removed fields are NOT present and required fields ARE present.

Checks:
  - "研究团队" does NOT appear in any output
  - "综合总结" slide does NOT appear in HTML PPT
  - "总体行业分析" section does NOT appear in Markdown
  - "发展建议" section does NOT appear in Markdown
  - Translation (中文翻译) IS present and non-empty
  - 6-dimension analysis IS present and non-empty
"""

import time
import json
import zipfile
import io
import sys
import os
import urllib.request
from playwright.sync_api import sync_playwright, Page

# Force UTF-8 output on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FRONTEND_URL = "http://localhost:5173"
BACKEND_URL = "http://localhost:8000"
SCREENSHOT_DIR = r"C:\Users\xieyeming1\Downloads\git_repo\domain_expert\backend\tests\e2e_screenshots\nosum"
RESULT_DIR = r"C:\Users\xieyeming1\Downloads\git_repo\domain_expert\backend\literature_research\result"

TOPIC = "FRONTEND_NOSUM"
QUERY = '"noninvasive prenatal diagnosis"[Title/Abstract] AND "2026/01/01 00:00":"3000/01/01 05:00"[Date - Entry] AND "journal article"[Publication Type]'
MAX_PAPERS = 1

POLL_INTERVAL_SECONDS = 10
MAX_WAIT_SECONDS = 300  # 5 minutes

# ── Result tracking ─────────────────────────────────────────────────────────
results = {
    "screenshots": [],
    "errors": [],
    "warnings": [],
    "job_id": None,
    "submission_success": False,
    "job_completed": False,
    "papers_found": False,
    "translation_present": False,
    "analysis_present": False,
    # New checks for removed fields
    "no_research_team": None,   # True = passed (field absent)
    "no_summary_slide": None,   # True = passed (slide absent)
    "no_industry_analysis": None,  # True = passed (section absent)
    "no_development_advice": None, # True = passed (section absent)
    "details": {},
}


def screenshot(page: Page, name: str) -> str:
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    page.screenshot(path=path, full_page=True)
    results["screenshots"].append(path)
    print(f"  [screenshot] Saved: {path}")
    return path


def log(msg: str):
    print(f"  {msg}")


def check_file_for_removed_fields(content: str, filename: str, file_type: str):
    """Check file content for presence/absence of required/removed fields."""
    log(f"\n  --- Checking {file_type}: {filename} ---")
    length = len(content)
    log(f"  File size: {length} chars")

    # ── Check: 研究团队 should NOT appear ──
    if "研究团队" in content:
        results["no_research_team"] = False
        # Find context
        idx = content.find("研究团队")
        ctx = content[max(0, idx-30):idx+60].replace('\n', ' ')
        results["errors"].append(
            f"[{filename}] FAIL: '研究团队' found at pos {idx}: ...{ctx}..."
        )
        log(f"  FAIL: '研究团队' found in {filename}")
    else:
        if results["no_research_team"] is None:
            results["no_research_team"] = True
        log(f"  PASS: '研究团队' not found in {filename}")

    # ── Check: 综合总结 should NOT appear in HTML PPT ──
    if file_type == "HTML_PPT":
        if "综合总结" in content:
            results["no_summary_slide"] = False
            idx = content.find("综合总结")
            ctx = content[max(0, idx-30):idx+60].replace('\n', ' ')
            results["errors"].append(
                f"[{filename}] FAIL: '综合总结' slide found at pos {idx}: ...{ctx}..."
            )
            log(f"  FAIL: '综合总结' found in HTML PPT {filename}")
        else:
            if results["no_summary_slide"] is None:
                results["no_summary_slide"] = True
            log(f"  PASS: '综合总结' not found in HTML PPT {filename}")

    # ── Check: 总体行业分析 should NOT appear in Markdown ──
    if file_type == "MARKDOWN":
        if "总体行业分析" in content:
            results["no_industry_analysis"] = False
            idx = content.find("总体行业分析")
            ctx = content[max(0, idx-30):idx+80].replace('\n', ' ')
            results["errors"].append(
                f"[{filename}] FAIL: '总体行业分析' section found at pos {idx}: ...{ctx}..."
            )
            log(f"  FAIL: '总体行业分析' found in Markdown {filename}")
        else:
            if results["no_industry_analysis"] is None:
                results["no_industry_analysis"] = True
            log(f"  PASS: '总体行业分析' not found in Markdown {filename}")

        # ── Check: 发展建议 should NOT appear in Markdown ──
        if "发展建议" in content:
            results["no_development_advice"] = False
            idx = content.find("发展建议")
            ctx = content[max(0, idx-30):idx+80].replace('\n', ' ')
            results["errors"].append(
                f"[{filename}] FAIL: '发展建议' section found at pos {idx}: ...{ctx}..."
            )
            log(f"  FAIL: '发展建议' found in Markdown {filename}")
        else:
            if results["no_development_advice"] is None:
                results["no_development_advice"] = True
            log(f"  PASS: '发展建议' not found in Markdown {filename}")

        # ── Check: Translation present ──
        has_trans_section = "中文翻译" in content or "中文标题" in content or "标题翻译" in content
        has_nonempty_trans = "暂无翻译" not in content
        log(f"  Translation section present: {has_trans_section}, non-empty: {has_nonempty_trans}")
        if has_trans_section and has_nonempty_trans:
            results["translation_present"] = True
        elif has_trans_section and not has_nonempty_trans:
            results["errors"].append(f"[{filename}] Translation section present but shows '暂无翻译'")
        elif not has_trans_section:
            results["warnings"].append(f"[{filename}] No translation section found (中文翻译/中文标题)")

        # ── Check: 6-dimension analysis ──
        dim_fields = ["技术路线", "技术优势", "技术不足", "技术壁垒", "应用场景", "未来方向"]
        found_dims = [d for d in dim_fields if d in content]
        bad_dims = [
            d for d in found_dims
            if (f"**{d}**: 待分析" in content or f"**{d}**: 分析失败" in content
                or f"{d}: 待分析" in content or f"{d}: 分析失败" in content)
        ]
        log(f"  Dimension fields found: {found_dims}")
        if bad_dims:
            log(f"  Bad (not analyzed) dims: {bad_dims}")
            results["warnings"].append(f"[{filename}] Some dims not analyzed: {bad_dims}")

        if len(found_dims) >= 4:
            good_dims = [d for d in found_dims if d not in bad_dims]
            if len(good_dims) >= 3:
                results["analysis_present"] = True
                log(f"  PASS: Analysis present ({len(good_dims)} valid dims)")
            else:
                results["warnings"].append(f"[{filename}] Only {len(good_dims)} valid analysis dims")
        else:
            results["warnings"].append(f"[{filename}] Only {len(found_dims)} dim fields found in markdown")

    # ── Check in all file types: 研究团队 is the critical check ──


def check_result_dir_files(result_subdir: str):
    """Check files in the local result directory."""
    log(f"\n  Checking result directory: {result_subdir}")
    if not os.path.exists(result_subdir):
        results["errors"].append(f"Result directory not found: {result_subdir}")
        log(f"  ERROR: Directory does not exist: {result_subdir}")
        return

    files = os.listdir(result_subdir)
    log(f"  Files: {files}")
    results["details"]["result_dir_files"] = files

    for fname in files:
        fpath = os.path.join(result_subdir, fname)
        ext = fname.lower().split('.')[-1] if '.' in fname else ''

        if ext in ('md',):
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            if '_原始NCBI_' in fname:
                check_file_for_removed_fields(content, fname, "MARKDOWN_RAW")
            else:
                check_file_for_removed_fields(content, fname, "MARKDOWN")

        elif ext in ('html',):
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            if '_ppt' in fname:
                check_file_for_removed_fields(content, fname, "HTML_PPT")
            else:
                check_file_for_removed_fields(content, fname, "HTML_READING")


def run_test():
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # ── Step 1: Open frontend ──────────────────────────────────────────────
        print("\n[Step 1] Opening frontend at", FRONTEND_URL)
        page.goto(FRONTEND_URL, timeout=20000)
        page.wait_for_load_state("networkidle", timeout=20000)
        screenshot(page, "01_homepage")
        title = page.title()
        log(f"Page title: {title}")

        # ── Step 2: Navigate to Research section ───────────────────────────────
        print("\n[Step 2] Navigating to 'Research' section")
        research_menu = page.get_by_role("menuitem", name="Research")
        research_menu.click()
        page.wait_for_timeout(1500)
        screenshot(page, "02_research_section")
        log("Clicked 'Research' menu item")

        # Verify we're on the Literature Research page
        try:
            heading = page.locator("text=Literature Research").first
            heading.wait_for(timeout=8000)
            log("Literature Research section loaded")
        except Exception:
            # Try alternate text
            try:
                heading = page.locator("text=文献调研").first
                heading.wait_for(timeout=5000)
                log("Literature Research section loaded (Chinese text)")
            except Exception as e:
                results["errors"].append(f"Could not confirm Research section loaded: {e}")
                log(f"Warning: Could not confirm Research section: {e}")

        # ── Step 3: Fill in the form ───────────────────────────────────────────
        print("\n[Step 3] Filling in research form")

        # Topic field
        try:
            topic_input = page.locator('input[placeholder*="NIPD"]').first
            topic_input.wait_for(timeout=5000)
            topic_input.click()
            topic_input.select_text()
            topic_input.fill(TOPIC)
            log(f"Set Topic: {TOPIC}")
        except Exception as e:
            # Fallback: try first text input
            try:
                topic_input = page.locator('input[type="text"]').first
                topic_input.click()
                topic_input.select_text()
                topic_input.fill(TOPIC)
                log(f"Set Topic (fallback): {TOPIC}")
            except Exception as e2:
                results["errors"].append(f"Could not fill topic: {e2}")
                log(f"ERROR filling topic: {e2}")

        # Query textarea
        try:
            query_textarea = page.locator("textarea").first
            query_textarea.wait_for(timeout=5000)
            query_textarea.click()
            # Triple-click to select all text in textarea
            query_textarea.triple_click()
            page.keyboard.press("Control+a")
            query_textarea.fill(QUERY)
            log(f"Set Query: {QUERY[:70]}...")
        except Exception as e:
            results["errors"].append(f"Could not fill query: {e}")
            log(f"ERROR filling query: {e}")

        # Max papers input
        try:
            max_papers_input = page.locator('input[role="spinbutton"]').first
            max_papers_input.wait_for(timeout=5000)
            max_papers_input.click()
            max_papers_input.triple_click()
            max_papers_input.fill(str(MAX_PAPERS))
            log(f"Set Max Papers: {MAX_PAPERS}")
        except Exception as e:
            results["errors"].append(f"Could not set max papers: {e}")
            log(f"ERROR setting max papers: {e}")

        screenshot(page, "03_form_filled")

        # ── Step 4: Submit the form ────────────────────────────────────────────
        print("\n[Step 4] Submitting research job")
        try:
            run_button = page.get_by_role("button", name="Run Research")
            run_button.wait_for(timeout=5000)
            run_button.click()
            log("Clicked 'Run Research' button")
        except Exception as e:
            # Try alternate button text
            try:
                run_button = page.get_by_role("button", name="运行研究")
                run_button.click()
                log("Clicked '运行研究' button (Chinese)")
            except Exception as e2:
                results["errors"].append(f"Could not click run button: {e2}")
                log(f"ERROR clicking run button: {e2}")

        # Wait for success/error toast
        try:
            success_msg = page.locator(".ant-message-success").first
            success_msg.wait_for(timeout=15000)
            msg_text = success_msg.inner_text()
            log(f"Success toast: {msg_text}")
            results["submission_success"] = True
            if "Research job started:" in msg_text or "job_id" in msg_text.lower():
                parts = msg_text.split(":")
                if len(parts) > 1:
                    results["job_id"] = parts[-1].strip()
                    log(f"Job ID from toast: {results['job_id']}")
        except Exception:
            # Check for error toast
            try:
                err_msg = page.locator(".ant-message-error").first
                err_text = err_msg.inner_text()
                results["errors"].append(f"Submission error toast: {err_text}")
                log(f"ERROR toast seen: {err_text}")
            except Exception:
                pass
            # Maybe it succeeded but toast disappeared - check via table
            try:
                row = page.locator("tr", has_text=TOPIC).first
                row.wait_for(timeout=10000)
                log("Job row appeared in table - assuming submission success")
                results["submission_success"] = True
            except Exception as e3:
                results["errors"].append(f"No success confirmation found: {str(e3)[:100]}")
                log(f"Could not confirm submission: {e3}")

        screenshot(page, "04_after_submit")

        # ── Step 5: Poll job status ────────────────────────────────────────────
        print(f"\n[Step 5] Polling job status every {POLL_INTERVAL_SECONDS}s (max {MAX_WAIT_SECONDS}s)")
        start_time = time.time()
        last_status = None
        poll_count = 0

        while time.time() - start_time < MAX_WAIT_SECONDS:
            time.sleep(POLL_INTERVAL_SECONDS)
            poll_count += 1
            elapsed = int(time.time() - start_time)

            try:
                target_row = page.locator("tr", has_text=TOPIC).first
                target_row.wait_for(timeout=5000)
                row_text = target_row.inner_text()

                if "COMPLETED" in row_text.upper() or "completed" in row_text.lower():
                    log(f"[poll {poll_count}] Status: COMPLETED ({elapsed}s elapsed)")
                    last_status = "completed"
                    results["job_completed"] = True
                    break
                elif "FAILED" in row_text.upper() or "failed" in row_text.lower():
                    log(f"[poll {poll_count}] Status: FAILED ({elapsed}s elapsed)")
                    last_status = "failed"
                    results["errors"].append("Job FAILED in UI")
                    break
                elif "RUNNING" in row_text.upper() or "running" in row_text.lower():
                    log(f"[poll {poll_count}] Status: RUNNING ({elapsed}s elapsed)")
                    last_status = "running"
                elif "PENDING" in row_text.upper() or "pending" in row_text.lower():
                    log(f"[poll {poll_count}] Status: PENDING ({elapsed}s elapsed)")
                    last_status = "pending"
                else:
                    log(f"[poll {poll_count}] Row: {row_text[:100]} ({elapsed}s elapsed)")
                    last_status = "unknown"
            except Exception as e:
                log(f"[poll {poll_count}] Could not find '{TOPIC}' row: {str(e)[:60]} ({elapsed}s elapsed)")

        screenshot(page, "05_after_polling")
        log(f"Polling ended. Last status: {last_status}, elapsed: {int(time.time()-start_time)}s")

        if not results["job_completed"]:
            results["errors"].append(
                f"Job did not complete within {MAX_WAIT_SECONDS}s. Last status: {last_status}"
            )

        # ── Step 6: Open job details modal ─────────────────────────────────────
        print("\n[Step 6] Opening job details modal")
        try:
            target_row = page.locator("tr", has_text=TOPIC).first
            target_row.wait_for(timeout=5000)
            details_btn = target_row.get_by_role("button", name="Details")
            details_btn.click()
            page.wait_for_timeout(1500)
            screenshot(page, "06_details_modal")

            modal = page.locator(".ant-modal-content")
            modal.wait_for(timeout=8000)
            modal_text = modal.inner_text()
            log(f"Modal content ({len(modal_text)} chars): {modal_text[:300]}")
            results["details"]["modal_text_preview"] = modal_text[:500]

            # Check modal for removed fields
            if "研究团队" in modal_text:
                results["errors"].append(f"FAIL: '研究团队' found in details modal")
                log("FAIL: '研究团队' in modal text")
            else:
                log("PASS: '研究团队' not in modal text")

            # Close modal
            try:
                close_btn = page.locator(".ant-modal-footer button", has_text="Close")
                close_btn.click()
                page.wait_for_timeout(500)
            except Exception:
                try:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(500)
                except Exception:
                    pass
        except Exception as e:
            results["errors"].append(f"Could not open details modal: {str(e)[:120]}")
            log(f"Warning: Could not open modal: {e}")

        # ── Step 7: Verify via backend API ─────────────────────────────────────
        print("\n[Step 7] Verifying results via backend API")

        try:
            api_resp = urllib.request.urlopen(f"{BACKEND_URL}/api/v1/research/jobs", timeout=15)
            jobs_data = json.loads(api_resp.read())
            target_jobs = [j for j in jobs_data if j.get("topic") == TOPIC]

            if not target_jobs:
                results["errors"].append(f"No '{TOPIC}' job found via API")
                log(f"No '{TOPIC}' job found in API!")
            else:
                target_job = sorted(target_jobs, key=lambda x: x.get("created_at", ""), reverse=True)[0]
                job_id = target_job["job_id"]
                results["job_id"] = results["job_id"] or job_id
                status = target_job["status"]
                log(f"API job: {job_id}, status: {status}")
                results["details"]["job_status_api"] = status
                results["details"]["total_papers"] = target_job.get("total_papers")
                results["details"]["processed_papers"] = target_job.get("processed_papers")
                results["details"]["result_path"] = target_job.get("result_path", "")

                if status == "completed":
                    results["job_completed"] = True

                    # Download and inspect zip
                    dl_url = f"{BACKEND_URL}/api/v1/research/download/{job_id}"
                    log(f"Downloading zip: {dl_url}")
                    try:
                        dl_resp = urllib.request.urlopen(dl_url, timeout=30)
                        zip_bytes = dl_resp.read()
                        log(f"Downloaded {len(zip_bytes)} bytes")

                        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                            names = zf.namelist()
                            log(f"Zip contents: {names}")
                            results["details"]["zip_contents"] = names

                            # ── raw_data.json checks ──
                            if "raw_data.json" in names:
                                raw_json = json.loads(zf.read("raw_data.json"))
                                papers = raw_json.get("papers", [])
                                log(f"Papers in raw_data.json: {len(papers)}")
                                results["details"]["paper_count"] = len(papers)

                                if papers:
                                    results["papers_found"] = True
                                    paper = papers[0]
                                    log(f"First paper keys: {list(paper.keys())}")
                                    log(f"First paper title: {paper.get('title', '')[:80]}")

                                    # Check for 研究团队 in JSON
                                    paper_str = json.dumps(paper, ensure_ascii=False)
                                    if "研究团队" in paper_str:
                                        results["errors"].append("FAIL: '研究团队' found in raw_data.json paper")
                                        log("FAIL: '研究团队' in raw_data.json")
                                    else:
                                        log("PASS: '研究团队' not in raw_data.json paper")

                                    # Translation check
                                    trans_keys = [
                                        "abstract_cn", "abstract_zh", "translation",
                                        "abstract_chinese", "chinese_abstract", "zh_abstract",
                                        "title_cn", "title_zh"
                                    ]
                                    translation = ""
                                    for tk in trans_keys:
                                        val = paper.get(tk)
                                        if val and len(str(val)) > 20 and "暂无翻译" not in str(val):
                                            translation = str(val)
                                            log(f"Translation at '{tk}': {translation[:80]}...")
                                            break

                                    results["details"]["translation_preview"] = translation[:200] if translation else "(not found in JSON)"
                                    if translation:
                                        results["translation_present"] = True
                                        log(f"PASS: Translation found ({len(translation)} chars)")
                                    else:
                                        log("Translation not found in JSON keys, will check markdown")

                                    # 6-dimension analysis check
                                    analysis = paper.get("analysis", {}) or {}
                                    dim_map = {
                                        "技术路线": ["technical_route", "技术路线"],
                                        "技术优势": ["advantages", "技术优势"],
                                        "技术不足": ["limitations", "技术不足"],
                                        "技术壁垒": ["technical_barriers", "技术壁垒"],
                                        "应用场景": ["feasibility", "应用场景"],
                                        "未来方向": ["generalization", "未来方向"],
                                    }
                                    found_dims = {}
                                    for cn, keys in dim_map.items():
                                        val = ""
                                        for k in keys:
                                            v = paper.get(k) or analysis.get(k)
                                            if v and str(v) not in {"待分析", "分析失败", ""}:
                                                val = str(v)
                                                break
                                        found_dims[cn] = val

                                    valid = {k: v for k, v in found_dims.items() if v}
                                    results["details"]["analysis_dims_json"] = {k: v[:60] for k, v in found_dims.items()}
                                    results["details"]["valid_analysis_dims"] = list(valid.keys())
                                    log(f"Valid analysis dims from JSON: {list(valid.keys())}")
                                    if len(valid) >= 3:
                                        results["analysis_present"] = True
                                        log(f"PASS: Analysis present ({len(valid)} dims)")

                            # ── Markdown checks ──
                            md_files = [n for n in names if n.endswith(".md") and "原始" not in n]
                            for mdf in md_files:
                                md_content = zf.read(mdf).decode("utf-8", errors="replace")
                                check_file_for_removed_fields(md_content, mdf, "MARKDOWN")

                            # ── HTML PPT checks ──
                            html_ppt_files = [n for n in names if n.endswith(".html") and "ppt" in n.lower()]
                            for hf in html_ppt_files:
                                html_content = zf.read(hf).decode("utf-8", errors="replace")
                                check_file_for_removed_fields(html_content, hf, "HTML_PPT")

                            # Also check non-PPT HTML files for 研究团队
                            other_html = [n for n in names if n.endswith(".html") and "ppt" not in n.lower()]
                            for hf in other_html:
                                html_content = zf.read(hf).decode("utf-8", errors="replace")
                                check_file_for_removed_fields(html_content, hf, "HTML_READING")

                    except Exception as e:
                        results["errors"].append(f"Download/parse error: {str(e)[:200]}")
                        log(f"Download error: {e}")

                elif status == "failed":
                    err_msg = target_job.get("error_message", "unknown")
                    results["errors"].append(f"Job failed via API: {err_msg}")
                    log(f"Job failed: {err_msg}")

        except Exception as e:
            results["errors"].append(f"API verification error: {str(e)[:200]}")
            log(f"API error: {e}")

        # ── Step 8: Check local result files directly ──────────────────────────
        print("\n[Step 8] Checking local result files directly")
        # Find FRONTEND_NOSUM result directory
        try:
            if os.path.exists(RESULT_DIR):
                all_dirs = os.listdir(RESULT_DIR)
                target_dirs = [d for d in all_dirs if "FRONTEND_NOSUM" in d]
                log(f"Found result dirs for FRONTEND_NOSUM: {target_dirs}")

                for tdir in target_dirs:
                    full_path = os.path.join(RESULT_DIR, tdir)
                    check_result_dir_files(full_path)
            else:
                log(f"Result directory not found: {RESULT_DIR}")
        except Exception as e:
            results["errors"].append(f"Local file check error: {str(e)[:150]}")
            log(f"Local file check error: {e}")

        # ── Step 9: Final screenshots ──────────────────────────────────────────
        print("\n[Step 9] Final screenshots")
        page.wait_for_timeout(2000)
        screenshot(page, "07_final_state")

        # Try to download via UI click and screenshot
        try:
            target_row = page.locator("tr", has_text=TOPIC).first
            target_row.wait_for(timeout=5000)
            download_btn = target_row.get_by_role("button", name="Download")
            if download_btn.count() > 0:
                with page.expect_download(timeout=15000) as dl_info:
                    download_btn.click()
                dl = dl_info.value
                log(f"Downloaded via UI: {dl.suggested_filename}")
                results["details"]["ui_download_filename"] = dl.suggested_filename
            screenshot(page, "08_after_download")
        except Exception as e:
            log(f"UI download click skipped: {str(e)[:80]}")

        browser.close()


def print_summary():
    print("\n" + "=" * 70)
    print("TEST RESULTS SUMMARY - FRONTEND_NOSUM")
    print("=" * 70)

    print(f"\nJob ID:                        {results['job_id']}")
    print(f"Screenshots saved to:          {SCREENSHOT_DIR}")
    print(f"Screenshots taken:             {len(results['screenshots'])}")
    for s in results["screenshots"]:
        print(f"  - {s}")

    print("\n--- Core Checks ---")
    checks = [
        ("Submission successful",       results["submission_success"]),
        ("Job completed",               results["job_completed"]),
        ("Papers found",                results["papers_found"]),
        ("Translation (中文翻译) present", results["translation_present"]),
        ("6-dimension analysis present", results["analysis_present"]),
    ]
    for label, val in checks:
        status = "PASS" if val else "FAIL"
        print(f"  [{status}] {label}")

    print("\n--- Removed Field Checks (should all PASS) ---")
    removed_checks = [
        ("研究团队 NOT in output",      results["no_research_team"]),
        ("综合总结 NOT in HTML PPT",    results["no_summary_slide"]),
        ("总体行业分析 NOT in Markdown", results["no_industry_analysis"]),
        ("发展建议 NOT in Markdown",    results["no_development_advice"]),
    ]
    for label, val in removed_checks:
        if val is True:
            status = "PASS"
        elif val is False:
            status = "FAIL"
        else:
            status = "N/A (not checked)"
        print(f"  [{status}] {label}")

    d = results["details"]
    if d:
        print("\n--- Job Details ---")
        for k in ["job_status_api", "total_papers", "processed_papers", "paper_count",
                  "zip_contents", "result_dir_files"]:
            if k in d:
                print(f"  {k}: {d[k]}")

        if "translation_preview" in d and d["translation_preview"]:
            print(f"\n  Translation preview: {d['translation_preview'][:150]}")

        if "valid_analysis_dims" in d:
            print(f"  Valid analysis dims: {d['valid_analysis_dims']}")

        if "analysis_dims_json" in d:
            print("\n  Analysis dimension values:")
            for dim, val in d["analysis_dims_json"].items():
                ok = "OK" if val else "MISSING"
                print(f"    [{ok}] {dim}: {val[:70] if val else '(empty)'}")

    if results["warnings"]:
        print(f"\n--- Warnings ({len(results['warnings'])}) ---")
        for w in results["warnings"]:
            print(f"  ! {w}")

    if results["errors"]:
        print(f"\n--- Errors/Failures ({len(results['errors'])}) ---")
        for e in results["errors"]:
            print(f"  X {e}")

    # Overall verdict
    print("\n" + "=" * 70)
    core_passed = (
        results["submission_success"] and
        results["job_completed"] and
        results["papers_found"] and
        results["translation_present"] and
        results["analysis_present"]
    )
    removed_passed = (
        results["no_research_team"] is True and
        results["no_summary_slide"] is True and
        results["no_industry_analysis"] is True and
        results["no_development_advice"] is True
    )

    all_passed = core_passed and removed_passed

    if all_passed:
        print("OVERALL: PASS - All checks succeeded")
    else:
        failed_core = [label for label, val in checks if not val]
        failed_removed = [label for label, val in removed_checks if val is not True]
        print(f"OVERALL: FAIL")
        if failed_core:
            print(f"  Core failed: {failed_core}")
        if failed_removed:
            print(f"  Removed-field checks failed: {failed_removed}")
    print("=" * 70)


if __name__ == "__main__":
    print("=" * 70)
    print("E2E Test: Literature Research - NOSUM Variant")
    print(f"Topic: {TOPIC}")
    print(f"Frontend: {FRONTEND_URL}")
    print(f"Backend: {BACKEND_URL}")
    print(f"Screenshots: {SCREENSHOT_DIR}")
    print("=" * 70)

    run_test()
    print_summary()
