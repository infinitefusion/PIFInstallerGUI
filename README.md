# Pokémon Infinite Fusion Launcher

Cross-platform Python/Tk launcher for installing, updating, and starting the
Windows game build on Windows or macOS.

## macOS Wine behavior

The launcher pins Wine Stable 11.0 as its tested runtime. Runtime selection is
automatic: reuse an installed Wine 11.0, then an optional bundled Wine 11.0,
then the launcher's previously downloaded runtime. Only when none of those
exist does the launcher download the checksum-verified managed runtime. Other
installed Wine versions are left untouched and are not used.

Each game gets an isolated prefix under:

```text
~/Library/Application Support/infinitefusion_common/wineprefixes/
```

To include Wine directly in a macOS build, place an extracted Wine bundle at
`vendor/wine/Wine Stable.app` before running the build. Otherwise it is
downloaded on demand.

The upstream Wine package declares GStreamer.framework as a runtime dependency.
The launcher does not need it to manage files or initialize Wine, but Wine
multimedia features may require the framework to be present.

## Build

Install Python, Pillow, and PyInstaller on the target OS, then run:

```bash
python build.py
```

Build the Windows `.exe` on Windows and the macOS `.app` on macOS. Public macOS
distribution still requires signing and notarizing the resulting app and any
bundled runtime with the project's Apple Developer identity.

## Runtime override

For development or custom deployments, `PIF_WINE_BINARY` can point to a Wine
executable and `PIF_LAUNCHER_DATA_DIR` can override the per-user data directory.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the managed runtime's
source and license information.
