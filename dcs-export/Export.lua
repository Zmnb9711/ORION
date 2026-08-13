-- ORION DCS Export telemetry bridge
-- Install by loading this file from Saved Games/DCS/Scripts/Export.lua.

local socket = require("socket")
local telemetryUdp = socket.udp()
telemetryUdp:settimeout(0)

local commandUdp = socket.udp()
commandUdp:settimeout(0)
commandUdp:setsockname("127.0.0.1", 45101)

local ORION_HOST = "127.0.0.1"
local ORION_TELEMETRY_PORT = 45100
local previousLuaExportAfterNextFrame = LuaExportAfterNextFrame
local telemetrySequence = 0

local cockpitMapping = {
    version = "fa18c-clickable-v0",
    validated = false,
    comm1_selector = 133,
    comm2_selector = 134,
    tacan_power = 410,
    tacan_channel_tens = 411,
    tacan_channel_ones = 412,
    tacan_xy = 413,
    left_ddi_brightness = 198,
    right_ddi_brightness = 201,
    mpcd_brightness = 203,
}

local diagnostics = {
    enabled = false,
    min_argument = 0,
    max_argument = 999,
    epsilon = 0.001,
    sample_every_frames = 10,
    frame = 0,
    previous = {},
}

local function jsonString(value)
    if value == nil then return "null" end
    return string.format("%q", tostring(value))
end

local function jsonNumber(value)
    if type(value) ~= "number" or value ~= value or value == math.huge or value == -math.huge then return "null" end
    return string.format("%.6f", value)
end

local function jsonBoolean(value)
    if type(value) ~= "boolean" then return "null" end
    return value and "true" or "false"
end

local function jsonScalar(value)
    if type(value) == "number" then return jsonNumber(value) end
    if type(value) == "boolean" then return jsonBoolean(value) end
    if type(value) == "string" then return jsonString(value) end
    return "null"
end

local function extractJsonString(payload, key)
    return payload:match('"' .. key .. '"%s*:%s*"([^"]*)"')
end

local function extractJsonNumber(payload, key)
    local raw = payload:match('"' .. key .. '"%s*:%s*(-?[%d%.]+)')
    return raw and tonumber(raw) or nil
end

local function safeCall(name)
    local fn = _G[name]
    if type(fn) ~= "function" then return nil, false end
    local ok, value = pcall(fn)
    if not ok then return nil, false end
    return value, true
end

local function safeTriple(name)
    local fn = _G[name]
    if type(fn) ~= "function" then return nil, nil, nil, false end
    local ok, a, b, c = pcall(fn)
    if not ok then return nil, nil, nil, false end
    return a, b, c, true
end

local function safeArgument(device, argument)
    if not device or type(device.get_argument_value) ~= "function" or type(argument) ~= "number" then return nil end
    local ok, value = pcall(device.get_argument_value, device, argument)
    if ok and type(value) == "number" then return value end
    return nil
end

local function pairJson(value)
    if type(value) ~= "table" then return "null" end
    return string.format('{"left":%s,"right":%s}', jsonNumber(value.left), jsonNumber(value.right))
end

local function mechItemJson(value)
    if type(value) ~= "table" then return "null" end
    return string.format('{"status":%s,"value":%s}', jsonScalar(value.status), jsonNumber(value.value))
end

local function airframeJson(mech)
    if type(mech) ~= "table" then return "null" end
    return string.format(
        '{"gear":%s,"flaps":%s,"speedbrakes":%s,"hook":%s,"wing":%s,"canopy":%s,"refueling":%s,"wheelbrakes":%s}',
        mechItemJson(mech.gear), mechItemJson(mech.flaps), mechItemJson(mech.speedbrakes),
        mechItemJson(mech.hook), mechItemJson(mech.wing), mechItemJson(mech.canopy),
        mechItemJson(mech.refuelingboom), mechItemJson(mech.wheelbrakes)
    )
end

local function propulsionJson(engine)
    if type(engine) ~= "table" then return "null" end
    return string.format(
        '{"rpm":%s,"temperature":%s,"fuel_consumption":%s,"hydraulic_pressure":%s}',
        pairJson(engine.RPM), pairJson(engine.Temperature), pairJson(engine.FuelConsumption), pairJson(engine.HydraulicPressure)
    )
