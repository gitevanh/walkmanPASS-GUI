import os
import re
import shutil
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.wave import WAVE
from mutagen.easymp4 import EasyMP4
from mutagen.asf import ASF
from mutagen.oggvorbis import OggVorbis
import mutagen

# --- Constants ---
AUDIO_LOADERS = {
    '.mp3': MP3,
    '.flac': FLAC,
    '.wav': WAVE,
    '.m4a': EasyMP4,
    '.wma': ASF,
    '.ogg': OggVorbis,
    '.aac': mutagen.File
}
AUDIO_EXTENSIONS = tuple(AUDIO_LOADERS.keys())

# --- Audio Metadata ---
def get_audio_metadata(file_path):
    try:
        ext = file_path.suffix.lower()
        loader = AUDIO_LOADERS.get(ext)
        if not loader:
            return None, None, None

        audio = loader(str(file_path))
        if audio is None or not hasattr(audio, 'info'):
            return None, None, None

        duration = int(audio.info.length)

        artist = "Unknown Artist"
        title = file_path.stem

        if audio.tags:
            try:
                # --- Format-specific tag handling ---
                if isinstance(audio, (FLAC, OggVorbis)):
                    artist = audio.tags.get('artist', [artist])[0]
                    title = audio.tags.get('title', [title])[0]

                elif isinstance(audio, EasyMP4):
                    artist = audio.tags.get('©ART', [artist])[0]
                    title = audio.tags.get('©nam', [title])[0]

                else:  # MP3, WAV, WMA, etc.
                    artist = audio.tags.get('TPE1', [artist])[0]
                    title = audio.tags.get('TIT2', [title])[0]

            except Exception:
                pass

        # --- Fallback: extract from filename ---
        if artist == "Unknown Artist" and " - " in title:
            parts = title.split(" - ", 1)
            if len(parts) == 2:
                artist, title = parts

        return duration, str(artist), str(title)

    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return None, None, None


# --- Playlist Logic ---
def normalize_path(file_path, playlist_path):
    playlist_dir = Path(playlist_path).parent
    rel = os.path.relpath(file_path, playlist_dir)
    return rel.replace("\\", "/")


