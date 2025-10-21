# Windows 11, Python 3.10+
# pip install playwright pandas
# playwright install

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import threading, time, json, re, sys, contextlib
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ----------------------------- GUI APP -----------------------------

class ImageGenApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ChatGPT batch image generator")

        # state
        self.running_thread = None
        self.skip_event = threading.Event()
        self.stop_event = threading.Event()
        self.config_path = Path("generator_config.json")

        # defaults
        self.primary_url = tk.StringVar(value="https://chat.openai.com/?model=gpt-5")
        self.fallback_url = tk.StringVar(value="https://chatgpt.com/?model=gpt-5")
        self.profile_dir = tk.StringVar(value=str(Path.cwd() / "chrome_profile"))
        self.output_dir = tk.StringVar(value=str(Path.cwd() / "outputs"))
        self.csv_path = tk.StringVar()
        self.char_json = tk.StringVar()
        self.variants_json = tk.StringVar()
        self.preprompt = tk.StringVar(value="can you create me this image in widescreen from the story, Cinematic gritty sci fi realism, warm industrial lighting, weathered working class starship interiors, painterly photorealism with strong character focus: ")
        self.delay_sec = tk.IntVar(value=180)

        # try load saved config
        self._load_config()

        # layout
        r = 0
        self._row("Prompts file", self.csv_path, self._pick_csv, r); r += 1
        self._row("characters.json", self.char_json, self._pick_json_char, r); r += 1
        self._row("name_variants.json", self.variants_json, self._pick_json_var, r); r += 1
        self._row("Chrome profile folder", self.profile_dir, lambda: self._pick_folder(self.profile_dir), r); r += 1
        self._row("Outputs folder", self.output_dir, lambda: self._pick_folder(self.output_dir), r); r += 1

        tk.Label(root, text="Preprompt").grid(row=r, column=0, sticky="e")
        tk.Entry(root, width=90, textvariable=self.preprompt).grid(row=r, column=1, columnspan=2, sticky="we"); r += 1

        tk.Label(root, text="Delay between prompts, seconds").grid(row=r, column=0, sticky="e")
        tk.Spinbox(root, from_=10, to=900, increment=10, width=8, textvariable=self.delay_sec).grid(row=r, column=1, sticky="w"); r += 1

        tk.Label(root, text="Primary URL").grid(row=r, column=0, sticky="e")
        tk.Entry(root, width=90, textvariable=self.primary_url).grid(row=r, column=1, columnspan=2, sticky="we"); r += 1
        tk.Label(root, text="Fallback URL").grid(row=r, column=0, sticky="e")
        tk.Entry(root, width=90, textvariable=self.fallback_url).grid(row=r, column=1, columnspan=2, sticky="we"); r += 1

        btns = tk.Frame(root)
        btns.grid(row=r, column=0, columnspan=3, pady=6, sticky="w")
        tk.Button(btns, text="Run setup", command=self._run_setup).pack(side="left", padx=4)
        tk.Button(btns, text="Start generation", command=self._start).pack(side="left", padx=4)
        tk.Button(btns, text="Skip wait now", command=self._skip_now).pack(side="left", padx=4)
        tk.Button(btns, text="Stop", command=self._stop).pack(side="left", padx=4)
        # new helper to build characters.json and name_variants.json
        tk.Button(btns, text="Generate JSONs", command=self._generate_jsons).pack(side="left", padx=4)
        r += 1

        self.console = scrolledtext.ScrolledText(root, width=110, height=24, state="disabled")
        self.console.grid(row=r, column=0, columnspan=3, pady=6, sticky="nsew")
        root.grid_columnconfigure(1, weight=1)
        root.grid_rowconfigure(r, weight=1)

    # rows
    def _row(self, label, var, cmd, row):
        tk.Label(self.root, text=label).grid(row=row, column=0, sticky="e")
        tk.Entry(self.root, width=90, textvariable=var).grid(row=row, column=1, sticky="we")
        tk.Button(self.root, text="Browse", command=cmd).grid(row=row, column=2, sticky="w")

    # pickers
    def _pick_csv(self):
        p = filedialog.askopenfilename(
            title="Select prompts file, CSV or TXT",
            filetypes=[("CSV or TXT", "*.csv *.txt"), ("CSV files", "*.csv"), ("Text files", "*.txt")]
        )
        if p:
            self.csv_path.set(p)
            self._save_config()

    def _pick_json_char(self):
        p = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if p: self.char_json.set(p); self._save_config()
    def _pick_json_var(self):
        p = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if p: self.variants_json.set(p); self._save_config()
    def _pick_folder(self, var):
        p = filedialog.askdirectory()
        if p: var.set(p); self._save_config()

    # logging
    def log(self, msg):
        self.console.configure(state="normal")
        self.console.insert("end", msg + "\n")
        self.console.see("end")
        self.console.configure(state="disabled")

    # setup
    def _run_setup(self):
        def worker():
            import subprocess
            cmds = [
                ["pip", "install", "playwright", "pandas"],
                ["playwright", "install"],
            ]
            for cmd in cmds:
                self.log(f"$ {' '.join(cmd)}")
                try:
                    subprocess.run(cmd, check=False)
                except Exception as e:
                    self.log(f"Setup step failed, {e}")
            self.log("Setup complete.")
        threading.Thread(target=worker, daemon=True).start()

    # new, auto generate characters.json and name_variants.json
    def _generate_jsons(self):
        img_dir = filedialog.askdirectory(title="Select character_images folder")
        if not img_dir:
            return
        img_dir = Path(img_dir)

        chars = {}
        variants = {}
        for file in img_dir.iterdir():
            if file.is_file() and file.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]:
                key = file.stem.strip().lower()
                chars[key] = str(file.resolve())
                safe = re.escape(key)
                variants[key] = [fr"\b{safe}\b"]

        if not chars:
            messagebox.showerror("No images", f"No character images found in {img_dir}")
            return

        # save next to the images folder parent, common project layout
        char_json_path = img_dir.parent / "characters.json"
        variants_json_path = img_dir.parent / "name_variants.json"

        try:
            char_json_path.write_text(json.dumps(chars, indent=2), encoding="utf-8")
            variants_json_path.write_text(json.dumps(variants, indent=2), encoding="utf-8")
        except Exception as e:
            messagebox.showerror("Write error", f"Could not write JSON files, {e}")
            return

        # update GUI fields and persist
        self.char_json.set(str(char_json_path))
        self.variants_json.set(str(variants_json_path))
        self._save_config()
        self.log(f"Generated {char_json_path} and {variants_json_path}")

    # control
    def _start(self):
        if self.running_thread and self.running_thread.is_alive():
            messagebox.showinfo("Running", "Generation is already in progress.")
            return
        if not Path(self.csv_path.get()).exists():
            messagebox.showerror("Missing file", "Please choose a valid prompts file.")
            return
        if not Path(self.char_json.get()).exists():
            messagebox.showerror("Missing file", "Please choose a valid characters.json.")
            return
        if not Path(self.variants_json.get()).exists():
            messagebox.showerror("Missing file", "Please choose a valid name_variants.json.")
            return
        Path(self.output_dir.get()).mkdir(parents=True, exist_ok=True)
        Path(self.profile_dir.get()).mkdir(parents=True, exist_ok=True)

        self.skip_event.clear()
        self.stop_event.clear()
        self._save_config()
        self.running_thread = threading.Thread(target=self._run_generator, daemon=True)
        self.running_thread.start()

    def _skip_now(self):
        self.skip_event.set()

    def _stop(self):
        self.stop_event.set()
        self.log("Stop requested, will halt after the current step.")

    # config persistence
    def _save_config(self):
        data = dict(
            csv=self.csv_path.get(),
            characters=self.char_json.get(),
            variants=self.variants_json.get(),
            output=self.output_dir.get(),
            profile=self.profile_dir.get(),
            preprompt=self.preprompt.get(),
            delay=self.delay_sec.get(),
            primary=self.primary_url.get(),
            fallback=self.fallback_url.get(),
        )
        self.config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_config(self):
        if self.config_path.exists():
            try:
                cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
                self.csv_path.set(cfg.get("csv", ""))
                self.char_json.set(cfg.get("characters", ""))
                self.variants_json.set(cfg.get("variants", ""))
                self.output_dir.set(cfg.get("output", str(Path.cwd() / "outputs")))
                self.profile_dir.set(cfg.get("profile", str(Path.cwd() / "chrome_profile")))
                self.preprompt.set(cfg.get("preprompt", self.preprompt.get()))
                self.delay_sec.set(int(cfg.get("delay", 180)))
                self.primary_url.set(cfg.get("primary", self.primary_url.get()))
                self.fallback_url.set(cfg.get("fallback", self.fallback_url.get()))
            except Exception:
                pass

    # --------------------- batch generation core ---------------------

    def _run_generator(self):
        CSV_PATH = self.csv_path.get()
        CHAR_MAP_JSON = self.char_json.get()
        NAME_VARIANTS_JSON = self.variants_json.get()
        OUTPUT_DIR = self.output_dir.get()
        PROFILE_DIR = self.profile_dir.get()
        PREPROMPT = self.preprompt.get()
        PRIMARY_URL = self.primary_url.get()
        FALLBACK_URL = self.fallback_url.get()
        DELAY_BETWEEN_PROMPTS = int(self.delay_sec.get())

        def log(msg): self.log(msg)

        TAG_PATTERN = re.compile(r"\[@([a-zA-Z0-9_\- '’]+)\]")

        def load_name_variants(path):
            try:
                return json.loads(Path(path).read_text(encoding="utf-8"))
            except Exception as e:
                log(f"Could not load name_variants.json, {e}")
                return {}

        # updated, supports CSV and TXT
        def load_prompts(prompts_path: str):
            """
            Accepts:
              1) CSV with header id,prompt (either .csv or .txt)
              2) CSV without header: prompt_id,"prompt text..."
              3) Plain TXT, one prompt per paragraph separated by blank lines
              4) Plain TXT where a block starts with 'prompt123:' or 'id: ...'
            Returns list of {id, prompt}
            """
            p = Path(prompts_path)
            if not p.exists():
                return []

            text = p.read_text(encoding="utf-8", errors="ignore").strip()

            def normalize(rows):
                out = []
                for i, row in enumerate(rows, start=1):
                    pid = str(row.get("id") or f"row_{i:03d}").strip()
                    pr = (row.get("prompt") or "").strip()
                    if pr:
                        out.append({"id": pid, "prompt": pr})
                return out

            # detect CSV like content
            looks_like_csv = False
            first_line = text.splitlines()[0] if text else ""
            if "," in first_line or p.suffix.lower() in [".csv", ".txt"]:
                if first_line.lower().strip().startswith("id,prompt"):
                    looks_like_csv = True
                elif re.match(r'^\s*[^,]+,\s*".*"$', first_line) or re.match(r"^\s*[^,]+,\s*[^\"].+$", first_line):
                    looks_like_csv = True

            if looks_like_csv:
                try:
                    import io
                    df = pd.read_csv(io.StringIO(text), dtype=str)
                    cols = [c.lower().strip() for c in df.columns]
                    if len(df.columns) == 2 and set(cols) != {"id", "prompt"}:
                        df = pd.read_csv(io.StringIO(text), names=["id", "prompt"], header=None, dtype=str)
                    df = df.fillna("")
                    rows = [{"id": str(r.get("id", f"row_{i+1}")).strip(),
                             "prompt": str(r.get("prompt", "")).strip()}
                            for i, r in df.iterrows()]
                    return normalize(rows)
                except Exception:
                    pass  # fall through to TXT parsing

            # plain TXT parsing
            blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
            rows = []
            for idx, block in enumerate(blocks, start=1):
                lines = block.splitlines()
                if not lines:
                    continue
                header = lines[0].strip()
                m1 = re.match(r"^(prompt[_\- ]?\d+)\s*:\s*(.*)$", header, flags=re.IGNORECASE)
                m2 = re.match(r"^id\s*:\s*(.+)$", header, flags=re.IGNORECASE)
                if m1:
                    pid = m1.group(1).strip()
                    rest = m1.group(2).strip()
                    prompt_text = (rest + "\n" + "\n".join(lines[1:])).strip() if rest else "\n".join(lines[1:]).strip()
                elif m2:
                    pid = m2.group(1).strip()
                    prompt_text = "\n".join(lines[1:]).strip()
                else:
                    pid = f"row_{idx:03d}"
                    prompt_text = block.strip()
                if prompt_text:
                    rows.append({"id": pid, "prompt": prompt_text})

            return normalize(rows)

        def load_char_map(json_path):
            if not Path(json_path).exists(): return {}
            m = json.loads(Path(json_path).read_text(encoding="utf-8"))
            out = {}
            for k, v in m.items():
                key = k.strip().lower()
                p = Path(v).expanduser()
                if p.exists():
                    out[key] = str(p)
            return out

        NAME_VARIANTS = load_name_variants(NAME_VARIANTS_JSON)

        def extract_characters(prompt_text, char_map):
            tags = [m.group(1).strip().lower() for m in TAG_PATTERN.finditer(prompt_text)]
            lower = prompt_text.lower()
            for name, pats in NAME_VARIANTS.items():
                try:
                    if name not in tags and any(re.search(p, lower) for p in pats):
                        tags.append(name)
                except Exception:
                    pass
            clean = TAG_PATTERN.sub("", prompt_text)
            clean = re.sub(r"\s{2,}", " ", clean).strip()
            files = [char_map[t] for t in tags if t in char_map]
            return tags, files, clean

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
                if cand: return cand
                for fr in page.frames:
                    cand = try_frame(fr)
                    if cand: return cand
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
            raise TimeoutError("Composer not visible")

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
            dismiss_common_popups(page)
            return find_composer_any_frame(page, timeout_ms=8000)

        def goto_with_fallback(page):
            for url in [self.primary_url.get(), self.fallback_url.get()]:
                page.goto(url)
                dismiss_common_popups(page)
                try:
                    comp = ensure_composer_ready(page)
                    if comp: return
                except Exception:
                    pass

        # do work
        try:
            prompts = load_prompts(CSV_PATH)
            if not prompts:
                log("No prompts found, check file")
                return
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

                log("If you see a login or human check, finish it in Chrome, open a chat, then return here and click OK.")
                if not messagebox.askokcancel("Login check", "Finish login if needed, then click OK to start."):
                    log("Canceled by user.")
                    return

                try:
                    composer = ensure_composer_ready(page)
                except Exception:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    snap = Path(OUTPUT_DIR) / f"debug_no_composer_{ts}.png"
                    with contextlib.suppress(Exception):
                        page.screenshot(path=str(snap), full_page=True)
                    log(f"Composer not found, saved snapshot to {snap}")
                    return

                for idx, item in enumerate(prompts, start=1):
                    if self.stop_event.is_set():
                        log("Stop requested, exiting loop.")
                        break

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

                    finputs = page.query_selector_all("input[type='file']")
                    attached_files = []
                    if char_files and finputs:
                        try:
                            finputs[0].set_input_files(char_files)
                            attached_files = [Path(f).name for f in char_files]
                            time.sleep(0.5)
                        except Exception as e:
                            log(f"Attach failed for {item['id']}, {e}")

                    if page.query_selector(SELECTORS["send_btn"]):
                        page.click(SELECTORS["send_btn"])
                    else:
                        page.keyboard.press("Enter")

                    if attached_files:
                        log(f"[{item['id']}] Prompt sent, attached: {', '.join(attached_files)}")
                    else:
                        log(f"[{item['id']}] Prompt sent, no attachments")

                    # wait with skip, log every 10 seconds only
                    self.skip_event.clear()
                    remaining = DELAY_BETWEEN_PROMPTS
                    log(f"Waiting up to {remaining // 60} minutes. Click 'Skip wait now' to continue immediately.")
                    while remaining > 0 and not self.skip_event.is_set() and not self.stop_event.is_set():
                        if remaining % 10 == 0 or remaining == 1:
                            mins, secs = divmod(remaining, 60)
                            self.log(f"Time left: {mins:02d}:{secs:02d}")
                        time.sleep(1)
                        remaining -= 1

                    if self.skip_event.is_set():
                        log(">> Skip pressed, continuing")
                    elif self.stop_event.is_set():
                        log(">> Stop requested, halting after current step")
                        break
                    else:
                        log(">> Wait finished, continuing")

                log("All prompts processed.")
        except Exception as e:
            log(f"Fatal error, {e}")

    def _set_status_line(self, text):
        # kept for compatibility, but not used by the new countdown
        self.console.configure(state="normal")
        self.console.insert("end", text + "\r")
        self.console.see("end")
        self.console.configure(state="disabled")


if __name__ == "__main__":
    root = tk.Tk()
    app = ImageGenApp(root)
    root.mainloop()
