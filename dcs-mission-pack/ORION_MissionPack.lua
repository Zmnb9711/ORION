-- ORION Mission Pack v0.1
-- Load from a MISSION START / DO SCRIPT FILE trigger.
-- This module exposes an allowlisted mission API. It does not open sockets and
-- does not execute arbitrary Lua received from outside the mission.

ORION_MISSION_PACK = ORION_MISSION_PACK or {}

local pack = ORION_MISSION_PACK
pack.version = "0.1.0"
pack.protocolVersion = "0.2"
pack.capabilities = {
    laser = true,
    smoke = true,
    awacs = true,
    tanker = true,
    tasking = false,
    artillery = false,
    csar = false,
}
pack.activeLasers = pack.activeLasers or {}

local function unitByName(name)
    if not name then return nil, "unit name is required" end
    local unit = Unit.getByName(name)
    if not unit or not unit:isExist() then
        return nil, "unit not found: " .. tostring(name)
    end
    return unit, nil
end

local function laser(command)
    local provider, providerError = unitByName(command.provider_unit_id)
    if not provider then return false, providerError end
    local target, targetError = unitByName(command.target_unit_id)
    if not target then return false, targetError end

    local code = tonumber(command.laser_code)
    if not code then return false, "laser_code is required" end

    local oldSpot = pack.activeLasers[command.command_id]
    if oldSpot then oldSpot:destroy() end

    local spot = Spot.createLaser(
        provider,
        {x = 0, y = 2, z = 0},
        target:getPoint(),
        code
    )
    pack.activeLasers[command.command_id] = spot
    return true, "laser active"
end

local smokeColors = {
    green = trigger.smokeColor.Green,
    red = trigger.smokeColor.Red,
    white = trigger.smokeColor.White,
    orange = trigger.smokeColor.Orange,
    blue = trigger.smokeColor.Blue,
}

local function smoke(command)
    local target, targetError = unitByName(command.target_unit_id)
    if not target then return false, targetError end
    local color = smokeColors[command.smoke_color or "red"]
    if not color then return false, "unsupported smoke color" end
    trigger.action.smoke(target:getPoint(), color)
    return true, "smoke placed"
end

local handlers = {
    laser = laser,
    smoke = smoke,
}

function pack.getRegistration(missionId)
    local capabilities = {}
    for name, enabled in pairs(pack.capabilities) do
        if enabled then table.insert(capabilities, name) end
    end
    return {
        mission_id = missionId or "unknown",
        pack_version = pack.version,
        protocol_version = pack.protocolVersion,
        capabilities = capabilities,
    }
end

function pack.execute(command)
    if type(command) ~= "table" then
        return {status = "failed", detail = "command must be a table"}
    end
    local handler = handlers[command.command]
    if not handler or not pack.capabilities[command.command] then
        return {status = "failed", detail = "unsupported mission command"}
    end
    local ok, detail = handler(command)
    return {
        command_id = command.command_id,
        status = ok and "completed" or "failed",
        detail = detail,
    }
end

trigger.action.outText("ORION Mission Pack " .. pack.version .. " loaded", 5)
