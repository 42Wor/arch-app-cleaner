#!/usr/bin/env python3
import sys
import os
import subprocess
import re
import glob
import shutil
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                             QScrollArea, QFrame, QMessageBox, QSizePolicy)
from PyQt6.QtGui import QPixmap, QIcon, QFont
from PyQt6.QtCore import Qt, QThread, pyqtSignal

# --- Worker Thread for Scanning (Prevents UI freezing) ---
class AppScanner(QThread):
    finished = pyqtSignal(list)

    def run(self):
        apps = self.get_gui_apps()
        self.finished.emit(apps)

    def get_all_packages_info(self):
        res = subprocess.run(["pacman", "-Qi"], capture_output=True, text=True)
        packages = {}
        current_pkg = None
        for line in res.stdout.splitlines():
            if line.startswith("Name"):
                current_pkg = line.split(":", 1)[1].strip()
                packages[current_pkg] = {}
            elif line.startswith("Description") and current_pkg:
                packages[current_pkg]["desc"] = line.split(":", 1)[1].strip()
            elif line.startswith("Installed Size") and current_pkg:
                packages[current_pkg]["size"] = line.split(":", 1)[1].strip()
        return packages

    def find_icon_path(self, icon_name):
        if not icon_name: return None
        if os.path.isabs(icon_name) and os.path.exists(icon_name): return icon_name
        
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
                if os.path.exists(path): return path
                    
        for root, dirs, files in os.walk("/usr/share/icons", followlinks=True):
            if len(root.split(os.sep)) > 6: continue
            for ext in [".png", ".svg"]:
                if (icon_name + ext) in files:
                    return os.path.join(root, icon_name + ext)
        return None

    def get_gui_apps(self):
        pkg_info = self.get_all_packages_info()
        installed_packages = set(pkg_info.keys())
        apps = []
        
        desktop_files = glob.glob("/usr/share/applications/*.desktop")
        for df in desktop_files:
            try:
                with open(df, 'r', errors='ignore') as f:
                    content = f.read()
                
                if "NoDisplay=true" in content or "NoDisplay=True" in content: continue
                if "[Desktop Entry]" not in content: continue
                
                entry_lines = content.split("[Desktop Entry]")[1].split("[")[0]
                name, icon, exec_cmd, comment = None, None, None, ""
                
                for line in entry_lines.splitlines():
                    if line.startswith("Name="): name = line.split("=", 1)[1].strip()
                    elif line.startswith("Icon="): icon = line.split("=", 1)[1].strip()
                    elif line.startswith("Exec="):
                        raw_exec = line.split("=", 1)[1].strip()
                        exec_cmd = re.sub(r'%\w', '', raw_exec).strip().split()[0]
                        exec_cmd = os.path.basename(exec_cmd).strip('"\'')
                    elif line.startswith("Comment="): comment = line.split("=", 1)[1].strip()
                
                if not name or not exec_cmd: continue
                
                pkg_name = None
                if exec_cmd in installed_packages:
                    pkg_name = exec_cmd
                else:
                    binary_path = shutil.which(exec_cmd)
                    if binary_path:
                        res = subprocess.run(["pacman", "-Qo", binary_path], capture_output=True, text=True)
                        if res.returncode == 0:
                            pkg_name = res.stdout.strip().split()[-2]
                
                if pkg_name and pkg_name in installed_packages:
                    apps.append({
                        "name": name, "package": pkg_name, 
                        "icon": self.find_icon_path(icon),
                        "desc": comment or pkg_info[pkg_name].get("desc", ""),
                        "size": pkg_info[pkg_name].get("size", "Unknown")
                    })
            except Exception:
                pass
                
        seen = set()
        unique_apps = []
        for app in apps:
            if app["package"] not in seen:
                seen.add(app["package"])
                unique_apps.append(app)
                
        unique_apps.sort(key=lambda x: x["name"].lower())
        return unique_apps

