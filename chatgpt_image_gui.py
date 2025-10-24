# Windows 11, Python 3.10+
# pip install playwright pandas
# playwright install

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from tkinter import font as tkfont
from tkinter import ttk
import threading, time, json, re, sys, contextlib, os, shutil, subprocess
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ----------------------------- GUI APP -----------------------------

class ImageGenApp:
    def __init__(self, root):
        self.root = root
        self.root.title("PromptBot caption & image generator")
        self.root.protocol("WM_DELETE_WINDOW", self._exit_app)
        icon_path = Path(__file__).with_name("promptBot.ico")
        if icon_path.exists():
            try:
                self.root.iconbitmap(icon_path)
            except tk.TclError:
                pass

        # state
        self.running_thread = None
        self.skip_event = threading.Event()
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.config_path = Path("generator_config.json")
        self._save_after_id: str | None = None

        # defaults
        self.primary_url = tk.StringVar(value="https://chat.openai.com/?model=gpt-5")
        self.fallback_url = tk.StringVar(value="https://chatgpt.com/?model=gpt-5")
        default_profile = Path.cwd() / "chrome_profile"
        if sys.platform == "win32":
            local_app = os.environ.get("LOCALAPPDATA")
            if local_app:
                default_profile = Path(local_app) / "ChromeProfiles" / "chatgpt_profile"
        self.profile_dir = tk.StringVar(value=str(default_profile))
        self.output_dir = tk.StringVar(value=str(Path.cwd() / "outputs"))
        self.csv_path = tk.StringVar()
        self.char_json = tk.StringVar()
        self.variants_json = tk.StringVar()
        self.preprompt = tk.StringVar(value="can you create me this image in widescreen from the story, Cinematic gritty sci fi realism, warm industrial lighting, weathered working class starship interiors, painterly photorealism with strong character focus: ")
        self.delay_sec = tk.IntVar(value=180)

        # try load saved config
        self._load_config()
        self._setup_config_autosave()

        # styling & layout
        self._init_styles()
        self.root.configure(bg=self.colors["background"])
        self.root.minsize(940, 500)
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        main = ttk.Frame(root, style="PromptBot.TFrame", padding=(18, 14, 18, 16))
        main.grid(row=0, column=0, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)

        header = ttk.Frame(main, style="PromptBotHeader.TFrame", padding=(16, 12))
        header.grid(row=0, column=0, sticky="nsew")
        header.grid_columnconfigure(1, weight=1)
        self._build_header(header)

        form_card = ttk.Frame(main, style="PromptBotCard.TFrame", padding=(16, 14))
        form_card.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        form_card.grid_columnconfigure(1, weight=1)
        form_card.grid_columnconfigure(2, weight=0)

        row = 0
        ttk.Label(form_card, text="Project files", style="PromptBotSection.TLabel").grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        ttk.Label(
            form_card,
            text="Supply PromptBot with the prompts, character mappings, and output locations.",
            style="PromptBotNote.TLabel",
            wraplength=600,
            justify="left",
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(2, 8))
        row += 1

        self._row(form_card, "Prompts file", self.csv_path, self._pick_csv, row); row += 1
        self._row(form_card, "characters.json", self.char_json, self._pick_json_char, row); row += 1
        self._row(form_card, "name_variants.json", self.variants_json, self._pick_json_var, row); row += 1
        self._row(form_card, "Chrome profile folder", self.profile_dir, lambda: self._pick_folder(self.profile_dir), row); row += 1
        self._row(form_card, "Outputs folder", self.output_dir, lambda: self._pick_folder(self.output_dir), row); row += 1

        ttk.Separator(form_card, orient="horizontal", style="PromptBot.TSeparator").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=(6, 10)
        )
        row += 1

        ttk.Label(form_card, text="Generation settings", style="PromptBotSection.TLabel").grid(
            row=row, column=0, columnspan=3, sticky="w"
        )
        row += 1
        ttk.Label(
            form_card,
            text="Adjust default prompt text, pacing, and ChatGPT endpoints.",
            style="PromptBotNote.TLabel",
            wraplength=600,
            justify="left",
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(2, 8))
        row += 1

        ttk.Label(form_card, text="Preprompt", style="PromptBotFieldLabel.TLabel").grid(row=row, column=0, sticky="w")
        ttk.Entry(form_card, textvariable=self.preprompt, style="PromptBot.TEntry").grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=(0, 6), padx=(0, 12)
        )
        row += 1

        ttk.Label(
            form_card,
            text="Delay between prompts (seconds)",
            style="PromptBotFieldLabel.TLabel",
        ).grid(row=row, column=0, sticky="w")
        ttk.Spinbox(
            form_card,
            from_=10,
            to=900,
            increment=10,
            width=10,
            textvariable=self.delay_sec,
            style="PromptBot.TSpinbox",
        ).grid(row=row, column=1, sticky="w", pady=(0, 6), padx=(0, 12))
        row += 1

        ttk.Label(form_card, text="Primary URL", style="PromptBotFieldLabel.TLabel").grid(row=row, column=0, sticky="w")
        ttk.Entry(form_card, textvariable=self.primary_url, style="PromptBot.TEntry").grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=(0, 6), padx=(0, 12)
        )
        row += 1

        ttk.Label(form_card, text="Fallback URL", style="PromptBotFieldLabel.TLabel").grid(row=row, column=0, sticky="w")
        ttk.Entry(form_card, textvariable=self.fallback_url, style="PromptBot.TEntry").grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=(0, 8), padx=(0, 12)
        )
        row += 1

        btns = ttk.Frame(form_card, style="PromptBotCard.TFrame")
        btns.grid(row=row, column=0, columnspan=3, sticky="ew")

        ttk.Button(btns, text="Start generation", command=self._start, style="Primary.TButton").pack(side="left", padx=(0, 6))
        self.pause_btn = ttk.Button(btns, text="Pause wait", command=self._toggle_pause, style="Secondary.TButton")
        self.pause_btn.pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="Skip wait now", command=self._skip_now, style="Secondary.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="Stop", command=self._stop, style="Danger.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(
            btns,
            text="Launch profile in Chrome",
            command=self._launch_profile_browser,
            style="Secondary.TButton",
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            btns,
            text="Generate JSONs",
            command=self._generate_jsons,
            style="Accent.TButton",
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            btns,
            text="Exit",
            command=self._exit_app,
            style="Secondary.TButton",
        ).pack(side="right", padx=(6, 0))
        ttk.Button(
            btns,
            text="Save settings",
            command=self._save_settings_now,
            style="Secondary.TButton",
        ).pack(side="right", padx=(6, 0))

        log_card = ttk.Frame(main, style="PromptBotCard.TFrame", padding=(16, 14))
        log_card.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(2, weight=1)

        ttk.Label(log_card, text="Activity log", style="PromptBotSection.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            log_card,
            text="Monitor setup and batch progress. Messages update automatically while jobs run.",
            style="PromptBotNote.TLabel",
            wraplength=600,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(2, 8))

        self.console = scrolledtext.ScrolledText(
            log_card,
            width=110,
            height=18,
            state="disabled",
            relief="flat",
            borderwidth=0,
            wrap="word",
        )
        self.console.grid(row=2, column=0, sticky="nsew")
        self.console.configure(
            background=self.colors["console_bg"],
            foreground=self.colors["text"],
            insertbackground=self.colors["accent"],
            highlightthickness=1,
            highlightbackground=self.colors["border"],
            highlightcolor=self.colors["accent"],
            selectbackground=self.colors["accent"],
            selectforeground=self.colors["background"],
            font="TkFixedFont",
        )

        status_bar = ttk.Frame(log_card, style="PromptBotCard.TFrame")
        status_bar.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        status_bar.grid_columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(status_bar, textvariable=self.status_var, style="PromptBotStatus.TLabel").grid(
            row=0, column=0, sticky="w"
        )

        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = max(self.root.winfo_height() - 100, 100)
        x_offset = (self.root.winfo_screenwidth() - width) // 2
        self.root.geometry(f"{width}x{height}+{x_offset}+0")

    # styling helpers
    def _blend_colors(self, color_a: str, color_b: str, ratio: float) -> str:
        ratio = max(0.0, min(1.0, ratio))

        def hex_to_rgb(value: str) -> tuple[int, int, int]:
            value = value.lstrip("#")
            return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))

        r1, g1, b1 = hex_to_rgb(color_a)
        r2, g2, b2 = hex_to_rgb(color_b)
        r = int(r1 + (r2 - r1) * ratio)
        g = int(g1 + (g2 - g1) * ratio)
        b = int(b1 + (b2 - b1) * ratio)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _init_palette(self):
        self.colors = {
            "background": "#041326",
            "card": "#0b1f3a",
            "card_highlight": "#11284d",
            "primary": "#0f6dff",
            "accent": "#38bdf8",
            "text": "#f8fafc",
            "muted": "#8ea2c3",
            "label": "#dbeafe",
            "border": "#1e3357",
            "console_bg": "#07142c",
            "input_bg": "#102646",
            "danger": "#ef4444",
            "disabled_bg": "#102037",
            "disabled_fg": "#46546b",
        }
        self.colors["primary_dark"] = self._blend_colors(self.colors["primary"], "#000000", 0.2)
        self.colors["primary_hover"] = self._blend_colors(self.colors["primary"], "#ffffff", 0.18)
        self.colors["accent_muted"] = self._blend_colors(self.colors["accent"], "#ffffff", 0.6)
        self.colors["accent_hover"] = self._blend_colors(self.colors["accent"], "#ffffff", 0.24)
        self.colors["secondary_bg"] = self._blend_colors(self.colors["card"], "#ffffff", 0.08)
        self.colors["secondary_hover"] = self._blend_colors(self.colors["secondary_bg"], "#ffffff", 0.12)
        self.colors["danger_hover"] = self._blend_colors(self.colors["danger"], "#ffffff", 0.14)

    def _init_fonts(self):
        family = "Segoe UI"
        base = tkfont.Font(family=family, size=10)
        bold = tkfont.Font(family=family, size=10, weight="bold")

        self.fonts = {
            "base": base,
            "bold": bold,
            "title": tkfont.Font(family=family, size=20, weight="bold"),
            "subtitle": tkfont.Font(family=family, size=11),
            "section": tkfont.Font(family=family, size=11, weight="bold"),
            "note": tkfont.Font(family=family, size=9),
        }

    def _init_styles(self):
        self._init_palette()
        self._init_fonts()
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", font=self.fonts["base"])
        style.configure("PromptBot.TFrame", background=self.colors["background"])
        style.configure("PromptBotHeader.TFrame", background=self.colors["primary"])
        style.configure("PromptBotCard.TFrame", background=self.colors["card"])

        style.configure(
            "HeaderTitle.TLabel",
            background=self.colors["primary"],
            foreground="white",
            font=self.fonts["title"],
        )
        style.configure(
            "HeaderSubtitle.TLabel",
            background=self.colors["primary"],
            foreground=self.colors["accent_muted"],
            font=self.fonts["subtitle"],
        )
        style.configure(
            "PromptBotSection.TLabel",
            background=self.colors["card"],
            foreground=self.colors["label"],
            font=self.fonts["section"],
        )
        style.configure(
            "PromptBot.TLabel",
            background=self.colors["card"],
            foreground=self.colors["text"],
            font=self.fonts["base"],
        )
        style.configure(
            "PromptBotFieldLabel.TLabel",
            background=self.colors["card"],
            foreground=self.colors["muted"],
            font=self.fonts["bold"],
        )
        style.configure(
            "PromptBotNote.TLabel",
            background=self.colors["card"],
            foreground=self.colors["muted"],
            font=self.fonts["note"],
        )

        style.configure(
            "PromptBotStatus.TLabel",
            background=self.colors["card"],
            foreground=self.colors["accent_muted"],
            font=self.fonts["bold"],
        )

        style.configure(
            "Primary.TButton",
            background=self.colors["primary"],
            foreground="white",
            font=self.fonts["bold"],
            padding=(10, 5),
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "Primary.TButton",
            background=[("active", self.colors["primary_hover"]), ("disabled", self.colors["disabled_bg"])],
            foreground=[("disabled", self.colors["disabled_fg"])],
        )

        style.configure(
            "Secondary.TButton",
            background=self.colors["secondary_bg"],
            foreground=self.colors["text"],
            font=self.fonts["base"],
            padding=(8, 5),
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "Secondary.TButton",
            background=[("active", self.colors["secondary_hover"]), ("disabled", self.colors["disabled_bg"])],
            foreground=[("disabled", self.colors["disabled_fg"])],
        )

        style.configure(
            "Accent.TButton",
            background=self.colors["accent"],
            foreground=self.colors["background"],
            font=self.fonts["bold"],
            padding=(10, 5),
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "Accent.TButton",
            background=[("active", self.colors["accent_hover"]), ("disabled", self.colors["disabled_bg"])],
            foreground=[("disabled", self.colors["disabled_fg"])],
        )

        style.configure(
            "Danger.TButton",
            background=self.colors["danger"],
            foreground="white",
            font=self.fonts["bold"],
            padding=(10, 5),
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "Danger.TButton",
            background=[("active", self.colors["danger_hover"]), ("disabled", self.colors["disabled_bg"])],
            foreground=[("disabled", self.colors["disabled_fg"])],
        )

        style.configure(
            "PromptBot.TEntry",
            fieldbackground=self.colors["input_bg"],
            background=self.colors["input_bg"],
            foreground=self.colors["text"],
            font=self.fonts["base"],
            padding=(8, 4),
        )
        style.map(
            "PromptBot.TEntry",
            fieldbackground=[("focus", self.colors["card_highlight"])],
        )

        style.configure(
            "PromptBot.TSpinbox",
            fieldbackground=self.colors["input_bg"],
            background=self.colors["input_bg"],
            foreground=self.colors["text"],
            font=self.fonts["base"],
            padding=(8, 4),
            arrowsize=14,
        )
        style.map(
            "PromptBot.TSpinbox",
            fieldbackground=[("focus", self.colors["card_highlight"])],
        )

        style.configure("PromptBot.TSeparator", background=self.colors["border"])

        self.style = style

    def _build_header(self, parent: ttk.Frame):
        icon = tk.Canvas(parent, width=72, height=72, bg=self.colors["primary"], highlightthickness=0)
        icon.grid(row=0, column=0, rowspan=2, padx=(0, 20))
        self._draw_logo_icon(icon)

        ttk.Label(parent, text="PromptBot", style="HeaderTitle.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(
            parent,
            text="Batch prompts to orchestrate cinematic caption imagery.",
            style="HeaderSubtitle.TLabel",
            wraplength=520,
            justify="left",
        ).grid(row=1, column=1, sticky="w", pady=(4, 0))

    def _draw_logo_icon(self, canvas: tk.Canvas):
        canvas.delete("all")
        base = self.colors["primary"]
        halo = self.colors["primary_dark"]
        accent = self.colors["accent"]

        canvas.create_oval(6, 12, 66, 70, fill=halo, outline=accent, width=4)
        canvas.create_line(36, 6, 36, 18, fill=accent, width=4, capstyle=tk.ROUND)
        canvas.create_oval(30, 0, 42, 12, fill=accent, outline=accent)
        canvas.create_rectangle(20, 28, 52, 54, fill=base, outline=accent, width=3)
        canvas.create_oval(26, 36, 34, 44, fill="white", outline=base, width=2)
        canvas.create_oval(38, 36, 46, 44, fill="white", outline=base, width=2)
        canvas.create_rectangle(30, 48, 42, 54, fill=accent, outline=accent)

    # rows
    def _row(self, parent, label, var, cmd, row):
        ttk.Label(parent, text=label, style="PromptBotFieldLabel.TLabel").grid(row=row, column=0, sticky="w")
        ttk.Entry(parent, textvariable=var, style="PromptBot.TEntry").grid(
            row=row, column=1, sticky="ew", padx=(0, 12), pady=(0, 4)
        )
        ttk.Button(parent, text="Browse", command=cmd, style="Secondary.TButton").grid(row=row, column=2, sticky="w", pady=(0, 4))

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

    def _set_activity_status(self, message: str):
        if not hasattr(self, "status_var"):
            return

        def updater():
            self.status_var.set(message)

        self.root.after(0, updater)

    # new, auto generate characters.json and name_variants.json
    def _generate_jsons(self):
        img_dir = filedialog.askdirectory(title="Select character_images folder")
        if not img_dir:
            return
        img_dir = Path(img_dir)

        def tokenize_name(stem: str):
            """Split a filename stem into lowercase tokens.

            Handles separators (spaces, hyphen, underscore) and CamelCase so that a
            name like "AydaPrime" yields tokens ["ayda", "prime"]. Apostrophes are
            preserved to support names such as "O'Connor".
            """
            sanitized = re.sub(r"[^0-9A-Za-z'’_\-\s]", " ", stem)
            parts = [p for p in re.split(r"[\s_\-]+", sanitized) if p]
            if len(parts) == 1:
                part = parts[0]
                camel = re.findall(r"[A-Z]?[a-z0-9'’]+|[A-Z]+(?![a-z])", part)
                if len(camel) > 1:
                    parts = camel
            return [p.lower() for p in parts]

        def flex_apostrophes(text: str) -> str:
            """Allow both straight and curly apostrophes inside a regex pattern."""
            return re.sub(r"[’']", "['’]", text)

        def build_patterns(raw_key: str, tokens: list[str]):
            pattern_set = set()

            def add_variant(text: str):
                if not text:
                    return
                escaped = flex_apostrophes(re.escape(text))
                pattern_set.add(rf"\b{escaped}(?:['’]s)?\b")

            add_variant(raw_key)

            canonical = " ".join(tokens)
            if canonical and canonical != raw_key:
                add_variant(canonical)

            if tokens:
                joined_tokens = "[\\s_\\-]+".join(flex_apostrophes(re.escape(t)) for t in tokens)
                pattern_set.add(rf"\b{joined_tokens}(?:['’]s)?\b")
                collapsed = "".join(tokens)
                if collapsed:
                    add_variant(collapsed)

            return sorted(pattern_set)

        chars = {}
        variants = {}
        for file in img_dir.iterdir():
            if file.is_file() and file.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]:
                stem = file.stem.strip()
                if not stem:
                    continue
                raw_key = stem.lower()
                tokens = tokenize_name(stem)
                if not tokens and not raw_key:
                    continue

                canonical_key = " ".join(tokens)

                patterns = build_patterns(raw_key, tokens)
                primary_key = canonical_key or raw_key

                resolved_path = str(file.resolve())
                if primary_key:
                    chars[primary_key] = resolved_path
                    variants[primary_key] = list(patterns)

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
        self.pause_event.clear()
        self._update_pause_button(False)
        self._save_config()
        self._set_activity_status("Starting batch run...")
        self.running_thread = threading.Thread(target=self._run_generator, daemon=True)
        self.running_thread.start()

    def _skip_now(self):
        self.skip_event.set()

    def _stop(self):
        self.stop_event.set()
        self.pause_event.clear()
        self._update_pause_button(False)
        self.log("Stop requested, will halt after the current step.")
        self._set_activity_status("Stop requested. Finishing current step...")

    def _exit_app(self):
        self._save_config()

        def destroy_when_idle():
            if self.running_thread and self.running_thread.is_alive():
                self.root.after(150, destroy_when_idle)
                return
            self.root.destroy()

        if self.running_thread and self.running_thread.is_alive():
            self._stop()
            self.log("Exit requested. Closing after the current step.")
            self._set_activity_status("Exit requested. Shutting down after current step...")
            self.root.after(150, destroy_when_idle)
        else:
            self.root.destroy()

    def _update_pause_button(self, paused: bool):
        if hasattr(self, "pause_btn"):
            self.pause_btn.config(text="Resume wait" if paused else "Pause wait")

    def _toggle_pause(self):
        if not self.running_thread or not self.running_thread.is_alive():
            messagebox.showinfo("Not running", "Start generation before using pause.")
            return
        if self.pause_event.is_set():
            self.pause_event.clear()
            self._update_pause_button(False)
            self.log("Countdown resumed.")
            self._set_activity_status("Countdown resumed.")
        else:
            self.pause_event.set()
            self._update_pause_button(True)
            self.log("Countdown paused. Click 'Resume wait' to continue.")
            self._set_activity_status("App paused. Click 'Resume wait' to continue.")

    def _resolve_chrome_executable(self) -> str | None:
        env_path = os.environ.get("CHROME_PATH")
        if env_path and Path(env_path).exists():
            return str(Path(env_path))

        candidates = []
        if sys.platform == "win32":
            roots = [
                os.environ.get("PROGRAMFILES"),
                os.environ.get("PROGRAMFILES(X86)"),
                os.environ.get("LOCALAPPDATA"),
            ]
            for root in roots:
                if not root:
                    continue
                candidates.append(Path(root) / "Google/Chrome/Application/chrome.exe")
        else:
            candidates.extend(
                Path(p) for p in [
                    "/usr/bin/google-chrome",
                    "/usr/bin/chromium",
                    "/usr/bin/chromium-browser",
                    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                ]
            )

        for cand in candidates:
            if cand and cand.exists():
                return str(cand)

        for name in ["chrome", "google-chrome", "chromium", "chromium-browser"]:
            path = shutil.which(name)
            if path:
                return path
        return None

    def _launch_profile_browser(self):
        chrome_path = self._resolve_chrome_executable()
        if not chrome_path:
            messagebox.showerror(
                "Chrome not found",
                "Could not locate Chrome. Install it or set CHROME_PATH to the executable.",
            )
            return

        profile = Path(self.profile_dir.get()).expanduser()
        profile.mkdir(parents=True, exist_ok=True)
        target_url = self.primary_url.get().strip() or self.fallback_url.get().strip() or "https://chatgpt.com/?model=gpt-5"

        try:
            subprocess.Popen([chrome_path, f"--user-data-dir={profile}", target_url])
            self.log(f"Launched Chrome with profile {profile}")
        except Exception as e:
            messagebox.showerror("Launch failed", f"Could not launch Chrome: {e}")

    # config persistence
    def _save_config(self):
        self._cancel_pending_config_save()

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
        try:
            self.config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return True
        except OSError as exc:
            self.log(f"Failed to save settings: {exc}")
            return False

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

    def _setup_config_autosave(self):
        self._config_trace_ids: list[tuple[tk.Variable, str]] = []
        config_vars = [
            self.csv_path,
            self.char_json,
            self.variants_json,
            self.output_dir,
            self.profile_dir,
            self.preprompt,
            self.delay_sec,
            self.primary_url,
            self.fallback_url,
        ]

        for var in config_vars:
            try:
                trace_id = var.trace_add("write", self._on_config_var_change)
            except AttributeError:
                trace_id = var.trace("w", self._on_config_var_change)
            self._config_trace_ids.append((var, trace_id))

    def _on_config_var_change(self, *args):
        self._schedule_config_save()

    def _schedule_config_save(self):
        self._cancel_pending_config_save()
        self._save_after_id = self.root.after(600, self._perform_scheduled_save)

    def _perform_scheduled_save(self):
        self._save_after_id = None
        self._save_config()

    def _cancel_pending_config_save(self):
        if self._save_after_id is not None:
            try:
                self.root.after_cancel(self._save_after_id)
            except tk.TclError:
                pass
            finally:
                self._save_after_id = None

    def _save_settings_now(self):
        if self._save_config():
            self.log("Settings saved to generator_config.json.")
            self._set_activity_status("Settings saved.")
        else:
            messagebox.showerror("Save failed", "Could not save settings to generator_config.json.")

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

        def tokenize_for_patterns(stem: str):
            sanitized = re.sub(r"[^0-9A-Za-z'’_\-\s]", " ", stem)
            parts = [p for p in re.split(r"[\s_\-]+", sanitized) if p]
            if len(parts) == 1:
                part = parts[0]
                camel = re.findall(r"[A-Z]?[a-z0-9'’]+|[A-Z]+(?![a-z])", part)
                if len(camel) > 1:
                    parts = camel
            return [p.lower() for p in parts]

        def flex_apostrophes(text: str) -> str:
            return re.sub(r"[’']", "['’]", text)

        def default_patterns_for(name: str):
            raw_key = name.strip().lower()
            tokens = tokenize_for_patterns(name)
            pattern_set = set()

            def add_variant(text: str):
                if not text:
                    return
                escaped = flex_apostrophes(re.escape(text))
                pattern_set.add(rf"\b{escaped}(?:['’]s)?\b")

            add_variant(raw_key)

            canonical = " ".join(tokens)
            if canonical and canonical != raw_key:
                add_variant(canonical)

            if tokens:
                joined_tokens = "[\\s_\\-]+".join(flex_apostrophes(re.escape(t)) for t in tokens)
                pattern_set.add(rf"\b{joined_tokens}(?:['’]s)?\b")
                collapsed = "".join(tokens)
                if collapsed:
                    add_variant(collapsed)

            return sorted(pattern_set)

        def resolve_alias(alias: str):
            key = alias.strip().lower()
            if key in char_map:
                return key
            for name, pats in NAME_VARIANTS.items():
                target = name.strip().lower()
                if target in char_map:
                    for pattern in pats:
                        try:
                            if re.search(pattern, alias, flags=re.IGNORECASE):
                                return target
                        except re.error:
                            continue
            for raw_name in char_map.keys():
                target = str(raw_name).strip().lower()
                for pattern in default_patterns_for(raw_name):
                    try:
                        if re.search(pattern, alias, flags=re.IGNORECASE):
                            if target in char_map:
                                return target
                    except re.error:
                        continue
            return key

        def extract_characters(prompt_text, char_map):
            raw_tags = [m.group(1).strip() for m in TAG_PATTERN.finditer(prompt_text)]
            tags = []
            seen = set()
            for raw in raw_tags:
                resolved = resolve_alias(raw)
                if resolved and resolved not in seen:
                    tags.append(resolved)
                    seen.add(resolved)
            for name, pats in NAME_VARIANTS.items():
                key = name.strip().lower()
                if key in seen:
                    continue
                try:
                    for pattern in pats:
                        if re.search(pattern, prompt_text, flags=re.IGNORECASE):
                            tags.append(key)
                            seen.add(key)
                            break
                except re.error:
                    continue
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

        def ensure_composer_ready(page, *, timeout_ms=6000, allow_reload=True, allow_new_chat=True):
            try:
                return find_composer_any_frame(page, timeout_ms=timeout_ms)
            except Exception:
                pass
            if allow_new_chat and not in_conversation(page.url):
                for sel in SELECTORS["new_chat_buttons"]:
                    with contextlib.suppress(Exception):
                        el = page.locator(sel).first
                        if el.is_visible(timeout=1200):
                            el.click()
                            page.wait_for_load_state("domcontentloaded")
                            return find_composer_any_frame(page, timeout_ms=timeout_ms)
            if not allow_reload:
                raise TimeoutError("Composer not visible (reload skipped)")
            page.reload(wait_until="domcontentloaded", timeout=15000)
            dismiss_common_popups(page)
            return find_composer_any_frame(page, timeout_ms=max(timeout_ms, 8000))

        def looks_like_login(page):
            url = (page.url or "").lower()
            for token in ("login", "signin", "auth", "account"):
                if token in url and "logout" not in url:
                    return True
            text_clues = [
                "Log in",
                "Sign in",
                "Welcome back",
                "Continue with",
                "Use the ChatGPT app to continue",
                "Verify you are human",
                "human check",
            ]
            for clue in text_clues:
                with contextlib.suppress(Exception):
                    loc = page.get_by_text(clue, exact=False).first
                    if loc.is_visible(timeout=300):
                        return True
            selector_clues = [
                "input[type='email']",
                "input[type='password']",
                "button:has-text('Log in')",
                "button:has-text('Sign in')",
                "form[action*='login']",
                "iframe[src*='captcha']",
                "iframe[title*='captcha']",
            ]
            for sel in selector_clues:
                with contextlib.suppress(Exception):
                    loc = page.locator(sel).first
                    if loc.is_visible(timeout=300):
                        return True
            with contextlib.suppress(Exception):
                for frame in page.frames:
                    if frame is page:
                        continue
                    f_url = (frame.url or "").lower()
                    if "captcha" in f_url or "auth" in f_url:
                        return True
            return False

        def goto_with_fallback(page):
            urls = [PRIMARY_URL, FALLBACK_URL]
            for attempt, url in enumerate(urls, start=1):
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=15000)
                except PWTimeout:
                    log(f"Navigation to {url} hit timeout, continuing (attempt {attempt}).")
                except Exception as e:
                    log(f"Navigation to {url} failed, {e}")
                    continue
                dismiss_common_popups(page)
                if looks_like_login(page):
                    return None, True
                try:
                    comp = ensure_composer_ready(page, timeout_ms=2500, allow_reload=False)
                    if comp:
                        return comp, False
                except Exception:
                    pass
            return None, False

        # do work
        try:
            prompts = load_prompts(CSV_PATH)
            if not prompts:
                log("No prompts found, check file")
                self._set_activity_status("No prompts found. Update your file and try again.")
                return
            total_prompts = len(prompts)
            plural = "s" if total_prompts != 1 else ""
            self._set_activity_status(f"Loaded {total_prompts} prompt{plural}.")
            char_map = load_char_map(CHAR_MAP_JSON)
            Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
            Path(PROFILE_DIR).mkdir(parents=True, exist_ok=True)

            self._set_activity_status("Launching browser session...")
            with sync_playwright() as p:
                ctx = p.chromium.launch_persistent_context(
                    user_data_dir=PROFILE_DIR,
                    headless=False,
                    channel="chrome",
                    viewport={"width": 1340, "height": 900},
                    accept_downloads=True,
                )
                page = ctx.new_page()
                self._set_activity_status("Checking chat composer...")
                composer, login_needed = goto_with_fallback(page)
                needs_user_action = login_needed or composer is None

                if needs_user_action:
                    self._set_activity_status("Awaiting manual login...")
                    log("If you see a login or human check, finish it in Chrome, open a chat, then return here and click OK.")
                    if not messagebox.askokcancel("Login check", "Finish login if needed, then click OK to start."):
                        log("Canceled by user.")
                        self._set_activity_status("Login canceled. Batch stopped.")
                        return
                    with contextlib.suppress(Exception):
                        page.wait_for_load_state("domcontentloaded", timeout=15000)
                    dismiss_common_popups(page)
                    composer = None
                    self._set_activity_status("Resuming automated run...")
                else:
                    log("Chat composer detected immediately; starting batch run.")

                try:
                    composer = composer or ensure_composer_ready(page)
                    self._set_activity_status("Chat composer ready. Starting prompts...")
                except Exception:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    snap = Path(OUTPUT_DIR) / f"debug_no_composer_{ts}.png"
                    with contextlib.suppress(Exception):
                        page.screenshot(path=str(snap), full_page=True)
                    log(f"Composer not found, saved snapshot to {snap}")
                    self._set_activity_status("Composer not found. See saved snapshot for details.")
                    return

                stopped = False
                for idx, item in enumerate(prompts, start=1):
                    if self.stop_event.is_set():
                        log("Stop requested, exiting loop.")
                        self._set_activity_status("Stop requested. Finishing current step...")
                        stopped = True
                        break

                    self._set_activity_status(f"Sending prompt {idx}/{total_prompts}...")
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
                    mins, secs = divmod(remaining, 60)
                    self._set_activity_status(f"Countdown: {mins:02d}:{secs:02d} remaining")
                    was_paused = False
                    while remaining > 0 and not self.skip_event.is_set() and not self.stop_event.is_set():
                        if self.pause_event.is_set():
                            if not was_paused:
                                was_paused = True
                                self._set_activity_status("App paused. Click 'Resume wait' to continue.")
                            time.sleep(0.5)
                            continue
                        if was_paused:
                            was_paused = False
                            mins, secs = divmod(remaining, 60)
                            self._set_activity_status(f"Countdown: {mins:02d}:{secs:02d} remaining")
                        if remaining % 10 == 0 or remaining == 1:
                            mins, secs = divmod(remaining, 60)
                            msg = f"Time left: {mins:02d}:{secs:02d}"
                            log(msg)
                            self._set_activity_status(f"Countdown: {mins:02d}:{secs:02d} remaining")
                        time.sleep(1)
                        remaining -= 1

                    self.pause_event.clear()
                    self._update_pause_button(False)

                    if self.skip_event.is_set():
                        log(">> Skip pressed, continuing")
                        self._set_activity_status("Skip pressed. Continuing to next prompt...")
                    elif self.stop_event.is_set():
                        log(">> Stop requested, halting after current step")
                        self._set_activity_status("Stop requested. Finishing current step...")
                        stopped = True
                        break
                    else:
                        log(">> Wait finished, continuing")
                        self._set_activity_status("Wait finished. Continuing...")

                if stopped:
                    log("Batch stopped by user.")
                    self._set_activity_status("Batch stopped. Ready when you are.")
                else:
                    log("All prompts processed.")
                    self._set_activity_status("All prompts processed.")
        except Exception as e:
            log(f"Fatal error, {e}")
            self._set_activity_status(f"Fatal error: {e}")
        finally:
            self.pause_event.clear()
            self._update_pause_button(False)

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
