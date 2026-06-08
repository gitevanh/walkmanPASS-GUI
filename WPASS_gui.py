"""
WPASS_gui.py — Walkman Playlist Assistant Super Script, GUI Edition
====================================================================
Generates M3U8 playlists for Sony Walkman devices from a local music
library, and optionally syncs audio files between two directories.

Usage:
    python WPASS_gui.py          # Run directly
    pyinstaller WPASS_gui.spec   # Build standalone executable

Requirements:
    pip install mutagen
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from mutagen.asf import ASF
from mutagen.easymp4 import EasyMP4
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE
import mutagen

# ── Constants ─────────────────────────────────────────────────────────────────

AUDIO_LOADERS = {
    '.mp3':  MP3,
    '.flac': FLAC,
    '.wav':  WAVE,
    '.m4a':  EasyMP4,
    '.wma':  ASF,
    '.ogg':  OggVorbis,
    '.aac':  mutagen.File,
}
AUDIO_EXTENSIONS = tuple(AUDIO_LOADERS.keys())

# Classic Windows 95/98 colour palette
BG       = '#c0c0c0'   # Silver
BG_LIGHT = '#d4d0c8'   # Highlight
FG       = '#000000'   # Black
NAVY     = '#000080'   # Accent / active title
WHITE    = '#ffffff'
GRAY     = '#808080'   # Disabled / dim

FONT      = ('Courier New', 9)
FONT_BOLD = ('Courier New', 9, 'bold')

_CONFIG_PATH = Path.home() / '.wpass_gui.json'

# ── Config persistence ────────────────────────────────────────────────────────

def load_config():
    """Load saved path preferences from the user's home directory."""
    try:
        if _CONFIG_PATH.exists():
            return json.loads(_CONFIG_PATH.read_text('utf-8'))
    except Exception:
        pass
    return {}


def save_config(data):
    """Persist path preferences to the user's home directory."""
    try:
        _CONFIG_PATH.write_text(json.dumps(data, indent=2), 'utf-8')
    except Exception:
        pass

# ── Tooltip ───────────────────────────────────────────────────────────────────

class ToolTip:
    """Lightweight Win95-style tooltip shown on widget hover."""

    def __init__(self, widget, text):
        self._tip = None
        widget.bind('<Enter>', lambda e: self._show(widget, text))
        widget.bind('<Leave>', lambda e: self._hide())

    def _show(self, widget, text):
        x = widget.winfo_rootx() + 20
        y = widget.winfo_rooty() + widget.winfo_height() + 2
        self._tip = tk.Toplevel(widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f'+{x}+{y}')
        tk.Label(self._tip, text=text, bg='#ffffe1', fg=FG,
                 font=FONT, relief='solid', bd=1, padx=4, pady=2).pack()

    def _hide(self):
        if self._tip:
            self._tip.destroy()
            self._tip = None

# ── Utilities ─────────────────────────────────────────────────────────────────

def open_folder(path):
    """Open a directory in the platform's default file manager."""
    if sys.platform == 'win32':
        os.startfile(path)
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', path])
    else:
        subprocess.Popen(['xdg-open', path])

# ── Audio metadata ────────────────────────────────────────────────────────────

