-- The lobby, built in code: spawn plaza, battle pads, story portal, Part Forge, Paint Shop,
-- training grounds, the Star Road path, daily chest, leaderboard and the Robux shop stall.
local Lighting = game:GetService("Lighting")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Workspace = game:GetService("Workspace")

local Config = require(ReplicatedStorage.Shared.Config)
local Format = require(ReplicatedStorage.Shared.Format)
local Remotes = require(ReplicatedStorage.Shared.Remotes)
local DataService = require(script.Parent.DataService)
local Npc = require(script.Parent.Npc)
local Profile = require(script.Parent.Profile)
local Visuals = require(script.Parent.Visuals)

local P = Visuals.Part
local Sign = Visuals.Sign

local Lobby = {}

local root -- Model "Lobby"

local function rgb(r, g, b)
	return Color3.fromRGB(r, g, b)
end

local function anchor(position, parent)
	return P({ Name = "Anchor", Size = Vector3.new(1, 1, 1), Transparency = 1, CanCollide = false, CanQuery = false, CFrame = CFrame.new(position), Parent = parent or root })
end

local function prompt(part, action, objectText, onTrigger, distance)
	local pp = Instance.new("ProximityPrompt")
	pp.ActionText = action
	pp.ObjectText = objectText or ""
	pp.HoldDuration = 0
	pp.MaxActivationDistance = distance or 10
	pp.RequiresLineOfSight = false
	pp.KeyboardKeyCode = Enum.KeyCode.R -- E is the heavy attack, so prompts use R
	pp.GamepadKeyCode = Enum.KeyCode.ButtonL3
	pp.Parent = part
	pp.Triggered:Connect(function(player)
		if DataService.Get(player) then
			onTrigger(player)
		end
	end)
	return pp
end

local function openPanel(player, panel)
	Remotes.Notify:FireClient(player, { Type = "Open", Panel = panel })
end

local function lighting()
	Lighting.ClockTime = 14.5
	Lighting.Brightness = 2.6
	Lighting.OutdoorAmbient = rgb(150, 150, 170)
	Lighting.Ambient = rgb(90, 90, 110)
	Lighting.GlobalShadows = true
	local atmosphere = Instance.new("Atmosphere")
	atmosphere.Density = 0.25
	atmosphere.Color = rgb(200, 220, 255)
	atmosphere.Decay = rgb(120, 140, 200)
	atmosphere.Glare = 0.2
	atmosphere.Haze = 0.6
	atmosphere.Parent = Lighting
	local cc = Instance.new("ColorCorrectionEffect")
	cc.Saturation = 0.25
	cc.Contrast = 0.08
	cc.Parent = Lighting
	local bloom = Instance.new("BloomEffect")
	bloom.Intensity = 0.6
	bloom.Size = 30
	bloom.Threshold = 1.6
	bloom.Parent = Lighting
end

local function pedestal(position, color, parent)
	P({ Name = "Pedestal", Shape = Enum.PartType.Cylinder, Size = Vector3.new(3, 5.5, 5.5), CFrame = CFrame.new(position + Vector3.new(0, 1.5, 0)) * CFrame.Angles(0, 0, math.rad(90)), Color = rgb(50, 50, 70), Material = Enum.Material.Marble, Parent = parent })
	return P({ Name = "PedestalTop", Shape = Enum.PartType.Cylinder, Size = Vector3.new(0.4, 5.8, 5.8), CFrame = CFrame.new(position + Vector3.new(0, 3.1, 0)) * CFrame.Angles(0, 0, math.rad(90)), Color = color, Material = Enum.Material.Neon, Parent = parent })
end

