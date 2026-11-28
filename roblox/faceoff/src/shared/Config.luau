-- Every number, part, chapter and product in Mix & Smash lives here.
local Config = {}

Config.GameName = "Mix & Smash"
Config.StartCoins = 150
Config.Gravity = 110

-- Fight rules -------------------------------------------------------------------------
Config.Fight = {
	Stocks = 3, -- lives per match
	MatchSeconds = 180,
	CountdownSeconds = 3,
	RespawnDelay = 1.6,
	RespawnInvuln = 2.2,
	MaxDamage = 999,
	DodgeTime = 0.35, -- invulnerable for this long
	DodgeCooldown = 1.0,
	DodgeSpeed = 65,
	BotFillSeconds = 12, -- alone in a queue this long? a bot joins so nobody waits
	FFAWaitSeconds = 10, -- FFA starts this long after the 2nd player joins (or right away at 4)
	FFAMax = 4,
	BlastSide = 60, -- blast walls this far past the stage edge
	BlastBottom = 55,
	BlastTop = 105,
	HitstunBase = 0.12,
	HitstunPerSpeed = 0.0042,
	HitstunMax = 1.1,
	KOCreditSeconds = 6, -- a ring-out counts as your KO if you hit them this recently
}

-- The jab everyone has (click). Knockback speed = Base + Growth x the target's damage %.
Config.Light = {
	Name = "Jab",
	Type = "Melee",
	Damage = 5,
	Base = 12,
	Growth = 0.3,
	Angle = 40,
	Range = 4.5,
	Radius = 3.6,
	Windup = 0.06,
	Cooldown = 0.32,
	Color = Color3.fromRGB(255, 255, 255),
}

Config.Rarities = {
	Common = Color3.fromRGB(190, 200, 210),
	Rare = Color3.fromRGB(70, 160, 255),
	Epic = Color3.fromRGB(180, 90, 255),
	Legendary = Color3.fromRGB(255, 190, 40),
}

Config.Slots = { "Head", "Arms", "Legs" }
Config.SlotInfo = {
	Head = { Title = "HEAD", Role = "Special move (Q)", Icon = "🧠" },
	Arms = { Title = "ARMS", Role = "Heavy attack (E)", Icon = "💪" },
	Legs = { Title = "LEGS", Role = "Movement and weight", Icon = "🦿" },
}
Config.StartParts = { Head = "Bolt", Arms = "Gloves", Legs = "Sneakers" }

local function c(r, g, b)
	return Color3.fromRGB(r, g, b)
end
local R90 = math.rad(90)

