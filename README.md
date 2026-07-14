# MCLauncher Fork v0.1

This is the first real MCLauncher fork overlay.

It does not reimplement the Android Minecraft runtime. Instead, GitHub Actions
checks out Zalith Launcher 2 version 2.4.3, preserves its working Pojav-derived
runtime, applies MCLauncher branding and a new custom Compose home screen, then
builds and validates the APK.

## What changes in v0.1

- App name becomes **MCLauncher**
- A new MCLauncher home dashboard opens first
- Original runtime activity remains available
- Original Java, renderer, LWJGL, touch-control, download, account, and launch
  services remain untouched
- Original licences and copyright notices remain
- The startup interface clearly says **Unofficial Modified Version**
- GitHub Actions builds and uploads the APK

## Current custom screens

- Home
- Instances entry
- Content entry
- Downloads entry
- Settings entry
- Diagnostics entry
- Accounts entry
- Runtime status

In v0.1, these entries safely open the original runtime interface. Future phases
will connect each MCLauncher screen directly to the upstream repositories and
services, one screen at a time.

## Build from Android

1. Extract this ZIP.
2. Create an empty GitHub repository.
3. Upload everything inside the extracted folder.
4. Open **Actions**.
5. Run **Build MCLauncher v0.1**.
6. Download the `MCLauncher-v0.1-debug` artifact.
7. Extract and install the APK.

## Why the release is pinned

The build uses upstream tag `2.4.3`, rather than a moving `main` branch. This
makes the first build reproducible and reduces the chance that an upstream UI
refactor breaks the patch unexpectedly.

## Licence

The resulting modified application remains subject to Zalith Launcher 2's
GPL-3.0 licence and additional section 7 terms. Do not remove upstream notices,
source availability, or displayed copyright notices.
