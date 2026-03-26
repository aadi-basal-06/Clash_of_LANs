"""
Authoritative UDP game server.
"""

import socket
import threading
import time

from protocol import PType, make_packet, parse_packet

HOST = "0.0.0.0"
PORT = 5555
TICK_RATE = 20
TIMEOUT_SEC = 10


class GameServer:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((HOST, PORT))

        self.lock = threading.Lock()
        self.clients = {}
        self.game_state = {}
        self.last_seen = {}
        self.stats = {}
        self.seq = 0

        print(f"[SERVER] Listening on {HOST}:{PORT}")
        print(f"[SERVER] Tick rate: {TICK_RATE} Hz | Timeout: {TIMEOUT_SEC}s\n")

    def _next_seq(self):
        self.seq += 1
        return self.seq

    def _broadcast(self, packet: bytes, exclude_id=None):
        with self.lock:
            targets = {
                player_id: addr
                for player_id, addr in self.clients.items()
                if player_id != exclude_id
            }

        for player_id, addr in targets.items():
            try:
                self.sock.sendto(packet, addr)
                with self.lock:
                    if player_id in self.stats:
                        self.stats[player_id]["packets_sent"] += 1
            except Exception as exc:
                print(f"[SERVER] Broadcast error to {player_id}: {exc}")

    def _send(self, packet: bytes, addr):
        try:
            self.sock.sendto(packet, addr)
        except Exception as exc:
            print(f"[SERVER] Send error to {addr}: {exc}")

    def _drop_player(self, player_id: str):
        with self.lock:
            name = self.game_state.get(player_id, {}).get("name", player_id)
            self.clients.pop(player_id, None)
            self.game_state.pop(player_id, None)
            self.last_seen.pop(player_id, None)
            self.stats.pop(player_id, None)
            state_snapshot = dict(self.game_state)

        print(f"[SERVER] Player '{name}' ({player_id}) disconnected")
        self._broadcast(make_packet(PType.STATE, state_snapshot, self._next_seq()))

    def _handle_join(self, pkt: dict, addr):
        player_id = pkt["data"]["player_id"]
        name = pkt["data"].get("name", player_id)
        color = pkt["data"].get("color", "#ffffff")

        with self.lock:
            already_connected = player_id in self.clients
            self.clients[player_id] = addr
            self.last_seen[player_id] = time.time()
            self.game_state[player_id] = {
                "x": 0,
                "y": 0,
                "name": name,
                "color": color,
            }
            self.stats[player_id] = {
                "packets_recv": 0,
                "packets_sent": 0,
                "last_latency": 0,
            }
            state_snapshot = dict(self.game_state)

        action = "rejoined" if already_connected else "joined"
        print(f"[SERVER] '{name}' ({player_id}) {action} from {addr}")

        self._send(make_packet(PType.STATE, state_snapshot, self._next_seq()), addr)
        self._broadcast(
            make_packet(PType.STATE, state_snapshot, self._next_seq()),
            exclude_id=player_id,
        )

    def _handle_move(self, pkt: dict, addr):
        _ = addr
        player_id = pkt["data"].get("player_id")
        if not player_id:
            return

        with self.lock:
            if player_id not in self.game_state:
                return
            self.game_state[player_id]["x"] = pkt["data"].get("x", 0)
            self.game_state[player_id]["y"] = pkt["data"].get("y", 0)
            self.last_seen[player_id] = time.time()
            self.stats[player_id]["packets_recv"] += 1
            state_snapshot = dict(self.game_state)

        self._broadcast(make_packet(PType.STATE, state_snapshot, self._next_seq()))

    def _handle_ping(self, pkt: dict, addr):
        player_id = pkt["data"].get("player_id")
        with self.lock:
            if player_id in self.last_seen:
                self.last_seen[player_id] = time.time()

        pong = make_packet(
            PType.PONG,
            {
                "player_id": player_id,
                "client_time": pkt["timestamp"],
            },
        )
        self._send(pong, addr)

    def _handle_leave(self, pkt: dict, addr):
        _ = addr
        player_id = pkt["data"].get("player_id")
        if player_id:
            self._drop_player(player_id)

    def _handle_chat(self, pkt: dict, addr):
        _ = addr
        player_id = pkt["data"].get("player_id")
        message = pkt["data"].get("message", "")
        with self.lock:
            name = self.game_state.get(player_id, {}).get("name", player_id)
            if player_id in self.last_seen:
                self.last_seen[player_id] = time.time()

        print(f"[CHAT] {name}: {message}")
        chat_packet = make_packet(
            PType.CHAT,
            {"player_id": player_id, "name": name, "message": message},
        )
        self._broadcast(chat_packet)

    def _receive_loop(self):
        handlers = {
            PType.JOIN: self._handle_join,
            PType.MOVE: self._handle_move,
            PType.PING: self._handle_ping,
            PType.LEAVE: self._handle_leave,
            PType.CHAT: self._handle_chat,
        }

        while True:
            try:
                raw, addr = self.sock.recvfrom(4096)
                packet = parse_packet(raw)
                handler = handlers.get(packet["type"])
                if handler:
                    threading.Thread(
                        target=handler,
                        args=(packet, addr),
                        daemon=True,
                    ).start()
                else:
                    print(f"[SERVER] Unknown packet type: {packet['type']}")
            except ValueError as exc:
                print(f"[SERVER] Parse error: {exc}")
            except Exception as exc:
                print(f"[SERVER] Receive loop error: {exc}")

    def _timeout_loop(self):
        while True:
            time.sleep(2)
            now = time.time()
            with self.lock:
                timed_out = [
                    player_id
                    for player_id, ts in self.last_seen.items()
                    if now - ts > TIMEOUT_SEC
                ]
            for player_id in timed_out:
                print(f"[SERVER] Timing out player {player_id}")
                self._drop_player(player_id)

    def _status_loop(self):
        while True:
            time.sleep(5)
            with self.lock:
                count = len(self.clients)
                players = [
                    state.get("name", player_id)
                    for player_id, state in self.game_state.items()
                ]
            if count > 0:
                print(f"[SERVER] {count} player(s) online: {', '.join(players)}")
            else:
                print("[SERVER] No players connected.")

    def run(self):
        threading.Thread(target=self._receive_loop, daemon=True).start()
        threading.Thread(target=self._timeout_loop, daemon=True).start()
        threading.Thread(target=self._status_loop, daemon=True).start()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[SERVER] Shutting down.")
            self.sock.close()


if __name__ == "__main__":
    GameServer().run()
