# NBNE Print Agent

Polls `manufacture.nbnesigns.co.uk` for pending thermal print jobs and forwards the rendered command string to the label printer on the Alnwick office LAN.

## Requirements

- Python 3.11+
- Network access to both Hetzner (outbound HTTPS) and the printer (TCP 9100)
- Printer model TBD — agent is transport-only, does not care about command language

## Setup on the Pi

```bash
sudo useradd -r -s /bin/false printagent
sudo mkdir /opt/nbne-print-agent
sudo cp agent.py requirements.txt /opt/nbne-print-agent/
sudo python3 -m venv /opt/nbne-print-agent/venv
sudo /opt/nbne-print-agent/venv/bin/pip install -r /opt/nbne-print-agent/requirements.txt

sudo cp config.example.env /etc/nbne-print-agent.env
sudo nano /etc/nbne-print-agent.env  # fill in real values

sudo cp systemd/nbne-print-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nbne-print-agent
sudo systemctl status nbne-print-agent
```

## Testing locally

Point at `nc -l 9100` to see raw ZPL output without a real printer:

```bash
# Terminal 1
nc -l 9100

# Terminal 2
MANUFACTURE_API_BASE=https://manufacture.nbnesigns.co.uk \
PRINT_AGENT_TOKEN=<token> \
PRINTER_HOST=127.0.0.1 \
python agent.py
```

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `MANUFACTURE_API_BASE` | Yes | — | e.g. `https://manufacture.nbnesigns.co.uk` |
| `PRINT_AGENT_TOKEN` | Yes | — | Shared secret — must match Django `PRINT_AGENT_TOKEN` |
| `PRINTER_HOST` | Yes | — | Printer IP on local LAN |
| `PRINTER_PORT` | No | `9100` | Raw TCP port |
| `POLL_INTERVAL_SECONDS` | No | `3` | Seconds between polls |
