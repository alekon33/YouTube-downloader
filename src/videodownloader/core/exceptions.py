"""Application exceptions carrying safe user-facing messages."""


class VideoDownloaderError(Exception):
    """Base exception separating user messages from technical details."""

    def __init__(self, user_message: str, detail: str | None = None) -> None:
        super().__init__(detail or user_message)
        self.user_message = user_message
        self.detail = detail or user_message


class ToolUnavailableError(VideoDownloaderError):
    """A required external executable is unavailable or invalid."""


class MetadataError(VideoDownloaderError):
    """Media metadata could not be obtained."""


class DownloadError(VideoDownloaderError):
    """A download process failed."""


class DownloadCancelled(VideoDownloaderError):
    """The user cancelled an active operation."""

