#!/usr/bin/env python3
"""
NBNE Manufacture — one-shot printer setup for Ubuntu workstations.

Pairs a Bluetooth thermal label printer (PM-2411-BT family is the default,
but works for any TSPL/ZPL device once you know its MAC), binds it to
/dev/rfcomm0, prints a sanity-check label, installs the print agent as a
systemd service, and starts it.

Run on the workstation that has the printer:

    sudo python3 setup_printer.py
    # or non-interactively
    sudo python3 setup_printer.py --mac AA:BB:CC:DD:EE:FF \\
        --token "<paste-from-toby>" --slug pm-2411-bt-bi --no-test-print

Idempotent — safe to re-run; existing files / services are updated in place.
"""
from __future__ import annotations

import argparse
import getpass
import os
import re
import shutil
import socket
import subprocess
import sys
import textwrap
import time
import urllib.request
from pathlib import Path

# ─── Defaults ────────────────────────────────────────────────────────────────

API_BASE_DEFAULT = "https://manufacture.nbnesigns.co.uk"
PRINTER_SLUG_DEFAULT = "pm-2411-bt-bi"
RFCOMM_INDEX = 0  # creates /dev/rfcomm0
INSTALL_DIR = Path("/opt/nbne-print-agent")
ENV_FILE = Path("/etc/nbne-print-agent.env")
SERVICE_FILE = Path("/etc/systemd/system/nbne-print-agent.service")
RFCOMM_SERVICE_FILE = Path("/etc/systemd/system/nbne-rfcomm-bind.service")
USER = "printagent"

MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")

# ─── Embedded payloads ───────────────────────────────────────────────────────
# The agent and unit files are embedded so this script is fully self-contained.
# When agent.py changes upstream, run `setup_printer.py --refresh-agent` and
# this script will re-fetch the latest version from the manufacture host.

AGENT_DOWNLOAD_PATH = "/api/print-agent/agent.py"  # served by the manufacture app

# Minimal embedded fallback so the installer works even when offline.
EMBEDDED_AGENT_PY = textwrap.dedent('''
    """
    NBNE Print Agent (embedded fallback). Forwards print jobs to a thermal
    printer over tcp / serial / cups. See repo print_agent/agent.py for the
    canonical version.
    """
    import logging, os, socket, subprocess, time
    import requests

    LOG = logging.getLogger("nbne-print-agent")
    API_BASE = os.environ["MANUFACTURE_API_BASE"]
    API_TOKEN = os.environ["PRINT_AGENT_TOKEN"]
    POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS", "3"))
    AGENT_ID = os.environ.get("AGENT_ID") or socket.gethostname()
    PRINTER_SLUG = os.environ.get("PRINTER_SLUG", "")
    TRANSPORT = os.environ.get("PRINTER_TRANSPORT", "serial").lower()
    PRINTER_HOST = os.environ.get("PRINTER_HOST", "")
    PRINTER_PORT = int(os.environ.get("PRINTER_PORT", "9100"))
    PRINTER_DEVICE = os.environ.get("PRINTER_DEVICE", "")
    PRINTER_QUEUE = os.environ.get("PRINTER_QUEUE", "")
    HEADERS = {"Authorization": f"Token {API_TOKEN}", "X-Agent-Id": AGENT_ID}
    if PRINTER_SLUG:
        HEADERS["X-Printer"] = PRINTER_SLUG

    def fetch_pending_jobs():
        r = requests.get(f"{API_BASE}/api/print-agent/pending/", headers=HEADERS, timeout=10)
        r.raise_for_status()
        return r.json()

    def report_result(job_id, status, error_message=""):
        payload = {"status": status}
        if error_message:
            payload["error_message"] = error_message
        requests.post(f"{API_BASE}/api/print-agent/jobs/{job_id}/complete/",
                      headers=HEADERS, json=payload, timeout=10).raise_for_status()

    def send_to_printer(payload):
        if TRANSPORT == "tcp":
            with socket.create_connection((PRINTER_HOST, PRINTER_PORT), timeout=10) as s:
                s.sendall(payload.encode("utf-8"))
        elif TRANSPORT == "serial":
            with open(PRINTER_DEVICE, "wb", buffering=0) as fh:
                fh.write(payload.encode("utf-8"))
        elif TRANSPORT == "cups":
            proc = subprocess.run(["lp", "-d", PRINTER_QUEUE, "-o", "raw"],
                                  input=payload.encode("utf-8"),
                                  capture_output=True, timeout=20)
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.decode(errors="replace"))
        else:
            raise RuntimeError(f"Unknown PRINTER_TRANSPORT: {TRANSPORT}")

    def main():
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        LOG.info("Starting agent id=%s slug=%s transport=%s", AGENT_ID, PRINTER_SLUG, TRANSPORT)
        while True:
            try:
                for job in fetch_pending_jobs():
                    job_id = job["id"]
                    LOG.info("Processing job %s (%d labels)", job_id, job["quantity"])
                    try:
                        send_to_printer(job["command_payload"])
                        report_result(job_id, "done")
                    except Exception as e:
                        LOG.exception("Job %s failed", job_id)
                        try:
                            report_result(job_id, "error", str(e))
                        except Exception:
                            LOG.exception("Failed to report error for job %s", job_id)
            except Exception:
                LOG.exception("Poll cycle failed")
            time.sleep(POLL_INTERVAL)

    if __name__ == "__main__":
        main()
''').lstrip()

