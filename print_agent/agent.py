"""
NBNE Print Agent
Polls manufacture.nbnesigns.co.uk for pending print jobs and forwards
the rendered command string to a thermal label printer on the local LAN
over TCP:9100 (raw socket).

Printer-agnostic: the agent does not know or care what command language
is in the payload. Django + the renderer decide that. The agent is
purely a transport layer between the job queue and the printer.
"""
import os
import socket
import time
import logging

import requests

LOG = logging.getLogger("nbne-print-agent")

API_BASE = os.environ["MANUFACTURE_API_BASE"]       # https://manufacture.nbnesigns.co.uk
API_TOKEN = os.environ["PRINT_AGENT_TOKEN"]
PRINTER_HOST = os.environ["PRINTER_HOST"]           # 192.168.1.50
PRINTER_PORT = int(os.environ.get("PRINTER_PORT", "9100"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS", "3"))
AGENT_ID = socket.gethostname()

HEADERS = {
    "Authorization": f"Token {API_TOKEN}",
    "X-Agent-Id": AGENT_ID,
}


def fetch_pending_jobs() -> list[dict]:
    r = requests.get(f"{API_BASE}/api/print-agent/pending/", headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()


def send_to_printer(command_string: str) -> None:
    """Send a printer-ready command string (ZPL, TSPL, etc.) over raw TCP."""
    with socket.create_connection((PRINTER_HOST, PRINTER_PORT), timeout=10) as sock:
        sock.sendall(command_string.encode("utf-8"))


def preflight_check() -> bool:
    """
    On agent startup, verify we can reach the printer before accepting jobs.
    Returns True if the printer socket is reachable.

    Does NOT try to validate the command language — we can't reliably detect
    that without printer-specific status queries. If the wrong language is
    configured in Django, the first print job will fail visibly.
    """
    try:
        with socket.create_connection((PRINTER_HOST, PRINTER_PORT), timeout=5):
            LOG.info("Printer reachable at %s:%s", PRINTER_HOST, PRINTER_PORT)
            return True
    except Exception as e:
        LOG.error("Printer unreachable at %s:%s — %s", PRINTER_HOST, PRINTER_PORT, e)
        return False


def report_result(job_id: int, status: str, error_message: str = "") -> None:
    payload = {"status": status}
    if error_message:
        payload["error_message"] = error_message
    requests.post(
        f"{API_BASE}/api/print-agent/jobs/{job_id}/complete/",
        headers=HEADERS,
        json=payload,
        timeout=10,
    ).raise_for_status()


def process_job(job: dict) -> None:
    job_id = job["id"]
    LOG.info("Processing job %s (%d labels)", job_id, job["quantity"])
    try:
        send_to_printer(job["command_payload"])
        report_result(job_id, "done")
        LOG.info("Job %s complete", job_id)
    except Exception as e:
        LOG.exception("Job %s failed", job_id)
        try:
            report_result(job_id, "error", str(e))
        except Exception:
            LOG.exception("Failed to report error for job %s", job_id)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    LOG.info("Starting agent %s, polling %s every %ds", AGENT_ID, API_BASE, POLL_INTERVAL)

    # Pre-flight: warn loudly but don't exit — printer may come online later
    if not preflight_check():
        LOG.warning("Printer not reachable on startup; will keep polling jobs regardless")

    while True:
        try:
            jobs = fetch_pending_jobs()
            for job in jobs:
                process_job(job)
        except Exception:
            LOG.exception("Poll cycle failed")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