# --- UI Components ---
class AppCard(QFrame):
    def __init__(self, app_data, parent_window):
        super().__init__()
        self.app_data = app_data
        self.parent_window = parent_window
        
        self.setObjectName("AppCard")
        self.setStyleSheet("""
            #AppCard {
                background-color: #1e1e1e;
                border: 1px solid #333;
                border-radius: 8px;
                margin-bottom: 5px;
            }
            #AppCard:hover { border: 1px solid #0ea5e9; }
        """)
        
        layout = QHBoxLayout(self)
        
        # Icon
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(48, 48)
        if app_data['icon'] and os.path.exists(app_data['icon']):
            pixmap = QPixmap(app_data['icon']).scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.icon_label.setPixmap(pixmap)
        else:
            self.icon_label.setText("📦")
            self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.icon_label.setStyleSheet("font-size: 24px;")
            
        # Details
        details_layout = QVBoxLayout()
        title = QLabel(f"<b>{app_data['name']}</b> ({app_data['package']})")
        title.setStyleSheet("color: white; font-size: 14px;")
        desc = QLabel(app_data['desc'])
        desc.setStyleSheet("color: #aaa; font-size: 12px;")
        size = QLabel(f"Size: {app_data['size']}")
        size.setStyleSheet("color: #777; font-size: 11px;")
        
        details_layout.addWidget(title)
        details_layout.addWidget(desc)
        details_layout.addWidget(size)
        
        # Uninstall Button
        self.btn = QPushButton("Uninstall Cleanly")
        self.btn.setStyleSheet("""
            QPushButton {
                background-color: #7f1d1d; color: #fca5a5;
                border: 1px solid #991b1b; border-radius: 6px; padding: 8px 12px; font-weight: bold;
            }
            QPushButton:hover { background-color: #991b1b; border: 1px solid #b91c1c; color: white; }
        """)
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.clicked.connect(self.uninstall)
        
        layout.addWidget(self.icon_label)
        layout.addLayout(details_layout)
        layout.addStretch()
        layout.addWidget(self.btn)

    def uninstall(self):
        self.btn.setText("Uninstalling...")
        self.btn.setEnabled(False)
        self.parent_window.trigger_uninstall(self.app_data['package'], self)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Arch Software Cleaner")
        self.resize(800, 600)
        self.setStyleSheet("background-color: #121212;")
        
        self.cards = []
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Header
        header_layout = QHBoxLayout()
        title = QLabel("Arch Software Cleaner")
        title.setStyleSheet("color: #0ea5e9; font-size: 24px; font-weight: bold;")
        
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search apps...")
        self.search_bar.setStyleSheet("""
            QLineEdit {
                background-color: #1e1e1e; border: 1px solid #333;
                border-radius: 6px; padding: 8px; color: white;
            }
            QLineEdit:focus { border: 1px solid #0ea5e9; }
        """)
        self.search_bar.textChanged.connect(self.filter_apps)
        
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.search_bar)
        main_layout.addLayout(header_layout)
        
        # Scroll Area for Apps
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; }")
        
        self.scroll_widget = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self.status_label = QLabel("Scanning installed GUI applications... Please wait.")
        self.status_label.setStyleSheet("color: #aaa; font-size: 14px;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_layout.addWidget(self.status_label)
        
        self.scroll.setWidget(self.scroll_widget)
        main_layout.addWidget(self.scroll)
        
        # Start scanning
        self.scanner = AppScanner()
        self.scanner.finished.connect(self.populate_apps)
        self.scanner.start()

    def populate_apps(self, apps):
        self.status_label.deleteLater()
        if not apps:
            lbl = QLabel("No graphical applications found.")
            lbl.setStyleSheet("color: white;")
            self.scroll_layout.addWidget(lbl)
            return
            
        for app in apps:
            card = AppCard(app, self)
            self.cards.append(card)
            self.scroll_layout.addWidget(card)

    def filter_apps(self, text):
        query = text.lower()
        for card in self.cards:
            app = card.app_data
            match = query in app['name'].lower() or query in app['package'].lower() or query in app['desc'].lower()
            card.setVisible(match)

    def trigger_uninstall(self, package, card_widget):
        cmd = ["pkexec", "pacman", "-Rns", "--noconfirm", package]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                card_widget.deleteLater()
                self.cards.remove(card_widget)
                QMessageBox.information(self, "Success", f"Cleanly uninstalled {package}!")
            else:
                QMessageBox.critical(self, "Error", f"Failed to uninstall {package}.\n\n{res.stderr.strip() or res.stdout.strip()}")
                card_widget.btn.setText("Uninstall Cleanly")
                card_widget.btn.setEnabled(True)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            card_widget.btn.setText("Uninstall Cleanly")
            card_widget.btn.setEnabled(True)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
