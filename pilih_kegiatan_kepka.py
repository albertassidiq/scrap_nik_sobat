import argparse
import os
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config-automasi-pengajuan.txt"
SCREENSHOT_PATH = BASE_DIR / "pilih_kegiatan_kepka_success.png"


def read_config(filepath: Path) -> dict[str, str]:
    config = {}
    with filepath.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            config[key.strip()] = value.strip()
    return config


def get_config_value(config: dict[str, str], *keys: str) -> str:
    lowered = {key.lower(): value for key, value in config.items()}
    for key in keys:
        value = config.get(key)
        if value:
            return value
        value = lowered.get(key.lower())
        if value:
            return value
    return ""


def get_login_credentials(config: dict[str, str]) -> tuple[str, str]:
    username = get_config_value(config, "Username", "SSO Username", "user", "username")
    password = get_config_value(config, "Password", "SSO Password", "pass", "password")

    if not username or not password:
        raise ValueError("Config wajib berisi `Username` dan `Password` untuk login SSO.")

    return username, password


def wait_overlay_done(page, timeout=15000) -> None:
    try:
        page.wait_for_selector(".velmld-overlay:visible", state="hidden", timeout=timeout)
    except PlaywrightTimeoutError:
        pass


def selected_dropdown_text(page, label: str) -> str:
    dropdown = page.locator(
        f"xpath=//label[contains(normalize-space(), '{label}')]/following-sibling::div[contains(@class, 'dropdown')]"
    )
    return dropdown.locator(".text").first.inner_text(timeout=5000).strip()


def pilih_dropdown(page, label: str, nilai: str) -> None:
    print(f"-> Memilih {label} = {nilai}...")
    wait_overlay_done(page)
    page.wait_for_timeout(500)

    dropdown = page.locator(
        f"xpath=//label[contains(normalize-space(), '{label}')]/following-sibling::div[contains(@class, 'dropdown')]"
    )
    dropdown.wait_for(state="visible", timeout=30000)
    dropdown.scroll_into_view_if_needed()
    dropdown.click()

    try:
        dropdown.locator("div.item").first.wait_for(state="attached", timeout=15000)
        page.wait_for_timeout(500)
    except PlaywrightTimeoutError:
        pass

    item = dropdown.locator(f"div.item:has-text('{nilai}')").first
    try:
        item.wait_for(state="visible", timeout=4000)
        item.click(force=True)
        print(f"   [OK] {label} dipilih langsung.")
    except PlaywrightTimeoutError:
        print(f"   [Info] Opsi belum terlihat, cari dengan input: {nilai}")
        search_input = dropdown.locator("input.search")
        search_input.fill(nilai)
        page.wait_for_timeout(1000)

        try:
            item.wait_for(state="visible", timeout=7000)
            item.click(force=True)
            print(f"   [OK] {label} dipilih setelah filter.")
        except PlaywrightTimeoutError:
            opsi = dropdown.locator("div.item").all_inner_texts()
            print(f"   [DEBUG] Opsi tersedia: {[x.strip() for x in opsi if x.strip()]}")
            search_input.press("Enter")
            page.wait_for_timeout(1000)

    wait_overlay_done(page)
    page.wait_for_timeout(1200)


def login_sso(page, username: str, password: str) -> None:
    print("[1] Membuka halaman manajemen mitra...")
    page.goto("https://manajemen-mitra.bps.go.id/launcher", wait_until="domcontentloaded")

    login_button = page.locator("button:has-text('Login SSO BPS')")
    try:
        login_button.wait_for(state="visible", timeout=10000)
        print("[2] Menekan tombol Login SSO BPS...")
        login_button.click()
    except PlaywrightTimeoutError:
        print("[2] Tombol login tidak muncul; kemungkinan sesi sudah aktif.")

    try:
        page.wait_for_selector("#username", state="visible", timeout=30000)
    except PlaywrightTimeoutError:
        pass

    if page.locator("#username").is_visible(timeout=1000):
        print("[3] Mengisi username dan password...")
        page.fill("#username", username)
        page.fill("#password", password)

        print("[4] Login...")
        page.click("#kc-login")
    else:
        print("[3] Form SSO tidak muncul; lanjut cek dashboard.")

    print("[5] Menunggu masuk dashboard...")
    page.wait_for_url("**/mitra/dashboard**", timeout=45000)
    print("   [OK] Berhasil masuk dashboard.")


def run(headless: bool, hold_seconds: int) -> None:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config tidak ditemukan: {CONFIG_PATH}")

    config = read_config(CONFIG_PATH)
    username, password = get_login_credentials(config)
    sensus_survei = config.get("Sensus/Survei", "")
    kegiatan = config.get("Kegiatan", "")
    if not sensus_survei or not kegiatan:
        raise ValueError("Config wajib berisi `Sensus/Survei` dan `Kegiatan`.")

    print("Konfigurasi dimuat:")
    print(f"- Username SSO: {username}")
    print(f"- Sensus/Survei: {sensus_survei}")
    print(f"- Kegiatan: {kegiatan}")
    print("- Mode aman: berhenti setelah Kegiatan terpilih, tidak klik Pilih Mitra/Tawarkan.")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        try:
            login_sso(page, username, password)

            print("[6] Masuk ke halaman seleksi...")
            page.goto("https://manajemen-mitra.bps.go.id/mitra/seleksi", wait_until="domcontentloaded")
            page.wait_for_selector("label:has-text('Provinsi')", timeout=30000)

            pilih_dropdown(page, "Provinsi", "KEPULAUAN RIAU")
            pilih_dropdown(page, "Kabupaten/Kota", "KOTA TANJUNG PINANG")
            pilih_dropdown(page, "Sensus/Survei", sensus_survei)
            pilih_dropdown(page, "Kegiatan", kegiatan)

            print("[7] Verifikasi tombol tahap berikutnya tersedia, tanpa diklik...")
            page.locator("button.btn-success.dropdown-toggle:has-text('Pilih Mitra')").wait_for(
                state="visible",
                timeout=30000,
            )

            print("[OK] Sampai tahap pilih kegiatan berhasil.")
            print(f"     Provinsi: {selected_dropdown_text(page, 'Provinsi')}")
            print(f"     Kabupaten/Kota: {selected_dropdown_text(page, 'Kabupaten/Kota')}")
            print(f"     Sensus/Survei: {selected_dropdown_text(page, 'Sensus/Survei')}")
            print(f"     Kegiatan: {selected_dropdown_text(page, 'Kegiatan')}")

            page.screenshot(path=str(SCREENSHOT_PATH), full_page=True)
            print(f"Screenshot tersimpan: {SCREENSHOT_PATH}")

            if hold_seconds > 0:
                print(f"Browser ditahan {hold_seconds} detik untuk review visual...")
                page.wait_for_timeout(hold_seconds * 1000)
        finally:
            context.close()
            browser.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Login dan pilih kegiatan Manajemen Mitra BPS. Berhenti sebelum tahap assign/tawarkan."
    )
    parser.add_argument("--headless", action="store_true", help="Jalankan browser tanpa tampilan.")
    parser.add_argument("--hold-seconds", type=int, default=5, help="Tahan browser setelah sukses.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(headless=args.headless, hold_seconds=args.hold_seconds)
