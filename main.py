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
                             QDialog, QProgressBar, QPlainTextEdit, QMessageBox,
                             QStackedWidget, QComboBox, QCheckBox, QScrollArea)
from PyQt6.QtGui import QPixmap, QIcon, QFont
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QProcess, QSize

# --- Helper Utilities ---
def parse_size_to_bytes(size_str):
    try:
        match = re.match(r"([\d\.]+)\s*([a-zA-Z]+)", size_str)
        if not match: return 0
        value = float(match.group(1))
        unit = match.group(2).lower()
        if 'ki' in unit or 'k' in unit: return int(value * 1024)
        elif 'mi' in unit or 'm' in unit: return int(value * 1024 * 1024)
        elif 'gi' in unit or 'g' in unit: return int(value * 1024 * 1024 * 1024)
        return int(value)
    except Exception: return 0

def format_bytes_to_human(bytes_val):
    for unit in ['B', 'KiB', 'MiB', 'GiB', 'TiB']:
        if bytes_val < 1024.0:
            return f"{bytes_val:.2f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.2f} PiB"

def run_cmd_output(cmd_list):
    try:
        res = subprocess.run(cmd_list, capture_output=True, text=True)
        return res.stdout.strip()
    except Exception: return ""

def get_dir_size(path):
    """Calculates directory size using du"""
    try:
        if os.path.exists(path):
            res = run_cmd_output(["du", "-sb", path])
            return int(res.split()[0])
        return 0
    except Exception: return 0


# --- Generic Real-Time Process Runner Dialog ---
class ActionRunnerDialog(QDialog):
    def __init__(self, title, command, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(600, 400)
        self.setStyleSheet("background-color: #131316; color: #f4f4f5;")
        
        layout = QVBoxLayout(self)
        
        self.status_lbl = QLabel(f"Executing: {' '.join(command)}")
        self.status_lbl.setStyleSheet("font-weight: bold; font-size: 14px; color: #1793d1;")
        layout.addWidget(self.status_lbl)
        
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setStyleSheet("""
            QProgressBar { border: 1px solid #2d2d34; border-radius: 6px; text-align: center; background-color: #1e1e24; color: #fff; height: 20px;}
            QProgressBar::chunk { background-color: #1793d1; }
        """)
        layout.addWidget(self.progress)
        
        self.log_area = QPlainTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet("""
            QPlainTextEdit { background-color: #0b0b0d; color: #22c55e; font-family: monospace; font-size: 11px; border: 1px solid #2d2d34; border-radius: 6px; }
        """)
        layout.addWidget(self.log_area)
        
        self.close_btn = QPushButton("Close")
        self.close_btn.setEnabled(False)
        self.close_btn.setStyleSheet("""
            QPushButton { background-color: #2d2d34; color: #9a9a9f; border-radius: 6px; padding: 10px 20px; font-weight: bold; border: none;}
            QPushButton:enabled { background-color: #1793d1; color: #fff; }
            QPushButton:enabled:hover { background-color: #137bb0; }
        """)
        self.close_btn.clicked.connect(self.accept)
        layout.addWidget(self.close_btn)
        
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.process_finished)
        self.process.start(command[0], command[1:])
        
    def read_output(self):
        data = self.process.readAllStandardOutput()
        self.log_area.appendPlainText(bytes(data).decode("utf-8", errors="ignore").rstrip())

    def process_finished(self, exit_code, exit_status):
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.close_btn.setEnabled(True)
        if exit_code == 0:
            self.status_lbl.setText("Task completed successfully.")
            self.status_lbl.setStyleSheet("font-weight: bold; font-size: 14px; color: #22c55e;")
        else:
            self.status_lbl.setText("Task terminated or failed.")
            self.status_lbl.setStyleSheet("font-weight: bold; font-size: 14px; color: #ef4444;")


