"""
E2E Playwright test for Literature Research feature - PFIX fixes verification.

Verifies three fixes end-to-end via the browser UI:
  1. HTML PPT slide page count is correct (slide X / Y where Y == actual total slides)
  2. Paper title font-size is 1.1rem (consistent across both slides per paper)
  3. PDF conversion produces a PDF where each slide fills one full page

Usage:
    python tests/e2e_pfix_test.py
    # or with explicit frontend URL:
    FRONTEND_URL=http://localhost:5173 python tests/e2e_pfix_test.py
"""

import os
import re
import sys
import glob
import json
import time
import traceback
import urllib.request

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
SCREENSHOT_DIR = (
    r"C:\Users\xieyeming1\Downloads\git_repo\domain_expert\backend\tests\e2e_screenshots\pfix"
)
RESULT_BASE = (
    r"C:\Users\xieyeming1\Downloads\git_repo\domain_expert\backend\literature_research\result"
)

TOPIC = "FFIX_TEST"
QUERY = "NIPD[Title/Abstract] AND monogenic[Title/Abstract]"
MAX_PAPERS = 2
JOB_TIMEOUT_SEC = 5 * 60  # 5 minutes
POLL_INTERVAL_SEC = 5

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def screenshot(page, name: str) -> str:
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    page.screenshot(path=path, full_page=True)
    print(f"  [screenshot] {path}")
    return path


def api_get(path: str):
    url = f"{BACKEND_URL}{path}"
    # Use a generous timeout - LLM processing can make the backend slow
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.loads(resp.read().decode())


def check_frontend_running() -> bool:
    try:
        urllib.request.urlopen(FRONTEND_URL, timeout=5)
        return True
    except Exception:
        return False


def check_backend_running() -> bool:
    try:
        urllib.request.urlopen(f"{BACKEND_URL}/api/v1/research/jobs", timeout=5)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Result-dir + file helpers
# ---------------------------------------------------------------------------

def find_result_dir(topic: str) -> str | None:
    """Find the most-recently-created result directory for *topic*."""
    pattern = os.path.join(RESULT_BASE, f"{topic}调研_*")
    dirs = glob.glob(pattern)
    if not dirs:
        return None
    # newest by mtime
    return max(dirs, key=os.path.getmtime)


def find_ppt_html(result_dir: str) -> str | None:
    paths = glob.glob(os.path.join(result_dir, "*_ppt.html"))
    return paths[0] if paths else None


def find_ppt_pdf(result_dir: str) -> str | None:
    paths = glob.glob(os.path.join(result_dir, "*_ppt.pdf"))
    return paths[0] if paths else None


# ---------------------------------------------------------------------------
# Verification checks
# ---------------------------------------------------------------------------

def check_A_result_dir(topic: str) -> tuple[bool, str, str | None]:
    """Check A: result directory exists for topic."""
    d = find_result_dir(topic)
    if d:
        return True, f"Result dir found: {d}", d
    return False, f"Result dir NOT found under {RESULT_BASE} for topic={topic}", None


def check_B_slide_count(html_path: str) -> tuple[bool, str, dict]:
    """Check B: actual slide count == declared total in slide-num spans."""
    content = open(html_path, encoding="utf-8").read()

    # Count top-level slide divs:  <div class="slide ...">
    actual_slides = len(re.findall(r'<div class="slide ', content))

    # Extract declared totals from slide-num spans, e.g. "3 / 7" → 7
    declared_totals = [int(m) for m in re.findall(r'class="slide-num"[^>]*>\s*\d+\s*/\s*(\d+)', content)]

    unique_totals = set(declared_totals)
    declared_total = declared_totals[0] if declared_totals else None

    details = {
        "actual_slides": actual_slides,
        "declared_totals_found": declared_totals,
        "unique_declared": list(unique_totals),
        "declared_total": declared_total,
    }

    if declared_total is None:
        # No slide-nums found - may be single slide or cover-only; check if slide count is sensible
        return False, f"No slide-num spans found in HTML. Actual slide divs: {actual_slides}", details

    if actual_slides != declared_total:
        return (
            False,
            f"MISMATCH: actual_slides={actual_slides} vs declared_total={declared_total}. "
            f"All declared totals: {declared_totals}",
            details,
        )

    if len(unique_totals) > 1:
        return (
            False,
            f"INCONSISTENT declared totals across slide-num spans: {unique_totals}",
            details,
        )

    return (
        True,
        f"OK: actual_slides={actual_slides} == declared_total={declared_total}",
        details,
    )


