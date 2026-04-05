"""
End-to-End test for Literature Research feature.
Tests the full flow: navigate -> submit job -> poll status -> verify results.
"""

import time
import json
import zipfile
import io
import sys
import os
from playwright.sync_api import sync_playwright, Page

# Force UTF-8 output on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FRONTEND_URL = "http://localhost:5173"
BACKEND_URL = "http://localhost:8000"
SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "e2e_screenshots")

TOPIC = "E2E_TEST"
QUERY = '"noninvasive prenatal diagnosis"[Title/Abstract] AND "2026/01/01 00:00":"3000/01/01 05:00"[Date - Entry] AND "journal article"[Publication Type]'
MAX_PAPERS = 1

POLL_INTERVAL_SECONDS = 5
MAX_WAIT_SECONDS = 300  # 5 minutes max

results = {
    "screenshots": [],
    "errors": [],
    "job_id": None,
    "submission_success": False,
    "job_completed": False,
    "papers_found": False,
    "translation_present": False,
    "analysis_present": False,
    "details": {},
}


def screenshot(page: Page, name: str) -> str:
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    page.screenshot(path=path, full_page=True)
    results["screenshots"].append(path)
    print(f"  [screenshot] {path}")
    return path


def log(msg: str):
    print(f"  {msg}")


