"""MinerU PDF-to-Markdown conversion service using the hosted agent API."""

import http.client
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

AGENT_CREATE_ENDPOINT = "/api/v1/agent/parse/file"
AGENT_STATUS_ENDPOINT = "/api/v1/agent/parse"

FINISHED_STATES = {"done", "failed"}
MAX_POLL_ATTEMPTS = 120
POLL_INTERVAL_SECONDS = 3


class MinerUService:
    """Handles PDF → Markdown conversion via the hosted MinerU API."""

    def __init__(self):
        self.base_url = settings.mineru_base_url.rstrip("/")
        self.token = settings.mineru_api_token

    def convert_pdf(self, pdf_path: str, output_dir: str) -> dict:
        """Convert a single PDF file to Markdown via the MinerU API.

        Returns a dict with keys:
            - success: bool
            - markdown: str
            - json_content: dict
            - error: str
        """
        pdf_path = os.path.abspath(pdf_path)
        if not os.path.exists(pdf_path):
            return {"success": False, "error": f"PDF not found: {pdf_path}"}

        file_size = os.path.getsize(pdf_path)
        if file_size > 200 * 1024 * 1024:
            return {"success": False, "error": "File exceeds 200MB limit"}

        output_dir = os.path.abspath(output_dir)
        os.makedirs(output_dir, exist_ok=True)

        try:
            task_id, file_url = self._create_task(pdf_path)
            logger.info("MinerU task created: %s for %s", task_id, os.path.basename(pdf_path))

            self._upload_file(file_url, pdf_path)
            markdown_url = self._wait_for_task(task_id)
            if not markdown_url:
                return {"success": False, "error": "MinerU task completed without markdown output"}

            markdown = self._download_markdown(markdown_url, output_dir)
            return {
                "success": True,
                "markdown": markdown,
                "json_content": {"task_id": task_id, "markdown_url": markdown_url},
                "error": "",
            }
        except Exception as e:
            logger.error("MinerU conversion failed: %s", e)
            return {"success": False, "error": str(e)}

    def _create_task(self, pdf_path: str) -> tuple[str, str]:
        payload = json.dumps({"file_name": os.path.basename(pdf_path)}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{AGENT_CREATE_ENDPOINT}",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"MinerU create-task error HTTP {e.code}: {body}")

        data = result.get("data", {})
        task_id = data.get("task_id")
        file_url = data.get("file_url")
        if not task_id or not file_url:
            raise RuntimeError(f"Unexpected MinerU create-task response: {result}")
        return task_id, file_url

    def _upload_file(self, file_url: str, pdf_path: str):
        parsed = urllib.parse.urlsplit(file_url)
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        with open(pdf_path, "rb") as f:
            body = f.read()
        conn = http.client.HTTPSConnection(parsed.netloc, timeout=120)

        try:
            conn.putrequest("PUT", path)
            conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(body)
            resp = conn.getresponse()
            resp_body = resp.read().decode("utf-8", errors="replace")
            if resp.status >= 400:
                raise RuntimeError(f"MinerU upload error HTTP {resp.status}: {resp_body}")
        finally:
            conn.close()

    def _wait_for_task(self, task_id: str) -> str:
        for attempt in range(MAX_POLL_ATTEMPTS):
            status = self._check_task_status(task_id)
            state = status.get("state", "")
            if state in FINISHED_STATES:
                if state == "failed":
                    raise RuntimeError(f"MinerU task {task_id} failed: {status}")
                return status.get("markdown_url", "")
            logger.info(
                "MinerU task %s state: %s (attempt %d/%d)",
                task_id,
                state,
                attempt + 1,
                MAX_POLL_ATTEMPTS,
            )
            time.sleep(POLL_INTERVAL_SECONDS)

        raise RuntimeError(f"MinerU task {task_id} timed out")

    def _check_task_status(self, task_id: str) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}{AGENT_STATUS_ENDPOINT}/{task_id}",
            headers={"Authorization": f"Bearer {self.token}"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("data", data)

    def _download_markdown(self, markdown_url: str, output_dir: str) -> str:
        req = urllib.request.Request(markdown_url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                markdown = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"MinerU markdown download error HTTP {e.code}: {body}")

        markdown_path = os.path.join(output_dir, "full.md")
        with open(markdown_path, "w", encoding="utf-8") as f:
            f.write(markdown)
        return markdown


_mineru_service: Optional[MinerUService] = None


def get_mineru_service() -> MinerUService:
    global _mineru_service
    if _mineru_service is None:
        _mineru_service = MinerUService()
    return _mineru_service
