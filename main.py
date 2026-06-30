#!/usr/bin/env python3
import sys
import os
import subprocess
import re
import glob
import shutil
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                             QListWidget, QListWidgetItem, QSplitter, QFrame,
                             QDialog, QProgressBar, QPlainTextEdit, QMessageBox)
from PyQt6.QtGui import QPixmap, QIcon, QFont
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QProcess, QSize

# --- Helper Utilities for Sizes ---
def parse_size_to_bytes(size_str):
    """Parses package size strings (e.g., '15.42 MiB', '452.00 KiB') into numeric bytes."""
    try:
        match = re.match(r"([\d\.]+)\s*([a-zA-Z]+)", size_str)
        if not match:
            return 0
        value = float(match.group(1))
        unit = match.group(2).lower()
        if 'ki' in unit or 'k' in unit:
            return int(value * 1024)
        elif 'mi' in unit or 'm' in unit:
            return int(value * 1024 * 1024)
        elif 'gi' in unit or 'g' in unit:
            return int(value * 1024 * 1024 * 1024)
        return int(value)
    except Exception:
        return 0

def format_bytes_to_human(bytes_val):
    """Converts a byte count back into a human-readable size string."""
    for unit in ['B', 'KiB', 'MiB', 'GiB', 'TiB']:
        if bytes_val < 1024.0:
            return f"{bytes_val:.2f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.2f} PiB"


