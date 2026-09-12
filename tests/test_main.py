import os

import main


def test_get_current_version_reads_file():
    version = main.get_current_version()
    assert version != ""


def test_get_default_downloads_path_contains_downloads():
    assert "Downloads" in main.get_default_downloads_path()


def test_get_app_dir_resolves_project_root():
    app_dir = main.get_app_dir()
    assert os.path.isfile(os.path.join(app_dir, "version.txt"))


def test_download_thread_format_video_alta(qapp):
    thread = main.DownloadThread(
        url="https://example.com/video",
        output_path="/tmp",
        format_type="Video",
        quality="Alta",
    )
    assert "1080" in thread._get_format()


def test_download_thread_format_audio(qapp):
    thread = main.DownloadThread(
        url="https://example.com/video",
        output_path="/tmp",
        format_type="Audio",
        quality="Alta",
    )
    assert thread._get_format() == "bestaudio/best"
