"""Mario-style side-scrolling platformer for Python 3.11 + Pygame.

Install once: py -3.11 -m pip install pygame
Run:          py -3.11 main.py

Controls: A/D or Left/Right = move, W/Up/Space = jump, Esc = pause,
          R = restart after game over, Q or window close = quit.

This is a graphical migration of the user's CMD platformer. It retains three
worlds, jumping/stomping combat, health/lives, coins, optional treasure chests,
level progression, a final victory condition, and sound effects. New features:
spikes, moving platforms, and persistent per-run checkpoints.
"""

import math
import random
import struct
import sys
import time

import pygame

# ---------------------------- Configuration ----------------------------
SCREEN_W, SCREEN_H = 1000, 640
FPS = 60
TILE = 40
GRAVITY = 1800.0
PLAYER_SPEED = 300.0
JUMP_SPEED = 690.0
PLAYER_W, PLAYER_H = 28, 42
START_HEALTH, START_LIVES = 3, 3
INVULN_SECONDS = 1.35
TOTAL_LEVELS = 3
LEVEL_NAMES = {1: "Green Hills", 2: "Crystal Caverns", 3: "Lava Fortress"}
LEVEL_WIDTHS = {1: 3000, 2: 3400, 3: 3800}

SKY = (130, 205, 245)
WHITE = (250, 250, 245)
DARK = (30, 36, 48)
GOLD = (255, 205, 55)
RED = (220, 65, 65)
GREEN = (72, 180, 92)


def clamp(value, low, high):
    return max(low, min(value, high))


def make_tone(frequency=600, duration_ms=90, volume=0.18):
    """Create a short mono sound without needing external audio files."""
    sample_rate = 22050
    count = max(1, int(sample_rate * duration_ms / 1000))
    samples = bytearray()
    for i in range(count):
        envelope = min(1.0, i / 250, (count - i) / 500)
        value = int(127 * volume * envelope * math.sin(2 * math.pi * frequency * i / sample_rate))
        samples.extend(struct.pack("<h", value * 256))
    return pygame.mixer.Sound(buffer=bytes(samples))


class SoundBank:
    def __init__(self):
        self.sounds = {}
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
            patterns = {
                "jump": [(650, 65)],
                "coin": [(850, 45), (1150, 60)],
                "chest": [(520, 70), (660, 70), (820, 110)],
                "stomp": [(280, 65)],
                "hurt": [(180, 140)],
                "checkpoint": [(620, 75), (850, 100)],
                "level": [(520, 90), (660, 90), (790, 90), (1040, 170)],
                "win": [(660, 100), (790, 100), (990, 100), (1320, 230)],
                "game_over": [(420, 130), (310, 160), (210, 240)],
            }
            for name, notes in patterns.items():
                self.sounds[name] = [make_tone(freq, dur) for freq, dur in notes]
        except (pygame.error, RuntimeError, OSError):
            self.sounds = {}

    def play(self, name):
        notes = self.sounds.get(name, [])
        for i, sound in enumerate(notes):
            try:
                # Small delays make multi-note effects melodic without blocking gameplay.
                if i == 0:
                    sound.play()
                else:
                    pygame.time.set_timer(pygame.USEREVENT + i, 45 * i, loops=1)
                    PENDING_SOUNDS[pygame.USEREVENT + i] = sound
            except pygame.error:
                pass


PENDING_SOUNDS = {}


class MovingPlatform:
    def __init__(self, x, y, width, travel, speed, phase=0.0):
        self.start_x = float(x)
        self.x = float(x)
        self.y = float(y)
        self.w = width
        self.h = 14
        self.travel = float(travel)
        self.speed = float(speed)
        self.phase = phase
        self.prev_x = self.x

    @property
    def rect(self):
        return pygame.Rect(round(self.x), round(self.y), self.w, self.h)

    def update(self, dt, elapsed):
        self.prev_x = self.x
        self.x = self.start_x + math.sin(elapsed * self.speed + self.phase) * self.travel

    @property
    def dx(self):
        return self.x - self.prev_x


