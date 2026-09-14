-- Offline source execution: no socket, simulator, command or provider I/O.
local packet = nil
package.loaded.socket = {udp=function() return {
    settimeout=function() end, setsockname=function() end,
    receive=function() return nil end,
    sendto=function(_, payload) packet=payload end
} end}
LoGetSelfData = function() return {Name='fixture-aircraft', Heading=1,
    LatLongAlt={Lat=42, Long=62, Alt=1234}} end
LoGetVectorVelocity = function() return {x=12,y=3,z=4} end
LoGetTrueAirSpeed = function() return 80 end
LoGetVerticalVelocity = function() return -2 end
LoGetAltitudeAboveGroundLevel = function() return 500 end
dofile('dcs-export/Export.lua')
LuaExportAfterNextFrame(); print(packet)
LoGetTrueAirSpeed = function() return 0 end
LoGetVerticalVelocity = function() return 0 end
LoGetAltitudeAboveGroundLevel = function() return 0 end
LuaExportAfterNextFrame(); print(packet)
LoGetTrueAirSpeed = function() error('fixture unavailable') end
LoGetVerticalVelocity = nil
LoGetAltitudeAboveGroundLevel = function() return -1 end
LuaExportAfterNextFrame(); print(packet)
LoGetTrueAirSpeed = function() return '80' end
LoGetVerticalVelocity = function() return false end
LoGetAltitudeAboveGroundLevel = nil
LuaExportAfterNextFrame(); print(packet)
