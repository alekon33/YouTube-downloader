# Windows installer

`VideoDownloader.iss` creates a per-user installer and does not request elevation or modify `PATH`.
User settings and downloaded external tools live under `%LOCALAPPDATA%\VideoDownloader`, outside the
installation directory, so a normal application update preserves them.

Build the standalone directory first, then compile the installer:

```powershell
.\scripts\build.ps1 -Clean
.\scripts\build_installer.ps1
```

The result is `installer\output\VideoDownloaderSetup-<version>.exe` plus its SHA-256 file.
