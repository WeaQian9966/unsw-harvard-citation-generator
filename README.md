# Purpose
This project is used to simplify citation process in academic writing.

# Quick Start
## GUI
run command
```
python unsw_harvard_cite_generator.py --gui
```

### Or one click on mac
Install `UNSWHarvardCiteGenerator.app`

## TUI
### generate citation with .bib file
```
python3 unsw_harvard_cite_generator.py input.bib
```
### generate citation with specific page number (for in-text citation)
```
python3 unsw_harvard_cite_generator.py input.bib --page 12
```
### generate citation with terminal input
```
python3 unsw_harvard_cite_generator.py
```
* to end input with `ctrl` + `D` for mac/linux, `ctrl` + `Z` for windows
### If your command is not `python3`
```
python unsw_harvard_cite_generator.py ...
```


# GUI Packaging (macOS + Windows)

## Prerequisite

Install PyInstaller in your Python environment:
```
pip install pyinstaller
```

## Build macOS app (on macOS)

Run:
```
bash scripts/build_gui_macos.sh
```

Output:
```
- dist/UNSWHarvardCiteGenerator.app
```
This .app bundle has been verified to launch successfully on macOS.

## Build Windows exe (on Windows)

Run in PowerShell:
```
./scripts/build_gui_windows.ps1
```
Output:
```
- dist/UNSWHarvardCiteGenerator.exe
```
This is a direct executable file (single .exe), no installer required.


## Notes

- PyInstaller cannot reliably build native Windows exe directly on macOS.
- For release distribution, sign and notarize the macOS app if required by your target environment.