-- Spawn plaza ---------------------------------------------------------------------------------------------
local function plaza()
	P({ Name = "Ground", Size = Vector3.new(460, 2, 460), CFrame = CFrame.new(0, -1, 0), Color = rgb(110, 200, 110), Material = Enum.Material.Grass, Parent = root })
	P({ Name = "Plaza", Shape = Enum.PartType.Cylinder, Size = Vector3.new(0.4, 70, 70), CFrame = CFrame.new(0, 0.2, 0) * CFrame.Angles(0, 0, math.rad(90)), Color = rgb(245, 235, 220), Material = Enum.Material.Pavement, Parent = root })
	P({ Name = "PlazaRing", Shape = Enum.PartType.Cylinder, Size = Vector3.new(0.5, 72, 72), CFrame = CFrame.new(0, 0.15, 0) * CFrame.Angles(0, 0, math.rad(90)), Color = rgb(255, 120, 200), Material = Enum.Material.Neon, Parent = root })
	local spawn = Instance.new("SpawnLocation")
	spawn.Name = "MixSpawn"
	spawn.Size = Vector3.new(12, 1, 12)
	spawn.CFrame = CFrame.new(0, 0.5, 0)
	spawn.Anchored = true
	spawn.Neutral = true
	spawn.Duration = 0
	spawn.Color = rgb(255, 210, 60)
	spawn.Material = Enum.Material.Neon
	spawn.TopSurface = Enum.SurfaceType.Smooth
	spawn.Parent = root
	local decal = spawn:FindFirstChildOfClass("Decal")
	if decal then
		decal:Destroy()
	end
	-- Paths to every zone
	local paths = {
		{ Vector3.new(0, 0.25, -45), Vector3.new(10, 0.3, 30), rgb(255, 80, 120) }, -- battle
		{ Vector3.new(45, 0.25, 0), Vector3.new(30, 0.3, 10), rgb(255, 160, 40) }, -- forge
		{ Vector3.new(-45, 0.25, 0), Vector3.new(30, 0.3, 10), rgb(80, 200, 255) }, -- training
		{ Vector3.new(0, 0.25, 42), Vector3.new(10, 0.3, 16), rgb(255, 220, 60) }, -- star road
	}
	for _, p in paths do
		P({ Name = "Path", Size = p[2], CFrame = CFrame.new(p[1]), Color = p[3], Material = Enum.Material.SmoothPlastic, Parent = root })
	end
	local title = anchor(Vector3.new(0, 26, -30))
	Sign(title, '<font color="#FFD23C">MIX</font> <font color="#FFFFFF">&amp;</font> <font color="#FF5AA0">SMASH</font>', Color3.new(1, 1, 1), UDim2.fromOffset(700, 140), Vector3.zero, 300)
	local sub = anchor(Vector3.new(0, 20, -30))
	Sign(sub, "Build your fighter from parts. Smash everyone off the stage!", rgb(230, 230, 255), UDim2.fromOffset(700, 40), Vector3.zero, 200)
	-- Signposts
	local posts = {
		{ Vector3.new(0, 8, -24), "⚔️ BATTLE ⬆" },
		{ Vector3.new(24, 8, 0), "🔧 PART FORGE ➡" },
		{ Vector3.new(-24, 8, 0), "⬅ 🎯 TRAINING" },
		{ Vector3.new(0, 8, 24), "⭐ STAR ROAD ⬇" },
	}
	for _, post in posts do
		P({ Name = "Post", Size = Vector3.new(0.6, 7, 0.6), CFrame = CFrame.new(post[1] - Vector3.new(0, 4.5, 0)), Color = rgb(120, 85, 50), Material = Enum.Material.Wood, Parent = root })
		Sign(anchor(post[1]), post[2], Color3.new(1, 1, 1), UDim2.fromOffset(260, 50), Vector3.zero, 90)
	end
	return CFrame.new(0, 4, 0)
end

