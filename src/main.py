import json
import os
import shlex
import shutil
import subprocess
import sys
from urllib.parse import urlparse

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QPlainTextEdit, QComboBox, QProgressBar,
    QFileDialog, QMessageBox, QCheckBox, QListWidget, QListWidgetItem,
    QGroupBox, QFormLayout
)
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QDragEnterEvent, QDropEvent, QIcon

# --- Repository GitHub per il controllo aggiornamenti ---
GITHUB_REPO = "enkas79/downloader"
APP_AUTHOR = "enkas79"

THEMES = {
    "dark": "theme_dark.qss",
    "light": "theme_light.qss",
}

# Domini di piattaforme note per usare DRM (Widevine/PlayReady) che yt-dlp
# non è in grado di decifrare: il download da questi siti non è supportato.
DRM_PROTECTED_DOMAINS = [
    "netflix.com",
    "primevideo.com",
]


# --- Funzioni di utilità ---

def get_app_dir():
    """Restituisce la root del progetto (cartella che contiene version.txt e downloader.svg)."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(script_dir) == "src":
        return os.path.dirname(script_dir)
    return script_dir


def get_settings_dir():
    """Cartella dati utente persistente per le impostazioni dell'applicazione."""
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
    elif sys.platform == "darwin":
        base = os.path.join(home, "Library", "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.join(home, ".config"))
    return os.path.join(base, "YTDownloader")


def get_current_version():
    """Legge la versione corrente da version.txt."""
    version_file = os.path.join(get_app_dir(), "version.txt")
    try:
        with open(version_file, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "0.0.0"


def get_default_downloads_path():
    """Restituisce il percorso predefinito della cartella Downloads."""
    return os.path.join(os.path.expanduser("~"), "Downloads")


def load_theme(app, theme_name="dark"):
    """Applica il foglio di stile QSS del tema richiesto, se presente."""
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    theme_file = THEMES.get(theme_name, THEMES["dark"])
    theme_path = os.path.join(base_dir, theme_file)
    try:
        with open(theme_path, "r") as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        pass


def available_themes():
    """Restituisce i nomi interni dei temi disponibili."""
    return list(THEMES.keys())


def is_drm_protected_url(url):
    """Verifica se l'URL appartiene a una piattaforma con DRM non supportato (es. Netflix, Amazon Prime Video)."""
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return False
    return any(host == domain or host.endswith("." + domain) for domain in DRM_PROTECTED_DOMAINS)


def check_yt_dlp_installed():
    """Controlla se yt-dlp è installato e accessibile."""
    return shutil.which("yt-dlp") is not None


def is_newer_version(remote, current):
    """Confronta due versioni semantiche: True se remote è più recente di current."""
    def parse(version):
        parts = []
        for token in version.split("."):
            digits = ""
            for ch in token:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            parts.append(int(digits) if digits else 0)
        return tuple(parts)

    remote_parts = parse(remote)
    current_parts = parse(current)
    length = max(len(remote_parts), len(current_parts))
    remote_parts += (0,) * (length - len(remote_parts))
    current_parts += (0,) * (length - len(current_parts))
    return remote_parts > current_parts


# --- Thread per il download ---

class DownloadThread(QThread):
    progress_signal = pyqtSignal(int, str)  # (percentuale, URL)
    message_signal = pyqtSignal(str)  # Messaggio di log
    finished_signal = pyqtSignal(str, bool)  # (URL, successo)

    def __init__(self, url, output_path, format_type, quality,
                 playlist=False, subtitles=False, sub_lang="", cookies_path="", custom_args=""):
        super().__init__()
        self.url = url
        self.output_path = output_path
        self.format_type = format_type
        self.quality = quality
        self.playlist = playlist
        self.subtitles = subtitles
        self.sub_lang = sub_lang
        self.cookies_path = cookies_path
        self.custom_args = custom_args
        self._is_cancelled = False
        self._process = None

    def run(self):
        command = ["yt-dlp"] + self._build_args()

        try:
            self._process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            self.message_signal.emit(f"Errore avvio yt-dlp: {exc}")
            self.finished_signal.emit(self.url, False)
            return

        for line in self._process.stdout:
            line = line.strip()
            if not line:
                continue
            if "%" in line:
                self._emit_progress(line)
            else:
                self.message_signal.emit(line)
                if "drm" in line.lower():
                    self.message_signal.emit(
                        "⚠️ Contenuto protetto da DRM: yt-dlp non è in grado di scaricarlo."
                    )

        self._process.wait()
        success = (not self._is_cancelled) and self._process.returncode == 0
        self.finished_signal.emit(self.url, success)

    def _build_args(self):
        command = [
            "-o", os.path.join(self.output_path, "%(title)s.%(ext)s"),
            "--format", self._get_format(),
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/91.0.4472.124 Safari/537.36",
            "--progress-template", "%(progress._percent_str)s",
            "--newline",
        ]

        if self.playlist:
            command.append("--yes-playlist")
        if self.subtitles and self.sub_lang and self.format_type != "Audio":
            command.extend(["--write-subs", "--sub-lang", self.sub_lang])
        if self.cookies_path:
            command.extend(["--cookies", self.cookies_path])
        if self.custom_args:
            command.extend(shlex.split(self.custom_args))
        command.append(self.url)
        return command

    def _emit_progress(self, line):
        try:
            percent = int(float(line.rstrip("%").strip()))
            self.progress_signal.emit(percent, self.url)
        except ValueError:
            pass

    def _get_format(self):
        if self.format_type == "Video":
            if self.quality == "Alta":
                return "bestvideo[height>=1080]+bestaudio/best"
            elif self.quality == "Media":
                return "bestvideo[height>=720]+bestaudio/best"
            else:
                return "bestvideo[height>=480]+bestaudio/best"
        elif self.format_type == "Audio":
            return "bestaudio/best"
        else:
            return "best"


# --- Thread per il controllo aggiornamenti ---

class UpdateCheckThread(QThread):
    result_signal = pyqtSignal(bool, str, str)  # (aggiornamento_disponibile, versione_remota, changelog/errore)

    def run(self):
        try:
            import requests
            response = requests.get(
                f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                timeout=5,
            )
            response.raise_for_status()
            data = response.json()
            remote_version = data.get("tag_name", "").lstrip("v")
            changelog = data.get("body", "")
            current_version = get_current_version()
            is_newer = bool(remote_version) and is_newer_version(remote_version, current_version)
            self.result_signal.emit(is_newer, remote_version, changelog)
        except Exception as exc:
            self.result_signal.emit(False, "", str(exc))


# --- Finestra principale ---

class YTDLPGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YT-DLP Downloader Avanzato")
        self.setGeometry(100, 100, 800, 600)
        self.setAcceptDrops(True)
        icon_path = os.path.join(get_app_dir(), "downloader.svg")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(16, 16, 16, 16)
        self.layout.setSpacing(12)
        self.central_widget.setLayout(self.layout)

        self.download_queue = []
        self.active_threads = {}
        self.history = []
        self._update_thread = None
        self._download_counter = 0

        self._load_settings()
        self._create_menu()
        self._create_ui()
        load_theme(QApplication.instance(), self.current_theme)
        self._check_updates(manual=False)

    def _load_settings(self):
        try:
            with open(self._settings_path(), "r") as f:
                settings = json.load(f)
                self.default_output = settings.get("output_path", get_default_downloads_path())
                self.default_quality = settings.get("quality", "Alta")
                self.default_format = settings.get("format", "Video")
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self.default_output = get_default_downloads_path()
            self.default_quality = "Alta"
            self.default_format = "Video"
        self.current_theme = settings.get("theme", "dark") if isinstance(settings, dict) else "dark"
        if self.current_theme not in THEMES:
            self.current_theme = "dark"

    def _save_settings(self):
        settings = {
            "output_path": self.output_input.text(),
            "quality": self.quality_combo.currentText(),
            "format": self.format_combo.currentText(),
            "theme": self.current_theme,
        }
        try:
            os.makedirs(get_settings_dir(), exist_ok=True)
            with open(self._settings_path(), "w") as f:
                json.dump(settings, f)
        except OSError:
            pass

    @staticmethod
    def _settings_path():
        return os.path.join(get_settings_dir(), "settings.json")

    def _create_menu(self):
        view_menu = self.menuBar().addMenu("&Visualizza")

        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        self._theme_actions = {}
        theme_labels = {"dark": "Tema scuro", "light": "Tema chiaro"}
        for theme_name in available_themes():
            action = QAction(theme_labels.get(theme_name, theme_name), self, checkable=True)
            action.setChecked(theme_name == self.current_theme)
            action.triggered.connect(lambda checked, name=theme_name: self._switch_theme(name))
            self._theme_group.addAction(action)
            view_menu.addAction(action)
            self._theme_actions[theme_name] = action

        help_menu = self.menuBar().addMenu("&Aiuto")

        about_action = QAction("Informazioni", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

        update_action = QAction("Controlla aggiornamenti", self)
        update_action.triggered.connect(lambda: self._check_updates(manual=True))
        help_menu.addAction(update_action)

        guide_action = QAction("Guida", self)
        guide_action.triggered.connect(self._show_guide)
        help_menu.addAction(guide_action)

    def _switch_theme(self, theme_name):
        """Cambia il tema grafico applicato e aggiorna il menu."""
        if theme_name not in THEMES:
            return
        self.current_theme = theme_name
        load_theme(QApplication.instance(), theme_name)
        action = self._theme_actions.get(theme_name)
        if action is not None:
            action.setChecked(True)

    def _show_about(self):
        QMessageBox.about(
            self,
            "Informazioni",
            f"<b>YT-DLP Downloader Avanzato</b><br>"
            f"Versione: {get_current_version()}<br>"
            f"Autore: {APP_AUTHOR}",
        )

    def _show_guide(self):
        QMessageBox.information(
            self,
            "Guida",
            "1. Incolla l'URL del video o della playlist (o trascinalo nella finestra).\n"
            "2. Scegli formato, qualità e le opzioni desiderate.\n"
            "3. Seleziona la cartella di destinazione.\n"
            "4. Premi 'Scarica' per aggiungere il download alla coda.\n"
            "5. Usa 'Annulla tutto' per interrompere i download in corso.",
        )

    def _check_updates(self, manual=True):
        if self._update_thread and self._update_thread.isRunning():
            return
        self._update_thread = UpdateCheckThread()
        self._update_thread.result_signal.connect(
            lambda available, version, info: self._on_update_check_result(available, version, info, manual)
        )
        self._update_thread.start()

    def _on_update_check_result(self, available, remote_version, info, manual):
        if available:
            reply = QMessageBox.question(
                self,
                "Aggiornamento disponibile",
                f"È disponibile la versione {remote_version} (attuale: {get_current_version()}).\n\n"
                f"Changelog:\n{info}\n\nAprire la pagina di download?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                import webbrowser
                webbrowser.open(f"https://github.com/{GITHUB_REPO}/releases/latest")
        elif manual:
            if remote_version:
                QMessageBox.information(self, "Aggiornamenti", "Stai già usando l'ultima versione disponibile.")
            else:
                QMessageBox.warning(self, "Aggiornamenti", f"Impossibile verificare gli aggiornamenti.\n{info}")

    def _create_ui(self):
        # --- Sezione URL e opzioni ---
        url_group = QGroupBox("Download")
        url_layout = QFormLayout()
        url_layout.setSpacing(10)
        url_layout.setContentsMargins(8, 12, 8, 8)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Inserisci l'URL del video o playlist")
        url_layout.addRow("URL:", self.url_input)

        self.format_combo = QComboBox()
        self.format_combo.addItems(["Video", "Audio"])
        self.format_combo.setCurrentText(self.default_format)
        url_layout.addRow("Formato:", self.format_combo)

        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["Alta", "Media", "Bassa"])
        self.quality_combo.setCurrentText(self.default_quality)
        url_layout.addRow("Qualità:", self.quality_combo)

        self.playlist_checkbox = QCheckBox("Scarica playlist")
        url_layout.addRow(self.playlist_checkbox)

        self.subtitles_checkbox = QCheckBox("Scarica sottotitoli")
        self.sub_lang_input = QLineEdit("it,en")
        self.sub_lang_input.setEnabled(False)
        self.subtitles_checkbox.stateChanged.connect(
            lambda: self.sub_lang_input.setEnabled(self.subtitles_checkbox.isChecked())
        )
        url_layout.addRow(self.subtitles_checkbox)
        url_layout.addRow("Lingue sottotitoli:", self.sub_lang_input)

        self.cookies_button = QPushButton("Seleziona file cookie...")
        self.cookies_path = ""
        self.cookies_button.clicked.connect(self._select_cookies_file)
        url_layout.addRow("File cookie:", self.cookies_button)

        self.custom_args_input = QLineEdit()
        self.custom_args_input.setPlaceholderText("Es: --limit-rate 1M")
        url_layout.addRow("Opzioni yt-dlp:", self.custom_args_input)

        url_group.setLayout(url_layout)
        self.layout.addWidget(url_group)

        # --- Sezione cartella di output ---
        output_group = QGroupBox("Destinazione")
        output_layout = QHBoxLayout()

        self.output_input = QLineEdit(self.default_output)
        output_button = QPushButton("Sfoglia...")
        output_button.clicked.connect(self._select_output_folder)

        output_layout.addWidget(self.output_input)
        output_layout.addWidget(output_button)
        output_group.setLayout(output_layout)
        self.layout.addWidget(output_group)

        # --- Pulsanti di azione ---
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)

        self.download_button = QPushButton("Scarica")
        self.download_button.setObjectName("primaryButton")
        self.download_button.clicked.connect(self._add_to_queue)
        buttons_layout.addWidget(self.download_button)

        self.cancel_button = QPushButton("Annulla tutto")
        self.cancel_button.setObjectName("dangerButton")
        self.cancel_button.clicked.connect(self._cancel_all_downloads)
        buttons_layout.addWidget(self.cancel_button)

        self.exit_button = QPushButton("Esci")
        self.exit_button.clicked.connect(self._exit_app)
        buttons_layout.addWidget(self.exit_button)

        self.layout.addLayout(buttons_layout)

        # --- Barra di progresso e log ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.layout.addWidget(self.progress_bar)

        log_label = QLabel("Log:")
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumBlockCount(5000)
        self.layout.addWidget(log_label)
        self.layout.addWidget(self.log_output)

        # --- Coda dei download ---
        queue_group = QGroupBox("Coda dei download")
        self.queue_layout = QVBoxLayout()
        self.queue_list = QListWidget()
        self.queue_list.itemDoubleClicked.connect(self._remove_from_queue)
        self.queue_layout.addWidget(self.queue_list)
        queue_group.setLayout(self.queue_layout)
        self.layout.addWidget(queue_group)

        # --- Controllo dipendenze all'avvio ---
        if not check_yt_dlp_installed():
            QMessageBox.warning(
                self,
                "Errore",
                "yt-dlp non è installato o non è accessibile.\n"
                "Installa yt-dlp con: pip install yt-dlp"
            )

    def _select_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Seleziona cartella di output")
        if folder:
            self.output_input.setText(folder)

    def _select_cookies_file(self):
        file, _ = QFileDialog.getOpenFileName(self, "Seleziona file cookie", "", "Cookie Files (*.txt)")
        if file:
            self.cookies_path = file
            self.cookies_button.setText(os.path.basename(file))

    def _add_to_queue(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Errore", "Inserisci un URL valido.")
            return

        if is_drm_protected_url(url):
            QMessageBox.warning(
                self,
                "Piattaforma non supportata",
                "Netflix e Amazon Prime Video proteggono i video con DRM "
                "(Widevine/PlayReady): yt-dlp non può decifrarli, quindi il "
                "download da queste piattaforme non è supportato.\n\n"
                "Puoi scaricare da servizi senza DRM come YouTube o RaiPlay.",
            )
            return

        output_path = self.output_input.text().strip()
        if not output_path:
            QMessageBox.warning(self, "Errore", "Seleziona una cartella di output.")
            return

        # Aggiungi alla coda
        item = QListWidgetItem(f"{url} ({self.format_combo.currentText()}, {self.quality_combo.currentText()})")
        self.queue_list.addItem(item)
        self.download_queue.append({
            "url": url,
            "output_path": output_path,
            "format": self.format_combo.currentText(),
            "quality": self.quality_combo.currentText(),
            "playlist": self.playlist_checkbox.isChecked(),
            "subtitles": self.subtitles_checkbox.isChecked(),
            "sub_lang": self.sub_lang_input.text().strip(),
            "cookies_path": self.cookies_path,
            "custom_args": self.custom_args_input.text().strip(),
        })

        self.log_output.appendPlainText(f"Aggiunto alla coda: {url}")
        self.url_input.clear()

        # Se non ci sono download attivi, avvia il primo della coda
        if not self.active_threads:
            self._start_next_download()

    def _start_next_download(self):
        if not self.download_queue:
            self.progress_bar.setValue(0)
            return

        download = self.download_queue.pop(0)
        self.queue_list.takeItem(0)

        self._download_counter += 1
        download_id = self._download_counter

        thread = DownloadThread(
            url=download["url"],
            output_path=download["output_path"],
            format_type=download["format"],
            quality=download["quality"],
            playlist=download["playlist"],
            subtitles=download["subtitles"],
            sub_lang=download["sub_lang"],
            cookies_path=download["cookies_path"],
            custom_args=download["custom_args"],
        )
        thread.progress_signal.connect(self._update_progress)
        thread.message_signal.connect(self._update_log)
        thread.finished_signal.connect(
            lambda url, success, tid=download_id: self._on_download_finished(tid, url, success)
        )

        self.active_threads[download_id] = thread
        thread.start()
        self.log_output.appendPlainText(f"Avviato download: {download['url']}")

    def _on_download_finished(self, download_id, url, success):
        thread = self.active_threads.pop(download_id, None)
        if thread is not None:
            thread.wait()
        if success:
            self._update_log(f"Download completato: {url}")
        else:
            self._update_log(f"Download non riuscito o annullato: {url}")
        self._start_next_download()

    def _cancel_download(self, download_id):
        thread = self.active_threads.get(download_id)
        if thread is not None:
            thread.cancel()
            self._update_log(f"Download annullato: {thread.url}")

    def _update_progress(self, percent, url):
        self.progress_bar.setValue(percent)

    def _update_log(self, message):
        self.log_output.appendPlainText(message)

    def _cancel_all_downloads(self):
        for download_id in list(self.active_threads.keys()):
            self._cancel_download(download_id)
        for thread in self.active_threads.values():
            thread.wait(3000)
        self.download_queue.clear()
        self.queue_list.clear()
        self.progress_bar.setValue(0)
        self._update_log("Tutti i download sono stati annullati.")

    def _remove_from_queue(self, item):
        row = self.queue_list.row(item)
        if row >= 0:
            self.queue_list.takeItem(row)
            del self.download_queue[row]
            self._update_log(f"Rimosso dalla coda: {item.text()}")

    def _confirm_exit_with_active_downloads(self):
        reply = QMessageBox.question(
            self,
            "Download in corso",
            "Ci sono download attivi. Vuoi davvero uscire?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _exit_app(self):
        if self.active_threads and not self._confirm_exit_with_active_downloads():
            return
        self._save_settings()
        self._cancel_all_downloads()
        self.close()

    def closeEvent(self, event):
        if self.active_threads and not self._confirm_exit_with_active_downloads():
            event.ignore()
            return
        self._save_settings()
        self._cancel_all_downloads()
        event.accept()

    # --- Drag & Drop ---
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            url = urls[0].toString()
            if url.startswith("http"):
                self.url_input.setText(url)
                event.accept()
        else:
            event.ignore()


# --- Avvio dell'applicazione ---

if __name__ == "__main__":
    app = QApplication(sys.argv)
    load_theme(app)
    window = YTDLPGUI()
    window.show()
    sys.exit(app.exec())
