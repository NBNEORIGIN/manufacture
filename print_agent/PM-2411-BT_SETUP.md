# PM-2411-BT setup on Ubuntu

End-to-end recipe for getting the PM-2411-BT thermal label printer printing
labels from the Manufacture app on Ben & Ivan's Ubuntu workstation.

The printer prints **50 × 25 mm** thermal labels via Bluetooth using **TSPL**.

---

## 1. Pair the printer over Bluetooth

```bash
# turn the printer on, hold the power/feed button to put it into pairing mode
sudo bluetoothctl
[bluetooth]# power on
[bluetooth]# agent on
[bluetooth]# default-agent
[bluetooth]# scan on
# wait until the PM-2411-BT MAC appears, e.g. 00:11:22:33:44:55
[bluetooth]# pair  00:11:22:33:44:55
[bluetooth]# trust 00:11:22:33:44:55
[bluetooth]# scan off
[bluetooth]# quit
```

If pairing prompts for a PIN, the default for these printers is usually
`0000` or `1234`.

## 2. Bind a serial port to the printer

The agent talks to a tty. Bind `/dev/rfcomm0` to the printer's MAC:

```bash
# one-shot
sudo rfcomm bind 0 00:11:22:33:44:55

# verify
ls -l /dev/rfcomm0
# crw-rw---- 1 root dialout 216, 0 Apr 29 09:00 /dev/rfcomm0
```

To make the bind survive reboots, add to `/etc/rc.local` (or a systemd
unit) and put the agent's user (`printagent` below) in the `dialout`
group so it can write to the device without sudo:

```bash
sudo usermod -aG dialout printagent
```

## 3. Quick sanity-check from the shell

Before the agent does anything, verify a raw label prints. Save this as
`test.tspl`:

```
SIZE 50 mm,25 mm
GAP 2 mm,0 mm
DENSITY 8
SPEED 4
CLS
TEXT 30,30,"3",0,1,1,"PM-2411-BT OK"
PRINT 1,1
```

Send it:

```bash
cat test.tspl > /dev/rfcomm0
```

If a label feeds out with the text on it, you're done with the printer side.
If not, troubleshoot pairing / rfcomm bind first — the agent can't help.

## 4. Register the printer in Django

Either via the admin (`/admin/barcodes/printer/add/`) or via the Django
shell on the server:

```python
from barcodes.models import Printer
Printer.objects.create(
    name='Ben & Ivan PM-2411-BT',
    slug='pm-2411-bt-bi',           # the agent uses this slug
    transport='serial',
    address='/dev/rfcomm0',
    command_language='tspl',
    label_width_mm=50,
    label_height_mm=25,
    label_dpi=203,
)
```

## 5. Install the agent on the workstation

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
PRINT_AGENT_TOKEN=<paste from the Django settings>
PRINTER_SLUG=pm-2411-bt-bi
PRINTER_TRANSPORT=serial
PRINTER_DEVICE=/dev/rfcomm0
POLL_INTERVAL_SECONDS=3
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now nbne-print-agent
journalctl -u nbne-print-agent -f
```

You should see:

```
Starting agent id=ben-ivan-pc slug=pm-2411-bt-bi transport=serial polling https://...
Printer device present at /dev/rfcomm0 (serial @ 9600 baud)
```

## 6. Print from the app

1. Open `/barcodes` in the app
2. Tick the rows you want
3. The new printer will appear in the dropdown next to the **Send to printer** button
4. Click it — the queue page (`/print-queue`) will show the job claimed within seconds

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Agent logs `Printer device present` but jobs never claim | Wrong `PRINTER_SLUG` or printer marked inactive in Django admin |
| Jobs claim then error out | TSPL dialect mismatch — view the payload in the queue page (ZPL button) and tweak `services/rendering/tspl.py` |
| Nothing comes out of the printer | Bluetooth dropped — `sudo rfcomm release 0` then `bind 0 <MAC>` again |
| Smudged or faded print | Increase `DENSITY` in the renderer (8 → 10 → 12 max) |
