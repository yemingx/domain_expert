"""
E2E Playwright test for Literature Research - SSHOT (screenshot PDF assembly) verification.

Verifies the new 2x device-pixel-ratio + PIL-based PDF assembly approach end-to-end:
  A. Output files listed with sizes
  B. _ppt.pdf exists AND size > 500 KB  (high-res screenshots should produce large PDFs)
  C. PDF page count == HTML slide count  (every slide captured)
  D. Slide page numbering correct        (grep slide-num shows proper X/Y values)
  E. Title font-size 1.1rem >= 4 occurrences for 2 papers

Usage:
    python tests/e2e_sshot_test.py
    FRONTEND_URL=http://localhost:5173 python tests/e2e_sshot_test.py
"""

import os
import re
import sys
import glob
import json
import time
import traceback
import urllib.request
import urllib.error

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

# Force UTF-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")
BACKEND_URL  = os.environ.get("BACKEND_URL",  "http://localhost:8000")

SCREENSHOT_DIR = r"C:\Users\xieyeming1\Downloads\git_repo\domain_expert\backend\tests\e2e_screenshots\sshot"
RESULT_BASE    = r"C:\Users\xieyeming1\Downloads\git_repo\domain_expert\backend\literature_research\result"

TOPIC      = "FSSHOT_TEST"
QUERY      = "NIPD[Title/Abstract] AND monogenic[Title/Abstract]"
MAX_PAPERS = 2

JOB_TIMEOUT_SEC  = 6 * 60   # 6 minutes as specified
POLL_INTERVAL_SEC = 5
MIN_PDF_SIZE_BYTES = 500 * 1024  # 500 KB

