-- Trail cosmetics: bought with coins (server-validated) or granted via developer product.
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Config = require(ReplicatedStorage.Shared.Config)
local Format = require(ReplicatedStorage.Shared.Format)
local DataService = require(script.Parent.DataService)
local Economy = require(script.Parent.Economy)

local Cosmetics = {}

-- Replicates the equipped trail to all clients via a player attribute.
function Cosmetics.Refresh(player)
	local data = DataService.Get(player)
	if data then
		player:SetAttribute("Trail", data.EquippedTrail)
	end
	Economy.Push(player)
end

function Cosmetics.Grant(player, id)
	local data = DataService.Get(player)
	local info = Config.Cosmetics[id]
	if not data or not info then
		return
	end
	data.OwnedCosmetics[id] = true
	data.EquippedTrail = id
	Economy.Toast(player, "Unlocked " .. info.Name .. "!")
	Cosmetics.Refresh(player)
end

function Cosmetics.Handle(player, action, id)
	local data = DataService.Get(player)
	if not data or type(action) ~= "string" or type(id) ~= "string" then
		return false
	end

	if action == "Equip" then
		if id == "" then
			data.EquippedTrail = ""
		elseif Config.Cosmetics[id] and data.OwnedCosmetics[id] then
			data.EquippedTrail = id
		else
			return false
		end
	elseif action == "Buy" then
		local info = Config.Cosmetics[id]
		if not info or not info.Cost or data.OwnedCosmetics[id] then
			return false
		end
		if not Economy.SpendCoins(player, info.Cost) then
			Economy.Toast(player, "You need " .. Format.Number(info.Cost) .. " coins.")
			return false
		end
		Cosmetics.Grant(player, id)
		return true
	else
		return false
	end

	Cosmetics.Refresh(player)
	return true
end

return Cosmetics
