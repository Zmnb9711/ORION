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

local function jsonString(value)
    if value == nil then return "null" end
    return string.format("%q", tostring(value))
end

local function jsonNumber(value)
    if type(value) ~= "number" then return "null" end
    return string.format("%.6f", value)
end

local function extractJsonString(payload, key)
    return payload:match('"' .. key .. '"%s*:%s*"([^"]*)"')
end

local function safeArgument(device, argument)
    if not device or type(device.get_argument_value) ~= "function" then return nil end
    local ok, value = pcall(device.get_argument_value, device, argument)
    if ok and type(value) == "number" then return value end
    return nil
end

local function hornetCockpitState(selfData)
    if not selfData or selfData.Name ~= "FA-18C_hornet" then return nil end

    -- DCS clickable argument IDs are intentionally isolated here. They are
    -- raw simulator observations, not inferred state. Unknown/unavailable
    -- values remain null so ORION never invents cockpit data.
    local ok, main = pcall(GetDevice, 0)
    if not ok then main = nil end

    local state = {
        comm1_selector = safeArgument(main, 133),
        comm2_selector = safeArgument(main, 134),
        tacan_power = safeArgument(main, 410),
        tacan_channel_tens = safeArgument(main, 411),
        tacan_channel_ones = safeArgument(main, 412),
        tacan_xy = safeArgument(main, 413),
        left_ddi_brightness = safeArgument(main, 198),
        right_ddi_brightness = safeArgument(main, 201),
        mpcd_brightness = safeArgument(main, 203),
    }

    return string.format(
        '{"aircraft_id":"fa-18c","mapping_version":"fa18c-clickable-v0","mapping_validated":false,"raw_arguments":{' ..
        '"comm1_selector":%s,"comm2_selector":%s,' ..
        '"tacan_power":%s,"tacan_channel_tens":%s,"tacan_channel_ones":%s,"tacan_xy":%s,' ..
        '"left_ddi_brightness":%s,"right_ddi_brightness":%s,"mpcd_brightness":%s}}',
        jsonNumber(state.comm1_selector), jsonNumber(state.comm2_selector),
        jsonNumber(state.tacan_power), jsonNumber(state.tacan_channel_tens),
        jsonNumber(state.tacan_channel_ones), jsonNumber(state.tacan_xy),
        jsonNumber(state.left_ddi_brightness), jsonNumber(state.right_ddi_brightness),
        jsonNumber(state.mpcd_brightness)
    )
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

    local payload = string.format(
        '{"protocol_version":"0.2","source":"dcs-export","state":{' ..
        '"aircraft_type":%s,"position":{"latitude":%.8f,"longitude":%.8f,"altitude_m":%.2f},' ..
        '"heading_deg":%.2f,"true_airspeed_mps":%.2f,"vertical_speed_mps":%.2f,"cockpit_state":%s}}',
        jsonString(selfData.Name),
        selfData.LatLongAlt.Lat,
        selfData.LatLongAlt.Long,
        selfData.LatLongAlt.Alt,
        heading,
        speed,
        velocity.y,
        cockpitState
    )

    telemetryUdp:sendto(payload, ORION_HOST, ORION_TELEMETRY_PORT)
end