end

local function fuelJson(engine)
    if type(engine) ~= "table" then return "null" end
    if type(engine.fuel_internal) ~= "number" and type(engine.fuel_external) ~= "number" then return "null" end
    return string.format(
        '{"internal_raw":%s,"external_raw":%s,"semantics":"module_dependent","documented_unit":"kg"}',
        jsonNumber(engine.fuel_internal), jsonNumber(engine.fuel_external)
    )
end

local function weaponTypeJson(weapon)
    if type(weapon) ~= "table" then return "null" end
    return string.format(
        '[%s,%s,%s,%s]',
        jsonNumber(weapon.level1 or weapon[1]), jsonNumber(weapon.level2 or weapon[2]),
        jsonNumber(weapon.level3 or weapon[3]), jsonNumber(weapon.level4 or weapon[4])
    )
end

local function payloadJson(payload, snares)
    if type(payload) ~= "table" and type(snares) ~= "table" then return "null" end
    local stations = {}
    if type(payload) == "table" and type(payload.Stations) == "table" then
        local indexes = {}
        for index, _ in pairs(payload.Stations) do
            if type(index) == "number" then indexes[#indexes + 1] = index end
        end
        table.sort(indexes)
        for _, index in ipairs(indexes) do
            local station = payload.Stations[index]
            if type(station) == "table" then
                stations[#stations + 1] = string.format(
                    '{"station":%d,"container":%s,"weapon_type":%s,"count":%s}',
                    index, jsonBoolean(station.container == true), weaponTypeJson(station.weapon), jsonNumber(station.count)
                )
            end
        end
    end
    local shells = nil
    if type(payload) == "table" and type(payload.Cannon) == "table" then shells = payload.Cannon.shells end
    local chaff = type(snares) == "table" and snares.chaff or nil
    local flare = type(snares) == "table" and snares.flare or nil
    return string.format(
        '{"current_station":%s,"cannon_shells":%s,"stations":[%s],"countermeasures":{"chaff":%s,"flare":%s}}',
        jsonNumber(type(payload) == "table" and payload.CurrentStation or nil), jsonNumber(shells), table.concat(stations, ","),
        jsonNumber(chaff), jsonNumber(flare)
    )
end

local function navigationJson(nav, beacons)
    if type(nav) ~= "table" and type(beacons) ~= "table" then return "null" end
    local master = nil
    local submode = nil
    local acsMode = nil
    local reqRoll = nil
    local reqPitch = nil
    local reqSpeed = nil
    if type(nav) == "table" then
        if type(nav.SystemMode) == "table" then
            master = nav.SystemMode.master
            submode = nav.SystemMode.submode
        end
        if type(nav.ACS) == "table" then acsMode = nav.ACS.mode end
        if type(nav.Requirements) == "table" then
            reqRoll = nav.Requirements.roll
            reqPitch = nav.Requirements.pitch
            reqSpeed = nav.Requirements.speed
        end
    end
    return string.format(
        '{"system_mode":{"master":%s,"submode":%s},"acs_mode":%s,"requirements":{"roll":%s,"pitch":%s,"speed":%s},' ..
        '"beacons":{"airfield_near":%s,"airfield_far":%s,"course_lock":%s,"glideslope_lock":%s}}',
        jsonString(master), jsonString(submode), jsonScalar(acsMode), jsonNumber(reqRoll), jsonNumber(reqPitch), jsonNumber(reqSpeed),
        jsonScalar(type(beacons) == "table" and beacons.airfield_near or nil),
        jsonScalar(type(beacons) == "table" and beacons.airfield_far or nil),
        jsonScalar(type(beacons) == "table" and beacons.course_deviation_beacon_lock or nil),
        jsonScalar(type(beacons) == "table" and beacons.glideslope_deviation_beacon_lock or nil)
    )
end

local function ewJson(tws)
    if type(tws) ~= "table" then return "null" end
    local emitters = {}
    if type(tws.Emitters) == "table" then
        local count = 0
        for _, emitter in pairs(tws.Emitters) do
            if type(emitter) == "table" and count < 64 then
                count = count + 1
                emitters[#emitters + 1] = string.format(
                    '{"id":%s,"type":%s,"power":%s,"azimuth_rad":%s,"priority":%s,"signal_type":%s}',
                    jsonNumber(emitter.ID), weaponTypeJson(emitter.Type), jsonNumber(emitter.Power), jsonNumber(emitter.Azimuth),
                    jsonNumber(emitter.Priority), jsonString(emitter.SignalType)
                )
            end
        end
    end
    return string.format('{"mode":%s,"emitters":[%s]}', jsonNumber(tws.Mode), table.concat(emitters, ","))
end

local function sensorsJson(info)
    if type(info) ~= "table" then return "null" end
    local prfCurrent = nil
    local prfSelection = nil
    if type(info.PRF) == "table" then
        prfCurrent = info.PRF.current
        prfSelection = info.PRF.selection
    end
    return string.format(
        '{"manufacturer":%s,"launch_authorized":%s,"radar_on":%s,"optical_system_on":%s,"ecm_on":%s,"laser_on":%s,' ..
        '"prf":{"current":%s,"selection":%s}}',
        jsonString(info.Manufacturer), jsonScalar(info.LaunchAuthorized), jsonScalar(info.radar_on),
        jsonScalar(info.optical_system_on), jsonScalar(info.ECM_on), jsonScalar(info.laser_on),
        jsonString(prfCurrent), jsonString(prfSelection)
    )
end

local function hornetCockpitState(selfData)
    if not selfData or selfData.Name ~= "FA-18C_hornet" then return nil end

    local ok, main = pcall(GetDevice, 0)
    if not ok then main = nil end

    local state = {
        comm1_selector = safeArgument(main, cockpitMapping.comm1_selector),
        comm2_selector = safeArgument(main, cockpitMapping.comm2_selector),
        tacan_power = safeArgument(main, cockpitMapping.tacan_power),
        tacan_channel_tens = safeArgument(main, cockpitMapping.tacan_channel_tens),
        tacan_channel_ones = safeArgument(main, cockpitMapping.tacan_channel_ones),
        tacan_xy = safeArgument(main, cockpitMapping.tacan_xy),
        left_ddi_brightness = safeArgument(main, cockpitMapping.left_ddi_brightness),
        right_ddi_brightness = safeArgument(main, cockpitMapping.right_ddi_brightness),
        mpcd_brightness = safeArgument(main, cockpitMapping.mpcd_brightness),
    }

    return string.format(
        '{"aircraft_id":"fa-18c","mapping_version":%s,"mapping_validated":%s,"raw_arguments":{' ..
        '"comm1_selector":%s,"comm2_selector":%s,' ..
        '"tacan_power":%s,"tacan_channel_tens":%s,"tacan_channel_ones":%s,"tacan_xy":%s,' ..
        '"left_ddi_brightness":%s,"right_ddi_brightness":%s,"mpcd_brightness":%s}}',
        jsonString(cockpitMapping.version), jsonBoolean(cockpitMapping.validated),
        jsonNumber(state.comm1_selector), jsonNumber(state.comm2_selector),
        jsonNumber(state.tacan_power), jsonNumber(state.tacan_channel_tens),
        jsonNumber(state.tacan_channel_ones), jsonNumber(state.tacan_xy),
        jsonNumber(state.left_ddi_brightness), jsonNumber(state.right_ddi_brightness),
        jsonNumber(state.mpcd_brightness)
    )
end

local function diagnosticsJson(selfData)
    if not diagnostics.enabled or not selfData or selfData.Name ~= "FA-18C_hornet" then return "null" end
    diagnostics.frame = diagnostics.frame + 1
    if diagnostics.frame % diagnostics.sample_every_frames ~= 0 then return "null" end

    local ok, main = pcall(GetDevice, 0)
    if not ok or not main then return "null" end

    local changes = {}
    for argument = diagnostics.min_argument, diagnostics.max_argument do
        local value = safeArgument(main, argument)
        if value ~= nil then
            local previous = diagnostics.previous[argument]
            if previous == nil or math.abs(value - previous) >= diagnostics.epsilon then
                changes[#changes + 1] = string.format('{"id":%d,"value":%.6f,"previous":%s}', argument, value, jsonNumber(previous))
                diagnostics.previous[argument] = value
            end
        end
    end

    if #changes == 0 then return "null" end
    return string.format(
        '{"mode":"cockpit_argument_changes","aircraft_id":"fa-18c","range":{"min":%d,"max":%d},"changes":[%s]}',
        diagnostics.min_argument, diagnostics.max_argument, table.concat(changes, ",")
    )
end

local function applyCockpitMapping(payload)
    local required = {"tacan_power", "tacan_channel_tens", "tacan_channel_ones", "tacan_xy", "comm1_selector", "comm2_selector"}
    local nextMapping = {}
    for _, key in ipairs(required) do
        local value = extractJsonNumber(payload, key .. "_id")
        if value == nil then
            log.write("ORION", log.WARNING, "Rejected incomplete Hornet cockpit mapping")
            return false
        end
        nextMapping[key] = math.floor(value)
    end

    local optional = {"left_ddi_brightness", "right_ddi_brightness", "mpcd_brightness"}
    for _, key in ipairs(optional) do
        local value = extractJsonNumber(payload, key .. "_id")
        nextMapping[key] = value and math.floor(value) or cockpitMapping[key]
    end

    nextMapping.version = extractJsonString(payload, "mapping_version") or "fa18c-clickable-calibrated-v1"
    nextMapping.validated = true
    cockpitMapping = nextMapping
    log.write("ORION", log.INFO, "Validated Hornet cockpit mapping applied: " .. cockpitMapping.version)
    return true
end

local function handleCommand(payload)
    local command = extractJsonString(payload, "command")
    if command == "ping" then
        log.write("ORION", log.INFO, "Ping received")
    elseif command == "request_status" then
        log.write("ORION", log.INFO, "Status requested")
    elseif command == "show_message" then
        local message = extractJsonString(payload, "message") or ""
        log.write("ORION", log.INFO, "Message: " .. message:sub(1, 240))
    elseif command == "set_cockpit_mapping" then
        applyCockpitMapping(payload)
    elseif command == "start_cockpit_diagnostics" then
        diagnostics.enabled = true
        diagnostics.previous = {}
        diagnostics.frame = 0
        diagnostics.min_argument = math.max(0, math.floor(extractJsonNumber(payload, "min_argument") or diagnostics.min_argument))
        diagnostics.max_argument = math.min(2000, math.floor(extractJsonNumber(payload, "max_argument") or diagnostics.max_argument))
        diagnostics.epsilon = math.max(0.000001, extractJsonNumber(payload, "epsilon") or diagnostics.epsilon)
        log.write("ORION", log.INFO, string.format("Hornet cockpit diagnostics enabled for arguments %d-%d", diagnostics.min_argument, diagnostics.max_argument))
    elseif command == "stop_cockpit_diagnostics" then
        diagnostics.enabled = false
        diagnostics.previous = {}
        log.write("ORION", log.INFO, "Hornet cockpit diagnostics disabled")
    else
        log.write("ORION", log.WARNING, "Rejected unsupported command")
    end
end

local function sendHeartbeat()
    telemetryUdp:sendto(
        '{"kind":"heartbeat","protocol_version":"0.3","source":"dcs-export","aircraft_available":false}',
        ORION_HOST, ORION_TELEMETRY_PORT
    )
end

function LuaExportAfterNextFrame()
    if previousLuaExportAfterNextFrame then previousLuaExportAfterNextFrame() end

    local commandPayload = commandUdp:receive()
    if commandPayload then handleCommand(commandPayload) end

    local selfData, selfOk = safeCall("LoGetSelfData")
    if not selfOk or type(selfData) ~= "table" or type(selfData.LatLongAlt) ~= "table" then
        sendHeartbeat()
        return
    end

    telemetrySequence = telemetrySequence + 1

    local velocity = select(1, safeCall("LoGetVectorVelocity"))
    if type(velocity) ~= "table" then velocity = {x = 0, y = 0, z = 0} end
    local vx = type(velocity.x) == "number" and velocity.x or 0
    local vy = type(velocity.y) == "number" and velocity.y or 0
    local vz = type(velocity.z) == "number" and velocity.z or 0
    local speed = math.sqrt(vx ^ 2 + vy ^ 2 + vz ^ 2)
    local heading = math.deg(selfData.Heading or 0) % 360

    local agl = select(1, safeCall("LoGetAltitudeAboveGroundLevel"))
    if type(agl) == "number" and agl < 0 then agl = 0 end
    local modelTime = select(1, safeCall("LoGetModelTime"))
    local pitch, bank, yaw, attitudeOk = safeTriple("LoGetADIPitchBankYaw")

    local mech, mechOk = safeCall("LoGetMechInfo")
    local engine, engineOk = safeCall("LoGetEngineInfo")
    local nav, navOk = safeCall("LoGetNavigationInfo")
    local beacons, beaconsOk = safeCall("LoGetRadioBeaconsStatus")
    local payloadInfo, payloadOk = safeCall("LoGetPayloadInfo")
    local snares, snaresOk = safeCall("LoGetSnares")

    local sensorAllowed = true
    local sensorPermission, sensorPermissionOk = safeCall("LoIsSensorExportAllowed")
    if sensorPermissionOk and sensorPermission == false then sensorAllowed = false end

    local tws, twsOk = nil, false
    local sighting, sightingOk = nil, false
    if sensorAllowed then
        tws, twsOk = safeCall("LoGetTWSInfo")
        sighting, sightingOk = safeCall("LoGetSightingSystemInfo")
    end

    local cockpitState = hornetCockpitState(selfData) or "null"
    local diagnosticState = diagnosticsJson(selfData)
    local attitudeJson = "null"
    if attitudeOk then
        attitudeJson = string.format(
            '{"pitch_deg":%s,"bank_deg":%s,"yaw_deg":%s}',
            jsonNumber(type(pitch) == "number" and math.deg(pitch) or nil),
            jsonNumber(type(bank) == "number" and math.deg(bank) or nil),
            jsonNumber(type(yaw) == "number" and (math.deg(yaw) % 360) or nil)
        )
    end

    local capabilities = string.format(
        '{"identity":"available","kinematics":"available","airframe":%s,"propulsion":%s,"fuel":%s,' ..
        '"navigation":%s,"radios":"not_yet_mapped","payload":%s,"ew":%s,"sensors":%s,"cockpit":%s,"mission_world":"separate"}',
        jsonString(mechOk and type(mech) == "table" and "available" or "unavailable"),
        jsonString(engineOk and type(engine) == "table" and "available" or "unavailable"),
        jsonString(engineOk and type(engine) == "table" and "available" or "unavailable"),
        jsonString((navOk and type(nav) == "table") or (beaconsOk and type(beacons) == "table") and "available" or "unavailable"),
        jsonString((payloadOk and type(payloadInfo) == "table") or (snaresOk and type(snares) == "table") and "available" or "unavailable"),
        jsonString(not sensorAllowed and "restricted" or (twsOk and type(tws) == "table" and "available" or "unavailable")),
        jsonString(not sensorAllowed and "restricted" or (sightingOk and type(sighting) == "table" and "available" or "unavailable")),
        jsonString(selfData.Name == "FA-18C_hornet" and "available" or "not_yet_mapped")
    )

    local payload = string.format(
        '{"protocol_version":"0.3","source":"dcs-export","sequence":%d,"model_time_s":%s,"state":{' ..
        '"aircraft_type":%s,"position":{"latitude":%.8f,"longitude":%.8f,"altitude_m":%.2f,"altitude_agl_m":%s},' ..
        '"heading_deg":%.2f,"true_airspeed_mps":%.2f,"vertical_speed_mps":%.2f,' ..
        '"attitude":%s,"velocity_vector":{"x_mps":%.6f,"y_mps":%.6f,"z_mps":%.6f},' ..
        '"airframe":%s,"propulsion":%s,"fuel":%s,"navigation":%s,"payload":%s,"ew":%s,"sensors":%s,' ..
        '"capabilities":%s,"cockpit_state":%s,"diagnostics":%s}}',
        telemetrySequence, jsonNumber(modelTime), jsonString(selfData.Name),
        selfData.LatLongAlt.Lat, selfData.LatLongAlt.Long, selfData.LatLongAlt.Alt, jsonNumber(agl),
        heading, speed, vy, attitudeJson, vx, vy, vz,
        airframeJson(mech), propulsionJson(engine), fuelJson(engine), navigationJson(nav, beacons),
        payloadJson(payloadInfo, snares), ewJson(tws), sensorsJson(sighting), capabilities, cockpitState, diagnosticState
    )

    telemetryUdp:sendto(payload, ORION_HOST, ORION_TELEMETRY_PORT)
end
