import argparse
import json
import random
import re
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from pilih_kegiatan_kepka import (
    CONFIG_PATH,
    get_login_credentials,
    read_config,
    login_sso,
    pilih_dropdown,
    selected_dropdown_text,
    wait_overlay_done,
)
import captcha_bypass


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_JSON_PATH = BASE_DIR / "scrap_kepka_rekening.json"
SCREENSHOT_PATH = BASE_DIR / "scrap_kepka_rekening_last_page.png"
DEBUG_SCREENSHOT_PATH = BASE_DIR / "scrap_kepka_rekening_debug.png"


def compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def clean_actions(text: str) -> str:
    pieces = [compact_text(piece) for piece in re.split(r"\n+| {2,}", text or "") if compact_text(piece)]
    result = []
    for piece in pieces:
        if piece not in result:
            result.append(piece)
    return "; ".join(result)


def parse_status(status_text: str) -> tuple[str, str, str, str]:
    text = compact_text(status_text)
    if not text:
        return "", "", "", ""

    status = text
    last_update = ""
    if "Last Update" in text:
        status, last_update = text.split("Last Update", 1)
        status = compact_text(status)
        last_update = compact_text(last_update.lstrip(" :"))

    email = ""
    waktu = ""
    match = re.match(r"(.+?)\s*\((.+)\)$", last_update)
    if match:
        email = match.group(1).strip()
        waktu = match.group(2).strip()

    return status, last_update, email, waktu


def get_page_info(page) -> tuple[int, int]:
    footer = mitra_table_wrap(page).locator("div.footer__navigation__page-info").first
    try:
        footer.wait_for(state="visible", timeout=10000)
        current = int(footer.locator("input.footer__navigation__page-info__current-entry").input_value(timeout=5000))
        text = footer.inner_text(timeout=5000)
        total_match = re.search(r"dari\s+(\d+)", text, re.IGNORECASE)
        if total_match:
            return current, int(total_match.group(1))
    except Exception:
        pass

    text = page.locator("body").inner_text(timeout=10000)
    matches = re.findall(r"halaman\s+(\d+)\s+dari\s+(\d+)", text, re.IGNORECASE)
    if not matches:
        return 1, 1
    current, total = matches[-1]
    return int(current), int(total)


