"""
Bidirectional Sync Test: Frontend job deletion ↔ Backend file deletion.

Direction 1: API delete → result folder deleted from disk
Direction 2: Manual folder delete → job disappears from API list (stale purge)
Direction 3: Frontend browser sync via Playwright
"""

import json
import os
import shutil
import sys
import time
from pathlib import Path

import requests

# ── Constants ──────────────────────────────────────────────────────────────────
BACKEND_URL = "http://localhost:8000/api/v1"
FRONTEND_URL = "http://localhost:5173"
SCREENSHOT_DIR = Path(
    "C:/Users/xieyeming1/Downloads/git_repo/domain_expert/backend/tests/e2e_screenshots/delete_sync"
)
RESULT_BASE = Path(
    "C:/Users/xieyeming1/Downloads/git_repo/domain_expert/backend/literature_research/result"
)
DATA_RESEARCH = Path(
    "C:/Users/xieyeming1/Downloads/git_repo/domain_expert/backend/data/research"
)
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# ── Result tracking ────────────────────────────────────────────────────────────
results: list[dict] = []


def check(name: str, passed: bool, detail: str = ""):
    status = "PASS" if passed else "FAIL"
    entry = {"check": name, "status": status, "detail": detail}
    results.append(entry)
    marker = "[PASS]" if passed else "[FAIL]"
    print(f"  {marker} {name}" + (f" — {detail}" if detail else ""))
    return passed


# ── Helpers ────────────────────────────────────────────────────────────────────

def post_job(topic: str, query: str, max_papers: int = 1) -> dict:
    resp = requests.post(
        f"{BACKEND_URL}/research/run",
        json={"topic": topic, "query": query, "max_papers": max_papers},
        timeout=(10, 60),
    )
    resp.raise_for_status()
    return resp.json()


