-- Coins, multipliers, passes, rebirth, daily rewards, and state sync to clients.
local MarketplaceService = game:GetService("MarketplaceService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Config = require(ReplicatedStorage.Shared.Config)
local Format = require(ReplicatedStorage.Shared.Format)
local Remotes = require(ReplicatedStorage.Shared.Remotes)
local DataService = require(script.Parent.DataService)

local Economy = {}

local passes = {} -- [Player] = { [passKey] = true }
local dirty = {} -- [Player] = true
local club = {} -- [Player] = true while subscribed
local friendSets = {} -- [Player] = { [Player] = true }
local lastOffer = {} -- [Player] = os.clock()

local function toast(player, text)
	Remotes.Notify:FireClient(player, { Type = "Toast", Text = text })
end
Economy.Toast = toast

-- Passes -----------------------------------------------------------------
function Economy.HasPass(player, key)
	local owned = passes[player]
	return owned ~= nil and owned[key] == true
end

function Economy.LoadPasses(player)
	passes[player] = {}
	for key, info in Config.GamePasses do
		if info.Id ~= 0 then
			local ok, owns = pcall(function()
				return MarketplaceService:UserOwnsGamePassAsync(player.UserId, info.Id)
			end)
			if ok and owns then
				passes[player][key] = true
			end
		end
	end
	Economy.RefreshClub(player)
	Economy.Push(player)
end

function Economy.GrantPass(player, key)
	passes[player] = passes[player] or {}
	passes[player][key] = true
	toast(player, "Purchased " .. Config.GamePasses[key].Name .. "!")
	Economy.Push(player)
end

function Economy.ClearPlayer(player)
	passes[player] = nil
	dirty[player] = nil
	club[player] = nil
	lastOffer[player] = nil
	for _, set in friendSets do
		set[player] = nil
	end
	friendSets[player] = nil
end

-- Subscription (Crystal Club) ---------------------------------------------
function Economy.IsClub(player)
	return club[player] == true
end

function Economy.RefreshClub(player)
	local id = Config.Subscription.Id
	if id == "" then
		return
	end
	local ok, status = pcall(function()
		return MarketplaceService:GetUserSubscriptionStatusAsync(player, id)
	end)
	club[player] = ok and type(status) == "table" and status.IsSubscribed == true
	Economy.Push(player)
end

-- Friends bonus ---------------------------------------------------------------
function Economy.TrackFriends(player)
	friendSets[player] = friendSets[player] or {}
	for _, other in Players:GetPlayers() do
		if other ~= player then
			local ok, isFriend = pcall(function()
				return player:IsFriendsWith(other.UserId)
			end)
			if ok and isFriend and player.Parent and other.Parent then
				friendSets[player][other] = true
				friendSets[other] = friendSets[other] or {}
				friendSets[other][player] = true
				Economy.Push(other)
			end
		end
	end
	Economy.Push(player)
end

function Economy.FriendCount(player)
	local count = 0
	for other in friendSets[player] or {} do
		if other.Parent then
			count += 1
		end
	end
	return count
end

function Economy.FriendBonus(player)
	return math.min(Economy.FriendCount(player), Config.FriendBonusCap) * Config.FriendBonus
end

-- Contextual purchase offers (only for products that are configured) ----------
function Economy.Offer(player, productKey, text)
	local info = Config.Products[productKey]
	if not info or info.Id == 0 then
		return
	end
	if lastOffer[player] and os.clock() - lastOffer[player] < 180 then
		return
	end
	lastOffer[player] = os.clock()
	Remotes.Notify:FireClient(player, { Type = "Offer", Product = productKey, Text = text })
end

function Economy.OfferCoins(player)
	local data = DataService.Get(player)
	if data and not data.StarterBought and Config.Products.StarterPack.Id ~= 0 then
		Economy.Offer(player, "StarterPack", "Starter Pack: 25K coins + a Wolf pet for a great price!")
	else
		Economy.Offer(player, "CoinsSmall", "Short on coins? Grab a Coin Pack and keep going!")
	end
end

-- Leaderstats ------------------------------------------------------------
function Economy.SetupPlayer(player)
	local stats = Instance.new("Folder")
	stats.Name = "leaderstats"
	for _, name in { "Coins", "Rebirths" } do
		local value = Instance.new("IntValue")
		value.Name = name
		value.Parent = stats
	end
	stats.Parent = player
	Economy.SyncLeaderstats(player)
end

function Economy.SyncLeaderstats(player)
	local data = DataService.Get(player)
	local stats = player:FindFirstChild("leaderstats")
	if not data or not stats then
		return
	end
	stats.Coins.Value = math.floor(data.Coins)
	stats.Rebirths.Value = data.Rebirths
end

-- Multipliers ------------------------------------------------------------
function Economy.GetSlots(player)
	local slots = Config.BaseSlots
	if Economy.HasPass(player, "ExtraSlots") then
		slots += Config.ExtraSlotsBonus
	end
	if Economy.IsClub(player) then
		slots += Config.Subscription.ExtraSlots
	end
	return slots
end

function Economy.GetMultiplier(player)
	local data = DataService.Get(player)
	if not data then
		return 1
	end
	local petBonus = 0
	for _, name in data.Equipped do
		petBonus += Config.Pets[name].Mult
	end
	local mult = (1 + petBonus) * (1 + Config.RebirthBonus * data.Rebirths)
	if Economy.HasPass(player, "DoubleCoins") then
		mult *= 2
	end
	if Economy.HasPass(player, "VIP") then
		mult *= Config.VIPMultiplier
	end
	if data.BoostUntil > os.time() then
		mult *= Config.BoostMultiplier
	end
	if Economy.IsClub(player) then
		mult *= Config.Subscription.CoinMultiplier
	end
	mult *= 1 + Economy.FriendBonus(player)
	return mult
end

-- Coins ------------------------------------------------------------------
function Economy.AddCoins(player, amount)
	local data = DataService.Get(player)
	if not data then
		return
	end
	data.Coins += amount
	Economy.SyncLeaderstats(player)
	Economy.Push(player)
end

function Economy.SpendCoins(player, amount)
	local data = DataService.Get(player)
	if not data or data.Coins < amount then
		return false
	end
	data.Coins -= amount
	Economy.SyncLeaderstats(player)
	Economy.Push(player)
	return true
end

-- Zones ------------------------------------------------------------------
function Economy.UnlockZone(player, zoneId)
	local data = DataService.Get(player)
	local zone = Config.ZoneById[zoneId]
	if not data or not zone then
		return
	end
	if data.Zones[zoneId] then
		return toast(player, zone.Name .. " is already unlocked.")
	end
	if not Economy.SpendCoins(player, zone.Cost) then
		return toast(player, "You need " .. Format.Number(zone.Cost) .. " coins to unlock " .. zone.Name .. ".")
	end
	data.Zones[zoneId] = true
	toast(player, "Unlocked " .. zone.Name .. "!")
	Economy.Push(player)
end

-- Rebirth ----------------------------------------------------------------
function Economy.Rebirth(player)
	local data = DataService.Get(player)
	if not data then
		return false
	end
	local cost = Config.RebirthCost(data.Rebirths)
	if data.Coins < cost then
		toast(player, "You need " .. Format.Number(cost) .. " coins to rebirth.")
		return false
	end
	data.Coins = 0
	data.Zones = { Meadow = true }
	data.Rebirths += 1
	Economy.SyncLeaderstats(player)
	toast(player, "Rebirth " .. data.Rebirths .. "! Permanent bonus increased.")
	Economy.Offer(player, "Boost", "Rebirth complete! Re-climb twice as fast with a 2x Boost.")
	Economy.Push(player)
	return true
end

-- Daily reward -----------------------------------------------------------
local function dailyReady(data)
	return os.time() - data.LastDaily >= Config.DailyCooldown
end

function Economy.ClaimDaily(player)
	local data = DataService.Get(player)
	if not data or not dailyReady(data) then
		return false
	end
	local gap = os.time() - data.LastDaily
	if data.LastDaily > 0 and gap <= Config.DailyStreakWindow then
		data.DailyStreak = data.DailyStreak % #Config.DailyRewards + 1
	else
		data.DailyStreak = 1
	end
	data.LastDaily = os.time()
	local reward = Config.DailyRewards[data.DailyStreak] * (1 + data.Rebirths)
	if Economy.HasPass(player, "VIP") then
		reward *= 2
	end
	Economy.AddCoins(player, reward)
	toast(player, string.format("Daily reward day %d: +%s coins!", data.DailyStreak, Format.Number(reward)))
	return true
end

-- State sync (batched, ~5x per second max) ---------------------------------
local function buildState(player)
	local data = DataService.Get(player)
	if not data then
		return nil
	end
	return {
		Coins = data.Coins,
		Rebirths = data.Rebirths,
		Pets = data.Pets,
		Equipped = data.Equipped,
		Zones = data.Zones,
		Multiplier = Economy.GetMultiplier(player),
		Slots = Economy.GetSlots(player),
		Passes = passes[player] or {},
		BoostUntil = data.BoostUntil,
		OwnedCosmetics = data.OwnedCosmetics,
		Club = Economy.IsClub(player),
		FriendBonus = Economy.FriendBonus(player),
		StarterBought = data.StarterBought,
		EquippedTrail = data.EquippedTrail,
		DailyReady = dailyReady(data),
		DailyStreak = data.DailyStreak,
		RebirthCost = Config.RebirthCost(data.Rebirths),
		ServerTime = os.time(),
	}
end

function Economy.Push(player)
	dirty[player] = true
end

function Economy.Start()
	task.spawn(function()
		while true do
			task.wait(0.2)
			for player in dirty do
				dirty[player] = nil
				if player.Parent then
					local state = buildState(player)
					if state then
						Remotes.State:FireClient(player, state)
					end
				end
			end
		end
	end)
end

return Economy