SYSTEMD_UNIT = textwrap.dedent(f'''
    [Unit]
    Description=NBNE Manufacture print agent
    After=network-online.target nbne-rfcomm-bind.service
    Wants=network-online.target nbne-rfcomm-bind.service

    [Service]
    Type=simple
    User={USER}
    Group=dialout
    EnvironmentFile={ENV_FILE}
    ExecStart=/usr/bin/python3 {INSTALL_DIR}/agent.py
    Restart=always
    RestartSec=5
    StandardOutput=journal
    StandardError=journal

    [Install]
    WantedBy=multi-user.target
''').lstrip()

# rfcomm bind isn't persistent across reboots by default; this unit binds
# /dev/rfcomm{RFCOMM_INDEX} on boot using the printer's MAC.
RFCOMM_UNIT_TEMPLATE = textwrap.dedent('''
    [Unit]
    Description=Bind /dev/rfcomm{idx} to printer {mac}
    After=bluetooth.service
    Requires=bluetooth.service

    [Service]
    Type=oneshot
    ExecStart=/bin/sh -c "rfcomm release {idx} 2>/dev/null; rfcomm bind {idx} {mac}"
    ExecStop=/usr/bin/rfcomm release {idx}
    RemainAfterExit=yes

    [Install]
    WantedBy=bluetooth.target
''').lstrip()

TEST_LABEL_TSPL = (
    "SIZE 50 mm,25 mm\r\n"
    "GAP 2 mm,0 mm\r\n"
    "DENSITY 8\r\nSPEED 4\r\nDIRECTION 1\r\nCLS\r\n"
    'TEXT 30,30,"3",0,1,1,"NBNE Manufacture"\r\n'
    'TEXT 30,60,"3",0,1,1,"PM-2411-BT — OK"\r\n'
    "PRINT 1,1\r\n"
)

# ─── Helpers ─────────────────────────────────────────────────────────────────


def step(msg: str) -> None:
    print(f"\n\033[1m▶ {msg}\033[0m")


def info(msg: str) -> None:
    print(f"  {msg}")


def warn(msg: str) -> None:
    print(f"\033[33m  ⚠ {msg}\033[0m")


def fail(msg: str) -> None:
    print(f"\033[31m✗ {msg}\033[0m", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str], check: bool = True, capture: bool = False, **kwargs) -> subprocess.CompletedProcess:
    if capture:
        kwargs["capture_output"] = True
        kwargs["text"] = True
    return subprocess.run(cmd, check=check, **kwargs)


def ensure_root() -> None:
    if os.geteuid() != 0:
        fail("Must be run as root: sudo python3 setup_printer.py")


def ensure_packages() -> None:
    step("Checking required system packages")
    needed = {
        "bluetoothctl": "bluez",
        "rfcomm": "bluez bluez-tools",
        "systemctl": "systemd",
        "python3": "python3",
    }
    missing = [pkg for cmd, pkg in needed.items() if shutil.which(cmd) is None]
    if missing:
        info(f"Installing: {' '.join(missing)}")
        run(["apt-get", "update"], capture=True)
        run(["apt-get", "install", "-y"] + list(set(missing)))
    else:
        info("All required tools already present")


