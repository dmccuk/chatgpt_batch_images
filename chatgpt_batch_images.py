# pip install playwright pandas
# playwright install

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from pathlib import Path
import pandas as pd
import json, re, time, sys, contextlib
from datetime import datetime
from urllib.parse import urlparse
import msvcrt  # Windows safe keyboard check

# -------------- CONFIG --------------
CSV_PATH = r"C:\Users\bigd_\Downloads\chatgpt_images\calliopes_curse\prompts.csv"
CHAR_MAP_JSON = r"C:\Users\bigd_\Downloads\chatgpt_images\calliopes_curse\characters.json"
NAME_VARIANTS_JSON = r"C:\Users\bigd_\Downloads\chatgpt_images\calliopes_curse\name_variants.json"
OUTPUT_DIR = r"C:\Users\bigd_\Downloads\chatgpt_images\outputs"

PRIMARY_URL  = "https://chat.openai.com/?model=gpt-4o"
FALLBACK_URL = "https://chatgpt.com/?model=gpt-4o"

# Preprompt with style
PREPROMPT = (
    "can you create me this image in widescreen from the story, "
    "Cinematic gritty sci-fi realism, warm industrial lighting, weathered working-class starship interiors, painterly photorealism with strong character focus: "
)

PROFILE_DIR = r"C:\Users\bigd_\Downloads\chatgpt_images\chrome_profile"

# Timing
DELAY_BETWEEN_PROMPTS = 180   # 3 minutes between prompts

SELECTORS = {
    "composer_candidates": [
        "input[placeholder*='Ask anything']",
        "textarea[placeholder*='Ask anything']",
        "[aria-label*='Ask anything']",
        "div[contenteditable='true'][data-placeholder*='Ask anything']",
        "[data-testid='composer'] div[contenteditable='true']",
        "div[contenteditable='true'][data-placeholder*='Send a message']",
        "textarea[placeholder*='Send a message']",
        "[aria-label*='Message']",
        "div[contenteditable='true'][role='textbox']",
        "[contenteditable='true'][data-placeholder]",
        "[role='textbox']",
    ],
    "ask_anything_click_targets": [
        "text=Ask anything",
        "button:has-text('Ask anything')",
        "div:has-text('Ask anything')",
    ],
    "new_chat_buttons": [
        "button:has-text('New chat')",
        "a:has-text('New chat')",
        "button:has-text('Start chatting')",
        "a:has-text('Start chatting')",
        "button:has-text('Start new chat')",
    ],
    "attach_btn": "button[aria-label*='Attach'], button[data-testid='attach-button']",
    "file_input": "input[type='file']",
    "send_btn": "button:has-text('Send'), button[data-testid='send-button']",
}

# Detect tags like [@ayda] and plain name mentions
TAG_PATTERN = re.compile(r"\[@([a-zA-Z0-9_\- '’]+)\]")

