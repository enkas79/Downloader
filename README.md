# Downloader

Applicazione desktop (PyQt6) per scaricare video, audio e playlist da un'ampia gamma
di siti tramite [yt-dlp](https://github.com/yt-dlp/yt-dlp).

## Funzionalità principali

- Download di singoli video, audio o intere playlist, con scelta di formato e qualità.
- Coda di download con avvio automatico del successivo ed esecuzione in background
  (nessun blocco dell'interfaccia grazie a `QThread`).
- Supporto sottotitoli, cookie di autenticazione e opzioni personalizzate di `yt-dlp`.
- Drag & drop dell'URL direttamente nella finestra.
- Menu **Aiuto** con Informazioni sull'app, Guida e controllo automatico/manuale
  degli aggiornamenti tramite GitHub Releases.

## Requisiti

- Python 3.9+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) installato e presente nel `PATH`
- Dipendenze elencate in `requirements.txt`

## Avvio

```bash
pip install -r requirements.txt
python src/main.py
```

## Test

```bash
pytest
```

## Build eseguibili

Gli eseguibili per Windows, macOS e Linux vengono generati automaticamente dal
workflow GitHub Actions `.github/workflows/build-installers.yml` a ogni
aggiornamento di `version.txt`.