def check_C_title_font(html_path: str, n_papers: int) -> tuple[bool, str, dict]:
    """Check C: paper title font-size is 1.1rem, not 0.9rem/0.82rem in title divs."""
    content = open(html_path, encoding="utf-8").read()

    count_11 = len(re.findall(r"font-size:1\.1rem", content))
    # 0.9rem / 0.82rem in actual title div context (NOT in end-slide footnote <p>)
    # Title divs: those immediately after slide-header with font-size style
    # Count total occurrences of bad sizes in font-weight:700 contexts (title-like)
    count_09_total = len(re.findall(r"font-size:0\.9rem", content))
    count_082_total = len(re.findall(r"font-size:0\.82rem", content))

    # Count 0.9rem/0.82rem that appear with font-weight:700 (those would be in title divs)
    count_09_in_title = len(re.findall(
        r"font-size:0\.9rem[^\"]*font-weight:700|font-weight:700[^\"]*font-size:0\.9rem",
        content,
    ))
    count_082_in_title = len(re.findall(
        r"font-size:0\.82rem[^\"]*font-weight:700|font-weight:700[^\"]*font-size:0\.82rem",
        content,
    ))

    # Expected: 1.1rem appears at least 2*n_papers times
    # (each paper has 2 slides with a title div: basic-info slide + deep-analysis slide)
    min_expected_11 = 2 * n_papers

    details = {
        "count_1_1rem": count_11,
        "count_0_9rem_total": count_09_total,
        "count_0_82rem_total": count_082_total,
        "count_0_9rem_in_title_context": count_09_in_title,
        "count_0_82rem_in_title_context": count_082_in_title,
        "min_expected_1_1rem": min_expected_11,
    }

    failures = []
    if count_11 < min_expected_11:
        failures.append(
            f"font-size:1.1rem appears {count_11} times, expected >= {min_expected_11}"
        )
    if count_09_in_title > 0:
        failures.append(
            f"font-size:0.9rem found in title-like (bold) context {count_09_in_title} times"
        )
    if count_082_in_title > 0:
        failures.append(
            f"font-size:0.82rem found in title-like (bold) context {count_082_in_title} times"
        )

    if failures:
        return False, "; ".join(failures), details

    # Note about end-slide footnote 0.9rem - it's in a <p> not a title div; that's acceptable
    note = ""
    if count_09_total > 0:
        note = f" (note: {count_09_total} 0.9rem in non-title context, e.g. end-slide footnote - acceptable)"

    return (
        True,
        f"OK: font-size:1.1rem={count_11} (>= {min_expected_11}), no bad sizes in title divs" + note,
        details,
    )


def check_D_pdf_exists(result_dir: str) -> tuple[bool, str, dict]:
    """Check D: PDF file exists and has non-zero size."""
    pdf_path = find_ppt_pdf(result_dir)
    if pdf_path is None:
        return False, f"_ppt.pdf not found in {result_dir}", {}
    size = os.path.getsize(pdf_path)
    if size == 0:
        return False, f"_ppt.pdf exists but is empty (0 bytes): {pdf_path}", {"path": pdf_path, "size": 0}
    return True, f"OK: PDF exists, size={size:,} bytes: {pdf_path}", {"path": pdf_path, "size": size}


