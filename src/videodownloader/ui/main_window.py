"""Main responsive desktop window."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Slot
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
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from videodownloader.core.exceptions import VideoDownloaderError
from videodownloader.core.state import AppStateMachine
from videodownloader.models import (
    Container,
    DownloadOptions,
    DownloadProgress,
    DownloadStage,
    JobState,
    MediaItem,
    Quality,
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
    DownloadStage.POST_PROCESSING: "Объединение дорожек",
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
        self._build_ui()
        self._connect_signals()
        self._load_settings()
        self._set_state(JobState.IDLE)
        if auto_prepare and not controller.tools_available():
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, self._show_preparation)
        elif auto_prepare and update_check_due(self._settings):
            from PySide6.QtCore import QTimer

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
        options_layout.addWidget(QLabel(self.tr("Максимальное качество")), 0, 0)
        options_layout.addWidget(QLabel(self.tr("Контейнер")), 0, 1)
        self._quality = QComboBox()
        for quality in Quality:
            self._quality.addItem(quality.label, quality)
        self._container = QComboBox()
        self._container.addItem("MP4", Container.MP4)
        self._container.addItem("MKV", Container.MKV)
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
        range_row.addWidget(QLabel(self.tr("Диапазон:")))
        self._range_start = QSpinBox()
        self._range_start.setRange(1, 999_999)
        self._range_start.setValue(1)
        self._range_start.setMaximumWidth(110)
        self._range_end = QSpinBox()
        self._range_end.setRange(0, 999_999)
        self._range_end.setSpecialValueText(self.tr("Все"))
        self._range_end.setMaximumWidth(110)
        range_row.addWidget(self._range_start)
        range_row.addWidget(QLabel("—"))
        range_row.addWidget(self._range_end)
        range_row.addStretch()
        playlist_layout.addLayout(range_row, 0, 1)
        playlist_layout.addWidget(self._playlist_folder, 1, 0, 1, 2)
        self._archive = QCheckBox(self.tr("Пропускать уже скачанные"))
        self._archive.setToolTip(
            self.tr("Использовать архив загрузок и не скачивать одинаковые видео повторно")
        )
        playlist_layout.addWidget(self._archive, 2, 0, 1, 2)
        self._playlist_options.hide()
        options_layout.addWidget(self._playlist_options, 4, 0, 1, 2)
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
        self._set_state(JobState.ANALYZING)
        self._status.setText(self.tr("Анализ…"))
        self._media_title.setText(self.tr("Получаем информацию…"))
        self._controller.analyze(url)

    @Slot(object)
    def _analysis_complete(self, value: object) -> None:
        if not isinstance(value, MediaItem):
            self._analysis_failed(VideoDownloaderError("Получены некорректные данные."))
            return
        self._media = value
        self._media_title.setText(value.title)
        if value.is_playlist:
            count = str(value.item_count) if value.item_count is not None else "неизвестно"
            details = self.tr("Плейлист · элементов: {count}").format(count=count)
        else:
            qualities = ", ".join(f"{height}p" for height in value.available_heights) or "—"
            details = self.tr("{duration} · качества: {qualities} · размер: {size}").format(
                duration=format_duration(value.duration_seconds),
                qualities=qualities,
                size=format_bytes(value.estimated_bytes),
            )
        self._media_details.setText(details)
        self._playlist_status.clear()
        self._overall_progress.setValue(0)
        self._status.setText(self.tr("Готово к скачиванию"))
        self._set_state(JobState.READY)

    @Slot(object)
    def _analysis_failed(self, value: object) -> None:
        error = self._coerce_error(value, "Не удалось получить информацию о видео.")
        self._media = None
        self._media_title.setText(self.tr("Ссылка не проанализирована"))
        self._media_details.setText(error.user_message)
        self._set_state(JobState.FAILED)
        self._show_error(error)
        self._state.reset()
        self._refresh_controls()

    @Slot()
    def _start_download(self) -> None:
        if self._media is None:
            return
        destination = Path(self._folder.text().strip())
        try:
            destination.mkdir(parents=True, exist_ok=True)
            options = DownloadOptions(
                destination=destination,
                quality=Quality(self._quality.currentData()),
                container=Container(self._container.currentData()),
                playlist_start=self._range_start.value() if self._media.is_playlist else None,
                playlist_end=(self._range_end.value() or None) if self._media.is_playlist else None,
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
        self._status.setText(_STAGE_TEXT[value.stage])
        if value.percent is not None:
            self._current_progress.setValue(round(value.percent))
        if value.overall_percent is not None:
            self._overall_progress.setValue(round(value.overall_percent))
        if value.playlist_index is not None:
            count = str(value.playlist_count) if value.playlist_count is not None else "?"
            self._playlist_status.setText(f"Видео {value.playlist_index} из {count}")
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
        error = self._coerce_error(value, "Не удалось скачать видео.")
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
        is_playlist = self._media is not None and self._media.is_playlist
        self._playlist_options.setVisible(is_playlist and editable)
        self._playlist_status.setVisible(is_playlist and active)
        self._overall_label.setVisible(is_playlist and active)
        self._overall_progress.setVisible(is_playlist and active)
        self._url.setEnabled(editable)
        self._analyze.setEnabled(editable and bool(self._url.text().strip()))
        for widget in (
            self._quality,
            self._container,
            self._folder,
            self._browse,
            self._number_items,
            self._playlist_folder,
            self._range_start,
            self._range_end,
            self._archive,
        ):
            widget.setEnabled(editable)
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

    def _persist_settings(self, destination: Path) -> None:
        self._settings = replace(
            self._settings,
            destination=destination,
            quality=Quality(self._quality.currentData()),
            container=Container(self._container.currentData()),
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