def get_audio_metadata(file_path):
    """
    Extract duration, artist, and title from an audio file via mutagen.

    Falls back to 'Unknown Artist' and the filename stem when tags are absent,
    and attempts an 'Artist - Title' stem split as a last resort.

    Returns (duration_seconds, artist, title), or (None, None, None) on failure.
    """
    try:
        loader = AUDIO_LOADERS.get(file_path.suffix.lower())
        if not loader:
            return None, None, None

        audio = loader(str(file_path))
        if audio is None or not hasattr(audio, 'info'):
            return None, None, None

        duration = int(audio.info.length)
        artist   = 'Unknown Artist'
        title    = file_path.stem

        if audio.tags:
            try:
                if isinstance(audio, (FLAC, OggVorbis)):
                    artist = audio.tags.get('artist', [artist])[0]
                    title  = audio.tags.get('title',  [title])[0]
                elif isinstance(audio, EasyMP4):
                    # EasyMP4 uses simplified keys — NOT raw MP4 atoms like ©ART
                    artist = audio.tags.get('artist', [artist])[0]
                    title  = audio.tags.get('title',  [title])[0]
                elif isinstance(audio, ASF):
                    # ASF/WMA exposes 'Author' and 'Title', not ID3 frame names
                    a = audio.tags.get('Author')
                    t = audio.tags.get('Title')
                    if a: artist = str(a[0])
                    if t: title  = str(t[0])
                else:
                    # MP3 and WAV — ID3
                    tpe1 = audio.tags.get('TPE1')
                    tit2 = audio.tags.get('TIT2')
                    if tpe1: artist = str(tpe1[0])
                    if tit2: title  = str(tit2[0])
            except Exception:
                pass

        # Last-resort filename split: "Artist - Title"
        if artist == 'Unknown Artist' and ' - ' in title:
            parts = title.split(' - ', 1)
            if len(parts) == 2:
                artist, title = parts

        return duration, str(artist), str(title)

    except Exception as exc:
        print(f'[WPASS] Metadata error — {file_path.name}: {exc}')
        return None, None, None

# ── Playlist logic ────────────────────────────────────────────────────────────

def _normalize_path(file_path, playlist_path):
    """Return a forward-slash relative path from the playlist to the audio file."""
    return os.path.relpath(file_path, Path(playlist_path).parent).replace('\\', '/')


def _scan_files(directory, recursive=True):
    """Return a sorted list of all supported audio files under directory."""
    glob = Path(directory).rglob('*') if recursive else Path(directory).glob('*')
    return sorted(f for f in glob if f.suffix.lower() in AUDIO_EXTENSIONS)


def _write_playlist_entries(f_obj, files, playlist_path, exclude_instr,
                             progress_cb=None, offset=0, total=0):
    """
    Write EXTINF entries to an already-open playlist file.

    Args:
        f_obj:         Open file handle in write mode.
        files:         Ordered list of audio Paths to process.
        playlist_path: Path of the playlist being written.
        exclude_instr: Skip tracks whose title matches 'instrumental' or 'karaoke'.
        progress_cb:   Optional callable(current, total) for progress updates.
        offset:        File index offset for multi-folder progress reporting.
        total:         Global file total for accurate progress reporting.

    Returns:
        Number of EXTINF entries written.
    """
    n       = total or len(files)
    written = 0
    for i, fp in enumerate(files):
        duration, artist, title = get_audio_metadata(fp)
        if progress_cb:
            progress_cb(offset + i + 1, n)
        if duration is None:
            continue
        if exclude_instr and re.search(r'(instrumental|karaoke)', title, re.IGNORECASE):
            continue
        f_obj.write(f'#EXTINF:{duration},{artist} - {title}\n')
        f_obj.write(f'{_normalize_path(fp, playlist_path)}\n')
        written += 1
    return written


def generate_single_playlist(input_dir, playlist_path, exclude_instr, progress_cb=None):
    """
    Recursively scan input_dir and write a single M3U8 playlist.
    Returns (tracks_written, tracks_scanned).
    """
    files = _scan_files(input_dir)
    with open(playlist_path, 'w', encoding='utf-8') as f:
        f.write('#EXTM3U\n')
        written = _write_playlist_entries(
            f, files, Path(playlist_path), exclude_instr,
            progress_cb, offset=0, total=len(files))
    return written, len(files)


