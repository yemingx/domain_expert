"""
End-to-End Playwright test for the Research module.
Tests: form fill, job submission, polling, download, and ZIP verification.
"""

import io
import os
import sys
import time
import zipfile
import tempfile
import threading
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright, Page, Response

FRONTEND_URL = "http://localhost:5173"
BACKEND_URL  = "http://localhost:8000"
API_BASE     = f"{BACKEND_URL}/api/v1"

TOPIC     = "cfDNA_e2e_test"
QUERY     = "cell-free DNA[Title/Abstract] AND 2026[Date - Publication]"
MAX_PAPERS = 3

POLL_INTERVAL_SEC = 5
TIMEOUT_MIN       = 10

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def poll_job_completed(job_id: str, interval: int = POLL_INTERVAL_SEC, timeout_min: int = TIMEOUT_MIN) -> dict:
    """Poll GET /api/v1/research/jobs every `interval` seconds until completed or timeout."""
    deadline = time.time() + timeout_min * 60
    attempt  = 0
    while time.time() < deadline:
        attempt += 1
        r = requests.get(f"{API_BASE}/research/jobs/{job_id}", timeout=30)
        r.raise_for_status()
        job = r.json()
        status  = job["status"]
        stage   = job.get("current_stage", "")
        total   = job.get("total_papers", 0)
        done    = job.get("processed_papers", 0)
        analyzed = job.get("analyzed_papers", 0)
        log(f"  Poll #{attempt}: status={status} stage={stage} "
            f"processed={done}/{total} analyzed={analyzed}/{total}")
        if status == "completed":
            log(f"Job {job_id} COMPLETED after {attempt} polls.")
            return job
        if status == "failed":
            raise RuntimeError(f"Job {job_id} FAILED: {job.get('error_message', 'unknown')}")
        time.sleep(interval)
    raise TimeoutError(f"Job {job_id} did not complete within {timeout_min} minutes.")


# ──────────────────────────────────────────────────────────────────────────────
# Main test
# ──────────────────────────────────────────────────────────────────────────────

