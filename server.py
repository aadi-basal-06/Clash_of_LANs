"""
server.py - Authoritative UDP Game Server for Clash of LANs

This module implements the central authoritative game server that manages
all connected players, processes incoming packets, and broadcasts the
authoritative game state to every client over UDP.

Architecture:
    - Uses a multi-threaded design with separate loops for receiving,
      dispatching, timeout detection, and status reporting.
    - A thread-safe queue decouples packet reception from processing
      to avoid blocking the network I/O thread.
    - All game state mutations are protected by a threading lock to
      ensure consistency across concurrent operations.

Usage:
    python server.py
"""

import copy 
import queue 
import socket
import threading
import time

from protocol import PType, make_packet, parse_packet

# ── Server Configuration Constants ──────────────────────────────────────────
HOST = "0.0.0.0"       # bind to all available network interfaces
PORT = 5555            # UDP port the server listens on
TICK_RATE = 20         # server tick rate in Hz (updates per second)
TIMEOUT_SEC = 10       # seconds of silence before dropping a client
MAX_PACKET_SIZE = 4096 # maximum UDP datagram size in bytes


class GameServer:
    """Authoritative UDP game server that manages player connections and game state.

    The server uses a producer-consumer pattern: a receive thread pushes
    parsed packets onto a queue, and a dispatch thread processes them
    sequentially.  This avoids race conditions while keeping the network
    I/O non-blocking.
    """

    def __init__(self):
        # Create a UDP (SOCK_DGRAM) socket bound to all interfaces
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((HOST, PORT))

        # Shared state protected by a reentrant lock for thread safety
        self.lock = threading.Lock()
        self.clients = {}             # player_id -> (ip, port) address tuple
        self.game_state = {}          # player_id -> {x, y, name, color}
        self.last_seen = {}           # player_id -> last heartbeat timestamp
        self.stats = {}               # player_id -> {packets_recv, packets_sent, last_latency}
        self.seq = 0                  # monotonically increasing sequence number

        # Thread-safe FIFO queue that decouples receiving from processing
        self._packet_queue = queue.Queue()

        # Track when the server was started for uptime reporting
        self._start_time = time.time()

        print(f"[SERVER] Listening on {HOST}:{PORT}")
        print(f"[SERVER] Tick rate: {TICK_RATE} Hz | Timeout: {TIMEOUT_SEC}s\n")

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _next_seq(self):
        """Return the next sequence number for outgoing packets.

        Sequence numbers are monotonically increasing integers used by
        clients to detect out-of-order or duplicate packets.
        """
        self.seq += 1
        return self.seq

    def get_player_count(self):
        """Return the number of currently connected players (thread-safe)."""
        with self.lock:
            return len(self.clients)

    def get_uptime(self):
        """Return server uptime in seconds since start."""
        return time.time() - self._start_time

    def _broadcast(self, packet: bytes, exclude_id=None):
        """Send a packet to every connected client, optionally skipping one.

        Args:
            packet: Pre-serialised and encrypted packet bytes.
            exclude_id: If set, this player_id will *not* receive the packet
                        (useful to avoid echoing a player's own actions).
        """
        with self.lock:
            targets = {
                player_id: addr
                for player_id, addr in self.clients.items()
                if player_id != exclude_id
            }  # dictionary of all clients

        for player_id, addr in targets.items():  # one to many comm
            try:
                self.sock.sendto(packet, addr)
                with self.lock:
                    if player_id in self.stats:
                        self.stats[player_id]["packets_sent"] += 1
            except Exception as exc:
                print(f"[SERVER] Broadcast error to {player_id}: {exc}")

    # ── Networking (send / broadcast) ────────────────────────────────────────

    def _send(self, packet: bytes, addr):
        """Send a packet to a single client address (unicast)."""
        try:
            self.sock.sendto(packet, addr)
        except Exception as exc:
            print(f"[SERVER] Send error to {addr}: {exc}")

    # ── Player lifecycle ─────────────────────────────────────────────────────

    def _drop_player(self, player_id: str):
        """Remove a player from all server state and notify remaining clients.

        After cleanup, a fresh STATE packet is broadcast so every client
        removes the departed player from their local world view.
        """
        with self.lock:
            name = self.game_state.get(player_id, {}).get("name", player_id)
            self.clients.pop(player_id, None)
            self.game_state.pop(player_id, None)
            self.last_seen.pop(player_id, None)
            self.stats.pop(player_id, None)
            
            state_snapshot = copy.deepcopy(self.game_state)

        print(f"[SERVER] Player '{name}' ({player_id}) disconnected")
        self._broadcast(make_packet(PType.STATE, state_snapshot, self._next_seq()))

    # ── Packet handlers (called by _dispatch_loop) ──────────────────────────

    def _handle_join(self, pkt: dict, addr):
        """Handle a JOIN packet from a new or reconnecting player.

        Registers the player in all server dictionaries, then sends the
        full game state back to the joining client and broadcasts the
        updated state to everyone else.
        """
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
           
            state_snapshot = copy.deepcopy(self.game_state)

        action = "rejoined" if already_connected else "joined"
        print(f"[SERVER] '{name}' ({player_id}) {action} from {addr}")

        
        state_packet = make_packet(PType.STATE, state_snapshot, self._next_seq())
        self._send(state_packet, addr)
        self._broadcast(state_packet, exclude_id=player_id)

    def _handle_move(self, pkt: dict, addr):
        """Handle a MOVE packet containing a player's updated position.

        Updates the authoritative game state with the new coordinates
        and broadcasts the resulting state to all connected clients.
        """
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
            
            state_snapshot = copy.deepcopy(self.game_state)

        self._broadcast(make_packet(PType.STATE, state_snapshot, self._next_seq()))

    def _handle_ping(self, pkt: dict, addr):
        """Respond to a PING with a PONG carrying the client's original timestamp.

        The client uses the round-trip time to calculate latency.  This
        also refreshes the player's last_seen timestamp to prevent timeout.
        """
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
        """Handle a graceful LEAVE packet from a client that is disconnecting."""
        _ = addr
        player_id = pkt["data"].get("player_id")
        if player_id:
            self._drop_player(player_id)

    def _handle_chat(self, pkt: dict, addr):
        """Handle an incoming CHAT message and relay it to all clients.

        Chat messages are broadcast to every connected player, including
        the sender, so they see their own message in the chat log.
        """
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

    # ── Core event loops (each runs in its own daemon thread) ────────────────

    def _receive_loop(self):
        """Receives raw UDP packets and pushes them onto the handler queue."""
        while True:
            try:
                raw, addr = self.sock.recvfrom(MAX_PACKET_SIZE)
                packet = parse_packet(raw)
               
                self._packet_queue.put((packet, addr))
            except ValueError as exc:
                print(f"[SERVER] Parse error: {exc}")
            except Exception as exc:
                print(f"[SERVER] Receive loop error: {exc}")

    def _dispatch_loop(self):
        """Processes packets from the queue sequentially (no race conditions)."""
        handlers = {
            PType.JOIN:  self._handle_join,
            PType.MOVE:  self._handle_move,
            PType.PING:  self._handle_ping,
            PType.LEAVE: self._handle_leave,
            PType.CHAT:  self._handle_chat,
        }

        while True:
            try:
                packet, addr = self._packet_queue.get()
                handler = handlers.get(packet["type"])
                if handler:
                    handler(packet, addr)
                else:
                    print(f"[SERVER] Unknown packet type: {packet['type']}")
            except Exception as exc:
                print(f"[SERVER] Dispatch error: {exc}")

    def _timeout_loop(self):
        """Periodically scan for players that have gone silent and drop them.

        Runs every 2 seconds and compares each player's last_seen
        timestamp against TIMEOUT_SEC to detect disconnected clients.
        """
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
        """Print a periodic status line showing connected player count.

        Useful for server operators to monitor activity without needing
        a separate monitoring tool.
        """
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

    # ── Entry point ──────────────────────────────────────────────────────────

    def run(self):
        """Start all server threads and block until interrupted.

        Spawns four daemon threads:
            1. _receive_loop  - listens for incoming UDP packets
            2. _dispatch_loop - processes queued packets sequentially
            3. _timeout_loop  - drops silent clients
            4. _status_loop   - logs server status periodically

        The main thread sleeps in a loop and catches KeyboardInterrupt
        to allow a graceful shutdown.
        """
        threading.Thread(target=self._receive_loop, daemon=True).start()
        threading.Thread(target=self._dispatch_loop, daemon=True).start()  # ✅ FIX 3
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