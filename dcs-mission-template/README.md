# ORION Mission Template

This directory defines the source contract for an ORION-ready DCS mission.
It is not yet a prebuilt `.miz` file.

## Author workflow

1. Open a mission in DCS Mission Editor.
2. Add a `MISSION START` trigger.
3. Add a `DO SCRIPT FILE` action that loads `ORION_MissionPack.lua`.
4. Save the mission as a separate ORION copy.
5. Run the ORION Mission Manager inspection endpoint.

## Safe-slot contract

`ORION_SafeSlot.lua` is a development marker used by automated tests and by
future template generation. It must not be treated as a substitute for a real
DCS Mission Editor trigger until the generated `.miz` has been verified in DCS.

ORION never modifies the original mission. Automatic activation is allowed only
for a recognized template contract; unknown mission structures require the
manual Mission Editor workflow above.

## Planned verified template

A binary template will be added after it has been created and re-saved by the
current DCS Mission Editor and then tested in both single-player and multiplayer
server environments.
