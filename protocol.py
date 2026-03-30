"""
Shared UDP packet helpers for the multiplayer demo.
"""

import json
import time
import hmac
import hashlib
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
import base64

# Shared secret keys (must be identical on server and client)
SECRET_KEY = b"supersecretkey123"   # for HMAC (any length is fine)
AES_KEY    = b"thisisaeskey1234"    # 16 bytes → AES-128

def _pad(data: bytes) -> bytes:
    pad_len = 16 - (len(data) % 16)
    return data + bytes([pad_len]) * pad_len

def _unpad(data: bytes) -> bytes:
    pad_len = data[-1]
    return data[:-pad_len]

def make_packet(ptype: str, data: dict, seq: int = 0) -> bytes:
    packet = {
        "type": ptype,
        "seq": seq,
        "timestamp": time.time(),
        "data": data,
    }
    raw_json = json.dumps(packet, separators=(",", ":")).encode("utf-8")

    # Encrypt with AES-CBC
    iv = get_random_bytes(16)
    cipher = AES.new(AES_KEY, AES.MODE_CBC, iv)
    ciphertext = cipher.encrypt(_pad(raw_json))

    # Compute HMAC over iv+ciphertext
    mac = hmac.new(SECRET_KEY, iv + ciphertext, hashlib.sha256).hexdigest()

    # Final packet structure
    secure_packet = {
        "iv": base64.b64encode(iv).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
        "hmac": mac,
    }
    return json.dumps(secure_packet, separators=(",", ":")).encode("utf-8")

def parse_packet(raw: bytes) -> dict:
    try:
        secure_packet = json.loads(raw.decode("utf-8"))
        iv = base64.b64decode(secure_packet["iv"])
        ciphertext = base64.b64decode(secure_packet["ciphertext"])
        mac = secure_packet["hmac"]
    except Exception as e:
        raise ValueError(f"Malformed secure packet: {e}")

    # Verify HMAC
    expected_mac = hmac.new(SECRET_KEY, iv + ciphertext, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected_mac):
        raise ValueError("Invalid HMAC: packet tampered")

    # Decrypt AES
    cipher = AES.new(AES_KEY, AES.MODE_CBC, iv)
    plaintext = _unpad(cipher.decrypt(ciphertext))

    # Parse JSON payload
    return json.loads(plaintext.decode("utf-8"))

class PType:
    JOIN  = "JOIN"
    LEAVE = "LEAVE"
    MOVE  = "MOVE"
    STATE = "STATE"
    PING  = "PING"
    PONG  = "PONG"
    CHAT  = "CHAT"
    ERROR = "ERROR"