def scan_for_printer(timeout: int = 12) -> list[tuple[str, str]]:
    """Return [(mac, name), ...] from a one-shot bluetoothctl scan."""
    step(f"Scanning for Bluetooth devices ({timeout}s)…")
    info("Make sure the printer is on and in pairing mode.")
    proc = subprocess.Popen(
        ["bluetoothctl"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True,
    )
    proc.stdin.write("power on\nagent on\ndefault-agent\nscan on\n")
    proc.stdin.flush()
    time.sleep(timeout)
    proc.stdin.write("scan off\ndevices\nquit\n")
    proc.stdin.flush()
    out, _ = proc.communicate(timeout=5)

    devices = []
    for line in out.splitlines():
        m = re.search(r"Device ([0-9A-F:]{17})\s+(.+)", line)
        if m:
            devices.append((m.group(1), m.group(2).strip()))
    return devices


def pair_printer(mac: str, pin: str = "0000") -> None:
    step(f"Pairing with {mac}")
    cmds = (
        "power on\n"
        "agent on\n"
        "default-agent\n"
        f"trust {mac}\n"
        f"pair {mac}\n"
        f"connect {mac}\n"
        "quit\n"
    )
    proc = subprocess.run(
        ["bluetoothctl"], input=cmds, capture_output=True, text=True, timeout=60,
    )
    if "Failed to pair" in proc.stdout and "AlreadyExists" not in proc.stdout:
        warn(f"bluetoothctl reported issues:\n{proc.stdout[-500:]}")
        warn(f"If pairing wants a PIN, the default for these printers is usually {pin} or 1234.")
    info("Pairing requested. (If the printer needs a PIN entered on a phone first, do that and re-run.)")


def install_rfcomm_bind_unit(mac: str) -> None:
    step("Persisting /dev/rfcomm0 bind across reboots")
    RFCOMM_SERVICE_FILE.write_text(RFCOMM_UNIT_TEMPLATE.format(idx=RFCOMM_INDEX, mac=mac))
    RFCOMM_SERVICE_FILE.chmod(0o644)
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", RFCOMM_SERVICE_FILE.stem])
    # Bind right now too
    run(["rfcomm", "release", str(RFCOMM_INDEX)], check=False, capture=True)
    res = run(["rfcomm", "bind", str(RFCOMM_INDEX), mac], check=False, capture=True)
    if res.returncode != 0:
        warn(f"rfcomm bind returned non-zero: {res.stderr.strip()}")
    device_path = Path(f"/dev/rfcomm{RFCOMM_INDEX}")
    if not device_path.exists():
        fail(f"{device_path} did not appear after bind. Check pairing first.")
    info(f"{device_path} ready")


def test_print(device: str = f"/dev/rfcomm{RFCOMM_INDEX}") -> None:
    step("Sending a test label to the printer")
    try:
        with open(device, "wb", buffering=0) as fh:
            fh.write(TEST_LABEL_TSPL.encode("utf-8"))
        info("Test label sent. Confirm a label fed out before continuing.")
    except OSError as e:
        warn(f"Could not write to {device}: {e}")
        warn("Skipping test print — service install will continue.")


def ensure_user() -> None:
    step(f"Ensuring system user '{USER}' exists")
    res = run(["id", "-u", USER], check=False, capture=True)
    if res.returncode != 0:
        run(["useradd", "-r", "-s", "/usr/sbin/nologin", USER])
        info(f"Created user {USER}")
    else:
        info(f"User {USER} already exists")
    run(["usermod", "-aG", "dialout", USER])
    info(f"User {USER} added to 'dialout' group (read/write tty access)")


def ensure_pip_requests() -> None:
    step("Ensuring 'requests' library is installed")
    try:
        import requests  # noqa: F401
        info("requests already importable")
        return
    except ImportError:
        pass
    res = run(["python3", "-m", "pip", "install", "--system", "requests"], check=False, capture=True)
    if res.returncode != 0:
        # Some Ubuntus disallow --system; fall back to apt
        info("pip install failed, falling back to apt")
        run(["apt-get", "install", "-y", "python3-requests"])


def fetch_remote_agent(api_base: str) -> str | None:
    """Try to download the latest agent.py from the manufacture host."""
    url = f"{api_base.rstrip('/')}{AGENT_DOWNLOAD_PATH}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            if resp.status == 200:
                return resp.read().decode("utf-8")
    except Exception as e:
        warn(f"Could not fetch agent.py from {url}: {e}. Using embedded fallback.")
    return None


def install_agent(api_base: str) -> None:
    step(f"Installing agent into {INSTALL_DIR}")
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    contents = fetch_remote_agent(api_base) or EMBEDDED_AGENT_PY
    agent_path = INSTALL_DIR / "agent.py"
    agent_path.write_text(contents)
    agent_path.chmod(0o755)
    shutil.chown(INSTALL_DIR, user=USER)
    shutil.chown(agent_path, user=USER)
    info(f"Wrote {agent_path} ({len(contents)} bytes)")


def write_env(api_base: str, token: str, slug: str) -> None:
    step(f"Writing {ENV_FILE}")
    body = textwrap.dedent(f"""\
        MANUFACTURE_API_BASE={api_base}
        PRINT_AGENT_TOKEN={token}
        PRINTER_SLUG={slug}
        PRINTER_TRANSPORT=serial
        PRINTER_DEVICE=/dev/rfcomm{RFCOMM_INDEX}
        POLL_INTERVAL_SECONDS=3
        AGENT_ID={socket.gethostname()}-{slug}
    """)
    ENV_FILE.write_text(body)
    ENV_FILE.chmod(0o640)
    shutil.chown(ENV_FILE, user="root", group=USER)
    info("Env file written (mode 640, root:printagent)")


def install_systemd_unit() -> None:
    step("Installing systemd service")
    SERVICE_FILE.write_text(SYSTEMD_UNIT)
    SERVICE_FILE.chmod(0o644)
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "nbne-print-agent"])
    run(["systemctl", "restart", "nbne-print-agent"])
    info("Service enabled and started")


