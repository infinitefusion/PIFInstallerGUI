import tkinter as tk
from pathlib import Path
from tkinter import filedialog, scrolledtext
import os
import subprocess
import threading
import webbrowser

from config import load_config, save_config
from installer import run_install

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

DEFAULT_PATH = Path("~") / "Downloads" / "InfiniteFusion"

THEMES = {
    "kanto": {
        "accent":        "#ff4444",
        "accent2":       "#8b1a1a",
        "text":          "#ffe8e8",
        "subtext":       "#cc9999",
        "log_bg":        "#100505",
        "log_fg":        "#ff9999",
        "install_bg":    "#cc2222",
        "install_hover": "#ff4444",
        "panel_bg":      "#1a0808",
    },
    "hoenn": {
        "accent":        "#00b4d8",
        "accent2":       "#0077b6",
        "text":          "#caf0f8",
        "subtext":       "#90e0ef",
        "log_bg":        "#050d15",
        "log_fg":        "#48cae4",
        "install_bg":    "#0096c7",
        "install_hover": "#00b4d8",
        "panel_bg":      "#050d15",
    },
}

TITLES = {
    "kanto": ("POKÉMON INFINITE FUSION 1", "KANTO"),
    "hoenn": ("POKÉMON INFINITE FUSION 2", "HOENN"),
}

# (icon filename stem, label, url)
SOCIAL_LINKS = [
    ("discord",  "Discord",  "https://discord.gg/infinitefusion"),
    ("wiki",     "Wiki",     "https://infinitefusion.fandom.com/wiki/Pok%C3%A9mon_Infinite_Fusion_Wiki"),
    ("youtube",  "YouTube",  "https://www.youtube.com/@PokemonInfiniteFusion_Official"),
    ("github",   "GitHub",   "https://github.com/infinitefusion/PIFInstallerGUI"),
    ("linktree", "Linktree", "https://linktr.ee/chardub513"),
]

POWER_CLEAR_AVAILABLE = False #Todo

ICON_SIZE       = 24          # px — icons are resized to this square
SOCIAL_BAR_H    = 44          # px — height of the bar
_PC = "Power Clear" if POWER_CLEAR_AVAILABLE else "Georgia"

FONT_BTN     = (_PC, 12, "bold")
FONT_INSTALL = (_PC, 14, "bold")
FONT_LOG     = ("Consolas", 9)          # keep monospace for logs
FONT_LABEL   = (_PC, 8, "bold")
FONT_SOCIAL  = (_PC, 10, "bold")
BTN_W, BTN_H    = 256, 199


# ── PIL helpers ───────────────────────────────────────────────────────────────

def _hex_to_rgb(hex_color):
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

def pil_load_native(path, bg_color="#000000"):
    if not PIL_AVAILABLE:
        return None, 0, 0
    try:
        img = Image.open(path).convert("RGBA")
        bg = Image.new("RGBA", img.size, (*_hex_to_rgb(bg_color), 255))
        bg.paste(img, mask=img.split()[3])
        photo = ImageTk.PhotoImage(bg.convert("RGB"))
        return photo, img.width, img.height
    except Exception:
        return None, 0, 0

