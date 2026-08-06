# ADR-003: ORION settings boundary

## Status
Accepted

## Decision
ORION configures only ORION.

The application must not expose controls that modify DCS graphics or controls, VR headset settings, OpenXR or SteamVR runtime settings, GPU driver settings, Quad Views, foveated rendering, DLSS, or other third-party software.

ORION may use a user-selected DCS installation and launch mode, but it must not rewrite DCS or third-party configuration files as part of the settings system.

## Settings scope
The settings UI and API may contain only:

- DCS installation references used by ORION;
- ORION launch profiles;
- ORION voice and language behavior;
- ORION AI behavior and memory policy;
- ORION Mission Pack behavior;
- ORION interface behavior;
- ORION hotkeys when implemented;
- ORION version and update information.

## Placement rule
A value needed before most flights belongs on the Launch Screen. A value normally configured once belongs in Settings.

## Consequences
This keeps ORION predictable, prevents configuration conflicts, and reduces support burden caused by changes in third-party software.