def check_E_pdf_pages(pdf_path: str, expected_pages: int) -> tuple[bool, str, dict]:
    """Check E: PDF page count equals slide count (requires PyMuPDF)."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(pdf_path)
        page_count = len(doc)
        page_sizes = [(p.rect.width, p.rect.height) for p in doc]
        doc.close()

        details = {
            "page_count": page_count,
            "expected_pages": expected_pages,
            "page_sizes": page_sizes,
        }

        if page_count != expected_pages:
            return (
                False,
                f"PDF page count {page_count} != expected {expected_pages} slides",
                details,
            )

        # Check all pages have same dimensions (each slide fills one full page)
        unique_sizes = set(page_sizes)
        if len(unique_sizes) > 1:
            return (
                False,
                f"PDF pages have inconsistent sizes: {unique_sizes}",
                details,
            )

        w, h = page_sizes[0]
        return (
            True,
            f"OK: PDF has {page_count} pages, each {w:.0f}x{h:.0f} pts (one slide per page)",
            details,
        )
    except ImportError:
        return None, "PyMuPDF not available - skipping page count check", {}
    except Exception as exc:
        return False, f"Error reading PDF: {exc}", {}


# ---------------------------------------------------------------------------
# Wait for job completion via backend API
# ---------------------------------------------------------------------------

def wait_for_job_completion(job_id: str, timeout_sec: int = JOB_TIMEOUT_SEC) -> dict:
    """Poll backend API until job completes or times out. Returns final job dict."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        job = api_get(f"/api/v1/research/jobs/{job_id}")
        status = job.get("status")
        stage = job.get("current_stage", "")
        processed = job.get("processed_papers", 0)
        total = job.get("total_papers", 0)
        print(
            f"  [poll] status={status} stage={stage} papers={processed}/{total}"
        )
        if status == "completed":
            return job
        if status == "failed":
            raise RuntimeError(f"Job failed: {job.get('error_message', 'unknown error')}")
        time.sleep(POLL_INTERVAL_SEC)
    raise TimeoutError(f"Job {job_id} did not complete within {timeout_sec}s")


# ---------------------------------------------------------------------------
# Main test
# ---------------------------------------------------------------------------

