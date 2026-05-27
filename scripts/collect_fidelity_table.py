from __future__ import annotations
import csv
import time
import re
import subprocess
import shutil
import socket
from pathlib import Path
from datetime import datetime, time as dt_time, timedelta
from zoneinfo import ZoneInfo
from dataclasses import dataclass
from playwright.sync_api import sync_playwright, Page

@dataclass
class SweepStats:
    added: int = 0
    duplicates: int = 0
    failed_switches: int = 0
    missing_bars: int = 0
    invalid_bars: int = 0
    skipped_symbol_mismatch: int = 0

EDGE_DEBUG_PORT = 9222
EDGE_DEBUG_URL = f"http://localhost:{EDGE_DEBUG_PORT}"
EDGE_USER_DATA_DIR = Path.home() / "edge_debug_profile"
EDGE_PATHS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",]

SYMBOLS = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "TSLA", "SPY", "WMT", "GME", "MGNI"]
INTERVAL = "5min"
MARKET_TZ = ZoneInfo("America/New_York")
COLLECTION_START = dt_time(9, 30)
COLLECTION_END = dt_time(16, 10)

BAR_MINUTES = 5
BAR_DELAY_SECONDS = 15
OUT_OF_HOURS_SLEEP_SECONDS = 300
RESTART_EVERY_N_SWEEPS = 3
RAW_LIVE_DIR = Path("data/raw/live")
FIDELITY_URL = "https://digital.fidelity.com/ftgw/digital/traderplus"
FIDELITY_TS_PATTERN = re.compile(r"^\d{2}/\d{2}/\d{4}\s+\d{1,2}:\d{2}\s+(AM|PM)$")

CPP_EXE = Path("cpp/build/Debug/normalize_data.exe")
LIVE_RAW_DIR = Path("data/raw/live")
PROCESSED_DIR = Path("data/processed")
LIVE_ARCHIVE_DIR = Path("data/raw/archive")

LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