# --- System Analysis Worker ---
class SystemAnalyzerThread(QThread):
    finished_apps = pyqtSignal(list)
    finished_junk = pyqtSignal(dict)
    finished_docker = pyqtSignal(dict)

    def run(self):
        # 1. Packages
        apps = self.scan_packages()
        self.finished_apps.emit(apps)
        
        # 2. System Junk Stats
        junk_data = {
            'pacman_cache': get_dir_size('/var/cache/pacman/pkg'),
            'user_cache': get_dir_size(os.path.expanduser('~/.cache')),
            'journal_logs': self.get_journal_size(),
            'orphans': len(run_cmd_output(["pacman", "-Qtdq"]).splitlines())
        }
        self.finished_junk.emit(junk_data)

        # 3. Docker Stats
        docker_active = "active" in run_cmd_output(["systemctl", "is-active", "docker"]).lower()
        d_stats = {'active': docker_active, 'images': 0, 'containers': 0}
        if docker_active:
            d_stats['images'] = len(run_cmd_output(["docker", "images", "-q"]).splitlines())
            d_stats['containers'] = len(run_cmd_output(["docker", "ps", "-aq"]).splitlines())
        self.finished_docker.emit(d_stats)

    def get_journal_size(self):
        try:
            out = run_cmd_output(["journalctl", "--disk-usage"])
            match = re.search(r'([\d\.]+[KMG]?)', out)
            if match:
                # Naive conversion for Journalctl string format to bytes
                val_str = match.group(1).replace('K', 'KiB').replace('M', 'MiB').replace('G', 'GiB')
                return parse_size_to_bytes(val_str)
            return 0
        except Exception: return 0

    def scan_packages(self):
        res = subprocess.run(["pacman", "-Qei"], capture_output=True, text=True)
        packages, current_pkg = {}, None
        for line in res.stdout.splitlines():
            if line.startswith("Name            :"):
                current_pkg = line.split(":", 1)[1].strip()
                packages[current_pkg] = {
                    "name": current_pkg, "desc": "No description.", "size": "0 B", "size_bytes": 0,
                    "is_gui": False, "icon_name": "package-x-generic", "icon_path": None,
                    "friendly_name": current_pkg, "version": "Unknown", "depends": []
                }
            elif line.startswith("Description     :") and current_pkg: packages[current_pkg]["desc"] = line.split(":", 1)[1].strip()
            elif line.startswith("Version         :") and current_pkg: packages[current_pkg]["version"] = line.split(":", 1)[1].strip()
            elif line.startswith("Installed Size  :") and current_pkg: 
                sz = line.split(":", 1)[1].strip()
                packages[current_pkg]["size"], packages[current_pkg]["size_bytes"] = sz, parse_size_to_bytes(sz)
            elif line.startswith("Depends On      :") and current_pkg:
                deps_raw = line.split(":", 1)[1].strip()
                packages[current_pkg]["depends"] = [re.split(r'[<>=]', d)[0] for d in deps_raw.split() if d != "None"]
        
        # Link to desktop files to flag as GUI apps
        desktop_files = glob.glob("/usr/share/applications/*.desktop") + glob.glob(os.path.expanduser("~/.local/share/applications/*.desktop"))
        for df in desktop_files:
            try:
                content = open(df, 'r', errors='ignore').read()
                if "[Desktop Entry]" not in content or "NoDisplay=true" in content: continue
                lines = content.split("[Desktop Entry]")[1].split("[")[0]
                name, exec_cmd = re.search(r'\nName=(.*)', lines), re.search(r'\nExec=([^\s]+)', lines)
                if exec_cmd and name:
                    cmd_base = os.path.basename(exec_cmd.group(1).replace('"', ''))
                    if cmd_base in packages:
                        packages[cmd_base]['is_gui'] = True
                        packages[cmd_base]['friendly_name'] = name.group(1).strip()
            except Exception: pass
        return list(packages.values())


# --- Base Modules / Widgets ---

class AppListRow(QWidget):
    def __init__(self, app_data, parent=None):
        super().__init__(parent)
        self.app_data = app_data
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.icon_lbl = QLabel("📦")
        self.icon_lbl.setStyleSheet("font-size: 20px;")
        
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


class AppManagerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        main_layout = QHBoxLayout(self)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(2)
        main_layout.addWidget(self.splitter)
        
        # Left Panel
        left_pane = QWidget()
        left_layout = QVBoxLayout(left_pane)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["🎨 GUI Applications Only", "🖥️ All Packages (GUI + CLI)"])
        self.filter_combo.setStyleSheet("QComboBox { background-color: #272730; color: #fff; border-radius: 4px; padding: 6px; }")
        self.filter_combo.currentIndexChanged.connect(self.trigger_filter)
        left_layout.addWidget(self.filter_combo)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search apps & packages...")
        self.search_bar.setStyleSheet("QLineEdit { background-color: #16161a; border: 1px solid #2d2d34; border-radius: 6px; padding: 10px; color: #ffffff; }")
        self.search_bar.textChanged.connect(self.trigger_filter)
        left_layout.addWidget(self.search_bar)
        
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("QListWidget { background-color: #16161a; border: 1px solid #2d2d34; border-radius: 8px; } QListWidget::item:hover { background-color: #272730; } QListWidget::item:selected { background-color: #1793d1; }")
        self.list_widget.currentItemChanged.connect(self.app_selected)
        left_layout.addWidget(self.list_widget)
        
        self.splitter.addWidget(left_pane)
        
        # Right Panel
        self.right_pane = QWidget()
        self.right_layout = QVBoxLayout(self.right_pane)
        self.placeholder_lbl = QLabel("Select an app/package to manage.")
        self.placeholder_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.right_layout.addWidget(self.placeholder_lbl)
        self.splitter.addWidget(self.right_pane)
        self.splitter.setSizes([350, 450])

    def trigger_filter(self):
        query = self.search_bar.text().lower()
        gui_only = self.filter_combo.currentIndex() == 0
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            app = self.list_widget.itemWidget(item).app_data
            
            gui_match = True if not gui_only else app['is_gui']
            text_match = query in app['name'].lower() or query in app['friendly_name'].lower() or query in app['desc'].lower()
            item.setHidden(not (gui_match and text_match))

    def populate(self, apps):
        for app in apps:
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 52))
            row = AppListRow(app)
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, row)
        self.trigger_filter()

    def app_selected(self, current, previous):
        while self.right_layout.count():
            item = self.right_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
            
        if not current: return
        app_data = self.list_widget.itemWidget(current).app_data
        
        title = QLabel(app_data['friendly_name'])
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        self.right_layout.addWidget(title)
        
        info = QLabel(f"<b>Package:</b> {app_data['name']} <br><b>Version:</b> {app_data['version']} <br><b>Size:</b> {app_data['size']}")
        info.setStyleSheet("color: #9a9a9f;")
        self.right_layout.addWidget(info)
        
        desc = QLabel(app_data['desc'])
        desc.setWordWrap(True)
        self.right_layout.addWidget(desc)
        
        self.right_layout.addStretch()
        
        rm_btn = QPushButton("🔒 Clean Uninstall Package (-Rns)")
        rm_btn.setStyleSheet("QPushButton { background-color: #e01b24; color: #fff; font-weight: bold; border-radius: 8px; padding: 12px; } QPushButton:hover { background-color: #c01c28; }")
        rm_btn.clicked.connect(lambda: self.run_remove(app_data['name']))
        self.right_layout.addWidget(rm_btn)

    def run_remove(self, pkg):
        dlg = ActionRunnerDialog(f"Removing {pkg}", ["pkexec", "pacman", "-Rns", "--noconfirm", pkg], self)
        dlg.exec()


# --- Junk Cleaner & Docker Widgets ---
class OverviewCard(QWidget):
    def __init__(self, title, desc, action_btn_text, command):
        super().__init__()
        self.command = command
        layout = QVBoxLayout(self)
        self.setStyleSheet("background-color: #272730; border-radius: 8px;")
        
        t = QLabel(title)
        t.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.desc_lbl = QLabel(desc)
        self.desc_lbl.setStyleSheet("color: #9a9a9f;")
        
        btn = QPushButton(action_btn_text)
        btn.setStyleSheet("background-color: #1793d1; color: white; padding: 8px; border-radius: 4px; font-weight:bold;")
        btn.clicked.connect(self.run_task)
        
        layout.addWidget(t)
        layout.addWidget(self.desc_lbl)
        layout.addWidget(btn)

    def run_task(self):
        dlg = ActionRunnerDialog("Cleaning Routine", self.command, self)
        dlg.exec()