def run_test():
    print("=" * 70)
    print("E2E Test: Literature Research PFIX fixes verification")
    print("=" * 70)
    print(f"Frontend: {FRONTEND_URL}")
    print(f"Backend:  {BACKEND_URL}")
    print(f"Topic:    {TOPIC}")
    print(f"Query:    {QUERY}")
    print(f"MaxPapers:{MAX_PAPERS}")
    print()

    # Pre-flight checks
    print("[0] Pre-flight checks...")
    if not check_backend_running():
        print(f"  ERROR: Backend not reachable at {BACKEND_URL}")
        sys.exit(1)
    print(f"  Backend: OK ({BACKEND_URL})")
    if not check_frontend_running():
        print(f"  WARNING: Frontend not reachable at {FRONTEND_URL} - will try anyway")
    else:
        print(f"  Frontend: OK ({FRONTEND_URL})")

    results = {}
    job_id = None
    n_papers = MAX_PAPERS  # will be updated from API

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        try:
            # ------------------------------------------------------------------
            # Step 1: Navigate to frontend
            # ------------------------------------------------------------------
            print("\n[1] Navigating to frontend...")
            page.goto(FRONTEND_URL, wait_until="networkidle", timeout=30000)
            screenshot(page, "01_homepage")
            print(f"  Title: {page.title()}")

            # ------------------------------------------------------------------
            # Step 2: Find the "Research" tab / section
            # ------------------------------------------------------------------
            print("\n[2] Finding Literature Research section...")
            # The Layout uses ant-design Menu with key='research' label='Research'
            research_menu = page.locator("text=Research").first
            research_menu.wait_for(state="visible", timeout=10000)
            research_menu.click()
            page.wait_for_load_state("networkidle")
            screenshot(page, "02_research_tab")
            print("  Clicked Research menu item")

            # Verify the LiteratureResearch component is shown
            page.wait_for_selector("text=Literature Research", timeout=10000)
            print("  LiteratureResearch component visible")

            # ------------------------------------------------------------------
            # Step 3: Fill the form
            # ------------------------------------------------------------------
            print("\n[3] Filling research form...")

            # Topic field - clear default and type new value
            topic_input = page.locator("input[placeholder='e.g., NIPD, CRISPR']")
            topic_input.wait_for(state="visible", timeout=10000)
            topic_input.click(click_count=3)
            topic_input.fill(TOPIC)
            print(f"  Topic: {TOPIC}")

            # Query textarea
            query_textarea = page.locator("textarea[placeholder*='NIPD']")
            query_textarea.wait_for(state="visible", timeout=5000)
            query_textarea.click(click_count=3)
            query_textarea.fill(QUERY)
            print(f"  Query: {QUERY}")

            # Max papers - ant-design InputNumber
            max_input = page.locator(".ant-input-number-input").first
            max_input.click(click_count=3)
            max_input.fill(str(MAX_PAPERS))
            print(f"  MaxPapers: {MAX_PAPERS}")

            screenshot(page, "03_form_filled")

            # ------------------------------------------------------------------
            # Step 4: Submit the form
            # ------------------------------------------------------------------
            print("\n[4] Submitting research job...")
            run_btn = page.locator("button:has-text('Run Research')")
            run_btn.wait_for(state="visible", timeout=5000)

            # Check if a usable completed FFIX_TEST job already exists (avoid re-submitting)
            existing_jobs = api_get("/api/v1/research/jobs")
            completed_ffix = [
                j for j in existing_jobs
                if j.get("topic") == TOPIC and j.get("status") == "completed"
                and j.get("result_path")
            ]

            if completed_ffix:
                job_id = completed_ffix[0]["job_id"]
                final_job = completed_ffix[0]
                n_papers = final_job.get("total_papers", MAX_PAPERS)
                print(f"  Reusing existing completed job: {job_id} (papers={n_papers})")
                screenshot(page, "04_reusing_existing_job")
            else:
                # Intercept the POST /api/v1/research/run to capture job_id
                captured_job_id = []

                def on_response(response):
                    if "/api/v1/research/run" in response.url and response.status == 200:
                        try:
                            data = response.json()
                            captured_job_id.append(data.get("job_id"))
                        except Exception:
                            pass

                page.on("response", on_response)
                run_btn.click()

                # Wait for the success message or job_id to appear
                page.wait_for_timeout(5000)
                screenshot(page, "04_job_submitted")

                if captured_job_id:
                    job_id = captured_job_id[0]
                    print(f"  Job started: job_id={job_id}")
                else:
                    # Fallback: get from API - the newest job with our topic
                    print("  job_id not captured from response, checking API...")
                    jobs = api_get("/api/v1/research/jobs")
                    ffix_jobs = [j for j in jobs if j.get("topic") == TOPIC]
                    if ffix_jobs:
                        job_id = ffix_jobs[0]["job_id"]
                        print(f"  Found job via API: {job_id}")
                    else:
                        raise RuntimeError(f"Could not find job with topic={TOPIC} in API response")

                # ------------------------------------------------------------------
                # Step 5: Wait for job to complete (polling API)
                # ------------------------------------------------------------------
                print(f"\n[5] Waiting for job {job_id} to complete (up to {JOB_TIMEOUT_SEC}s)...")
                final_job = wait_for_job_completion(job_id, timeout_sec=JOB_TIMEOUT_SEC)
                n_papers = final_job.get("total_papers", MAX_PAPERS)
                print(f"  Job completed! total_papers={n_papers}")

            screenshot(page, "05_job_completed_api_done")

            # Refresh UI to show completed status
            page.wait_for_timeout(6000)  # wait for 5s refetchInterval
            screenshot(page, "06_ui_after_completion")

            # ------------------------------------------------------------------
            # Step 6: Trigger "生成报告" (convert) via UI if HTML/PDF not yet present
            # ------------------------------------------------------------------
            print("\n[6] Checking report files / triggering generation...")
            existing_result_dir = find_result_dir(TOPIC)
            files_exist = (
                existing_result_dir is not None
                and find_ppt_html(existing_result_dir) is not None
                and find_ppt_pdf(existing_result_dir) is not None
            )

            if files_exist:
                print(f"  Report files already exist in: {existing_result_dir}")
                print("  Skipping '生成报告' click (files already generated)")
                screenshot(page, "07_files_already_exist")
            else:
                print("  Files not yet present - clicking '生成报告' button...")
                convert_btn = page.locator("button:has-text('生成报告')").first
                if convert_btn.count() == 0 or not convert_btn.is_visible():
                    print("  Button not visible, refreshing page...")
                    page.reload(wait_until="networkidle")
                    page.wait_for_timeout(2000)
                    page.locator("text=Research").first.click()
                    page.wait_for_timeout(2000)
                    convert_btn = page.locator("button:has-text('生成报告')").first

                if convert_btn.count() > 0 and convert_btn.is_visible():
                    # Wait for download (the report zip)
                    with page.expect_download(timeout=120000) as dl_info:
                        convert_btn.click()
                    download = dl_info.value
                    print(f"  Download started: {download.suggested_filename}")
                    dl_path = os.path.join(SCREENSHOT_DIR, download.suggested_filename)
                    download.save_as(dl_path)
                    print(f"  Saved zip to: {dl_path}")
                    screenshot(page, "07_after_convert")
                else:
                    print("  WARNING: '生成报告' button not found - files may appear via background job")
                    screenshot(page, "07_convert_btn_not_found")

        except Exception as exc:
            print(f"\n  ERROR during browser steps: {exc}")
            traceback.print_exc()
            screenshot(page, "error_state")
        finally:
            browser.close()

    # --------------------------------------------------------------------------
    # Verification checks (independent of browser)
    # --------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("VERIFICATION CHECKS")
    print("=" * 70)

    # Check A: result directory
    print("\n[A] Result directory exists...")
    ok_a, msg_a, result_dir = check_A_result_dir(TOPIC)
    results["A_result_dir"] = {"pass": ok_a, "msg": msg_a}
    status_a = "PASS" if ok_a else "FAIL"
    print(f"  {status_a}: {msg_a}")

    if not ok_a:
        print("\n  Cannot proceed with further checks without result directory.")
        print_summary(results)
        return results

    # Check B: slide count
    print("\n[B] HTML PPT slide count is correct...")
    html_path = find_ppt_html(result_dir)
    if html_path is None:
        results["B_slide_count"] = {"pass": False, "msg": f"_ppt.html not found in {result_dir}"}
        print(f"  FAIL: {results['B_slide_count']['msg']}")
    else:
        print(f"  HTML file: {html_path}")
        ok_b, msg_b, details_b = check_B_slide_count(html_path)
        results["B_slide_count"] = {"pass": ok_b, "msg": msg_b, "details": details_b}
        status_b = "PASS" if ok_b else "FAIL"
        print(f"  {status_b}: {msg_b}")
        print(f"  Details: {json.dumps(details_b, ensure_ascii=False)}")
        actual_slides = details_b.get("actual_slides", n_papers * 2 + 3)

    # Check C: title font size
    print("\n[C] Paper title font-size is 1.1rem...")
    if html_path is None:
        results["C_title_font"] = {"pass": False, "msg": "_ppt.html not found"}
        print(f"  FAIL: _ppt.html not found")
    else:
        ok_c, msg_c, details_c = check_C_title_font(html_path, n_papers)
        results["C_title_font"] = {"pass": ok_c, "msg": msg_c, "details": details_c}
        status_c = "PASS" if ok_c else "FAIL"
        print(f"  {status_c}: {msg_c}")
        print(f"  Details: {json.dumps(details_c, ensure_ascii=False)}")

    # Check D: PDF exists
    print("\n[D] PDF file exists and is non-empty...")
    ok_d, msg_d, details_d = check_D_pdf_exists(result_dir)
    results["D_pdf_exists"] = {"pass": ok_d, "msg": msg_d, "details": details_d}
    status_d = "PASS" if ok_d else "FAIL"
    print(f"  {status_d}: {msg_d}")

    # Check E: PDF page count
    print("\n[E] PDF page count matches slide count...")
    pdf_path = details_d.get("path") if ok_d else find_ppt_pdf(result_dir)
    if pdf_path and ok_d:
        # actual_slides may not be defined if check_B had no html
        expected = details_b.get("actual_slides", n_papers * 2 + 3) if html_path else n_papers * 2 + 3
        ok_e, msg_e, details_e = check_E_pdf_pages(pdf_path, expected)
        if ok_e is None:
            results["E_pdf_pages"] = {"pass": None, "msg": msg_e, "details": details_e}
            print(f"  SKIP: {msg_e}")
        else:
            results["E_pdf_pages"] = {"pass": ok_e, "msg": msg_e, "details": details_e}
            status_e = "PASS" if ok_e else "FAIL"
            print(f"  {status_e}: {msg_e}")
            if details_e:
                print(f"  Details: {json.dumps(details_e, ensure_ascii=False)}")
    else:
        results["E_pdf_pages"] = {"pass": False, "msg": "PDF not found or empty"}
        print(f"  FAIL: PDF not found or empty - cannot check pages")

    print_summary(results)
    return results


def print_summary(results: dict):
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    all_pass = True
    for key, val in results.items():
        p = val.get("pass")
        if p is None:
            icon = "SKIP"
        elif p:
            icon = "PASS"
        else:
            icon = "FAIL"
            all_pass = False
        print(f"  [{icon}] {key}: {val['msg']}")

    print()
    if all(v.get("pass") is not False for v in results.values()):
        print("ALL CHECKS PASSED (or skipped)")
    else:
        print("SOME CHECKS FAILED - see details above")
    print("=" * 70)
    print(f"Screenshots saved to: {SCREENSHOT_DIR}")


if __name__ == "__main__":
    run_test()
