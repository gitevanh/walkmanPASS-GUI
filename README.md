# 🎧 Walkman Playlist Assistant (GUI Edition)

<p align="center">
  <img width="180" src="https://github.com/user-attachments/assets/876165c1-4888-441c-9b97-bfb1bb5dd68a">
</p>

<p align="center">
  <b>A lightweight desktop tool for generating Walkman-compatible playlists</b>
</p>

---


##  Features

### Playlist Generation
- Generate `.m3u8` playlists compatible with Walkman devices  
- Scan entire music libraries automatically  
- Create:
  - **One playlist for all files**
  - **One playlist per folder (including subfolders)**  
- Option to **exclude Instrumental/Karaoke tracks**  
- Uses **metadata when available**, with filename fallback  
- Supports **flexible playlist locations** using relative paths  

---

### Folder Sync & Comparison
- Compare two directories (e.g., Walkman vs. library)  
- Detect:
  - Missing files  
  - Extra files  
- Copy missing files between folders (**choose direction**)  

---

## Supported Formats
 MP3 • FLAC • WAV • M4A • WMA • OGG • AAC (also you can just add more its very open)
 
---

## Usage

1. Select your **Music Folder**  
2. Choose:
   - a **playlist file path** (single playlist), or  
   - an **output folder** (multiple playlists)  
3. (Optional) Enable filtering options  
4. Click **Generate Playlist(s)**  

---

## Platform Support

- Windows (tested on Windows 11 23H2)  
- Linux (tested on openSUSE)  

---

## Notes

- Designed for **non-Android Sony Walkman devices**  
- Some models may not support `../` relative paths  
- Best results when playlists are near the music folder  
- Metadata quality depends on your files  

---

## Disclaimer

This project was created as a personal utility and may not follow best practices.  
It is provided **as-is**, with no guarantees.
