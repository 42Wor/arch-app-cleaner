# Arch App Cleaner

A native desktop application for Arch Linux that automatically finds all installed GUI applications, maps them to their underlying `pacman` packages, and allows you to uninstall them completely cleanly (including unused dependencies and configuration files) with a single click.

## Features
- **Native UI**: Built with PyQt6, providing a fast, responsive interface.
- **Smart Matching**: Connects desktop icons (`.desktop` files) to their actual `pacman` binaries and package names.
- **Clean Uninstallation**: Safely runs `pacman -Rns` to remove software alongside all orphaned dependencies.
- **Secure**: Uses `pkexec` (Polkit) to securely ask for your password via a system GUI prompt—no need to run the app as root.

## Dependencies

Make sure you have PyQt6 and SVG support installed via pacman:
```bash
sudo pacman -S python-pyqt6 qt6-svg polkit
```

## Running the App
Simply execute the Python script:
```bash
./main.py
```
*(Or `python main.py`)*

## Contributing
Pull requests are welcome!
