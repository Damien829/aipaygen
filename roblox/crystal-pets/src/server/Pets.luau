-- Egg hatching and pet equipping. All validation is server-side.
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Config = require(ReplicatedStorage.Shared.Config)
local Format = require(ReplicatedStorage.Shared.Format)
local Remotes = require(ReplicatedStorage.Shared.Remotes)
local DataService = require(script.Parent.DataService)
local Economy = require(script.Parent.Economy)

local Pets = {}

local lastHatch = {} -- [Player] = os.clock()

-- Replicates equipped pets to every client via a player attribute.
function Pets.Refresh(player)
	local data = DataService.Get(player)
	if data then
		player:SetAttribute("EquippedPets", table.concat(data.Equipped, ","))
	end
	Economy.Push(player)
end

local function roll(egg, lucky)
	local weights, total = {}, 0
	for i, entry in egg.Pets do
		local weight = entry[2]
		if lucky then
			weight *= Config.LuckyBoost[Config.Pets[entry[1]].Rarity] or 1
		end
		weights[i] = weight
		total += weight
	end
	local pick = math.random() * total
	for i, entry in egg.Pets do
		pick -= weights[i]
		if pick <= 0 then
			return entry[1]
		end
	end
	return egg.Pets[#egg.Pets][1]
end

function Pets.Hatch(player, eggKey)
	local egg = Config.Eggs[eggKey]
	local data = DataService.Get(player)
	if not egg or not data then
		return
	end

	local now = os.clock()
	if lastHatch[player] and now - lastHatch[player] < Config.HatchCooldown then
		return
	end
	lastHatch[player] = now

	if not data.Zones[egg.Zone] then
		return Economy.Toast(player, "Unlock " .. Config.ZoneById[egg.Zone].Name .. " first!")
	end
	if not Economy.SpendCoins(player, egg.Cost) then
		return Economy.Toast(player, "You need " .. Format.Number(egg.Cost) .. " coins for this egg.")
	end

	local name = roll(egg, Economy.HasPass(player, "LuckyHatch"))
	data.Pets[name] = (data.Pets[name] or 0) + 1

	-- Auto-equip if there is a free slot.
	if #data.Equipped < Economy.GetSlots(player) then
		table.insert(data.Equipped, name)
	end
	Pets.Refresh(player)

	local info = Config.Pets[name]
	Remotes.Notify:FireClient(player, {
		Type = "Hatch",
		Pet = name,
		Icon = info.Icon,
		Rarity = info.Rarity,
		Mult = info.Mult,
	})
end

-- Toggle: equips one copy if there is room, otherwise unequips one copy.
function Pets.Toggle(player, name)
	local data = DataService.Get(player)
	if not data or type(name) ~= "string" or not Config.Pets[name] then
		return false
	end

	local equippedCount, firstIndex = 0, nil
	for i, equipped in data.Equipped do
		if equipped == name then
			equippedCount += 1
			firstIndex = firstIndex or i
		end
	end

	local owned = data.Pets[name] or 0
	if owned > equippedCount and #data.Equipped < Economy.GetSlots(player) then
		table.insert(data.Equipped, name)
	elseif firstIndex then
		table.remove(data.Equipped, firstIndex)
	else
		Economy.Toast(player, "No free pet slots! Unequip a pet first.")
		return false
	end

	Pets.Refresh(player)
	return true
end

function Pets.ClearPlayer(player)
	lastHatch[player] = nil
end

return Pets
