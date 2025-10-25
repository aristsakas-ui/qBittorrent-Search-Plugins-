Python "intelligent" scripts fully working IMPORTANT all require the installation of a library

Tested on qBittorrent v5.1.0 Python 3.9.13

3 scrape the torrent sites and 2 use the apis and try to sort the most relevant results 

leetx.py is a plugin for the official _1337x_ site

IMPORTANT: x1337xtube.py is NOT an official mirror of x1337x but contains all of it's torrents. __Use at your own risk__

# Dependencies Installation Guide

## What You Need to Install

All search plugins require one main Python library to work properly.

### For Both Windows and Linux:

**Required Library:** `beautifulsoup4`

---

## 🪟 Windows Installation

### Method 1: Using Command Prompt (Easiest)
1. Press `Windows Key + R`, type `cmd`, and press Enter
2. Copy and paste this command:
   ```cmd
   pip install beautifulsoup4
   ```
3. Press Enter and wait for installation to complete

### Method 2: If the above doesn't work
1. Open Command Prompt as Administrator (right-click Command Prompt → "Run as administrator")
2. Try this command instead:
   ```cmd
   python -m pip install beautifulsoup4
   ```

---

## 🐧 Linux Installation

### Method 1: Using pip (Recommended)
Open your terminal and run:
```bash
pip install beautifulsoup4
```

### Method 2: If you get "command not found"
```bash
sudo apt update
sudo apt install python3-pip
pip3 install beautifulsoup4
```

### Method 3: Using your package manager (Alternative)
```bash
# For Ubuntu/Debian:
sudo apt install python3-bs4

# For Fedora:
sudo dnf install python3-beautifulsoup4

# For Arch Linux:
sudo pacman -S python-beautifulsoup4
```

---

## ✅ Verification

To check if installation was successful, open command prompt/terminal and type:
```bash
python -c "import bs4; print('BeautifulSoup4 is installed!')"
```

If you see the success message, you're all set!

---