def is_port_open(host: str = "127.0.0.1", port: int = EDGE_DEBUG_PORT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False
    
def find_edge_executable() -> str | None:
    for path in EDGE_PATHS:
        if Path(path).exists():
            return path
    return None

def start_edge_debug():
    if is_port_open():
        log("Edge debug session already running.")
        return None
    
    edge_path = find_edge_executable()

    if edge_path is None:
        log("Could not find Microsoft Edge executable.")
        return None
    
    EDGE_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    cmd = [edge_path, f"--remote-debugging-port={EDGE_DEBUG_PORT}", f"--user-data-dir={EDGE_USER_DATA_DIR}", f"--new-window", FIDELITY_URL]

    log("Starting Edge debug session...")
    edge_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for _ in range(20):
        if is_port_open():
            log("Edge debug session started.")
            return edge_process
        time.sleep(1)

    log("Edge debug session did not start in time.")
    
    try:
        edge_process.terminate()
    except Exception:
        pass

    return None

def connect_and_prepare_page(p):
    edge_process = start_edge_debug()

    if not is_port_open():
        log("Edge debug port is not open. Cannot connect.")
        return None, None, None
    
    try:
        browser = p.chromium.connect_over_cdp(EDGE_DEBUG_URL)
    except Exception as e:
        log(f"Could not connect to Edge debug session: {e}")
        return None, None, edge_process
    
    page = ensure_fidelity_page(browser)

    if page is None:
        log("Could not create or find Fidelity page.")
        return browser, None, edge_process
    
    wait_for_trader_ready(page)

    close_extra_pages(browser, page)

    return browser, page, edge_process

def ensure_fidelity_page(browser):
    page = get_fidelity_page(browser)

    if page is not None:
        log(f"Using existing Fidelity page: {page.url}")
        return page
    
    log("No Fidelity page found. Opening Fidelity Trader+.")

    context = browser.contexts[0] if browser.contexts else browser.new_context()
    page = context.new_page()
    page.goto(FIDELITY_URL, wait_until="domcontentloaded", timeout=60000)
    return page

def trader_page_ready(page: Page) -> bool:
    try:
        body = page.locator("body").inner_text(timeout=5000).lower()
        return ("trading dashboard" in body or "symbol search box" in body or "positions" in body)
    except Exception:
        return False
    
def wait_for_trader_ready(page: Page) -> bool:
    log("Waiting for Fidelity Trader+ to become ready...")
    login_click_attempts = 0
    max_login_click_attempts = 3

    while True:
        if trader_page_ready(page):
            log(f"Fidelity Trader+ is ready.")
            return True
        
        if login_click_attempts < max_login_click_attempts:
            if try_click_login_button(page):
                login_click_attempts += 1
        else:
            log("Login button was clicked several times. Waiting for manual login if needed.")
        time.sleep(15)

def try_click_login_button(page: Page) -> bool:
    possible_buttons = [
        page.get_by_role("button", name="Log in"),
        page.get_by_role("button", name="Login"),
        page.get_by_role("button", name="Continue"),
        page.locator('button:has-text("Log in")').first,
        page.locator('button:has-text("Login")').first,
        page.locator('button:has-text("Continue")').first,
    ]

    for button in possible_buttons:
        try:
            if button.count() == 0:
                continue

            button.wait_for(state="visible", timeout=1500)
            button.click(force=True)
            log("Clicked login/continue button.")
            page.wait_for_timeout(5000)
            return True
        
        except Exception:
            continue
    
    return False

def restart_edge_debug(p, browser, edge_process):
    log("Restarting Edge debug session to control memory usage...")

    stop_edge_debug(browser, edge_process)

    browser, page, edge_process = connect_and_prepare_page(p)

    if browser is None or page is None:
        log("Failed to restart Edge debug session.")
        return None, None, edge_process
    
    log("Edge debug session restarted successfully.")
    return browser, page, edge_process
    
def stop_edge_debug(browser, edge_process) -> None:
    log("Stopping Edge debug session...")

    try:
        if browser is not None:
            browser.close()
    except Exception as e:
        log(f"Browser close failed: {e}")

    if edge_process is not None:
        try:
            subprocess.run(["taskkill", "/PID", str(edge_process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,)
            log("Requested termination of Edge process tree.")
        except Exception as e:
            log(f"taskkill process-tree terminate failed: {e}")
        
        try:
            edge_process.wait(timeout=5)
        except Exception:
            pass
    
    kill_edge_debug_profile()
    
    time.sleep(5)

def kill_edge_debug_profile() -> None:
    profile = str(EDGE_USER_DATA_DIR)

    ps_command = (
        "Get-CimInstance Win32_Process "
        "-Filter \"name = 'msedge.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{profile}*' }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    )

    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,)
        log("Requested terminated of Edge debug-profile processes.")
    except Exception as e:
        log(f"Failed to terminate Edge debug profile processes: {e}")

def close_extra_pages(browser, keep_page) -> None:
    closed = 0

    for context in browser.contexts:
        for page in list(context.pages):
            if page == keep_page:
                continue

            try:
                page.close()
                closed += 1
            except Exception as e:
                log(f"Failed to close extra page: {e}")
    
    if closed > 0:
        log(f"Closed {closed} extra browser page(s).")

def now_market_time() -> datetime:
    return datetime.now(MARKET_TZ)

def is_weekday(dt: datetime) -> bool:
    return dt.weekday() < 5

def is_collection_time() -> bool:
    now = now_market_time()

    if not is_weekday(now):
        return False
    
    return COLLECTION_START <= now.time() <= COLLECTION_END

def next_trading_day_start(now: datetime) -> datetime:
    candidate = now.replace(hour=COLLECTION_START.hour, minute=COLLECTION_START.minute, second=0, microsecond=0,)

    if now >= candidate:
        candidate += timedelta(days=1)

    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    
    return candidate

def sleep_until_next_trading_day() -> None:
    now = now_market_time()
    start = next_trading_day_start(now)
    seconds = max(0.0, (start - now).total_seconds())

    log(f"Market closed. Collector idle until {start:%Y-%m-%d %H:%M:%S %Z}.")

    time.sleep(seconds)

def is_after_market_hours() -> bool:
    now = now_market_time()

    if now.weekday() >= 5:
        return True
    
    return now.time() > COLLECTION_END

def clean_number(value: str) -> str:
    return value.replace(",", "").strip()

def output_path(symbol: str) -> Path:
    RAW_LIVE_DIR.mkdir(parents=True, exist_ok=True)
    return RAW_LIVE_DIR / f"{symbol}_{INTERVAL}_live.csv"

def ensure_csv_header(path: Path) -> None:
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Date", "Open", "High", "Low", "Close", "Volume"])

def load_seen_timestamps(path: Path) -> set[str]:
    if not path.exists():
        return set()

    seen: set[str] = set()

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        if reader.fieldnames is None or "Date" not in reader.fieldnames:
            log(f"WARNING: {path} missing Date header. Ignoring existing timestamps.")
            return seen
        
        for row in reader:
            ts = row.get("Date")
            if ts:
                seen.add(ts)

    return seen

def append_bar(path: Path, bar: dict[str, str]) -> None:
    ensure_csv_header(path)

    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            bar["Date"],
            bar["Open"],
            bar["High"],
            bar["Low"],
            bar["Close"],
            bar["Volume"],
        ])

def looks_like_fidelity_timestamp(value: str) -> bool:
    return bool(FIDELITY_TS_PATTERN.match(value.strip()))

def normalize_fidelity_timestamp(ts: str) -> str | None:
    ts = ts.strip()

    if not looks_like_fidelity_timestamp(ts):
        return None

    try:
        dt_local = datetime.strptime(ts, "%m/%d/%Y %I:%M %p")
    except ValueError:
        return None

    dt_local = dt_local.replace(tzinfo=MARKET_TZ)
    dt_utc = dt_local.astimezone(ZoneInfo("UTC"))

    return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

def get_fidelity_page(browser):
    for context in browser.contexts:
        for candidate in context.pages:
            try:
                url = candidate.url.lower()

                try:
                    title = candidate.title().lower()
                except Exception:
                    title = ""

                try:
                    body = candidate.locator("body").inner_text(timeout=3000).lower()
                except Exception:
                    body = ""

                looks_like_fidelity = (
                    "fidelity.com" in url
                    or "traderplus" in url
                    or "fidelity" in title
                    or "trader+" in body
                    or "trading dashboard" in body
                    or "symbol search box" in body
                )

                if looks_like_fidelity:
                    return candidate

            except Exception as e:
                log(f"Skipping page during Fidelity lookup: {e}")
                continue

    return None

def page_is_healthy(page: Page) -> bool:
    try:
        page.locator("body").inner_text(timeout=5000)
        return True
    except Exception:
        return False
    
def find_chart_table(page: Page):
    tables = page.locator("table")

    for i in range(tables.count()):
        table = tables.nth(i)
        text = table.inner_text(timeout=5000)

        if (
            "Date" in text
            and "Open" in text
            and "High" in text
            and "Low" in text
            and "Close" in text
            and "Volume" in text
        ):
            return table

    return None

def extract_ohlcv_rows(parts: list[str], data_start: int) -> list[list[str]]:
    rows: list[list[str]] = []

    # Find every location where a new row starts.
    timestamp_indexes = []

    for i in range(data_start, len(parts)):
        if looks_like_fidelity_timestamp(parts[i]):
            timestamp_indexes.append(i)

    for idx, start in enumerate(timestamp_indexes):
        end = timestamp_indexes[idx + 1] if idx + 1 < len(timestamp_indexes) else len(parts)
        row = parts[start:end]

        # Expected possibilities:
        # 8 fields: Date, O, H, L, C, %Change, %ChangeVsAvg, Volume
        # 7 fields: Date, O, H, L, C, %Change, Volume
        if len(row) >= 7:
            rows.append(row)

    return rows

def read_recent_bars(page: Page) -> list[dict[str, str]]:
    if not ensure_table_view(page):
        return []

    table = wait_for_chart_table(page, timeout_seconds=10)

    if table is None:
        log("DEBUG: Chart table not found after waiting.")
        return []

    text = table.inner_text(timeout=5000)
    parts = [part.strip() for part in text.splitlines() if part.strip()]

    expected_header = [
        "Date",
        "Open",
        "High",
        "Low",
        "Close",
        "% Change",
        "% Change vs Average",
        "Volume",
    ]

    if len(parts) < 16:
        log(f"DEBUG: Not enough table parts. parts={len(parts)}")
        log(f"DEBUG table parts sample: {parts[:30]}")
        return []

    header_start = -1

    for i in range(len(parts) - len(expected_header) + 1):
        if parts[i:i + len(expected_header)] == expected_header:
            header_start = i
            break

    if header_start == -1:
        log("DEBUG: Could not find chart header in table text.")
        log(f"DEBUG table parts sample: {parts[:40]}")
        return []

    data_start = header_start + len(expected_header)

    rows = extract_ohlcv_rows(parts, data_start)

    if not rows:
        log("DEBUG: No valid OHLCV rows found.")
        log(f"DEBUG table parts sample: {parts[data_start:data_start + 40]}")
        return []

    bars: list[dict[str, str]] = []

    for row in rows:
        if len(row) < 7:
            continue

        normalized_date = normalize_fidelity_timestamp(row[0])

        if normalized_date is None:
            continue

        bar = {
            "Date": normalized_date,
            "Open": clean_number(row[1]),
            "High": clean_number(row[2]),
            "Low": clean_number(row[3]),
            "Close": clean_number(row[4]),
            "Volume": clean_number(row[-1]),
        }

        bars.append(bar)

    return bars

def is_valid_bar(bar: dict[str, str]) -> bool:
    required = ["Date", "Open", "High", "Low", "Close", "Volume"]

    for field in required:
        if field not in bar or bar[field] == "":
            return False

    try:
        open_price = float(bar["Open"])
        high_price = float(bar["High"])
        low_price = float(bar["Low"])
        close_price = float(bar["Close"])
        volume = int(bar["Volume"])
    except ValueError:
        return False

    if open_price <= 0 or high_price <= 0 or low_price <= 0 or close_price <= 0:
        return False

    if volume < 0:
        return False

    if high_price < low_price:
        return False

    if not (low_price <= open_price <= high_price):
        return False

    if not (low_price <= close_price <= high_price):
        return False

    return True

def bar_is_today(bar: dict[str, str]) -> bool:
    ts = bar["Date"]

    try:
        dt_utc = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        log(f"Invalid timestamp while checking for bar date: {ts}")
        return False
    
    dt_market = dt_utc.astimezone(MARKET_TZ)
    today_market = now_market_time().date()

    return dt_market.date() == today_market

def page_matches_symbol(page: Page, symbol: str) -> bool:
    try:
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return False

    return symbol in body

def collect_symbol(page: Page, symbol: str, seen: set[str]) -> str:
    path = output_path(symbol)
    ensure_csv_header(path)
    seen.update(load_seen_timestamps(path))

    if not page_matches_symbol(page, symbol):
        log(f"[{symbol}] Page symbol mismatch. Skipping collection.")
        return "symbol_mismatch"

    recent_bars = read_recent_bars(page)

    if not recent_bars:
        log(f"[{symbol}] No completed bar found.")
        return "missing"

    missing_bars: list[dict[str,str]] = []

    for bar in recent_bars:
        ts = bar["Date"]

        if not bar_is_today(bar):
            break

        if ts in seen:
            break

        if not is_valid_bar(bar):
            log(f"[{symbol}] Invalid bar while catching up, skipping: {bar}")
            continue

        missing_bars.append(bar)

    if not missing_bars:
        latest_ts = recent_bars[0]["Date"]
        log(f"[{symbol}] Already seen through {latest_ts}")
        return "duplicate"
    
    missing_bars.reverse()

    for bar in missing_bars:
        ts = bar["Date"]

        append_bar(path, bar)
        seen.add(ts)
        log(f"[{symbol}] Added {ts} O={bar['Open']} H={bar['High']} L={bar['Low']} C={bar['Close']} V={bar['Volume']}")

    if len(missing_bars) > 1:
        log(f"[{symbol}] Caught up {len(missing_bars)} missing bars.")

    return "added"

def switch_symbol(page: Page, symbol: str) -> bool:
    selector = 'input[aria-label="symbol search box"]'

    try:
        symbol_input = page.locator(selector).first
        symbol_input.wait_for(state="visible", timeout=5000)

        # Avoid normal click because Fidelity's cover element intercepts it.
        symbol_input.focus()
        page.keyboard.press("Control+A")
        page.keyboard.type(symbol)
        page.keyboard.press("Enter")

        return wait_for_symbol_update(page, symbol)

    except Exception as e:
        log(f"[{symbol}] Failed to switch symbol: {e}")
        return False

def wait_for_symbol_update(page: Page, symbol: str) -> bool:
    page.wait_for_timeout(1000)

    body = page.locator("body").inner_text(timeout=5000)

    if symbol not in body:
        log(f"[{symbol}] Symbol switch failed: symbol not found in page body.")
        return False

    if not ensure_table_view(page):
        log(f"[{symbol}] Symbol switch failed: could not enable table view.")
        return False

    table = wait_for_chart_table(page, timeout_seconds=10)

    if table is None:
        log(f"[{symbol}] Symbol switch failed: chart table not ready.")
        return False

    return True

def ensure_table_view(page: Page) -> bool:
    # If the chart table is already visible, no need to click anything.
    if find_chart_table(page) is not None:
        return True

    table_buttons = [
        page.get_by_role("button", name="Table"),
        page.get_by_role("button", name="Table View"),
        page.locator('button[aria-label*="Table"]').first,
        page.locator('button:has-text("Table")').first,
    ]

    for button in table_buttons:
        try:
            if button.count() == 0:
                continue

            button.wait_for(state="visible", timeout=2000)
            button.click(force=True)
            page.wait_for_timeout(1000)

            if find_chart_table(page) is not None:
                return True

        except Exception:
            continue

    log("DEBUG: Could not switch to table view.")
    return False

def wait_for_chart_table(page: Page, timeout_seconds: int = 10):
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        table = find_chart_table(page)

        if table is not None:
            return table

        page.wait_for_timeout(500)

    return None

def time_until_next_bar_run(now: datetime) -> float:
    minute = now.minute
    second = now.second
    microsecond = now.microsecond

    minutes_past = minute % BAR_MINUTES
    minutes_until_next = BAR_MINUTES - minutes_past

    if minutes_past == 0 and second < BAR_DELAY_SECONDS:
        next_run = now.replace(second=BAR_DELAY_SECONDS, microsecond=0)
        return max(0.0, (next_run - now).total_seconds())
    
    next_run = now.replace(second=BAR_DELAY_SECONDS, microsecond=0)
    next_run += timedelta(minutes=minutes_until_next)

    return max(0.0, (next_run - now).total_seconds())

def sleep_until_next_bar_run() -> None:
    now = now_market_time()

    if now.time() > COLLECTION_END or now.weekday() >= 5:
        return

    seconds = time_until_next_bar_run(now)
    next_run = now + timedelta(seconds=seconds)
    log(f"Next collection sweep scheduled for {next_run:%Y-%m-%d %H:%M:%S %Z}")
    time.sleep(seconds)

def run_cpp_command(args: list[str]) -> bool:
    if not CPP_EXE.exists():
        log(f"C++ executable not found: {CPP_EXE}")
        return False
    
    cmd = [str(CPP_EXE)] + args

    log(f"Running C++ command: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300,)

        if result.stdout:
            log(result.stdout.strip())

        if result.stderr:
            log(f"C++ stderr: {result.stderr.strip()}")
        
        if result.returncode != 0:
            log(f"C++ command failed with return code {result.returncode}")
            return False

        return True
    
    except Exception as e:
        log(f"Failed to run C++ command: {e}")
        return False
    
def archive_live_files() -> None:
    today = now_market_time().strftime("%Y-%m-%d")
    archive_dir = LIVE_ARCHIVE_DIR / today
    archive_dir.mkdir(parents=True, exist_ok=True)

    moved = 0

    for path in LIVE_RAW_DIR.glob("*.csv"):
        destination = archive_dir / path.name

        try:
            shutil.move(str(path), str(destination))
            moved += 1
        except Exception as e:
            log(f"Failed to archive {path}: {e}")
    
    log(f"Archived {moved} live files(s) to {archive_dir}")
    
def run_end_of_day_processing() -> bool:
    log("Starting end-of-day live data processing...")

    merge_ok = run_cpp_command(["--merge", str(LIVE_RAW_DIR), str(PROCESSED_DIR),])

    if not merge_ok:
        log("End-of-day merge failed. Live files were not archived.")
        return False
    
    validate_ok = run_cpp_command(["--validate", str(PROCESSED_DIR)])

    if not validate_ok:
        log("Post-merge validation failed. Live files were not archived.")
        return False
    
    log("End-of-day merge and validation succeeded.")
    archive_live_files()
    return True

def log(message: str) -> None:
    now = datetime.now()
    line = f"[{now:%Y-%m-%d %H:%M:%S}] {message}"
    log_path = LOG_DIR / f"collector_{now:%Y-%m-%d}.log"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

def main() -> None:
    log("Starting Fidelity table collector...")

    with sync_playwright() as p:
        browser = None
        page = None
        edge_process = None
        sweep_count = 0
        consecutive_bad_sweeps = 0
        seen_by_symbol: dict[str, set[str]] = {}
        last_eod_processing_date: str | None = None

        for symbol in SYMBOLS:
            path = output_path(symbol)
            ensure_csv_header(path)
            seen_by_symbol[symbol] = load_seen_timestamps(path)
            
        try:
            while True:
                if not is_collection_time():
                    now = now_market_time()
                    today = now.strftime("%Y-%m-%d")

                    if browser is not None or edge_process is not None:
                        log("Collection window closed. Stopping Edge to save resources.")
                        stop_edge_debug(browser, edge_process)
                        browser = None
                        page = None
                        edge_process = None
                    
                    if now.time() > COLLECTION_END and last_eod_processing_date != today:
                        if run_end_of_day_processing():
                            last_eod_processing_date = today
                        else:
                            log("End-of-day processing failed. WIll retry on next inactive loop.")
                            time.sleep(300)
                            continue
                    
                    sleep_until_next_trading_day()
                    continue

                if browser is None or page is None:
                    log("Collection window active. Starting Edge/Fidelity.")
                    browser, page, edge_process = connect_and_prepare_page(p)

                    if browser is None or page is None:
                        log("Could not prepare Edge/Fidelity. Wating 60 seconds.")
                        time.sleep(60)
                        continue

                    sweep_count = 0
                    consecutive_bad_sweeps = 0
                
                stats = SweepStats()

                for symbol in SYMBOLS:
                    if not switch_symbol(page, symbol):
                        stats.failed_switches += 1
                        continue

                    if not ensure_table_view(page):
                        log(f"[{symbol}] Could not open table view, skipping.")
                        stats.missing_bars += 1
                        continue
                        
                    try:
                        result = collect_symbol(page, symbol, seen_by_symbol[symbol])
                    except Exception as e:
                        log(f"[{symbol}] Unexpected collection error: {e}")
                        stats.missing_bars += 1
                        continue

                    if result == "added":
                        stats.added += 1
                    elif result == "duplicate":
                        stats.duplicates += 1
                    elif result == "missing":
                        stats.missing_bars += 1
                    elif result == "invalid":
                        stats.invalid_bars += 1
                    elif result == "symbol_mismatch":
                        stats.skipped_symbol_mismatch += 1

                    page.wait_for_timeout(1000)

                sweep_failed = (stats.failed_switches > 0 or stats.missing_bars >= len(SYMBOLS) or stats.skipped_symbol_mismatch > 0)
                if sweep_failed:
                    consecutive_bad_sweeps += 1
                else:
                    consecutive_bad_sweeps = 0

                log(
                    "Sweep complete: "
                    f"added={stats.added}, "
                    f"duplicates={stats.duplicates}, "
                    f"failed_switches={stats.failed_switches}, "
                    f"missing_bars={stats.missing_bars}, "
                    f"invalid_bars={stats.invalid_bars}, "
                    f"symbol_mismatches={stats.skipped_symbol_mismatch}"
                )

                if consecutive_bad_sweeps >= 2:
                    log("Multiple bad sweeps detected. Restarting browser.")
                    browser, page, edge_process = restart_edge_debug(p, browser, edge_process)

                    if browser is None or page is None:
                        log("Bad-sweep restart failed. Waiting before retry.")
                        time.sleep(60)
                        browser, page, edge_process = connect_and_prepare_page(p)

                        if browser is None or page is None:
                            log("Reconnect failed after bad-sweep restart.")
                            sleep_until_next_bar_run()
                            continue
                    
                    consecutive_bad_sweeps = 0

                sweep_count += 1
                if sweep_count % RESTART_EVERY_N_SWEEPS == 0:
                    browser, page, edge_process = restart_edge_debug(p, browser, edge_process)

                    if browser is None or page is None:
                        log("Restart failed. Waiting before retry.")
                        time.sleep(60)
                        browser, page, edge_process = connect_and_prepare_page(p)

                        if browser is None or page is None:
                            log("Reconnect failed. Skipping next cycle.")
                            sleep_until_next_bar_run()
                            continue

                if not is_collection_time():
                    log("Collection window ended after sweep. Closing Edge.")
                    stop_edge_debug(browser, edge_process)
                    browser = None
                    page = None
                    edge_process = None
                    continue

                sleep_until_next_bar_run()

        except KeyboardInterrupt:
            log("\nCollector stopped by user.")
            stop_edge_debug(browser, edge_process)

if __name__ == "__main__":
    main()