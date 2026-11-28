-- Coins, Star Road, daily streak, quests, ranks, win streaks, parts/paints ownership, passes,
-- name tags and the state the UI shows.
local MarketplaceService = game:GetService("MarketplaceService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Config = require(ReplicatedStorage.Shared.Config)
local Format = require(ReplicatedStorage.Shared.Format)
local Remotes = require(ReplicatedStorage.Shared.Remotes)
local DataService = require(script.Parent.DataService)
local Visuals = require(script.Parent.Visuals)

local Profile = {}

local passes = {} -- [Player] = { [key] = true }
local activity = {} -- [Player] = "Match" | "Story" | nil
local lastOffer = {} -- [Player] = os.clock()
local offered = {} -- [Player] = { [key] = true } (each offer at most once per visit)
local pushQueued = {} -- [Player] = true

local GOLD = Color3.fromRGB(255, 205, 70)
local DAY = 86400

local function toast(player, text, color)
	Remotes.Notify:FireClient(player, { Type = "Toast", Text = text, Color = color })
end
Profile.Toast = toast

function Profile.Feed(text, color)
	Remotes.Notify:FireAllClients({ Type = "Feed", Text = text, Color = color })
end

function Profile.Celebrate(player, title, text, icon)
	Remotes.Notify:FireClient(player, { Type = "Celebrate", Title = title, Text = text, Icon = icon })
end

function Profile.SetActivity(player, value)
	activity[player] = value
	player:SetAttribute("Activity", value)
end

function Profile.GetActivity(player)
	return activity[player]
end

-- Passes -----------------------------------------------------------------------------------------
function Profile.HasPass(player, key)
	local owned = passes[player]
	return owned ~= nil and owned[key] == true
end

function Profile.LoadPasses(player)
	passes[player] = passes[player] or {}
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
end

function Profile.GrantPass(player, key)
	passes[player] = passes[player] or {}
	passes[player][key] = true
	local info = Config.GamePasses[key]
	Profile.Celebrate(player, info.Name .. " unlocked!", info.Desc, info.Icon)
	Profile.Feed(player.DisplayName .. " got " .. info.Name .. "!", GOLD)
	Profile.RefreshTag(player)
	Profile.Push(player)
end

function Profile.ClearPlayer(player)
	passes[player] = nil
	activity[player] = nil
	lastOffer[player] = nil
	offered[player] = nil
	pushQueued[player] = nil
end

-- Robux prompts (only for items that have an Id set) ---------------------------------------------
function Profile.PromptProduct(player, key)
	local info = Config.Products[key]
	if not info or info.Id == 0 then
		toast(player, "This item isn't for sale yet.")
		return
	end
	MarketplaceService:PromptProductPurchase(player, info.Id)
end

function Profile.PromptPass(player, key)
	local info = Config.GamePasses[key]
	if not info or info.Id == 0 then
		toast(player, "This pass isn't for sale yet.")
		return
	end
	if Profile.HasPass(player, key) then
		toast(player, "You already own " .. info.Name .. "!")
		return
	end
	MarketplaceService:PromptGamePassPurchase(player, info.Id)
end

-- An honest, dismissable suggestion. Shown at most once per item per visit, never mid-fight.
function Profile.Offer(player, kind, key, text)
	local info = kind == "Pass" and Config.GamePasses[key] or Config.Products[key]
	if not info or info.Id == 0 then
		return
	end
	if kind == "Pass" and Profile.HasPass(player, key) then
		return
	end
	offered[player] = offered[player] or {}
	if offered[player][key] then
		return
	end
	if lastOffer[player] and os.clock() - lastOffer[player] < 240 then
		return
	end
	offered[player][key] = true
	lastOffer[player] = os.clock()
	Remotes.Notify:FireClient(player, { Type = "Offer", Kind = kind, Key = key, Text = text })
end

-- Coins and multipliers ----------------------------------------------------------------------------
function Profile.AddCoins(player, amount)
	local data = DataService.Get(player)
	if not data or amount == 0 then
		return
	end
	data.Coins = math.max(0, data.Coins + math.floor(amount))
	Profile.Push(player)
end

function Profile.Spend(player, amount)
	local data = DataService.Get(player)
	if not data or data.Coins < amount then
		return false
	end
	data.Coins -= amount
	Profile.Push(player)
	return true
end

function Profile.CoinMult(player)
	return Profile.HasPass(player, "VIP") and Config.Rewards.VIPCoins or 1
end

function Profile.XPMult(player)
	local mult = 1
	if Profile.HasPass(player, "VIP") then
		mult *= Config.Rewards.VIPXP
	end
	if Profile.HasPass(player, "StarBoost") then
		mult *= Config.Rewards.BoostXP
	end
	return mult
end

-- Ownership -----------------------------------------------------------------------------------------
function Profile.OwnsPart(player, key)
	local data = DataService.Get(player)
	return data ~= nil and DataService.Owns(data, key)
end

function Profile.OwnsPaint(player, key)
	local data = DataService.Get(player)
	local paint = Config.Paints[key]
	if not data or not paint then
		return false
	end
	if key == "Default" or data.Paints[key] then
		return true
	end
	return paint.Pass ~= nil and Profile.HasPass(player, paint.Pass)
end

-- Gives a part. If already owned, pays its coin value instead so a reward is never wasted.
function Profile.GrantPart(player, key, quiet)
	local data = DataService.Get(player)
	local part = Config.Parts[key]
	if not data or not part then
		return
	end
	if DataService.Owns(data, key) then
		local refund = part.Price or 500
		data.Coins += refund
		if not quiet then
			toast(player, "You already had " .. part.Name .. ", so you got " .. Format.Number(refund) .. " coins instead!")
		end
	else
		data.Parts[key] = true
		if not quiet then
			Profile.Celebrate(player, "NEW PART!", part.Icon .. " " .. part.Name .. "\n" .. part.Desc, part.Icon)
			Profile.Feed(player.DisplayName .. " unlocked " .. part.Name .. "!", Config.Rarities[part.Rarity])
		end
	end
	Profile.Push(player)
end

function Profile.GrantPaint(player, key, quiet)
	local data = DataService.Get(player)
	local paint = Config.Paints[key]
	if not data or not paint then
		return
	end
	data.Paints[key] = true
	if not quiet then
		Profile.Celebrate(player, "NEW PAINT!", paint.Name .. " paint. Equip it in the Build menu.", "🎨")
	end
	Profile.Push(player)
end

function Profile.GrantTitle(player, title)
	local data = DataService.Get(player)
	if not data then
		return
	end
	data.Titles[title] = true
	toast(player, "New title: " .. title .. "!", GOLD)
	Profile.Push(player)
end

-- Character dressing + name tag ---------------------------------------------------------------------
function Profile.RefreshTag(player)
	local data = DataService.Get(player)
	local character = player.Character
	if not data or not character then
		return
	end
	local rank = Config.RankFor(data.Trophies)
	local vip = Profile.HasPass(player, "VIP")
	local streak = data.WinStreak >= 3 and ("  🔥" .. data.WinStreak) or ""
	Visuals.Tag(character, (vip and "👑 " or "") .. player.DisplayName, rank.Icon .. " " .. rank.Name .. " · " .. data.Title .. streak, vip and GOLD or Color3.new(1, 1, 1), rank.Color)
	Visuals.SetDamageTag(character, character:GetAttribute("Damage") or 0, activity[player] ~= nil)
	local stats = player:FindFirstChild("leaderstats")
	if stats then
		stats.Trophies.Value = data.Trophies
		stats.Wins.Value = data.Wins
	end
end

-- Hook set by Main: re-applies combat stats after an equip.
Profile.OnLoadoutChanged = nil

function Profile.DressCharacter(player)
	local data = DataService.Get(player)
	local character = player.Character
	if not data or not character then
		return
	end
	Visuals.Dress(character, data.Loadout, data.Paint)
	if Profile.OnLoadoutChanged then
		Profile.OnLoadoutChanged(player)
	end
end

function Profile.Equip(player, slot, key)
	local data = DataService.Get(player)
	local part = Config.Parts[key]
	if not data or not part or part.Slot ~= slot then
		return false
	end
	if not DataService.Owns(data, key) then
		toast(player, part.Name .. " is locked. Get it from: " .. part.Source)
		return false
	end
	if activity[player] then
		toast(player, "You can change parts back in the lobby.")
		return false
	end
	data.Loadout[slot] = key
	Profile.DressCharacter(player)
	toast(player, "Equipped " .. part.Name .. "!")
	Profile.Push(player)
	return true
end

function Profile.BuyPart(player, key)
	local data = DataService.Get(player)
	local part = Config.Parts[key]
	if not data or not part then
		return false
	end
	if DataService.Owns(data, key) then
		return Profile.Equip(player, part.Slot, key)
	end
	if not part.Price then
		toast(player, part.Name .. " can't be bought. Get it from: " .. part.Source)
		return false
	end
	if not Profile.Spend(player, part.Price) then
		toast(player, "You need " .. Format.Number(part.Price - data.Coins) .. " more coins. Win matches to earn more!")
		Profile.Offer(player, "Product", "CoinsS", "Short on coins? A Pile of Coins gives 600.")
		return false
	end
	Profile.GrantPart(player, key)
	if not activity[player] then
		data.Loadout[part.Slot] = key
		Profile.DressCharacter(player)
	end
	Profile.Push(player)
	return true
end

function Profile.BuyPaint(player, key)
	local data = DataService.Get(player)
	local paint = Config.Paints[key]
	if not data or not paint then
		return false
	end
	if Profile.OwnsPaint(player, key) then
		return Profile.SetPaint(player, key)
	end
	if paint.Product then
		Profile.PromptProduct(player, paint.Product)
		return false
	end
	if paint.Pass then
		Profile.PromptPass(player, paint.Pass)
		return false
	end
	if not paint.Price then
		toast(player, paint.Name .. " comes from: " .. paint.Source)
		return false
	end
	if not Profile.Spend(player, paint.Price) then
		toast(player, "You need " .. Format.Number(paint.Price - data.Coins) .. " more coins.")
		return false
	end
	data.Paints[key] = true
	Profile.SetPaint(player, key)
	return true
end

function Profile.SetPaint(player, key)
	local data = DataService.Get(player)
	if not data or not Profile.OwnsPaint(player, key) then
		return false
	end
	data.Paint = key
	Profile.DressCharacter(player)
	Profile.Push(player)
	return true
end

function Profile.SetTitle(player, title)
	local data = DataService.Get(player)
	if not data or type(title) ~= "string" then
		return false
	end
	if title ~= "Rookie" and not data.Titles[title] then
		return false
	end
	data.Title = title
	Profile.RefreshTag(player)
	Profile.Push(player)
	return true
end

-- Star Road -------------------------------------------------------------------------------------------
local function grantStarReward(player, tier)
	local reward = Config.StarRoad[tier]
	local data = DataService.Get(player)
	if reward.Coins then
		data.Coins += reward.Coins
	end
	if reward.Part then
		Profile.GrantPart(player, reward.Part)
	end
	if reward.Paint then
		Profile.GrantPaint(player, reward.Paint)
	end
	if reward.Title then
		Profile.GrantTitle(player, reward.Title)
	end
	if reward.Revive then
		data.Revives += reward.Revive
	end
end

function Profile.AddXP(player, amount)
	local data = DataService.Get(player)
	if not data or amount <= 0 then
		return 0
	end
	amount = math.floor(amount * Profile.XPMult(player))
	local total = #Config.StarRoad
	if data.StarTier >= total then
		data.StarOverflow += amount
		while data.StarOverflow >= Config.StarOverflowXP do
			data.StarOverflow -= Config.StarOverflowXP
			data.Coins += Config.StarOverflowCoins
			toast(player, "Star Road bonus: +" .. Config.StarOverflowCoins .. " coins!", GOLD)
		end
		Profile.Push(player)
		return amount
	end
	data.StarXP += amount
	while data.StarTier < total and data.StarXP >= Config.StarXPFor(data.StarTier + 1) do
		data.StarXP -= Config.StarXPFor(data.StarTier + 1)
		data.StarTier += 1
		grantStarReward(player, data.StarTier)
		Remotes.Notify:FireClient(player, { Type = "StarTier", Tier = data.StarTier })
		if data.StarTier == 3 then
			Profile.Offer(player, "Pass", "StarBoost", "Liking the Star Road? Star Boost doubles your Star XP forever.")
		end
	end
	if data.StarTier >= total then
		data.StarXP = 0
	end
	Profile.Push(player)
	return amount
end

-- Daily login streak -------------------------------------------------------------------------------------
local function dayNumber(t)
	return math.floor(t / DAY)
end

function Profile.CanClaimDaily(data)
	return dayNumber(os.time()) > dayNumber(data.LastDaily)
end

function Profile.ClaimDaily(player)
	local data = DataService.Get(player)
	if not data or not Profile.CanClaimDaily(data) then
		return false
	end
	local today = dayNumber(os.time())
	if today - dayNumber(data.LastDaily) == 1 then
		data.DailyStreak += 1
	else
		data.DailyStreak = 1 -- missed a day (or first time): back to day 1
	end
	data.LastDaily = os.time()
	local index = (data.DailyStreak - 1) % #Config.Daily + 1
	local reward = Config.Daily[index]
	local coins = math.floor(reward.Coins * Profile.CoinMult(player))
	data.Coins += coins
	if reward.XP then
		Profile.AddXP(player, reward.XP)
	end
	Profile.Celebrate(player, "DAY " .. data.DailyStreak .. " STREAK!", "+" .. Format.Number(coins) .. " coins" .. (reward.XP and (" and +" .. reward.XP .. " Star XP") or "") .. "\nCome back tomorrow for day " .. (data.DailyStreak + 1) .. "!", "📅")
	Profile.Push(player)
	return true
end

-- Daily quests ------------------------------------------------------------------------------------------------
local function questDef(id)
	for _, q in Config.QuestPool do
		if q.Id == id then
			return q
		end
	end
	return nil
end

local function ensureQuests(player, data)
	local today = dayNumber(os.time())
	if data.Quests.Day == today and type(data.Quests.List) == "table" then
		return
	end
	local rng = Random.new(today * 7919 + player.UserId % 100000)
	local pool = table.clone(Config.QuestPool)
	local list = {}
	for _ = 1, Config.QuestsPerDay do
		local q = table.remove(pool, rng:NextInteger(1, #pool))
		table.insert(list, { Id = q.Id, Progress = 0, Claimed = false })
	end
	data.Quests = { Day = today, List = list }
end

function Profile.Quest(player, stat, amount)
	local data = DataService.Get(player)
	if not data then
		return
	end
	ensureQuests(player, data)
	local changed = false
	for _, q in data.Quests.List do
		local def = questDef(q.Id)
		if def and def.Stat == stat and not q.Claimed and q.Progress < def.Goal then
			q.Progress = math.min(def.Goal, q.Progress + amount)
			changed = true
			if q.Progress >= def.Goal then
				toast(player, "Quest done: " .. def.Text .. "! Claim it in Quests.", GOLD)
			end
		end
	end
	if changed then
		Profile.Push(player)
	end
end

function Profile.ClaimQuest(player, index)
	local data = DataService.Get(player)
	if not data or type(index) ~= "number" then
		return false
	end
	ensureQuests(player, data)
	local q = data.Quests.List[index]
	local def = q and questDef(q.Id)
	if not def or q.Claimed or q.Progress < def.Goal then
		return false
	end
	q.Claimed = true
	local coins = math.floor(def.Coins * Profile.CoinMult(player))
	data.Coins += coins
	Profile.AddXP(player, def.XP)
	toast(player, "+" .. coins .. " coins and Star XP!", GOLD)
	Profile.Push(player)
	return true
end

-- Match and story results --------------------------------------------------------------------------------
-- r = { Won, Placement, Players, KOs, Ranked, Bots }
function Profile.MatchResult(player, r)
	local data = DataService.Get(player)
	if not data then
		return nil
	end
	local R = Config.Rewards
	local coins, xp
	if r.Won then
		coins, xp = R.WinCoins, R.WinXP
	elseif r.Placement == 2 and r.Players > 2 then
		coins, xp = R.SecondCoins, R.SecondXP
	else
		coins, xp = R.LossCoins, R.LossXP
	end
	coins += R.KOCoins * r.KOs
	xp += R.KOXP * r.KOs
	if r.Bots then
		coins = math.floor(coins * R.BotScale)
		xp = math.floor(xp * R.BotScale)
	end

	local streakBonus = 0
	if r.Won then
		data.Wins += 1
		data.WinStreak += 1
		data.BestStreak = math.max(data.BestStreak, data.WinStreak)
		streakBonus = math.min((data.WinStreak - 1) * R.StreakStep, R.StreakMax)
	else
		data.Losses += 1
		data.WinStreak = 0
	end
	data.KOs += r.KOs
	coins = math.floor(coins * (1 + streakBonus) * Profile.CoinMult(player))
	data.Coins += coins

	local trophyDelta = 0
	local oldRank = Config.RankFor(data.Trophies)
	if r.Ranked then
		trophyDelta = r.Won and Config.TrophyWin or -math.min(Config.TrophyLoss, data.Trophies)
		if trophyDelta == 0 then
			trophyDelta = 0 -- turns -0 into 0 so the results never read "+-0"
		end
		data.Trophies += trophyDelta
	end
	local newRank = Config.RankFor(data.Trophies)
	local xpGained = Profile.AddXP(player, xp)

	Profile.Quest(player, "Play", 1)
	if r.Won then
		Profile.Quest(player, "Win", 1)
	end
	if r.KOs > 0 then
		Profile.Quest(player, "KO", r.KOs)
	end
	if newRank.Min > oldRank.Min then
		Profile.Celebrate(player, "RANK UP!", newRank.Icon .. " You reached " .. newRank.Name .. "!", newRank.Icon)
		Profile.Feed(player.DisplayName .. " ranked up to " .. newRank.Name .. "!", newRank.Color)
	end
	if data.WinStreak == 3 or data.WinStreak == 5 or data.WinStreak == 10 then
		Profile.Feed(player.DisplayName .. " is on a " .. data.WinStreak .. "-win streak! 🔥", Color3.fromRGB(255, 120, 40))
	end
	Profile.RefreshTag(player)
	Profile.Push(player)
	return {
		Coins = coins,
		XP = xpGained,
		Trophies = trophyDelta,
		Streak = data.WinStreak,
		StreakBonus = streakBonus,
		Rank = newRank.Name,
	}
end

function Profile.StoryResult(player, chapterIndex)
	local data = DataService.Get(player)
	local chapter = Config.Chapters[chapterIndex]
	if not data or not chapter then
		return nil
	end
	local first = chapterIndex > data.StoryCleared
	local coins = first and chapter.Coins or Config.StoryReplayCoins
	local xp = first and chapter.XP or Config.StoryReplayXP
	coins = math.floor(coins * Profile.CoinMult(player))
	data.Coins += coins
	if first then
		data.StoryCleared = chapterIndex
		Profile.GrantPart(player, chapter.Reward)
		if chapter.Title then
			Profile.GrantTitle(player, chapter.Title)
		end
		Profile.Feed(player.DisplayName .. " beat " .. chapter.Boss .. " in Story Chapter " .. chapterIndex .. "!", Color3.fromRGB(180, 120, 255))
	end
	local xpGained = Profile.AddXP(player, xp)
	Profile.Quest(player, "Story", 1)
	Profile.Push(player)
	return { Coins = coins, XP = xpGained, First = first, Part = first and chapter.Reward or nil }
end

-- State sync ------------------------------------------------------------------------------------------------
local function snapshot(player, data)
	ensureQuests(player, data)
	local quests = {}
	for _, q in data.Quests.List do
		local def = questDef(q.Id)
		if def then
			table.insert(quests, { Text = def.Text, Progress = q.Progress, Goal = def.Goal, Claimed = q.Claimed, Coins = def.Coins, XP = def.XP })
		end
	end
	local owned = {}
	for key in Config.Parts do
		if DataService.Owns(data, key) then
			owned[key] = true
		end
	end
	local paints = {}
	for key in Config.Paints do
		if Profile.OwnsPaint(player, key) then
			paints[key] = true
		end
	end
	local titles = { "Rookie" }
	for title in data.Titles do
		table.insert(titles, title)
	end
	local rank = Config.RankFor(data.Trophies)
	local nextTier = math.min(data.StarTier + 1, #Config.StarRoad)
	return {
		Coins = data.Coins,
		StarXP = data.StarXP,
		StarTier = data.StarTier,
		StarNeed = Config.StarXPFor(nextTier),
		Trophies = data.Trophies,
		Rank = rank.Name,
		Wins = data.Wins,
		Losses = data.Losses,
		KOs = data.KOs,
		WinStreak = data.WinStreak,
		BestStreak = data.BestStreak,
		DailyStreak = data.DailyStreak,
		CanClaimDaily = Profile.CanClaimDaily(data),
		-- The streak day you'd get by claiming now (back to 1 if a day was missed).
		DailyNext = Profile.CanClaimDaily(data) and (dayNumber(os.time()) - dayNumber(data.LastDaily) == 1 and data.DailyStreak + 1 or 1) or data.DailyStreak,
		Owned = owned,
		Loadout = data.Loadout,
		Paint = data.Paint,
		Paints = paints,
		Titles = titles,
		Title = data.Title,
		StoryCleared = data.StoryCleared,
		Revives = data.Revives,
		Quests = quests,
		StarterBought = data.StarterBought,
		VIP = Profile.HasPass(player, "VIP"),
		StarBoost = Profile.HasPass(player, "StarBoost"),
		SeenHelp = data.SeenHelp,
		SavingOff = player:GetAttribute("SavingOff") == true,
	}
end

-- Batches several changes in one frame into one network message.
function Profile.Push(player)
	if pushQueued[player] then
		return
	end
	pushQueued[player] = true
	task.defer(function()
		pushQueued[player] = nil
		local data = player.Parent and DataService.Get(player)
		if data then
			Remotes.State:FireClient(player, snapshot(player, data))
		end
	end)
end

function Profile.SetupPlayer(player)
	local stats = Instance.new("Folder")
	stats.Name = "leaderstats"
	local trophies = Instance.new("IntValue")
	trophies.Name = "Trophies"
	trophies.Parent = stats
	local wins = Instance.new("IntValue")
	wins.Name = "Wins"
	wins.Parent = stats
	stats.Parent = player
	local data = DataService.Get(player)
	if data then
		trophies.Value = data.Trophies
		wins.Value = data.Wins
	end
end

function Profile.MarkHelpSeen(player)
	local data = DataService.Get(player)
	if data then
		data.SeenHelp = true
	end
end

Players.PlayerRemoving:Connect(function(player)
	Profile.ClearPlayer(player)
end)

return Profile