-- Battle zone: queue pads + story portal -------------------------------------------------------------------
local function battleZone()
	local center = Vector3.new(0, 0, -80)
	P({ Name = "BattleFloor", Size = Vector3.new(100, 0.4, 56), CFrame = CFrame.new(center + Vector3.new(0, 0.2, 0)), Color = rgb(60, 45, 90), Material = Enum.Material.SmoothPlastic, Parent = root })
	local pads = {}
	local function makePad(mode, x, color, title)
		local pos = center + Vector3.new(x, 0.5, 4)
		local pad = P({ Name = mode .. "Pad", Shape = Enum.PartType.Cylinder, Size = Vector3.new(0.6, 16, 16), CFrame = CFrame.new(pos) * CFrame.Angles(0, 0, math.rad(90)), Color = color, Material = Enum.Material.Neon, Parent = root })
		P({ Name = "PadRim", Shape = Enum.PartType.Cylinder, Size = Vector3.new(0.5, 18, 18), CFrame = CFrame.new(pos - Vector3.new(0, 0.1, 0)) * CFrame.Angles(0, 0, math.rad(90)), Color = rgb(30, 30, 40), Material = Enum.Material.Metal, Parent = root })
		for i = 0, 3 do
			local a = math.rad(i * 90 + 45)
			P({ Name = "PadPillar", Size = Vector3.new(1.2, 14, 1.2), CFrame = CFrame.new(pos + Vector3.new(math.cos(a) * 10, 7, math.sin(a) * 10)), Color = color, Material = Enum.Material.Neon, Parent = root })
		end
		local label = Sign(anchor(pos + Vector3.new(0, 12, 0)), title, Color3.new(1, 1, 1), UDim2.fromOffset(320, 120), Vector3.zero, 160)
		pads[mode] = { Part = pad, Label = label }
	end
	makePad("Ranked", -26, rgb(255, 60, 90), "1v1 RANKED")
	makePad("FFA", 26, rgb(60, 150, 255), "FREE-FOR-ALL")
	Sign(anchor(center + Vector3.new(-26, 17, 4)), "🏆 Win trophies, climb Bronze ➜ Champion", rgb(255, 210, 80), UDim2.fromOffset(360, 36), Vector3.zero, 100)
	Sign(anchor(center + Vector3.new(26, 17, 4)), "💥 Up to 4 players, last one standing wins", rgb(150, 210, 255), UDim2.fromOffset(360, 36), Vector3.zero, 100)

	-- Story portal
	local portalPos = center + Vector3.new(0, 0, -18)
	for i = 0, 15 do
		local a = math.rad(i * (360 / 16))
		P({ Name = "PortalRing", Size = Vector3.new(2, 2, 2), CFrame = CFrame.new(portalPos + Vector3.new(math.cos(a) * 9, 10 + math.sin(a) * 9, 0)), Color = rgb(170, 80, 255), Material = Enum.Material.Neon, Parent = root })
	end
	P({ Name = "PortalCore", Shape = Enum.PartType.Cylinder, Size = Vector3.new(0.5, 16, 16), CFrame = CFrame.new(portalPos + Vector3.new(0, 10, 0)) * CFrame.Angles(0, math.rad(90), 0), Color = rgb(120, 40, 220), Material = Enum.Material.Neon, Transparency = 0.45, CanCollide = false, Parent = root })
	local portalStand = pedestal(portalPos + Vector3.new(0, 0, 5), rgb(170, 80, 255), root)
	Sign(anchor(portalPos + Vector3.new(0, 22, 0)), "📖 STORY MODE\nThe Scrapyard Saga", rgb(220, 180, 255), UDim2.fromOffset(340, 90), Vector3.zero, 160)
	prompt(portalStand, "Open Story", "Story Portal", function(player)
		openPanel(player, "Story")
	end)
	return pads
end

