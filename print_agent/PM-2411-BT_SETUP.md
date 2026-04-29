# PM-2411-BT setup on Ubuntu

Recipe for getting the **PM-2411-BT** Bluetooth thermal label printer
(50 × 25 mm thermal labels, TSPL) printing from the Manufacture app on
Ben & Ivan's Ubuntu workstation.

There are two paths: the **one-shot installer** (recommended) and the
**manual** procedure (kept for reference / debugging).

---

## A. One-shot installer (recommended)

The manufacture app serves a self-contained Python installer at
`/api/print-agent/setup_printer.py`. It pairs over Bluetooth, binds
`/dev/rfcomm0`, sends a test label, installs the agent as a systemd
service and starts it. About a minute end-to-end.

On Ben's PC:

```bash
# Download
curl -sSO https://manufacture.nbnesigns.co.uk/api/print-agent/setup_printer.py

# Run (interactive — it'll scan for the printer and prompt for the token)
sudo python3 setup_printer.py
```

If you already know the MAC and have the token in hand, run it
non-interactively:

```bash
sudo python3 setup_printer.py \
    --mac AA:BB:CC:DD:EE:FF \
    --token 'paste-from-toby'
```

After it finishes, the agent runs as a systemd service. Tail it with:

```bash
journalctl -u nbne-print-agent -f
```

Then open `/barcodes` in the manufacture app, tick a couple of rows,
pick **Ben & Ivan PM-2411-BT** from the printer dropdown, and click
**Send to printer**.

### What the installer does

1. Installs `bluez`, `bluez-tools`, `python3-requests` if missing
2. Pairs the printer via `bluetoothctl` (PIN defaults to `0000`)
3. Creates a systemd unit (`nbne-rfcomm-bind.service`) that re-binds
   `/dev/rfcomm0` on boot, then binds it now
4. Sends a test label over the bound device
5. Creates the `printagent` system user, adds it to `dialout`
6. Drops `agent.py` in `/opt/nbne-print-agent/` (latest from the host)
7. Writes `/etc/nbne-print-agent.env` with the API base, token, slug,
   transport (serial), device path
8. Installs / starts `nbne-print-agent.service`
9. Tails the journal so you can see it connect

The installer is **idempotent** — re-run it any time to refresh the
agent or change the token. Pass `--scan` to just list nearby Bluetooth
devices and exit.

---

## B. Manual procedure (reference)

Use this if the installer fails or you're debugging.

### 1. Pair the printer

```bash
sudo bluetoothctl
[bluetooth]# power on
[bluetooth]# agent on
[bluetooth]# default-agent
[bluetooth]# scan on
# wait for the PM-2411-BT MAC, e.g. 00:11:22:33:44:55
[bluetooth]# pair  00:11:22:33:44:55
[bluetooth]# trust 00:11:22:33:44:55
[bluetooth]# scan off
[bluetooth]# quit
```

PIN, if asked, is usually `0000` or `1234`.

### 2. Bind /dev/rfcomm0

```bash
sudo rfcomm bind 0 00:11:22:33:44:55
ls -l /dev/rfcomm0
# crw-rw---- 1 root dialout 216, 0 …
```

To survive reboots, install the same systemd unit the installer uses
(`/etc/systemd/system/nbne-rfcomm-bind.service`).

### 3. Quick raw test

```bash
cat <<'EOF' > /dev/rfcomm0
SIZE 50 mm,25 mm
GAP 2 mm,0 mm
DENSITY 8
SPEED 4
CLS
TEXT 30,30,"3",0,1,1,"PM-2411-BT OK"
PRINT 1,1
EOF
```

### 4. Register the printer in Django

(Already done for Ben & Ivan's printer — `slug=pm-2411-bt-bi`. For a
new device, add via Django admin or shell.)

### 5. Install the agent manually

```bash
sudo useradd -r -s /usr/sbin/nologin printagent
sudo usermod -aG dialout printagent
sudo mkdir -p /opt/nbne-print-agent
sudo cp agent.py /opt/nbne-print-agent/
sudo cp systemd/nbne-print-agent.service /etc/systemd/system/
```

Create `/etc/nbne-print-agent.env`:

```
MANUFACTURE_API_BASE=https://manufacture.nbnesigns.co.uk
PRINT_AGENT_TOKEN=<from Toby>
PRINTER_SLUG=pm-2411-bt-bi
PRINTER_TRANSPORT=serial
PRINTER_DEVICE=/dev/rfcomm0
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now nbne-print-agent
journalctl -u nbne-print-agent -f
```

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Installer reports `Failed to pair` | Printer not in pairing mode, or already paired with another device. Hold the feed button to enter pairing mode. |
| `journalctl` shows `Printer device present` but no jobs claim | Wrong `PRINTER_SLUG` or printer marked inactive in Django admin |
| Jobs claim then error out | TSPL dialect mismatch — open the queue page, click the **ZPL** modal on the failing job, check the payload, and tweak `services/rendering/tspl.py` |
| Nothing comes out | rfcomm dropped after sleep — `sudo rfcomm release 0 && rfcomm bind 0 <MAC>`, or restart the bind service: `sudo systemctl restart nbne-rfcomm-bind` |
| Smudged / faint print | Increase `DENSITY` in `services/rendering/tspl.py` (8 → 10 → max 12) |
