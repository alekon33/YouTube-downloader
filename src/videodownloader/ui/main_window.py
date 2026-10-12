"""Main responsive desktop window."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QEvent, QSignalBlocker, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from videodownloader.core.exceptions import VideoDownloaderError
from videodownloader.core.state import AppStateMachine
from videodownloader.models import (
    Container,
    CookieBrowser,
    DownloadOptions,
    DownloadProgress,
    DownloadStage,
    JobState,
    MediaItem,
    Quality,
    parse_playlist_intervals,
)
from videodownloader.models.session import SavedPlaylist
from videodownloader.services.tool_updates import update_check_due
from videodownloader.settings import SettingsService
from videodownloader.tools.releases import YtDlpUpdate
from videodownloader.ui.controller import AppController, openable_folder
from videodownloader.ui.dialogs import PreparationDialog, show_about
from videodownloader.ui.formatting import format_bytes, format_duration, format_eta
from videodownloader.ui.tray import TrayIcon

_STAGE_TEXT = {
    DownloadStage.ANALYZING: "Анализ…",
    DownloadStage.VIDEO: "Загрузка видео",
    DownloadStage.AUDIO: "Загрузка аудио",
    DownloadStage.RESUMING: "Возобновление загрузки…",
    DownloadStage.PAUSING: "Включение паузы…",
    DownloadStage.PAUSED: "На паузе",
    DownloadStage.WAITING_FOR_CONNECTION: "Ожидание соединения…",
    DownloadStage.POST_PROCESSING: "Обработка файла",
    DownloadStage.COMPLETED: "Готово",
    DownloadStage.CANCELLED: "Отменено",
}

_ACTIVE_DOWNLOAD_STATES = frozenset(
    {
        JobState.DOWNLOADING,
        JobState.POST_PROCESSING,
        JobState.PAUSING,
        JobState.PAUSED,
        JobState.WAITING_FOR_CONNECTION,
    }
)


class MainWindow(QMainWindow):
    """Present media state and delegate all operations to the controller."""

    quit_requested = Signal()

    def __init__(
        self,
        controller: AppController,
        settings_service: SettingsService,
        *,
        auto_prepare: bool = True,
    ) -> None:
        super().__init__()
        self._controller = controller
        self._settings_service = settings_service
        self._settings = settings_service.load()
        self._state = AppStateMachine()
        self._media: MediaItem | None = None
        self._playlist_session: SavedPlaylist | None = None
        self._result_folder = self._settings.destination
        self._manual_update_check = False
        self._download_cancel_requested = False
        self._download_retry_available = False
        self._download_error_box: QMessageBox | None = None
        self._explicit_exit = False
        self._shutting_down = False
        self._tray_notice_shown = False
        self._analysis_elapsed = QElapsedTimer()
        self._analysis_timer = QTimer(self)
        self._analysis_timer.setInterval(1000)
        self._analysis_timer.timeout.connect(self._update_analysis_elapsed)
        self._build_ui()
        self._connect_signals()
        self._load_settings()
        self._tray = TrayIcon(self)
        self.setWindowIcon(self._tray.icon())
        self._tray.restore_requested.connect(self._restore_from_tray)
        self._tray.exit_requested.connect(self._request_exit)
        self._controller.shutdown_finished.connect(self._finish_exit)
        self._hide_to_tray_action.setEnabled(self._tray.isSystemTrayAvailable())
        self._set_state(JobState.IDLE)
        if auto_prepare and not controller.tools_available():
            QTimer.singleShot(0, self._show_preparation)
        elif auto_prepare and update_check_due(self._settings):
            QTimer.singleShot(1200, self._check_updates)

    def _build_ui(self) -> None:
        self.setWindowTitle("VideoDownloader")
        self.setMinimumSize(660, 560)
        self.resize(820, 720)
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        central = QWidget()
        root = QVBoxLayout(central)
        root.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)
        self._scroll_area.setWidget(central)
        self.setCentralWidget(self._scroll_area)

        title = QLabel("VideoDownloader")
        title.setObjectName("title")
        root.addWidget(title)

        link_card = QFrame()
        link_card.setObjectName("card")
        link_layout = QVBoxLayout(link_card)
        link_layout.setContentsMargins(16, 14, 16, 16)
        link_layout.addWidget(QLabel(self.tr("Ссылка на видео или плейлист")))
        link_row = QHBoxLayout()
        self._url = QLineEdit()
        self._url.setPlaceholderText("https://…")
        self._url.setClearButtonEnabled(True)
        link_row.addWidget(self._url, 1)
        self._analyze = QPushButton(self.tr("Анализировать"))
        link_row.addWidget(self._analyze)
        link_layout.addLayout(link_row)
        restore_row = QHBoxLayout()
        self._restore_playlist = QPushButton(self.tr("Докачать плейлист из папки"))
        self._restore_playlist.setObjectName("secondary")
        self._restore_playlist.setAccessibleDescription(
            self.tr(
                "Выбрать папку с сохранённым заданием и продолжить плейлист после перезапуска программы."
            )
        )
        self._new_download = QPushButton(self.tr("Новая загрузка"))
        self._new_download.setObjectName("secondary")
        self._new_download.hide()
        restore_row.addWidget(self._restore_playlist)
        restore_row.addStretch()
        restore_row.addWidget(self._new_download)
        link_layout.addLayout(restore_row)
        root.addWidget(link_card)

        self._info_card = QFrame()
        self._info_card.setObjectName("card")
        info_layout = QVBoxLayout(self._info_card)
        info_layout.setContentsMargins(16, 14, 16, 14)
        self._media_title = QLabel(self.tr("Ссылка ещё не проанализирована"))
        self._media_title.setObjectName("mediaTitle")
        self._media_title.setWordWrap(True)
        self._media_details = QLabel(self.tr("Здесь появятся длительность и доступные качества"))
        self._media_details.setObjectName("muted")
        self._media_details.setWordWrap(True)
        info_layout.addWidget(self._media_title)
        info_layout.addWidget(self._media_details)
        root.addWidget(self._info_card)

        self._options_group = QGroupBox(self.tr("Параметры"))
        options_layout = QGridLayout(self._options_group)
        options_layout.setColumnStretch(0, 1)
        options_layout.setColumnStretch(1, 1)
        self._quality_label = QLabel(self.tr("Максимальное качество"))
        options_layout.addWidget(self._quality_label, 0, 0)
        container_header = QHBoxLayout()
        self._container_label = QLabel(self.tr("Контейнер видео"))
        container_header.addWidget(self._container_label)
        container_header.addStretch()
        self._audio_only = QCheckBox(self.tr("Только аудио"))
        self._audio_only.setAccessibleName(self.tr("Скачать только аудио"))
        self._audio_only.setAccessibleDescription(
            self.tr("Скачать лучшую аудиодорожку и преобразовать её в MP3")
        )
        self._audio_only.setToolTip(self.tr("Скачать лучшую аудиодорожку в формате MP3 без видео"))
        container_header.addWidget(self._audio_only)
        options_layout.addLayout(container_header, 0, 1)
        self._quality = QComboBox()
        for quality in Quality:
            self._quality.addItem(quality.label, quality)
        self._container = QComboBox()
        self._container.addItem("MP4", Container.MP4)
        self._container.addItem("MKV", Container.MKV)
        self._quality_label.setBuddy(self._quality)
        self._container_label.setBuddy(self._container)
        options_layout.addWidget(self._quality, 1, 0)
        options_layout.addWidget(self._container, 1, 1)
        options_layout.addWidget(QLabel(self.tr("Папка сохранения")), 2, 0, 1, 2)
        folder_row = QHBoxLayout()
        self._folder = QLineEdit()
        folder_row.addWidget(self._folder, 1)
        self._browse = QPushButton("…")
        self._browse.setObjectName("secondary")
        self._browse.setAccessibleName(self.tr("Выбрать папку"))
        folder_row.addWidget(self._browse)
        options_layout.addLayout(folder_row, 3, 0, 1, 2)
        options_layout.addWidget(
            QLabel(self.tr("Авторизация YouTube (если требуется)")), 4, 0, 1, 2
        )
        self._cookie_browser = QComboBox()
        self._cookie_browser.addItem(self.tr("Без авторизации"), None)
        for browser in CookieBrowser:
            label = browser.label
            if browser is CookieBrowser.FIREFOX:
                label = self.tr("{browser} (рекомендуется)").format(browser=label)
            self._cookie_browser.addItem(label, browser)
        self._cookie_browser.setToolTip(
            self.tr(
                "Использовать только при запросе авторизации. yt-dlp прочитает cookies "
                "выбранного браузера; VideoDownloader не сохраняет их."
            )
        )
        options_layout.addWidget(self._cookie_browser, 5, 0, 1, 2)
        self._playlist_options = QWidget(self._options_group)
        playlist_layout = QGridLayout(self._playlist_options)
        playlist_layout.setContentsMargins(0, 8, 0, 0)
        playlist_layout.setHorizontalSpacing(16)
        playlist_layout.setVerticalSpacing(8)
        playlist_layout.setColumnStretch(0, 1)
        playlist_layout.setColumnStretch(1, 1)
        self._number_items = QCheckBox(self.tr("Нумеровать видео"))
        self._playlist_folder = QCheckBox(self.tr("Создать папку с названием плейлиста"))
        playlist_layout.addWidget(self._number_items, 0, 0)
        range_row = QHBoxLayout()
        intervals_label = QLabel(self.tr("Интервалы:"))
        self._playlist_intervals = QLineEdit()
        self._playlist_intervals.setPlaceholderText(self.tr("Например: 1–5, 8–12, 20"))
        self._playlist_intervals.setClearButtonEnabled(True)
        self._playlist_intervals.setAccessibleName(self.tr("Интервалы плейлиста"))
        self._playlist_intervals.setAccessibleDescription(
            self.tr(
                "Номера и интервалы через запятую. "
                "Открытый интервал 5– означает с пятого до конца. "
                "Оставьте поле пустым, чтобы скачать весь плейлист."
            )
        )
        self._playlist_intervals.setToolTip(
            self.tr(
                "Укажите номера и интервалы через запятую, "
                "например: 1–5, 8–12, 20. 5– означает с пятого "
                "до конца. Пустое поле — весь плейлист."
            )
        )
        intervals_label.setBuddy(self._playlist_intervals)
        range_row.addWidget(intervals_label)
        range_row.addWidget(self._playlist_intervals, 1)
        playlist_layout.addLayout(range_row, 0, 1)
        playlist_layout.addWidget(self._playlist_folder, 1, 0, 1, 2)
        self._archive = QCheckBox(self.tr("Пропускать уже скачанные"))
        self._archive.setToolTip(
            self.tr("Использовать архив загрузок и не скачивать одинаковые видео повторно")
        )
        playlist_layout.addWidget(self._archive, 2, 0, 1, 2)
        self._playlist_options.hide()
        options_layout.addWidget(self._playlist_options, 6, 0, 1, 2)
        root.addWidget(self._options_group)

        self._download = QPushButton(self.tr("Скачать"))
        self._download.setMinimumHeight(44)
        root.addWidget(self._download)

        progress_card = QFrame()
        progress_card.setObjectName("card")
        progress_layout = QVBoxLayout(progress_card)
        progress_layout.setContentsMargins(16, 14, 16, 14)
        status_row = QHBoxLayout()
        self._status = QLabel(self.tr("Готово к работе"))
        self._status.setObjectName("mediaTitle")
        self._status.setWordWrap(True)
        self._playlist_status = QLabel("")
        self._playlist_status.setObjectName("muted")
        self._playlist_status.hide()
        status_row.addWidget(self._status)
        status_row.addStretch()
        status_row.addWidget(self._playlist_status)
        progress_layout.addLayout(status_row)
        self._current_progress = QProgressBar()
        self._current_progress.setRange(0, 100)
        self._current_progress.setValue(0)
        progress_layout.addWidget(self._current_progress)
        self._overall_label = QLabel(self.tr("Общий прогресс"))
        self._overall_label.setObjectName("muted")
        self._overall_progress = QProgressBar()
        self._overall_progress.setRange(0, 100)
        progress_layout.addWidget(self._overall_label)
        progress_layout.addWidget(self._overall_progress)
        self._overall_label.hide()
        self._overall_progress.hide()
        self._telemetry = QLabel("—")
        self._telemetry.setObjectName("muted")
        progress_layout.addWidget(self._telemetry)
        action_row = QHBoxLayout()
        self._cancel = QPushButton(self.tr("Отмена"))
        self._cancel.setObjectName("danger")
        self._pause = QPushButton(self.tr("Пауза"))
        self._pause.setObjectName("secondary")
        self._pause.setAccessibleName(self.tr("Пауза или продолжение загрузки"))
        self._pause.setAccessibleDescription(
            self.tr("Приостановить загрузку, сохранив данные, или продолжить её.")
        )
        self._open_folder = QPushButton(self.tr("Открыть папку"))
        self._open_folder.setObjectName("secondary")
        action_row.addWidget(self._cancel)
        action_row.addWidget(self._pause)
        action_row.addStretch()
        action_row.addWidget(self._open_folder)
        progress_layout.addLayout(action_row)
        root.addWidget(progress_card)
        root.addStretch()

        program_menu = self.menuBar().addMenu(self.tr("Программа"))
        self._hide_to_tray_action = program_menu.addAction(self.tr("Свернуть в трей"))
        self._hide_to_tray_action.triggered.connect(self._hide_to_tray)
        self._tray_enabled_action = program_menu.addAction(
            self.tr("Сворачивать в трей при закрытии и сворачивании")
        )
        self._tray_enabled_action.setCheckable(True)
        self._tray_enabled_action.setChecked(self._settings.minimize_to_tray)
        self._tray_enabled_action.toggled.connect(self._tray_preference_changed)
        program_menu.addSeparator()
        self._exit_action = program_menu.addAction(self.tr("Выйти"))
        self._exit_action.triggered.connect(self._request_exit)

        help_menu = self.menuBar().addMenu(self.tr("Справка"))
        check_updates = QAction(self.tr("Проверить обновление yt-dlp"), self)
        check_updates.triggered.connect(self._manual_check_updates)
        open_log = QAction(self.tr("Открыть журнал"), self)
        open_log.triggered.connect(self._open_log)
        about = QAction(self.tr("О программе"), self)
        about.triggered.connect(lambda: show_about(self))
        help_menu.addAction(check_updates)
        help_menu.addAction(open_log)
        help_menu.addAction(about)

    def _connect_signals(self) -> None:
        self._url.textChanged.connect(self._refresh_controls)
        self._url.returnPressed.connect(self._start_analysis)
        self._analyze.clicked.connect(self._start_analysis)
        self._restore_playlist.clicked.connect(self._choose_saved_playlist)
        self._new_download.clicked.connect(self._reset_saved_playlist)
        self._browse.clicked.connect(self._choose_folder)
        self._download.clicked.connect(self._start_download)
        self._cancel.clicked.connect(self._cancel_download)
        self._pause.clicked.connect(self._toggle_pause)
        self._open_folder.clicked.connect(self._show_result_folder)
        self._audio_only.toggled.connect(self._audio_only_changed)
        self._cookie_browser.currentIndexChanged.connect(self._cookie_browser_changed)
        self._controller.analysis_succeeded.connect(self._analysis_complete)
        self._controller.analysis_failed.connect(self._analysis_failed)
        self._controller.playlist_restored.connect(self._playlist_restored)
        self._controller.playlist_restore_failed.connect(self._analysis_failed)
        self._controller.download_progress.connect(self._update_progress)
        self._controller.download_succeeded.connect(self._download_complete)
        self._controller.download_failed.connect(self._download_failed)
        self._controller.download_cancelled.connect(self._download_cancelled)
        self._controller.update_checked.connect(self._update_checked)
        self._controller.update_check_failed.connect(self._update_check_failed)
        self._controller.update_installed.connect(self._update_installed)
        self._controller.update_install_failed.connect(self._update_install_failed)
        self._controller.update_progress.connect(self._update_download_progress)

    def _load_settings(self) -> None:
        self._folder.setText(str(self._settings.destination))
        self._set_combo_data(self._quality, self._settings.quality)
        self._set_combo_data(self._container, self._settings.container)
        self._audio_only.setChecked(self._settings.audio_only)
        blocker = QSignalBlocker(self._cookie_browser)
        if self._settings.cookie_browser is None:
            self._cookie_browser.setCurrentIndex(0)
        else:
            self._set_combo_data(self._cookie_browser, self._settings.cookie_browser)
        del blocker
        self._playlist_folder.setChecked(self._settings.create_playlist_folder)
        self._number_items.setChecked(self._settings.number_playlist_items)
        self._archive.setChecked(self._settings.use_download_archive)

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: object) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    @Slot()
    def _start_analysis(self) -> None:
        self._playlist_session = None
        self._download_retry_available = False
        if self._download_error_box is not None:
            self._download_error_box.close()
        url = self._url.text().strip()
        if not url:
            return
        self._media = None
        self._playlist_status.clear()
        self._start_analysis_progress()
        self._set_state(JobState.ANALYZING)
        self._status.setText(self.tr("Анализ…"))
        self._media_title.setText(self.tr("Получаем информацию…"))
        self._controller.analyze(url, self._selected_cookie_browser())

    @Slot(object)
    def _analysis_complete(self, value: object) -> None:
        self._playlist_session = None
        self._stop_analysis_progress()
        if not isinstance(value, MediaItem):
            self._analysis_failed(VideoDownloaderError("Получены некорректные данные."))
            return
        self._media = value
        self._media_title.setText(value.title)
        self._update_media_details()
        self._playlist_status.clear()
        self._overall_progress.setValue(0)
        self._status.setText(self.tr("Готово к скачиванию"))
        self._set_state(JobState.READY)

    def _update_media_details(self) -> None:
        value = self._media
        if value is None:
            return
        if value.is_playlist:
            count = str(value.item_count) if value.item_count is not None else "неизвестно"
            details = self.tr("Плейлист · элементов: {count}").format(count=count)
            if self._audio_only.isChecked():
                details += self.tr(" · только аудио (MP3)")
        elif self._audio_only.isChecked():
            details = self.tr("{duration} · будет загружено только аудио (MP3)").format(
                duration=format_duration(value.duration_seconds)
            )
        else:
            qualities = ", ".join(f"{height}p" for height in value.available_heights) or "—"
            details = self.tr("{duration} · качества: {qualities} · размер: {size}").format(
                duration=format_duration(value.duration_seconds),
                qualities=qualities,
                size=format_bytes(value.estimated_bytes),
            )
        self._media_details.setText(details)

    @Slot(bool)
    def _audio_only_changed(self, checked: bool) -> None:
        del checked
        self._refresh_controls()
        self._update_media_details()

    @Slot(object)
    def _analysis_failed(self, value: object) -> None:
        self._stop_analysis_progress()
        error = self._coerce_error(value, "Не удалось получить информацию о видео.")
        self._media = None
        self._media_title.setText(self.tr("Ссылка не проанализирована"))
        self._media_details.setText(error.user_message)
        self._set_state(JobState.FAILED)
        self._show_error(error)
        self._state.reset()
        self._refresh_controls()

    def _start_analysis_progress(self) -> None:
        """Show honest activity feedback while yt-dlp analyzes an unknown workload."""

        self._current_progress.setRange(0, 0)
        self._current_progress.setTextVisible(False)
        self._analysis_elapsed.start()
        self._telemetry.setText(self.tr("Анализ выполняется · прошло 0:00"))
        self._analysis_timer.start()

    def _stop_analysis_progress(self) -> None:
        self._analysis_timer.stop()
        self._analysis_elapsed.invalidate()
        self._current_progress.setRange(0, 100)
        self._current_progress.setValue(0)
        self._current_progress.setTextVisible(True)
        self._telemetry.setText("—")

    @Slot()
    def _update_analysis_elapsed(self) -> None:
        if self._state.state is not JobState.ANALYZING or not self._analysis_elapsed.isValid():
            return
        elapsed = format_duration(self._analysis_elapsed.elapsed() // 1000)
        self._telemetry.setText(
            self.tr("Анализ выполняется · прошло {elapsed}").format(elapsed=elapsed)
        )

    @Slot()
    def _start_download(self) -> None:
        if self._media is None:
            return
        if self._playlist_session is not None:
            self._start_saved_playlist()
            return
        try:
            playlist_intervals = (
                parse_playlist_intervals(self._playlist_intervals.text(), self._media.item_count)
                if self._media.is_playlist
                else ()
            )
        except ValueError as error:
            self._show_error(VideoDownloaderError(str(error)))
            self._playlist_intervals.setFocus()
            self._playlist_intervals.selectAll()
            return
        destination = Path(self._folder.text().strip())
        try:
            destination.mkdir(parents=True, exist_ok=True)
            options = DownloadOptions(
                destination=destination,
                quality=Quality(self._quality.currentData()),
                container=Container(self._container.currentData()),
                audio_only=self._audio_only.isChecked(),
                cookie_browser=self._selected_cookie_browser(),
                playlist_intervals=playlist_intervals,
                create_playlist_folder=self._playlist_folder.isChecked(),
                number_playlist_items=self._number_items.isChecked(),
                use_download_archive=self._archive.isChecked(),
            )
        except (OSError, ValueError) as error:
            self._show_error(
                VideoDownloaderError("Не удалось использовать выбранную папку.", str(error))
            )
            return
        self._persist_settings(destination)
        self._result_folder = destination
        self._current_progress.setValue(0)
        self._overall_progress.setValue(0)
        self._telemetry.setText("—")
        self._download_cancel_requested = False
        self._download_retry_available = False
        if self._download_error_box is not None:
            self._download_error_box.close()
        self._set_state(JobState.DOWNLOADING)
        self._status.setText(self.tr("Запуск загрузки…"))
        self._controller.download(self._media, options)

    @Slot()
    def _choose_saved_playlist(self) -> None:
        if self._state.state is JobState.ANALYZING or self._state.state in _ACTIVE_DOWNLOAD_STATES:
            return
        selected = QFileDialog.getExistingDirectory(
            self, self.tr("Выберите папку с сохранённым плейлистом"), self._folder.text()
        )
        if not selected:
            return
        if self._download_error_box is not None:
            self._download_error_box.close()
        self._playlist_session = None
        self._media = None
        self._state.reset()
        self._start_analysis_progress()
        self._set_state(JobState.ANALYZING)
        self._status.setText(self.tr("Проверяем сохранённое задание…"))
        self._controller.restore_playlist(Path(selected))

    @Slot(object)
    def _playlist_restored(self, value: object) -> None:
        self._stop_analysis_progress()
        if not isinstance(value, SavedPlaylist):
            self._analysis_failed(
                VideoDownloaderError("Получены некорректные данные сохранённого задания.")
            )
            return
        self._playlist_session = value
        self._result_folder = value.folder
        self._media = value.media()
        self._download_retry_available = False
        self._url.setText(value.source_url)
        self._folder.setText(str(value.folder))
        self._set_combo_data(self._quality, value.options.quality)
        self._set_combo_data(self._container, value.options.container)
        self._audio_only.setChecked(value.options.audio_only)
        self._number_items.setChecked(value.options.number_playlist_items)
        self._playlist_folder.setChecked(False)
        self._archive.setChecked(value.options.use_download_archive)
        self._playlist_intervals.setText(
            ", ".join(
                str(i.start) if i.end == i.start else f"{i.start}–{i.end or ''}"
                for i in value.options.playlist_intervals
            )
        )
        self._media_title.setText(value.title)
        ready = value.completed_count
        total = len(value.items)
        self._media_details.setText(
            self.tr(
                "Сохранённое задание · готово {ready} из {total} · осталось {remaining}"
            ).format(ready=ready, total=total, remaining=total - ready)
        )
        self._overall_progress.setValue(round(ready / total * 100))
        self._status.setText(
            self.tr("Готово к продолжению") if ready < total else self.tr("Все файлы уже скачаны")
        )
        self._set_state(JobState.READY)
        if ready < total:
            answer = QMessageBox.question(
                self,
                self.tr("Продолжить плейлист?"),
                self.tr(
                    "{title}\nГотово {ready} из {total}, осталось {remaining}.\nПродолжить с сохранёнными параметрами?"
                ).format(title=value.title, ready=ready, total=total, remaining=total - ready),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._start_saved_playlist()

    def _start_saved_playlist(self) -> None:
        session = self._playlist_session
        if (
            session is None
            or not session.pending_items
            or self._state.state not in {JobState.READY, JobState.CANCELLED, JobState.COMPLETED}
        ):
            return
        self._current_progress.setValue(0)
        self._overall_progress.setValue(round(session.completed_count / len(session.items) * 100))
        self._download_cancel_requested = self._download_retry_available = False
        if self._download_error_box is not None:
            self._download_error_box.close()
        self._set_state(JobState.DOWNLOADING)
        self._status.setText(self.tr("Продолжаем сохранённый плейлист…"))
        self._controller.resume_playlist(session, self._selected_cookie_browser())

    @Slot()
    def _reset_saved_playlist(self) -> None:
        if self._state.state in _ACTIVE_DOWNLOAD_STATES:
            return
        self._playlist_session = None
        self._media = None
        self._download_retry_available = False
        if self._download_error_box is not None:
            self._download_error_box.close()
        self._result_folder = self._settings.destination
        self._current_progress.setValue(0)
        self._overall_progress.setValue(0)
        self._telemetry.setText("—")
        self._state.reset()
        self._url.clear()
        self._load_settings()
        self._media_title.setText(self.tr("Ссылка ещё не проанализирована"))
        self._media_details.setText(self.tr("Здесь появятся длительность и доступные качества"))
        self._status.setText(self.tr("Готово к работе"))
        self._refresh_controls()

    @Slot(object)
    def _update_progress(self, value: object) -> None:
        if (
            not isinstance(value, DownloadProgress)
            or self._shutting_down
            or self._download_cancel_requested
            or self._state.state not in _ACTIVE_DOWNLOAD_STATES
        ):
            return
        if self._state.state in {JobState.PAUSING, JobState.PAUSED} and value.stage in {
            DownloadStage.VIDEO,
            DownloadStage.AUDIO,
        }:
            return
        progress_states = {
            DownloadStage.VIDEO: JobState.DOWNLOADING,
            DownloadStage.AUDIO: JobState.DOWNLOADING,
            DownloadStage.RESUMING: JobState.DOWNLOADING,
            DownloadStage.POST_PROCESSING: JobState.POST_PROCESSING,
            DownloadStage.PAUSED: JobState.PAUSED,
            DownloadStage.PAUSING: JobState.PAUSING,
            DownloadStage.WAITING_FOR_CONNECTION: JobState.WAITING_FOR_CONNECTION,
        }
        target_state = progress_states.get(value.stage)
        if target_state is not None:
            self._set_state(target_state)
        if value.stage is DownloadStage.POST_PROCESSING and self._audio_only.isChecked():
            self._status.setText(self.tr("Обработка аудио"))
        else:
            control_stage = value.stage in {
                DownloadStage.PAUSED,
                DownloadStage.PAUSING,
                DownloadStage.RESUMING,
                DownloadStage.WAITING_FOR_CONNECTION,
            }
            self._status.setText(
                value.message if control_stage and value.message else _STAGE_TEXT[value.stage]
            )
        if value.percent is not None:
            self._current_progress.setValue(round(value.percent))
        if value.overall_percent is not None:
            self._overall_progress.setValue(round(value.overall_percent))
        if value.playlist_index is not None:
            count = str(value.playlist_count) if value.playlist_count is not None else "?"
            item_name = self.tr("Трек") if self._audio_only.isChecked() else self.tr("Видео")
            self._playlist_status.setText(f"{item_name} {value.playlist_index} из {count}")
        speed = (
            f"{format_bytes(value.speed_bytes_per_second)}/с"
            if value.speed_bytes_per_second is not None
            else "скорость —"
        )
        self._telemetry.setText(f"{speed} · {format_eta(value.eta_seconds)}")

    @Slot(object)
    def _download_complete(self, result: object) -> None:
        self._download_cancel_requested = False
        self._download_retry_available = False
        self._result_folder = openable_folder(result, Path(self._folder.text()))
        self._current_progress.setValue(100)
        self._overall_progress.setValue(100)
        self._status.setText(self.tr("Готово"))
        self._set_state(JobState.COMPLETED)
        if not self.isVisible() and not self._shutting_down:
            self._tray.notify(self.tr("Загрузка завершена"), self.tr("Файлы сохранены."))

    @Slot(object)
    def _download_failed(self, value: object) -> None:
        if self._shutting_down:
            return
        error = self._coerce_error(value, "Не удалось скачать файл.")
        self._download_cancel_requested = False
        self._status.setText(self.tr("Ошибка"))
        self._set_state(JobState.FAILED)
        self._state.reset(ready=self._media is not None)
        self._download_retry_available = self._media is not None
        self._refresh_controls()
        self._show_download_error(error)

    def _show_download_error(self, error: VideoDownloaderError) -> None:
        """A terminal failure must not hide usable retry controls behind a modal loop."""
        self._restore_from_tray()
        if self._download_error_box is not None:
            self._download_error_box.close()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(self.tr("Ошибка загрузки"))
        box.setText(error.user_message)
        box.setDetailedText(error.detail)
        buttons = QMessageBox.StandardButton.Close
        if self._download_retry_available:
            buttons |= QMessageBox.StandardButton.Retry
            box.setInformativeText(
                self.tr(
                    "Можно повторить загрузку без закрытия программы. Недокачанные файлы сохранены."
                )
            )
        box.setStandardButtons(buttons)
        close_button = box.button(QMessageBox.StandardButton.Close)
        if close_button is not None:
            close_button.setText(self.tr("Закрыть"))
        retry_button = box.button(QMessageBox.StandardButton.Retry)
        if retry_button is not None:
            retry_button.setText(self.tr("Повторить"))
        box.setDefaultButton(QMessageBox.StandardButton.Close)
        box.setWindowModality(Qt.WindowModality.NonModal)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._download_error_box = box

        def finished(result: int) -> None:
            if self._download_error_box is box:
                self._download_error_box = None
            if (
                result == QMessageBox.StandardButton.Retry
                and self._download_retry_available
                and self._state.state is JobState.READY
                and not self._shutting_down
            ):
                self._start_download()

        box.finished.connect(finished)
        box.show()

    @Slot(object)
    def _download_cancelled(self, value: object) -> None:
        del value
        self._download_cancel_requested = False
        self._download_retry_available = False
        self._status.setText(self.tr("Загрузка отменена"))
        self._set_state(JobState.CANCELLED)

    @Slot()
    def _cancel_download(self) -> None:
        self._download_cancel_requested = True
        self._refresh_controls()
        self._status.setText(self.tr("Отмена…"))
        self._controller.cancel_download()

    @Slot()
    def _toggle_pause(self) -> None:
        if self._download_cancel_requested:
            return
        if self._state.state is JobState.READY and self._download_retry_available:
            self._start_download()
            return
        if self._state.state is JobState.PAUSED:
            self._controller.resume_download()
            self._set_state(JobState.DOWNLOADING)
            self._status.setText(self.tr("Возобновление загрузки…"))
        elif self._state.state in {JobState.DOWNLOADING, JobState.WAITING_FOR_CONNECTION}:
            if self._controller.pause_download():
                self._set_state(JobState.PAUSING)
                self._status.setText(self.tr("Включение паузы…"))

    def _set_state(self, state: JobState) -> None:
        self._state.transition(state)
        self._refresh_controls()

    @Slot()
    def _refresh_controls(self) -> None:
        state = self._state.state
        analyzing = state is JobState.ANALYZING
        active = state in _ACTIVE_DOWNLOAD_STATES
        editable = not analyzing and not active
        restored = self._playlist_session is not None
        parameters_editable = editable and not restored
        audio_only = self._audio_only.isChecked()
        is_playlist = self._media is not None and self._media.is_playlist
        self._playlist_options.setVisible(is_playlist and parameters_editable)
        self._playlist_status.setVisible(is_playlist and active)
        self._overall_label.setVisible(is_playlist and (active or restored))
        self._overall_progress.setVisible(is_playlist and (active or restored))
        self._restore_playlist.setEnabled(editable)
        self._new_download.setVisible(restored)
        self._new_download.setEnabled(editable)
        self._url.setEnabled(parameters_editable)
        self._analyze.setEnabled(parameters_editable and bool(self._url.text().strip()))
        self._audio_only.setEnabled(parameters_editable)
        video_options_enabled = parameters_editable and not audio_only
        for video_widget in (
            self._quality_label,
            self._quality,
            self._container_label,
            self._container,
        ):
            video_widget.setEnabled(video_options_enabled)
        for editable_widget in (
            self._folder,
            self._browse,
            self._cookie_browser,
        ):
            editable_widget.setEnabled(
                parameters_editable if editable_widget is not self._cookie_browser else editable
            )
        for playlist_widget in (
            self._number_items,
            self._playlist_folder,
            self._playlist_intervals,
            self._archive,
        ):
            playlist_widget.setEnabled(parameters_editable and is_playlist)
        self._number_items.setText(
            self.tr("Нумеровать треки") if audio_only else self.tr("Нумеровать видео")
        )
        self._download.setText(self.tr("Скачать аудио") if audio_only else self.tr("Скачать"))
        if restored:
            self._download.setText(self.tr("Продолжить плейлист"))
        self._download.setEnabled(
            editable
            and self._media is not None
            and (
                not restored
                or bool(self._playlist_session and self._playlist_session.pending_items)
            )
        )
        self._cancel.setEnabled(active and not self._download_cancel_requested)
        retry = self._download_retry_available and state is JobState.READY
        self._pause.setText(
            self.tr("Повторить")
            if retry
            else (self.tr("Продолжить") if state is JobState.PAUSED else self.tr("Пауза"))
        )
        self._pause.setEnabled(
            not self._download_cancel_requested
            and (
                retry
                or state in {JobState.DOWNLOADING, JobState.PAUSED, JobState.WAITING_FOR_CONNECTION}
            )
        )
        self._pause.setToolTip(
            self.tr("Повторить загрузку с учётом недокачанных файлов.")
            if retry
            else self.tr("Пауза недоступна во время объединения дорожек или обработки аудио.")
            if state is JobState.POST_PROCESSING
            else self.tr("Пауза сохраняет недокачанные данные.")
        )
        self._open_folder.setEnabled(self._result_folder.exists())

    @Slot()
    def _choose_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, self.tr("Выберите папку"), self._folder.text()
        )
        if selected:
            self._folder.setText(selected)

    @Slot()
    def _show_result_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._result_folder)))

    @Slot()
    def _open_log(self) -> None:
        log_path = self._controller.paths.logs_dir / "videodownloader.log"
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_path)))

    def _selected_cookie_browser(self) -> CookieBrowser | None:
        value = self._cookie_browser.currentData()
        try:
            return CookieBrowser(str(value)) if value is not None else None
        except ValueError:
            return None

    @Slot()
    def _cookie_browser_changed(self) -> None:
        browser = self._selected_cookie_browser()
        if browser is not None:
            answer = QMessageBox.warning(
                self,
                self.tr("Использовать cookies браузера?"),
                self.tr(
                    "yt-dlp прочитает cookies из {browser} только во время анализа и "
                    "загрузки. VideoDownloader не сохраняет их. Использование аккаунта "
                    "для автоматических загрузок может привести к его временной или "
                    "постоянной блокировке. Продолжить?"
                ).format(browser=browser.label),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                blocker = QSignalBlocker(self._cookie_browser)
                self._cookie_browser.setCurrentIndex(0)
                del blocker
                browser = None
        self._settings = replace(self._settings, cookie_browser=browser)
        self._settings_service.save(self._settings)

    def _persist_settings(self, destination: Path) -> None:
        self._settings = replace(
            self._settings,
            destination=destination,
            quality=Quality(self._quality.currentData()),
            container=Container(self._container.currentData()),
            audio_only=self._audio_only.isChecked(),
            cookie_browser=self._selected_cookie_browser(),
            create_playlist_folder=self._playlist_folder.isChecked(),
            number_playlist_items=self._number_items.isChecked(),
            use_download_archive=self._archive.isChecked(),
        )
        self._settings_service.save(self._settings)

    def _show_preparation(self) -> None:
        if self._shutting_down:
            return
        dialog = PreparationDialog(self._controller, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._status.setText(self.tr("Компоненты не подготовлены"))

    @Slot()
    def _manual_check_updates(self) -> None:
        self._manual_update_check = True
        self._check_updates()

    @Slot()
    def _check_updates(self) -> None:
        if self._shutting_down:
            return
        if not self._controller.tools_available():
            if self._manual_update_check:
                self._show_preparation()
            return
        self._status.setText(self.tr("Проверка обновления yt-dlp…"))
        self._controller.check_yt_dlp_update()

    @Slot(object)
    def _update_checked(self, value: object) -> None:
        if self._shutting_down:
            return
        self._settings = replace(self._settings, last_yt_dlp_check=datetime.now(UTC).isoformat())
        self._settings_service.save(self._settings)
        manual = self._manual_update_check
        self._manual_update_check = False
        if isinstance(value, YtDlpUpdate):
            self._restore_from_tray()
            answer = QMessageBox.question(
                self,
                self.tr("Доступно обновление yt-dlp"),
                self.tr("Обновить yt-dlp с {old} до {new}?").format(
                    old=value.installed_version, new=value.asset.version
                ),
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._status.setText(self.tr("Обновление yt-dlp…"))
                self._controller.install_yt_dlp_update(value)
            else:
                self._status.setText(self.tr("Готово к работе"))
        else:
            self._status.setText(self.tr("yt-dlp уже обновлён"))
            if manual:
                QMessageBox.information(
                    self, self.tr("Обновление yt-dlp"), self.tr("Установлена актуальная версия.")
                )

    @Slot(object)
    def _update_check_failed(self, value: object) -> None:
        manual = self._manual_update_check
        self._manual_update_check = False
        self._status.setText(self.tr("Не удалось проверить обновление"))
        if manual:
            self._show_error(self._coerce_error(value, "Не удалось проверить обновление yt-dlp."))

    @Slot(str, int, int)
    def _update_download_progress(self, name: str, downloaded: int, total: int) -> None:
        del name
        if total:
            self._current_progress.setValue(min(100, int(downloaded / total * 100)))

    @Slot(str)
    def _update_installed(self, version: str) -> None:
        self._status.setText(self.tr("yt-dlp обновлён до {version}").format(version=version))

    @Slot(object)
    def _update_install_failed(self, value: object) -> None:
        self._status.setText(self.tr("Не удалось обновить yt-dlp"))
        self._show_error(self._coerce_error(value, "Не удалось обновить yt-dlp."))

    def _show_error(self, error: VideoDownloaderError) -> None:
        if self._shutting_down:
            return
        self._restore_from_tray()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(self.tr("Ошибка"))
        box.setText(error.user_message)
        box.setDetailedText(error.detail)
        box.exec()

    @staticmethod
    def _coerce_error(value: object, fallback: str) -> VideoDownloaderError:
        if isinstance(value, VideoDownloaderError):
            return value
        return VideoDownloaderError(fallback, str(value))

    @Slot(bool)
    def _tray_preference_changed(self, enabled: bool) -> None:
        self._settings = replace(self._settings, minimize_to_tray=enabled)
        self._settings_service.save(self._settings)

    @Slot()
    def _hide_to_tray(self) -> bool:
        if self._shutting_down or not self._tray.can_hide_window():
            return False
        self._persist_settings(Path(self._folder.text()))
        self.hide()
        if not self._tray_notice_shown:
            self._tray_notice_shown = True
            self._tray.notify(
                "VideoDownloader",
                self.tr(
                    "Программа продолжает работать в трее. Нажмите значок, чтобы "
                    "открыть окно. Для завершения выберите «Выйти» в меню значка."
                ),
            )
        return True

    @Slot()
    def _restore_from_tray(self) -> None:
        if self._shutting_down:
            return
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            QTimer.singleShot(0, self._hide_minimized_window)

    def _hide_minimized_window(self) -> None:
        # A queued check avoids re-entering Qt's window-state change handler.
        if self.isMinimized() and self._settings.minimize_to_tray:
            self._hide_to_tray()

    @Slot()
    def _request_exit(self) -> None:
        if not self._shutting_down:
            self._explicit_exit = True
            self.close()

    @Slot()
    def _finish_exit(self) -> None:
        if self._shutting_down:
            self._tray.hide()
            self.quit_requested.emit()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._shutting_down:
            event.accept()
            return
        if not self._explicit_exit and self._settings.minimize_to_tray and self._hide_to_tray():
            event.ignore()
            return
        if self._state.state in _ACTIVE_DOWNLOAD_STATES:
            self._restore_from_tray()
            answer = QMessageBox.question(
                self,
                self.tr("Завершить загрузку?"),
                self.tr("Активная загрузка будет отменена."),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._explicit_exit = False
                event.ignore()
                return
        self._persist_settings(Path(self._folder.text()))
        self._shutting_down = True
        self._analysis_timer.stop()
        self.setEnabled(False)
        self._tray.menu.setEnabled(False)
        self._tray.setToolTip(self.tr("VideoDownloader — завершение работы…"))
        self._controller.shutdown()
        event.accept()
