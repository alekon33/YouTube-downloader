"""Main responsive desktop window."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QSignalBlocker, Qt, QTimer, QUrl, Slot
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
from videodownloader.services.tool_updates import update_check_due
from videodownloader.settings import SettingsService
from videodownloader.tools.releases import YtDlpUpdate
from videodownloader.ui.controller import AppController, openable_folder
from videodownloader.ui.dialogs import PreparationDialog, show_about
from videodownloader.ui.formatting import format_bytes, format_duration, format_eta

_STAGE_TEXT = {
    DownloadStage.ANALYZING: "Анализ…",
    DownloadStage.VIDEO: "Загрузка видео",
    DownloadStage.AUDIO: "Загрузка аудио",
    DownloadStage.POST_PROCESSING: "Обработка файла",
    DownloadStage.COMPLETED: "Готово",
    DownloadStage.CANCELLED: "Отменено",
}


class MainWindow(QMainWindow):
    """Present media state and delegate all operations to the controller."""

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
        self._result_folder = self._settings.destination
        self._manual_update_check = False
        self._analysis_elapsed = QElapsedTimer()
        self._analysis_timer = QTimer(self)
        self._analysis_timer.setInterval(1000)
        self._analysis_timer.timeout.connect(self._update_analysis_elapsed)
        self._build_ui()
        self._connect_signals()
        self._load_settings()
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
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
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
        self._audio_only.setToolTip(
            self.tr("Скачать лучшую аудиодорожку в формате MP3 без видео")
        )
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
        self._open_folder = QPushButton(self.tr("Открыть папку"))
        self._open_folder.setObjectName("secondary")
        action_row.addWidget(self._cancel)
        action_row.addStretch()
        action_row.addWidget(self._open_folder)
        progress_layout.addLayout(action_row)
        root.addWidget(progress_card)
        root.addStretch()

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
        self._browse.clicked.connect(self._choose_folder)
        self._download.clicked.connect(self._start_download)
        self._cancel.clicked.connect(self._cancel_download)
        self._open_folder.clicked.connect(self._show_result_folder)
        self._audio_only.toggled.connect(self._audio_only_changed)
        self._cookie_browser.currentIndexChanged.connect(self._cookie_browser_changed)
        self._controller.analysis_succeeded.connect(self._analysis_complete)
        self._controller.analysis_failed.connect(self._analysis_failed)
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
        try:
            playlist_intervals = (
                parse_playlist_intervals(
                    self._playlist_intervals.text(), self._media.item_count
                )
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
            self._show_error(VideoDownloaderError("Не удалось использовать выбранную папку.", str(error)))
            return
        self._persist_settings(destination)
        self._result_folder = destination
        self._current_progress.setValue(0)
        self._overall_progress.setValue(0)
        self._telemetry.setText("—")
        self._set_state(JobState.DOWNLOADING)
        self._status.setText(self.tr("Запуск загрузки…"))
        self._controller.download(self._media, options)

    @Slot(object)
    def _update_progress(self, value: object) -> None:
        if not isinstance(value, DownloadProgress):
            return
        if value.stage is DownloadStage.POST_PROCESSING and self._state.state is JobState.DOWNLOADING:
            self._set_state(JobState.POST_PROCESSING)
        if value.stage is DownloadStage.POST_PROCESSING and self._audio_only.isChecked():
            self._status.setText(self.tr("Обработка аудио"))
        else:
            self._status.setText(_STAGE_TEXT[value.stage])
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
        self._result_folder = openable_folder(result, Path(self._folder.text()))
        self._current_progress.setValue(100)
        self._overall_progress.setValue(100)
        self._status.setText(self.tr("Готово"))
        self._set_state(JobState.COMPLETED)

    @Slot(object)
    def _download_failed(self, value: object) -> None:
        error = self._coerce_error(value, "Не удалось скачать файл.")
        self._status.setText(self.tr("Ошибка"))
        self._set_state(JobState.FAILED)
        self._show_error(error)
        self._state.reset(ready=self._media is not None)
        self._refresh_controls()

    @Slot(object)
    def _download_cancelled(self, value: object) -> None:
        del value
        self._status.setText(self.tr("Загрузка отменена"))
        self._set_state(JobState.CANCELLED)

    @Slot()
    def _cancel_download(self) -> None:
        self._cancel.setEnabled(False)
        self._status.setText(self.tr("Отмена…"))
        self._controller.cancel_download()

    def _set_state(self, state: JobState) -> None:
        self._state.transition(state)
        self._refresh_controls()

    @Slot()
    def _refresh_controls(self) -> None:
        state = self._state.state
        analyzing = state is JobState.ANALYZING
        active = state in {JobState.DOWNLOADING, JobState.POST_PROCESSING}
        editable = not analyzing and not active
        audio_only = self._audio_only.isChecked()
        is_playlist = self._media is not None and self._media.is_playlist
        self._playlist_options.setVisible(is_playlist and editable)
        self._playlist_status.setVisible(is_playlist and active)
        self._overall_label.setVisible(is_playlist and active)
        self._overall_progress.setVisible(is_playlist and active)
        self._url.setEnabled(editable)
        self._analyze.setEnabled(editable and bool(self._url.text().strip()))
        self._audio_only.setEnabled(editable)
        video_options_enabled = editable and not audio_only
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
            editable_widget.setEnabled(editable)
        for playlist_widget in (
            self._number_items,
            self._playlist_folder,
            self._playlist_intervals,
            self._archive,
        ):
            playlist_widget.setEnabled(editable and is_playlist)
        self._number_items.setText(
            self.tr("Нумеровать треки") if audio_only else self.tr("Нумеровать видео")
        )
        self._download.setText(self.tr("Скачать аудио") if audio_only else self.tr("Скачать"))
        self._download.setEnabled(editable and self._media is not None)
        self._cancel.setEnabled(active)
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
        dialog = PreparationDialog(self._controller, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._status.setText(self.tr("Компоненты не подготовлены"))

    @Slot()
    def _manual_check_updates(self) -> None:
        self._manual_update_check = True
        self._check_updates()

    @Slot()
    def _check_updates(self) -> None:
        if not self._controller.tools_available():
            if self._manual_update_check:
                self._show_preparation()
            return
        self._status.setText(self.tr("Проверка обновления yt-dlp…"))
        self._controller.check_yt_dlp_update()

    @Slot(object)
    def _update_checked(self, value: object) -> None:
        self._settings = replace(
            self._settings, last_yt_dlp_check=datetime.now(UTC).isoformat()
        )
        self._settings_service.save(self._settings)
        manual = self._manual_update_check
        self._manual_update_check = False
        if isinstance(value, YtDlpUpdate):
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

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._state.state in {JobState.DOWNLOADING, JobState.POST_PROCESSING}:
            answer = QMessageBox.question(
                self,
                self.tr("Завершить загрузку?"),
                self.tr("Активная загрузка будет отменена."),
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self._persist_settings(Path(self._folder.text()))
        self._controller.shutdown()
        event.accept()