def run_test():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # ── Step 1: Open frontend ──────────────────────────────────────────────
        print("\n[Step 1] Opening frontend at", FRONTEND_URL)
        page.goto(FRONTEND_URL)
        page.wait_for_load_state("networkidle", timeout=15000)
        screenshot(page, "01_homepage")
        title = page.title()
        log(f"Page title: {title}")

        # ── Step 2: Navigate to Research section ───────────────────────────────
        print("\n[Step 2] Navigating to 'Research' section")
        # Menu items are rendered as <li> with aria-label or text
        # From Layout.tsx: key='research', label='Research'
        research_menu = page.get_by_role("menuitem", name="Research")
        research_menu.click()
        page.wait_for_timeout(1000)
        screenshot(page, "02_research_section")
        log("Clicked 'Research' menu item")

        # Verify we're on the Literature Research page
        heading = page.locator("text=Literature Research").first
        heading.wait_for(timeout=5000)
        log("Literature Research section loaded")

        # ── Step 3: Fill in the form ───────────────────────────────────────────
        print("\n[Step 3] Filling in research form")

        # Clear and fill Topic field (placeholder: "e.g., NIPD, CRISPR")
        topic_input = page.locator('input[placeholder*="NIPD"]').first
        topic_input.click()
        topic_input.select_text()
        topic_input.fill(TOPIC)
        log(f"Set Topic: {TOPIC}")

        # Clear and fill Query textarea
        query_textarea = page.locator("textarea").first
        query_textarea.click()
        query_textarea.select_text()
        query_textarea.fill(QUERY)
        log(f"Set Query: {QUERY[:60]}...")

        # Clear and fill Max Papers (InputNumber spin button)
        max_papers_input = page.locator('input[role="spinbutton"]').first
        max_papers_input.click()
        max_papers_input.select_text()
        max_papers_input.fill(str(MAX_PAPERS))
        log(f"Set Max Papers: {MAX_PAPERS}")

        screenshot(page, "03_form_filled")

        # ── Step 4: Submit the form ────────────────────────────────────────────
        print("\n[Step 4] Submitting research job")
        run_button = page.get_by_role("button", name="Run Research")
        run_button.click()
        log("Clicked 'Run Research' button")

        # Wait for the Ant Design message toast
        try:
            success_msg = page.locator(".ant-message-success").first
            success_msg.wait_for(timeout=12000)
            msg_text = success_msg.inner_text()
            log(f"Success message: {msg_text}")
            results["submission_success"] = True
            if "Research job started:" in msg_text:
                results["job_id"] = msg_text.split("Research job started:")[-1].strip()
                log(f"Job ID from toast: {results['job_id']}")
        except Exception as e:
            # Check for error toast
            try:
                err_msg = page.locator(".ant-message-error").first
                err_text = err_msg.inner_text()
                results["errors"].append(f"Submission error toast: {err_text}")
                log(f"ERROR toast: {err_text}")
            except:
                pass
            results["errors"].append(f"No success toast visible: {str(e)[:100]}")
            log(f"Warning: Could not confirm success toast: {e}")

        screenshot(page, "04_after_submit")

        # ── Step 5: Poll job status ────────────────────────────────────────────
        print("\n[Step 5] Polling job status (every 5s)")
        start_time = time.time()
        last_status = None
        poll_count = 0

        while time.time() - start_time < MAX_WAIT_SECONDS:
            time.sleep(POLL_INTERVAL_SECONDS)
            poll_count += 1

            # The table auto-refreshes every 5s via React Query
            try:
                e2e_row = page.locator("tr", has_text="E2E_TEST").first
                e2e_row.wait_for(timeout=3000)
                row_text = e2e_row.inner_text()

                if "COMPLETED" in row_text.upper():
                    log(f"[poll {poll_count}] Status: COMPLETED")
                    last_status = "completed"
                    results["job_completed"] = True
                    break
                elif "FAILED" in row_text.upper():
                    log(f"[poll {poll_count}] Status: FAILED")
                    last_status = "failed"
                    results["errors"].append("Job FAILED in UI")
                    break
                elif "RUNNING" in row_text.upper():
                    log(f"[poll {poll_count}] Status: RUNNING ({int(time.time()-start_time)}s elapsed)")
                    last_status = "running"
                elif "PENDING" in row_text.upper():
                    log(f"[poll {poll_count}] Status: PENDING ({int(time.time()-start_time)}s elapsed)")
                    last_status = "pending"
                else:
                    log(f"[poll {poll_count}] Row text: {row_text[:120]}")
            except Exception as e:
                log(f"[poll {poll_count}] Could not find E2E_TEST row: {e}")

        screenshot(page, "05_after_polling")
        log(f"Final status from UI: {last_status} after {int(time.time()-start_time)}s")

        if not results["job_completed"]:
            results["errors"].append(
                f"Job did not complete within {MAX_WAIT_SECONDS}s, last status: {last_status}"
            )

        # ── Step 6: Open job details modal ─────────────────────────────────────
        print("\n[Step 6] Opening job details modal")
        try:
            e2e_row = page.locator("tr", has_text="E2E_TEST").first
            details_btn = e2e_row.get_by_role("button", name="Details")
            details_btn.click()
            page.wait_for_timeout(1000)
            screenshot(page, "06_details_modal")

            modal = page.locator(".ant-modal-content")
            modal.wait_for(timeout=5000)
            modal_text = modal.inner_text()
            log(f"Modal content preview: {modal_text[:400]}")
            results["details"]["modal_text"] = modal_text

            # Close modal
            close_btn = page.locator(".ant-modal-footer button", has_text="Close")
            close_btn.click()
            page.wait_for_timeout(500)
        except Exception as e:
            results["errors"].append(f"Could not open details modal: {str(e)[:100]}")
            log(f"Warning: {e}")

        # ── Step 7: Verify result content via backend API ──────────────────────
        print("\n[Step 7] Verifying result content via backend API")
        import urllib.request

        try:
            api_response = urllib.request.urlopen(f"{BACKEND_URL}/api/v1/research/jobs")
            jobs_data = json.loads(api_response.read())
            e2e_jobs = [j for j in jobs_data if j.get("topic") == TOPIC]

            if not e2e_jobs:
                results["errors"].append("No E2E_TEST job found via API")
                log("No E2E_TEST job found in API!")
            else:
                # Most recent E2E_TEST job
                e2e_job = sorted(e2e_jobs, key=lambda x: x["created_at"], reverse=True)[0]
                job_id = e2e_job["job_id"]
                results["job_id"] = results["job_id"] or job_id
                log(f"API found job: {job_id}, status: {e2e_job['status']}")
                results["details"]["job_status_api"] = e2e_job["status"]
                results["details"]["total_papers"] = e2e_job["total_papers"]
                results["details"]["processed_papers"] = e2e_job["processed_papers"]

                if e2e_job["status"] == "completed":
                    results["job_completed"] = True

                    # Download zip and inspect content
                    try:
                        dl_url = f"{BACKEND_URL}/api/v1/research/download/{job_id}"
                        log(f"Downloading: {dl_url}")
                        dl_resp = urllib.request.urlopen(dl_url)
                        zip_bytes = dl_resp.read()
                        log(f"Downloaded zip: {len(zip_bytes)} bytes")

                        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                            names = zf.namelist()
                            log(f"Zip contents: {names}")

                            # ── Check raw_data.json ──
                            if "raw_data.json" in names:
                                raw_json = json.loads(zf.read("raw_data.json"))
                                papers = raw_json.get("papers", [])
                                log(f"Papers in raw_data.json: {len(papers)}")
                                results["details"]["paper_count_json"] = len(papers)

                                if papers:
                                    results["papers_found"] = True
                                    paper = papers[0]
                                    log(f"First paper title: {paper.get('title', '')[:80]}")
                                    log(f"Paper keys: {list(paper.keys())}")

                                    # Check translation (Chinese abstract)
                                    # Backend stores it as 'abstract_cn' or 'title_cn'
                                    trans_keys = [
                                        "abstract_cn", "abstract_zh", "translation",
                                        "abstract_chinese", "chinese_abstract", "zh_abstract",
                                    ]
                                    translation = ""
                                    for tk in trans_keys:
                                        val = paper.get(tk)
                                        if val and len(str(val)) > 20:
                                            translation = str(val)
                                            log(f"Found translation at key '{tk}' ({len(translation)} chars)")
                                            break
                                    results["details"]["translation_value"] = translation[:200] if translation else "(not found)"
                                    if translation and len(translation) > 20 and "暂无翻译" not in translation:
                                        results["translation_present"] = True

                                    # Check 6-dimension analysis
                                    # Backend stores them as English keys:
                                    # technical_route, advantages, limitations,
                                    # technical_barriers, feasibility, generalization
                                    analysis_key_map = {
                                        "技术路线": "technical_route",
                                        "技术优势": "advantages",
                                        "技术不足": "limitations",
                                        "技术壁垒": "technical_barriers",
                                        "应用场景": "feasibility",
                                        "未来方向": "generalization",
                                    }
                                    analysis = paper.get("analysis", {}) or {}
                                    found_dims = {}
                                    for cn_name, en_key in analysis_key_map.items():
                                        val = (paper.get(en_key) or
                                               analysis.get(en_key) or
                                               analysis.get(cn_name) or
                                               paper.get(cn_name) or "")
                                        found_dims[cn_name] = str(val) if val else ""

                                    bad = {"待分析", "分析失败", ""}
                                    valid = {k: v for k, v in found_dims.items()
                                             if v and v not in bad}
                                    results["details"]["analysis_fields"] = found_dims
                                    results["details"]["valid_analysis_dims"] = list(valid.keys())
                                    if len(valid) >= 3:
                                        results["analysis_present"] = True
                                    log(f"Valid analysis dims from JSON: {list(valid.keys())}")

                            # ── Check Markdown report ──
                            md_files = [n for n in names if n.endswith(".md")]
                            if md_files:
                                md_content = zf.read(md_files[0]).decode("utf-8", errors="replace")
                                log(f"Markdown report: {md_files[0]}, size: {len(md_content)} chars")
                                results["details"]["md_report_size"] = len(md_content)
                                results["details"]["md_filename"] = md_files[0]

                                # Translation check in markdown
                                has_zh_trans = "中文翻译" in md_content or "中文标题" in md_content
                                not_empty_trans = "暂无翻译" not in md_content
                                log(f"MD has translation section: {has_zh_trans}, non-empty: {not_empty_trans}")
                                if has_zh_trans and not_empty_trans:
                                    results["translation_present"] = True
                                elif has_zh_trans and not not_empty_trans:
                                    results["errors"].append("Translation is '暂无翻译' in markdown")

                                # Analysis check in markdown
                                dim_fields_md = ["技术路线", "技术优势", "技术不足", "技术壁垒"]
                                found_in_md = [d for d in dim_fields_md if d in md_content]
                                bad_in_md = [
                                    d for d in found_in_md
                                    if (f"**{d}**: 待分析" in md_content or
                                        f"**{d}**: 分析失败" in md_content)
                                ]
                                log(f"Dims in markdown: {found_in_md}, bad: {bad_in_md}")
                                if len(found_in_md) >= 3 and not bad_in_md:
                                    results["analysis_present"] = True

                    except Exception as e:
                        results["errors"].append(f"Download error: {str(e)[:150]}")
                        log(f"Download/parse error: {e}")

                elif e2e_job["status"] == "failed":
                    results["errors"].append(
                        f"Job failed: {e2e_job.get('error_message', 'unknown error')}"
                    )

        except Exception as e:
            results["errors"].append(f"API verification error: {str(e)[:150]}")
            log(f"API error: {e}")

        # ── Step 8: Final screenshot ───────────────────────────────────────────
        print("\n[Step 8] Taking final screenshot")
        page.wait_for_timeout(2000)
        screenshot(page, "07_final_state")

        browser.close()


