-- All game balance + monetization settings live here.
-- IMPORTANT: fill in the GamePasses / Products `Id` fields after creating them
-- on the Roblox Creator Dashboard (see README.md). Id = 0 means "not set up yet".

local Config = {}

Config.GameName = "Crystal Pets Simulator"

-- Core loop -------------------------------------------------------------
Config.CrystalValue = 5 -- base coins per crystal (before zone / multipliers)
Config.CrystalRespawn = 3 -- seconds
Config.MineRange = 20 -- studs; server validates this
Config.AutoCollectRange = 18
Config.AutoCollectPerTick = 3 -- crystals per second with the Auto Collect pass
Config.BaseSlots = 3
Config.ExtraSlotsBonus = 3
Config.HatchCooldown = 0.75

-- Multipliers -----------------------------------------------------------
Config.RebirthBonus = 0.5 -- +50% coins per rebirth (additive)
Config.VIPMultiplier = 1.25
Config.BoostMultiplier = 2 -- from the timed boost product
Config.LuckyBoost = { Rare = 1.5, Epic = 2, Legendary = 2.5, Mythic = 3 }

function Config.RebirthCost(rebirths)
	return math.floor(10000 * 3 ^ rebirths)
end

-- Daily rewards (multiplied by 1 + rebirths, doubled for VIP) -----------
Config.DailyRewards = { 500, 1000, 2500, 5000, 10000, 25000, 100000 }
Config.DailyCooldown = 20 * 3600
Config.DailyStreakWindow = 48 * 3600

-- Rarities --------------------------------------------------------------
Config.Rarities = {
	Common = { Color = Color3.fromRGB(190, 190, 190), Order = 1 },
	Uncommon = { Color = Color3.fromRGB(90, 220, 120), Order = 2 },
	Rare = { Color = Color3.fromRGB(70, 150, 255), Order = 3 },
	Epic = { Color = Color3.fromRGB(180, 90, 255), Order = 4 },
	Legendary = { Color = Color3.fromRGB(255, 165, 40), Order = 5 },
	Mythic = { Color = Color3.fromRGB(255, 70, 130), Order = 6 },
}

-- Pets: Mult is added to the coin multiplier while equipped ---------------
Config.Pets = {
	Slime = { Icon = "🟢", Rarity = "Common", Mult = 0.10 },
	Bunny = { Icon = "🐰", Rarity = "Common", Mult = 0.15 },
	Fox = { Icon = "🦊", Rarity = "Uncommon", Mult = 0.40 },
	Wolf = { Icon = "🐺", Rarity = "Rare", Mult = 1.0 },
	Owl = { Icon = "🦉", Rarity = "Rare", Mult = 1.2 },
	Unicorn = { Icon = "🦄", Rarity = "Epic", Mult = 3 },
	Dragon = { Icon = "🐉", Rarity = "Legendary", Mult = 10 },
	Phoenix = { Icon = "🔥", Rarity = "Mythic", Mult = 40 },
	Celestial = { Icon = "🌟", Rarity = "Mythic", Mult = 120 },
	FrostWyrm = { Icon = "❄️", Rarity = "Mythic", Mult = 25 }, -- limited-time (Winter Egg)
}

-- Zones: Center is world position; players unlock them with coins ---------
Config.Zones = {
	{
		Id = "Meadow", Name = "Sunny Meadow", Cost = 0, Mult = 1, CrystalCount = 40,
		Center = Vector3.new(0, 0, 0),
		FloorColor = Color3.fromRGB(88, 170, 90), Material = Enum.Material.Grass,
		CrystalColor = Color3.fromRGB(110, 230, 255),
	},
	{
		Id = "Cave", Name = "Crystal Cave", Cost = 2500, Mult = 4, CrystalCount = 55,
		Center = Vector3.new(160, 0, 0), Stand = Vector3.new(95, 0, 0),
		FloorColor = Color3.fromRGB(70, 80, 120), Material = Enum.Material.Slate,
		CrystalColor = Color3.fromRGB(190, 120, 255),
	},
	{
		Id = "Volcano", Name = "Magma Volcano", Cost = 60000, Mult = 20, CrystalCount = 55,
		Center = Vector3.new(-160, 0, 0), Stand = Vector3.new(-95, 0, 0),
		FloorColor = Color3.fromRGB(90, 40, 35), Material = Enum.Material.Basalt,
		CrystalColor = Color3.fromRGB(255, 120, 50),
	},
	{
		Id = "Sky", Name = "Cloud Kingdom", Cost = 1500000, Mult = 100, CrystalCount = 55,
		Center = Vector3.new(0, 0, 160), Stand = Vector3.new(0, 0, 95),
		FloorColor = Color3.fromRGB(235, 240, 255), Material = Enum.Material.SmoothPlastic,
		CrystalColor = Color3.fromRGB(255, 235, 120),
	},
}

