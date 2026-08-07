-- ORION DCS Export prototype
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
    if type(value) ~= "number" then return "null" end
    return string.format("%.6f", value)
end

local function jsonBoolean(value)
    return value and "true" or "false"
end

local function extractJsonString(payload, key)
    return payload:match('"' .. key .. '"%s*:%s*"([^"]*)"')
end

local function extractJsonNumber(payload, key)
    local raw = payload:match('"' .. key .. '"%s*:%s*(-?[%d%.]+)')
    return raw and tonumber(raw) or nil
end

local function safeArgument(device, argument)
    if not device or type(device.get_argument_value) ~= "function" or type(argument) ~= "number" then return nil end
    local ok, value = pcall(device.get_argument_value, device, argument)
    if ok and type(value) == "number" then return value end
    return nil
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
    if not diagnostics.enabled or not selfData or selfData.Name ~= "FA-18C_hornet" then
        return "null"
    end

    diagnostics.frame = diagnostics.frame + 1
    if diagnostics.frame % diagnostics.sample_every_frames ~= 0 then
        return "null"
    end

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
        diagnostics.min_argument,
        diagnostics.max_argument,
        table.concat(changes, ",")
    )
end

local function applyCockpitMapping(payload)
    local required = {
        "tacan_power",
        "tacan_channel_tens",
        "tacan_channel_ones",
        "tacan_xy",
        "comm1_selector",
        "comm2_selector",
    }
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

function LuaExportAfterNextFrame()
    if previousLuaExportAfterNextFrame then
        previousLuaExportAfterNextFrame()
    end

    local commandPayload = commandUdp:receive()
    if commandPayload then handleCommand(commandPayload) end

    local selfData = LoGetSelfData()
    if not selfData then return end

    local velocity = LoGetVectorVelocity() or {x = 0, y = 0, z = 0}
    local speed = math.sqrt(velocity.x ^ 2 + velocity.y ^ 2 + velocity.z ^ 2)
    local heading = math.deg(selfData.Heading or 0) % 360
    local cockpitState = hornetCockpitState(selfData) or "null"
    local diagnosticState = diagnosticsJson(selfData)

    local payload = string.format(
        '{"protocol_version":"0.2","source":"dcs-export","state":{' ..
        '"aircraft_type":%s,"position":{"latitude":%.8f,"longitude":%.8f,"altitude_m":%.2f},' ..
        '"heading_deg":%.2f,"true_airspeed_mps":%.2f,"vertical_speed_mps":%.2f,"cockpit_state":%s,"diagnostics":%s}}',
        jsonString(selfData.Name),
        selfData.LatLongAlt.Lat,
        selfData.LatLongAlt.Long,
        selfData.LatLongAlt.Alt,
        heading,
        speed,
        velocity.y,
        cockpitState,
        diagnosticState
    )

    telemetryUdp:sendto(payload, ORION_HOST, ORION_TELEMETRY_PORT)
end