if __name__ == "__main__":
    print("=" * 60)
    print("E2E Test: Literature Research Feature")
    print("=" * 60)

    run_test()

    print("\n" + "=" * 60)
    print("TEST RESULTS SUMMARY")
    print("=" * 60)
    print(f"Screenshots taken: {len(results['screenshots'])}")
    for s in results["screenshots"]:
        print(f"  - {s}")

    print(f"\nJob ID:                   {results['job_id']}")
    print(f"Submission successful:     {results['submission_success']}")
    print(f"Job completed:             {results['job_completed']}")
    print(f"Papers found:              {results['papers_found']}")
    print(f"Chinese translation:       {results['translation_present']}")
    print(f"6-dimension analysis:      {results['analysis_present']}")

    d = results["details"]
    if d:
        print("\nJob details from API:")
        for k in ["job_status_api", "total_papers", "processed_papers",
                  "paper_count_json", "md_filename", "md_report_size"]:
            if k in d:
                print(f"  {k}: {d[k]}")

        if "translation_value" in d:
            tv = d["translation_value"]
            print(f"\nTranslation preview: {tv[:120]}")

        if "valid_analysis_dims" in d:
            print(f"\nValid analysis dims: {d['valid_analysis_dims']}")

        if "analysis_fields" in d:
            print("\nAnalysis field values:")
            for dim, val in d["analysis_fields"].items():
                status = "OK" if val and val not in {"待分析", "分析失败"} else "MISSING/BAD"
                print(f"  [{status}] {dim}: {str(val)[:80]}")

    if results["errors"]:
        print(f"\nErrors/Warnings ({len(results['errors'])}):")
        for e in results["errors"]:
            print(f"  - {e}")

    # Final verdict
    print("\n" + "=" * 60)
    all_passed = (
        results["submission_success"] and
        results["job_completed"] and
        results["papers_found"] and
        results["translation_present"] and
        results["analysis_present"]
    )
    if all_passed:
        print("OVERALL: PASS - All checks succeeded")
    else:
        checks = {
            "Submission": results["submission_success"],
            "Job completed": results["job_completed"],
            "Papers found": results["papers_found"],
            "Translation": results["translation_present"],
            "Analysis": results["analysis_present"],
        }
        failed = [k for k, v in checks.items() if not v]
        print(f"OVERALL: PARTIAL/FAIL - Failed checks: {failed}")
    print("=" * 60)