# --- Real-Time Uninstallation Progress Dialog ---
class UninstallDialog(QDialog):
    def __init__(self, package, parent=None):
        super().__init__(parent)
        self.package = package
        self.setWindowTitle(f"Cleanly Removing {package}")
        self.setMinimumSize(600, 400)
        self.setStyleSheet("background-color: #131316; color: #f4f4f5;")
        
        layout = QVBoxLayout(self)
        
        self.status_lbl = QLabel(f"Initiating clean removal of {package}...")
        self.status_lbl.setStyleSheet("font-weight: bold; font-size: 14px; color: #1793d1;")
        layout.addWidget(self.status_lbl)
        
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #2d2d34;
                border-radius: 6px;
                text-align: center;
                background-color: #1e1e24;
                color: #fff;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: #1793d1;
            }
        """)
        layout.addWidget(self.progress)
        
        self.log_area = QPlainTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0b0b0d;
                color: #22c55e;
                font-family: monospace;
                font-size: 11px;
                border: 1px solid #2d2d34;
                border-radius: 6px;
            }
        """)
        layout.addWidget(self.log_area)
        
        self.close_btn = QPushButton("Done")
        self.close_btn.setEnabled(False)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background-color: #2d2d34; color: #9a9a9f;
                border-radius: 6px; padding: 10px 20px; font-weight: bold;
                border: none;
            }
            QPushButton:enabled {
                background-color: #1793d1; color: #fff;
            }
            QPushButton:enabled:hover {
                background-color: #137bb0;
            }
        """)
        self.close_btn.clicked.connect(self.accept)
        layout.addWidget(self.close_btn)
        
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.process_finished)
        
        self.process.start("pkexec", ["pacman", "-Rns", "--noconfirm", package])
        
    def read_output(self):
        data = self.process.readAllStandardOutput()
        text = bytes(data).decode("utf-8", errors="ignore")
        self.log_area.appendPlainText(text.rstrip())
        
        text_lower = text.lower()
        if "checking dependencies" in text_lower:
            self.progress.setRange(0, 100)
            self.progress.setValue(20)
            self.status_lbl.setText("Analyzing system dependencies...")
        elif "removing" in text_lower:
            self.progress.setValue(60)
            self.status_lbl.setText("Purging package binaries and directory files...")
        elif "running post-transaction hooks" in text_lower:
            self.progress.setValue(90)
            self.status_lbl.setText("Executing post-transaction synchronization hooks...")

    def process_finished(self, exit_code, exit_status):
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.close_btn.setEnabled(True)
        
        if exit_code == 0:
            self.status_lbl.setText("Uninstallation completed successfully!")
            self.status_lbl.setStyleSheet("font-weight: bold; font-size: 14px; color: #22c55e;")
        else:
            self.status_lbl.setText("Process terminated or cancelled by user.")
            self.status_lbl.setStyleSheet("font-weight: bold; font-size: 14px; color: #ef4444;")


# --- Worker Thread for Scanning System Software ---
class AppScanner(QThread):
    finished = pyqtSignal(list)

    def run(self):
        pkg_info = self.get_all_explicit_packages()
        apps = self.match_with_desktop_entries(pkg_info)
        self.finished.emit(apps)

    def get_all_explicit_packages(self):
        res = subprocess.run(["pacman", "-Qei"], capture_output=True, text=True)
        packages = {}
        current_pkg = None
        
        for line in res.stdout.splitlines():
            if line.startswith("Name            :"):
                current_pkg = line.split(":", 1)[1].strip()
                packages[current_pkg] = {
                    "name": current_pkg,
                    "desc": "No description available.",
                    "size": "0 B",
                    "size_bytes": 0,
                    "is_gui": False,
                    "icon_name": "package-x-generic",
                    "icon_path": None,
                    "friendly_name": current_pkg,
                    "version": "Unknown",
                    "depends": []
                }
            elif line.startswith("Description     :") and current_pkg:
                packages[current_pkg]["desc"] = line.split(":", 1)[1].strip()
            elif line.startswith("Version         :") and current_pkg:
                packages[current_pkg]["version"] = line.split(":", 1)[1].strip()
            elif line.startswith("Depends On      :") and current_pkg:
                deps_raw = line.split(":", 1)[1].strip()
                packages[current_pkg]["depends"] = [
                    re.split(r'[<>=]', d.strip())[0] 
                    for d in deps_raw.split() if d.strip() != "None"
                ]
            elif line.startswith("Installed Size  :") and current_pkg:
                size_str = line.split(":", 1)[1].strip()
                packages[current_pkg]["size"] = size_str
                packages[current_pkg]["size_bytes"] = parse_size_to_bytes(size_str)
        return packages

    def match_with_desktop_entries(self, pkg_info):
        binary_map = {}
        desktop_files = glob.glob("/usr/share/applications/*.desktop")
        
        for df in desktop_files:
            try:
                with open(df, 'r', errors='ignore') as f:
                    content = f.read()
                if "NoDisplay=true" in content or "NoDisplay=True" in content:
                    continue
                if "[Desktop Entry]" not in content:
                    continue
                
                entry_lines = content.split("[Desktop Entry]")[1].split("[")[0]
                name, icon, exec_cmd = None, None, None
                
                for line in entry_lines.splitlines():
                    if line.startswith("Name="):
                        name = line.split("=", 1)[1].strip()
                    elif line.startswith("Icon="):
                        icon = line.split("=", 1)[1].strip()
                    elif line.startswith("Exec="):
                        raw_exec = line.split("=", 1)[1].strip()
                        exec_cmd = re.sub(r'%\w', '', raw_exec).strip().split()[0]
                        exec_cmd = os.path.basename(exec_cmd).strip('"\'')
                
                if name and exec_cmd:
                    binary_map[exec_cmd] = {
                        "friendly_name": name,
                        "icon": icon
                    }
            except Exception:
                pass

        for pkg_name, info in pkg_info.items():
            if pkg_name in binary_map:
                info["friendly_name"] = binary_map[pkg_name]["friendly_name"]
                info["icon_name"] = binary_map[pkg_name]["icon"]
                info["icon_path"] = self.find_icon_path(binary_map[pkg_name]["icon"])
                info["is_gui"] = True
            else:
                binary_path = shutil.which(pkg_name)
                if binary_path:
                    info["icon_name"] = "utilities-terminal"
                else:
                    info["icon_name"] = "package-x-generic"
        
        return list(pkg_info.values())

    def find_icon_path(self, icon_name):
        if not icon_name:
            return None
        if os.path.isabs(icon_name) and os.path.exists(icon_name):
            return icon_name
        
        search_dirs = [
            "/usr/share/pixmaps",
            "/usr/share/icons/hicolor/48x48/apps",
            "/usr/share/icons/hicolor/scalable/apps",
            "/usr/share/icons/Adwaita/48x48/apps",
            "/usr/share/icons/breeze/apps/48",
        ]
        for sd in search_dirs:
            for ext in [".png", ".svg"]:
                path = os.path.join(sd, icon_name + ext)
                if os.path.exists(path):
                    return path
                    
        for root, dirs, files in os.walk("/usr/share/icons", followlinks=True):
            if len(root.split(os.sep)) > 6:
                continue
            for ext in [".png", ".svg"]:
                if (icon_name + ext) in files:
                    return os.path.join(root, icon_name + ext)
        return None


# --- Custom Widget representing a row in the List View ---
class AppListRow(QWidget):
    def __init__(self, app_data, parent=None):
        super().__init__(parent)
        self.app_data = app_data
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)
        
        self.icon_lbl = QLabel()
        self.icon_lbl.setFixedSize(36, 36)
        
        icon_loaded = False
        theme_icon = QIcon.fromTheme(app_data['icon_name'])
        if not theme_icon.isNull():
            self.icon_lbl.setPixmap(theme_icon.pixmap(36, 36))
            icon_loaded = True
        elif app_data['icon_path'] and os.path.exists(app_data['icon_path']):
            self.icon_lbl.setPixmap(QPixmap(app_data['icon_path']).scaled(36, 36, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            icon_loaded = True
            
        if not icon_loaded:
            self.icon_lbl.setText("📦")
            self.icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.icon_lbl.setStyleSheet("font-size: 18px;")
            
        text_layout = QVBoxLayout()
        text_layout.setSpacing(1)
        
        title_lbl = QLabel(app_data['friendly_name'])
        title_lbl.setStyleSheet("font-weight: bold; color: #fff; font-size: 13px;")
        
        pkg_lbl = QLabel(f"{app_data['name']} • {app_data['size']}")
        pkg_lbl.setStyleSheet("color: #9a9a9f; font-size: 11px;")
        
        text_layout.addWidget(title_lbl)
        text_layout.addWidget(pkg_lbl)
        
        layout.addWidget(self.icon_lbl)
        layout.addLayout(text_layout)
        layout.addStretch()


# --- Application Window with Custom Styled Two-Pane Layout ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Arch App Cleaner")
        self.resize(1000, 680)
        self.setStyleSheet("background-color: #1e1e24; color: #ffffff;")
        
        self.cards = []
        
        # Base central container
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(16)
        
        # Splitter to allow dynamic layout adjustment
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(2)
        self.splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #2d2d34;
            }
        """)
        main_layout.addWidget(self.splitter)
        
        # --- LEFT PANE (Application selection and search) ---
        left_pane = QWidget()
        left_layout = QVBoxLayout(left_pane)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)
        
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Filter packages...")
        self.search_bar.setStyleSheet("""
            QLineEdit {
                background-color: #16161a; border: 1px solid #2d2d34;
                border-radius: 6px; padding: 10px; color: #ffffff;
                font-size: 13px;
            }
            QLineEdit:focus { border: 1px solid #1793d1; }
        """)
        self.search_bar.textChanged.connect(self.filter_apps)
        left_layout.addWidget(self.search_bar)
        
        # Dynamic Space Stats Bar
        self.stats_label = QLabel("Analyzing package configurations...")
        self.stats_label.setStyleSheet("color: #9a9a9f; font-size: 12px; background-color: #16161a; padding: 8px 12px; border-radius: 6px; border: 1px solid #2d2d34;")
        left_layout.addWidget(self.stats_label)
        
        # List of applications
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: #16161a;
                border: 1px solid #2d2d34;
                border-radius: 8px;
                padding: 4px;
            }
            QListWidget::item {
                border-radius: 6px;
                margin: 2px 4px;
            }
            QListWidget::item:hover {
                background-color: #272730;
            }
            QListWidget::item:selected {
                background-color: #1793d1;
            }
        """)
        self.list_widget.currentItemChanged.connect(self.app_selected)
        left_layout.addWidget(self.list_widget)
        
        # Loading Indicator Label inside the List Box
        self.loading_label = QLabel("Initializing engine and scanning system structures...")
        self.loading_label.setStyleSheet("color: #9a9a9f; font-size: 13px; font-weight: bold;")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(self.loading_label)
        
        self.splitter.addWidget(left_pane)
        
        # --- RIGHT PANE (Selected app details & uninstall panel) ---
        self.right_pane = QWidget()
        self.right_pane.setStyleSheet("background-color: #1e1e24;")
        self.right_layout = QVBoxLayout(self.right_pane)
        self.right_layout.setContentsMargins(12, 0, 0, 0)
        self.right_layout.setSpacing(20)
        
        # Placeholder view when no app is chosen
        self.placeholder_lbl = QLabel("No application selected.\nChoose an app from the list to begin clean uninstallation.")
        self.placeholder_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder_lbl.setStyleSheet("color: #9a9a9f; font-size: 14px; line-height: 1.5;")
        self.right_layout.addWidget(self.placeholder_lbl)
        
        self.splitter.addWidget(self.right_pane)
        
        # Set panel proportions
        self.splitter.setSizes([450, 550])
        
        # Run package scanner thread
        self.scanner = AppScanner()
        self.scanner.finished.connect(self.populate_apps)
        self.scanner.start()

    def populate_apps(self, apps):
        self.loading_label.deleteLater()
        for app in apps:
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 52))
            
            row_widget = AppListRow(app)
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, row_widget)
            
        self.update_stats()

    def update_stats(self):
        """Iterates list records dynamically to sum space totals for matching entries."""
        visible_bytes = 0
        visible_count = 0
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if not item.isHidden():
                row_widget = self.list_widget.itemWidget(item)
                visible_bytes += row_widget.app_data['size_bytes']
                visible_count += 1
        
        readable_size = format_bytes_to_human(visible_bytes)
        self.stats_label.setText(
            f"Showing {visible_count} of {self.list_widget.count()} packages | Recoverable Space: <b style='color: #1793d1;'>{readable_size}</b>"
        )

    def filter_apps(self, text):
        query = text.lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            row_widget = self.list_widget.itemWidget(item)
            app = row_widget.app_data
            match = (query in app['name'].lower() or 
                     query in app['package'].lower() or 
                     query in app['desc'].lower() or 
                     query in app['friendly_name'].lower())
            item.setHidden(not match)
        self.update_stats()

    def app_selected(self, current, previous):
        # Clear out existing layout elements from the right pane
        while self.right_layout.count():
            item = self.right_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
                
        if not current:
            # Re-draw placeholder
            self.placeholder_lbl = QLabel("No application selected.\nChoose an app from the list to begin clean uninstallation.")
            self.placeholder_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.placeholder_lbl.setStyleSheet("color: #9a9a9f; font-size: 14px; line-height: 1.5;")
            self.right_layout.addWidget(self.placeholder_lbl)
            return

        row_widget = self.list_widget.itemWidget(current)
        app_data = row_widget.app_data
        
        # Header Layout
        header = QHBoxLayout()
        header.setSpacing(16)
        
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(64, 64)
        icon_loaded = False
        theme_icon = QIcon.fromTheme(app_data['icon_name'])
        if not theme_icon.isNull():
            icon_lbl.setPixmap(theme_icon.pixmap(64, 64))
            icon_loaded = True
        elif app_data['icon_path'] and os.path.exists(app_data['icon_path']):
            icon_lbl.setPixmap(QPixmap(app_data['icon_path']).scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            icon_loaded = True
            
        if not icon_loaded:
            icon_lbl.setText("📦")
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_lbl.setStyleSheet("font-size: 36px;")
            
        header_text = QVBoxLayout()
        header_text.setSpacing(2)
        
        title = QLabel(app_data['friendly_name'])
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #fff;")
        
        pkg_id = QLabel(f"Package ID: {app_data['package']}")
        pkg_id.setStyleSheet("color: #1793d1; font-family: monospace; font-size: 12px;")
        
        version_lbl = QLabel(f"Version: {app_data['version']}  •  Installed Size: {app_data['size']}")
        version_lbl.setStyleSheet("color: #9a9a9f; font-size: 12px;")
        
        header_text.addWidget(title)
        header_text.addWidget(pkg_id)
        header_text.addWidget(version_lbl)
        
        header.addWidget(icon_lbl)
        header.addLayout(header_text)
        header.addStretch()
        
        self.right_layout.addLayout(header)
        
        # Frame Divider
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("background-color: #2d2d34; max-height: 1px;")
        self.right_layout.addWidget(divider)
        
        # Details Layout
        desc_title = QLabel("Description")
        desc_title.setStyleSheet("font-weight: bold; color: #fff; font-size: 13px;")
        self.right_layout.addWidget(desc_title)
        
        desc_lbl = QLabel(app_data['desc'])
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("color: #9a9a9f; font-size: 13px; line-height: 1.5;")
        self.right_layout.addWidget(desc_lbl)
        
        # Unused Dependencies Panel
        deps_title = QLabel("Dependencies to be cleaned up")
        deps_title.setStyleSheet("font-weight: bold; color: #fff; font-size: 13px;")
        self.right_layout.addWidget(deps_title)
        
        deps_container = QWidget()
        deps_container_layout = QHBoxLayout(deps_container)
        deps_container_layout.setContentsMargins(0, 0, 0, 0)
        deps_container_layout.setSpacing(6)
        
        if app_data['depends']:
            # Create a simple scrollable row of dependency tags
            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            scroll_area.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")
            scroll_widget = QWidget()
            scroll_layout = QHBoxLayout(scroll_widget)
            scroll_layout.setContentsMargins(0, 0, 0, 0)
            scroll_layout.setSpacing(6)
            scroll_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
            
            for dep in app_data['depends']:
                dep_lbl = QLabel(dep)
                dep_lbl.setStyleSheet("""
                    background-color: #272730; color: #f4f4f5; 
                    font-size: 11px; padding: 4px 8px; border-radius: 4px;
                    border: 1px solid #3c3c45;
                """)
                scroll_layout.addWidget(dep_lbl)
                
            scroll_widget.setLayout(scroll_layout)
            scroll_area.setWidget(scroll_widget)
            self.right_layout.addWidget(scroll_area)
        else:
            no_deps = QLabel("None (Standalone package)")
            no_deps.setStyleSheet("color: #71717a; font-size: 12px; font-style: italic;")
            self.right_layout.addWidget(no_deps)
            
        self.right_layout.addStretch()
        
        # Destructive Action Crimson Button with security lock
        uninstall_btn = QPushButton("🔒  Clean Uninstall")
        uninstall_btn.setStyleSheet("""
            QPushButton {
                background-color: #e01b24; color: #ffffff;
                border: none; border-radius: 8px; padding: 14px; 
                font-weight: bold; font-size: 14px;
            }
            QPushButton:hover {
                background-color: #c01c28;
            }
            QPushButton:pressed {
                background-color: #a51d24;
            }
        """)
        uninstall_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        uninstall_btn.clicked.connect(lambda: self.trigger_uninstall(app_data['package']))
        self.right_layout.addWidget(uninstall_btn)

    def trigger_uninstall(self, package):
        dialog = UninstallDialog(package, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Successfully uninstalled; find and delete matching list record
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                row_widget = self.list_widget.itemWidget(item)
                if row_widget.app_data['package'] == package:
                    self.list_widget.takeItem(i)
                    break
            self.update_stats()


# --- Startup Authentication and Elevation ---
def authenticate_at_startup():
    """Prompts for authentication immediately upon execution.
    Caches polkit credentials so subsequent operations don't request passwords."""
    try:
        res = subprocess.run(["pkexec", "true"], capture_output=True)
        return res.returncode == 0
    except Exception:
        return False


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Prompt for admin authentication up front before rendering the GUI
    if not authenticate_at_startup():
        QMessageBox.critical(None, "Authentication Cancelled", "Admin access is required to purge system packages. Exiting.")
        sys.exit(0)
        
    window = MainWindow()
    window.show()
    sys.exit(app.exec())