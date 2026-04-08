"""
Pygame-based multiplayer UDP client.
"""
 
import random
import socket
import sys
import threading
import time
import uuid
 
try:
    import pygame
except ImportError:
    print("Pygame not found. Install it with: pip install -r requirements.txt")
    sys.exit(1)
 
from protocol import PType, make_packet, parse_packet#parse packet decoding the raw bytes
 
SERVER_IP = input("Enter server IP (press Enter for same computer): ").strip() or "127.0.0.1"
SERVER_PORT = 5555
PLAYER_NAME = input("Enter your name: ").strip() or "Player"
 
SCREEN_W = 1000
SCREEN_H = 700
WORLD_W = 2000
WORLD_H = 2000
PLAYER_RADIUS = 18
MOVE_SPEED = 3
PING_INTERVAL = 2#how often the client pings the srever
FPS = 60#game loop controlling speed and smoothness
RECONCILE_DIST = 8
 
PALETTE = [
    (255, 80, 80),
    (80, 200, 120),
    (80, 140, 255),
    (255, 210, 60),
    (200, 100, 255),
    (60, 220, 220),
    (255, 140, 60),
    (255, 100, 180),
]
 
 
def lerp(a, b, t):
    return a + (b - a) * t
 
 
class GameClient:
    def __init__(self):
        self.player_id = str(uuid.uuid4())[:8]
        self.color = random.choice(PALETTE)
        self.color_hex = "#{:02x}{:02x}{:02x}".format(*self.color)#converting to hex 
 
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.5)
        self.server = (SERVER_IP, SERVER_PORT)
        self.seq = 0
 
        self.local_x = float(WORLD_W // 2)
        self.local_y = float(WORLD_H // 2)
        self.server_state = {}
        self.smooth_pos = {}
        self.chat_messages = []
 
        self.latency = 0.0
        self.jitter = 0.0
        self.latency_history = []
        self.packets_sent = 0
        self.packets_recv = 0
        self.packets_lost = 0
        self.last_seq_seen = -1
 
        self.running = True
        self.chat_active = False
        self.chat_input = ""
 
    def _next_seq(self):
        self.seq += 1
        return self.seq
 
    def _send(self, ptype, data):
        packet = make_packet(ptype, data, self._next_seq())
        self.sock.sendto(packet, self.server)
        self.packets_sent += 1
 
    def _real_players(self):
        """Returns server_state entries that are not monitors."""
        return {
            pid: info
            for pid, info in self.server_state.items()
            if not info.get("is_monitor", False)
        }
 
    def _receive_loop(self):
        while self.running:
            try:
                raw, _ = self.sock.recvfrom(8192)
                packet = parse_packet(raw)
                self.packets_recv += 1
 
                seq = packet.get("seq", 0)
                if self.last_seq_seen >= 0 and seq > self.last_seq_seen + 1:
                    self.packets_lost += seq - self.last_seq_seen - 1
                self.last_seq_seen = max(self.last_seq_seen, seq)
 
                if packet["type"] == PType.STATE:
                    self._handle_state(packet["data"])
                elif packet["type"] == PType.PONG:
                    self._handle_pong(packet)
                elif packet["type"] == PType.CHAT:
                    data = packet["data"]
                    self.chat_messages.append((data["name"], data["message"], time.time()))
                    if len(self.chat_messages) > 8:
                        self.chat_messages.pop(0)
            except socket.timeout:
                continue
            except Exception:
                pass
 
    def _handle_state(self, state):
        self.server_state = state
        if self.player_id in state:
            player = state[self.player_id]
            if (
                abs(player["x"] - self.local_x) > RECONCILE_DIST
                or abs(player["y"] - self.local_y) > RECONCILE_DIST
            ):
                self.local_x = player["x"]
                self.local_y = player["y"]
 
    def _handle_pong(self, packet):
        rtt = (time.time() - packet["data"]["client_time"]) * 1000
        self.latency = rtt
        self.latency_history.append(rtt)
        if len(self.latency_history) > 20:
            self.latency_history.pop(0)
        if len(self.latency_history) >= 2:
            diffs = [
                abs(self.latency_history[i] - self.latency_history[i - 1])
                for i in range(1, len(self.latency_history))
            ]
            self.jitter = sum(diffs) / len(diffs)
 
    def _ping_loop(self):
        while self.running:
            self._send(PType.PING, {"player_id": self.player_id})
            time.sleep(PING_INTERVAL)
 
    def _apply_move(self, dx, dy):
        self.local_x = max(PLAYER_RADIUS, min(WORLD_W - PLAYER_RADIUS, self.local_x + dx))
        self.local_y = max(PLAYER_RADIUS, min(WORLD_H - PLAYER_RADIUS, self.local_y + dy))
        self._send(
            PType.MOVE,
            {
                "player_id": self.player_id,
                "x": int(self.local_x),
                "y": int(self.local_y),
            },
        )
 
    def _draw_grid(self, surface, cam_x, cam_y):
        grid = 100
        color = (40, 40, 55)
        x = -(cam_x % grid)
        while x < SCREEN_W:
            pygame.draw.line(surface, color, (int(x), 0), (int(x), SCREEN_H))
            x += grid
        y = -(cam_y % grid)
        while y < SCREEN_H:
            pygame.draw.line(surface, color, (0, int(y)), (SCREEN_W, int(y)))
            y += grid
 
    def _draw_player(self, surface, sx, sy, color, name, is_self, font):
        sx, sy = int(sx), int(sy)
        pygame.draw.circle(surface, (0, 0, 0), (sx + 3, sy + 3), PLAYER_RADIUS)
        pygame.draw.circle(surface, color, (sx, sy), PLAYER_RADIUS)
        if is_self:
            pygame.draw.circle(surface, (255, 255, 255), (sx, sy), PLAYER_RADIUS, 3)
        else:
            outline = tuple(max(0, channel - 60) for channel in color)
            pygame.draw.circle(surface, outline, (sx, sy), PLAYER_RADIUS, 2)
        label = font.render(name, True, (255, 255, 255))
        surface.blit(label, (sx - label.get_width() // 2, sy - PLAYER_RADIUS - 20))
 
    def _draw_hud(self, surface, font_sm):
        panel = pygame.Surface((260, 130), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 150))
        surface.blit(panel, (10, 10))
        real_players = self._real_players()  # <-- exclude monitors from count
        lines = [
            f"Player : {PLAYER_NAME}",
            f"Pos    : ({int(self.local_x)}, {int(self.local_y)})",
            f"Latency: {self.latency:.1f} ms",
            f"Jitter : {self.jitter:.1f} ms",
            f"Loss   : {(self.packets_lost / max(self.packets_sent, 1) * 100):.1f}%",
            f"Online : {len(real_players)} player(s)",  # <-- correct count
        ]
        for index, line in enumerate(lines):
            text_surface = font_sm.render(line, True, (200, 220, 255))
            surface.blit(text_surface, (18, 16 + index * 19))
 
        if self.latency < 50:
            latency_color = (80, 255, 120)
        elif self.latency < 100:
            latency_color = (255, 220, 60)
        else:
            latency_color = (255, 80, 80)
        pygame.draw.circle(surface, latency_color, (245, 22), 7)
 
    def _draw_chat(self, surface, font_sm):
        now = time.time()
        y = SCREEN_H - 120
        for name, message, ts in reversed(self.chat_messages[-6:]):
            if now - ts > 12:
                continue
            text = font_sm.render(f"{name}: {message}", True, (240, 240, 160))
            surface.blit(text, (14, y))
            y -= 22
        if self.chat_active:
            box = pygame.Surface((500, 34), pygame.SRCALPHA)
            box.fill((0, 0, 0, 180))
            surface.blit(box, (10, SCREEN_H - 44))
            prompt = font_sm.render(f"Chat: {self.chat_input}_", True, (255, 255, 100))
            surface.blit(prompt, (16, SCREEN_H - 38))
 
    def _draw_controls(self, surface, font_sm):
        hints = ["WASD / Arrows: Move", "T: Chat", "ESC: Quit"]
        for index, hint in enumerate(hints):
            text_surface = font_sm.render(hint, True, (130, 130, 160))
            surface.blit(text_surface, (SCREEN_W - 200, SCREEN_H - 70 + index * 20))
 
    def _draw_minimap(self, surface):
        mm_w, mm_h = 140, 100
        mm_x = SCREEN_W - mm_w - 10
        mm_y = SCREEN_H - mm_h - 95
        scale_x = mm_w / WORLD_W
        scale_y = mm_h / WORLD_H
        background = pygame.Surface((mm_w, mm_h), pygame.SRCALPHA)
        background.fill((0, 0, 0, 160))
        surface.blit(background, (mm_x, mm_y))
        pygame.draw.rect(surface, (80, 80, 120), (mm_x, mm_y, mm_w, mm_h), 1)
        for player_id, info in self._real_players().items():  # <-- exclude monitors
            px = mm_x + int(info["x"] * scale_x)
            py = mm_y + int(info["y"] * scale_y)
            color = PALETTE[hash(player_id) % len(PALETTE)]
            radius = 5 if player_id == self.player_id else 3
            pygame.draw.circle(surface, color, (px, py), radius)
 
    def run(self):
        pygame.init()
        screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption(f"Multiplayer Engine - {PLAYER_NAME}")
        clock = pygame.time.Clock()
        font_sm = pygame.font.SysFont("consolas", 15)
 
        self._send(
            PType.JOIN,
            {
                "player_id": self.player_id,
                "name": PLAYER_NAME,
                "color": self.color_hex,
            },
        )
 
        threading.Thread(target=self._receive_loop, daemon=True).start()
        threading.Thread(target=self._ping_loop, daemon=True).start()
 
        while self.running:
            clock.tick(FPS)
 
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN:
                    if self.chat_active:
                        if event.key == pygame.K_RETURN:
                            if self.chat_input.strip():
                                self._send(
                                    PType.CHAT,
                                    {
                                        "player_id": self.player_id,
                                        "name": PLAYER_NAME,
                                        "message": self.chat_input.strip(),
                                    },
                                )
                            self.chat_input = ""
                            self.chat_active = False
                        elif event.key == pygame.K_ESCAPE:
                            self.chat_input = ""
                            self.chat_active = False
                        elif event.key == pygame.K_BACKSPACE:
                            self.chat_input = self.chat_input[:-1]
                        elif len(self.chat_input) < 60:
                            self.chat_input += event.unicode
                    else:
                        if event.key == pygame.K_ESCAPE:
                            self.running = False
                        elif event.key == pygame.K_t:
                            self.chat_active = True
 
            if not self.chat_active:
                keys = pygame.key.get_pressed()
                dx = 0
                dy = 0
                if keys[pygame.K_LEFT] or keys[pygame.K_a]:
                    dx -= MOVE_SPEED
                if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
                    dx += MOVE_SPEED
                if keys[pygame.K_UP] or keys[pygame.K_w]:
                    dy -= MOVE_SPEED
                if keys[pygame.K_DOWN] or keys[pygame.K_s]:
                    dy += MOVE_SPEED
                if dx != 0 or dy != 0:
                    self._apply_move(dx, dy)
 
            cam_x = max(0, min(WORLD_W - SCREEN_W, self.local_x - SCREEN_W / 2))
            cam_y = max(0, min(WORLD_H - SCREEN_H, self.local_y - SCREEN_H / 2))
 
            # Smooth interpolation for real players only
            for player_id, info in self._real_players().items():  # <-- exclude monitors
                if player_id == self.player_id:
                    continue
                if player_id not in self.smooth_pos:
                    self.smooth_pos[player_id] = [float(info["x"]), float(info["y"])]
                else:
                    self.smooth_pos[player_id][0] = lerp(
                        self.smooth_pos[player_id][0], info["x"], 0.2
                    )
                    self.smooth_pos[player_id][1] = lerp(
                        self.smooth_pos[player_id][1], info["y"], 0.2
                    )
 
            screen.fill((22, 22, 35))
            self._draw_grid(screen, cam_x, cam_y)
 
            border_rect = pygame.Rect(-cam_x, -cam_y, WORLD_W, WORLD_H)
            pygame.draw.rect(screen, (60, 60, 90), border_rect, 3)
 
            # Draw other real players only
            for player_id, info in self._real_players().items():  # <-- exclude monitors
                if player_id == self.player_id:
                    continue
                smooth_position = self.smooth_pos.get(player_id, [info["x"], info["y"]])
                sx = smooth_position[0] - cam_x
                sy = smooth_position[1] - cam_y
                color = PALETTE[hash(player_id) % len(PALETTE)]
                self._draw_player(screen, sx, sy, color, info["name"], False, font_sm)
 
            self._draw_player(
                screen,
                self.local_x - cam_x,
                self.local_y - cam_y,
                self.color,
                PLAYER_NAME,
                True,
                font_sm,
            )
 
            self._draw_hud(screen, font_sm)
            self._draw_chat(screen, font_sm)
            self._draw_controls(screen, font_sm)
            self._draw_minimap(screen)
 
            pygame.display.flip()
 
        self._send(PType.LEAVE, {"player_id": self.player_id})
        pygame.quit()
        self.sock.close()
        print("Disconnected. Goodbye!")
 
 
if __name__ == "__main__":
    GameClient().run()