def pil_load_exact(path, w, h):
    if not PIL_AVAILABLE or w < 1 or h < 1:
        return None
    try:
        img = Image.open(path).convert("RGBA").resize((w, h), Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None

def pil_load_icon(path, size, bg_color="#000000"):
    """Load a PNG icon, resize to `size`×`size`, composite onto bg_color, return PhotoImage."""
    if not PIL_AVAILABLE:
        return None
    try:
        img = Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
        bg = Image.new("RGBA", (size, size), (*_hex_to_rgb(bg_color), 255))
        bg.paste(img, mask=img.split()[3])
        return ImageTk.PhotoImage(bg.convert("RGB"))
    except Exception:
        return None


# ── ImageButton ───────────────────────────────────────────────────────────────

class ImageButton(tk.Canvas):
    def __init__(self, parent, command, fallback_text="", **kwargs):
        super().__init__(parent, width=BTN_W, height=BTN_H,
                         highlightthickness=0, bd=0, cursor="hand2", **kwargs)
        self._command    = command
        self._fallback   = fallback_text
        self._img_ref    = None
        self._img_normal = None
        self._img_sel    = None
        self._selected   = False        # ← track state
        self._bg_color   = "#000000"    # ← remember bg for re-render

        self.bind("<Button-1>",        lambda _: self.configure(highlightthickness=2,
                                                                highlightbackground="#ffffff"))
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", lambda _: self._redraw(True))
        self.bind("<Leave>", lambda _: self._redraw(self._selected))

    def set_paths(self, normal_path, selected_path):
        self._img_normal = normal_path
        self._img_sel    = selected_path

    def refresh(self, bg_color, selected: bool):
        self._bg_color = bg_color
        self._selected = selected
        self._redraw(selected)

    def _redraw(self, use_sel: bool):
        self.configure(bg=self._bg_color)
        self.delete("all")
        path = (self._img_sel if use_sel else self._img_normal) or ""
        if path and os.path.isfile(path):
            img, w, h = pil_load_native(path, self._bg_color)
            if img:
                self._img_ref = img
                self.configure(width=w, height=h)
                self.create_image(0, 0, anchor="nw", image=img)
                return
        self._img_ref = None
        self.configure(width=BTN_W, height=BTN_H)
        self.create_text(BTN_W // 2, BTN_H // 2, text=self._fallback,
                         fill="#ffffff", font=FONT_BTN, justify="center")

    def _on_release(self, _):
        self.configure(highlightthickness=0)
        self._command()


# ── SocialButton ──────────────────────────────────────────────────────────────

class SocialButton(tk.Frame):
    """Icon + label button for the social bar. Falls back to text-only if PIL unavailable."""

    def __init__(self, parent, icon_path, label, url, bg, icon_size=ICON_SIZE, **kwargs):
        super().__init__(parent, bg=bg, cursor="hand2", **kwargs)
        self._url       = url
        self._bg        = bg
        self._icon_ref  = None          # keep reference so GC doesn't collect it

        # Try to load icon image
        icon_photo = pil_load_icon(icon_path, icon_size, bg)

        if icon_photo:
            self._icon_ref = icon_photo
            self.icon_lbl = tk.Label(self, image=icon_photo, bg=bg, cursor="hand2")
            self.icon_lbl.pack(side="left", padx=(6, 3))
        else:
            # No image — just a placeholder space so layout stays consistent
            tk.Label(self, text="•", bg=bg, fg="#888888",
                     font=FONT_SOCIAL, cursor="hand2").pack(side="left", padx=(6, 3))

        self.text_lbl = tk.Label(self, text=label, bg=bg, fg="#aaaaaa",
                                  font=FONT_SOCIAL, cursor="hand2")
        self.text_lbl.pack(side="left", padx=(0, 6))

        # Bind clicks and hover to frame + both child labels
        # Bind clicks + hover to all parts
        for widget in (self, self.text_lbl) + ((self.icon_lbl,) if icon_photo else ()):
            widget.bind("<Button-1>", self._on_click)
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)

    def _on_click(self, _):
        webbrowser.open(self._url)

    def set_accent(self, color: str):
        """Update hover accent color (called when theme changes)."""
        self._accent = color

    def _on_enter(self, _):
        accent = getattr(self, "_accent", "#00b4d8")
        self.text_lbl.configure(fg=accent)

    def _on_leave(self, _):
        self.text_lbl.configure(fg="#aaaaaa")


# ── Main app ──────────────────────────────────────────────────────────────────

class InstallerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Pokémon Infinite Fusion — Launcher")
        self.geometry("800x580")
        self.minsize(900, 720)
        self.resizable(True, True)
        self.configure(bg="#000000")

        self._theme_name   = "hoenn"
        self._theme        = THEMES["hoenn"]
        self._bg_ref       = None
        self._log_visible  = False
        self._status_text  = ""
        self._install_path = None
        self._res          = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")
        self._icons_dir    = os.path.join(self._res, "icons")

        self._build_ui()
        self._apply_theme("hoenn")
        self.after(100, self._show_persistent_buttons)
        self.after(50, lambda: self._load_logo("hoenn"))



    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        t = self._theme

        # Background canvas
        self.canvas_bg = tk.Canvas(self, highlightthickness=0, bd=0)
        self.canvas_bg.place(relx=0, rely=0, relwidth=1, relheight=1)
        tk.Widget.lower(self.canvas_bg)
        self.bind("<Configure>", lambda e: self._load_bg(self._theme_name)
                  if e.widget is self else None)

        # Game select buttons
        self.btn_kanto = ImageButton(self, command=lambda: self._select_game("kanto"),
                                     fallback_text="Infinite Fusion 1\nKanto", bg=t["panel_bg"])
        self.btn_kanto.set_paths(os.path.join(self._res, "btn_kanto.png"),
                                 os.path.join(self._res, "btn_kanto_sel.png"))
        self.btn_kanto.place(relx=0.5, rely=0.44, anchor="center", x=-150, y=-60)

        self.btn_hoenn = ImageButton(self, command=lambda: self._select_game("hoenn"),
                                     fallback_text="Infinite Fusion 2\nHoenn", bg=t["panel_bg"])
        self.btn_hoenn.set_paths(os.path.join(self._res, "btn_hoenn.png"),
                                 os.path.join(self._res, "btn_hoenn_sel.png"))
        self.btn_hoenn.place(relx=0.5, rely=0.44, anchor="center", x=150, y=-60)

        # Install location row
        self.loc_row = tk.Frame(self, bg="#08111d", bd=0,
                                highlightthickness=2,
                                highlightbackground=t["accent2"])
        self.loc_row.place(relx=0.05, rely=0.58, relwidth=0.90, anchor="w", height=48)

        cfg = load_config()
        saved_path = cfg.get(f"last_install_path_{self._theme_name}", str(DEFAULT_PATH.expanduser()))
        self.path_var = tk.StringVar(value=saved_path)
        self.path_var.trace_add("write", lambda *_: self.after(200, self._refresh_install_btn))

        self.path_entry = tk.Entry(self.loc_row, textvariable=self.path_var,
                                   font=("Consolas", 12),
                                   bg="#06101a", fg="#ffffff",
                                   insertbackground="#ffffff",
                                   relief="flat", bd=0, highlightthickness=0)
        self.path_entry.pack(side="left", fill="both", expand=True, padx=(14, 10), pady=10)

        # BROWSE
        self.browse_btn = tk.Label(
            self.loc_row, text="BROWSE",
            font=("Arial", 10, "bold"),
            bg="#1a3a5c", fg="#ffffff",
            cursor="hand2", padx=18, pady=6)
        self.browse_btn.pack(side="right", padx=8, pady=6)
        self.browse_btn.bind("<Button-1>", lambda _: self._browse())

        # LAUNCH GAME
        self.launch_btn = ImageButton(self, command=self._launch_game,
                                      fallback_text="LAUNCH GAME", bg=t["panel_bg"])
        self.launch_btn.set_paths(
            os.path.join(self._res, "buttons", "actionBtn_launch.png"),
            os.path.join(self._res, "buttons", "actionBtn_launch_sel.png"))

        # INSTALL
        self.install_btn = ImageButton(self, command=self._start_install,
                                       fallback_text="", bg=t["panel_bg"])
        self.install_btn.set_paths(
            os.path.join(self._res, "buttons", "actionBtn_install.png"),
            os.path.join(self._res, "buttons", "actionBtn_install_sel.png"))

        # UPDATE
        self.update_btn = ImageButton(self, command=self._start_install,
                                      fallback_text="", bg=t["panel_bg"])
        self.update_btn.set_paths(
            os.path.join(self._res, "buttons", "actionBtn_update.png"),
            os.path.join(self._res, "buttons", "actionBtn_update_sel.png"))

        # BACK TO MAIN MENU
        self.back_btn = ImageButton(self, command=self._show_main_screen,
                                    fallback_text="← MAIN MENU", bg=t["panel_bg"])
        self.back_btn.set_paths(
            os.path.join(self._res, "buttons", "actionBtn_back.png"),
            os.path.join(self._res, "buttons", "actionBtn_back_sel.png"))

        # TRY AGAIN
        self.retry_btn = ImageButton(self, command=self._retry_install,
                                     fallback_text="TRY AGAIN", bg=t["panel_bg"])
        self.retry_btn.set_paths(
            os.path.join(self._res, "buttons", "actionBtn_retry.png"),
            os.path.join(self._res, "buttons", "actionBtn_retry_sel.png"))

        # Status label (hidden until install)
        self.status_label = tk.Label(
            self, text="Installing the game...  This may take a few minutes.",
            font=("Georgia", 32),
            fg="#d7f4ff", bg=t["panel_bg"],
            wraplength=640, justify="center")

        # Log (hidden until install)
        self.log_box = scrolledtext.ScrolledText(
            self, font=FONT_LOG,
            bg=t["log_bg"], fg=t["log_fg"],
            insertbackground=t["log_fg"],
            relief="flat", bd=0,
            highlightthickness=2,
            highlightbackground=t["accent2"],
            wrap="word", state="disabled")

        # OPEN FOLDER
        self.open_folder_btn = ImageButton(self, command=self._open_install_folder,
                                           fallback_text="OPEN THE GAME'S FOLDER", bg=t["panel_bg"])
        self.open_folder_btn.set_paths(
            os.path.join(self._res, "buttons", "actionBtn_open_folder.png"),
            os.path.join(self._res, "buttons", "actionBtn_open_folder_sel.png"))

        # Social links bar
        self._build_social_bar()

    def _build_social_bar(self):
        """Pinned-to-bottom row of icon+label social link buttons."""
        self.social_bar = tk.Frame(self, bg="#000000", bd=0)
        self.social_bar.place(relx=0, rely=1.0, relwidth=1.0, anchor="sw", height=SOCIAL_BAR_H)

        # Thin separator line at the top of the bar
        sep = tk.Frame(self.social_bar, bg="#222222", height=1)
        sep.pack(side="top", fill="x")

        inner = tk.Frame(self.social_bar, bg="#000000")
        inner.pack(side="top", fill="both", expand=True)

        self._social_btns = []
        for stem, label, url in SOCIAL_LINKS:
            icon_path = os.path.join(self._icons_dir, f"{stem}.png")
            btn = SocialButton(inner, icon_path=icon_path, label=label, url=url, bg="#000000")
            btn.pack(side="left", padx=2, pady=4)
            btn.set_accent(self._theme["accent"])
            self._social_btns.append(btn)

    # ── Theme ─────────────────────────────────────────────────────────────────

    def _apply_theme(self, name: str):
        t = THEMES[name]
        self._theme_name = name
        self._theme      = t

        self._load_bg(name)
        self._load_logo(name)
        self.btn_kanto.refresh(t["panel_bg"], name == "kanto")
        self.btn_hoenn.refresh(t["panel_bg"], name == "hoenn")

        self.loc_row.configure(highlightbackground=t["accent2"])
        self.path_entry.configure(fg=t["text"], insertbackground=t["accent"])
        self.browse_btn.configure(activebackground=t["accent"])
        self.browse_btn.configure(fg="#ffffff")
        self.log_box.configure(bg=t["log_bg"], fg=t["log_fg"],
                               insertbackground=t["log_fg"],
                               highlightbackground=t["accent2"])
        self.install_btn.refresh(t["panel_bg"], selected=False)
        self.launch_btn.refresh(t["panel_bg"], selected=False)
        self.open_folder_btn.refresh(t["panel_bg"], selected=False)
        self.install_btn.refresh(t["panel_bg"], selected=False)
        self.update_btn.refresh(t["panel_bg"], selected=False)
        self.back_btn.refresh(t["panel_bg"], selected=False)
        self.retry_btn.refresh(t["panel_bg"], selected=False)


        # Update accent color on social buttons so hover matches theme
        for btn in getattr(self, "_social_btns", []):
            btn.set_accent(t["accent"])

    def _load_bg(self, name: str):
        self.canvas_bg.delete("bg")
        w = self.winfo_width() or 720
        h = self.winfo_height() or 580
        fname = {"kanto": "bg_kanto.png", "hoenn": "bg_hoenn.png"}.get(name, "")
        if fname:
            img = pil_load_exact(os.path.join(self._res, fname), w, h)
            if img:
                self._bg_ref = img
                self.canvas_bg.create_image(0, 0, anchor="nw", image=img, tags="bg")
                self.canvas_bg.tag_lower("bg")
                return
        self._bg_ref = None
        self.canvas_bg.configure(bg=self._theme["log_bg"])

    def _load_logo(self, name: str):
        self.canvas_bg.delete("logo")
        main, sub = TITLES.get(name, ("POKÉMON INFINITE FUSION", ""))
        w = max(self.winfo_width(), 720)
        cx = w // 2
        t = self._theme

        def outlined(x, y, text, font, fill, size=2):
            for dx in (-size, 0, size):
                for dy in (-size, 0, size):
                    if dx or dy:
                        self.canvas_bg.create_text(x + dx, y + dy, text=text,
                                                   font=font, fill="#000000",
                                                   anchor="n", tags="logo")
            self.canvas_bg.create_text(x, y, text=text, font=font, fill=fill,
                                       anchor="n", tags="logo")

        outlined(cx, 18, main, ("Arial", 36, "bold"), "#ffffff")
        outlined(cx, 62, sub, ("Impact", 48, "bold"), t["accent"], size=4)

        if not self._log_visible:
            outlined(cx, 364, "Install location: ", ("Arial", 16, "bold"), "#d7f4ff")
        elif self._status_text:
            self._draw_status_text(self._status_text)

    def _show_persistent_buttons(self):
        from installer import GAMES, is_existing_folder
        game = GAMES[self._theme_name]
        path = self._resolve_install_path(self.path_var.get().strip())
        if is_existing_folder(path, game):
            self.launch_btn.place(relx=0.5, rely=0.64, anchor="n")
            self.open_folder_btn.place(relx=0.5, rely=0.78, anchor="n")
            self.update_btn.place(relx=0.5, rely=0.86, anchor="n")
            self.install_btn.place_forget()
        else:
            self.launch_btn.place_forget()
            self.open_folder_btn.place_forget()
            self.update_btn.place_forget()
            self.install_btn.place(relx=0.5, rely=0.70, anchor="n")

    # ── Interaction ───────────────────────────────────────────────────────────
    def _select_game(self, game: str):
        self._apply_theme(game)
        cfg = load_config()
        self.path_var.set(cfg.get(f"last_install_path_{game}", str(DEFAULT_PATH.expanduser())))
        self._show_persistent_buttons()
        self._refresh_install_btn()

    def _browse(self):
        folder = filedialog.askdirectory(title="Select install folder",
                                         initialdir=self.path_var.get())
        if folder:
            self.path_var.set(folder)
            self._log(f"Install path set to: {folder}")
            self._refresh_install_btn()

    def _refresh_install_btn(self):
        self._show_persistent_buttons()

    def _log(self, msg: str, replace_last=False):
        self.log_box.configure(state="normal")
        if replace_last:
            try:
                self.log_box.delete("end-2l linestart", "end-1l")
            except tk.TclError:
                pass
        self.log_box.insert("end", f"» {msg}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _open_install_folder(self):
        raw_path = self.path_var.get().strip()
        if not raw_path:
            self._log("No path specified.")
            return
        resolved_path = self._resolve_install_path(raw_path)
        if not os.path.isdir(resolved_path):
            self._log(f"Folder does not exist: {resolved_path}")
            return
        import sys
        path_str = str(resolved_path)
        if sys.platform == "win32":
            os.startfile(path_str)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path_str])
        else:
            subprocess.Popen(["xdg-open", path_str])

    def _game_folder_name(self) -> str:
        from installer import GAMES
        return GAMES[self._theme_name]["folder"]

    def _resolve_install_path(self, base: str) -> Path:
        from pathlib import Path
        path = Path(base)
        if path.name != self._game_folder_name():
            path = path / self._game_folder_name()
        return path

    def _launch_game(self):
        from installer import GAMES
        exe_name = GAMES[self._theme_name].get("exe", "Game.exe")
        exe_path = self._resolve_install_path(self.path_var.get().strip()) / exe_name
        if not exe_path.is_file():
            self._log(f"Could not find {exe_name} in the game folder.")
            return
        import sys
        if sys.platform == "win32":
            os.startfile(exe_path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(exe_path)])
        else:
            subprocess.Popen([str(exe_path)])

    def _show_main_screen(self):
        self._log_visible = False
        self.back_btn.place_forget()
        self.launch_btn.place_forget()
        self.open_folder_btn.place_forget()
        self.update_btn.place_forget()
        self.retry_btn.place_forget()
        self.log_box.place_forget()
        self._clear_status_text()
        self.btn_kanto.place(relx=0.5, rely=0.44, anchor="center", x=-150, y=-60)
        self.btn_hoenn.place(relx=0.5, rely=0.44, anchor="center", x=150, y=-60)
        self.loc_row.place(relx=0.05, rely=0.58, relwidth=0.90, anchor="w", height=48)
        self.social_bar.place(relx=0, rely=1.0, relwidth=1.0, anchor="sw", height=SOCIAL_BAR_H)
        self._load_logo(self._theme_name)
        self._show_persistent_buttons()
        self._apply_theme(self._theme_name)

        self.update_idletasks()
        # Force redraw of widgets that sometimes appear grey
        self.btn_kanto.refresh(self._theme["panel_bg"], self._theme_name == "kanto")
        self.btn_hoenn.refresh(self._theme["panel_bg"], self._theme_name == "hoenn")

        for btn in self._social_btns:
            btn._on_leave(None)

        self.browse_btn.configure(
            bg="#1a3a5c",
            fg="#ffffff"
        )

    def _start_install(self):
        path = self.path_var.get().strip()
        if not path:
            self._show_log_panel()
            self._log("Please set an install location.")
            return

        self._install_path = path

        # Hide picker UI and social bar, show full-height log
        for w in (self.btn_kanto, self.btn_hoenn, self.loc_row,
                  self.install_btn, self.launch_btn, self.open_folder_btn, self.update_btn):
            w.place_forget()
        self.social_bar.place_forget()
        self._load_logo(self._theme_name)
        self._show_log_panel()

        save_config({f"last_install_path_{self._theme_name}": str(self._resolve_install_path(path))})

        self._log(f"Starting install to: {path}")

        def log_fn(msg, replace_last=False):
            self.after(0, lambda: self._log(msg, replace_last))

        def done_fn(success, msg):
            def finish():
                self._log(msg)
                self._draw_status_text(msg)
                if success:
                    folder = self._game_folder_name()
                    self._install_path = (
                        os.path.join(path, folder) if os.path.basename(path) != folder else path
                    )
                    self.back_btn.place(relx=0.5, rely=0.88, anchor="n")
                else:
                    # On failure: show Try Again + Back, hide everything else
                    self.install_btn.place_forget()
                    self.launch_btn.place_forget()
                    self.open_folder_btn.place_forget()
                    self.update_btn.place_forget()
                    self.retry_btn.place(relx=0.5, rely=0.80, anchor="n")
                    self.back_btn.place(relx=0.5, rely=0.88, anchor="n")
            self.after(0, finish)

        threading.Thread(target=run_install,
                         args=(self._theme_name, path, log_fn, done_fn),
                         daemon=True).start()

    def _retry_install(self):
        """Re-run the install using the current path, without returning to main screen."""
        self.retry_btn.place_forget()
        self.back_btn.place_forget()
        self.retry_btn.place_forget()
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self._start_install()

    def _show_log_panel(self):
        if self._log_visible:
            return
        self._log_visible = True
        self.geometry("800x580")
        self.minsize(900, 720)
        self._draw_status_text("Installing…  This will probably take a few minutes.\nPlease be patient.")
        self.log_box.place(relx=0.04, rely=0.36, relwidth=0.92, anchor="nw", height=300)

    def _draw_status_text(self, text: str):
        self._status_text = text
        self.canvas_bg.delete("status")
        w = max(self.winfo_width(), 720)
        def outlined(x, y, text, font, fill, size=2):
            for dx in (-size, 0, size):
                for dy in (-size, 0, size):
                    if dx or dy:
                        self.canvas_bg.create_text(x+dx, y+dy, text=text,
                                                   font=font, fill="#000000",
                                                   anchor="n", tags="status")
            self.canvas_bg.create_text(x, y, text=text, font=font, fill=fill,
                                       anchor="n", tags="status")
        outlined(w // 2, 136, text, ("Georgia", 24), "#ffffff")

    def _clear_status_text(self):
        self._status_text = ""
        self.canvas_bg.delete("status")


if __name__ == "__main__":
    InstallerApp().mainloop()