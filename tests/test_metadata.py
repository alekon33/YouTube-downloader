from videodownloader.downloader import parse_metadata
from videodownloader.models import MediaKind


def test_parse_video_metadata_collects_qualities_and_size() -> None:
    item = parse_metadata(
        {
            "id": "abc",
            "title": "Example",
            "duration": 61.9,
            "extractor_key": "Youtube",
            "formats": [
                {"height": 720, "filesize": 1000},
                {"height": 1080, "filesize_approx": 2500},
                {"acodec": "opus", "filesize": 200},
            ],
        },
        "https://example.test/watch/abc",
    )

    assert item.kind is MediaKind.VIDEO
    assert item.duration_seconds == 61
    assert item.available_heights == (1080, 720)
    assert item.estimated_bytes == 2500


def test_parse_playlist_metadata_preserves_entries() -> None:
    item = parse_metadata(
        {
            "_type": "playlist",
            "id": "list",
            "title": "Course",
            "entries": [
                {"id": "one", "title": "First", "url": "https://example.test/one"},
                {"id": "two", "title": "Second", "url": "https://example.test/two"},
            ],
        },
        "https://example.test/list",
    )

    assert item.kind is MediaKind.PLAYLIST
    assert item.item_count == 2
    assert [entry.title for entry in item.entries] == ["First", "Second"]


def test_parse_flat_playlist_metadata_without_video_formats() -> None:
    item = parse_metadata(
        {
            "_type": "playlist",
            "id": "list",
            "title": "Course",
            "playlist_count": 20,
            "entries": [
                {"id": "one", "title": "First", "url": "https://example.test/one"},
                {"id": "two", "title": "Second", "url": "https://example.test/two"},
            ],
        },
        "https://example.test/list",
    )

    assert item.kind is MediaKind.PLAYLIST
    assert item.item_count == 20
    assert [entry.available_heights for entry in item.entries] == [(), ()]
