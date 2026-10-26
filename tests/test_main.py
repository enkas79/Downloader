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


def test_get_settings_dir_is_not_app_dir():
    assert main.get_settings_dir() != main.get_app_dir()


def test_download_thread_format_video_alta(qapp):
    thread = main.DownloadThread(
        url="https://example.com/video",
        output_path="/tmp",
        format_type="Video",
        quality="Alta",
    )
    assert "1080" in thread._get_format()


def test_is_drm_protected_url_netflix():
    assert main.is_drm_protected_url("https://www.netflix.com/watch/12345")


def test_is_drm_protected_url_amazon_prime():
    assert main.is_drm_protected_url("https://www.primevideo.com/detail/abc")


def test_is_drm_protected_url_youtube_not_flagged():
    assert not main.is_drm_protected_url("https://www.youtube.com/watch?v=abc")


def test_is_drm_protected_url_subdomain_not_flagged():
    assert not main.is_drm_protected_url("https://netflix.com.evil.com/watch/1")


def test_download_thread_format_audio(qapp):
    thread = main.DownloadThread(
        url="https://example.com/video",
        output_path="/tmp",
        format_type="Audio",
        quality="Alta",
    )
    assert thread._get_format() == "bestaudio/best"


def test_build_args_no_check_certificate_absent(qapp):
    thread = main.DownloadThread(
        url="https://example.com/video",
        output_path="/tmp",
        format_type="Video",
        quality="Alta",
    )
    args = thread._build_args()
    assert "--no-check-certificate" not in args
    assert args[-1] == "https://example.com/video"


def test_build_args_playlist_and_cookies(qapp):
    thread = main.DownloadThread(
        url="https://example.com/playlist",
        output_path="/tmp",
        format_type="Video",
        quality="Media",
        playlist=True,
        cookies_path="/tmp/cookies.txt",
    )
    args = thread._build_args()
    assert "--yes-playlist" in args
    assert "--cookies" in args
    assert "/tmp/cookies.txt" in args


def test_build_args_subtitles_only_for_video(qapp):
    thread = main.DownloadThread(
        url="https://example.com/video",
        output_path="/tmp",
        format_type="Audio",
        quality="Alta",
        subtitles=True,
        sub_lang="it,en",
    )
    args = thread._build_args()
    assert "--write-subs" not in args


def test_build_args_custom_args_with_quotes(qapp):
    thread = main.DownloadThread(
        url="https://example.com/video",
        output_path="/tmp",
        format_type="Video",
        quality="Alta",
        custom_args='--ffmpeg-location "/opt/ffmpeg bin"',
    )
    args = thread._build_args()
    idx = args.index("--ffmpeg-location")
    assert args[idx + 1] == "/opt/ffmpeg bin"


def test_emit_progress_parses_percent_with_spaces(qapp):
    emitted = []
    thread = main.DownloadThread(
        url="https://example.com/video",
        output_path="/tmp",
        format_type="Video",
        quality="Alta",
    )
    thread.progress_signal.connect(lambda percent, url: emitted.append(percent))
    thread._emit_progress(" 42.5%")
    assert emitted == [42]


def test_is_newer_version_true():
    assert main.is_newer_version("1.1.0", "1.0.0")


def test_is_newer_version_false_on_downgrade():
    assert not main.is_newer_version("1.0.1", "1.1.0")


def test_is_newer_version_false_on_same():
    assert not main.is_newer_version("1.0.0", "1.0.0")


def test_is_newer_version_handles_different_lengths():
    assert main.is_newer_version("1.0.1", "1.0")
    assert not main.is_newer_version("1.0", "1.0.1")
