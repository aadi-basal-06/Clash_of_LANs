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

## Server Architecture

The authoritative server (`server.py`) uses a multi-threaded, event-driven
architecture to handle concurrent players efficiently over UDP:

| Thread           | Role                                              |
| ---------------- | ------------------------------------------------- |
| `_receive_loop`  | Reads raw UDP datagrams and enqueues parsed packets |
| `_dispatch_loop` | Processes queued packets sequentially (no races)  |
| `_timeout_loop`  | Drops players silent for more than `TIMEOUT_SEC`  |
| `_status_loop`   | Periodically logs online player count             |

**Packet flow:**

```
Client ──UDP──► _receive_loop ──Queue──► _dispatch_loop ──► handler
                                                            │
                                                   _broadcast / _send
                                                            │
                                                    ◄──UDP──┘
```

All shared state (`clients`, `game_state`, `last_seen`, `stats`) is protected
by a `threading.Lock` to guarantee consistency across threads.

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