-- Parts -----------------------------------------------------------------------------------
-- Look pieces attach to a body part (Head / Hand / Foot). Arms and legs are mirrored to both sides.
-- Price = coins at the Part Forge (nil = can't be bought, earn it from Source).
Config.Parts = {
	-- HEADS (special move)
	Bolt = {
		Slot = "Head",
		Name = "Bolt Head",
		Icon = "⚡",
		Rarity = "Common",
		Source = "Starter part",
		Desc = "Zap Burst: shocks everyone around you.",
		Move = { Name = "Zap Burst", Type = "Burst", Damage = 10, Base = 32, Growth = 0.5, Angle = 55, Radius = 8, Windup = 0.22, Cooldown = 2.2, Color = c(255, 230, 60) },
		Look = {
			{ Shape = "Block", Size = Vector3.new(1.5, 0.45, 1.5), Offset = CFrame.new(0, 0.75, 0), Color = c(255, 205, 40), Material = "Metal" },
			{ Shape = "Ball", Size = Vector3.new(0.55, 0.55, 0.55), Offset = CFrame.new(0, 1.35, 0), Color = c(255, 240, 90), Material = "Neon", Keep = true },
		},
	},
	Blaster = {
		Slot = "Head",
		Name = "Blaster Head",
		Icon = "🔴",
		Rarity = "Rare",
		Price = 500,
		Source = "Part Forge",
		Desc = "Laser: a fast shot straight ahead.",
		Move = { Name = "Laser", Type = "Projectile", Damage = 7, Base = 18, Growth = 0.28, Angle = 20, Speed = 110, Radius = 2, Life = 0.9, Windup = 0.08, Cooldown = 0.9, Color = c(255, 50, 60) },
		Look = {
			{ Shape = "Block", Size = Vector3.new(1.4, 0.4, 0.3), Offset = CFrame.new(0, 0.15, -0.65), Color = c(255, 40, 50), Material = "Neon", Keep = true },
			{ Shape = "Cylinder", Size = Vector3.new(1.1, 0.45, 0.45), Offset = CFrame.new(0.8, 0.35, -0.2) * CFrame.Angles(0, R90, 0), Color = c(70, 75, 90), Material = "Metal" },
		},
	},
	Magnet = {
		Slot = "Head",
		Name = "Magnet Head",
		Icon = "🧲",
		Rarity = "Epic",
		Price = 1200,
		Source = "Part Forge or Star Road tier 10",
		Desc = "Pull: yanks nearby enemies toward you. Follow up with a heavy!",
		Move = { Name = "Magnet Pull", Type = "Pull", Damage = 5, Radius = 20, Pull = 48, Windup = 0.2, Cooldown = 3, Color = c(255, 60, 60) },
		Look = {
			{ Shape = "Block", Size = Vector3.new(0.45, 1.0, 0.45), Offset = CFrame.new(-0.5, 1.05, 0), Color = c(230, 40, 40), Material = "SmoothPlastic" },
			{ Shape = "Block", Size = Vector3.new(0.45, 1.0, 0.45), Offset = CFrame.new(0.5, 1.05, 0), Color = c(230, 40, 40), Material = "SmoothPlastic" },
			{ Shape = "Block", Size = Vector3.new(1.45, 0.4, 0.45), Offset = CFrame.new(0, 0.7, 0), Color = c(200, 200, 210), Material = "Metal" },
		},
	},
	Frost = {
		Slot = "Head",
		Name = "Frost Head",
		Icon = "❄️",
		Rarity = "Epic",
		Source = "Story Chapter 2 boss",
		Desc = "Freeze Ray: a shot that freezes the target for a second.",
		Move = { Name = "Freeze Ray", Type = "Projectile", Damage = 6, Base = 12, Growth = 0.15, Angle = 15, Speed = 70, Radius = 2.4, Life = 1.1, Freeze = 1.0, Windup = 0.12, Cooldown = 2.4, Color = c(120, 230, 255) },
		Look = {
			{ Shape = "Block", Size = Vector3.new(0.35, 0.9, 0.35), Offset = CFrame.new(0, 1.05, 0), Color = c(150, 235, 255), Material = "Neon", Keep = true },
			{ Shape = "Block", Size = Vector3.new(0.3, 0.7, 0.3), Offset = CFrame.new(-0.45, 0.95, 0) * CFrame.Angles(0, 0, math.rad(20)), Color = c(150, 235, 255), Material = "Neon", Keep = true },
			{ Shape = "Block", Size = Vector3.new(0.3, 0.7, 0.3), Offset = CFrame.new(0.45, 0.95, 0) * CFrame.Angles(0, 0, math.rad(-20)), Color = c(150, 235, 255), Material = "Neon", Keep = true },
			{ Shape = "Block", Size = Vector3.new(1.4, 0.3, 1.4), Offset = CFrame.new(0, 0.65, 0), Color = c(200, 240, 255), Material = "Glass" },
		},
	},
	Dragon = {
		Slot = "Head",
		Name = "Dragon Head",
		Icon = "🐲",
		Rarity = "Epic",
		Price = 2500,
		Source = "Part Forge",
		Desc = "Fireball: a slow, heavy blast that launches far.",
		Move = { Name = "Fireball", Type = "Projectile", Damage = 13, Base = 34, Growth = 0.62, Angle = 35, Speed = 55, Radius = 3, Life = 1.4, Windup = 0.25, Cooldown = 2.6, Color = c(255, 110, 20) },
		Look = {
			{ Shape = "Block", Size = Vector3.new(1.0, 0.6, 0.9), Offset = CFrame.new(0, -0.1, -0.9), Color = c(210, 40, 30), Material = "SmoothPlastic" },
			{ Shape = "Block", Size = Vector3.new(0.25, 0.8, 0.25), Offset = CFrame.new(-0.45, 0.85, 0.2) * CFrame.Angles(math.rad(-25), 0, 0), Color = c(255, 210, 120), Material = "SmoothPlastic" },
			{ Shape = "Block", Size = Vector3.new(0.25, 0.8, 0.25), Offset = CFrame.new(0.45, 0.85, 0.2) * CFrame.Angles(math.rad(-25), 0, 0), Color = c(255, 210, 120), Material = "SmoothPlastic" },
			{ Shape = "Ball", Size = Vector3.new(0.3, 0.3, 0.3), Offset = CFrame.new(0.3, 0.25, -0.62), Color = c(255, 220, 40), Material = "Neon", Keep = true },
		},
	},
	Thunder = {
		Slot = "Head",
		Name = "Thunder King Head",
		Icon = "🌩️",
		Rarity = "Legendary",
		Source = "Story Chapter 5 boss",
		Desc = "Thunder Strike: lightning drops on the nearest enemy.",
		Move = { Name = "Thunder Strike", Type = "Strike", Damage = 15, Base = 36, Growth = 0.6, Angle = 75, Range = 48, Radius = 5.5, Windup = 0.15, Delay = 0.55, Cooldown = 3.2, Color = c(255, 250, 120) },
		Look = {
			{ Shape = "Block", Size = Vector3.new(1.5, 0.35, 1.5), Offset = CFrame.new(0, 0.7, 0), Color = c(255, 200, 40), Material = "Foil" },
			{ Shape = "Block", Size = Vector3.new(0.3, 0.6, 0.3), Offset = CFrame.new(-0.55, 1.1, 0), Color = c(255, 200, 40), Material = "Foil" },
			{ Shape = "Block", Size = Vector3.new(0.3, 0.8, 0.3), Offset = CFrame.new(0, 1.2, 0), Color = c(255, 200, 40), Material = "Foil" },
			{ Shape = "Block", Size = Vector3.new(0.3, 0.6, 0.3), Offset = CFrame.new(0.55, 1.1, 0), Color = c(255, 200, 40), Material = "Foil" },
			{ Shape = "Ball", Size = Vector3.new(0.4, 0.4, 0.4), Offset = CFrame.new(0, 1.7, 0), Color = c(255, 255, 140), Material = "Neon", Keep = true },
		},
	},

	-- ARMS (heavy attack)
	Gloves = {
		Slot = "Arms",
		Name = "Boxing Gloves",
		Icon = "🥊",
		Rarity = "Common",
		Source = "Starter part",
		Desc = "Big Punch: a strong hit straight ahead.",
		Move = { Name = "Big Punch", Type = "Melee", Damage = 13, Base = 38, Growth = 0.85, Angle = 35, Range = 5, Radius = 4, Windup = 0.28, Cooldown = 1.1, Color = c(255, 70, 70) },
		Look = {
			{ Shape = "Ball", Size = Vector3.new(1.3, 1.3, 1.3), Offset = CFrame.new(0, -0.25, 0), Color = c(230, 40, 40), Material = "SmoothPlastic" },
		},
	},
	Spring = {
		Slot = "Arms",
		Name = "Spring Arms",
		Icon = "🌀",
		Rarity = "Rare",
		Price = 500,
		Source = "Part Forge",
		Desc = "Boing Punch: hits from really far away.",
		Move = { Name = "Boing Punch", Type = "Melee", Damage = 11, Base = 30, Growth = 0.72, Angle = 30, Range = 10, Radius = 3.6, Windup = 0.3, Cooldown = 1.1, Color = c(90, 255, 120) },
		Look = {
			{ Shape = "Cylinder", Size = Vector3.new(1.2, 0.5, 0.5), Offset = CFrame.new(0, -0.45, 0) * CFrame.Angles(0, 0, R90), Color = c(170, 170, 180), Material = "Metal" },
			{ Shape = "Ball", Size = Vector3.new(0.95, 0.95, 0.95), Offset = CFrame.new(0, -1.15, 0), Color = c(60, 220, 100), Material = "SmoothPlastic" },
		},
	},
	Drill = {
		Slot = "Arms",
		Name = "Drill Arms",
		Icon = "🔩",
		Rarity = "Epic",
		Price = 1200,
		Source = "Part Forge",
		Desc = "Drill Rush: three fast hits, then a launch.",
		Move = { Name = "Drill Rush", Type = "Multi", Damage = 4, Hits = 3, Interval = 0.12, Base = 30, Growth = 0.7, Angle = 40, Range = 5, Radius = 4, Windup = 0.15, Cooldown = 1.4, Color = c(255, 160, 40) },
		Look = {
			{ Shape = "Cylinder", Size = Vector3.new(1.6, 0.75, 0.75), Offset = CFrame.new(0, -0.7, 0) * CFrame.Angles(0, 0, R90), Color = c(255, 150, 30), Material = "Metal" },
			{ Shape = "Ball", Size = Vector3.new(0.4, 0.4, 0.4), Offset = CFrame.new(0, -1.55, 0), Color = c(255, 230, 120), Material = "Neon", Keep = true },
		},
	},
	Hammer = {
		Slot = "Arms",
		Name = "Hammer Arms",
		Icon = "🔨",
		Rarity = "Epic",
		Source = "Story Chapter 1 boss",
		Desc = "Ground Pound: slow, wide and launches enemies up high.",
		Move = { Name = "Ground Pound", Type = "Melee", Damage = 16, Base = 40, Growth = 0.95, Angle = 70, Range = 4, Radius = 6.5, Windup = 0.42, Cooldown = 1.6, Color = c(150, 150, 170) },
		Look = {
			{ Shape = "Block", Size = Vector3.new(1.5, 0.95, 0.95), Offset = CFrame.new(0, -0.75, 0), Color = c(80, 80, 95), Material = "Metal" },
			{ Shape = "Block", Size = Vector3.new(0.35, 0.6, 0.35), Offset = CFrame.new(0, -0.1, 0), Color = c(150, 95, 50), Material = "Wood" },
		},
	},
	Claw = {
		Slot = "Arms",
		Name = "Crab Claws",
		Icon = "🦀",
		Rarity = "Epic",
		Price = 2000,
		Source = "Part Forge or Star Road tier 20",
		Desc = "Grab and Toss: grab the enemy and throw them behind you.",
		Move = { Name = "Grab and Toss", Type = "Throw", Damage = 10, Base = 44, Growth = 0.9, Angle = 40, Range = 4, Radius = 3.4, Windup = 0.2, Cooldown = 1.5, Color = c(255, 100, 60) },
		Look = {
			{ Shape = "Block", Size = Vector3.new(0.3, 1.0, 0.7), Offset = CFrame.new(-0.28, -0.6, 0) * CFrame.Angles(0, 0, math.rad(18)), Color = c(240, 90, 50), Material = "SmoothPlastic" },
			{ Shape = "Block", Size = Vector3.new(0.3, 1.0, 0.7), Offset = CFrame.new(0.28, -0.6, 0) * CFrame.Angles(0, 0, math.rad(-18)), Color = c(240, 90, 50), Material = "SmoothPlastic" },
		},
	},
	Rocket = {
		Slot = "Arms",
		Name = "Rocket Fists",
		Icon = "🚀",
		Rarity = "Legendary",
		Source = "Star Road tier 30",
		Desc = "Rocket Fist: your fist flies across the whole stage.",
		Move = { Name = "Rocket Fist", Type = "Projectile", Damage = 14, Base = 36, Growth = 0.8, Angle = 30, Speed = 85, Radius = 2.6, Life = 1.0, Windup = 0.22, Cooldown = 1.6, Color = c(255, 120, 40) },
		Look = {
			{ Shape = "Cylinder", Size = Vector3.new(1.3, 0.85, 0.85), Offset = CFrame.new(0, -0.4, 0) * CFrame.Angles(0, 0, R90), Color = c(210, 215, 225), Material = "Metal" },
			{ Shape = "Ball", Size = Vector3.new(0.6, 0.6, 0.6), Offset = CFrame.new(0, 0.35, 0), Color = c(255, 130, 30), Material = "Neon", Keep = true },
		},
	},

	-- LEGS (movement). Weight multiplies knockback taken (below 1 = heavier, harder to launch).
	Sneakers = {
		Slot = "Legs",
		Name = "Sneakers",
		Icon = "👟",
		Rarity = "Common",
		Source = "Starter part",
		Desc = "All-rounder: double jump, normal speed.",
		Stats = { Speed = 22, JumpPower = 52, AirJumps = 1, Weight = 1.0 },
		Look = {
			{ Shape = "Block", Size = Vector3.new(0.85, 0.4, 1.25), Offset = CFrame.new(0, -0.1, -0.1), Color = c(245, 245, 250), Material = "SmoothPlastic" },
			{ Shape = "Block", Size = Vector3.new(0.9, 0.12, 1.3), Offset = CFrame.new(0, -0.05, -0.1), Color = c(60, 140, 255), Material = "Neon", Keep = true },
		},
	},
	Wheels = {
		Slot = "Legs",
		Name = "Turbo Wheels",
		Icon = "🛞",
		Rarity = "Rare",
		Price = 500,
		Source = "Part Forge",
		Desc = "Fastest on the ground, quicker dodge, but a bit lighter.",
		Stats = { Speed = 30, JumpPower = 48, AirJumps = 1, Weight = 1.1, DodgeCooldown = 0.7 },
		Look = {
			{ Shape = "Cylinder", Size = Vector3.new(0.55, 1.1, 1.1), Offset = CFrame.new(0, -0.25, 0), Color = c(30, 30, 35), Material = "SmoothPlastic" },
			{ Shape = "Cylinder", Size = Vector3.new(0.6, 0.5, 0.5), Offset = CFrame.new(0, -0.25, 0), Color = c(255, 220, 50), Material = "Neon", Keep = true },
		},
	},
	SpringLegs = {
		Slot = "Legs",
		Name = "Pogo Legs",
		Icon = "🦘",
		Rarity = "Rare",
		Price = 900,
		Source = "Part Forge or Star Road tier 5",
		Desc = "Triple jump and the highest jumps. Great for recovering.",
		Stats = { Speed = 21, JumpPower = 62, AirJumps = 2, Weight = 1.05 },
		Look = {
			{ Shape = "Cylinder", Size = Vector3.new(0.8, 0.4, 0.4), Offset = CFrame.new(0, -0.45, 0) * CFrame.Angles(0, 0, R90), Color = c(180, 180, 190), Material = "Metal" },
			{ Shape = "Block", Size = Vector3.new(0.9, 0.2, 1.1), Offset = CFrame.new(0, -0.85, 0), Color = c(60, 220, 100), Material = "SmoothPlastic" },
		},
	},
	Treads = {
		Slot = "Legs",
		Name = "Tank Treads",
		Icon = "🛡️",
		Rarity = "Epic",
		Price = 1500,
		Source = "Part Forge",
		Desc = "Heavy: you get launched 25% less, but you're slower.",
		Stats = { Speed = 18, JumpPower = 48, AirJumps = 1, Weight = 0.75 },
		Look = {
			{ Shape = "Block", Size = Vector3.new(1.05, 0.65, 1.7), Offset = CFrame.new(0, -0.15, -0.1), Color = c(60, 90, 50), Material = "DiamondPlate" },
		},
	},
	RocketBoots = {
		Slot = "Legs",
		Name = "Rocket Boots",
		Icon = "🔥",
		Rarity = "Epic",
		Source = "Story Chapter 3 boss",
		Desc = "Air jumps become rocket dashes in the direction you hold.",
		Stats = { Speed = 23, JumpPower = 52, AirJumps = 2, Weight = 1.0, AirDash = true },
		Look = {
			{ Shape = "Block", Size = Vector3.new(0.85, 0.6, 1.15), Offset = CFrame.new(0, -0.05, -0.05), Color = c(200, 205, 215), Material = "Metal" },
			{ Shape = "Ball", Size = Vector3.new(0.55, 0.55, 0.55), Offset = CFrame.new(0, -0.05, 0.65), Color = c(255, 130, 20), Material = "Neon", Keep = true },
		},
	},
	Cloud = {
		Slot = "Legs",
		Name = "Cloud Legs",
		Icon = "☁️",
		Rarity = "Legendary",
		Source = "Story Chapter 4 boss",
		Desc = "Hold jump to float down slowly, plus 3 air jumps.",
		Stats = { Speed = 21, JumpPower = 50, AirJumps = 3, Weight = 1.12, Glide = true },
		Look = {
			{ Shape = "Ball", Size = Vector3.new(1.4, 1.0, 1.4), Offset = CFrame.new(0, -0.3, 0), Color = c(250, 250, 255), Material = "SmoothPlastic" },
			{ Shape = "Ball", Size = Vector3.new(0.9, 0.7, 0.9), Offset = CFrame.new(0.3, -0.45, 0.4), Color = c(225, 235, 255), Material = "SmoothPlastic" },
		},
	},
}

-- Display order in menus and on the Forge pedestals.
Config.PartOrder = {
	Head = { "Bolt", "Blaster", "Magnet", "Frost", "Dragon", "Thunder" },
	Arms = { "Gloves", "Spring", "Drill", "Hammer", "Claw", "Rocket" },
	Legs = { "Sneakers", "Wheels", "SpringLegs", "Treads", "RocketBoots", "Cloud" },
}
Config.TotalParts = 18

-- Paints (cosmetic only: they recolor your parts) -----------------------------------------
Config.Paints = {
	Default = { Name = "Factory", Order = 1, Source = "Free" },
	Chrome = { Name = "Chrome", Order = 2, Color = c(215, 220, 230), Material = "Metal", Price = 400, Source = "Part Forge (Star Road tier 4)" },
	Lava = { Name = "Lava", Order = 3, Color = c(255, 90, 20), Material = "Neon", Price = 800, Source = "Part Forge (Star Road tier 12)" },
	Toxic = { Name = "Toxic", Order = 4, Color = c(120, 255, 60), Material = "Neon", Price = 1200, Source = "Part Forge (Star Road tier 15)" },
	Ocean = { Name = "Ocean", Order = 5, Color = c(40, 140, 255), Material = "Glass", Source = "Star Road tier 22" },
	Shadow = { Name = "Shadow", Order = 6, Color = c(35, 28, 50), Material = "Slate", Source = "Star Road tier 27" },
	Gold = { Name = "24K Gold", Order = 7, Color = c(255, 200, 60), Material = "Foil", Product = "PaintGold", Source = "Robux" },
	Galaxy = { Name = "Galaxy", Order = 8, Color = c(130, 70, 255), Material = "Neon", Product = "PaintGalaxy", Source = "Robux" },
	Rainbow = { Name = "Rainbow", Order = 9, Color = c(255, 80, 160), Material = "Neon", Rainbow = true, Product = "PaintRainbow", Source = "Robux" },
	Royal = { Name = "Royal (VIP)", Order = 10, Color = c(150, 60, 255), Material = "Glass", Pass = "VIP", Source = "VIP pass" },
}

-- Star Road: a free 30-tier track. Star XP from matches, story and quests. No end date. -----
Config.StarRoad = {
	{ Coins = 100 },
	{ Title = "Mixer" },
	{ Coins = 150 },
	{ Paint = "Chrome" },
	{ Part = "SpringLegs" },
	{ Coins = 200 },
	{ Title = "Combo Kid" },
	{ Coins = 250 },
	{ Revive = 1 },
	{ Part = "Magnet" },
	{ Coins = 300 },
	{ Paint = "Lava" },
	{ Coins = 300 },
	{ Title = "Smasher" },
	{ Paint = "Toxic" },
	{ Coins = 400 },
	{ Revive = 1 },
	{ Coins = 400 },
	{ Title = "Sky Breaker" },
	{ Part = "Claw" },
	{ Coins = 500 },
	{ Paint = "Ocean" },
	{ Coins = 500 },
	{ Revive = 1 },
	{ Title = "Legend in the Making" },
	{ Coins = 600 },
	{ Paint = "Shadow" },
	{ Coins = 750 },
	{ Title = "Mix Master" },
	{ Part = "Rocket", Title = "Star Champion" },
}
function Config.StarXPFor(tier) -- XP needed to go from tier-1 to tier
	return 60 + (tier - 1) * 15
end
Config.StarOverflowXP = 300 -- after tier 30, every 300 XP gives a coin bonus
Config.StarOverflowCoins = 100

-- Ranked (1v1 vs real players only) --------------------------------------------------------
Config.Ranks = {
	{ Name = "Bronze", Min = 0, Icon = "🥉", Color = c(205, 127, 50) },
	{ Name = "Silver", Min = 150, Icon = "🥈", Color = c(200, 205, 215) },
	{ Name = "Gold", Min = 400, Icon = "🥇", Color = c(255, 200, 50) },
	{ Name = "Platinum", Min = 800, Icon = "💠", Color = c(90, 230, 220) },
	{ Name = "Diamond", Min = 1300, Icon = "💎", Color = c(110, 160, 255) },
	{ Name = "Champion", Min = 2000, Icon = "👑", Color = c(255, 90, 200) },
}
function Config.RankFor(trophies)
	local best = Config.Ranks[1]
	for _, rank in Config.Ranks do
		if trophies >= rank.Min then
			best = rank
		end
	end
	return best
end
Config.TrophyWin = 25
Config.TrophyLoss = 12

-- Rewards ----------------------------------------------------------------------------------
Config.Rewards = {
	WinCoins = 50,
	LossCoins = 20,
	SecondCoins = 32, -- 2nd place in free-for-all
	KOCoins = 5,
	WinXP = 80,
	LossXP = 40,
	SecondXP = 60,
	KOXP = 10,
	BotScale = 0.6, -- matches with bots give 60%
	StreakStep = 0.1, -- +10% coins per win in a row
	StreakMax = 0.5,
	VIPCoins = 1.5,
	VIPXP = 1.5,
	BoostXP = 2,
}

-- Daily login streak (7-day cycle). Missing a day restarts at day 1.
Config.Daily = {
	{ Coins = 100 },
	{ Coins = 150 },
	{ Coins = 200, XP = 50 },
	{ Coins = 300 },
	{ Coins = 400, XP = 100 },
	{ Coins = 500 },
	{ Coins = 1000, XP = 200 },
}

-- Daily quests (3 per day, picked from this pool)
Config.QuestPool = {
	{ Id = "Win2", Text = "Win 2 matches", Stat = "Win", Goal = 2, Coins = 150, XP = 80 },
	{ Id = "KO5", Text = "Get 5 KOs", Stat = "KO", Goal = 5, Coins = 120, XP = 70 },
	{ Id = "Play3", Text = "Play 3 matches", Stat = "Play", Goal = 3, Coins = 100, XP = 60 },
	{ Id = "Dmg300", Text = "Deal 300% damage", Stat = "Damage", Goal = 300, Coins = 120, XP = 70 },
	{ Id = "Special10", Text = "Use your special 10 times", Stat = "Special", Goal = 10, Coins = 80, XP = 50 },
	{ Id = "Story1", Text = "Clear a story fight", Stat = "Story", Goal = 1, Coins = 150, XP = 90 },
	{ Id = "Train60", Text = "Deal 60% to training dummies", Stat = "Train", Goal = 60, Coins = 60, XP = 40 },
	{ Id = "Dmg600", Text = "Deal 600% damage", Stat = "Damage", Goal = 600, Coins = 200, XP = 110 },
}
Config.QuestsPerDay = 3

-- Arenas -----------------------------------------------------------------------------------
-- Soft platforms: you can jump up through them and hold S/down to drop through.
Config.Arenas = {
	Junkyard = {
		Name = "Junkyard Ring",
		Width = 72,
		Floor = c(120, 95, 70),
		FloorMaterial = "CorrodedMetal",
		Accent = c(255, 170, 40),
		Backdrop = c(70, 60, 55),
		Platforms = { { -20, 13, 16 }, { 20, 13, 16 }, { 0, 25, 14 } }, -- { x, height, width }
		Deco = "Junk",
	},
	Rooftop = {
		Name = "Neon Rooftop",
		Width = 66,
		Floor = c(45, 45, 65),
		FloorMaterial = "Concrete",
		Accent = c(255, 60, 200),
		Backdrop = c(25, 20, 50),
		Platforms = { { -18, 12, 14 }, { 18, 12, 14 } },
		Deco = "City",
	},
	Clocktower = {
		Name = "Cog Clocktower",
		Width = 60,
		Floor = c(140, 110, 60),
		FloorMaterial = "Wood",
		Accent = c(255, 220, 120),
		Backdrop = c(90, 70, 45),
		Platforms = { { -22, 11, 12 }, { 0, 19, 16 }, { 22, 11, 12 } },
		Deco = "Gears",
	},
	SkyDocks = {
		Name = "Sky Docks",
		Width = 80,
		Floor = c(160, 120, 80),
		FloorMaterial = "WoodPlanks",
		Accent = c(90, 200, 255),
		Backdrop = c(120, 190, 255),
		Platforms = { { -26, 14, 14 }, { 26, 14, 14 }, { 0, 24, 18 } },
		Deco = "Clouds",
	},
	ScrapAlley = {
		Name = "Scrap Alley",
		Width = 76,
		Floor = c(100, 90, 80),
		FloorMaterial = "Asphalt",
		Accent = c(255, 140, 40),
		Backdrop = c(60, 55, 60),
		Platforms = { { -22, 13, 16 }, { 22, 13, 16 } },
		Deco = "Junk",
	},
	FrozenFactory = {
		Name = "Frozen Factory",
		Width = 72,
		Floor = c(170, 220, 255),
		FloorMaterial = "Ice",
		Accent = c(120, 230, 255),
		Backdrop = c(60, 90, 140),
		Platforms = { { -20, 12, 14 }, { 20, 12, 14 }, { 0, 23, 14 } },
		Deco = "Ice",
	},
	MagmaMill = {
		Name = "Magma Mill",
		Width = 70,
		Floor = c(60, 40, 35),
		FloorMaterial = "Basalt",
		Accent = c(255, 90, 20),
		Backdrop = c(90, 30, 20),
		Platforms = { { -20, 13, 14 }, { 20, 13, 14 } },
		Deco = "Lava",
	},
	JunkTower = {
		Name = "Dr. Junk's Tower",
		Width = 84,
		Floor = c(70, 70, 90),
		FloorMaterial = "DiamondPlate",
		Accent = c(180, 80, 255),
		Backdrop = c(30, 20, 45),
		Platforms = { { -28, 14, 14 }, { 28, 14, 14 }, { 0, 26, 20 } },
		Deco = "Gears",
	},
}
Config.PvPArenas = { "Junkyard", "Rooftop", "Clocktower", "SkyDocks" }

-- Story mode: The Scrapyard Saga ------------------------------------------------------------
Config.Speakers = {
	Bolt = { Name = "Professor Bolt", Icon = "🤖", Color = c(255, 210, 60) },
	Junk = { Name = "Dr. Junk", Icon = "😈", Color = c(180, 80, 255) },
	Clank = { Name = "Clank the Crusher", Icon = "🔨", Color = c(150, 150, 170) },
	Frostbyte = { Name = "Frostbyte", Icon = "❄️", Color = c(120, 230, 255) },
	Blaze = { Name = "Blaze Jaw", Icon = "🐲", Color = c(255, 110, 30) },
	Gale = { Name = "Captain Gale", Icon = "🏴‍☠️", Color = c(90, 200, 255) },
	Mega = { Name = "MEGA JUNK", Icon = "👾", Color = c(255, 60, 90) },
	You = { Name = "You", Icon = "😎", Color = c(90, 255, 140) },
}

local function minion(name, loadout, color)
	return { Name = name, Loadout = loadout, Color = color, Scale = 0.95, Weight = 1.25, Stocks = 1, Speed = 0.8, Skill = 0.35 }
end

Config.Chapters = {
	{
		Name = "Scrap Alley",
		Arena = "ScrapAlley",
		Boss = "Clank the Crusher",
		Reward = "Hammer",
		Coins = 300,
		XP = 150,
		Intro = {
			{ "Bolt", "Mixer! Wake up! Dr. Junk just stole every spare part in Mix City!" },
			{ "Bolt", "Your fighter is basic right now. But in this city, parts make the champion." },
			{ "Junk", "Ha ha ha! With every part in my tower, I'll build the ULTIMATE fighter!" },
			{ "Junk", "Junk Bots! Scrap that rookie!" },
			{ "Bolt", "Click to jab, E for a heavy hit, Q for your special. Knock them off the stage!" },
		},
		Waves = {
			{ minion("Junk Bot", { Head = "Bolt", Arms = "Gloves", Legs = "Sneakers" }, c(150, 120, 90)), minion("Junk Bot", { Head = "Bolt", Arms = "Gloves", Legs = "Sneakers" }, c(150, 120, 90)) },
		},
		BossIntro = {
			{ "Clank", "CLANK SMASH! You want my Hammer Arms? Come and take them!" },
			{ "Bolt", "He's heavy, so it takes more damage to launch him. Keep hitting!" },
		},
		BossDef = { Name = "Clank the Crusher", Loadout = { Head = "Bolt", Arms = "Hammer", Legs = "Treads" }, Color = c(130, 130, 150), Scale = 1.8, Weight = 0.8, Stocks = 2, Speed = 0.9, Skill = 0.55, Boss = true },
		Outro = {
			{ "Clank", "Clank... tired. Take the hammers..." },
			{ "Bolt", "The Hammer Arms are yours! Equip them in the Build menu and try a Ground Pound." },
			{ "Junk", "A lucky punch! The Frozen Factory will put you on ice, rookie!" },
		},
	},
	{
		Name = "Frozen Factory",
		Arena = "FrozenFactory",
		Boss = "Frostbyte",
		Reward = "Frost",
		Coins = 450,
		XP = 170,
		Intro = {
			{ "Bolt", "Brrr. The Frozen Factory. Careful, the floor is slippery!" },
			{ "Junk", "My Frost Bots never melt. Get them!" },
		},
		Waves = {
			{ minion("Frost Bot", { Head = "Frost", Arms = "Gloves", Legs = "Sneakers" }, c(150, 210, 240)), minion("Frost Bot", { Head = "Blaster", Arms = "Spring", Legs = "Sneakers" }, c(150, 210, 240)) },
			{ minion("Frost Bot", { Head = "Frost", Arms = "Drill", Legs = "Wheels" }, c(150, 210, 240)), minion("Frost Bot", { Head = "Bolt", Arms = "Gloves", Legs = "Wheels" }, c(150, 210, 240)) },
		},
		BossIntro = {
			{ "Frostbyte", "Ssssso cold... ssso lonely... Stay here and FREEZE with me!" },
			{ "Bolt", "Her Freeze Ray stops you in place. Dodge with F!" },
		},
		BossDef = { Name = "Frostbyte", Loadout = { Head = "Frost", Arms = "Spring", Legs = "SpringLegs" }, Color = c(140, 220, 255), Scale = 1.6, Weight = 0.9, Stocks = 2, Speed = 1.0, Skill = 0.6, Boss = true },
		Outro = {
			{ "Frostbyte", "Warm... for the first time... Take my Frost Head. Freeze him for me." },
			{ "Bolt", "Frost Head unlocked! Freeze someone, then smack them with a heavy." },
			{ "Junk", "Grr! Blaze Jaw will melt you in the Magma Mill!" },
		},
	},
	{
		Name = "Magma Mill",
		Arena = "MagmaMill",
		Boss = "Blaze Jaw",
		Reward = "RocketBoots",
		Coins = 600,
		XP = 190,
		Intro = {
			{ "Bolt", "The Magma Mill. Don't fall in. Seriously, don't." },
			{ "You", "Good tip, Professor." },
			{ "Junk", "Fire Bots, roast this pest!" },
		},
		Waves = {
			{ minion("Fire Bot", { Head = "Dragon", Arms = "Gloves", Legs = "Sneakers" }, c(220, 100, 60)), minion("Fire Bot", { Head = "Blaster", Arms = "Drill", Legs = "Sneakers" }, c(220, 100, 60)) },
			{ minion("Fire Bot", { Head = "Dragon", Arms = "Hammer", Legs = "Treads" }, c(220, 100, 60)), minion("Fire Bot", { Head = "Bolt", Arms = "Spring", Legs = "Wheels" }, c(220, 100, 60)), minion("Fire Bot", { Head = "Blaster", Arms = "Gloves", Legs = "Sneakers" }, c(220, 100, 60)) },
		},
		BossIntro = {
			{ "Blaze", "ROOOAR! My Rocket Boots let me fly over the lava. Can you?" },
		},
		BossDef = { Name = "Blaze Jaw", Loadout = { Head = "Dragon", Arms = "Drill", Legs = "RocketBoots" }, Color = c(255, 100, 40), Scale = 1.9, Weight = 0.85, Stocks = 2, Speed = 1.05, Skill = 0.65, Boss = true },
		Outro = {
			{ "Blaze", "Fine, FINE! The boots are yours. Don't burn your toes." },
			{ "Bolt", "Rocket Boots! Your air jumps now dash wherever you point." },
			{ "Junk", "Enough! Captain Gale guards the Sky Docks. Nobody beats the Captain!" },
		},
	},
	{
		Name = "Sky Docks",
		Arena = "SkyDocks",
		Boss = "Captain Gale",
		Reward = "Cloud",
		Coins = 750,
		XP = 210,
		Intro = {
			{ "Bolt", "The Sky Docks! Dr. Junk's tower is just above the clouds." },
			{ "Junk", "Sky Pirates! Throw this landlubber overboard!" },
		},
		Waves = {
			{ minion("Sky Pirate", { Head = "Blaster", Arms = "Claw", Legs = "SpringLegs" }, c(100, 170, 220)), minion("Sky Pirate", { Head = "Magnet", Arms = "Gloves", Legs = "Sneakers" }, c(100, 170, 220)) },
			{ minion("Sky Pirate", { Head = "Bolt", Arms = "Spring", Legs = "RocketBoots" }, c(100, 170, 220)), minion("Sky Pirate", { Head = "Blaster", Arms = "Drill", Legs = "SpringLegs" }, c(100, 170, 220)), minion("Sky Pirate", { Head = "Magnet", Arms = "Claw", Legs = "Sneakers" }, c(100, 170, 220)) },
		},
		BossIntro = {
			{ "Gale", "Yarr! I float like a cloud and hit like a storm. Ye'll never knock me down!" },
			{ "Bolt", "She floats a long time. Launch her hard, toward the sides!" },
		},
		BossDef = { Name = "Captain Gale", Loadout = { Head = "Magnet", Arms = "Claw", Legs = "Cloud" }, Color = c(90, 190, 255), Scale = 1.7, Weight = 0.9, Stocks = 3, Speed = 1.05, Skill = 0.7, Boss = true },
		Outro = {
			{ "Gale", "Ye fight like a true sky pirate. Take me Cloud Legs, matey." },
			{ "Bolt", "Cloud Legs! Hold jump to float. Now, to the tower!" },
			{ "Junk", "Come up, then. MEGA JUNK is finished. And it has ALL the parts." },
		},
	},
	{
		Name = "Dr. Junk's Tower",
		Arena = "JunkTower",
		Boss = "MEGA JUNK",
		Reward = "Thunder",
		Title = "Saga Hero",
		Coins = 1000,
		XP = 300,
		Intro = {
			{ "Junk", "Welcome to the top, rookie. Meet my bodyguards." },
			{ "Bolt", "This is it, Mixer. Everything we've learned. Mix it up!" },
		},
		Waves = {
			{ minion("Guard Bot", { Head = "Frost", Arms = "Hammer", Legs = "Treads" }, c(120, 90, 160)), minion("Guard Bot", { Head = "Dragon", Arms = "Spring", Legs = "SpringLegs" }, c(120, 90, 160)), minion("Guard Bot", { Head = "Blaster", Arms = "Drill", Legs = "Wheels" }, c(120, 90, 160)) },
		},
		BossIntro = {
			{ "Junk", "Behold! MEGA JUNK! Every stolen part, in one fighter!" },
			{ "Mega", "SYSTEMS ONLINE. TARGET: MIXER. INITIATING SMASH." },
			{ "Bolt", "It's huge and heavy. Freeze it, pull it, pound it. Use everything!" },
		},
		BossDef = { Name = "MEGA JUNK", Loadout = { Head = "Thunder", Arms = "Rocket", Legs = "Treads" }, Color = c(255, 70, 100), Scale = 2.3, Weight = 0.7, Stocks = 3, Speed = 1.0, Skill = 0.8, Boss = true },
		Outro = {
			{ "Mega", "SYSTEM... FAILURE... *clunk*" },
			{ "Junk", "No! I had every part! How did you beat me with those leftovers?" },
			{ "Bolt", "Because it was never about having the most parts, Doctor. It's how you MIX them." },
			{ "Junk", "...Hmph. Fine. Take the Thunder King Head. And give me back my screwdriver." },
			{ "Bolt", "You did it, Mixer! You're a Saga Hero! Now go show the arenas what you can do." },
		},
	},
}
Config.StoryReplayCoins = 100
Config.StoryReplayXP = 50
Config.ReviveWindow = 30 -- safety net only: the Second Wind pop-up shows no timer and "No thanks" ends it at once

-- Bots for matchmaking fill
Config.BotNames = { "Bot Sparky", "Bot Gizmo", "Bot Rusty", "Bot Nova", "Bot Pixel", "Bot Turbo", "Bot Widget", "Bot Zappy" }

-- Monetization -----------------------------------------------------------------------------
-- Create these on the Creator Dashboard, then paste the Ids here. Id = 0 hides the offer.
Config.GamePasses = {
	VIP = { Id = 0, Name = "VIP", Price = 199, Icon = "👑", Desc = "+50% coins and Star XP forever, a gold name, and the Royal paint." },
	StarBoost = { Id = 0, Name = "Star Boost", Price = 149, Icon = "🌟", Desc = "2x Star XP forever, so you climb the Star Road twice as fast." },
}

Config.Products = {
	CoinsS = { Id = 0, Name = "Pile of Coins", Price = 49, Icon = "🪙", Coins = 600, Desc = "600 coins." },
	CoinsM = { Id = 0, Name = "Sack of Coins", Price = 129, Icon = "💰", Coins = 1800, Desc = "1,800 coins." },
	CoinsL = { Id = 0, Name = "Vault of Coins", Price = 349, Icon = "🏦", Coins = 5500, Desc = "5,500 coins." },
	Starter = {
		Id = 0,
		Name = "Starter Bundle",
		Price = 99,
		Icon = "🎁",
		Coins = 1000,
		Parts = { "Blaster", "Wheels" },
		Paint = "Chrome",
		OneTime = true,
		Desc = "Blaster Head + Turbo Wheels + Chrome paint + 1,000 coins. One per account.",
	},
	SecondWind = { Id = 0, Name = "Second Wind", Price = 25, Icon = "💨", Revive = 1, Desc = "Refills your 3 lives in a story fight. If you're not in one, it's saved for next time." },
	PaintGold = { Id = 0, Name = "24K Gold Paint", Price = 79, Icon = "✨", Paint = "Gold", Desc = "Makes all your parts shiny gold." },
	PaintGalaxy = { Id = 0, Name = "Galaxy Paint", Price = 79, Icon = "🌌", Paint = "Galaxy", Desc = "Glowing purple galaxy parts." },
	PaintRainbow = { Id = 0, Name = "Rainbow Paint", Price = 99, Icon = "🌈", Paint = "Rainbow", Desc = "Your parts cycle through every color." },
}
Config.ShopOrder = { "Starter", "CoinsS", "CoinsM", "CoinsL", "PaintGold", "PaintGalaxy", "PaintRainbow", "SecondWind" }

return Config
