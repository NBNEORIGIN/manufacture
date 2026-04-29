"""
NBNE Print Agent
================

Polls manufacture.nbnesigns.co.uk for pending print jobs and forwards each
rendered command string to a thermal label printer.

Three transports supported, picked via PRINTER_TRANSPORT:

    tcp     — raw TCP socket, e.g. a Zebra GX430t at 192.168.1.50:9100
              PRINTER_HOST = 192.168.1.50
              PRINTER_PORT = 9100         (default)

    serial  — open a tty and write raw bytes. Use this for Bluetooth-paired
              printers like the PM-2411-BT after rfcomm-binding the device:
                  sudo rfcomm bind 0 <MAC>
              PRINTER_DEVICE = /dev/rfcomm0
              PRINTER_BAUD   = 9600        (default — most BT thermals)

    cups    — shell out to `lp -d <queue>` to send via the local CUPS daemon.
              PRINTER_QUEUE = pm2411bt

Printer routing (multi-printer setups):
    Set PRINTER_SLUG to the slug of a Printer record in Django. The agent
    sends `X-Printer: <slug>` on every poll; the backend only returns jobs
    targeting that printer (or legacy printer-less jobs). Without a slug,
    the agent runs in legacy mode and only claims printer-less jobs.

Printer-agnostic: the agent does not parse the payload. Django renders
ZPL / TSPL / ESC-POS as appropriate; the agent just forwards bytes.
"""
import logging
import os
import socket
import subprocess
import time

import requests

LOG = logging.getLogger("nbne-print-agent")

API_BASE = os.environ["MANUFACTURE_API_BASE"]
API_TOKEN = os.environ["PRINT_AGENT_TOKEN"]
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS", "3"))
AGENT_ID = os.environ.get("AGENT_ID") or socket.gethostname()
PRINTER_SLUG = os.environ.get("PRINTER_SLUG", "")  # optional routing key

# Transport selection
TRANSPORT = os.environ.get("PRINTER_TRANSPORT", "tcp").lower()

# tcp
PRINTER_HOST = os.environ.get("PRINTER_HOST", "")
PRINTER_PORT = int(os.environ.get("PRINTER_PORT", "9100"))

# serial / Bluetooth
PRINTER_DEVICE = os.environ.get("PRINTER_DEVICE", "")
PRINTER_BAUD = int(os.environ.get("PRINTER_BAUD", "9600"))

# CUPS
PRINTER_QUEUE = os.environ.get("PRINTER_QUEUE", "")

HEADERS = {
    "Authorization": f"Token {API_TOKEN}",
    "X-Agent-Id": AGENT_ID,
}
if PRINTER_SLUG:
    HEADERS["X-Printer"] = PRINTER_SLUG


# ─────────────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────────────


def fetch_pending_jobs() -> list[dict]:
    r = requests.get(f"{API_BASE}/api/print-agent/pending/", headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()


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


# ─────────────────────────────────────────────────────────────────────────────
# Transports
# ─────────────────────────────────────────────────────────────────────────────


def send_via_tcp(command_string: str) -> None:
    if not PRINTER_HOST:
        raise RuntimeError("PRINTER_HOST not set for tcp transport")
    with socket.create_connection((PRINTER_HOST, PRINTER_PORT), timeout=10) as sock:
        sock.sendall(command_string.encode("utf-8"))


def send_via_serial(command_string: str) -> None:
    if not PRINTER_DEVICE:
        raise RuntimeError("PRINTER_DEVICE not set for serial transport")
    # Open in binary write mode. PySerial would give finer control but isn't
    # required — most rfcomm-bound BT printers accept a plain raw stream.
    with open(PRINTER_DEVICE, "wb", buffering=0) as fh:
        fh.write(command_string.encode("utf-8"))


def send_via_cups(command_string: str) -> None:
    if not PRINTER_QUEUE:
        raise RuntimeError("PRINTER_QUEUE not set for cups transport")
    # lp reads the document from stdin when no file is given.
    proc = subprocess.run(
        ["lp", "-d", PRINTER_QUEUE, "-o", "raw"],
        input=command_string.encode("utf-8"),
        capture_output=True,
        timeout=20,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"lp exited {proc.returncode}: {proc.stderr.decode(errors='replace')}")


def send_to_printer(command_string: str) -> None:
    if TRANSPORT == "tcp":
        send_via_tcp(command_string)
    elif TRANSPORT == "serial":
        send_via_serial(command_string)
    elif TRANSPORT == "cups":
        send_via_cups(command_string)
    else:
        raise RuntimeError(f"Unknown PRINTER_TRANSPORT: {TRANSPORT}")


# ─────────────────────────────────────────────────────────────────────────────
# Lifecycle
# ─────────────────────────────────────────────────────────────────────────────


def preflight_check() -> bool:
    """Try to reach the printer at startup. Warns but doesn't exit on failure."""
    try:
        if TRANSPORT == "tcp":
            with socket.create_connection((PRINTER_HOST, PRINTER_PORT), timeout=5):
                LOG.info("Printer reachable at %s:%s (tcp)", PRINTER_HOST, PRINTER_PORT)
        elif TRANSPORT == "serial":
            if not os.path.exists(PRINTER_DEVICE):
                raise FileNotFoundError(PRINTER_DEVICE)
            LOG.info("Printer device present at %s (serial @ %d baud)", PRINTER_DEVICE, PRINTER_BAUD)
        elif TRANSPORT == "cups":
            proc = subprocess.run(["lpstat", "-p", PRINTER_QUEUE], capture_output=True, timeout=5)
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.decode(errors='replace').strip())
            LOG.info("CUPS queue '%s' is configured", PRINTER_QUEUE)
        else:
            LOG.error("Unknown PRINTER_TRANSPORT: %s", TRANSPORT)
            return False
        return True
    except Exception as e:
        LOG.error("Printer not ready (%s transport): %s", TRANSPORT, e)
        return False


def process_job(job: dict) -> None:
    job_id = job["id"]
    LOG.info("Processing job %s (%d labels, %s)", job_id, job["quantity"], job.get("command_language", "?"))
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
    LOG.info(
        "Starting agent id=%s slug=%s transport=%s polling %s every %ds",
        AGENT_ID, PRINTER_SLUG or '(legacy)', TRANSPORT, API_BASE, POLL_INTERVAL,
    )
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