def write_progress(rows: list[dict], meta: dict) -> None:
    payload = {
        "meta": {
            **meta,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "row_count": len(rows),
        },
        "rows": rows,
    }
    OUTPUT_JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_existing_rows() -> list[dict]:
    if not OUTPUT_JSON_PATH.exists():
        return []

    try:
        payload = json.loads(OUTPUT_JSON_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        return []

    cleaned = []
    seen = set()
    for row in rows:
        sobat_id = str(row.get("Sobat-ID", "")).strip()
        nomor_rekening = str(row.get("Nomor Rekening", "")).strip()
        if not sobat_id or not nomor_rekening or sobat_id in seen:
            continue
        cleaned.append(row)
        seen.add(sobat_id)
    return cleaned


def human_pause(page, min_seconds: float, max_seconds: float, reason: str) -> None:
    if max_seconds <= 0:
        return
    min_seconds = max(0, min_seconds)
    max_seconds = max(min_seconds, max_seconds)
    seconds = random.uniform(min_seconds, max_seconds)
    print(f"     [Jeda] {reason}: {seconds:.1f} detik")
    page.wait_for_timeout(int(seconds * 1000))


def mitra_table(page):
    return page.locator(
        "xpath=//table[@id='vgt-table']["
        ".//th//span[normalize-space()='NIK'] and "
        ".//th//span[normalize-space()='Sobat-ID'] and "
        ".//th//span[normalize-space()='Nama'] and "
        ".//th//span[normalize-space()='Aksi']"
        "]"
    ).first


def mitra_table_wrap(page):
    return mitra_table(page).locator("xpath=ancestor::div[contains(@class, 'vgt-inner-wrap')][1]").first


def set_rows_per_page(page, per_page: str = "500") -> None:
    wrap = mitra_table_wrap(page)
    per_page_select = wrap.locator("select.footer__row-count__select[name='perPageSelect']").first
    per_page_select.wait_for(state="visible", timeout=30000)

    current = per_page_select.input_value(timeout=5000)
    if current == per_page:
        print(f"[Table] Tampilan row sudah {per_page}.")
        return

    before_count = visible_rows(page).count()
    print(f"[Table] Mengubah tampilan row menjadi {per_page}...")
    per_page_select.select_option(value=per_page)
    wait_overlay_done(page)

    for _ in range(80):
        page.wait_for_timeout(250)
        current = per_page_select.input_value(timeout=5000)
        row_count = visible_rows(page).count()
        if current == per_page and row_count >= before_count:
            print(f"[Table] Row terlihat setelah set {per_page}: {row_count}")
            return

    print("[Table] Peringatan: belum bisa memastikan semua row tampil, lanjut dengan row yang terlihat.")


def visible_rows(page):
    table = mitra_table(page)
    table.wait_for(state="visible", timeout=30000)
    rows = table.locator("tbody tr")
    rows.first.wait_for(state="visible", timeout=30000)
    return rows


def get_row_data(row) -> dict:
    cells = row.locator("td")
    status, last_update, email, waktu = parse_status(cells.nth(5).inner_text())

    return {
        "No": compact_text(row.locator("th.line-numbers").inner_text()),
        "Nama Bank": "",
        "Nomor Rekening": "",
        "Nomor Rekening Tersensor": "",
        "Nama Pemilik Rekening": "",
        "Sobat-ID": compact_text(cells.nth(1).inner_text()),
        "Nama": compact_text(cells.nth(2).inner_text()),
        "Posisi Daftar": compact_text(cells.nth(3).inner_text()),
        "Posisi Diterima": compact_text(cells.nth(4).inner_text()),
        "Status": status,
        "Last Update": last_update,
        "Last Update Email": email,
        "Last Update Waktu": waktu,
        "Penilaian Kinerja": compact_text(cells.nth(6).inner_text()),
        "Aksi": clean_actions(cells.nth(7).inner_text()),
    }


def find_plaintext_field(modal, label_text: str):
    field = modal.locator(
        f"xpath=.//label[contains(normalize-space(), '{label_text}')]/"
        "following-sibling::div[contains(@class, 'form-control-plaintext')][1]"
    ).first
    if field.count():
        try:
            field.wait_for(state="visible", timeout=5000)
        except PlaywrightTimeoutError:
            pass
        return field
    return None


def field_text(field) -> str:
    if field is None:
        return ""
    try:
        return compact_text(field.inner_text(timeout=8000))
    except Exception:
        return ""


def detail_dialog(page):
    dialog = page.locator("[role='dialog']").filter(has_text="Detail Informasi Mitra").last
    if dialog.count():
        return dialog
    return page.locator("[role='dialog']:visible").last


def wait_no_visible_dialog(page, timeout=10000) -> None:
    page.wait_for_function(
        """
        () => !Array.from(document.querySelectorAll('[role="dialog"].v--modal')).some((el) => {
          const rect = el.getBoundingClientRect();
          const style = window.getComputedStyle(el);
          return style.display !== 'none'
            && style.visibility !== 'hidden'
            && rect.width > 0
            && rect.height > 0;
        })
        """,
        timeout=timeout,
    )


def wait_detail_dialog(page, timeout=7000) -> None:
    page.locator("[role='dialog']").filter(has_text="Detail Informasi Mitra").last.wait_for(
        state="visible",
        timeout=timeout,
    )


def access_limited_visible(page) -> bool:
    try:
        body_text = page.locator("body").inner_text(timeout=100).lower()
    except Exception:
        body_text = ""

    challenge_texts = [
        "akses dibatasi",
        "saya bukan robot",
        "i'm not a robot",
        "checking if the site connection is secure",
        "verify you are human",
    ]
    if any(text in body_text for text in challenge_texts):
        return True

    challenge_selectors = [
        "iframe[src*='captcha']",
        "iframe[src*='recaptcha']",
        "iframe[src*='turnstile']",
        "iframe[title*='captcha']",
        "iframe[title*='challenge']",
    ]
    for selector in challenge_selectors:
        try:
            locator = page.locator(selector)
            for index in range(min(locator.count(), 3)):
                if locator.nth(index).is_visible(timeout=250):
                    return True
        except Exception:
            continue

    return False


def detail_rekening_ready(page) -> bool:
    try:
        modal = detail_dialog(page)
        if modal.locator("#tabs-rekening-btn, a[href='#tabs-rekening']").first.is_visible(timeout=500):
            return True
        modal_text = modal.inner_text(timeout=500)
        return "Nomor Rekening" in modal_text or "Nama Bank" in modal_text
    except Exception:
        return False


def wait_app_ready_after_manual_check(page, timeout=300000) -> str:
    deadline = time.monotonic() + (timeout / 1000)
    while time.monotonic() < deadline:
        if not access_limited_visible(page):
            if detail_rekening_ready(page):
                return "modal rekening"

            try:
                modal = detail_dialog(page)
                if modal.is_visible(timeout=500):
                    modal_text = modal.inner_text(timeout=500)
                    if "Mengambil Data" not in modal_text:
                        return "modal"
            except Exception:
                pass

            try:
                if mitra_table(page).is_visible(timeout=500):
                    return "table"
            except Exception:
                pass

        page.wait_for_timeout(1000)

    page.screenshot(path=str(DEBUG_SCREENSHOT_PATH), full_page=True)
    raise RuntimeError(f"Captcha/Akses Dibatasi belum selesai. Screenshot debug: {DEBUG_SCREENSHOT_PATH}")


def wait_access_limited_if_present(page, tracker=None, timeout=300000) -> str | None:
    try:
        access_box = page.locator("text=Akses Dibatasi").last
        access_box.wait_for(state="visible", timeout=800)
    except Exception:
        if not access_limited_visible(page):
            return None

    print("[MANUAL] Captcha/Akses Dibatasi muncul. Klik 'Saya bukan robot' di browser; script menunggu...")
    if tracker:
        tracker.record_captcha()
    ready_state = wait_app_ready_after_manual_check(page, timeout=timeout)
    page.wait_for_timeout(1500)
    print(f"[OK] Captcha selesai, aplikasi kembali ke {ready_state}.")
    return ready_state


def open_detail_from_row(page, row_index: int, tracker=None) -> None:
    wait_no_visible_dialog(page)

    for attempt in range(1, 4):
        rows = visible_rows(page)
        detail_link = rows.nth(row_index).locator("td").nth(0).locator("[title='Lihat Detail Mitra']").first
        detail_link.evaluate("element => element.scrollIntoView({ block: 'center', inline: 'center' })")
        page.wait_for_timeout(300)

        try:
            captcha_bypass.move_mouse_to_locator(page, detail_link)
            if attempt == 1:
                detail_link.click(timeout=5000)
            elif attempt == 2:
                detail_link.click(force=True, timeout=5000)
            else:
                box = detail_link.bounding_box()
                if not box:
                    raise RuntimeError("Bounding box link detail mitra tidak tersedia.")
                page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

            wait_detail_dialog(page, timeout=6000)
            return
        except Exception:
            ready_state = wait_access_limited_if_present(page, tracker)
            if ready_state and "modal" in ready_state:
                return
            if attempt == 3:
                page.screenshot(path=str(DEBUG_SCREENSHOT_PATH), full_page=True)
                raise
            page.wait_for_timeout(800)


def get_rekening_targets(page):
    wait_detail_dialog(page, timeout=15000)
    modal = detail_dialog(page)

    tab_selectors = [
        "#tabs-rekening-btn",
        "a[href='#tabs-rekening']",
        "a[data-bs-toggle='tab']:has-text('Rekening')",
    ]

    tab_ready = None
    for selector in tab_selectors:
        tab = modal.locator(selector).first
        try:
            tab.wait_for(state="visible", timeout=30000)
            tab_ready = tab
            break
        except PlaywrightTimeoutError:
            continue

    if tab_ready is None:
        page.screenshot(path=str(DEBUG_SCREENSHOT_PATH), full_page=True)
        raise RuntimeError(f"Tab Rekening tidak ditemukan setelah data modal dimuat. Screenshot debug: {DEBUG_SCREENSHOT_PATH}")

    for selector in tab_selectors:
        tab = modal.locator(selector).first
        if tab.count():
            try:
                tab.click(force=True, timeout=5000)
                page.wait_for_timeout(500)
                break
            except Exception:
                continue

    bank_field = find_plaintext_field(modal, "Nama Bank")
    rekening_field = find_plaintext_field(modal, "Nomor Rekening")
    owner_field = find_plaintext_field(modal, "Nama Pemilik Rekening")

    if rekening_field is None:
        page.screenshot(path=str(DEBUG_SCREENSHOT_PATH), full_page=True)
        raise RuntimeError(f"Field Nomor Rekening tidak ditemukan. Screenshot debug: {DEBUG_SCREENSHOT_PATH}")
    try:
        rekening_field.wait_for(state="visible", timeout=10000)
    except PlaywrightTimeoutError:
        page.screenshot(path=str(DEBUG_SCREENSHOT_PATH), full_page=True)
        raise RuntimeError(f"Field Nomor Rekening belum terlihat setelah tab Rekening diklik. Screenshot debug: {DEBUG_SCREENSHOT_PATH}")

    return modal, bank_field, rekening_field, owner_field


def read_rekening_from_target(target) -> str | None:
    text = field_text(target)
    if not text or "*" in text:
        return None

    digits = re.sub(r"\D", "", text)
    if 5 <= len(digits) <= 30:
        return digits
    return None


def click_rekening_eye(modal, target, page) -> bool:
    eye_button = target.locator("button:has(i.fa-eye)").first
    if eye_button.count() == 0:
        group = modal.locator(
            "xpath=.//label[contains(normalize-space(), 'Nomor Rekening')]/"
            "ancestor::div[contains(@class, 'form-group')][1]"
        ).first
        eye_button = group.locator("button:has(i.fa-eye)").first
    if eye_button.count() == 0:
        eye_button = modal.locator("button:has(i.fa-eye)").first

    try:
        eye_button.wait_for(state="visible", timeout=10000)
        captcha_bypass.move_mouse_to_locator(page, eye_button)
        eye_button.click(force=True)
        return True
    except PlaywrightTimeoutError:
        return False


def reveal_rekening_from_modal(page, tracker=None) -> dict:
    try:
        wait_detail_dialog(page, timeout=15000)
    except PlaywrightTimeoutError:
        page.screenshot(path=str(DEBUG_SCREENSHOT_PATH), full_page=True)
        modal_count = page.locator(".modal").count()
        dialog_count = page.locator("[role='dialog']").count()
        raise RuntimeError(
            f"Modal detail tidak muncul. Screenshot debug: {DEBUG_SCREENSHOT_PATH}. "
            f"Jumlah .modal={modal_count}, role=dialog={dialog_count}"
        )

    if wait_access_limited_if_present(page, tracker):
        raise RuntimeError("Captcha selesai; ulang buka detail agar state modal rekening bersih.")
    modal, bank_field, target, owner_field = get_rekening_targets(page)

    bank_name = field_text(bank_field)
    owner_name = field_text(owner_field)
    masked_rekening = field_text(target)

    try:
        visible_rekening = read_rekening_from_target(target)
        if visible_rekening:
            return {
                "Nama Bank": bank_name,
                "Nomor Rekening": visible_rekening,
                "Nomor Rekening Tersensor": masked_rekening,
                "Nama Pemilik Rekening": owner_name,
            }
    except Exception:
        modal, bank_field, target, owner_field = get_rekening_targets(page)

    if not click_rekening_eye(modal, target, page):
        page.screenshot(path=str(DEBUG_SCREENSHOT_PATH), full_page=True)
        raise RuntimeError(f"Tombol mata Nomor Rekening tidak ditemukan. Screenshot debug: {DEBUG_SCREENSHOT_PATH}")

    reclick_after_captcha = False

    for _ in range(240):
        page.wait_for_timeout(250)
        if wait_access_limited_if_present(page, tracker):
            raise RuntimeError("Captcha selesai; ulang buka detail agar state modal rekening bersih.")

        try:
            visible_rekening = read_rekening_from_target(target)
            if visible_rekening:
                return {
                    "Nama Bank": bank_name,
                    "Nomor Rekening": visible_rekening,
                    "Nomor Rekening Tersensor": masked_rekening,
                    "Nama Pemilik Rekening": owner_name,
                }
        except Exception:
            modal, bank_field, target, owner_field = get_rekening_targets(page)
            bank_name = field_text(bank_field)
            owner_name = field_text(owner_field)
            continue

        if not reclick_after_captcha:
            reclick_after_captcha = click_rekening_eye(modal, target, page)

    page.screenshot(path=str(DEBUG_SCREENSHOT_PATH), full_page=True)
    raise RuntimeError("Nomor rekening penuh tidak ditemukan setelah tombol mata diklik.")


def close_modal(page) -> None:
    modal = detail_dialog(page)
    close_selectors = [
        "button.btn-close",
        "button.close",
        "button:has-text('Tutup')",
        "button:has-text('Close')",
    ]

    for selector in close_selectors:
        button = modal.locator(selector).first
        if button.count() and button.is_visible(timeout=1000):
            captcha_bypass.move_mouse_to_locator(page, button)
            button.click()
            break
    else:
        page.keyboard.press("Escape")

    try:
        modal.wait_for(state="hidden", timeout=5000)
    except PlaywrightTimeoutError:
        page.keyboard.press("Escape")
        try:
            modal.wait_for(state="hidden", timeout=5000)
        except PlaywrightTimeoutError:
            page.mouse.click(20, 120)
            modal.wait_for(state="hidden", timeout=10000)

    wait_no_visible_dialog(page)
    page.wait_for_timeout(400)


def scrape_current_page(
    page,
    page_no: int,
    rows_out: list[dict],
    meta: dict,
    max_rows: int | None,
    tracker,
    pause_every: int,
    pause_seconds: float,
) -> bool:
    rows = visible_rows(page)
    row_count = rows.count()
    print(f"[Scrape] Halaman {page_no}: {row_count} row terlihat.")

    for index in range(row_count):
        if max_rows is not None and len(rows_out) >= max_rows:
            return False

        rows = visible_rows(page)
        row = rows.nth(index)
        data = get_row_data(row)
        existing_ids = {str(row.get("Sobat-ID", "")).strip() for row in rows_out if row.get("Nomor Rekening")}
        if data["Sobat-ID"] in existing_ids:
            print(f"  -> Skip halaman {page_no}, row {index + 1}, Sobat-ID {data['Sobat-ID']} (sudah ada di JSON).")
            continue

        label = f"halaman {page_no}, row {index + 1}, Sobat-ID {data['Sobat-ID']}"
        print(f"  -> Buka detail {label}")

        last_error = None
        for detail_attempt in range(1, 4):
            try:
                tracker.sleep(page, "sebelum buka detail")
                captcha_bypass.random_scroll(page)
                open_detail_from_row(page, index, tracker)
                data.update(reveal_rekening_from_modal(page, tracker))
                close_modal(page)
                last_error = None
                break
            except Exception as error:
                last_error = error
                wait_access_limited_if_present(page, tracker)

                try:
                    close_modal(page)
                except Exception:
                    pass

                if detail_attempt >= 3:
                    raise

                print(
                    f"     [Retry] Detail rekening belum kebaca untuk {data['Sobat-ID']} "
                    f"(percobaan {detail_attempt}/3): {type(error).__name__}: {error}"
                )
                page.wait_for_timeout(1500)

        if last_error is not None:
            raise last_error

        rows_out.append(data)
        write_progress(rows_out, meta)
        tracker.record_success()
        print(f"     [OK] Rekening tersimpan untuk {data['Nama']} ({data['Sobat-ID']}) - {data['Nama Bank']}.")
        tracker.sleep(page, "setelah tutup detail")

        if pause_every > 0 and len(rows_out) % pause_every == 0:
            print(f"     [Istirahat] Sudah scrape {len(rows_out)} row. Pause {pause_seconds:.0f} detik.")
            page.wait_for_timeout(int(max(0, pause_seconds) * 1000))

    return True


def click_next_page(page, current_page: int, tracker) -> None:
    tracker.sleep(page, "sebelum pindah halaman")
    captcha_bypass.random_scroll(page)
    next_button = mitra_table_wrap(page).locator("button:has-text('Selanjutnya'), button:has-text('Setelah')").last
    captcha_bypass.move_mouse_to_locator(page, next_button)
    next_button.click(force=True)
    wait_overlay_done(page)

    for _ in range(40):
        page.wait_for_timeout(250)
        new_page, _ = get_page_info(page)
        if new_page > current_page:
            return

    raise RuntimeError("Gagal pindah ke halaman berikutnya.")


def prepare_selection(page, context, username: str, password: str, sensus_survei: str, kegiatan: str) -> dict:
    captcha_bypass.login_sso_with_storage(page, context, username, password)

    print("[6] Masuk ke halaman seleksi...")
    page.goto("https://manajemen-mitra.bps.go.id/mitra/seleksi", wait_until="domcontentloaded")
    page.wait_for_selector("label:has-text('Provinsi')", timeout=30000)

    pilih_dropdown(page, "Provinsi", "KEPULAUAN RIAU")
    pilih_dropdown(page, "Kabupaten/Kota", "KOTA TANJUNG PINANG")
    pilih_dropdown(page, "Sensus/Survei", sensus_survei)
    pilih_dropdown(page, "Kegiatan", kegiatan)

    mitra_table(page).wait_for(state="visible", timeout=30000)
    page.wait_for_timeout(1000)
    set_rows_per_page(page, "500")

    return {
        "Provinsi": selected_dropdown_text(page, "Provinsi"),
        "Kabupaten/Kota": selected_dropdown_text(page, "Kabupaten/Kota"),
        "Sensus/Survei": selected_dropdown_text(page, "Sensus/Survei"),
        "Kegiatan": selected_dropdown_text(page, "Kegiatan"),
    }


def run(
    headless: bool,
    hold_seconds: int,
    max_pages: int | None,
    max_rows: int | None,
    delay_min: float,
    delay_max: float,
    pause_every: int,
    pause_seconds: float,
    resume: bool,
) -> None:
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
    print("- Mode baca: scrape tabel dan modal Rekening, tidak klik Pilih Mitra/Tawarkan/Assign.")

    rows_out: list[dict] = load_existing_rows() if resume else []
    if rows_out:
        print(f"[Resume] Ditemukan {len(rows_out)} row valid di JSON lama; akan skip yang sudah ada.")

    tracker = captcha_bypass.AdaptiveDelayTracker(delay_min, delay_max)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        
        context_options = {
            "viewport": {"width": 1440, "height": 900},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        
        if captcha_bypass.SESSION_STATE_PATH.exists():
            print(f"[Restore] Menggunakan file sesi dari {captcha_bypass.SESSION_STATE_PATH}")
            context_options["storage_state"] = str(captcha_bypass.SESSION_STATE_PATH)
            
        context = browser.new_context(**context_options)
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        try:
            selection = prepare_selection(page, context, username, password, sensus_survei, kegiatan)
            current_page, total_pages = get_page_info(page)
            pages_to_scrape = total_pages if max_pages is None else min(total_pages, max_pages)
            meta = {
                **selection,
                "total_pages_detected": total_pages,
                "scrape_scope_pages": pages_to_scrape,
            }
            write_progress(rows_out, meta)

            try:
                while current_page <= pages_to_scrape:
                    should_continue = scrape_current_page(
                        page,
                        current_page,
                        rows_out,
                        meta,
                        max_rows,
                        tracker,
                        pause_every,
                        pause_seconds,
                    )
                    if not should_continue:
                        break

                    if current_page >= pages_to_scrape:
                        break

                    click_next_page(page, current_page, tracker)
                    current_page, total_pages = get_page_info(page)
            except Exception as error:
                write_progress(rows_out, {**meta, "total_pages_detected": total_pages})
                print("\n[TERHENTI] Browser/halaman tertutup atau elemen berubah saat proses.")
                print(f"          Progress aman tersimpan: {len(rows_out)} row.")
                print("          Jalankan run_scrape_kepka_rekening.cmd lagi untuk lanjut dari row berikutnya.")
                print(f"          Detail singkat: {type(error).__name__}: {error}")
                return

            page.screenshot(path=str(SCREENSHOT_PATH), full_page=True)
            write_progress(rows_out, {**meta, "total_pages_detected": total_pages})
            print(f"[SELESAI] Total row tersimpan: {len(rows_out)}")
            print(f"JSON tersimpan: {OUTPUT_JSON_PATH}")
            print(f"Screenshot akhir tersimpan: {SCREENSHOT_PATH}")

            if hold_seconds > 0:
                print(f"Browser ditahan {hold_seconds} detik untuk review visual...")
                page.wait_for_timeout(hold_seconds * 1000)
        finally:
            context.close()
            browser.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape tabel KEPKA SE26 dengan bank dan nomor rekening dari modal detail. Tidak melakukan assign/tawarkan."
    )
    parser.add_argument("--headless", action="store_true", help="Jalankan browser tanpa tampilan.")
    parser.add_argument("--hold-seconds", type=int, default=0, help="Tahan browser setelah selesai.")
    parser.add_argument("--max-pages", type=int, default=None, help="Batasi jumlah halaman untuk test.")
    parser.add_argument("--max-rows", type=int, default=None, help="Batasi jumlah row untuk test.")
    parser.add_argument("--delay-min", type=float, default=0.0, help="Jeda minimum antar aksi row.")
    parser.add_argument("--delay-max", type=float, default=0.0, help="Jeda maksimum antar aksi row.")
    parser.add_argument("--pause-every", type=int, default=0, help="Istirahat setiap N row sukses. 0 = tidak ada.")
    parser.add_argument("--pause-seconds", type=float, default=10.0, help="Durasi istirahat periodik.")
    parser.add_argument("--resume", action="store_true", help="Lanjut dari JSON lama dan skip Sobat-ID yang sudah tersimpan.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(
        headless=args.headless,
        hold_seconds=args.hold_seconds,
        max_pages=args.max_pages,
        max_rows=args.max_rows,
        delay_min=args.delay_min,
        delay_max=args.delay_max,
        pause_every=args.pause_every,
        pause_seconds=args.pause_seconds,
        resume=args.resume,
    )
