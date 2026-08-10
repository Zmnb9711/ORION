# ORION approved application icon

Status: **approved**

The final ORION application branding is the user-approved artwork with:

- top-down F/A-18 silhouette
- dark navy / DCS-inspired blue palette
- yellow HUD arcs
- `ORION` wordmark
- `ATC & MISSION ASSISTANT` subtitle

The approved raster source and the generated multi-resolution Windows ICO are intentionally identified by digest so a later packaging step cannot silently substitute a similar-looking asset.

## Approved digests

- source PNG SHA-256: `56a1a6870de5ce306d9539091c7783c336d6b0e72b101ba9fd22745c77360e7b`
- Windows ICO SHA-256: `4c7059d3d6909442433e550ec8a5582679924f8b12bbbdfdb37d90125258fce0`

## Windows ICO sizes

The prepared ICO contains the following sizes:

`16x16`, `24x24`, `32x32`, `48x48`, `64x64`, `128x128`, `256x256`.

## Packaging targets

Once the exact binary asset is present in the repository it must be used consistently for:

1. the `ORION.exe` executable icon (PyInstaller `--icon`)
2. Inno Setup `SetupIconFile`
3. Start Menu and desktop shortcuts
4. uninstall display icon
5. Windows tray icon
6. launcher window icon where supported

Do not replace this artwork with a generated placeholder or approximate redraw merely to satisfy packaging. If the binary asset is unavailable, keep the existing fallback and report branding as pending rather than claiming the approved icon is installed.
