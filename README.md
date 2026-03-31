# UDP Multiplayer Demo

This codebase packages the provided files into a runnable Python project with
authenticated and encrypted UDP packets:

- `server.py`: authoritative UDP game server
- `client.py`: Pygame client for players
- `monitor.py`: terminal monitor for latency, jitter, loss, and update rate
- `protocol.py`: shared packet helpers, packet type constants, AES-CBC encryption,
  and HMAC verification

## Requirements

- Python 3.10+
- `pip install -r requirements.txt`
- Python packages:
  - `pygame`
  - `pycryptodomex`

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

## Security Layer

All packets are wrapped by `protocol.py` before being sent:

- Payloads are serialized as JSON
- Payloads are encrypted with AES-CBC
- `iv + ciphertext` is authenticated with HMAC-SHA256

This means `server.py`, `client.py`, and `monitor.py` all require the crypto
dependency from `requirements.txt`.

## Project Layout

```text
.
├── README.md
├── client.py
├── monitor.py
├── protocol.py
├── requirements.txt
└── server.py
```