# Load name variants from JSON
def load_name_variants():
    if Path(NAME_VARIANTS_JSON).exists():
        try:
            with open(NAME_VARIANTS_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading {NAME_VARIANTS_JSON}, using defaults: {e}")
    return {}

NAME_VARIANTS = load_name_variants()
# -------------- END CONFIG --------------


def load_prompts(csv_path):
    df = pd.read_csv(csv_path, dtype=str).fillna("")
    out = []
    for i, r in df.iterrows():
        pid = (r.get("id") or f"row_{i+1:03d}").strip()
        text = (r.get("prompt") or "").strip()
        if text:
            out.append({"id": pid, "prompt": text})
    return out

def load_char_map(json_path):
    if not Path(json_path).exists():
        return {}
    m = json.loads(Path(json_path).read_text(encoding="utf-8"))
    out = {}
    for k, v in m.items():
        key = k.strip().lower()
        p = Path(v).expanduser()
        if p.exists():
            out[key] = str(p)
    return out

def extract_characters(prompt_text, char_map):
    seen = set()
    tags = []

    def add_tag(value):
        key = value.strip().lower()
        if key and key not in seen:
            seen.add(key)
            tags.append(key)

    for match in TAG_PATTERN.finditer(prompt_text):
        add_tag(match.group(1))

    lower = prompt_text.lower()
    for name, pats in NAME_VARIANTS.items():
        if any(re.search(p, lower) for p in pats):
            add_tag(name)

    clean = TAG_PATTERN.sub("", prompt_text)
    clean = re.sub(r"\s{2,}", " ", clean).strip()

    for name in char_map.keys():
        pattern = re.compile(rf"\b{re.escape(name)}(?:'s)?\b", re.IGNORECASE)
        if pattern.search(clean):
            add_tag(name)

    files = [char_map[t] for t in tags if t in char_map]
    return tags, files, clean

def wait_for_cloudflare_if_needed(page, max_wait_sec=180):
    try:
        if "challenges.cloudflare.com" in page.url or "api/auth/error" in page.url:
            print("Cloudflare verification detected, complete it in the Chrome window, then press Enter here.")
            try:
                input()
            except EOFError:
                pass
            page.wait_for_load_state("networkidle", timeout=max_wait_sec * 1000)
    except Exception:
        pass

def dismiss_common_popups(page):
    for txt in ["Accept", "Got it", "Okay", "OK", "I agree", "Continue", "Dismiss"]:
        with contextlib.suppress(Exception):
            page.locator(f"button:has-text('{txt}')").first.click(timeout=400)

def in_conversation(url: str) -> bool:
    try:
        u = urlparse(url)
        return "/c/" in u.path or "model=" in (u.query or "")
    except Exception:
        return False

def find_composer_any_frame(page, timeout_ms=15000):
    deadline = time.time() + timeout_ms / 1000.0

    def try_frame(frame):
        with contextlib.suppress(Exception):
            loc = frame.get_by_placeholder("Ask anything")
            loc.first.wait_for(state="visible", timeout=1200)
            return loc.first
        with contextlib.suppress(Exception):
            loc = frame.get_by_role("textbox")
            loc.first.wait_for(state="visible", timeout=1200)
            return loc.first
        for sel in SELECTORS["composer_candidates"]:
            with contextlib.suppress(Exception):
                loc = frame.locator(sel)
                loc.first.wait_for(state="visible", timeout=1200)
                return loc.first
        return None

    while time.time() < deadline:
        cand = try_frame(page)
        if cand:
            return cand
        for fr in page.frames:
            cand = try_frame(fr)
            if cand:
                return cand
        time.sleep(0.3)

    with contextlib.suppress(Exception):
        page.evaluate("""
            () => {
                const eds = Array.from(document.querySelectorAll('[contenteditable="true"]'));
                const last = eds[eds.length - 1];
                if (last) { last.focus(); return true; }
                return false;
            }
        """)
        loc = page.locator('[contenteditable="true"]').last
        loc.wait_for(state="visible", timeout=1200)
        return loc

    raise TimeoutError("Composer not visible in any frame")

def ensure_composer_ready(page):
    try:
        return find_composer_any_frame(page, timeout_ms=6000)
    except Exception:
        pass
    if not in_conversation(page.url):
        for sel in SELECTORS["new_chat_buttons"]:
            with contextlib.suppress(Exception):
                el = page.locator(sel).first
                if el.is_visible():
                    el.click()
                    page.wait_for_load_state("domcontentloaded")
                    return find_composer_any_frame(page, timeout_ms=6000)
    page.reload()
    wait_for_cloudflare_if_needed(page)
    dismiss_common_popups(page)
    return find_composer_any_frame(page, timeout_ms=8000)

def goto_with_fallback(page):
    for url in [PRIMARY_URL, FALLBACK_URL]:
        page.goto(url)
        wait_for_cloudflare_if_needed(page)
        dismiss_common_popups(page)
        try:
            comp = ensure_composer_ready(page)
            if comp:
                return
        except Exception:
            pass

# --- Countdown with skip, Windows safe ---
def wait_with_skip(total_seconds, step=10):
    print(f"Waiting up to {total_seconds//60} minutes... (press Enter to skip)")
    for remaining in range(total_seconds, 0, -step):
        mins, secs = divmod(remaining, 60)
        print(f"Time left: {mins:02d}:{secs:02d}", end="\r", flush=True)

        for _ in range(step):
            if msvcrt.kbhit():
                key = msvcrt.getwch()
                if key == "\r":
                    print("\n>> Enter pressed, skipping wait")
                    return
            time.sleep(1)

    print("\n>> Wait finished, continuing...")

# --- Main ---
def main():
    prompts = load_prompts(CSV_PATH)
    if not prompts:
        print("No prompts found, check CSV_PATH")
        sys.exit(1)
    char_map = load_char_map(CHAR_MAP_JSON)
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    Path(PROFILE_DIR).mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=False,
            channel="chrome",
            viewport={"width": 1340, "height": 900},
            accept_downloads=True,
        )
        page = ctx.new_page()
        goto_with_fallback(page)

        print("If you see a login or human check, finish it now in the Chrome window, open a chat, then press Enter here.")
        try:
            input()
        except EOFError:
            pass

        try:
            composer = ensure_composer_ready(page)
        except Exception:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            snap = Path(OUTPUT_DIR) / f"debug_no_composer_{ts}.png"
            with contextlib.suppress(Exception):
                page.screenshot(path=str(snap), full_page=True)
            print(f"Composer not found, saved page snapshot to {snap}")
            return

        for idx, item in enumerate(prompts, start=1):
            raw = item["prompt"]
            tags, char_files, clean_prompt = extract_characters(raw, char_map)
            message = PREPROMPT + clean_prompt

            page.bring_to_front()
            page.wait_for_load_state("domcontentloaded")
            dismiss_common_popups(page)

            composer = ensure_composer_ready(page)
            composer.click()
            try:
                composer.fill(message)
            except PWTimeout:
                composer.type(message, delay=10)
            time.sleep(0.2)

            finputs = page.query_selector_all(SELECTORS["file_input"])
            attached_files = []
            if char_files and finputs:
                try:
                    finputs[0].set_input_files(char_files)
                    attached_files = [Path(f).name for f in char_files]
                    time.sleep(0.5)
                except Exception as e:
                    print(f"Could not attach files for {item['id']}, {e}")

            if page.query_selector(SELECTORS["send_btn"]):
                page.click(SELECTORS["send_btn"])
            else:
                page.keyboard.press("Enter")

            if attached_files:
                print(f"[{item['id']}] Prompt sent, attached: {', '.join(attached_files)}")
            else:
                print(f"[{item['id']}] Prompt sent, no attachments")

            wait_with_skip(DELAY_BETWEEN_PROMPTS, step=10)

        print("All prompts processed")

if __name__ == "__main__":
    main()