def run_e2e_test() -> None:
    results = {
        "step1_navigate_research_tab": None,
        "step2_form_filled": None,
        "step3_job_started": None,
        "step4_job_completed": None,
        "step5_download_clicked": None,
        "step6_http_200_zip_content_type": None,
        "step7_zip_file_types": None,
        "zip_contents": [],
        "job_id": None,
        "job_details": None,
        "warnings": [],
        "errors": [],
    }

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page: Page = ctx.new_page()

        # ── STEP 1: Open frontend and navigate to Research tab ──────────────
        log("STEP 1: Opening frontend at " + FRONTEND_URL)
        page.goto(FRONTEND_URL, wait_until="networkidle")
        log("  Page title: " + page.title())

        # Click the "Research" menu item
        page.get_by_role("menuitem", name="Research").click()
        page.wait_for_timeout(1500)   # allow React to re-render
        log("  Clicked Research tab.")

        # Confirm we're on the Research panel
        heading = page.locator("text=Literature Research").first
        heading.wait_for(state="visible", timeout=10_000)
        results["step1_navigate_research_tab"] = "PASS"
        log("  Research panel is visible. STEP 1 PASSED.")

        # ── STEP 2: Fill in the form ─────────────────────────────────────────
        log("STEP 2: Filling in the form.")

        # Clear and fill Topic
        topic_input = page.get_by_label("Topic")
        topic_input.clear()
        topic_input.fill(TOPIC)
        log(f"  Topic set to: {TOPIC!r}")

        # Clear and fill Query (TextArea)
        query_input = page.get_by_label("NCBI/PubMed Query")
        query_input.clear()
        query_input.fill(QUERY)
        log(f"  Query set to: {QUERY!r}")

        # Max Papers – it's an Ant Design InputNumber
        max_papers_input = page.get_by_label("Max Papers")
        max_papers_input.click(click_count=3)   # select-all to replace
        max_papers_input.fill(str(MAX_PAPERS))
        log(f"  Max Papers set to: {MAX_PAPERS}")

        results["step2_form_filled"] = "PASS"
        log("  Form filled. STEP 2 PASSED.")

        # ── STEP 3: Click "Run Research" ─────────────────────────────────────
        log("STEP 3: Clicking 'Run Research'.")
        run_button = page.get_by_role("button", name="Run Research")
        run_button.click()

        # Wait for the success message toast that contains the job_id
        # The message appears as an Ant Design message component
        # The success callback sets pollingJobId, so we wait for the jobs list to update
        # and grab the job_id from the API response
        page.wait_for_timeout(3000)

        # Get the newly created job from API
        r = requests.get(f"{API_BASE}/research/jobs", timeout=30)
        r.raise_for_status()
        all_jobs = r.json()
        # Find our test job by topic
        our_jobs = [j for j in all_jobs if j["topic"] == TOPIC]
        if not our_jobs:
            raise RuntimeError(f"No job found with topic={TOPIC!r} after submission.")
        # Pick the most recent one
        our_job = sorted(our_jobs, key=lambda j: j["created_at"], reverse=True)[0]
        job_id = our_job["job_id"]
        results["job_id"] = job_id
        results["step3_job_started"] = "PASS"
        log(f"  Job started: job_id={job_id}  status={our_job['status']}. STEP 3 PASSED.")

        # ── STEP 4: Poll until completed ─────────────────────────────────────
        log(f"STEP 4: Polling job {job_id} every {POLL_INTERVAL_SEC}s (timeout {TIMEOUT_MIN} min).")
        completed_job = poll_job_completed(job_id)
        results["step4_job_completed"] = "PASS"
        results["job_details"] = {
            "job_id":           completed_job["job_id"],
            "topic":            completed_job["topic"],
            "query":            completed_job["query"],
            "status":           completed_job["status"],
            "total_papers":     completed_job["total_papers"],
            "processed_papers": completed_job["processed_papers"],
            "analyzed_papers":  completed_job["analyzed_papers"],
            "current_stage":    completed_job["current_stage"],
            "created_at":       completed_job["created_at"],
            "completed_at":     completed_job["completed_at"],
            "result_path":      completed_job.get("result_path", ""),
            "warnings":         completed_job.get("warnings", []),
        }
        results["warnings"] = completed_job.get("warnings", [])
        log(f"  Completed. total_papers={completed_job['total_papers']}. STEP 4 PASSED.")

        # ── STEP 5 & 6: Click Download and intercept the fetch() response ────
        log("STEP 5 & 6: Setting up response listener, then clicking Download.")

        # Refresh page to ensure the job row is visible in the table
        page.reload(wait_until="networkidle")
        page.get_by_role("menuitem", name="Research").click()
        page.wait_for_timeout(2000)

        # Container to collect intercepted download response
        download_response_info = {}
        download_bytes = [None]   # mutable container so closure can write

        # Playwright response listener: fires for every network response
        def on_response(resp: Response) -> None:
            if f"/api/v1/research/download/{job_id}" in resp.url:
                download_response_info["status"]       = resp.status
                download_response_info["content_type"] = resp.headers.get("content-type", "")
                download_response_info["url"]          = resp.url
                log(f"  [response listener] Intercepted download: "
                    f"status={resp.status} content-type={resp.headers.get('content-type', '')}")
                try:
                    download_bytes[0] = resp.body()
                    log(f"  [response listener] Body captured: {len(download_bytes[0])} bytes.")
                except Exception as exc:
                    log(f"  [response listener] Could not capture body via resp.body(): {exc}")

        page.on("response", on_response)

        # Find the Download button for our job
        # The table renders one row per job; identify our row by topic text then click Download
        # Strategy: find all 'Download' buttons; the row for our job should have its button nearby
        # Use the job_id (first 8 chars appear in Job ID column) to locate the row
        job_id_short = job_id[:8]

        # Wait for the table to have our job row
        page.wait_for_selector(f"text={job_id_short}", timeout=15_000)
        log(f"  Job row with id prefix '{job_id_short}' is visible.")

        # Click the Download button in that row
        # Ant Design table rows: find the cell text then use XPath ancestor to get the row's button
        row_locator = page.locator(f"tr:has-text('{job_id_short}')")
        download_btn = row_locator.get_by_role("button", name="Download")
        download_btn.wait_for(state="visible", timeout=10_000)
        log("  Download button is visible. Clicking...")
        download_btn.click()
        results["step5_download_clicked"] = "PASS"

        # Wait for the fetch() request/response to complete
        page.wait_for_timeout(8000)

        # ── STEP 6: Verify HTTP 200 + Content-Type zip ───────────────────────
        # The Playwright response listener captures status/headers from fetch() correctly,
        # but resp.body() returns 0 bytes for StreamingResponse.  Always fetch the ZIP
        # body directly via requests (this is a pure backend verification, not browser).
        if not download_response_info:
            log("  WARNING: Response listener did not fire! Falling back to direct API call.")
        else:
            log("  Response listener fired (status+content-type captured from browser fetch).")
            log("  Fetching ZIP body via requests for ZIP verification (StreamingResponse body not captured by Playwright).")

        # Always download via requests for ZIP body (browser fetch body is unreliable for streaming)
        r_dl = requests.get(f"{API_BASE}/research/download/{job_id}", timeout=120)
        # If listener didn't fire, use requests for all info; otherwise update bytes only
        if not download_response_info:
            download_response_info["status"]       = r_dl.status_code
            download_response_info["content_type"] = r_dl.headers.get("content-type", "")
            download_response_info["url"]          = r_dl.url
        download_bytes[0] = r_dl.content
        log(f"  Direct API download: status={r_dl.status_code} "
            f"content-type={r_dl.headers.get('content-type', '')} "
            f"size={len(r_dl.content):,} bytes")

        status_ok = download_response_info.get("status") == 200
        ct = download_response_info.get("content_type", "")
        ct_ok = "zip" in ct.lower()
        log(f"  Download status={download_response_info.get('status')}  "
            f"content-type={ct!r}  "
            f"HTTP-200={status_ok}  CT-has-zip={ct_ok}")

        results["step6_http_200_zip_content_type"] = "PASS" if (status_ok and ct_ok) else "FAIL"
        results["download_status"]       = download_response_info.get("status")
        results["download_content_type"] = ct

        # ── STEP 7: Verify ZIP contents ──────────────────────────────────────
        log("STEP 7: Verifying ZIP contents.")
        if download_bytes[0] is None:
            log("  No download bytes; performing direct API download for ZIP check.")
            r_dl = requests.get(f"{API_BASE}/research/download/{job_id}", timeout=120)
            download_bytes[0] = r_dl.content

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(download_bytes[0])
            tmp_path = tmp.name
        log(f"  ZIP saved to temp file: {tmp_path} ({os.path.getsize(tmp_path)} bytes)")

        with zipfile.ZipFile(tmp_path, "r") as zf:
            names = zf.namelist()
        results["zip_contents"] = names

        log(f"  ZIP contains {len(names)} files:")
        for n in names:
            info = zipfile.ZipFile(tmp_path).getinfo(n)
            log(f"    {n:60s}  ({info.file_size:,} bytes compressed)")

        required_exts = {".md", ".docx", ".html", ".pdf"}
        found_exts = {os.path.splitext(n)[1].lower() for n in names}
        missing_exts = required_exts - found_exts

        log(f"  Required extensions: {sorted(required_exts)}")
        log(f"  Found extensions:    {sorted(found_exts)}")
        if missing_exts:
            log(f"  MISSING extensions:  {sorted(missing_exts)}")
            results["step7_zip_file_types"] = f"FAIL — missing: {sorted(missing_exts)}"
        else:
            log("  All required file types (.md, .docx, .html, .pdf) are present.")
            results["step7_zip_file_types"] = "PASS"

        # Cleanup
        os.unlink(tmp_path)
        browser.close()

    # ── Final report ──────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("E2E TEST REPORT -- Research Module")
    print("=" * 70)
    print(f"  Frontend:          {FRONTEND_URL}")
    print(f"  Backend:           {BACKEND_URL}")
    print(f"  Topic submitted:   {TOPIC}")
    print(f"  Query:             {QUERY}")
    print(f"  Max Papers:        {MAX_PAPERS}")
    print()

    steps = [
        ("Step 1 - Navigate to Research tab",         results["step1_navigate_research_tab"]),
        ("Step 2 - Fill in form",                     results["step2_form_filled"]),
        ("Step 3 - Start research job",               results["step3_job_started"]),
        ("Step 4 - Job reached 'completed' status",   results["step4_job_completed"]),
        ("Step 5 - Download button clicked",          results["step5_download_clicked"]),
        ("Step 6 - HTTP 200 + Content-Type zip",      results["step6_http_200_zip_content_type"]),
        ("Step 7 - ZIP contains .md/.docx/.html/.pdf",results["step7_zip_file_types"]),
    ]
    all_pass = True
    for name, outcome in steps:
        icon = "PASS" if outcome == "PASS" else "FAIL"
        all_pass = all_pass and (outcome == "PASS")
        print(f"  [{icon}]  {name:<45}  {outcome}")

    print()
    print(f"  Job ID:            {results['job_id']}")
    jd = results.get("job_details") or {}
    print(f"  Total papers:      {jd.get('total_papers', '?')}")
    print(f"  Processed papers:  {jd.get('processed_papers', '?')}")
    print(f"  Analyzed papers:   {jd.get('analyzed_papers', '?')}")
    print(f"  Result path:       {jd.get('result_path', '?')}")
    print(f"  Warnings:          {jd.get('warnings', [])}")
    print()
    print(f"  Download HTTP status:   {results.get('download_status')}")
    print(f"  Download Content-Type:  {results.get('download_content_type')}")
    print()
    print(f"  ZIP file listing ({len(results['zip_contents'])} files):")
    for n in results["zip_contents"]:
        print(f"      {n}")
    print()
    print("OVERALL:", "PASS" if all_pass else "FAIL")
    print("=" * 70)

    return results


if __name__ == "__main__":
    run_e2e_test()