-- Eggs: Pets = { {petName, weight}, ... } --------------------------------
Config.Eggs = {
	Meadow = {
		Name = "Meadow Egg", Cost = 250, Zone = "Meadow", Offset = Vector3.new(0, 0, -32),
		Color = Color3.fromRGB(120, 230, 140),
		Pets = { { "Slime", 55 }, { "Bunny", 30 }, { "Fox", 12 }, { "Wolf", 3 } },
	},
	Cave = {
		Name = "Cave Egg", Cost = 5000, Zone = "Cave", Offset = Vector3.new(0, 0, 0),
		Color = Color3.fromRGB(190, 120, 255),
		Pets = { { "Fox", 40 }, { "Wolf", 35 }, { "Owl", 18 }, { "Unicorn", 6.5 }, { "Dragon", 0.5 } },
	},
	Volcano = {
		Name = "Magma Egg", Cost = 120000, Zone = "Volcano", Offset = Vector3.new(0, 0, 0),
		Color = Color3.fromRGB(255, 110, 50),
		Pets = { { "Wolf", 40 }, { "Owl", 30 }, { "Unicorn", 20 }, { "Dragon", 9 }, { "Phoenix", 1 } },
	},
	-- Limited-time event egg: only hatchable inside its Event window (server time, UTC).
	-- Copy this entry for each seasonal event; it is the cheapest way to spike revenue and returns.
	Winter = {
		Name = "Winter Egg", Cost = 20000, Zone = "Meadow", Offset = Vector3.new(34, 0, -32),
		Color = Color3.fromRGB(150, 220, 255),
		Event = {
			Start = os.time({ year = 2026, month = 12, day = 1, hour = 0 }),
			End = os.time({ year = 2027, month = 1, day = 6, hour = 0 }),
		},
		Pets = { { "Fox", 30 }, { "Wolf", 35 }, { "Unicorn", 20 }, { "Dragon", 10 }, { "FrostWyrm", 5 } },
	},
	Sky = {
		Name = "Celestial Egg", Cost = 3000000, Zone = "Sky", Offset = Vector3.new(0, 0, 0),
		Color = Color3.fromRGB(255, 240, 150),
		Pets = { { "Unicorn", 45 }, { "Dragon", 40 }, { "Phoenix", 14 }, { "Celestial", 1 } },
	},
}

-- Monetization ----------------------------------------------------------
Config.PassOrder = { "DoubleCoins", "AutoCollect", "LuckyHatch", "ExtraSlots", "VIP" }
Config.GamePasses = {
	DoubleCoins = { Id = 0, Name = "2x Coins", Price = 299, Desc = "Permanently double every coin you earn." },
	AutoCollect = { Id = 0, Name = "Auto Collect", Price = 399, Desc = "Nearby crystals mine themselves." },
	LuckyHatch = { Id = 0, Name = "Lucky Hatch", Price = 249, Desc = "Much better odds for rare+ pets." },
	ExtraSlots = { Id = 0, Name = "+3 Pet Slots", Price = 199, Desc = "Equip three more pets at once." },
	VIP = { Id = 0, Name = "VIP", Price = 499, Desc = "x1.25 coins and double daily rewards." },
}

Config.ProductOrder = { "CoinsSmall", "CoinsMedium", "CoinsLarge", "Boost" }
Config.Products = {
	-- Coins granted = Coins * (1 + rebirths), so packs stay relevant late-game.
	CoinsSmall = { Id = 0, Name = "Coin Pack", Price = 49, Coins = 5000 },
	CoinsMedium = { Id = 0, Name = "Coin Bag", Price = 199, Coins = 50000 },
	CoinsLarge = { Id = 0, Name = "Coin Chest", Price = 799, Coins = 500000 },
	Boost = { Id = 0, Name = "2x Boost (15 min)", Price = 79, BoostSeconds = 900 },
}

-- Shiny variants: every pet gets a "Shiny <name>" that can only come from hatching ------
-- (rare chance on any egg; the Lucky Hatch pass raises it). 2.5x the pet's multiplier.
Config.ShinyChance = 0.02
Config.LuckyShinyChance = 0.05
Config.ShinyMultiplier = 2.5

local shinies = {}
for name, info in Config.Pets do
	shinies["Shiny " .. name] = {
		Icon = "✨" .. info.Icon,
		Rarity = info.Rarity,
		Mult = info.Mult * Config.ShinyMultiplier,
		Shiny = true,
	}
end
for name, info in shinies do
	Config.Pets[name] = info
end

-- Lookups ---------------------------------------------------------------
Config.ZoneById = {}
for _, zone in Config.Zones do
	Config.ZoneById[zone.Id] = zone
end

return Config
