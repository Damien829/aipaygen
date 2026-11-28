-- Minimal, safe DataStore wrapper: retries, reconcile, never overwrites on failed load.
local DataStoreService = game:GetService("DataStoreService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local Config = require(ReplicatedStorage.Shared.Config)

local DataService = {}

local store = DataStoreService:GetDataStore("CrystalPets_v1")
local profiles = {} -- [Player] = { Data, Key, CanSave }

local DEFAULT = {
	Coins = 0,
	Rebirths = 0,
	Pets = {}, -- [petName] = count
	Equipped = {}, -- array of petNames
	Zones = { Meadow = true },
	TotalMined = 0,
	LastDaily = 0,
	DailyStreak = 0,
	BoostUntil = 0,
	OwnedCosmetics = {}, -- [cosmeticId] = true
	EquippedTrail = "",
	Receipts = {}, -- recent PurchaseIds (idempotent ProcessReceipt)
}

local function deepCopy(value)
	if type(value) ~= "table" then
		return value
	end
	local copy = {}
	for k, v in value do
		copy[k] = deepCopy(v)
	end
	return copy
end

local function reconcile(data, template)
	for k, v in template do
		if data[k] == nil then
			data[k] = deepCopy(v)
		elseif type(v) == "table" and type(data[k]) == "table" then
			reconcile(data[k], v)
		end
	end
end

local function sanitize(data)
	local cleaned, used = {}, {}
	for _, name in data.Equipped do
		if Config.Pets[name] and (data.Pets[name] or 0) > (used[name] or 0) then
			used[name] = (used[name] or 0) + 1
			table.insert(cleaned, name)
		end
	end
	data.Equipped = cleaned
	data.Zones.Meadow = true
	if data.EquippedTrail ~= "" and not data.OwnedCosmetics[data.EquippedTrail] then
		data.EquippedTrail = ""
	end
end

function DataService.Load(player)
	local key = "Player_" .. player.UserId
	local ok, result
	for _ = 1, 4 do
		ok, result = pcall(function()
			return store:GetAsync(key)
		end)
		if ok then
			break
		end
		task.wait(1.5)
	end

	local data
	if ok then
		data = type(result) == "table" and result or deepCopy(DEFAULT)
		reconcile(data, DEFAULT)
	else
		warn("[DataService] Failed to load data for", player.Name, result)
		if not RunService:IsStudio() then
			return nil -- caller kicks the player so we never overwrite real progress
		end
		data = deepCopy(DEFAULT)
	end

	sanitize(data)
	profiles[player] = { Data = data, Key = key, CanSave = ok }
	return data
end

function DataService.Get(player)
	local profile = profiles[player]
	return profile and profile.Data
end

function DataService.Save(player)
	local profile = profiles[player]
	if not profile or not profile.CanSave then
		return false
	end
	local snapshot = deepCopy(profile.Data)
	snapshot.LastSave = os.time()
	for _ = 1, 3 do
		local ok, err = pcall(function()
			store:UpdateAsync(profile.Key, function()
				return snapshot
			end)
		end)
		if ok then
			return true
		end
		warn("[DataService] Save failed for", player.Name, err)
		task.wait(1)
	end
	return false
end

function DataService.Release(player)
	DataService.Save(player)
	profiles[player] = nil
end

return DataService
