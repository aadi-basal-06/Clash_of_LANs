"""
Terminal-based network performance monitor for the UDP game server.
"""

import collections
import os
import socket
import threading
import time

from protocol import PType, make_packet, parse_packet

SERVER_IP = "127.0.0.1"
SERVER_PORT = 5555
PLAYER_ID = "__monitor__"
SAMPLE_SIZE = 30
PING_RATE = 1.0


class NetworkMonitor:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(2.0)
        self.server = (SERVER_IP, SERVER_PORT)

        self.latencies = collections.deque(maxlen=SAMPLE_SIZE)
        self.state_updates = collections.deque(maxlen=SAMPLE_SIZE)
        self.player_states = {}

        self.pings_sent = 0
        self.pings_received = 0
        self.states_received = 0
        self.running = True

    def avg_latency(self):
        return sum(self.latencies) / len(self.latencies) if self.latencies else 0

    def min_latency(self):
        return min(self.latencies) if self.latencies else 0

    def max_latency(self):
        return max(self.latencies) if self.latencies else 0

    def jitter(self):
        if len(self.latencies) < 2:
            return 0
        diffs = [
            abs(self.latencies[index] - self.latencies[index - 1])
            for index in range(1, len(self.latencies))
        ]
        return sum(diffs) / len(diffs)

    def packet_loss(self):
        if self.pings_sent == 0:
            return 0.0
        return ((self.pings_sent - self.pings_received) / self.pings_sent) * 100

    def update_rate(self):
        if len(self.state_updates) < 2:
            return 0.0
        elapsed = self.state_updates[-1] - self.state_updates[0]
        if elapsed <= 0:
            return 0.0
        return (len(self.state_updates) - 1) / elapsed

    def _receive_loop(self):
        while self.running:
            try:
                raw, _ = self.sock.recvfrom(4096)
                packet = parse_packet(raw)

                if packet["type"] == PType.PONG:
                    rtt = (time.time() - packet["data"]["client_time"]) * 1000
                    self.latencies.append(rtt)
                    self.pings_received += 1
                elif packet["type"] == PType.STATE:
                    self.states_received += 1
                    self.state_updates.append(time.time())
                    self.player_states = packet["data"]
            except socket.timeout:
                continue
            except Exception as exc:
                if self.running:
                    print(f"[MONITOR] Receive error: {exc}")

    def _clear(self):
        os.system("cls" if os.name == "nt" else "clear")

    def _bar(self, value, max_val, width=20, fill="#", empty="-"):
        filled = int(min(value / max_val, 1.0) * width)
        return fill * filled + empty * (width - filled)

    def _latency_label(self, ms):
        if ms < 50:
            return "EXCELLENT"
        if ms < 100:
            return "GOOD"
        if ms < 200:
            return "FAIR"
        return "POOR"

    def _display_loop(self):
        while self.running:
            time.sleep(1)
            self._clear()

            avg = self.avg_latency()
            jitter = self.jitter()
            loss = self.packet_loss()
            rate = self.update_rate()
            players = len(self.player_states)

            print("+------------------------------------------------+")
            print("| NETWORK PERFORMANCE MONITOR                    |")
            print(f"| Server: {SERVER_IP}:{SERVER_PORT:<36}|")
            print("+------------------------------------------------+")
            print(f"| Players Online  : {players:<29}|")
            print(f"| States Received : {self.states_received:<29}|")
            print(f"| Pings Sent/Recv : {self.pings_sent}/{self.pings_received:<25}|")
            print("+------------------------------------------------+")
            print(f"| Avg Latency     : {avg:6.1f} ms  {self._latency_label(avg):<10}|")
            print(f"| Min / Max       : {self.min_latency():6.1f} / {self.max_latency():6.1f} ms |")
            print(f"| Jitter          : {jitter:6.1f} ms  {self._bar(jitter, 100):<20}|")
            print(f"| Packet Loss     : {loss:6.1f}%   {self._bar(loss, 100):<20}|")
            print(f"| Update Rate     : {rate:6.1f}/s  {self._bar(rate, 30):<20}|")
            print("+------------------------------------------------+")

            if self.player_states:
                print("| Visible Players                                 |")
                for player_id, info in list(self.player_states.items())[:5]:
                    label = info.get("name", player_id)[:10]
                    x = info.get("x", 0)
                    y = info.get("y", 0)
                    print(f"| {label:<12} x={x:<4} y={y:<4}                    |")
                print("+------------------------------------------------+")

            print("Press Ctrl+C to stop.")

    def _ping_loop(self):
        while self.running:
            self.sock.sendto(make_packet(PType.PING, {"player_id": PLAYER_ID}), self.server)
            self.pings_sent += 1
            time.sleep(PING_RATE)

    def run(self):
        print(f"[MONITOR] Connecting to {SERVER_IP}:{SERVER_PORT}...")
        self.sock.sendto(
            make_packet(
                PType.JOIN,
                {
                    "player_id": PLAYER_ID,
                    "name": "__monitor__",
                    "color": "#888888",
                },
            ),
            self.server,
        )

        threading.Thread(target=self._receive_loop, daemon=True).start()
        threading.Thread(target=self._ping_loop, daemon=True).start()

        try:
            self._display_loop()
        except KeyboardInterrupt:
            print("\n[MONITOR] Stopped.")
            self.sock.sendto(make_packet(PType.LEAVE, {"player_id": PLAYER_ID}), self.server)
            self.running = False
            self.sock.close()


if __name__ == "__main__":
    NetworkMonitor().run()
