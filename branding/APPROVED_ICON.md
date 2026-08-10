# ORION approved application icon

Status: **approved**

The final ORION application branding is the user-approved artwork with:

- top-down F/A-18 silhouette
- dark navy / DCS-inspired blue palette
- yellow HUD arcs
- `ORION` wordmark
- `ATC & MISSION ASSISTANT` subtitle

The approved raster source and generated Windows icon assets are identified by digest so packaging cannot silently substitute a similar-looking asset.

## Approved digests

- source PNG SHA-256: `56a1a6870de5ce306d9539091c7783c336d6b0e72b101ba9fd22745c77360e7b`
- master Windows ICO SHA-256 (16–256 px): `4c7059d3d6909442433e550ec8a5582679924f8b12bbbdfdb37d90125258fce0`
- packaged Alpha ICO SHA-256 (16/32/48/64 px): `0dd2b5c9207291781a6bec24222e34b9cf9b0767522952e4987cd061dab1ffbf`

## Windows ICO sizes

The master ICO contains:

`16x16`, `24x24`, `32x32`, `48x48`, `64x64`, `128x128`, `256x256`.

For the first Alpha installer, `branding/orion.ico` is a byte-stable packaging derivative generated from the same approved artwork and contains:

`16x16`, `32x32`, `48x48`, `64x64`.

The smaller Alpha derivative is intentional: it can be committed and verified reliably through the current GitHub tooling while covering the launcher window, tray, executable and standard Windows shortcut sizes. The master 128/256 px layers remain the approved source for a later hi-DPI packaging polish.

## Packaging targets

`branding/orion.ico` must be used consistently for:

1. the `ORION.exe` executable icon (PyInstaller `--icon`)
2. Inno Setup `SetupIconFile`
3. Start Menu and desktop shortcuts
4. uninstall display icon
5. Windows tray icon
6. launcher and Setup Wizard window icons

Windows CI must fail if the packaged Alpha ICO is missing or its SHA-256 differs from the approved Alpha digest above.
