# UDP Multiplayer Demo

This codebase packages the four provided files into a runnable Python project:

- `server.py`: authoritative UDP game server
- `client.py`: Pygame client for players
- `monitor.py`: terminal monitor for latency, jitter, loss, and update rate
- `protocol.py`: shared packet helpers and packet type constants

## Requirements

- Python 3.10+
- `pip install -r requirements.txt`

## Run

Start the server:

```bash
python server.py
```

Start one or more clients in separate terminals:

```bash
python client.py
```

Start the monitor:

```bash
python monitor.py
```

## Project Layout

```text
codes/
├── README.md
├── client.py
├── monitor.py
├── protocol.py
├── requirements.txt
└── server.py
```
