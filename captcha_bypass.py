import os
import random
import time
import math
from pathlib import Path
from playwright.sync_api import Page, ElementHandle, Locator

# Session file path
SESSION_STATE_PATH = Path(__file__).resolve().parent / "session_state.json"

class AdaptiveDelayTracker:
    def __init__(self, base_min: float = 1.0, base_max: float = 2.5):
        self.base_min = base_min
        self.base_max = base_max
        self.current_min = base_min
        self.current_max = base_max
        self.captcha_count = 0
        self.success_streak = 0
        
    def record_captcha(self):
        self.captcha_count += 1
        self.success_streak = 0
        print("     [AdaptiveDelay] Captcha terdeteksi; jeda tidak dinaikkan.")
        
    def record_success(self):
        self.success_streak += 1
        # After 5 successful rows, start reducing the delay back to base
        if self.success_streak >= 5:
            old_min = self.current_min
            self.current_min = max(self.base_min, self.current_min - 0.5)
            self.current_max = max(self.base_max, self.current_max - 1.0)
            if old_min != self.current_min:
                print(f"     [AdaptiveDelay] 5x sukses beruntun! Menurunkan jeda ke: {self.current_min:.1f} - {self.current_max:.1f} detik.")
            self.success_streak = 0
            
    def get_delay(self) -> float:
        return random.uniform(self.current_min, self.current_max)

    def sleep(self, page: Page, reason: str = ""):
        seconds = self.get_delay()
        if seconds <= 0:
            return
        if reason:
            print(f"     [Jeda] {reason}: {seconds:.1f} detik")
        page.wait_for_timeout(int(seconds * 1000))


# Track mouse position globally to start curves from where we left off
_last_mouse_pos = (random.randint(100, 500), random.randint(100, 500))

def generate_bezier_points(start, end, num_steps):
    x1, y1 = start
    x2, y2 = end
    
    # Random control points for cubic Bezier curve to simulate natural hand curve
    cx1 = x1 + (x2 - x1) * random.uniform(0.1, 0.4) + random.uniform(-50, 50)
    cy1 = y1 + (y2 - y1) * random.uniform(0.1, 0.4) + random.uniform(-50, 50)
    cx2 = x1 + (x2 - x1) * random.uniform(0.6, 0.9) + random.uniform(-50, 50)
    cy2 = y1 + (y2 - y1) * random.uniform(0.6, 0.9) + random.uniform(-50, 50)
    
    points = []
    for i in range(num_steps + 1):
        t = i / num_steps
        # Cubic Bezier formula
        x = (1-t)**3 * x1 + 3*(1-t)**2 * t * cx1 + 3*(1-t)*t**2 * cx2 + t**3 * x2
        y = (1-t)**3 * y1 + 3*(1-t)**2 * t * cy1 + 3*(1-t)*t**2 * cy2 + t**3 * y2
        points.append((x, y))
    return points

def move_mouse_to_locator(page: Page, locator: Locator):
    global _last_mouse_pos
    try:
        # Ensure it's scrolled into view if needed
        locator.scroll_into_view_if_needed()
        box = locator.bounding_box()
        if not box:
            return
        
        # Target center with a tiny bit of random offset
        target_x = box["x"] + box["width"] / 2 + random.uniform(-3, 3)
        target_y = box["y"] + box["height"] / 2 + random.uniform(-3, 3)
        
        start_x, start_y = _last_mouse_pos
        
        distance = math.sqrt((target_x - start_x)**2 + (target_y - start_y)**2)
        if distance < 15:
            page.mouse.move(target_x, target_y)
            _last_mouse_pos = (target_x, target_y)
            return
            
        num_steps = int(max(5, min(25, distance / 20)))
        points = generate_bezier_points((start_x, start_y), (target_x, target_y), num_steps)
        
        for x, y in points:
            page.mouse.move(x, y)
            page.wait_for_timeout(random.randint(5, 12))
            
        _last_mouse_pos = (target_x, target_y)
        page.wait_for_timeout(random.randint(100, 250)) # Micro-pause after hover
    except Exception as e:
        print(f"     [Mouse] Gagal menggerakkan mouse secara natural: {e}")
        # Fallback to standard hover
        try:
            locator.hover()
        except Exception:
            pass

def random_scroll(page: Page):
    # Scroll slightly up or down to simulate reading/natural browsing
    if random.random() < 0.25: # 25% chance
        direction = 1 if random.random() > 0.5 else -1
        scroll_y = direction * random.randint(100, 300)
        print(f"     [Scroll] Melakukan scroll random: {scroll_y}px")
        page.evaluate(f"window.scrollBy(0, {scroll_y})")
        page.wait_for_timeout(random.randint(300, 700))


def login_sso_with_storage(page: Page, context, username: str, password: str) -> None:
    print("[1] Membuka halaman manajemen mitra (memeriksa sesi)...")
    try:
        # Try going directly to the dashboard to see if session is still alive
        page.goto("https://manajemen-mitra.bps.go.id/mitra/dashboard", wait_until="networkidle", timeout=15000)
    except Exception:
        pass

    page.wait_for_timeout(2000)

    # If redirected or page URL shows dashboard, we're good
    if "mitra/dashboard" in page.url:
        print("   [OK] Sesi aktif ditemukan! Langsung masuk dashboard.")
        # Refresh the storage state file to keep it fresh
        try:
            context.storage_state(path=str(SESSION_STATE_PATH))
        except Exception:
            pass
        return

    print("   [Sesi] Sesi tidak ditemukan atau kedaluwarsa. Melakukan login SSO...")
    page.goto("https://manajemen-mitra.bps.go.id/launcher", wait_until="domcontentloaded")
    
    login_button = page.locator("button:has-text('Login SSO BPS')")
    try:
        login_button.wait_for(state="visible", timeout=10000)
        # natural mouse move and click
        move_mouse_to_locator(page, login_button)
        login_button.click()
    except Exception:
        print("   [Info] Tombol login SSO tidak muncul; melanjutkan...")

    try:
        page.wait_for_selector("#username", state="visible", timeout=15000)
        page.fill("#username", username)
        page.wait_for_timeout(random.randint(200, 500))
        page.fill("#password", password)
        page.wait_for_timeout(random.randint(200, 500))
        
        login_submit = page.locator("#kc-login")
        move_mouse_to_locator(page, login_submit)
        login_submit.click()
    except Exception:
        print("   [Info] Form login SSO tidak muncul; mungkin sudah terisi atau bypassed...")

    print("   [Sesi] Menunggu dashboard dimuat...")
    page.wait_for_url("**/mitra/dashboard**", timeout=45000)
    print("   [OK] Berhasil masuk dashboard.")
    
    # Save session state
    context.storage_state(path=str(SESSION_STATE_PATH))
    print(f"   [OK] Sesi disimpan ke: {SESSION_STATE_PATH}")