-- Part Forge + Paint Shop --------------------------------------------------------------------------------------
local function forge()
	local center = Vector3.new(88, 0, 0)
	local folder = Instance.new("Folder")
	folder.Name = "Forge"
	folder.Parent = root
	P({ Name = "ForgeFloor", Size = Vector3.new(80, 0.4, 84), CFrame = CFrame.new(center + Vector3.new(0, 0.2, 8)), Color = rgb(90, 60, 40), Material = Enum.Material.WoodPlanks, Parent = folder })
	P({ Name = "ForgeBackWall", Size = Vector3.new(2, 24, 84), CFrame = CFrame.new(center + Vector3.new(40, 12, 8)), Color = rgb(70, 45, 35), Material = Enum.Material.Brick, Parent = folder })
	P({ Name = "ForgeFurnace", Size = Vector3.new(4, 10, 16), CFrame = CFrame.new(center + Vector3.new(37, 5, -14)), Color = rgb(255, 110, 20), Material = Enum.Material.Neon, Parent = folder })
	Sign(anchor(center + Vector3.new(0, 22, -34), folder), "🔧 PART FORGE", rgb(255, 170, 60), UDim2.fromOffset(500, 90), Vector3.zero, 220)
	Sign(anchor(center + Vector3.new(0, 17, -34), folder), "Mix a head, arms and legs. Every part works with every other part!", rgb(255, 230, 200), UDim2.fromOffset(620, 36), Vector3.zero, 160)

	local buildStand = pedestal(center + Vector3.new(-34, 0, -26), rgb(255, 170, 60), folder)
	prompt(buildStand, "Open Build menu", "Your fighter", function(player)
		openPanel(player, "Build")
	end)

	local rows = { Head = -18, Arms = 0, Legs = 18 }
	for _, slot in Config.Slots do
		local z = rows[slot]
		local info = Config.SlotInfo[slot]
		Sign(anchor(center + Vector3.new(-32, 6, z), folder), info.Icon .. " " .. info.Title .. "\n" .. info.Role, Color3.new(1, 1, 1), UDim2.fromOffset(200, 70), Vector3.zero, 90)
		for i, key in Config.PartOrder[slot] do
			local part = Config.Parts[key]
			local pos = center + Vector3.new(-20 + (i - 1) * 10.5, 0, z)
			local top = pedestal(pos, Config.Rarities[part.Rarity], folder)
			local display = Visuals.Display(key, "Default", CFrame.new(pos + Vector3.new(0, 6.2, 0)), 2)
			display.Parent = folder
			local cost = part.Price and ("🪙 " .. Format.Number(part.Price)) or ("🔒 " .. part.Source)
			Sign(top, part.Icon .. " " .. part.Name .. '\n<font size="14">' .. part.Rarity .. " · " .. cost .. "</font>", Config.Rarities[part.Rarity], UDim2.fromOffset(220, 64), Vector3.new(0, 7.5, 0), 55)
			local pp = prompt(top, part.Price and "Buy" or "Locked", part.Name, function(player)
				Profile.BuyPart(player, key)
			end, 8)
			pp:SetAttribute("PartKey", key)
		end
	end

	-- Paint Shop row
	local paintKeys = {}
	for key in Config.Paints do
		table.insert(paintKeys, key)
	end
	table.sort(paintKeys, function(a, b)
		return Config.Paints[a].Order < Config.Paints[b].Order
	end)
	Sign(anchor(center + Vector3.new(0, 12, 36), folder), "🎨 PAINT SHOP (just for looks)", rgb(255, 150, 220), UDim2.fromOffset(420, 50), Vector3.zero, 140)
	for i, key in paintKeys do
		local paint = Config.Paints[key]
		local pos = center + Vector3.new(-31 + (i - 1) * 7, 0, 40)
		local top = P({ Name = "PaintStand", Size = Vector3.new(4, 3, 4), CFrame = CFrame.new(pos + Vector3.new(0, 1.5, 0)), Color = rgb(50, 50, 70), Material = Enum.Material.Marble, Parent = folder })
		local blob = P({ Name = "PaintBlob", Shape = Enum.PartType.Ball, Size = Vector3.new(2.6, 2.6, 2.6), CFrame = CFrame.new(pos + Vector3.new(0, 4.6, 0)), Color = paint.Color or rgb(230, 230, 235), Material = Enum.Material[paint.Material or "SmoothPlastic"], Parent = folder })
		if paint.Rainbow then
			game:GetService("CollectionService"):AddTag(blob, "RainbowPart")
		end
		local cost
		if paint.Price then
			cost = "🪙 " .. Format.Number(paint.Price)
		elseif paint.Product then
			cost = "R$ " .. Config.Products[paint.Product].Price
		elseif paint.Pass then
			cost = "👑 VIP"
		elseif key == "Default" then
			cost = "Free"
		else
			cost = "⭐ " .. paint.Source
		end
		Sign(blob, paint.Name .. '\n<font size="13">' .. cost .. "</font>", paint.Color or Color3.new(1, 1, 1), UDim2.fromOffset(130, 50), Vector3.new(0, 3, 0), 45)
		local pp = prompt(top, "Paint", paint.Name, function(player)
			Profile.BuyPaint(player, key)
		end, 7)
		pp:SetAttribute("PaintKey", key)
	end