def write_playlist(playlist_path, files, base_dir, exclude_instrumental):
    with open(playlist_path, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")

        for file_path in files:
            duration, artist, title = get_audio_metadata(file_path)
            if duration is None:
                continue

            if exclude_instrumental and re.search(r'(instrumental|karaoke)', title, re.IGNORECASE):
                continue

            relative_path = normalize_path(file_path, playlist_path)

            f.write(f"#EXTINF:{duration},{artist} - {title}\n")
            f.write(f"{relative_path}\n")


def generate_single_playlist(input_dir, playlist_path, exclude_instrumental, progress_callback=None):
    files = [f for f in Path(input_dir).rglob('*') if f.suffix.lower() in AUDIO_EXTENSIONS]
    total = len(files)

    with open(playlist_path, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")

        for i, file_path in enumerate(files):
            duration, artist, title = get_audio_metadata(file_path)
            if duration is None:
                continue

            if exclude_instrumental and re.search(r'(instrumental|karaoke)', title, re.IGNORECASE):
                continue

            relative_path = normalize_path(file_path, playlist_path)

            f.write(f"#EXTINF:{duration},{artist} - {title}\n")
            f.write(f"{relative_path}\n")

            if progress_callback:
                progress_callback(i + 1, total)


def generate_playlists_per_folder(root_dir, output_dir, exclude_instrumental, progress_callback=None):
    root_path = Path(root_dir)
    subfolders = [f for f in root_path.iterdir() if f.is_dir()]
    total = len(subfolders)

    for i, folder in enumerate(subfolders):
        files = [f for f in folder.rglob('*') if f.suffix.lower() in AUDIO_EXTENSIONS]
        if not files:
            continue

        playlist_name = folder.name + ".m3u8"
        playlist_path = Path(output_dir) / playlist_name

        write_playlist(playlist_path, files, folder, exclude_instrumental)

        if progress_callback:
            progress_callback(i + 1, total)


# --- Folder Sync Logic ---
def compare_folders(path_a, path_b):
    set_a = {f.relative_to(path_a) for f in path_a.rglob('*') if f.suffix.lower() in AUDIO_EXTENSIONS}
    set_b = {f.relative_to(path_b) for f in path_b.rglob('*') if f.suffix.lower() in AUDIO_EXTENSIONS}

    only_in_a = sorted(set_a - set_b)
    only_in_b = sorted(set_b - set_a)

    return only_in_a, only_in_b


def copy_files(missing_files, src_root, dst_root):
    for rel_path in missing_files:
        src = src_root / rel_path
        dst = dst_root / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


# --- GUI Functions ---
def select_folder(entry):
    folder = filedialog.askdirectory()
    if folder:
        entry.delete(0, tk.END)
        entry.insert(0, folder)


def select_playlist_file():
    file = filedialog.asksaveasfilename(defaultextension=".m3u8", filetypes=[("M3U8 Playlist", "*.m3u8")])
    if file:
        entry_playlist_path.delete(0, tk.END)
        entry_playlist_path.insert(0, file)


def select_output_folder():
    folder = filedialog.askdirectory()
    if folder:
        entry_output_folder.delete(0, tk.END)
        entry_output_folder.insert(0, folder)


def update_progress(current, total):
    progress.set(f"Processed {current} of {total}")
    percent = (current / total) * 100 if total else 0
    progress_bar['value'] = percent
    percentage.set(f"{percent:.2f}%")


def run_playlist_generation():
    exclude = exclude_var.get()
    multi = multi_folder_var.get()

    if multi:
        input_dir = entry_music_folder.get()
        output_dir = entry_output_folder.get()

        if not input_dir or not output_dir:
            messagebox.showwarning("Missing Input", "Please select both Music Folder and Output Folder.")
            return

        generate_playlists_per_folder(input_dir, output_dir, exclude, update_progress)

    else:
        music_dir = entry_music_folder.get()
        playlist_path = entry_playlist_path.get()

        if not music_dir or not playlist_path:
            messagebox.showwarning("Missing Input", "Please select Music Folder and Playlist File.")
            return

        generate_single_playlist(music_dir, playlist_path, exclude, update_progress)

    messagebox.showinfo("Done", "Playlist(s) created successfully!")


def analyze_folders():
    path_a = Path(entry_folder_a.get())
    path_b = Path(entry_folder_b.get())

    if not path_a.is_dir() or not path_b.is_dir():
        messagebox.showerror("Error", "Both paths must be valid directories.")
        return

    only_in_a, only_in_b = compare_folders(path_a, path_b)

    report = []
    report.append(f"Files only in Folder A ({path_a}):\n")
    report.extend([str(f) for f in only_in_a])
    report.append(f"\n\nFiles only in Folder B ({path_b}):\n")
    report.extend([str(f) for f in only_in_b])

    text_output.delete('1.0', tk.END)
    text_output.insert(tk.END, "\n".join(report))

    if only_in_a or only_in_b:
        response = messagebox.askquestion("Sync Files", "Do you want to copy missing files?")
        if response == 'yes':
            direction = messagebox.askquestion("Copy Direction", "Copy from A → B?\n(Select 'No' to copy B → A)")
            try:
                if direction == 'yes':
                    copy_files(only_in_a, path_a, path_b)
                else:
                    copy_files(only_in_b, path_b, path_a)
                messagebox.showinfo("Success", "Files copied successfully!")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to copy files:\n{e}")
    else:
        messagebox.showinfo("No Differences", "Both folders are in sync.")


# --- GUI Setup ---
root = tk.Tk()
root.title("Walkman Playlist Assistant")

notebook = ttk.Notebook(root)
tab_playlist = ttk.Frame(notebook)
tab_sync = ttk.Frame(notebook)

notebook.add(tab_playlist, text="Playlist Generator")
notebook.add(tab_sync, text="Folder Sync Analyzer")
notebook.pack(fill='both', expand=True)

padding = {'padx': 10, 'pady': 5}

# Playlist Tab
ttk.Label(tab_playlist, text="Music Folder:").grid(row=0, column=0, sticky=tk.W, **padding)
entry_music_folder = ttk.Entry(tab_playlist, width=50)
entry_music_folder.grid(row=0, column=1, sticky=tk.EW, **padding)
ttk.Button(tab_playlist, text="Browse", command=lambda: select_folder(entry_music_folder)).grid(row=0, column=2, **padding)

multi_folder_var = tk.BooleanVar()
ttk.Checkbutton(tab_playlist, text="Generate Playlist per Subfolder", variable=multi_folder_var).grid(row=1, columnspan=3, sticky=tk.W, **padding)

ttk.Label(tab_playlist, text="Playlist File Path (if single):").grid(row=2, column=0, sticky=tk.W, **padding)
entry_playlist_path = ttk.Entry(tab_playlist, width=50)
entry_playlist_path.grid(row=2, column=1, sticky=tk.EW, **padding)
ttk.Button(tab_playlist, text="Browse", command=select_playlist_file).grid(row=2, column=2, **padding)

ttk.Label(tab_playlist, text="Output Folder (if multiple):").grid(row=3, column=0, sticky=tk.W, **padding)
entry_output_folder = ttk.Entry(tab_playlist, width=50)
entry_output_folder.grid(row=3, column=1, sticky=tk.EW, **padding)
ttk.Button(tab_playlist, text="Browse", command=select_output_folder).grid(row=3, column=2, **padding)

exclude_var = tk.BooleanVar()
ttk.Checkbutton(tab_playlist, text="Exclude Instrumental/Karaoke Tracks", variable=exclude_var).grid(row=4, columnspan=3, sticky=tk.W, **padding)

ttk.Button(tab_playlist, text="Generate Playlist(s)", command=run_playlist_generation).grid(row=5, columnspan=3, sticky=tk.EW, **padding)

progress = tk.StringVar()
percentage = tk.StringVar()
ttk.Label(tab_playlist, textvariable=progress).grid(row=6, column=0, columnspan=2, sticky=tk.W, **padding)
ttk.Label(tab_playlist, textvariable=percentage).grid(row=6, column=2, sticky=tk.E, **padding)

progress_bar = ttk.Progressbar(tab_playlist, orient="horizontal", length=400, mode="determinate")
progress_bar.grid(row=7, column=0, columnspan=3, sticky=tk.EW, **padding)

# Sync Tab
ttk.Label(tab_sync, text="Folder A (Walkman):").grid(row=0, column=0, sticky=tk.W, **padding)
entry_folder_a = ttk.Entry(tab_sync, width=50)
entry_folder_a.grid(row=0, column=1, sticky=tk.EW, **padding)
ttk.Button(tab_sync, text="Browse", command=lambda: select_folder(entry_folder_a)).grid(row=0, column=2, **padding)

ttk.Label(tab_sync, text="Folder B (Library):").grid(row=1, column=0, sticky=tk.W, **padding)
entry_folder_b = ttk.Entry(tab_sync, width=50)
entry_folder_b.grid(row=1, column=1, sticky=tk.EW, **padding)
ttk.Button(tab_sync, text="Browse", command=lambda: select_folder(entry_folder_b)).grid(row=1, column=2, **padding)

ttk.Button(tab_sync, text="Analyze", command=analyze_folders).grid(row=2, columnspan=3, sticky=tk.EW, **padding)

text_output = tk.Text(tab_sync, height=20, wrap=tk.NONE)
text_output.grid(row=3, column=0, columnspan=3, sticky=tk.NSEW, **padding)

scroll_y = ttk.Scrollbar(tab_sync, orient='vertical', command=text_output.yview)
scroll_y.grid(row=3, column=3, sticky='ns')
text_output['yscrollcommand'] = scroll_y.set

scroll_x = ttk.Scrollbar(tab_sync, orient='horizontal', command=text_output.xview)
scroll_x.grid(row=4, column=0, columnspan=3, sticky='ew')
text_output['xscrollcommand'] = scroll_x.set

# Layout weights
for i in range(3):
    tab_playlist.grid_columnconfigure(i, weight=1)
    tab_sync.grid_columnconfigure(i, weight=1)

tab_sync.grid_rowconfigure(3, weight=1)

# --- Main Loop ---
if __name__ == '__main__':
    root.mainloop()