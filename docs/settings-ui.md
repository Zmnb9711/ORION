# ORION Settings UI specification

## Boundary

ORION settings control only ORION. The application does not expose controls for DCS graphics, VR headsets, OpenXR, SteamVR, GPU drivers or other third-party software.

## Sections

The Settings window contains: DCS, Profiles, Voice, AI, Mission Pack, Interface, Hotkeys and About.

## Voice

### Communication mode

The dropdown contains exactly:

1. Aviation English (`aviation_english`)
2. Aviation Russian (`aviation_russian`)
3. Free communication (`free_communication`)

Each item has an information control. Hover, keyboard focus or touch/click opens the description supplied by `GET /v1/settings/help`.

### Assistant voice

- Gender dropdown: Male or Female.
- Voice variant dropdown: populated dynamically for the selected gender and active TTS provider.
- No recommended badges or rankings.
- Preview button plays a short sample before saving.

### Microphone

- The dropdown lists every recording device available to ORION on Windows.
- The first option is the Windows default recording device.
- ORION stores a stable device identifier when available and uses the display name only as a fallback.
- The UI provides microphone status, Test microphone and Refresh list actions.

### Random conversations

A single checkbox enables or disables occasional appropriate non-operational conversation. When disabled, ORION speaks only in response to the pilot, an operational event, a warning or an active procedure.

### Callsign

There is no callsign field. ORION receives the pilot/group callsign from DCS. If DCS does not provide one, ORION does not invent one.

## Mission Pack

The section title includes an information control. Its popup content is supplied by `GET /v1/settings/help` and explains:

- Mission Pack prepares a separate copy of a DCS `.miz` mission for extended ORION functions.
- ORION checks the mission, creates a copy, adds service components and launches the prepared copy.
- The original mission file is never modified.

Available behavior for an unprepared mission:

- Ask before preparing a copy.
- Automatically prepare a copy.
- Launch without Mission Pack.

Additional options:

- Create a backup.
- Use the `(ORION)` suffix for prepared copies.
- Verify Mission Pack before launch.
- Manage additional mission search directories.

## Help behavior

Any non-obvious setting should expose an inline information control. Help must be accessible by mouse hover, keyboard focus and touch/click without changing the selected value.