end

-- Training grounds -------------------------------------------------------------------------------------------------
local function training()
	local center = Vector3.new(-85, 0, 0)
	local folder = Instance.new("Folder")
	folder.Name = "Training"
	folder.Parent = root
	P({ Name = "TrainingFloor", Size = Vector3.new(64, 0.4, 56), CFrame = CFrame.new(center + Vector3.new(0, 0.2, 0)), Color = rgb(60, 130, 200), Material = Enum.Material.SmoothPlastic, Parent = folder })
	for _, z in { -22, -11, 0, 11, 22 } do
		P({ Name = "Stripe", Size = Vector3.new(64, 0.45, 0.6), CFrame = CFrame.new(center + Vector3.new(0, 0.2, z)), Color = rgb(255, 255, 255), Material = Enum.Material.Neon, Parent = folder })
	end
	Sign(anchor(center + Vector3.new(0, 18, -24), folder), "🎯 TRAINING GROUNDS", rgb(120, 210, 255), UDim2.fromOffset(460, 80), Vector3.zero, 200)
	Sign(anchor(center + Vector3.new(0, 13, -24), folder), "Click = Jab · E = Heavy (arms) · Q = Special (head) · F = Dodge · Space = Jump", Color3.new(1, 1, 1), UDim2.fromOffset(700, 36), Vector3.zero, 150)
	Sign(anchor(center + Vector3.new(0, 10, -24), folder), "Try every part combo here. More damage % = they fly farther!", rgb(255, 230, 150), UDim2.fromOffset(600, 32), Vector3.zero, 150)
	for _, z in { -12, 0, 12 } do
		local pos = center + Vector3.new(-14, 3.2, z)
		P({ Name = "DummyBase", Shape = Enum.PartType.Cylinder, Size = Vector3.new(0.6, 6, 6), CFrame = CFrame.new(pos.X, 0.5, pos.Z) * CFrame.Angles(0, 0, math.rad(90)), Color = rgb(255, 200, 80), Material = Enum.Material.Neon, Parent = folder })
		Npc.SpawnDummy(pos, folder)
	end
end

-- Star Road path ---------------------------------------------------------------------------------------------------------
local function rewardText(reward)
	local bits = {}
	if reward.Coins then
		table.insert(bits, "🪙 " .. reward.Coins)
	end
	if reward.Part then
		table.insert(bits, Config.Parts[reward.Part].Icon .. " " .. Config.Parts[reward.Part].Name)
	end
	if reward.Paint then
		table.insert(bits, "🎨 " .. Config.Paints[reward.Paint].Name)
	end
	if reward.Title then
		table.insert(bits, "🏷️ " .. reward.Title)
	end
	if reward.Revive then
		table.insert(bits, "💨 Second Wind")
	end
	return table.concat(bits, "\n")
end
Lobby.RewardText = rewardText

local function starRoad()
	local folder = Instance.new("Folder")
	folder.Name = "StarRoad"
	folder.Parent = root
	Sign(anchor(Vector3.new(0, 16, 52), folder), "⭐ STAR ROAD ⭐", rgb(255, 220, 60), UDim2.fromOffset(460, 80), Vector3.zero, 220)
	Sign(anchor(Vector3.new(0, 11.5, 52), folder), "FREE rewards. Earn Star XP from every match, story fight and quest. Tiles light up as you go!", Color3.new(1, 1, 1), UDim2.fromOffset(760, 36), Vector3.zero, 160)
	local gate = pedestal(Vector3.new(-12, 0, 50), rgb(255, 220, 60), folder)
	prompt(gate, "View Star Road", "Star Road", function(player)
		openPanel(player, "StarRoad")
	end)
	for tier = 1, #Config.StarRoad do
		local row = (tier - 1) // 10
		local col = (tier - 1) % 10
		if row % 2 == 1 then
			col = 9 - col
		end
		local pos = Vector3.new(-58 + col * 12.9, 0.4, 62 + row * 20)
		local tile = P({ Name = "StarTile", Size = Vector3.new(10, 0.6, 10), CFrame = CFrame.new(pos), Color = rgb(90, 90, 110), Material = Enum.Material.SmoothPlastic, Parent = folder })
		tile:SetAttribute("Tier", tier)
		local reward = Config.StarRoad[tier]
		local big = reward.Part ~= nil or reward.Paint ~= nil or tier == #Config.StarRoad
		if big then
			P({ Name = "TileBeacon", Shape = Enum.PartType.Ball, Size = Vector3.new(3, 3, 3), CFrame = CFrame.new(pos + Vector3.new(0, 5, 0)), Color = rgb(255, 220, 60), Material = Enum.Material.Neon, CanCollide = false, Parent = folder })
		end
		Sign(tile, "<b>" .. tier .. "</b>\n" .. rewardText(reward), big and rgb(255, 230, 120) or Color3.new(1, 1, 1), UDim2.fromOffset(150, big and 70 or 56), Vector3.new(0, big and 8 or 3.5, 0), 70)
		if col == 9 and row < 2 or (col == 0 and row == 1) then
			-- Connector to the next row
			P({ Name = "TileLink", Size = Vector3.new(4, 0.5, 10), CFrame = CFrame.new(pos + Vector3.new(0, 0, 10)), Color = rgb(255, 220, 60), Material = Enum.Material.Neon, Parent = folder })
		end
	end
