# Выпуск версии

## Подготовка

Используйте 64-битную Windows 10/11, Python 3.12 и Inno Setup 6. Версия имеет
единственный источник истины — `src/videodownloader/__about__.py`.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev,build]"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

Опциональные ручные интеграционные тесты используют уже проверенные локальные
инструменты и не скачивают их сами:

```powershell
$env:VIDEODOWNLOADER_YTDLP = 'C:\path\to\yt-dlp.exe'
$env:VIDEODOWNLOADER_FFMPEG_DIR = 'C:\path\to\ffmpeg-bin'
$env:VIDEODOWNLOADER_INTEGRATION_URL = 'https://example.invalid/media'
.\.venv\Scripts\python.exe -m pytest -m integration
```

URL должен указывать на небольшой материал, который сопровождающий вправе
скачивать. Без переменных эти тесты корректно пропускаются.

## Артефакты

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build.ps1 -Clean
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_installer.ps1
```

Проверьте запуск `dist\VideoDownloader\VideoDownloader.exe` на чистой Windows,
первичную подготовку инструментов, анализ, одиночную загрузку, разрывные
интервалы плейлиста (`1–3, 8–10`) отдельно для видео и MP3, отмену, обновление
yt-dlp и удаление приложения. Убедитесь, что общий прогресс считает только
выбранные элементы, а рядом со сборкой присутствуют `LICENSE`,
`THIRD_PARTY_NOTICES.md` и `licenses`.

Проверьте трей: сворачивание и закрытие окна во время загрузки не отменяют её;
щелчок по значку и пункт «Открыть VideoDownloader» восстанавливают окно, включая
развёрнутое состояние. Пункт «Выйти» при активной загрузке запрашивает
подтверждение и корректно завершает фоновые операции. Отключение настройки
«Программа → Сворачивать в трей при закрытии и сворачивании» возвращает обычное
поведение окна и сохраняется после перезапуска. Без доступного трея окно
не должно скрываться. Перед обновлением установленной версии завершите её
через пункт «Выйти», а не через крестик.

## GitHub Release

1. Обновите версию по SemVer и changelog/описание release.
2. Повторите лицензионную проверку из `docs/licensing.md`.
3. Закоммитьте изменения и создайте подписанный либо аннотированный тег ровно
   `v<версия>`, например `v0.1.0`.
4. Отправьте commit и tag только после review.
5. Workflow `release.yml` сверит тег с версией, выполнит проверки, соберёт
   установщик, рассчитает SHA-256 и прикрепит оба файла к GitHub Release.

Release workflow не запускается для веток и не публикует ничего без явного
version tag. Локальный установщик не подписан; для публичной распространённой
сборки желательно добавить Windows code-signing certificate и проверку подписи
в CI.
