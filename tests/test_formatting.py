from videodownloader.ui.formatting import format_bytes, format_duration, format_eta


def test_localized_formatters() -> None:
    assert format_duration(3661) == "1:01:01"
    assert format_bytes(1024 * 1024) == "1.0 МБ"
    assert format_eta(77) == "осталось 01:17"

