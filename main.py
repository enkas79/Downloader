import sys
import os
import json
import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QComboBox, QProgressBar,
    QFileDialog, QMessageBox, QCheckBox, QListWidget, QListWidgetItem,
    QGroupBox, QFormLayout
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QProcess, QUrl, QMimeData
from PyQt6.QtGui import QDragEnterEvent, QDropEvent


# --- Funzioni di utilità ---

def get_default_downloads_path():
    """Restituisce il percorso predefinito della cartella Downloads."""
    return os.path.join(os.path.expanduser("~"), "Downloads")


def check_yt_dlp_installed():
    """Controlla se yt-dlp è installato e accessibile."""
    try:
        import subprocess
        result = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False


# --- Thread per il download ---

class DownloadThread(QThread):
    progress_signal = pyqtSignal(int, str)  # (percentuale, URL)
    message_signal = pyqtSignal(str)  # Messaggio di log
    finished_signal = pyqtSignal(str, bool)  # (URL, successo)
    start_process_signal = pyqtSignal(list, str)  # (command, url)
    cancel_process_signal = pyqtSignal(str)  # url

    def __init__(self, url, output_path, format_type, quality, playlist=False, subtitles=False, sub_lang="", cookies_path="", custom_args=""):
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

    def run(self):
        command = [
            "-o", f"{self.output_path}/%(title)s.%(ext)s",
            "--format", self._get_format(),
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "--no-check-certificate",
            "--progress-template", "%(progress._percent_str)s",
            "--newline",
        ]

        if self.playlist:
            command.append("--yes-playlist")
        if self.subtitles and self.sub_lang:
            command.extend(["--write-subs", "--sub-lang", self.sub_lang])
        if self.cookies_path:
            command.extend(["--cookies", self.cookies_path])
        if self.custom_args:
            command.extend(self.custom_args.split())
        command.append(self.url)

        # Emetti il segnale per avviare il processo nel thread principale
        self.start_process_signal.emit(command, self.url)

        # Simula un loop per mantenere il thread attivo
        while not self._is_cancelled:
            QApplication.processEvents()
            self.msleep(100)

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

    def cancel(self):
        self._is_cancelled = True
        self.cancel_process_signal.emit(self.url)


# --- Finestra principale ---

class YTDLPGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YT-DLP Downloader Avanzato")
        self.setGeometry(100, 100, 800, 600)
        self.setAcceptDrops(True)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout()
        self.central_widget.setLayout(self.layout)

        self.download_queue = []
        self.active_threads = {}
        self.processes = {}  # {url: (QProcess, DownloadThread)}
        self.history = []

        self._load_settings()
        self._create_ui()

    def _load_settings(self):
        try:
            with open("settings.json", "r") as f:
                settings = json.load(f)
                self.default_output = settings.get("output_path", get_default_downloads_path())
                self.default_quality = settings.get("quality", "Alta")
                self.default_format = settings.get("format", "Video")
        except (FileNotFoundError, json.JSONDecodeError):
            self.default_output = get_default_downloads_path()
            self.default_quality = "Alta"
            self.default_format = "Video"

    def _save_settings(self):
        settings = {
            "output_path": self.output_input.text(),
            "quality": self.quality_combo.currentText(),
            "format": self.format_combo.currentText(),
        }
        with open("settings.json", "w") as f:
            json.dump(settings, f)

    def _create_ui(self):
        # --- Sezione URL e opzioni ---
        url_group = QGroupBox("Download")
        url_layout = QFormLayout()

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Inserisci l'URL del video o playlist")
        url_layout.addRow("URL:", self.url_input)

        self.format_combo = QComboBox()
        self.format_combo.addItems(["Video", "Audio", "Entrambi"])
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

        self.download_button = QPushButton("Scarica")
        self.download_button.clicked.connect(self._add_to_queue)
        buttons_layout.addWidget(self.download_button)

        self.cancel_button = QPushButton("Annulla tutto")
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
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
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

        self.log_output.append(f"Aggiunto alla coda: {url}")
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
        thread.finished_signal.connect(self._on_download_finished)
        thread.start_process_signal.connect(self._start_process)
        thread.cancel_process_signal.connect(self._cancel_process)

        self.active_threads[download["url"]] = thread
        thread.start()
        self.log_output.append(f"Avviato download: {download['url']}")

    def _start_process(self, command, url):
        process = QProcess()
        process.setProgram("yt-dlp")
        process.setArguments(command)
        process.start()

        # Salva il riferimento al processo e al thread
        self.processes[url] = (process, self.active_threads[url])

        # Collega i segnali per leggere l'output
        process.readyReadStandardOutput.connect(lambda: self._read_output(process, url))
        process.readyReadStandardError.connect(lambda: self._read_error(process, url))
        process.finished.connect(lambda: self._on_process_finished(url, process))

    def _read_output(self, process, url):
        output = process.readAllStandardOutput().data().decode()
        if output:
            self._parse_progress(output, url)

    def _read_error(self, process, url):
        error = process.readAllStandardError().data().decode()
        if error:
            for line in error.split('\n'):
                if line.strip():
                    self._update_log(line.strip())

    def _parse_progress(self, output, url):
        try:
            for line in output.split('\n'):
                if '%' in line:
                    percent_str = line.strip().rstrip('%')
                    percent = int(float(percent_str))
                    self.progress_bar.setValue(percent)
        except (ValueError, IndexError):
            pass

    def _on_process_finished(self, url, process):
        if url in self.processes:
            thread = self.processes[url][1]
            if process.exitCode() == 0:
                self._update_log(f"Download completato: {url}")
                thread.finished_signal.emit(url, True)
            else:
                error = process.readAllStandardError().data().decode()
                self._update_log(f"Errore: {error}")
                thread.finished_signal.emit(url, False)
            del self.processes[url]

    def _on_download_finished(self, url, success):
        if url in self.active_threads:
            del self.active_threads[url]
        self._start_next_download()

    def _cancel_process(self, url):
        if url in self.processes:
            process, thread = self.processes[url]
            process.terminate()
            process.waitForFinished(1000)
            del self.processes[url]
            self._update_log(f"Download annullato: {url}")

    def _update_progress(self, percent, url):
        self.progress_bar.setValue(percent)

    def _update_log(self, message):
        self.log_output.append(message)

    def _cancel_all_downloads(self):
        for url in list(self.processes.keys()):
            self._cancel_process(url)
        self.active_threads.clear()
        self.processes.clear()
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

    def _exit_app(self):
        self._save_settings()
        if self.active_threads or self.processes:
            reply = QMessageBox.question(
                self,
                "Download in corso",
                "Ci sono download attivi. Vuoi davvero uscire?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self._cancel_all_downloads()
                self.close()
        else:
            self.close()

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
    window = YTDLPGUI()
    window.show()
    sys.exit(app.exec())