os.makedirs(SCREENSHOT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def screenshot(page, name: str) -> str:
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    page.screenshot(path=path, full_page=True)
    print(f"  [screenshot] {path}")
    return path


def api_get(path: str):
    url = f"{BACKEND_URL}{path}"
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.loads(resp.read().decode())


def api_post_json(path: str, payload: dict):
    url = f"{BACKEND_URL}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def check_backend_running() -> bool:
    try:
        urllib.request.urlopen(f"{BACKEND_URL}/api/v1/research/jobs", timeout=5)
        return True
    except Exception:
        return False


def check_frontend_running() -> bool:
    for port in ["5173", "3000", "8080"]:
        try:
            urllib.request.urlopen(f"http://localhost:{port}", timeout=5)
            return port
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Result-dir + file helpers
# ---------------------------------------------------------------------------

def find_result_dir(topic: str) -> str | None:
    pattern = os.path.join(RESULT_BASE, f"{topic}调研_*")
    dirs = glob.glob(pattern)
    if not dirs:
        return None
    return max(dirs, key=os.path.getmtime)


def find_ppt_html(result_dir: str) -> str | None:
    paths = glob.glob(os.path.join(result_dir, "*_ppt.html"))
    return paths[0] if paths else None


def find_ppt_pdf(result_dir: str) -> str | None:
    paths = glob.glob(os.path.join(result_dir, "*_ppt.pdf"))
    return paths[0] if paths else None


# ---------------------------------------------------------------------------
# Wait for job
# ---------------------------------------------------------------------------

def wait_for_job_completion(job_id: str, timeout_sec: int = JOB_TIMEOUT_SEC) -> dict:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        job = api_get(f"/api/v1/research/jobs/{job_id}")
        status  = job.get("status")
        stage   = job.get("current_stage", "")
        done    = job.get("processed_papers", 0)
        total   = job.get("total_papers", 0)
        elapsed = int(time.time() - (deadline - timeout_sec))
        print(f"  [poll +{elapsed}s] status={status} stage={stage} papers={done}/{total}")
        if status == "completed":
            return job
        if status == "failed":
            raise RuntimeError(f"Job failed: {job.get('error_message', 'unknown error')}")
        time.sleep(POLL_INTERVAL_SEC)
    raise TimeoutError(f"Job {job_id} did not complete within {timeout_sec}s")


# ---------------------------------------------------------------------------
# Verification checks
# ---------------------------------------------------------------------------

def check_A_list_files(result_dir: str) -> tuple[bool, str, list]:
    """A: List all output files with sizes."""
    all_files = []
    for f in sorted(os.listdir(result_dir)):
        fp = os.path.join(result_dir, f)
        if os.path.isfile(fp):
            size = os.path.getsize(fp)
            all_files.append({"name": f, "size": size, "path": fp})
    return (
        len(all_files) > 0,
        f"Found {len(all_files)} files in {result_dir}",
        all_files,
    )


def check_B_pdf_size(result_dir: str) -> tuple[bool, str, dict]:
    """B: _ppt.pdf exists AND size > 500 KB."""
    pdf_path = find_ppt_pdf(result_dir)
    if pdf_path is None:
        return False, f"_ppt.pdf NOT FOUND in {result_dir}", {}
    size = os.path.getsize(pdf_path)
    ok = size >= MIN_PDF_SIZE_BYTES
    msg = (
        f"OK: _ppt.pdf size={size:,} bytes ({size//1024} KB) >= 500 KB"
        if ok
        else f"FAIL: _ppt.pdf size={size:,} bytes ({size//1024} KB) < 500 KB threshold"
    )
    return ok, msg, {"path": pdf_path, "size": size, "threshold": MIN_PDF_SIZE_BYTES}


def check_C_page_count(html_path: str, pdf_path: str) -> tuple[bool, str, dict]:
    """C: PDF page count == HTML slide count."""
    # HTML slide count
    html_content = open(html_path, encoding="utf-8").read()
    html_slides = len(re.findall(r'<div class="slide ', html_content))

    # PDF page count via pypdf
    try:
        from pypdf import PdfReader
        pdf_lib = "pypdf"
    except ImportError:
        try:
            from PyPDF2 import PdfReader
            pdf_lib = "PyPDF2"
        except ImportError:
            return None, "Neither pypdf nor PyPDF2 is installed - skip page count check", {
                "html_slides": html_slides
            }

    try:
        reader = PdfReader(pdf_path)
        pdf_pages = len(reader.pages)
    except Exception as exc:
        return False, f"Could not read PDF: {exc}", {"html_slides": html_slides}

    ok = html_slides == pdf_pages
    details = {
        "html_slides": html_slides,
        "pdf_pages": pdf_pages,
        "pdf_lib": pdf_lib,
    }
    if ok:
        msg = f"OK: HTML slides={html_slides} == PDF pages={pdf_pages} (via {pdf_lib})"
    else:
        msg = f"MISMATCH: HTML slides={html_slides} != PDF pages={pdf_pages} (via {pdf_lib})"
    return ok, msg, details


def check_D_slide_numbering(html_path: str) -> tuple[bool, str, dict]:
    """D: Slide page numbering correct - check slide-num X/Y values.

    Design: cover (slide-cover) and end (slide-end) slides have no slide-num span.
    Only 'slide-page' slides carry slide-num spans.  The declared Y (total) in
    each span should equal the total number of ALL slide divs (cover+page+end).
    The X values should be sequential and contiguous (e.g. 2/7, 3/7, 4/7, 5/7, 6/7
    means pages 2-6 of 7 total slides are numbered – cover=1, end=7 are unnumbered).
    """
    content = open(html_path, encoding="utf-8").read()

    # Count slide divs by class
    all_slide_divs  = len(re.findall(r'<div class="slide ', content))
    cover_divs      = len(re.findall(r'class="slide slide-cover"', content))
    end_divs        = len(re.findall(r'class="slide slide-end"', content))
    page_divs       = len(re.findall(r'class="slide slide-page"', content))

    # Extract slide-num spans: flexible match for whitespace
    raw_nums = re.findall(r'class="slide-num"[^>]*>\s*(\d+)\s*/\s*(\d+)', content)

    # Also catch text content approach (more robust)
    if not raw_nums:
        text_vals = re.findall(r'slide-num[^>]*>([^<]+)<', content)
        for tv in text_vals:
            m = re.match(r'\s*(\d+)\s*/\s*(\d+)\s*', tv)
            if m:
                raw_nums.append((m.group(1), m.group(2)))

    if not raw_nums:
        return False, "No slide-num spans found in HTML", {
            "all_slide_divs": all_slide_divs,
            "cover_divs": cover_divs, "end_divs": end_divs, "page_divs": page_divs,
        }

    declared_totals = [int(y) for _, y in raw_nums]
    slide_indices   = [int(x) for x, _ in raw_nums]
    unique_totals   = set(declared_totals)
    first_3 = [f"{x}/{y}" for x, y in raw_nums[:3]]

    details = {
        "all_slide_divs": all_slide_divs,
        "cover_divs": cover_divs,
        "end_divs": end_divs,
        "page_divs": page_divs,
        "slide_num_spans_found": len(raw_nums),
        "first_3_values": first_3,
        "unique_declared_totals": list(unique_totals),
        "all_x_values": slide_indices,
    }

    failures = []

    # 1. Declared total must be consistent across all spans
    if len(unique_totals) > 1:
        failures.append(f"Inconsistent declared totals: {unique_totals}")

    # 2. Declared total Y must equal the actual total slide div count
    if declared_totals and declared_totals[0] != all_slide_divs:
        failures.append(
            f"Declared total Y={declared_totals[0]} != actual slide divs={all_slide_divs}"
        )

    # 3. X values must be strictly sequential (contiguous integers)
    if len(slide_indices) >= 2:
        expected_seq = list(range(slide_indices[0], slide_indices[0] + len(slide_indices)))
        if slide_indices != expected_seq:
            failures.append(f"Slide-num X values not sequential: {slide_indices}")

    # 4. Number of slide-num spans should equal number of slide-page divs
    if len(raw_nums) != page_divs:
        failures.append(
            f"slide-num span count={len(raw_nums)} != slide-page div count={page_divs}"
        )

    if failures:
        return False, "; ".join(failures), details

    return (
        True,
        f"OK: {len(raw_nums)} slide-num spans (pages {slide_indices[0]}-{slide_indices[-1]} of {declared_totals[0]}), "
        f"cover={cover_divs}, end={end_divs} (no slide-num on cover/end by design), "
        f"first 3: {first_3}",
        details,
    )


def check_E_title_font(html_path: str, n_papers: int) -> tuple[bool, str, dict]:
    """E: font-size:1.1rem count >= 4 for 2 papers (2 slides per paper x 2 papers)."""
    content = open(html_path, encoding="utf-8").read()
    count_11 = len(re.findall(r"font-size:1\.1rem", content))
    # Each paper generates 2 slides, each slide has a title with 1.1rem => min 2*n_papers
    min_expected = max(4, 2 * n_papers)
    ok = count_11 >= min_expected
    details = {
        "count_1_1rem": count_11,
        "min_expected": min_expected,
        "n_papers": n_papers,
    }
    if ok:
        msg = f"OK: font-size:1.1rem count={count_11} >= {min_expected}"
    else:
        msg = f"FAIL: font-size:1.1rem count={count_11} < {min_expected} (n_papers={n_papers})"
    return ok, msg, details


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_test():
    frontend_url = FRONTEND_URL  # local mutable copy

    print("=" * 70)
    print("E2E Test: Literature Research SSHOT (2x DPR + PIL PDF) verification")
    print("=" * 70)
    print(f"Frontend:   {frontend_url}")
    print(f"Backend:    {BACKEND_URL}")
    print(f"Topic:      {TOPIC}")
    print(f"Query:      {QUERY}")
    print(f"MaxPapers:  {MAX_PAPERS}")
    print(f"Screenshots:{SCREENSHOT_DIR}")
    print()

    # ------------------------------------------------------------------
    # Pre-flight
    # ------------------------------------------------------------------
    print("[0] Pre-flight checks...")
    if not check_backend_running():
        print(f"  ERROR: Backend not reachable at {BACKEND_URL}")
        sys.exit(1)
    print(f"  Backend: OK ({BACKEND_URL})")

    active_port = check_frontend_running()
    if active_port:
        frontend_url = f"http://localhost:{active_port}"
        print(f"  Frontend: OK ({frontend_url})")
    else:
        print(f"  WARNING: Frontend not reachable on ports 5173/3000/8080 - will try anyway")

    results = {}
    job_id  = None
    n_papers = MAX_PAPERS

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        try:
            # ------------------------------------------------------------------
            # Step 1: Navigate to frontend
            # ------------------------------------------------------------------
            print("\n[1] Navigating to frontend...")
            page.goto(frontend_url, wait_until="networkidle", timeout=30000)
            screenshot(page, "01_homepage")
            print(f"  Title: {page.title()}")

            # ------------------------------------------------------------------
            # Step 2: Navigate to Research section
            # ------------------------------------------------------------------
            print("\n[2] Finding Literature Research section...")
            research_menu = page.locator("text=Research").first
            research_menu.wait_for(state="visible", timeout=10000)
            research_menu.click()
            page.wait_for_load_state("networkidle")
            screenshot(page, "02_research_tab")
            print("  Clicked Research menu item")

            page.wait_for_selector("text=Literature Research", timeout=10000)
            print("  LiteratureResearch component visible")

            # ------------------------------------------------------------------
            # Step 3: Fill the form
            # ------------------------------------------------------------------
            print("\n[3] Filling research form...")

            topic_input = page.locator("input[placeholder='e.g., NIPD, CRISPR']")
            topic_input.wait_for(state="visible", timeout=10000)
            topic_input.click(click_count=3)
            topic_input.fill(TOPIC)
            print(f"  Topic: {TOPIC}")

            query_textarea = page.locator("textarea[placeholder*='NIPD']")
            query_textarea.wait_for(state="visible", timeout=5000)
            query_textarea.click(click_count=3)
            query_textarea.fill(QUERY)
            print(f"  Query: {QUERY}")

            max_input = page.locator(".ant-input-number-input").first
            max_input.click(click_count=3)
            max_input.fill(str(MAX_PAPERS))
            print(f"  MaxPapers: {MAX_PAPERS}")

            screenshot(page, "03_form_filled")

            # ------------------------------------------------------------------
            # Step 4: Check for existing FSSHOT_TEST completed job
            # ------------------------------------------------------------------
            print("\n[4] Checking for existing completed FSSHOT_TEST job...")
            existing_jobs = api_get("/api/v1/research/jobs")
            completed_jobs = [
                j for j in existing_jobs
                if j.get("topic") == TOPIC
                and j.get("status") == "completed"
                and j.get("result_path")
            ]

            if completed_jobs:
                # Reuse most recently completed
                final_job = sorted(completed_jobs, key=lambda x: x.get("created_at",""), reverse=True)[0]
                job_id   = final_job["job_id"]
                n_papers = final_job.get("total_papers", MAX_PAPERS)
                print(f"  Reusing existing completed job: {job_id} (papers={n_papers})")
                screenshot(page, "04_reusing_existing_job")
            else:
                print("  No completed FSSHOT_TEST job found - submitting new job...")

                # Capture job_id from response
                captured = []
                def on_response(response):
                    if "/api/v1/research/run" in response.url and response.status == 200:
                        try:
                            captured.append(response.json().get("job_id"))
                        except Exception:
                            pass
                page.on("response", on_response)

                run_btn = page.locator("button:has-text('Run Research')")
                run_btn.wait_for(state="visible", timeout=5000)
                run_btn.click()
                print("  Clicked 'Run Research'")

                page.wait_for_timeout(5000)
                screenshot(page, "04_job_submitted")

                if captured:
                    job_id = captured[0]
                    print(f"  Job started: {job_id}")
                else:
                    print("  job_id not captured from response, querying API...")
                    jobs = api_get("/api/v1/research/jobs")
                    matching = [j for j in jobs if j.get("topic") == TOPIC]
                    if matching:
                        job_id = matching[0]["job_id"]
                        print(f"  Found via API: {job_id}")
                    else:
                        raise RuntimeError(f"No job with topic={TOPIC} found in API")

                # ------------------------------------------------------------------
                # Step 5: Poll for completion (up to 6 minutes)
                # ------------------------------------------------------------------
                print(f"\n[5] Waiting for job {job_id} (up to {JOB_TIMEOUT_SEC}s)...")
                final_job = wait_for_job_completion(job_id, timeout_sec=JOB_TIMEOUT_SEC)
                n_papers  = final_job.get("total_papers", MAX_PAPERS)
                print(f"  Job completed! total_papers={n_papers}")

            screenshot(page, "05_job_completed_api_done")

            # Refresh UI to reflect completion
            page.wait_for_timeout(6000)
            screenshot(page, "06_ui_after_completion")

            # ------------------------------------------------------------------
            # Step 6: Trigger report generation if files not yet present
            # ------------------------------------------------------------------
            print("\n[6] Checking / generating report files...")
            result_dir_now = find_result_dir(TOPIC)
            html_exists = result_dir_now and find_ppt_html(result_dir_now)
            pdf_exists  = result_dir_now and find_ppt_pdf(result_dir_now)

            if html_exists and pdf_exists:
                print(f"  PPT HTML and PDF already present in: {result_dir_now}")
                screenshot(page, "07_files_already_exist")
            else:
                print("  PPT files missing - clicking '生成报告'...")
                # Reload to ensure the completed job row is visible
                page.reload(wait_until="networkidle")
                page.wait_for_timeout(2000)
                page.locator("text=Research").first.click()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(2000)

                convert_btn = page.locator("button:has-text('生成报告')").first
                if convert_btn.count() > 0 and convert_btn.is_visible():
                    with page.expect_download(timeout=180000) as dl_info:
                        convert_btn.click()
                    dl = dl_info.value
                    dl_path = os.path.join(SCREENSHOT_DIR, dl.suggested_filename)
                    dl.save_as(dl_path)
                    print(f"  Downloaded zip: {dl.suggested_filename} → {dl_path}")
                    screenshot(page, "07_after_convert")
                else:
                    print("  WARNING: '生成报告' button not found or not visible")
                    screenshot(page, "07_convert_btn_missing")

        except Exception as exc:
            print(f"\n  ERROR during browser steps: {exc}")
            traceback.print_exc()
            try:
                screenshot(page, "error_state")
            except Exception:
                pass
        finally:
            browser.close()

    # --------------------------------------------------------------------------
    # Verification Checks
    # --------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("VERIFICATION CHECKS")
    print("=" * 70)

    result_dir = find_result_dir(TOPIC)
    if not result_dir:
        print(f"\n  FATAL: No result directory found for topic={TOPIC} under {RESULT_BASE}")
        print("  Cannot perform checks A-E.")
        return results

    print(f"\n  Result directory: {result_dir}")
    html_path = find_ppt_html(result_dir)
    pdf_path  = find_ppt_pdf(result_dir)

    # ── Check A: List all output files ────────────────────────────────────────
    print("\n[A] Output files with sizes:")
    ok_a, msg_a, files_a = check_A_list_files(result_dir)
    results["A_output_files"] = {"pass": ok_a, "msg": msg_a, "files": files_a}
    for f in files_a:
        size_kb = f["size"] // 1024
        print(f"  {f['name']:60s}  {f['size']:>10,} bytes  ({size_kb:>6} KB)")
    print(f"  => {msg_a}")

    # ── Check B: PDF exists and size > 500 KB ─────────────────────────────────
    print("\n[B] _ppt.pdf exists and size > 500 KB:")
    ok_b, msg_b, details_b = check_B_pdf_size(result_dir)
    results["B_pdf_size"] = {"pass": ok_b, "msg": msg_b, "details": details_b}
    status_b = "PASS" if ok_b else "FAIL"
    print(f"  {status_b}: {msg_b}")

    # ── Check C: PDF pages == HTML slides ─────────────────────────────────────
    print("\n[C] PDF page count == HTML slide count:")
    if html_path and pdf_path:
        ok_c, msg_c, details_c = check_C_page_count(html_path, pdf_path)
        results["C_page_count"] = {"pass": ok_c, "msg": msg_c, "details": details_c}
        if ok_c is None:
            status_c = "SKIP"
        else:
            status_c = "PASS" if ok_c else "FAIL"
        print(f"  {status_c}: {msg_c}")
        print(f"  Details: {json.dumps(details_c, ensure_ascii=False)}")
    else:
        missing = []
        if not html_path: missing.append("_ppt.html")
        if not pdf_path:  missing.append("_ppt.pdf")
        msg = f"Cannot check: {', '.join(missing)} not found"
        results["C_page_count"] = {"pass": False, "msg": msg}
        print(f"  FAIL: {msg}")

    # ── Check D: Slide numbering ───────────────────────────────────────────────
    print("\n[D] Slide page numbering (slide-num X/Y values):")
    if html_path:
        ok_d, msg_d, details_d = check_D_slide_numbering(html_path)
        results["D_slide_numbering"] = {"pass": ok_d, "msg": msg_d, "details": details_d}
        status_d = "PASS" if ok_d else "FAIL"
        print(f"  {status_d}: {msg_d}")
        if "first_3_values" in details_d:
            print(f"  First 3 slide-num values: {details_d['first_3_values']}")
    else:
        results["D_slide_numbering"] = {"pass": False, "msg": "_ppt.html not found"}
        print(f"  FAIL: _ppt.html not found")

    # ── Check E: Title font-size 1.1rem count ─────────────────────────────────
    print("\n[E] Title font-size 1.1rem present (>= 4 for 2 papers):")
    if html_path:
        ok_e, msg_e, details_e = check_E_title_font(html_path, n_papers)
        results["E_title_font"] = {"pass": ok_e, "msg": msg_e, "details": details_e}
        status_e = "PASS" if ok_e else "FAIL"
        print(f"  {status_e}: {msg_e}")
        print(f"  Details: {json.dumps(details_e, ensure_ascii=False)}")
    else:
        results["E_title_font"] = {"pass": False, "msg": "_ppt.html not found"}
        print(f"  FAIL: _ppt.html not found")

    # --------------------------------------------------------------------------
    # Summary
    # --------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    pass_count = fail_count = skip_count = 0
    for key, val in results.items():
        p = val.get("pass")
        if p is None:
            icon = "SKIP"; skip_count += 1
        elif p:
            icon = "PASS"; pass_count += 1
        else:
            icon = "FAIL"; fail_count += 1
        print(f"  [{icon}] {key}: {val['msg']}")

    print()
    if fail_count == 0:
        print(f"ALL CHECKS PASSED ({pass_count} pass, {skip_count} skip)")
    else:
        print(f"SOME CHECKS FAILED: {fail_count} FAIL, {pass_count} PASS, {skip_count} SKIP")
    print("=" * 70)
    print(f"Screenshots saved to: {SCREENSHOT_DIR}")

    return results


if __name__ == "__main__":
    run_test()