# --- Main Application Shell ---
class MainShell(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Arch System Optimizer")
        self.resize(1000, 700)
        self.setStyleSheet("background-color: #1e1e24; color: #ffffff; font-family: Inter, Fira Sans, sans-serif;")
        
        shell_layout = QHBoxLayout()
        shell_layout.setContentsMargins(0,0,0,0)
        shell_layout.setSpacing(0)
        
        # Sidebar Menu
        self.sidebar = QWidget()
        self.sidebar.setFixedWidth(220)
        self.sidebar.setStyleSheet("background-color: #121215; border-right: 1px solid #2d2d34;")
        side_layout = QVBoxLayout(self.sidebar)
        side_layout.setContentsMargins(10, 20, 10, 20)
        
        title = QLabel("Arch Optimizer")
        title.setStyleSheet("font-size: 20px; font-weight: 900; color: #1793d1; padding-bottom: 20px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side_layout.addWidget(title)

        self.btns = []
        menus = [("📦 Applications", 0), ("🧹 System Junk", 1), ("🐳 Docker Studio", 2), ("⚡ Auto Sweep", 3)]
        
        for text, idx in menus:
            btn = QPushButton(text)
            btn.setStyleSheet("""
                QPushButton { text-align: left; padding: 12px; font-size: 14px; font-weight: bold; background: transparent; border-radius: 6px; color: #9a9a9f; }
                QPushButton:hover { background-color: #1e1e24; color: #fff; }
                QPushButton:checked { background-color: #1793d1; color: #fff; }
            """)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, i=idx: self.switch_tab(i))
            self.btns.append(btn)
            side_layout.addWidget(btn)
        
        side_layout.addStretch()
        shell_layout.addWidget(self.sidebar)

        # Central View Manager (Stacked)
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background-color: #1e1e24;")
        
        # Add Views
        self.app_manager = AppManagerWidget()
        self.junk_tab = QWidget()
        self.docker_tab = QWidget()
        self.auto_tab = QWidget()
        
        self.stack.addWidget(self.app_manager)   # 0
        self.stack.addWidget(self.junk_tab)      # 1
        self.stack.addWidget(self.docker_tab)    # 2
        self.stack.addWidget(self.auto_tab)      # 3
        
        shell_layout.addWidget(self.stack)
        
        central = QWidget()
        central.setLayout(shell_layout)
        self.setCentralWidget(central)
        
        self.setup_ui_skeletons()
        self.switch_tab(0)

        # Start background scans
        self.scanner = SystemAnalyzerThread()
        self.scanner.finished_apps.connect(self.app_manager.populate)
        self.scanner.finished_junk.connect(self.populate_junk)
        self.scanner.finished_docker.connect(self.populate_docker)
        self.scanner.start()

    def switch_tab(self, index):
        for i, btn in enumerate(self.btns):
            btn.setChecked(i == index)
        self.stack.setCurrentIndex(index)

    def setup_ui_skeletons(self):
        # Build Junk Skeleton
        j_lay = QVBoxLayout(self.junk_tab)
        j_lay.setContentsMargins(20,20,20,20)
        lbl = QLabel("🧹 Clean System Leftovers")
        lbl.setStyleSheet("font-size: 22px; font-weight:bold; color: #fff;")
        j_lay.addWidget(lbl)
        
        self.junk_container = QVBoxLayout()
        j_lay.addLayout(self.junk_container)
        j_lay.addStretch()

        # Build Docker Skeleton
        d_lay = QVBoxLayout(self.docker_tab)
        d_lay.setContentsMargins(20,20,20,20)
        dlbl = QLabel("🐳 Docker Environments")
        dlbl.setStyleSheet("font-size: 22px; font-weight:bold; color: #1793d1;")
        d_lay.addWidget(dlbl)
        self.docker_container = QVBoxLayout()
        d_lay.addLayout(self.docker_container)
        d_lay.addStretch()

        # Build Auto-Clean Skeleton
        a_lay = QVBoxLayout(self.auto_tab)
        a_lay.setContentsMargins(30,30,30,30)
        a_lbl = QLabel("⚡ 1-Click Complete System Sweep")
        a_lbl.setStyleSheet("font-size: 24px; font-weight:bold;")
        a_lay.addWidget(a_lbl)
        a_info = QLabel("Check boxes to safely sweep all configured locations in one click.")
        a_lay.addWidget(a_info)
        
        self.chk_pacman = QCheckBox("Wipe old pacman cache (Keeps 1 latest version)")
        self.chk_journal = QCheckBox("Truncate system journal logs (> 30 days)")
        self.chk_orphans = QCheckBox("Remove orphaned Pacman packages")
        for cb in [self.chk_pacman, self.chk_journal, self.chk_orphans]:
            cb.setStyleSheet("font-size: 15px; margin: 10px 0;")
            cb.setChecked(True)
            a_lay.addWidget(cb)
            
        a_lay.addStretch()
        
        sweep_btn = QPushButton("🔒 Start Automated Sweep")
        sweep_btn.setStyleSheet("""
            QPushButton { background-color: #1793d1; color: white; padding: 16px; border-radius: 8px; font-size: 18px; font-weight: bold; }
            QPushButton:hover { background-color: #137bb0; }
        """)
        sweep_btn.clicked.connect(self.run_auto_sweep)
        a_lay.addWidget(sweep_btn)

    def populate_junk(self, junk):
        # Pacman Cache
        sz1 = format_bytes_to_human(junk['pacman_cache'])
        c1 = OverviewCard("📦 Pacman Cache Directory", f"Occupies: {sz1}", "Clean All but 1 version (paccache)", ["pkexec", "paccache", "-rk1"])
        self.junk_container.addWidget(c1)
        
        # Journal Logs
        sz2 = format_bytes_to_human(junk['journal_logs'])
        c2 = OverviewCard("📝 Systemd Journal Logs", f"Occupies: {sz2}", "Vacuum Logs (> 2 weeks)", ["pkexec", "journalctl", "--vacuum-time=2w"])
        self.junk_container.addWidget(c2)
        
        # User Cache
        sz3 = format_bytes_to_human(junk['user_cache'])
        c3 = OverviewCard("👤 User Home Cache (~/.cache)", f"Occupies: {sz3}", "Empty specific caches", ["bash", "-c", "rm -rf ~/.cache/*"])
        self.junk_container.addWidget(c3)

        # Orphans
        sz4 = str(junk['orphans']) + " packages"
        c4 = OverviewCard("👻 Orphaned Packages", f"Found: {sz4}", "Remove Orphaned Software", ["pkexec", "sh", "-c", "pacman -Qtdq | pacman -Rns - || echo 'No orphans'"])
        self.junk_container.addWidget(c4)

    def populate_docker(self, d_stats):
        if not d_stats['active']:
            self.docker_container.addWidget(QLabel("Docker service is currently inactive or not installed."))
            return
            
        stat_lbl = QLabel(f"<b>Images found:</b> {d_stats['images']}  |  <b>Containers:</b> {d_stats['containers']}")
        stat_lbl.setStyleSheet("font-size: 14px; margin-bottom: 20px;")
        self.docker_container.addWidget(stat_lbl)
        
        c = OverviewCard("🧹 Deep Clean Docker Storage", "Purge all unused/dangling containers, images, and networks.", "Run System Prune", ["pkexec", "docker", "system", "prune", "-a", "-f"])
        self.docker_container.addWidget(c)

    def run_auto_sweep(self):
        # We stitch a bash script together based on selections to run cleanly under ONE Polkit prompt.
        script_cmds = []
        if self.chk_pacman.isChecked(): script_cmds.append("echo '==> Cleaning Pacman Cache'; paccache -rk1 || pacman -Sc --noconfirm")
        if self.chk_journal.isChecked(): script_cmds.append("echo '==> Truncating Journal Logs'; journalctl --vacuum-time=30d")
        if self.chk_orphans.isChecked(): script_cmds.append("echo '==> Removing Orphans'; orphans=$(pacman -Qtdq); if [ -n \"$orphans\" ]; then pacman -Rns --noconfirm $orphans; else echo 'No orphans found.'; fi")
        
        full_script = "\n".join(script_cmds)
        dlg = ActionRunnerDialog("Automated Complete Sweep", ["pkexec", "sh", "-c", full_script], self)
        dlg.exec()


# --- Application Entry Point ---
def authenticate_at_startup():
    try:
        return subprocess.run(["pkexec", "true"], capture_output=True).returncode == 0
    except Exception: return False

if __name__ == "__main__":
    app = QApplication(sys.argv)
    if not authenticate_at_startup():
        QMessageBox.critical(None, "Auth Required", "Admin authentication is required to access system components.")
        sys.exit(0)
        
    window = MainShell()
    window.show()
    sys.exit(app.exec())