def poll_job(job_id: str, timeout_s: int = 300) -> dict:
    """Poll until status is completed or failed, or timeout.

    Uses a long read timeout (60 s) so we don't trip on the backend being
    temporarily busy while running a research job, and retries on transient
    connection/read errors.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            resp = requests.get(
                f"{BACKEND_URL}/research/jobs/{job_id}",
                timeout=(10, 60),  # (connect, read)
            )
            if resp.status_code == 404:
                return {"status": "not_found"}
            resp.raise_for_status()
            data = resp.json()
            if data["status"] in ("completed", "failed"):
                return data
            print(
                f"    ... polling job {job_id[:8]} — "
                f"status={data['status']} stage={data.get('current_stage','')}"
            )
        except Exception as poll_err:
            print(f"    ... poll error (will retry): {type(poll_err).__name__}: {poll_err}")
        time.sleep(5)
    return {"status": "timeout"}


def find_result_dir(topic_prefix: str) -> Path | None:
    """Find the result directory whose name starts with topic_prefix."""
    if not RESULT_BASE.exists():
        return None
    for d in RESULT_BASE.iterdir():
        if d.is_dir() and d.name.startswith(topic_prefix):
            return d
    return None


# ── Direction 1 ───────────────────────────────────────────────────────────────

def test_direction_1():
    print("\n" + "=" * 70)
    print("DIRECTION 1: API delete → result folder deleted from disk")
    print("=" * 70)

    # Step 1: Submit job
    print("\n[1] Submitting DEL_TEST job...")
    try:
        job = post_job(
            topic="DEL_TEST",
            query="NIPD[Title/Abstract] AND monogenic[Title/Abstract]",
            max_papers=1,
        )
        job_id = job["job_id"]
        check("D1-submit: job created", True, f"job_id={job_id[:8]}")
    except Exception as e:
        check("D1-submit: job created", False, str(e))
        return

    # Step 2: Poll until completed
    print(f"\n[2] Polling job {job_id[:8]} (timeout 5 min)...")
    final = poll_job(job_id, timeout_s=300)
    status = final.get("status")
    check(
        "D1-poll: job completed",
        status == "completed",
        f"status={status}" + (f" error={final.get('error_message','')[:80]}" if status == "failed" else ""),
    )

    if status != "completed":
        print("  WARNING: Job did not complete — skipping folder checks for D1")
        # Still attempt deletion of any partial result
        result_path = final.get("result_path", "")
        result_dir = Path(result_path).parent if result_path else find_result_dir("DEL_TEST")
        if result_dir and result_dir.exists():
            print(f"  Partial result dir found: {result_dir}")
        return

    # Step 3: Note result_path
    result_path = final.get("result_path", "")
    print(f"\n[3] result_path = {result_path}")
    check("D1-result_path: field populated", bool(result_path), result_path or "(empty)")

    # Step 4: Find result directory
    result_dir: Path | None = None
    if result_path:
        result_dir = Path(result_path).parent
    if not result_dir or not result_dir.exists():
        # Fallback: search by topic prefix
        result_dir = find_result_dir("DEL_TEST")
    print(f"[4] result_dir = {result_dir}")

    # Step 5: Verify folder EXISTS before deletion
    folder_exists_before = result_dir is not None and result_dir.exists()
    check(
        "D1-before: result folder exists",
        folder_exists_before,
        str(result_dir) if result_dir else "no dir found",
    )

    # Step 6: DELETE via API
    print(f"\n[6] Calling DELETE /api/v1/research/jobs/{job_id[:8]}...")
    try:
        del_resp = requests.delete(f"{BACKEND_URL}/research/jobs/{job_id}", timeout=(10, 60))
        del_resp.raise_for_status()
        del_data = del_resp.json()
        check("D1-delete: API returned 200", True, str(del_data))
    except Exception as e:
        check("D1-delete: API returned 200", False, str(e))

    # Step 7: Verify folder NO LONGER EXISTS
    time.sleep(1)  # small grace period for I/O
    folder_exists_after = result_dir is not None and result_dir.exists()
    check(
        "D1-after: result folder deleted from disk",
        not folder_exists_after,
        str(result_dir),
    )

    # Step 8: Verify GET returns 404
    get_resp = requests.get(f"{BACKEND_URL}/research/jobs/{job_id}", timeout=(10, 60))
    check(
        "D1-after: GET job returns 404",
        get_resp.status_code == 404,
        f"HTTP {get_resp.status_code}",
    )


# ── Direction 2 ───────────────────────────────────────────────────────────────

def test_direction_2():
    print("\n" + "=" * 70)
    print("DIRECTION 2: Manual folder delete → job disappears from API list")
    print("=" * 70)

    # Step 1: Submit second job
    print("\n[1] Submitting STALE_TEST job...")
    try:
        job = post_job(
            topic="STALE_TEST",
            query="NIPD[Title/Abstract] AND monogenic[Title/Abstract]",
            max_papers=1,
        )
        job_id = job["job_id"]
        check("D2-submit: job created", True, f"job_id={job_id[:8]}")
    except Exception as e:
        check("D2-submit: job created", False, str(e))
        return

    # Step 2: Wait for completion
    print(f"\n[2] Polling job {job_id[:8]} (timeout 5 min)...")
    final = poll_job(job_id, timeout_s=300)
    status = final.get("status")
    check(
        "D2-poll: job completed",
        status == "completed",
        f"status={status}",
    )

    if status != "completed":
        print("  WARNING: Job did not complete — skipping stale-purge checks for D2")
        return

    result_path = final.get("result_path", "")
    print(f"\n[3] result_path = {result_path}")

    # Step 3: Verify job appears in GET /research/jobs list
    list_resp = requests.get(f"{BACKEND_URL}/research/jobs", timeout=(10, 60))
    list_resp.raise_for_status()
    job_ids_before = [j["job_id"] for j in list_resp.json()]
    check(
        "D2-before: STALE_TEST appears in job list",
        job_id in job_ids_before,
        f"found={job_id in job_ids_before}, total_jobs={len(job_ids_before)}",
    )

    # Step 4: Manually delete result folder
    result_dir: Path | None = None
    if result_path:
        result_dir = Path(result_path).parent
    if not result_dir or not result_dir.exists():
        result_dir = find_result_dir("STALE_TEST")

    print(f"\n[4] Manually deleting result folder: {result_dir}")
    if result_dir and result_dir.exists():
        shutil.rmtree(result_dir)
        check("D2-manual-delete: folder removed from disk", not result_dir.exists(), str(result_dir))
    else:
        check("D2-manual-delete: folder removed from disk", False, "folder not found before deletion")

    # Step 5: Call GET /research/jobs (triggers stale purge)
    print("\n[5] Calling GET /api/v1/research/jobs (triggers stale purge)...")
    list_resp2 = requests.get(f"{BACKEND_URL}/research/jobs", timeout=(10, 60))
    list_resp2.raise_for_status()
    job_ids_after = [j["job_id"] for j in list_resp2.json()]

    # Step 6: Verify STALE_TEST no longer appears
    check(
        "D2-after: STALE_TEST NOT in job list",
        job_id not in job_ids_after,
        f"found={job_id in job_ids_after}, total_jobs={len(job_ids_after)}",
    )

    # Step 7: Verify JSON metadata file is also gone
    json_meta_path = DATA_RESEARCH / f"{job_id}.json"
    check(
        "D2-after: metadata JSON file deleted",
        not json_meta_path.exists(),
        str(json_meta_path),
    )


# ── Direction 3 ───────────────────────────────────────────────────────────────

def test_direction_3():
    print("\n" + "=" * 70)
    print("DIRECTION 3: Frontend browser sync via Playwright")
    print("=" * 70)

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        check("D3-playwright: import", False, "playwright not installed")
        return

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()

        # ── 3.1: Open frontend ──────────────────────────────────────────────
        print("\n[1] Opening frontend...")
        try:
            page.goto(FRONTEND_URL, wait_until="networkidle", timeout=30000)
            page.screenshot(path=str(SCREENSHOT_DIR / "d3_01_homepage.png"))
            check("D3-frontend: page loads", True, FRONTEND_URL)
        except Exception as e:
            check("D3-frontend: page loads", False, str(e))
            browser.close()
            return

        # ── 3.2: Navigate to Literature Research section ────────────────────
        print("\n[2] Navigating to Literature Research...")
        nav_found = False
        for selector in [
            "text=Literature Research",
            "[data-menu-id*='research']",
            "li:has-text('Literature')",
            ".ant-menu-item:has-text('Research')",
        ]:
            try:
                page.locator(selector).first.click(timeout=5000)
                page.wait_for_timeout(2000)
                nav_found = True
                break
            except Exception:
                continue

        if not nav_found:
            # Try clicking any sidebar item that might lead to research
            try:
                page.locator(".ant-menu-item").nth(3).click(timeout=3000)
                page.wait_for_timeout(2000)
                nav_found = True
            except Exception:
                pass

        page.screenshot(path=str(SCREENSHOT_DIR / "d3_02_nav.png"))
        check("D3-navigate: Literature Research section", nav_found, "nav click attempted")

        # ── 3.3: Confirm DEL_TEST and STALE_TEST not in list ───────────────
        print("\n[3] Checking DEL_TEST and STALE_TEST are absent from UI job list...")
        page.wait_for_timeout(3000)
        page_content = page.content()
        del_test_absent = "DEL_TEST" not in page_content
        stale_test_absent = "STALE_TEST" not in page_content
        page.screenshot(path=str(SCREENSHOT_DIR / "d3_03_list_before.png"))
        check("D3-list: DEL_TEST absent from frontend", del_test_absent, "")
        check("D3-list: STALE_TEST absent from frontend", stale_test_absent, "")

        # ── 3.4: Create UI_DEL_TEST job through the UI ────────────────────
        print("\n[4] Creating UI_DEL_TEST job through the UI...")
        ui_job_submitted = False
        try:
            # Fill topic field
            topic_input = page.locator("input[placeholder*='NIPD'], input[placeholder*='topic']").first
            topic_input.fill("UI_DEL_TEST")
            page.wait_for_timeout(300)

            # Fill query field
            query_input = page.locator("textarea").first
            query_input.fill("NIPD[Title/Abstract] AND monogenic[Title/Abstract]")
            page.wait_for_timeout(300)

            # Fill max_papers if there's an input for it
            try:
                max_input = page.locator("input[type='number'], .ant-input-number input").first
                max_input.fill("1")
                page.wait_for_timeout(300)
            except Exception:
                pass

            # Click Run Research button
            run_btn = page.locator("button:has-text('Run Research')").first
            run_btn.click(timeout=5000)
            page.wait_for_timeout(3000)
            page.screenshot(path=str(SCREENSHOT_DIR / "d3_04_after_submit.png"))
            ui_job_submitted = True
            check("D3-submit: UI_DEL_TEST job submitted via UI", True, "")
        except Exception as e:
            check("D3-submit: UI_DEL_TEST job submitted via UI", False, str(e))
            page.screenshot(path=str(SCREENSHOT_DIR / "d3_04_submit_failed.png"))

        # ── Wait for UI_DEL_TEST to appear in API list ──────────────────────
        ui_job_id = None
        if ui_job_submitted:
            print("\n    Waiting for UI_DEL_TEST job to appear in API...")
            deadline = time.time() + 60
            while time.time() < deadline:
                list_r = requests.get(f"{BACKEND_URL}/research/jobs", timeout=(10, 60))
                if list_r.ok:
                    for j in list_r.json():
                        if j.get("topic") == "UI_DEL_TEST":
                            ui_job_id = j["job_id"]
                            break
                if ui_job_id:
                    break
                time.sleep(5)
            check(
                "D3-submit: UI_DEL_TEST visible in API",
                ui_job_id is not None,
                f"job_id={ui_job_id[:8] if ui_job_id else 'not found'}",
            )

        # ── Wait for UI_DEL_TEST to complete ─────────────────────────────
        if ui_job_id:
            print(f"\n    Polling UI_DEL_TEST ({ui_job_id[:8]}) for completion...")
            final_ui = poll_job(ui_job_id, timeout_s=300)
            ui_status = final_ui.get("status")
            check(
                "D3-poll: UI_DEL_TEST completed",
                ui_status == "completed",
                f"status={ui_status}",
            )

            # Refresh frontend and wait for completed job to show
            page.reload(wait_until="networkidle")
            page.wait_for_timeout(4000)

            # Try to navigate back to research section after reload
            for selector in [
                "text=Literature Research",
                "[data-menu-id*='research']",
                "li:has-text('Literature')",
            ]:
                try:
                    page.locator(selector).first.click(timeout=4000)
                    page.wait_for_timeout(2000)
                    break
                except Exception:
                    continue

            page.wait_for_timeout(3000)
            page.screenshot(path=str(SCREENSHOT_DIR / "d3_05_ui_job_completed.png"))

            ui_result_path = final_ui.get("result_path", "")
            ui_result_dir = Path(ui_result_path).parent if ui_result_path else find_result_dir("UI_DEL_TEST")

            # ── 3.5: Click delete button in frontend ──────────────────────
            print("\n[5] Clicking delete button for UI_DEL_TEST...")
            delete_clicked = False

            # Wait for table to render jobs
            try:
                page.wait_for_selector(".ant-table-row", timeout=10000)
                page.wait_for_timeout(2000)
            except Exception:
                pass

            # Find the delete button for UI_DEL_TEST row
            try:
                # The job row should contain "UI_DEL_TEST" text
                row = page.locator(".ant-table-row").filter(has_text="UI_DEL_TEST").first
                delete_btn = row.locator("button:has-text('Delete'), .ant-btn-dangerous").first
                delete_btn.click(timeout=5000)
                page.wait_for_timeout(1500)
                page.screenshot(path=str(SCREENSHOT_DIR / "d3_06_popconfirm.png"))

                # Confirm the popconfirm
                confirm_btn = page.locator(".ant-popconfirm button:has-text('Delete'), .ant-popconfirm .ant-btn-dangerous").first
                confirm_btn.click(timeout=5000)
                page.wait_for_timeout(3000)
                delete_clicked = True
            except Exception as e:
                # Try alternative: find any delete button and confirm
                try:
                    del_btns = page.locator("button:has-text('Delete')").all()
                    for btn in del_btns:
                        if btn.is_visible():
                            btn.click(timeout=3000)
                            page.wait_for_timeout(1000)
                            # Look for popconfirm OK
                            ok_btn = page.locator(".ant-popover button:has-text('Delete'), .ant-popconfirm button:has-text('Delete')").first
                            ok_btn.click(timeout=3000)
                            page.wait_for_timeout(3000)
                            delete_clicked = True
                            break
                except Exception as e2:
                    print(f"    delete click failed: {e2}")

            page.screenshot(path=str(SCREENSHOT_DIR / "d3_07_after_delete.png"))
            check("D3-delete: delete button clicked and confirmed", delete_clicked, "")

            # ── 3.6: Verify job disappears from frontend list ────────────
            print("\n[6] Verifying UI_DEL_TEST disappears from UI...")
            # Allow time for the delete_job retry loop (up to 2 s sleep for locked PDFs)
            page.wait_for_timeout(6000)
            page_content_after = page.content()
            ui_job_absent_from_ui = "UI_DEL_TEST" not in page_content_after
            page.screenshot(path=str(SCREENSHOT_DIR / "d3_08_list_after_delete.png"))
            check(
                "D3-list: UI_DEL_TEST disappears from frontend after delete",
                ui_job_absent_from_ui,
                "",
            )

            # Also check via API that job is gone
            api_check = requests.get(f"{BACKEND_URL}/research/jobs/{ui_job_id}", timeout=(10, 60))
            check(
                "D3-api: UI_DEL_TEST returns 404 from API",
                api_check.status_code == 404,
                f"HTTP {api_check.status_code}",
            )

            # ── 3.7: Verify result folder deleted from disk ─────────────
            print("\n[7] Verifying result folder deleted from disk...")
            # Poll for up to 10 s to allow the backend's retry loop to finish
            folder_gone = False
            for _attempt in range(5):
                time.sleep(2)
                if ui_result_dir:
                    folder_gone = not ui_result_dir.exists()
                else:
                    folder_gone = find_result_dir("UI_DEL_TEST") is None
                if folder_gone:
                    break
            check(
                "D3-disk: UI_DEL_TEST result folder gone from disk",
                folder_gone,
                str(ui_result_dir) if ui_result_dir else "dir not found",
            )

        else:
            # Skip UI deletion test if job wasn't submitted
            check("D3-skip: UI_DEL_TEST not submitted, skipping delete test", False, "job submission failed")

        browser.close()


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "#" * 70)
    print("# BIDIRECTIONAL SYNC TEST: Frontend deletion <-> Backend file deletion")
    print("#" * 70)
    print(f"Backend:  {BACKEND_URL}")
    print(f"Frontend: {FRONTEND_URL}")
    print(f"Screenshots: {SCREENSHOT_DIR}")

    test_direction_1()
    test_direction_2()
    test_direction_3()

    # ── Summary ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    for r in results:
        marker = "[PASS]" if r["status"] == "PASS" else "[FAIL]"
        detail = f" — {r['detail']}" if r["detail"] else ""
        print(f"  {marker} {r['check']}{detail}")
    print(f"\nTotal: {passed} passed, {failed} failed out of {len(results)} checks")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
