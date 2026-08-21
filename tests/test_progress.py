from videodownloader.downloader import ProgressParser
from videodownloader.models import DownloadStage


def test_parse_download_progress_and_overall_percentage() -> None:
    parser = ProgressParser()

    progress = parser.parse(
        'VDP_PROGRESS\t"downloading"\t500\t1000\tnull\t250.0\t2\t2\t4\t"video.mp4"'
    )

    assert progress is not None
    assert progress.stage is DownloadStage.VIDEO
    assert progress.percent == 50
    assert progress.overall_percent == 37.5
    assert progress.speed_bytes_per_second == 250
    assert progress.eta_seconds == 2


def test_second_stream_is_reported_as_audio() -> None:
    parser = ProgressParser()
    parser.parse('VDP_PROGRESS\t"downloading"\t1\t10\tnull\t1\t9\tnull\tnull\t"video.f1.mp4"')

    progress = parser.parse(
        'VDP_PROGRESS\t"downloading"\t1\t5\tnull\t1\t4\tnull\tnull\t"video.f2.m4a"'
    )

    assert progress is not None
    assert progress.stage is DownloadStage.AUDIO


def test_audio_only_first_stream_is_reported_as_audio() -> None:
    parser = ProgressParser(audio_only=True)

    progress = parser.parse(
        'VDP_PROGRESS\t"downloading"\t1\t10\tnull\t1\t9\t1\t3\t"track.webm"'
    )

    assert progress is not None
    assert progress.stage is DownloadStage.AUDIO
    assert progress.playlist_index == 1
    assert progress.playlist_count == 3


def test_parse_postprocessing_and_final_path() -> None:
    parser = ProgressParser()

    postprocess = parser.parse('VDP_POSTPROCESS\t"started"\t1\t1\t"Merger"')
    finished = parser.parse('VDP_FINISHED\t"C:\\\\Videos\\\\file.mp4"\t1\t1')

    assert postprocess is not None
    assert postprocess.stage is DownloadStage.POST_PROCESSING
    assert finished is not None
    assert finished.stage is DownloadStage.COMPLETED
    assert parser.final_path is not None
    assert parser.final_path.name == "file.mp4"


def test_new_playlist_item_resets_stream_stage() -> None:
    parser = ProgressParser()
    parser.parse('VDP_PROGRESS\t"downloading"\t1\t10\tnull\t1\t9\t1\t2\t"first.mp4"')
    parser.parse('VDP_PROGRESS\t"downloading"\t1\t5\tnull\t1\t4\t1\t2\t"first.m4a"')

    progress = parser.parse(
        'VDP_PROGRESS\t"downloading"\t1\t10\tnull\t1\t9\t2\t2\t"second.mp4"'
    )

    assert progress is not None
    assert progress.stage is DownloadStage.VIDEO


def test_partial_playlist_progress_uses_selected_queue_size() -> None:
    parser = ProgressParser()

    first = parser.parse(
        'VDP_PROGRESS\t"downloading"\t500\t1000\tnull\t250.0\t2\t1\t8\t"first.mp4"'
    )
    last = parser.parse('VDP_FINISHED\t"C:\\\\Videos\\\\last.mp4"\t8\t8')

    assert first is not None
    assert first.playlist_index == 1
    assert first.playlist_count == 8
    assert first.overall_percent == 6.25
    assert last is not None
    assert last.playlist_index == 8
    assert last.playlist_count == 8
    assert last.overall_percent == 100
