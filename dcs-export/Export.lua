-- ORION DCS Export prototype
-- Install by loading this file from Saved Games/DCS/Scripts/Export.lua.

local socket = require("socket")
local udp = socket.udp()
udp:settimeout(0)

local ORION_HOST = "127.0.0.1"
local ORION_PORT = 45100
local previousLuaExportAfterNextFrame = LuaExportAfterNextFrame

local function jsonString(value)
    if value == nil then return "null" end
    return string.format("%q", tostring(value))
end

function LuaExportAfterNextFrame()
    if previousLuaExportAfterNextFrame then
        previousLuaExportAfterNextFrame()
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

    udp:sendto(payload, ORION_HOST, ORION_PORT)
end
