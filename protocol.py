"""
Shared UDP packet helpers for the multiplayer demo.
"""

import json
import time


def make_packet(ptype: str, data: dict, seq: int = 0) -> bytes:
    packet = {
        "type": ptype,
        "seq": seq,
        "timestamp": time.time(),
        "data": data,
    }
    return json.dumps(packet).encode("utf-8")


def parse_packet(raw: bytes) -> dict:
    try:
        return json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Malformed packet: {exc}") from exc


class PType:
    JOIN = "JOIN"
    LEAVE = "LEAVE"
    MOVE = "MOVE"
    STATE = "STATE"
    PING = "PING"
    PONG = "PONG"
    CHAT = "CHAT"
    ERROR = "ERROR"