end

-- Daily chest, leaderboard, Robux shop stall ---------------------------------------------------------------------------------
local leaderLabel
local function spawnExtras()
	-- Daily chest
	local chestPos = Vector3.new(16, 0, 14)
	local chest = P({ Name = "DailyChest", Size = Vector3.new(5, 3.4, 3.4), CFrame = CFrame.new(chestPos + Vector3.new(0, 1.7, 0)), Color = rgb(150, 90, 40), Material = Enum.Material.Wood, Parent = root })
	P({ Name = "ChestLid", Size = Vector3.new(5.2, 1, 3.6), CFrame = CFrame.new(chestPos + Vector3.new(0, 3.8, 0)), Color = rgb(255, 200, 50), Material = Enum.Material.Foil, Parent = root })
	P({ Name = "ChestGlow", Shape = Enum.PartType.Ball, Size = Vector3.new(1.4, 1.4, 1.4), CFrame = CFrame.new(chestPos + Vector3.new(0, 2.2, -1.8)), Color = rgb(255, 240, 120), Material = Enum.Material.Neon, Parent = root })
	Sign(chest, "📅 DAILY REWARD\nCome back every day!", rgb(255, 220, 90), UDim2.fromOffset(220, 60), Vector3.new(0, 5, 0), 80)
	prompt(chest, "Claim daily reward", "Daily Chest", function(player)
		if not Profile.ClaimDaily(player) then
			Profile.Toast(player, "Already claimed today. Come back tomorrow to keep your streak!")
		end
	end)

	-- Leaderboard (players in this server)
	local board = P({ Name = "Leaderboard", Size = Vector3.new(22, 14, 1), CFrame = CFrame.new(-22, 8, 28) * CFrame.Angles(0, math.rad(35), 0), Color = rgb(30, 25, 50), Material = Enum.Material.SmoothPlastic, Parent = root })
	P({ Name = "BoardLeg", Size = Vector3.new(1, 8, 1), CFrame = CFrame.new(-22, 0.5, 28), Color = rgb(30, 25, 50), Material = Enum.Material.Metal, Parent = root })
	local surface = Instance.new("SurfaceGui")
	surface.Face = Enum.NormalId.Front
	surface.CanvasSize = Vector2.new(440, 280)
	surface.LightInfluence = 0
	surface.Parent = board
	local label = Instance.new("TextLabel")
	label.Size = UDim2.fromScale(1, 1)
	label.BackgroundTransparency = 1
	label.Font = Enum.Font.FredokaOne
	label.TextColor3 = Color3.new(1, 1, 1)
	label.TextSize = 20
	label.RichText = true
	label.TextXAlignment = Enum.TextXAlignment.Left
	label.TextYAlignment = Enum.TextYAlignment.Top
	label.Text = "🏆 TOP FIGHTERS HERE"
	label.Parent = surface
	local pad = Instance.new("UIPadding")
	pad.PaddingLeft = UDim.new(0, 14)
	pad.PaddingTop = UDim.new(0, 10)
	pad.Parent = label
	leaderLabel = label

	-- Robux shop stall: every stand shows exactly what you get.
	local stallCenter = Vector3.new(26, 0, 28)
	P({ Name = "ShopFloor", Size = Vector3.new(30, 0.4, 16), CFrame = CFrame.new(stallCenter + Vector3.new(0, 0.25, 0)) * CFrame.Angles(0, math.rad(-35), 0), Color = rgb(255, 230, 150), Material = Enum.Material.SmoothPlastic, Parent = root })
	Sign(anchor(stallCenter + Vector3.new(0, 13, 0)), "🛒 SHOP", rgb(255, 210, 80), UDim2.fromOffset(240, 60), Vector3.zero, 160)
	Sign(anchor(stallCenter + Vector3.new(0, 9.5, 0)), "Every item shows exactly what you get. No random boxes.", Color3.new(1, 1, 1), UDim2.fromOffset(460, 30), Vector3.zero, 90)
	local stands = {
		{ "Pass", "VIP", rgb(255, 200, 50) },
		{ "Pass", "StarBoost", rgb(255, 240, 120) },
		{ "Product", "Starter", rgb(120, 255, 160) },
		{ "Product", "CoinsM", rgb(255, 210, 60) },
	}
	local rot = CFrame.Angles(0, math.rad(-35), 0)
	for i, stand in stands do
		local kind, key, color = stand[1], stand[2], stand[3]
		local info = kind == "Pass" and Config.GamePasses[key] or Config.Products[key]
		local pos = (CFrame.new(stallCenter) * rot * CFrame.new(-10.5 + (i - 1) * 7, 0, 0)).Position
		local top = pedestal(pos, color, root)
		local icon = anchor(pos + Vector3.new(0, 6, 0))
		Sign(icon, info.Icon, Color3.new(1, 1, 1), UDim2.fromOffset(70, 70), Vector3.zero, 70)
		Sign(top, info.Name .. (info.Id ~= 0 and (' · R$ ' .. info.Price) or ' · coming soon') .. '\n<font size="12">' .. info.Desc .. "</font>", color, UDim2.fromOffset(230, 80), Vector3.new(0, 9, 0), 50)
		prompt(top, info.Id ~= 0 and ("Buy (R$ " .. info.Price .. ")") or "Coming soon", info.Name, function(player)
			if kind == "Pass" then
				Profile.PromptPass(player, key)
			else
				local data = DataService.Get(player)
				if info.OneTime and data and data.StarterBought then
					Profile.Toast(player, "You already have the " .. info.Name .. "!")
					return
				end
				Profile.PromptProduct(player, key)
			end
		end, 8)
	end
