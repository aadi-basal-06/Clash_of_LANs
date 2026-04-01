import json # this is for serialize or deserialize data into a portable format
import time#timestap
import hmac#message authetication code to preserver integrity
import hashlib
from Crypto.Cipher import AES#symm encryption
from Crypto.Random import get_random_bytes# generate a random initialisation vector
import base64#encode binary data to text for safe transmission

# Shared secret keys. In a real deployment these should come from config or env,
# but for this demo both sides must use the same values.
SECRET_KEY = b"supersecretkey123"   # for HMAC (any length is fine)
AES_KEY    = b"thisisaeskey1234"    # 16 bytes → AES-128

def _pad(data: bytes) -> bytes: 
    pad_len = 16 - (len(data) % 16)# identifying how many more bytes to add becoz AES is 16 bytes
    return data + bytes([pad_len]) * pad_len

def _unpad(data: bytes) -> bytes:
    pad_len = data[-1]# tells us how many padding bytes were added
    return data[:-pad_len]

def make_packet(ptype: str, data: dict, seq: int = 0) -> bytes:# returns a packet as bytes ready to be encrypted
    packet = {
        "type": ptype,
        "seq": seq,
        "timestamp": time.time(),
        "data": data,
    }
    raw_json = json.dumps(packet, separators=(",", ":")).encode("utf-8")#python dictonary to json string and then to bytes

    # AES-CBC needs a fresh IV per packet so repeated payloads do not encrypt
    # to the same ciphertext.
    iv = get_random_bytes(16)
    cipher = AES.new(AES_KEY, AES.MODE_CBC, iv)# creates the cipher object-CIPHER BLOCK CHAINING MODE
    ciphertext = cipher.encrypt(_pad(raw_json))#here actual encryption happens

    # Authenticate the IV and ciphertext together so tampering is detected
    # before we try to decrypt the packet.
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
    expected_mac = hmac.new(SECRET_KEY, iv + ciphertext, hashlib.sha256).hexdigest()# detecting tampering by comparing the received HMAC with the expected one computed from the iv and ciphertext
    if not hmac.compare_digest(mac, expected_mac):# compares the computed mac and the received mac
        raise ValueError("Invalid HMAC: packet tampered")

    # Decrypt AES
    cipher = AES.new(AES_KEY, AES.MODE_CBC, iv)
    plaintext = _unpad(cipher.decrypt(ciphertext))

    # Parse JSON payload
    return json.loads(plaintext.decode("utf-8"))# converts the decrypted plaintext back into a Python dictionary

class PType:
    JOIN  = "JOIN"#players are joining the game
    LEAVE = "LEAVE"#players leaving the game
    MOVE  = "MOVE"#players sending their movement updates to the server
    STATE = "STATE"#game state updates
    PING  = "PING"#clients send ping packets to measure latency and check connectivity
    PONG  = "PONG"#server responds to ping packets
    CHAT  = "CHAT"
    ERROR = "ERROR"