def generate_playlists_per_folder(root_dir, output_dir, exclude_instr, progress_cb=None):
    """
    Create one M3U8 per direct subfolder of root_dir, written to output_dir.

    Files are pre-scanned across all folders before writing begins so the
    progress bar moves at a consistent rate regardless of folder sizes.

    Returns (playlists_created, tracks_written, tracks_scanned).
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    folder_files = {
        folder: _scan_files(folder)
        for folder in sorted(Path(root_dir).iterdir())
        if folder.is_dir()
    }
    folder_files = {k: v for k, v in folder_files.items() if v}

    total          = sum(len(v) for v in folder_files.values())
    offset         = 0
    tracks_written = 0

    for folder, files in folder_files.items():
        pl_path = Path(output_dir) / (folder.name + '.m3u8')
        with open(pl_path, 'w', encoding='utf-8') as f:
            f.write('#EXTM3U\n')
            tracks_written += _write_playlist_entries(
                f, files, pl_path, exclude_instr, progress_cb, offset, total)
        offset += len(files)

    return len(folder_files), tracks_written, total

# ── Folder sync ───────────────────────────────────────────────────────────────

def compare_folders(pa, pb):
    """
    Compare two directories by their relative audio file paths.
    Returns (only_in_a, only_in_b, count_a, count_b).
    """
    sa = {f.relative_to(pa) for f in pa.rglob('*') if f.suffix.lower() in AUDIO_EXTENSIONS}
    sb = {f.relative_to(pb) for f in pb.rglob('*') if f.suffix.lower() in AUDIO_EXTENSIONS}
    return sorted(sa - sb), sorted(sb - sa), len(sa), len(sb)


def copy_files(files, src, dst):
    """Copy files (relative paths) from src to dst, creating subdirs as needed."""
    for rel in files:
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, target)

# ── Application ───────────────────────────────────────────────────────────────

class WPASSApp:
    """
    Main application window for the Walkman Playlist Assistant.

    Provides a two-tab interface:
      Playlist Generator — scan a music library and write M3U8 playlists.
      Folder Sync        — diff a Walkman and a library, then copy missing files.
    """

    def __init__(self):
        self.root = tk.Tk()
        self.root.title('Walkman Playlist Assistant Super Script  [GUI Edition]')
        self.root.configure(bg=BG)
        self.root.minsize(580, 480)
        self._last_output_path = None

        self._center(700, 560)
        self._setup_style()
        self._build()
        self._apply_config(load_config())

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _center(self, w, h):
        """Center the window on the primary screen."""
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f'{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}')

    def _setup_style(self):
        """Configure ttk styles to match the classic Win95 aesthetic."""
        s = ttk.Style()
        s.theme_use('classic')
        s.configure('TNotebook',     background=BG, borderwidth=2)
        s.configure('TNotebook.Tab', background=BG, foreground=FG,
                    font=FONT_BOLD, padding=(12, 4), relief='raised')
        s.map('TNotebook.Tab',
              background=[('selected', BG_LIGHT)],
              relief=[('selected', 'flat')])
        s.configure('Retro.Horizontal.TProgressbar',
                    troughcolor=GRAY, background=NAVY,
                    bordercolor=GRAY, lightcolor=NAVY, darkcolor=NAVY,
                    thickness=14)

    # ── Widget factories ──────────────────────────────────────────────────────
    # Colour defaults use setdefault() so callers can override via **kw
    # without triggering duplicate keyword argument errors.

    def _section(self, parent, text):
        """Return a groove-bordered labelled section frame."""
        return tk.LabelFrame(parent, text=f'  {text}  ', bg=BG, fg=FG,
                             font=FONT_BOLD, relief='groove', bd=2, padx=6, pady=4)

    def _label(self, parent, text, **kw):
        kw.setdefault('fg', FG)
        kw.setdefault('font', FONT)
        return tk.Label(parent, text=text, bg=BG, **kw)

    def _entry(self, parent, **kw):
        return tk.Entry(parent, bg=WHITE, fg=FG, font=FONT,
                        relief='sunken', bd=2, insertbackground=FG, **kw)

    def _btn(self, parent, text, cmd, **kw):
        kw.setdefault('bg', BG)
        kw.setdefault('fg', FG)
        return tk.Button(parent, text=text, command=cmd,
                         font=FONT_BOLD, relief='raised', bd=2, padx=6, pady=2,
                         activebackground=BG_LIGHT, cursor='hand2', **kw)

    def _navy_btn(self, parent, text, cmd, **kw):
        return tk.Button(parent, text=text, command=cmd,
                         bg=NAVY, fg=WHITE, font=FONT_BOLD,
                         relief='raised', bd=2, padx=6, pady=4,
                         activebackground='#0000b0', activeforeground=WHITE,
                         cursor='hand2', **kw)

    def _check(self, parent, text, var, **kw):
        kw.setdefault('fg', FG)
        return tk.Checkbutton(parent, text=text, variable=var,
                              bg=BG, font=FONT, activebackground=BG,
                              selectcolor=WHITE, **kw)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        """Construct the top-level window: banner, notebook tabs, status bar."""
        banner = tk.Frame(self.root, bg=NAVY)
        banner.pack(fill='x')
        tk.Label(banner,
                 text='  WALKMAN PLAYLIST ASSISTANT SUPER SCRIPT  [GUI EDITION]',
                 bg=NAVY, fg=WHITE, font=FONT_BOLD,
                 anchor='w', pady=5, padx=2).pack(side='left')
        tk.Label(banner, text='v0.5  ',
                 bg=NAVY, fg='#9090c0', font=FONT).pack(side='right', padx=4)

        nb = ttk.Notebook(self.root)
        nb.pack(fill='both', expand=True, padx=4, pady=4)
        tab_pl   = tk.Frame(nb, bg=BG)
        tab_sync = tk.Frame(nb, bg=BG)
        tab_about = tk.Frame(nb, bg=BG)
        nb.add(tab_pl,   text='  Playlist Generator  ')
        nb.add(tab_sync, text='  Folder Sync  ')
        nb.add(tab_about, text='  About  ')
        self._build_playlist_tab(tab_pl)
        self._build_sync_tab(tab_sync)
        self._build_about_tab(tab_about)
        
        self.status_var = tk.StringVar(value='Ready.')
        tk.Label(self.root, textvariable=self.status_var,
                 bg=BG, fg=FG, font=FONT, anchor='w',
                 relief='sunken', bd=1, padx=6, pady=2
                 ).pack(fill='x', side='bottom', padx=2, pady=(0, 2))

    def _build_playlist_tab(self, parent):
        """Populate the Playlist Generator tab."""
        pad = dict(padx=8, pady=4)

        # Input ──────────────────────────────────────────────────────────────
        sec_in = self._section(parent, 'Input')
        sec_in.pack(fill='x', **pad)
        sec_in.columnconfigure(1, weight=1)

        self._label(sec_in, 'Music Folder:').grid(row=0, column=0, sticky='w', pady=3)
        self.e_music = self._entry(sec_in)
        self.e_music.grid(row=0, column=1, sticky='ew', padx=(6, 4), pady=3)
        self._btn(sec_in, 'Browse...', lambda: self._pick_dir(self.e_music)
                  ).grid(row=0, column=2, pady=3)

        # Options ────────────────────────────────────────────────────────────
        sec_opt = self._section(parent, 'Options')
        sec_opt.pack(fill='x', **pad)
        sec_opt.columnconfigure(1, weight=1)

        self.multi_var = tk.BooleanVar()
        cb_multi = self._check(sec_opt, 'Generate one playlist per subfolder',
                                self.multi_var, command=self._toggle_mode)
        cb_multi.grid(row=0, column=0, columnspan=3, sticky='w', pady=2)
        ToolTip(cb_multi,
                'Creates a separate .m3u8 for each direct subfolder of your music library')

        self.lbl_pl = self._label(sec_opt, 'Playlist File:')
        self.lbl_pl.grid(row=1, column=0, sticky='w', pady=3)
        self.e_pl = self._entry(sec_opt)
        self.e_pl.grid(row=1, column=1, sticky='ew', padx=(6, 4), pady=3)
        self.btn_pl = self._btn(sec_opt, 'Save As...', self._pick_pl_file)
        self.btn_pl.grid(row=1, column=2, pady=3)

        self.lbl_out = self._label(sec_opt, 'Output Folder:', fg=GRAY)
        self.lbl_out.grid(row=2, column=0, sticky='w', pady=3)
        self.e_out = self._entry(sec_opt, state='disabled',
                                  disabledbackground='#a8a8a8',
                                  disabledforeground=GRAY)
        self.e_out.grid(row=2, column=1, sticky='ew', padx=(6, 4), pady=3)
        self.btn_out = self._btn(sec_opt, 'Browse...', self._pick_dir_out, state='disabled')
        self.btn_out.grid(row=2, column=2, pady=3)

        self.excl_var = tk.BooleanVar()
        cb_excl = self._check(sec_opt, 'Exclude Instrumental / Karaoke tracks',
                               self.excl_var)
        cb_excl.grid(row=3, column=0, columnspan=3, sticky='w', pady=(4, 2))
        ToolTip(cb_excl,
                'Skips tracks whose title or filename contains "instrumental" or "karaoke"')

        # Action ─────────────────────────────────────────────────────────────
        sec_act = self._section(parent, 'Action')
        sec_act.pack(fill='x', **pad)
        sec_act.columnconfigure(0, weight=1)

        self.btn_gen = self._navy_btn(sec_act, '[ GENERATE PLAYLIST(S) ]', self._generate)
        self.btn_gen.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(2, 4))

        self.btn_open = self._btn(sec_act, 'Open Output Folder',
                                   lambda: open_folder(self._last_output_path),
                                   state='disabled')
        self.btn_open.grid(row=1, column=0, sticky='w', pady=(0, 4))
        ToolTip(self.btn_open, 'Open the output folder in your file manager')

        frm_lbl = tk.Frame(sec_act, bg=BG)
        frm_lbl.grid(row=2, column=0, columnspan=2, sticky='ew')
        frm_lbl.columnconfigure(0, weight=1)
        self.prog_lbl = tk.StringVar()
        self.prog_pct = tk.StringVar()
        tk.Label(frm_lbl, textvariable=self.prog_lbl,
                 bg=BG, fg=FG, font=FONT, anchor='w').grid(row=0, column=0, sticky='w')
        tk.Label(frm_lbl, textvariable=self.prog_pct,
                 bg=BG, fg=FG, font=FONT, anchor='e').grid(row=0, column=1, sticky='e')

        self.pbar = ttk.Progressbar(sec_act, orient='horizontal', mode='determinate',
                                     style='Retro.Horizontal.TProgressbar')
        self.pbar.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(2, 4))

    def _build_sync_tab(self, parent):
        """Populate the Folder Sync tab."""
        pad = dict(padx=8, pady=4)

        # Folders ────────────────────────────────────────────────────────────
        sec_in = self._section(parent, 'Folders to Compare')
        sec_in.pack(fill='x', **pad)
        sec_in.columnconfigure(1, weight=1)

        self._label(sec_in, 'Walkman Folder:').grid(row=0, column=0, sticky='w', pady=3)
        self.e_fa = self._entry(sec_in)
        self.e_fa.grid(row=0, column=1, sticky='ew', padx=(6, 4), pady=3)
        self._btn(sec_in, 'Browse...', lambda: self._pick_dir(self.e_fa)
                  ).grid(row=0, column=2)

        self._label(sec_in, 'Library Folder:').grid(row=1, column=0, sticky='w', pady=3)
        self.e_fb = self._entry(sec_in)
        self.e_fb.grid(row=1, column=1, sticky='ew', padx=(6, 4), pady=3)
        self._btn(sec_in, 'Browse...', lambda: self._pick_dir(self.e_fb)
                  ).grid(row=1, column=2)

        self.btn_analyze = self._navy_btn(sec_in, '[ ANALYZE FOLDERS ]', self._analyze)
        self.btn_analyze.grid(row=2, column=0, columnspan=3, sticky='ew', pady=(6, 2))

        # Output terminal ────────────────────────────────────────────────────
        sec_out = self._section(parent, 'Analysis Output')
        sec_out.pack(fill='both', expand=True, **pad)
        sec_out.rowconfigure(1, weight=1)
        sec_out.columnconfigure(0, weight=1)

        frm_tb = tk.Frame(sec_out, bg=BG)
        frm_tb.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 4))
        self.btn_copy = self._btn(frm_tb, 'Copy All to Clipboard',
                                   self._copy_output, state='disabled')
        self.btn_copy.pack(side='right')

        self.txt = tk.Text(sec_out, wrap='none', font=('Courier New', 9),
                           bg='#0c0c0c', fg='#c0c0c0', relief='sunken', bd=2,
                           insertbackground='#c0c0c0',
                           selectbackground=NAVY, selectforeground=WHITE)
        self.txt.grid(row=1, column=0, sticky='nsew')

        sy = tk.Scrollbar(sec_out, command=self.txt.yview, relief='raised')
        sy.grid(row=1, column=1, sticky='ns')
        sx = tk.Scrollbar(sec_out, orient='horizontal',
                          command=self.txt.xview, relief='raised')
        sx.grid(row=2, column=0, sticky='ew')
        self.txt['yscrollcommand'] = sy.set
        self.txt['xscrollcommand'] = sx.set

        self.txt.tag_configure('summary', foreground='#88ccff')
        self.txt.tag_configure('rule',    foreground='#444444')
        self.txt.tag_configure('header',  foreground='#ffff55',
                               font=('Courier New', 9, 'bold'))
        self.txt.tag_configure('missing', foreground='#ff6060')
        self.txt.tag_configure('extra',   foreground='#55ff55')
        self.txt.tag_configure('ok',      foreground='#55ff55',
                               font=('Courier New', 9, 'bold'))
        self.txt.tag_configure('dim',     foreground='#555555')
        
    def _build_about_tab(self, parent):
        """Populate the About tab."""
        pad = dict(padx=8, pady=4)
        sec = self._section(parent, 'About')
        sec.pack(fill='x', **pad)

        info = [
            ('App',     'Walkman Playlist Assistant Super Script  [GUI Edition]'),
            ('Version', 'v0.5'),
            ('Author',  'gitevanh'),
            ('GitHub',  'https://github.com/gitevanh/walkmanPASS-GUI'),
            ('',        ''),
            ('About',   'Generates M3U8 playlists for Sony Walkman devices from a'),
            ('',        'local music library. Supports MP3, FLAC, WAV, M4A, WMA,'),
            ('',        'OGG and AAC. Includes a folder sync tool to diff and copy'),
            ('',        'files between your library and Walkman.'),
        ]

        for i, (label, value) in enumerate(info):
            self._label(sec, label, font=FONT_BOLD if label else FONT
                        ).grid(row=i, column=0, sticky='w', padx=(0, 10), pady=1)
            self._label(sec, value).grid(row=i, column=1, sticky='w', pady=1)
        
    # ── State management ──────────────────────────────────────────────────────

    def _toggle_mode(self):
        """Switch the playlist tab between single-file and per-folder mode."""
        multi = self.multi_var.get()
        self.btn_pl.config( state='disabled' if multi else 'normal')
        self.lbl_pl.config( fg=GRAY          if multi else FG)
        self.e_out.config(  state='normal'   if multi else 'disabled')
        self.btn_out.config(state='normal'   if multi else 'disabled')
        self.lbl_out.config(fg=FG            if multi else GRAY)

    def _pick_dir(self, entry):
        d = filedialog.askdirectory(
            parent=self.root,
            initialdir=Path.home()
        )
        if d:
            entry.delete(0, tk.END)
            entry.insert(0, d)

    def _pick_pl_file(self):
        path = filedialog.asksaveasfilename(
            parent=self.root,
            initialdir=Path.home(),
            defaultextension='.m3u8',
            filetypes=[('M3U8 Playlist', '*.m3u8')]
        )
        if path:
            self.e_pl.delete(0, tk.END)
            self.e_pl.insert(0, path)

    def _pick_dir_out(self):
        d = filedialog.askdirectory(
            parent=self.root,
            initialdir=Path.home()
        )
        if d:
            self.e_out.config(state='normal')
            self.e_out.delete(0, tk.END)
            self.e_out.insert(0, d)

    # ── Config ────────────────────────────────────────────────────────────────

    def _apply_config(self, cfg):
        """Pre-populate path entries from a saved config dictionary."""
        def _set(entry, key):
            val = cfg.get(key, '')
            if val:
                entry.config(state='normal')
                entry.delete(0, tk.END)
                entry.insert(0, val)

        _set(self.e_music, 'music_folder')
        _set(self.e_pl,    'playlist_file')
        _set(self.e_fa,    'folder_a')
        _set(self.e_fb,    'folder_b')

        val = cfg.get('output_folder', '')
        if val:
            self.e_out.config(state='normal')
            self.e_out.delete(0, tk.END)
            self.e_out.insert(0, val)
            if not self.multi_var.get():
                self.e_out.config(state='disabled')

    def _persist_config(self):
        """Save current path entries to disk. Must be called on the main thread."""
        save_config({
            'music_folder':  self.e_music.get(),
            'playlist_file': self.e_pl.get(),
            'output_folder': self.e_out.get(),
            'folder_a':      self.e_fa.get(),
            'folder_b':      self.e_fb.get(),
        })

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _copy_output(self):
        """Copy the full sync terminal contents to the system clipboard."""
        self.root.clipboard_clear()
        self.root.clipboard_append(self.txt.get('1.0', tk.END).strip())
        self._status('Output copied to clipboard.')

    def _update_progress(self, cur, total):
        """Thread-safe progress bar and label update."""
        pct = (cur / total * 100) if total else 0
        def _do(c=cur, t=total, p=pct):
            self.pbar['value'] = p
            self.prog_lbl.set(f'Processing {c:,} of {t:,} files...')
            self.prog_pct.set(f'{p:.0f}%')
        self.root.after(0, _do)

    def _status(self, msg):
        """Thread-safe status bar update."""
        self.root.after(0, lambda: self.status_var.set(msg))

    def _validate_paths(self, multi, music, dest):
        """
        Validate inputs before starting a generation or sync operation.
        Offers to create the destination directory if it does not exist.
        Returns True if safe to proceed.
        """
        if not music:
            messagebox.showwarning('Missing Input', 'Please select a Music Folder.',
                                    parent=self.root)
            return False
        if not Path(music).is_dir():
            messagebox.showerror('Invalid Path', f'Music folder not found:\n{music}',
                                  parent=self.root)
            return False
        if not dest:
            label = 'an Output Folder' if multi else 'a Playlist File path'
            messagebox.showwarning('Missing Input', f'Please select {label}.',
                                    parent=self.root)
            return False
        if not multi:
            parent_dir = Path(dest).parent
            if not parent_dir.exists():
                if messagebox.askyesno('Create Directory',
                                        f'Output directory does not exist. Create it?\n{parent_dir}',
                                        parent=self.root):
                    parent_dir.mkdir(parents=True, exist_ok=True)
                else:
                    return False
        return True

    # ── Actions ───────────────────────────────────────────────────────────────

    def _generate(self):
        """Validate inputs and start playlist generation on a background thread."""
        multi = self.multi_var.get()
        music = self.e_music.get().strip()
        dest  = (self.e_out.get() if multi else self.e_pl.get()).strip()

        if not self._validate_paths(multi, music, dest):
            return

        self.btn_gen.config(state='disabled')
        self.btn_open.config(state='disabled')
        self.pbar['value'] = 0
        self.prog_lbl.set('Starting...')
        self.prog_pct.set('')
        self._status('Working...')
        excl = self.excl_var.get()

        def task():
            try:
                if multi:
                    n_pl, written, scanned = generate_playlists_per_folder(
                        music, dest, excl, self._update_progress)
                    summary = (f'{n_pl} playlist(s) created.\n'
                               f'{written:,} tracks written from {scanned:,} scanned.')
                    out_path = dest
                else:
                    written, scanned = generate_single_playlist(
                        music, dest, excl, self._update_progress)
                    summary = (f'Playlist created.\n'
                               f'{written:,} tracks written from {scanned:,} scanned.')
                    out_path = str(Path(dest).parent)

                self._last_output_path = out_path

                def on_done():
                    messagebox.showinfo('Done', summary, parent=self.root)
                    self._status(summary.replace('\n', '  |  '))
                    self.btn_open.config(state='normal')
                    self._persist_config()
                self.root.after(0, on_done)

            except Exception as exc:
                self.root.after(0, lambda: messagebox.showerror(
                    'Error', str(exc), parent=self.root))
                self._status(f'Error: {exc}')
            finally:
                self.root.after(0, lambda: self.btn_gen.config(state='normal'))

        threading.Thread(target=task, daemon=True).start()

    def _analyze(self):
        """Validate inputs and start folder comparison on a background thread."""
        fa = Path(self.e_fa.get().strip())
        fb = Path(self.e_fb.get().strip())

        if not fa.is_dir() or not fb.is_dir():
            messagebox.showerror('Error', 'Both paths must be valid directories.',
                                  parent=self.root)
            return

        self.btn_analyze.config(state='disabled')
        self.btn_copy.config(state='disabled')
        self.txt.config(state='normal')
        self.txt.delete('1.0', tk.END)
        self.txt.insert(tk.END, 'Scanning...\n', 'dim')
        self._status('Analyzing...')

        def task():
            try:
                only_a, only_b, cnt_a, cnt_b = compare_folders(fa, fb)

                def on_done():
                    self._show_results(fa, fb, only_a, only_b, cnt_a, cnt_b)
                    self._persist_config()
                self.root.after(0, on_done)

            except Exception as exc:
                self.root.after(0, lambda: messagebox.showerror(
                    'Error', str(exc), parent=self.root))
                self._status('Error during analysis.')
            finally:
                self.root.after(0, lambda: self.btn_analyze.config(state='normal'))

        threading.Thread(target=task, daemon=True).start()

    def _show_results(self, fa, fb, only_a, only_b, cnt_a, cnt_b):
        """Render comparison results in the terminal panel and prompt to copy files."""
        t = self.txt
        t.config(state='normal')
        t.delete('1.0', tk.END)

        t.insert(tk.END,
                 f'> Walkman: {cnt_a:,} audio files  |  Library: {cnt_b:,} audio files\n',
                 'summary')
        t.insert(tk.END, '─' * 60 + '\n', 'rule')

        if not only_a and not only_b:
            t.insert(tk.END, '\n> FOLDERS ARE IN SYNC. NO DIFFERENCES FOUND.\n', 'ok')
            t.config(state='disabled')
            self.btn_copy.config(state='normal')
            self._status('Sync check complete — folders match.')
            messagebox.showinfo('In Sync', 'Both folders are in sync.', parent=self.root)
            return

        t.insert(tk.END,
                 f'\n> On Walkman, not in Library  [{len(only_a)} file(s)]\n', 'header')
        if only_a:
            for f in only_a:
                t.insert(tk.END, f'  {f}\n', 'missing')
        else:
            t.insert(tk.END, '  (none)\n', 'dim')

        t.insert(tk.END,
                 f'\n> In Library, not on Walkman  [{len(only_b)} file(s)]\n', 'header')
        if only_b:
            for f in only_b:
                t.insert(tk.END, f'  {f}\n', 'extra')
        else:
            t.insert(tk.END, '  (none)\n', 'dim')

        t.config(state='disabled')
        self.btn_copy.config(state='normal')
        self._status(
            f'{len(only_a)} extra on Walkman  |  {len(only_b)} missing from Walkman.')

        if messagebox.askquestion('Sync Files', 'Copy missing files?',
                                   parent=self.root) == 'yes':
            direction = messagebox.askquestion(
                'Copy Direction',
                'Copy missing files TO Walkman (from Library)?\n'
                "(No = copy files missing from Library instead.)",
                parent=self.root
            )
            try:
                if direction == 'yes':
                    copy_files(only_b, fb, fa)   # library → walkman
                else:
                    copy_files(only_a, fa, fb)   # walkman → library
                messagebox.showinfo('Done', 'Files copied successfully.', parent=self.root)
                self._status('Files copied.')
            except Exception as exc:
                messagebox.showerror('Error', f'Copy failed:\n{exc}', parent=self.root)

    # ── Entry point ───────────────────────────────────────────────────────────

    def run(self):
        """Start the tkinter main loop."""
        self.root.mainloop()


if __name__ == '__main__':
    WPASSApp().run()