end

local function updateLeaderboard()
	local list = {}
	for _, player in Players:GetPlayers() do
		local data = DataService.Get(player)
		if data then
			table.insert(list, { Name = player.DisplayName, Trophies = data.Trophies, Wins = data.Wins })
		end
	end
	table.sort(list, function(a, b)
		return a.Trophies > b.Trophies
	end)
	local lines = { '<font size="26" color="#FFD23C">🏆 TOP FIGHTERS HERE</font>' }
	for i = 1, math.min(8, #list) do
		local e = list[i]
		local rank = Config.RankFor(e.Trophies)
		table.insert(lines, i .. ". " .. rank.Icon .. " " .. e.Name .. "  ·  " .. e.Trophies .. " 🏆  ·  " .. e.Wins .. " wins")
	end
	leaderLabel.Text = table.concat(lines, "\n")
end

function Lobby.Build()
	for _, inst in Workspace:GetDescendants() do
		if inst:IsA("SpawnLocation") then
			inst:Destroy()
		end
	end
	root = Instance.new("Model")
	root.Name = "Lobby"
	root.Parent = Workspace
	lighting()
	local spawnCFrame = plaza()
	local pads = battleZone()
	forge()
	training()
	starRoad()
	spawnExtras()
	task.spawn(function()
		while true do
			pcall(updateLeaderboard)
			task.wait(10)
		end
	end)
	return { Spawn = spawnCFrame, Pads = pads }
end

return Lobby
