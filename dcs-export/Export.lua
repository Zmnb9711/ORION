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

local function extractJsonString(payload, key)
    return payload:match('"' .. key .. '"%s*:%s*"([^"]*)"')
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
    if commandPayload then
        handleCommand(commandPayload)
    end

    local selfData = LoGetSelfData()
    if not selfData then return end

    local velocity = LoGetVectorVelocity() or {x = 0, y = 0, z = 0}
    local speed = math.sqrt(velocity.x ^ 2 + velocity.y ^ 2 + velocity.z ^ 2)
    local heading = math.deg(selfData.Heading or 0) % 360

    local payload = string.format(
        '{"protocol_version":"0.1","source":"dcs-export","state":{' ..
        '"aircraft_type":%s,"position":{"latitude":%.8f,"longitude":%.8f,"altitude_m":%.2f},' ..
        '"heading_deg":%.2f,"true_airspeed_mps":%.2f,"vertical_speed_mps":%.2f}}',
        jsonString(selfData.Name),
        selfData.LatLongAlt.Lat,
        selfData.LatLongAlt.Long,
        selfData.LatLongAlt.Alt,
        heading,
        speed,
        velocity.y
    )

    telemetryUdp:sendto(payload, ORION_HOST, ORION_TELEMETRY_PORT)
end