def make_level(level_number):
    """Build level geometry in world coordinates. Rectangles use top-left coordinates."""
    world_w = LEVEL_WIDTHS[level_number]
    ground_y = SCREEN_H - 72
    ground = pygame.Rect(0, ground_y, world_w, SCREEN_H - ground_y + 100)

    # (x, y, width, height): fixed platforms.
    # Each world has its own platform route, silhouette, spacing, and height rhythm.
    # Collision uses these rectangles; rendering below gives each set its own material.
    layouts = {
        1: [  # Green Hills: broad grassy stepping-stones, gently rising and falling.
            (220, 475, 190, 22), (475, 420, 170, 20), (700, 365, 195, 22),
            (955, 445, 175, 20), (1190, 390, 210, 22), (1460, 330, 175, 20),
            (1695, 410, 195, 22), (1950, 350, 180, 20), (2190, 440, 205, 22),
            (2460, 380, 185, 22), (2710, 435, 190, 20)],
        2: [  # Crystal Caverns: narrow, staggered shelves with moderate jumps between them.
            (210, 445, 145, 24), (400, 375, 155, 28), (620, 430, 135, 22),
            (815, 355, 165, 26), (1045, 300, 145, 24), (1245, 380, 155, 28),
            (1460, 325, 140, 22), (1660, 415, 165, 26), (1885, 350, 150, 24),
            (2095, 285, 165, 28), (2320, 385, 145, 22), (2525, 320, 165, 26),
            (2750, 405, 150, 24), (2960, 340, 165, 26), (3180, 425, 140, 24)],
        3: [  # Lava Fortress: broad basalt battlements with varied heights and bridge sections.
            (200, 455, 170, 30), (425, 385, 145, 26), (630, 320, 155, 30),
            (850, 430, 185, 28), (1095, 360, 150, 26), (1305, 290, 165, 30),
            (1535, 405, 180, 28), (1775, 335, 150, 26), (1985, 270, 170, 30),
            (2220, 420, 185, 28), (2460, 350, 155, 26), (2675, 285, 165, 30),
            (2905, 425, 185, 28), (3150, 355, 155, 26), (3365, 295, 170, 30),
            (3590, 425, 170, 28)],
    }
    platforms = [pygame.Rect(*p) for p in layouts[level_number]]

    # Moving platforms are deliberately positioned over safe gaps.
    moving = []
    moving_specs = {
        1: [(650, 500, 110, 110, 1.35, 0.0), (1510, 485, 120, 125, 1.1, 1.2), (2190, 490, 110, 95, 1.45, 2.0)],
        2: [(430, 500, 110, 115, 1.4, 0.0), (1250, 500, 120, 135, 1.25, 1.0), (2150, 495, 115, 120, 1.5, 2.0), (2870, 500, 120, 130, 1.1, 0.5)],
        3: [(390, 500, 110, 125, 1.5, 0.0), (1170, 500, 110, 135, 1.4, 1.0), (1980, 500, 120, 140, 1.3, 2.0), (2700, 500, 110, 120, 1.55, 0.3), (3250, 500, 120, 120, 1.2, 1.4)],
    }
    for spec in moving_specs[level_number]:
        moving.append(MovingPlatform(*spec))

    # Coins: rows on ground and above fixed platforms. All are required to finish.
    coins = []
    # Ground coins overlap the player's body while standing, so they can be
    # collected naturally by walking. Platform coins sit just above each ledge.
    for x in range(130, world_w - 100, 145):
        coins.append(pygame.Rect(x, ground_y - 32, 20, 20))
    for p in platforms:
        for x in range(p.left + 25, p.right - 15, 65):
            coins.append(pygame.Rect(x, p.top - 32, 20, 20))
    # Do not place required coins on moving platforms: those coins used to stay
    # behind as the platform moved, making the level-completion goal unreliable.

    chest_xs = list(range(600, world_w - 120, 650))
    chests = [pygame.Rect(x, ground_y - 36, 30, 30) for x in chest_xs]

    # Enemy patrol ranges remain local to their spawn areas.
    enemies = []
    spacing = {1: 330, 2: 295, 3: 265}[level_number]
    for x in range(360, world_w - 100, spacing):
        enemies.append({
            "rect": pygame.Rect(x, ground_y - 36, 30, 36),
            "left": max(30, x - 90), "right": min(world_w - 40, x + 90),
            "dir": random.choice([-1, 1]), "alive": True,
            "speed": 65 + level_number * 12,
        })

    # Each world has its own obstacle pattern. All hazard rectangles use the
    # same damage logic, but their shapes, spacing, and visuals differ by world.
    spikes = []
    if level_number == 1:
        # Green Hills: familiar, clearly visible short spike strips.
        spike_patches = [
            (470, 58), (820, 76), (1190, 58), (1570, 82),
            (1980, 65), (2350, 78), (2700, 60),
        ]
        spikes = [pygame.Rect(x, ground_y - 22, w, 22) for x, w in spike_patches]
    elif level_number == 2:
        # Crystal Caverns: tall, chunky crystal formations on the ground,
        # with floating crystal shards that force the player to change height.
        crystal_pillars = [
            (390, 62, 48), (665, 78, 58), (1010, 58, 46),
            (1300, 88, 66), (1650, 68, 52), (1960, 82, 62),
            (2320, 60, 48), (2600, 92, 70), (3010, 72, 54),
        ]
        spikes = [pygame.Rect(x, ground_y - h, w, h) for x, h, w in crystal_pillars]
        # Floating crystal clusters are deliberately high enough to be visibly
        # different from the ground hazards and are dangerous to touch.
        for x, y, w, h in [
            (850, 425, 54, 34), (1470, 385, 66, 38),
            (2110, 420, 58, 36), (2790, 365, 70, 42),
        ]:
            spikes.append(pygame.Rect(x, y, w, h))
    else:
        # Lava Fortress: broad, bright lava channels plus tall fire vents.
        # These wide zones demand longer jumps; the vents add vertical danger.
        lava_patches = [
            (430, 112), (850, 150), (1320, 125), (1770, 165),
            (2260, 145), (2730, 170), (3230, 135),
        ]
        spikes = [pygame.Rect(x, ground_y - 24, w, 24) for x, w in lava_patches]
        for x, y, w, h in [
            (700, 455, 48, 42), (1120, 425, 54, 48),
            (1660, 445, 50, 44), (2110, 400, 58, 52),
            (2580, 435, 52, 46), (3080, 420, 60, 50),
        ]:
            spikes.append(pygame.Rect(x, y, w, h))

    # Checkpoints are world positions; touching one saves the respawn point.
    checkpoint_xs = [world_w // 3, (world_w * 2) // 3]
    checkpoints = [
        {"x": x, "rect": pygame.Rect(x, ground_y - 92, 22, 92), "active": False}
        for x in checkpoint_xs
    ]
    return world_w, ground_y, ground, platforms, moving, coins, chests, enemies, spikes, checkpoints


class Player:
    def __init__(self, x, y):
        self.rect = pygame.Rect(x, y, PLAYER_W, PLAYER_H)
        self.vx = 0.0
        self.vy = 0.0
        self.on_ground = False
        self.coyote_time = 0.0
        self.jump_buffer = 0.0
        self.health = START_HEALTH
        self.lives = START_LIVES
        self.score = 0
        self.kills = 0
        self.invulnerable_until = 0.0
        self.checkpoint_x = x
        self.checkpoint_y = y
        self.facing = 1


def draw_text(surface, font, text, x, y, color=WHITE, shadow=True):
    rendered = font.render(str(text), True, color)
    if shadow:
        surface.blit(font.render(str(text), True, (20, 25, 32)), (x + 2, y + 2))
    surface.blit(rendered, (x, y))


def draw_background(screen, camera_x, level_number):
    if level_number == 1:
        screen.fill((125, 205, 245))
        hill_color, far_color = (95, 185, 130), (65, 150, 100)
    elif level_number == 2:
        screen.fill((48, 53, 100))
        hill_color, far_color = (75, 85, 145), (45, 50, 95)
    else:
        screen.fill((70, 30, 38))
        hill_color, far_color = (135, 65, 50), (95, 40, 45)
    # Parallax hills add depth while keeping the game asset-free.
    offset1 = int(camera_x * 0.18) % 360
    offset2 = int(camera_x * 0.32) % 480
    for i in range(-1, 5):
        x = i * 360 - offset1
        pygame.draw.ellipse(screen, far_color, (x, SCREEN_H - 230, 450, 300))
    for i in range(-1, 4):
        x = i * 480 - offset2
        pygame.draw.ellipse(screen, hill_color, (x, SCREEN_H - 170, 520, 240))
    if level_number == 1:
        for i in range(6):
            x = (i * 230 - int(camera_x * 0.08)) % (SCREEN_W + 80) - 40
            pygame.draw.circle(screen, (255, 255, 255), (x, 75 + (i % 3) * 28), 18)
            pygame.draw.circle(screen, (255, 255, 255), (x + 20, 78 + (i % 3) * 28), 14)


def draw_player(screen, player, camera_x, now):
    if now < player.invulnerable_until and int(now * 14) % 2:
        return
    r = player.rect.move(-int(camera_x), 0)
    # Tiny cartoon adventurer built from shapes; no external sprite files needed.
    pygame.draw.ellipse(screen, (25, 25, 30), (r.x + 2, r.bottom - 5, r.w - 4, 8))
    pygame.draw.rect(screen, (205, 50, 55), (r.x + 3, r.y + 1, r.w - 6, 11), border_radius=4)
    pygame.draw.rect(screen, (244, 190, 135), (r.x + 5, r.y + 9, r.w - 10, 13), border_radius=4)
    pygame.draw.rect(screen, (45, 90, 210), (r.x + 3, r.y + 21, r.w - 6, 15), border_radius=3)
    pygame.draw.rect(screen, (75, 45, 35), (r.x + 2, r.y + 34, 10, 8))
    pygame.draw.rect(screen, (75, 45, 35), (r.x + 16, r.y + 34, 10, 8))
    eye_x = r.x + (19 if player.facing > 0 else 7)
    pygame.draw.circle(screen, (25, 25, 30), (eye_x, r.y + 14), 2)


def draw_enemy(screen, enemy, camera_x, now):
    if not enemy["alive"]:
        return
    r = enemy["rect"].move(-int(camera_x), 0)
    pygame.draw.ellipse(screen, (45, 30, 35), (r.x, r.y + 5, r.w, r.h - 3))
    pygame.draw.circle(screen, (245, 90, 80), (r.centerx, r.y + 10), 13)
    pygame.draw.circle(screen, WHITE, (r.x + 10, r.y + 12), 4)
    pygame.draw.circle(screen, WHITE, (r.x + 21, r.y + 12), 4)
    pygame.draw.circle(screen, DARK, (r.x + 11, r.y + 13), 2)
    pygame.draw.circle(screen, DARK, (r.x + 20, r.y + 13), 2)


def reset_player_at_checkpoint(player, sound):
    player.rect.topleft = (player.checkpoint_x, player.checkpoint_y)
    player.vx = player.vy = 0.0
    player.health = START_HEALTH
    player.invulnerable_until = time.time() + INVULN_SECONDS
    sound.play("hurt")


def main():
    pygame.init()
    pygame.display.set_caption("Pixel Quest — Platformer")
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas", 20, bold=True)
    small_font = pygame.font.SysFont("consolas", 16, bold=True)
    title_font = pygame.font.SysFont("consolas", 42, bold=True)
    sound = SoundBank()

    level_number = 1
    level_data = make_level(level_number)
    (world_w, ground_y, ground, platforms, moving_platforms, coins,
     chests, enemies, spikes, checkpoints) = level_data
    player = Player(70, ground_y - PLAYER_H)
    camera_x = 0.0
    elapsed = 0.0
    message = "Collect every coin and stomp every enemy!"
    message_until = time.time() + 4
    game_state = "menu"  # menu, playing, paused, game_over, victory
    opened_chests = set()
    collected_count = 0
    checkpoint_count = 0
    last_safe_ground = (player.rect.x, player.rect.y)

    def load_level(next_level, preserve_stats=True):
        nonlocal level_number, level_data, world_w, ground_y, ground, platforms
        nonlocal moving_platforms, coins, chests, enemies, spikes, checkpoints
        nonlocal opened_chests, collected_count, checkpoint_count, camera_x, message, message_until
        level_number = next_level
        level_data = make_level(level_number)
        (world_w, ground_y, ground, platforms, moving_platforms, coins,
         chests, enemies, spikes, checkpoints) = level_data
        player.rect.topleft = (70, ground_y - PLAYER_H)
        player.vx = player.vy = 0.0
        player.on_ground = False
        player.coyote_time = player.jump_buffer = 0.0
        player.checkpoint_x, player.checkpoint_y = player.rect.topleft
        player.invulnerable_until = time.time() + INVULN_SECONDS
        opened_chests = set()
        collected_count = checkpoint_count = 0
        camera_x = 0.0
        message = f"World {level_number}: {LEVEL_NAMES[level_number]}"
        message_until = time.time() + 3

    def take_damage(knockback=1):
        nonlocal message, message_until, game_state
        now = time.time()
        if now < player.invulnerable_until:
            return
        player.health -= 1
        player.invulnerable_until = now + INVULN_SECONDS
        player.vx = -250 * knockback
        player.vy = -360
        sound.play("hurt")
        message = f"Ouch! Health: {max(0, player.health)}"
        message_until = now + 1.5
        if player.health <= 0:
            player.lives -= 1
            if player.lives <= 0:
                sound.play("game_over")
                game_state = "game_over"
            else:
                reset_player_at_checkpoint(player, sound)
                message = f"Lost a life! {player.lives} lives left — checkpoint restored."
                message_until = now + 2.5

    running = True
    while running:
        dt = min(clock.tick(FPS) / 1000.0, 0.035)
        elapsed += dt
        now = time.time()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type in PENDING_SOUNDS:
                try:
                    PENDING_SOUNDS.pop(event.type).play()
                except pygame.error:
                    pass
            elif event.type == pygame.KEYDOWN:
                if game_state == "menu":
                    if event.key in (pygame.K_RETURN, pygame.K_SPACE):
                        game_state = "playing"
                elif game_state == "playing":
                    if event.key == pygame.K_ESCAPE:
                        game_state = "paused"
                    elif event.key in (pygame.K_SPACE, pygame.K_w, pygame.K_UP):
                        # Buffer jump input briefly so it still works just before landing.
                        player.jump_buffer = 0.14
                    elif event.key == pygame.K_q:
                        running = False
                elif game_state == "paused":
                    if event.key == pygame.K_ESCAPE:
                        game_state = "playing"
                    elif event.key == pygame.K_q:
                        running = False
                elif game_state in ("game_over", "victory"):
                    if event.key == pygame.K_r:
                        level_number = 1
                        level_data = make_level(level_number)
                        (world_w, ground_y, ground, platforms, moving_platforms, coins,
                         chests, enemies, spikes, checkpoints) = level_data
                        player = Player(70, ground_y - PLAYER_H)
                        camera_x = 0.0
                        elapsed = 0.0
                        opened_chests = set()
                        collected_count = checkpoint_count = 0
                        message = "Collect every coin and stomp every enemy!"
                        message_until = time.time() + 3
                        game_state = "playing"
                    elif event.key in (pygame.K_ESCAPE, pygame.K_q):
                        running = False

        keys = pygame.key.get_pressed()
        if game_state == "playing":
            # Update moving platforms before collision so their displacement is known.
            for mp in moving_platforms:
                mp.update(dt, elapsed)

            old_rect = player.rect.copy()
            player.vx = 0.0
            if keys[pygame.K_LEFT] or keys[pygame.K_a]:
                player.vx = -PLAYER_SPEED
                player.facing = -1
            if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
                player.vx = PLAYER_SPEED
                player.facing = 1

            # Carry the player horizontally when standing on a moving platform.
            for mp in moving_platforms:
                if player.on_ground and abs(player.rect.bottom - mp.rect.top) <= 5 and player.rect.right > mp.rect.left and player.rect.left < mp.rect.right:
                    player.rect.x += round(mp.dx)
                    break

            player.rect.x += round(player.vx * dt)
            player.rect.x = int(clamp(player.rect.x, 0, world_w - player.rect.w))

            # Horizontal collision with fixed platforms is intentionally solid.
            for p in platforms:
                if player.rect.colliderect(p):
                    if player.vx > 0:
                        player.rect.right = p.left
                    elif player.vx < 0:
                        player.rect.left = p.right

            # Reliable jump timing: a short coyote window allows jumping just after
            # leaving an edge, and jump buffering catches input just before landing.
            if player.on_ground:
                player.coyote_time = 0.12
            else:
                player.coyote_time = max(0.0, player.coyote_time - dt)
            player.jump_buffer = max(0.0, player.jump_buffer - dt)
            if player.jump_buffer > 0 and player.coyote_time > 0:
                player.vy = -JUMP_SPEED
                player.on_ground = False
                player.coyote_time = 0.0
                player.jump_buffer = 0.0
                sound.play("jump")

            player.vy += GRAVITY * dt
            player.rect.y += round(player.vy * dt)
            player.on_ground = False
            all_solid = [ground, *platforms] + [mp.rect for mp in moving_platforms]
            for solid in all_solid:
                if player.rect.colliderect(solid):
                    if player.vy >= 0 and old_rect.bottom <= solid.top + 14:
                        player.rect.bottom = solid.top
                        player.vy = 0
                        player.on_ground = True
                    elif player.vy < 0 and old_rect.top >= solid.bottom - 12:
                        player.rect.top = solid.bottom
                        player.vy = 0

            # Coins.
            for coin_index, coin in enumerate(coins):
                if coin is not None and player.rect.colliderect(coin):
                    coins[coin_index] = None
                    player.score += 10
                    collected_count += 1
                    sound.play("coin")

            # Chests are optional; touching one opens it and grants bonus points.
            for i, chest in enumerate(chests):
                if i not in opened_chests and player.rect.colliderect(chest):
                    opened_chests.add(i)
                    player.score += 50
                    sound.play("chest")
                    message = "Treasure found! +50 points"
                    message_until = now + 1.6

            # Stomp enemies from above; side contact hurts.
            for enemy in enemies:
                if not enemy["alive"]:
                    continue
                er = enemy["rect"]
                er.x += round(enemy["dir"] * enemy["speed"] * dt)
                if er.left < enemy["left"]:
                    er.left = enemy["left"]
                    enemy["dir"] = 1
                elif er.right > enemy["right"]:
                    er.right = enemy["right"]
                    enemy["dir"] = -1
                if player.rect.colliderect(er):
                    # Ground/platform resolution may already have reset vy to zero;
                    # use the previous feet position too so stomps remain reliable.
                    if old_rect.bottom <= er.top + 18 and player.rect.bottom >= er.top:
                        enemy["alive"] = False
                        player.vy = -JUMP_SPEED * 0.48
                        player.on_ground = False
                        player.score += 100
                        player.kills += 1
                        sound.play("stomp")
                        message = "Enemy stomped! +100 points"
                        message_until = now + 1.3
                    else:
                        take_damage(1 if player.rect.centerx < er.centerx else -1)

            # Spikes.
            for spike in spikes:
                if player.rect.colliderect(spike):
                    take_damage(1 if player.rect.centerx < spike.centerx else -1)
                    break

            # Checkpoints activate in order, and remain active after respawns.
            for i, checkpoint in enumerate(checkpoints):
                if not checkpoint["active"] and player.rect.colliderect(checkpoint["rect"]):
                    checkpoint["active"] = True
                    player.checkpoint_x = checkpoint["x"]
                    player.checkpoint_y = ground_y - PLAYER_H
                    player.score += 25
                    checkpoint_count += 1
                    sound.play("checkpoint")
                    message = "Checkpoint activated! +25 points"
                    message_until = now + 2

            # Falling off the map costs health and returns the player to the checkpoint.
            if player.rect.top > SCREEN_H + 100:
                take_damage(1)
                if game_state == "playing":
                    player.rect.topleft = (player.checkpoint_x, player.checkpoint_y)
                    player.vx = player.vy = 0
                    player.invulnerable_until = now + INVULN_SECONDS

            # Final level condition remains: all coins and all enemies defeated.
            level_complete = (all(c is None for c in coins)
                              and all(not e["alive"] for e in enemies))
            if level_complete:
                if level_number < TOTAL_LEVELS:
                    completed_level = level_number
                    player.score += 250
                    sound.play("level")
                    load_level(completed_level + 1)
                else:
                    game_state = "victory"
                    sound.play("win")

            target_camera = player.rect.centerx - SCREEN_W * 0.42
            camera_x += (clamp(target_camera, 0, world_w - SCREEN_W) - camera_x) * min(1, dt * 8)

        # ------------------------------- Draw -------------------------------
        draw_background(screen, camera_x, level_number)
        cam = int(camera_x)

        # Ground and platforms.
        pygame.draw.rect(screen, (70, 145, 65) if level_number == 1 else ((90, 100, 150) if level_number == 2 else (165, 65, 45)), ground.move(-cam, 0))
        pygame.draw.rect(screen, (50, 105, 45), (0, ground_y - cam * 0, SCREEN_W, 8))
        for p in platforms:
            r = p.move(-cam, 0)
            if level_number == 1:
                # Green Hills: earthy floating soil with a grassy, uneven-looking lip.
                pygame.draw.rect(screen, (120, 78, 46), r, border_radius=5)
                pygame.draw.rect(screen, (74, 160, 65), (r.x, r.y, r.w, 7), border_radius=3)
                pygame.draw.line(screen, (165, 112, 65), (r.x + 8, r.bottom - 4), (r.right - 8, r.bottom - 4), 2)
                for gx in range(r.x + 10, r.right - 5, 22):
                    pygame.draw.line(screen, (105, 205, 75), (gx, r.y + 2), (gx + 3, r.y - 3), 2)
            elif level_number == 2:
                # Crystal Caverns: dark mineral ledges with luminous cyan crystal facets.
                pygame.draw.rect(screen, (45, 69, 104), r, border_radius=2)
                pygame.draw.rect(screen, (65, 151, 190), (r.x, r.y, r.w, 5), border_radius=2)
                pygame.draw.line(screen, (145, 244, 255), (r.x + 8, r.y + 7), (r.right - 8, r.y + 7), 2)
                for cx in range(r.x + 15, r.right - 8, 42):
                    pygame.draw.polygon(screen, (72, 190, 222), [(cx - 5, r.y), (cx, r.y - 7), (cx + 5, r.y)])
                    pygame.draw.line(screen, (170, 250, 255), (cx, r.y - 5), (cx, r.y - 1), 1)
            else:
                # Lava Fortress: thick basalt battlements with glowing molten seams.
                pygame.draw.rect(screen, (66, 49, 53), r, border_radius=2)
                pygame.draw.rect(screen, (126, 61, 48), (r.x, r.y, r.w, 6))
                pygame.draw.line(screen, (255, 112, 38), (r.x + 5, r.bottom - 3), (r.right - 5, r.bottom - 3), 2)
                for bx in range(r.x + 8, r.right - 8, 34):
                    pygame.draw.line(screen, (39, 33, 40), (bx, r.y + 8), (bx + 12, r.y + 8), 2)
                for bx in range(r.x + 14, r.right - 5, 48):
                    pygame.draw.rect(screen, (191, 79, 44), (bx, r.y + 9, 3, max(4, r.height - 12)))
        for mp in moving_platforms:
            r = mp.rect.move(-cam, 0)
            pygame.draw.rect(screen, (240, 185, 65), r, border_radius=6)
            pygame.draw.rect(screen, (255, 225, 130), (r.x, r.y, r.w, 4), border_radius=3)
            pygame.draw.circle(screen, (105, 70, 30), (r.left + 12, r.centery), 3)
            pygame.draw.circle(screen, (105, 70, 30), (r.right - 12, r.centery), 3)

        # Obstacles are themed per world: stone spikes, glowing crystals,
        # and animated-looking lava channels. Their collision remains reliable.
        for hazard in spikes:
            r = hazard.move(-cam, 0)
            if level_number == 1:
                for sx in range(r.x, r.right, 18):
                    tip_x = min(sx + 9, r.right)
                    end_x = min(sx + 18, r.right)
                    pygame.draw.polygon(screen, (205, 215, 225), [(sx, r.bottom), (tip_x, r.top), (end_x, r.bottom)])
                    pygame.draw.line(screen, (100, 110, 125), (tip_x, r.top), (end_x, r.bottom), 2)
            elif level_number == 2:
                # Crystal Caverns: solid-looking cyan crystal pillars and
                # floating shard clusters, not triangular ground spikes.
                pygame.draw.polygon(screen, (35, 135, 190), [
                    (r.left, r.bottom), (r.left + r.width * 0.22, r.top + 8),
                    (r.centerx, r.top), (r.right - r.width * 0.18, r.top + 12),
                    (r.right, r.bottom)])
                pygame.draw.polygon(screen, (90, 235, 255), [
                    (r.left + 4, r.bottom - 3), (r.left + r.width * 0.22, r.top + 10),
                    (r.centerx - 2, r.bottom - 8), (r.centerx, r.top + 3)])
                pygame.draw.line(screen, (195, 255, 255), (r.centerx, r.top + 5), (r.centerx, r.bottom - 5), 3)
                pygame.draw.line(screen, (30, 95, 150), (r.left + 5, r.bottom - 4), (r.left + r.width * 0.22, r.top + 10), 2)
            else:
                # Lava Fortress: broad ground channels have a dark crust and
                # animated-looking molten surface; elevated vents are flame jets.
                if r.bottom >= ground_y - 2 and r.height >= 20:
                    pygame.draw.rect(screen, (95, 28, 22), r, border_radius=3)
                    pygame.draw.rect(screen, (230, 55, 18), (r.x, r.y + 4, r.w, max(5, r.h - 4)), border_radius=3)
                    pygame.draw.line(screen, (255, 185, 45), (r.x + 4, r.y + 5), (r.right - 4, r.y + 5), 3)
                    for bx in range(r.x + 12, r.right - 5, 27):
                        bubble_y = r.y + 8 + ((bx // 27) % 3) * 4
                        pygame.draw.circle(screen, (255, 220, 65), (bx, bubble_y), 3)
                else:
                    pygame.draw.polygon(screen, (150, 35, 20), [
                        (r.left, r.bottom), (r.left + 3, r.top + 12),
                        (r.centerx, r.top), (r.right - 4, r.top + 10), (r.right, r.bottom)])
                    pygame.draw.polygon(screen, (255, 105, 20), [
                        (r.left + 8, r.bottom), (r.centerx, r.top + 8), (r.right - 8, r.bottom)])
                    pygame.draw.polygon(screen, (255, 220, 70), [
                        (r.centerx - 6, r.bottom), (r.centerx, r.top + 14), (r.centerx + 6, r.bottom)])

        # Coins and chests.
        for coin in coins:
            if coin is not None:
                r = coin.move(-cam, 0)
                pygame.draw.ellipse(screen, (170, 110, 20), r.inflate(2, 2))
                pygame.draw.ellipse(screen, GOLD, r)
                pygame.draw.line(screen, (255, 245, 155), (r.centerx, r.top + 4), (r.centerx, r.bottom - 4), 3)
        for i, chest in enumerate(chests):
            r = chest.move(-cam, 0)
            pygame.draw.rect(screen, (140, 80, 35), r, border_radius=4)
            pygame.draw.rect(screen, GOLD, (r.x, r.y + 8, r.w, 5))
            pygame.draw.rect(screen, (240, 190, 55) if i in opened_chests else (95, 50, 25), (r.centerx - 3, r.y + 13, 6, 8))
            if i in opened_chests:
                pygame.draw.line(screen, (95, 50, 25), (r.left, r.top + 3), (r.left + 5, r.top - 7), 4)

        # Checkpoint poles.
        for checkpoint in checkpoints:
            r = checkpoint["rect"].move(-cam, 0)
            color = (60, 230, 130) if checkpoint["active"] else (225, 230, 235)
            pygame.draw.rect(screen, (80, 70, 60), (r.x + 8, r.y, 5, r.h))
            pygame.draw.polygon(screen, color, [(r.x + 13, r.y + 4), (r.x + 43, r.y + 15), (r.x + 13, r.y + 27)])

        for enemy in enemies:
            draw_enemy(screen, enemy, camera_x, now)
        draw_player(screen, player, camera_x, now)

        # HUD.
        pygame.draw.rect(screen, (20, 25, 38, 220), (0, 0, SCREEN_W, 68))
        draw_text(screen, font, f"WORLD {level_number}: {LEVEL_NAMES[level_number]}", 16, 10)
        draw_text(screen, small_font, f"Health: {'♥ ' * max(0, player.health)}  Lives: {player.lives}", 16, 40, (255, 125, 125))
        draw_text(screen, small_font, f"Score: {player.score}   Coins: {sum(c is None for c in coins)}/{len(coins)}   Enemies: {sum(not e['alive'] for e in enemies)}/{len(enemies)}", 360, 14)
        draw_text(screen, small_font, "Move: A/D or ←/→   Jump: W/↑/Space   Pause: Esc", 360, 40, (225, 235, 245))
        if now < message_until:
            label = font.render(message, True, WHITE)
            screen.blit(label, (SCREEN_W // 2 - label.get_width() // 2, 82))

        if game_state in ("menu", "paused", "game_over", "victory"):
            overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            overlay.fill((8, 12, 22, 180))
            screen.blit(overlay, (0, 0))
            if game_state == "menu":
                heading, sub1, sub2 = "PIXEL QUEST", "A side-scrolling platform adventure", "Press ENTER to start"
            elif game_state == "paused":
                heading, sub1, sub2 = "PAUSED", "Press ESC to resume", "Q to quit"
            elif game_state == "game_over":
                heading, sub1, sub2 = "GAME OVER", f"Final score: {player.score}", "Press R to play again  |  Esc to quit"
            else:
                heading, sub1, sub2 = "YOU WIN!", f"All worlds cleared! Final score: {player.score}", "Press R to play again  |  Esc to quit"
            title = title_font.render(heading, True, GOLD if game_state != "game_over" else RED)
            screen.blit(title, (SCREEN_W // 2 - title.get_width() // 2, SCREEN_H // 2 - 85))
            for idx, line in enumerate((sub1, sub2)):
                text_surf = font.render(line, True, WHITE)
                screen.blit(text_surf, (SCREEN_W // 2 - text_surf.get_width() // 2, SCREEN_H // 2 + idx * 38))
            if game_state == "menu":
                hint = small_font.render("Stomp enemies from above • Avoid world hazards • Activate checkpoints", True, (190, 220, 235))
                screen.blit(hint, (SCREEN_W // 2 - hint.get_width() // 2, SCREEN_H // 2 + 92))

        pygame.display.flip()

    pygame.quit()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except pygame.error as exc:
        print("Pygame could not start:", exc)
        print("Install it with: py -3.11 -m pip install pygame")
        raise SystemExit(1)
