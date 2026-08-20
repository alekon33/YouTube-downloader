# Third-party notices

This file records the main third-party components used to build or run
VideoDownloader. It is informational and does not replace the license texts or
the advice of a qualified professional.

## PySide6 and Qt 6

The standalone Windows distribution contains unmodified, dynamically loaded
PySide6 and Qt libraries. PySide6 package metadata offers
`LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` in addition to a commercial Qt
option; individual Qt modules and bundled dependencies can have their own
notices.

- Project and licensing overview: https://doc.qt.io/qtforpython-6/
- Qt open-source obligations: https://www.qt.io/development/open-source-lgpl-obligations
- PySide source: https://code.qt.io/cgit/pyside/pyside-setup.git/
- Qt source: https://code.qt.io/cgit/qt/
- License copies shipped with this application: `licenses/GPL-3.0.txt` and
  `licenses/LGPL-3.0-only.txt`

VideoDownloader does not modify Qt libraries and does not prohibit reverse
engineering for debugging changes to those libraries. A distributor who uses
the LGPL option must preserve the shared-library layout, notices and all other
applicable LGPL requirements, or obtain an appropriate commercial Qt license.

## yt-dlp

`yt-dlp.exe` is not stored in this repository and is not embedded in the
VideoDownloader installer. On first run, the application downloads a pinned
official release into its private data directory, verifies
SHA-256 and runs it as a separate process. Later updates are also obtained from
official GitHub releases.

- Project and source: https://github.com/yt-dlp/yt-dlp
- Licensing information: https://github.com/yt-dlp/yt-dlp#licensing
- Releases: https://github.com/yt-dlp/yt-dlp/releases

The official PyInstaller-bundled executable is distributed under GPL-3.0-or-
later and includes third-party components with their own notices. Refer to the
exact release's `THIRD_PARTY_LICENSES.txt` and source offer when redistributing
that executable independently.

## FFmpeg Windows build

`ffmpeg.exe` and `ffprobe.exe` are not stored in this repository and are not
embedded in the VideoDownloader installer. On first run, the application
downloads the pinned 64-bit “release essentials” archive from
Gyan.dev, verifies its SHA-256, extracts only the required executables and runs
them as separate processes through yt-dlp.

- FFmpeg source and licensing: https://ffmpeg.org/
- Official Windows download references: https://ffmpeg.org/download.html
- Gyan.dev build description and source links: https://www.gyan.dev/ffmpeg/builds/

Gyan.dev currently describes its static 64-bit builds as GPLv3. Anyone who
redistributes the downloaded binaries separately must review the exact build's
license and corresponding-source requirements.

## Deno

`deno.exe` is not stored in this repository and is not embedded in the
VideoDownloader installer. On first run, the application downloads a pinned
official Windows release, verifies its SHA-256 and supplies it to yt-dlp as a
separate JavaScript runtime for site extraction challenges.

- Project and source: https://github.com/denoland/deno
- Releases: https://github.com/denoland/deno/releases
- License: https://github.com/denoland/deno/blob/main/LICENSE.md

Deno is distributed under the MIT License. Refer to the exact release and its
third-party notices when redistributing the downloaded binary independently.

## Nuitka

The Nuitka compiler is a build-time tool under AGPL-3.0 and is not installed as
an end-user tool. Generated executables contain its runtime library; Nuitka's
Runtime Library Exception grants additional permission for that target code.
The build copies the exact exception shipped with the selected Nuitka version
into the standalone distribution.

- Project and license: https://github.com/Nuitka/Nuitka
- User manual: https://nuitka.net/user-documentation/user-manual.html

## Inno Setup

Inno Setup creates the installer but is not installed with VideoDownloader.
Its own license applies to the build system. Check the licensing terms of the
exact compiler version, especially before commercial distribution.

- Project: https://jrsoftware.org/isinfo.php
- License: https://jrsoftware.org/files/is/license.txt

## Python and standard runtime dependencies

The standalone build contains a Python runtime and several transitive runtime
files collected by Nuitka/PySide6. Their notices are preserved in the build
metadata where supplied. Release maintainers should review the generated
distribution for every dependency update and add any newly required attribution
before publishing.
