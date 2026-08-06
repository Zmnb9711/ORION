# Aircraft Knowledge Layer

Aircraft Knowledge Layer (AKL) is the module-specific knowledge system used by ORION to explain aircraft systems, answer operational questions, select compatible procedures, support troubleshooting, and adapt mission information to the player's current DCS module.

## Aircraft priority

1. F/A-18C Hornet
2. F-5E Tiger II
3. P-51D Mustang
4. MiG-21bis
5. A-10C II Tank Killer
6. JF-17 Thunder
7. P-47D Thunderbolt
8. Spitfire LF Mk IX
9. AH-64D Apache
10. F-16C Viper
11. Ka-50 III
12. Mi-24P Hind
13. Mi-8MTV2
14. F-14 Tomcat
15. Mirage 2000C
16. AV-8B N/A
17. F-15E Strike Eagle

The first eight positions are user-approved and must not be reordered without an explicit decision.

## Knowledge scope

Each profile may contain knowledge about the cockpit, controls, electrical and fuel systems, engines, hydraulics, flight controls, navigation, communications, autopilot, sensors, radar, electronic warfare, datalink, weapons, performance, limitations, procedures, emergencies, troubleshooting, checklists, and DCS integration.

## Source priority

1. Official module manual or locally installed module documentation.
2. Official Eagle Dynamics or third-party developer documentation and changelogs.
3. Current DCS mission or telemetry data for dynamic state.
4. Corroborated open sources and established community guides.
5. Flight-test observations collected during ORION testing.

A lower-priority source must not silently override an official source. Conflicts are retained as disputed records until reviewed.

## Evidence policy

Every knowledge entry carries:

- one or more source identifiers;
- an evidence level;
- applicability information;
- optional telemetry keys and procedure links;
- a review flag.

Evidence levels are `verified`, `corroborated`, `provisional`, and `disputed`. An entry cannot reference an unknown source. New imported content is provisional and requires review unless it has been checked against an authoritative source.

## F/A-18C initial profile

The F/A-18C profile starts as a schema-complete skeleton. It is not considered operationally complete until its entries are sourced, reviewed, and tested. Initial ingestion should prioritize normal procedures, limitations, emergency procedures, communications, navigation, flight controls, engines, fuel, electrical systems, sensors, radar, electronic warfare, datalink, weapons, and DCS telemetry mappings.

## API

- `GET /v1/aircraft-knowledge/profiles`
- `GET /v1/aircraft-knowledge/profiles/{aircraft_id}`
- `POST /v1/aircraft-knowledge/sources`
- `POST /v1/aircraft-knowledge/entries`
- `POST /v1/aircraft-knowledge/search`

The write endpoints are intended for controlled ingestion tooling. A future ingestion pipeline will extract candidate facts from manuals, preserve page or section references, and queue them for review before release.
