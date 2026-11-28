-- Minimal, safe DataStore wrapper: retries, reconcile, never overwrites on failed load.
local DataStoreService = game:GetService("DataStoreService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local Config = require(ReplicatedStorage.Shared.Config)

local DataService = {}

-- GetDataStore throws in an unpublished place; never let that stop the whole game from starting.
local storeOk, store = pcall(function()
	return DataStoreService:GetDataStore("CrystalPets_v1")
end)
if not storeOk then
	warn("[DataService] DataStore unavailable:", store)
	store = nil
end

-- Session lock: stops two servers from editing the same player's data at once
-- (e.g. rapid server hopping), which could roll back or duplicate purchases.
local JOB_ID = game.JobId ~= "" and game.JobId or "studio"
local LOCK_TIMEOUT = 90 -- a lock older than this (crashed server) can be taken over
local LOCK_RETRIES = 8
local LOCK_WAIT = 3

local function lockedByOther(data)
	local lock = type(data) == "table" and data.SessionLock
	return lock and lock.JobId ~= JOB_ID and os.time() - lock.Time < LOCK_TIMEOUT
end
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
	StarterBought = false,
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
	local trail = Config.Cosmetics[data.EquippedTrail]
	if data.EquippedTrail ~= "" and not data.OwnedCosmetics[data.EquippedTrail] and not (trail and trail.ClubOnly) then
		data.EquippedTrail = ""
	end
end

function DataService.Load(player)
	local key = "Player_" .. player.UserId
	local ok, result
	local errors = 0
	for _ = 1, LOCK_RETRIES do
		if not store then
			ok, result = false, "DataStore unavailable (place not published?)"
			break
		end
		local locked = false
		ok, result = pcall(function()
			return store:UpdateAsync(key, function(old)
				locked = false
				if lockedByOther(old) then
					locked = true
					return nil -- cancel: another server still owns this player
				end
				old = type(old) == "table" and old or {}
				old.SessionLock = { JobId = JOB_ID, Time = os.time() }
				return old
			end)
		end)
		if ok and not locked then
			break
		end
		if ok and locked then
			ok, result = false, "session locked by another server"
		else
			-- A real DataStore error (not a lock). In Studio this almost always means the place is not
			-- published or API access is off, so fail fast instead of stalling the player for ~24 seconds.
			errors += 1
			if RunService:IsStudio() or errors >= 3 then
				break
			end
		end
		task.wait(LOCK_WAIT)
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
		warn(
			"[DataService] SAVING IS OFF in this test. Fix: File > Save to Roblox, then Home > Game Settings >"
				.. " Security > Enable Studio Access to API Services, then press Play again."
		)
		player:SetAttribute("SavingOff", true)
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

function DataService.Save(player, release)
	local profile = profiles[player]
	if not profile or not profile.CanSave then
		return false
	end
	local snapshot = deepCopy(profile.Data)
	snapshot.LastSave = os.time()
	for _ = 1, 3 do
		local lost = false
		local ok, err = pcall(function()
			store:UpdateAsync(profile.Key, function(old)
				lost = false
				if lockedByOther(old) then
					lost = true
					return nil -- we lost the lock; never overwrite the other server's data
				end
				snapshot.SessionLock = if release then nil else { JobId = JOB_ID, Time = os.time() }
				return snapshot
			end)
		end)
		if ok and lost then
			warn("[DataService] Lost session lock for", player.Name, "- not saving")
			return false
		end
		if ok then
			return true
		end
		warn("[DataService] Save failed for", player.Name, err)
		task.wait(1)
	end
	return false
end

function DataService.Release(player)
	DataService.Save(player, true)
	profiles[player] = nil
end

return DataService