def show_status() -> None:
    step("Service status (last 20 lines)")
    time.sleep(2)  # let it log a bit
    res = run(
        ["journalctl", "-u", "nbne-print-agent", "-n", "20", "--no-pager"],
        check=False, capture=True,
    )
    print(res.stdout)


# ─── Main ────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--mac", help="Printer Bluetooth MAC, e.g. AA:BB:CC:DD:EE:FF")
    p.add_argument("--token", help="PRINT_AGENT_TOKEN from the manufacture app")
    p.add_argument("--slug", default=PRINTER_SLUG_DEFAULT, help="Printer slug (default: pm-2411-bt-bi)")
    p.add_argument("--api-base", default=API_BASE_DEFAULT, help=f"Manufacture API base (default: {API_BASE_DEFAULT})")
    p.add_argument("--no-test-print", action="store_true", help="Skip the sanity-check label")
    p.add_argument("--scan", action="store_true", help="Scan for nearby Bluetooth devices and exit")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    ensure_root()

    if args.scan:
        ensure_packages()
        for mac, name in scan_for_printer():
            print(f"  {mac}  {name}")
        return

    print("\033[1m\nNBNE Manufacture printer setup\033[0m")
    print(f"  slug={args.slug}  api={args.api_base}")

    ensure_packages()

    mac = args.mac
    if not mac:
        info("No --mac supplied; running a scan to help you pick.")
        for m, name in scan_for_printer():
            print(f"  {m}  {name}")
        mac = input("\nEnter the printer's MAC address: ").strip()
    if not MAC_RE.match(mac):
        fail(f"'{mac}' doesn't look like a Bluetooth MAC.")

    token = args.token or os.environ.get("PRINT_AGENT_TOKEN")
    if not token:
        token = getpass.getpass("Paste PRINT_AGENT_TOKEN (input hidden): ").strip()
    if not token:
        fail("Token is required.")

    pair_printer(mac)
    install_rfcomm_bind_unit(mac)
    if not args.no_test_print:
        test_print()
    ensure_user()
    ensure_pip_requests()
    install_agent(args.api_base)
    write_env(args.api_base, token, args.slug)
    install_systemd_unit()
    show_status()

    print(
        "\n\033[32m✓ Setup complete.\033[0m "
        f"Tail the agent with:  journalctl -u nbne-print-agent -f"
    )
    print(
        "Now open /barcodes in the manufacture app, tick a couple of rows,"
        " pick this printer in the dropdown, and hit Send to printer."
    )


if __name__ == "__main__":
    main()
