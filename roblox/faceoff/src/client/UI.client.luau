-- The whole UI, built in code: top bar, menu, Fight button + queue bar, panels (Build, Story,
-- Star Road, Quests, Shop, Help, Daily), fight HUD, story dialogue, results and pop-ups.
local Debris = game:GetService("Debris")
local MarketplaceService = game:GetService("MarketplaceService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")
local SoundService = game:GetService("SoundService")
local TweenService = game:GetService("TweenService")
local UserInputService = game:GetService("UserInputService")
local Workspace = game:GetService("Workspace")

local Config = require(ReplicatedStorage.Shared.Config)
local Format = require(ReplicatedStorage.Shared.Format)
local Remotes = require(ReplicatedStorage.Shared.Remotes)

local player = Players.LocalPlayer

local BG = Color3.fromRGB(24, 22, 44)
local CARD = Color3.fromRGB(42, 40, 74)
local ACCENT = Color3.fromRGB(110, 120, 255)
local GOLD = Color3.fromRGB(255, 205, 70)
local GREEN = Color3.fromRGB(70, 210, 120)
local RED = Color3.fromRGB(235, 60, 90)
local GRAY = Color3.fromRGB(95, 95, 120)
local PINK = Color3.fromRGB(255, 90, 170)
local PURPLE = Color3.fromRGB(170, 90, 255)
local WHITE = Color3.new(1, 1, 1)
local FONT = Enum.Font.FredokaOne

local state = nil
local match = nil
local queueMode, queueSince = nil, 0

-- Helpers ------------------------------------------------------------------------------------------
local function new(class, props, kids)
	local inst = Instance.new(class)
	local parent
	for k, v in props or {} do
		if k == "Parent" then
			parent = v
		else
			inst[k] = v
		end
	end
	for _, kid in kids or {} do
		kid.Parent = inst
	end
	inst.Parent = parent
	return inst
end

local function corner(radius)
	return new("UICorner", { CornerRadius = UDim.new(0, radius or 10) })
end

local function stroke(color, thickness)
	return new("UIStroke", { Color = color, Thickness = thickness or 2, ApplyStrokeMode = Enum.ApplyStrokeMode.Border })
end

local function label(props)
	props.BackgroundTransparency = props.BackgroundTransparency or 1
	props.Font = props.Font or FONT
	props.TextColor3 = props.TextColor3 or WHITE
	props.TextSize = props.TextSize or 16
	return new("TextLabel", props)
end

local function button(text, color, size, parent, props)
	local b = new("TextButton", {
		Text = text,
		Font = FONT,
		TextSize = 17,
		TextColor3 = WHITE,
		BackgroundColor3 = color,
		Size = size,
		AutoButtonColor = true,
		Parent = parent,
	}, { corner(10), stroke(color:Lerp(Color3.new(0, 0, 0), 0.4), 2) })
	for k, v in props or {} do
		b[k] = v
	end
	return b
end

local function sound(speed, volume)
	local s = Instance.new("Sound")
	s.SoundId = "rbxasset://sounds/electronicpingshort.wav"
	s.PlaybackSpeed = speed or 1
	s.Volume = volume or 0.5
	s.Parent = SoundService
	s:Play()
	Debris:AddItem(s, 3)
end

local function serverNow()
	return Workspace:GetServerTimeNow()
end

local function clear(frame)
	for _, child in frame:GetChildren() do
		if not child:IsA("UIGridLayout") and not child:IsA("UIListLayout") and not child:IsA("UIPadding") then
			child:Destroy()
		end
	end
end

local gui = new("ScreenGui", {
	Name = "MixUI",
	ResetOnSpawn = false,
	IgnoreGuiInset = false,
	ZIndexBehavior = Enum.ZIndexBehavior.Sibling,
	Parent = player:WaitForChild("PlayerGui"),
})

-- Toast + feed ------------------------------------------------------------------------------------------
local toastLabel = label({
	Size = UDim2.new(0.6, 0, 0, 40),
	AnchorPoint = Vector2.new(0.5, 0),
	Position = UDim2.new(0.5, 0, 0, 56),
	BackgroundColor3 = BG,
	BackgroundTransparency = 1,
	TextTransparency = 1,
	TextSize = 18,
	TextWrapped = true,
	ZIndex = 40,
	Parent = gui,
})
corner(10).Parent = toastLabel
new("UISizeConstraint", { MaxSize = Vector2.new(560, 60), Parent = toastLabel })
local toastToken = 0
local function toast(text, color)
	toastToken += 1
	local token = toastToken
	toastLabel.Text = text
	toastLabel.TextColor3 = color or WHITE
	toastLabel.TextTransparency = 0
	toastLabel.BackgroundTransparency = 0.15
	task.delay(3.2, function()
		if toastToken == token then
			TweenService:Create(toastLabel, TweenInfo.new(0.4), { TextTransparency = 1, BackgroundTransparency = 1 }):Play()
		end
	end)
end

local feed = new("Frame", {
	Size = UDim2.fromOffset(330, 150),
	AnchorPoint = Vector2.new(0, 1),
	Position = UDim2.new(0, 10, 1, -10),
	BackgroundTransparency = 1,
	Parent = gui,
}, {
	new("UIListLayout", { VerticalAlignment = Enum.VerticalAlignment.Bottom, Padding = UDim.new(0, 3), SortOrder = Enum.SortOrder.LayoutOrder }),
})
local feedOrder = 0
local function feedLine(text, color)
	feedOrder += 1
	local line = label({
		Size = UDim2.new(1, 0, 0, 22),
		Text = text,
		TextColor3 = color or WHITE,
		TextSize = 15,
		TextXAlignment = Enum.TextXAlignment.Left,
		TextStrokeTransparency = 0.4,
		TextTruncate = Enum.TextTruncate.AtEnd,
		LayoutOrder = feedOrder,
		Parent = feed,
	})
	local lines = {}
	for _, child in feed:GetChildren() do
		if child:IsA("TextLabel") then
			table.insert(lines, child)
		end
	end
	table.sort(lines, function(a, b)
		return a.LayoutOrder < b.LayoutOrder
	end)
	while #lines > 5 do
		table.remove(lines, 1):Destroy()
	end
	task.delay(9, function()
		if line.Parent then
			TweenService:Create(line, TweenInfo.new(0.6), { TextTransparency = 1, TextStrokeTransparency = 1 }):Play()
			Debris:AddItem(line, 0.7)
		end
	end)
end

-- Purchases (client prompts; the server grants) ------------------------------------------------------
local function buyProduct(key)
	local info = Config.Products[key]
	if not info or info.Id == 0 then
		toast("This item isn't for sale yet.")
		return
	end
	MarketplaceService:PromptProductPurchase(player, info.Id)
end

local function buyPass(key)
	local info = Config.GamePasses[key]
	if not info or info.Id == 0 then
		toast("This pass isn't for sale yet.")
		return
	end
	MarketplaceService:PromptGamePassPurchase(player, info.Id)
end

local function invoke(remote, ...)
	local args = table.pack(...)
	task.spawn(function()
		local ok, err = pcall(function()
			remote:InvokeServer(table.unpack(args, 1, args.n))
		end)
		if not ok then
			warn("[UI]", remote.Name, err)
		end
	end)
end

-- Top bar ----------------------------------------------------------------------------------------------------
local topBar = new("Frame", {
	Size = UDim2.fromOffset(0, 40),
	AutomaticSize = Enum.AutomaticSize.X,
	AnchorPoint = Vector2.new(0.5, 0),
	Position = UDim2.new(0.5, 0, 0, 8),
	BackgroundTransparency = 1,
	Parent = gui,
}, {
	new("UIListLayout", { FillDirection = Enum.FillDirection.Horizontal, Padding = UDim.new(0, 8), SortOrder = Enum.SortOrder.LayoutOrder, VerticalAlignment = Enum.VerticalAlignment.Center }),
})

local function pill(order, width, color)
	local frame = new("Frame", { Size = UDim2.fromOffset(width, 38), BackgroundColor3 = BG, BackgroundTransparency = 0.1, LayoutOrder = order, Parent = topBar }, { corner(19), stroke(color, 2) })
	local text = label({ Size = UDim2.new(1, -12, 1, 0), Position = UDim2.fromOffset(6, 0), TextSize = 18, Text = "", TextColor3 = WHITE, Parent = frame })
	return frame, text
end
local _, coinText = pill(1, 120, GOLD)
local starFrame, starText = pill(2, 170, Color3.fromRGB(255, 230, 110))
local starBar = new("Frame", { Size = UDim2.fromOffset(0, 4), Position = UDim2.new(0, 14, 1, -7), BackgroundColor3 = GOLD, BorderSizePixel = 0, Parent = starFrame }, { corner(2) })
local _, rankText = pill(3, 150, ACCENT)
local _, streakText = pill(4, 110, Color3.fromRGB(255, 130, 50))
local savingOff = label({
	Size = UDim2.fromOffset(520, 26),
	AnchorPoint = Vector2.new(1, 1),
	Position = UDim2.new(1, -10, 1, -8),
	Text = "Studio test: saving is off until the place is published",
	TextXAlignment = Enum.TextXAlignment.Right,
	TextColor3 = Color3.fromRGB(255, 120, 120),
	TextSize = 15,
	TextStrokeTransparency = 0.3,
	Visible = false,
	Parent = gui,
})

-- Panels -----------------------------------------------------------------------------------------------------
local panels = {}
local openName = nil

local function closePanels()
	for _, p in panels do
		p.Frame.Visible = false
	end
	openName = nil
end

local function openPanel(name)
	local p = panels[name]
	if not p then
		return
	end
	if match and name ~= "Help" then
		toast("Finish your fight first!")
		return
	end
	closePanels()
	p.Frame.Visible = true
	openName = name
	if p.Refresh and state then
		p.Refresh()
	end
	sound(1.2, 0.3)
end

local function makePanel(name, title, maxSize, color)
	local frame = new("Frame", {
		Name = name,
		Size = UDim2.fromScale(0.94, 0.86),
		AnchorPoint = Vector2.new(0.5, 0.5),
		Position = UDim2.fromScale(0.5, 0.53),
		BackgroundColor3 = BG,
		Visible = false,
		ZIndex = 10,
		Parent = gui,
	}, { corner(18), stroke(color or ACCENT, 3), new("UISizeConstraint", { MaxSize = maxSize }) })
	label({ Size = UDim2.new(1, -70, 0, 48), Position = UDim2.fromOffset(18, 4), Text = title, TextSize = 28, TextXAlignment = Enum.TextXAlignment.Left, TextColor3 = color or WHITE, Parent = frame })
	local close = button("✕", RED, UDim2.fromOffset(40, 40), frame, { Position = UDim2.new(1, -50, 0, 8), TextSize = 20 })
	close.Activated:Connect(closePanels)
	local body = new("Frame", { Size = UDim2.new(1, -24, 1, -66), Position = UDim2.fromOffset(12, 56), BackgroundTransparency = 1, Parent = frame })
	local p = { Frame = frame, Body = body }
	panels[name] = p
	return p
end

local function scroller(parent, size, position)
	return new("ScrollingFrame", {
		Size = size or UDim2.fromScale(1, 1),
		Position = position or UDim2.new(),
		BackgroundTransparency = 1,
		BorderSizePixel = 0,
		ScrollBarThickness = 8,
		CanvasSize = UDim2.new(),
		AutomaticCanvasSize = Enum.AutomaticSize.Y,
		ScrollingDirection = Enum.ScrollingDirection.Y,
		Parent = parent,
	})
end

-- Build panel ----------------------------------------------------------------------------------------------------
local build = makePanel("Build", "🔧 BUILD YOUR FIGHTER", Vector2.new(860, 600), Color3.fromRGB(255, 170, 60))
local buildTab = "Head"
local buildSummary = label({ Size = UDim2.new(1, 0, 0, 24), Text = "", TextSize = 16, TextXAlignment = Enum.TextXAlignment.Left, TextColor3 = Color3.fromRGB(255, 225, 180), TextTruncate = Enum.TextTruncate.AtEnd, Parent = build.Body })
local tabRow = new("Frame", { Size = UDim2.new(1, 0, 0, 38), Position = UDim2.fromOffset(0, 28), BackgroundTransparency = 1, Parent = build.Body }, {
	new("UIListLayout", { FillDirection = Enum.FillDirection.Horizontal, Padding = UDim.new(0, 6), SortOrder = Enum.SortOrder.LayoutOrder }),
})
local buildGrid = scroller(build.Body, UDim2.new(1, 0, 1, -74), UDim2.fromOffset(0, 74))
new("UIGridLayout", { CellSize = UDim2.fromOffset(158, 200), CellPadding = UDim2.fromOffset(8, 8), SortOrder = Enum.SortOrder.LayoutOrder, Parent = buildGrid })
local tabs = {
	{ "Head", "🧠 HEAD" },
	{ "Arms", "💪 ARMS" },
	{ "Legs", "🦿 LEGS" },
	{ "Paint", "🎨 PAINT" },
	{ "Title", "🏷️ TITLE" },
}
local tabButtons = {}
for i, tab in tabs do
	local b = button(tab[2], CARD, UDim2.fromOffset(112, 36), tabRow, { LayoutOrder = i, TextSize = 15 })
	tabButtons[tab[1]] = b
	b.Activated:Connect(function()
		buildTab = tab[1]
		build.Refresh()
	end)
end

local function card(parent, order, borderColor)
	return new("Frame", { BackgroundColor3 = CARD, LayoutOrder = order, Parent = parent }, { corner(12), stroke(borderColor, 2) })
end

local function moveStats(part)
	if part.Move then
		local m = part.Move
		local dmg = m.Hits and (m.Damage .. "% x" .. m.Hits) or (m.Damage .. "%")
		return m.Name .. " · " .. dmg .. " · " .. m.Cooldown .. "s"
	end
	local s = part.Stats
	return "Speed " .. s.Speed .. " · " .. (s.AirJumps + 1) .. " jumps · " .. (s.Weight < 1 and "Heavy" or (s.Weight > 1.05 and "Light" or "Medium"))
end

local function partCard(key, order)
	local part = Config.Parts[key]
	local rarity = Config.Rarities[part.Rarity]
	local c = card(buildGrid, order, rarity)
	label({ Size = UDim2.new(1, 0, 0, 46), Position = UDim2.fromOffset(0, 4), Text = part.Icon, TextSize = 38, Parent = c })
	label({ Size = UDim2.new(1, -10, 0, 22), Position = UDim2.fromOffset(5, 50), Text = part.Name, TextSize = 17, TextScaled = false, TextTruncate = Enum.TextTruncate.AtEnd, Parent = c })
	label({ Size = UDim2.new(1, -10, 0, 16), Position = UDim2.fromOffset(5, 72), Text = part.Rarity, TextSize = 13, TextColor3 = rarity, Parent = c })
	label({ Size = UDim2.new(1, -10, 0, 30), Position = UDim2.fromOffset(5, 88), Text = moveStats(part), TextSize = 12, TextWrapped = true, TextColor3 = Color3.fromRGB(200, 205, 255), Parent = c })
	label({ Size = UDim2.new(1, -10, 0, 40), Position = UDim2.fromOffset(5, 118), Text = part.Desc, TextSize = 12, TextWrapped = true, TextColor3 = Color3.fromRGB(210, 210, 225), TextYAlignment = Enum.TextYAlignment.Top, Parent = c })
	local equipped = state.Loadout[part.Slot] == key
	local owned = state.Owned[key]
	local text, color
	if equipped then
		text, color = "EQUIPPED", GRAY
	elseif owned then
		text, color = "EQUIP", GREEN
	elseif part.Price then
		text, color = "BUY 🪙" .. Format.Number(part.Price), state.Coins >= part.Price and GOLD:Lerp(Color3.new(0, 0, 0), 0.15) or Color3.fromRGB(150, 120, 60)
	else
		text, color = "🔒 " .. part.Source, Color3.fromRGB(70, 70, 90)
	end
	local b = button(text, color, UDim2.new(1, -12, 0, 32), c, { Position = UDim2.new(0, 6, 1, -38), TextSize = 13, TextWrapped = true })
	b.Activated:Connect(function()
		if equipped then
			return
		elseif owned then
			invoke(Remotes.Equip, part.Slot, key)
		elseif part.Price then
			invoke(Remotes.BuyPart, key)
		else
			toast(part.Name .. " comes from: " .. part.Source)
		end
	end)
end

local function paintCard(key, order)
	local paint = Config.Paints[key]
	local color = paint.Color or Color3.fromRGB(230, 230, 235)
	local c = card(buildGrid, order, color)
	new("Frame", { Size = UDim2.fromOffset(60, 60), Position = UDim2.new(0.5, -30, 0, 14), BackgroundColor3 = color, Parent = c }, { corner(30), stroke(WHITE, 2) })
	label({ Size = UDim2.new(1, -10, 0, 24), Position = UDim2.fromOffset(5, 82), Text = paint.Name, TextSize = 17, Parent = c })
	label({ Size = UDim2.new(1, -10, 0, 40), Position = UDim2.fromOffset(5, 108), Text = "Just for looks. From: " .. paint.Source, TextSize = 12, TextWrapped = true, TextColor3 = Color3.fromRGB(210, 210, 225), Parent = c })
	local text, bcolor
	if state.Paint == key then
		text, bcolor = "IN USE", GRAY
	elseif state.Paints[key] then
		text, bcolor = "USE", GREEN
	elseif paint.Price then
		text, bcolor = "BUY 🪙" .. Format.Number(paint.Price), GOLD:Lerp(Color3.new(0, 0, 0), 0.15)
	elseif paint.Product then
		text, bcolor = "R$ " .. Config.Products[paint.Product].Price, GREEN:Lerp(Color3.new(0, 0, 0), 0.1)
	elseif paint.Pass then
		text, bcolor = "👑 VIP", PURPLE
	else
		text, bcolor = "🔒 " .. paint.Source, Color3.fromRGB(70, 70, 90)
	end
	local b = button(text, bcolor, UDim2.new(1, -12, 0, 32), c, { Position = UDim2.new(0, 6, 1, -38), TextSize = 13, TextWrapped = true })
	b.Activated:Connect(function()
		if state.Paint == key then
			return
		elseif state.Paints[key] then
			invoke(Remotes.SetPaint, key)
		elseif paint.Product then
			buyProduct(paint.Product)
		elseif paint.Pass then
			buyPass(paint.Pass)
		elseif paint.Price then
			invoke(Remotes.BuyPaint, key)
		else
			toast(paint.Name .. " comes from: " .. paint.Source)
		end
	end)
end

build.Refresh = function()
	clear(buildGrid)
	for key, b in tabButtons do
		b.BackgroundColor3 = key == buildTab and ACCENT or CARD
	end
	local owned = 0
	for _ in state.Owned do
		owned += 1
	end
	local l = state.Loadout
	buildSummary.Text = "You: " .. Config.Parts[l.Head].Icon .. " " .. Config.Parts[l.Head].Name .. " + " .. Config.Parts[l.Arms].Icon .. " " .. Config.Parts[l.Arms].Name .. " + " .. Config.Parts[l.Legs].Icon .. " " .. Config.Parts[l.Legs].Name .. "   ·   Parts collected: " .. owned .. "/" .. Config.TotalParts
	if Config.PartOrder[buildTab] then
		for i, key in Config.PartOrder[buildTab] do
			partCard(key, i)
		end
	elseif buildTab == "Paint" then
		local keys = {}
		for key in Config.Paints do
			table.insert(keys, key)
		end
		table.sort(keys, function(a, b)
			return Config.Paints[a].Order < Config.Paints[b].Order
		end)
		for i, key in keys do
			paintCard(key, i)
		end
	else
		for i, title in state.Titles do
			local c = card(buildGrid, i, state.Title == title and GOLD or GRAY)
			label({ Size = UDim2.new(1, -10, 0, 90), Position = UDim2.fromOffset(5, 20), Text = "🏷️\n" .. title, TextSize = 18, TextWrapped = true, Parent = c })
			local b = button(state.Title == title and "WEARING" or "WEAR", state.Title == title and GRAY or GREEN, UDim2.new(1, -12, 0, 32), c, { Position = UDim2.new(0, 6, 1, -38) })
			b.Activated:Connect(function()
				invoke(Remotes.SetTitle, title)
			end)
		end
		local hint = card(buildGrid, 999, GRAY)
		label({ Size = UDim2.new(1, -10, 1, -10), Position = UDim2.fromOffset(5, 5), Text = "Earn more titles on the Star Road and in Story mode!", TextSize = 14, TextWrapped = true, TextColor3 = Color3.fromRGB(200, 200, 220), Parent = hint })
	end
end

-- Story panel ------------------------------------------------------------------------------------------------------
local storyPanel = makePanel("Story", "📖 STORY: THE SCRAPYARD SAGA", Vector2.new(760, 600), PURPLE)
local storyList = scroller(storyPanel.Body)
new("UIListLayout", { Padding = UDim.new(0, 8), SortOrder = Enum.SortOrder.LayoutOrder, Parent = storyList })
storyPanel.Refresh = function()
	clear(storyList)
	label({ Size = UDim2.new(1, -10, 0, 40), Text = "Dr. Junk stole every part in Mix City! Beat each boss to win their part.", TextSize = 16, TextWrapped = true, TextColor3 = Color3.fromRGB(220, 200, 255), LayoutOrder = 0, Parent = storyList })
	for i, chapter in Config.Chapters do
		local cleared = i <= state.StoryCleared
		local unlocked = i <= state.StoryCleared + 1
		local c = new("Frame", { Size = UDim2.new(1, -12, 0, 96), BackgroundColor3 = unlocked and CARD or Color3.fromRGB(32, 30, 50), LayoutOrder = i, Parent = storyList }, { corner(12), stroke(cleared and GREEN or (unlocked and PURPLE or GRAY), 2) })
		local reward = Config.Parts[chapter.Reward]
		label({ Size = UDim2.new(1, -170, 0, 28), Position = UDim2.fromOffset(14, 6), Text = "Chapter " .. i .. ": " .. chapter.Name, TextSize = 21, TextXAlignment = Enum.TextXAlignment.Left, Parent = c })
		label({ Size = UDim2.new(1, -170, 0, 22), Position = UDim2.fromOffset(14, 36), Text = "Boss: " .. chapter.Boss, TextSize = 15, TextXAlignment = Enum.TextXAlignment.Left, TextColor3 = Color3.fromRGB(255, 150, 150), Parent = c })
		label({ Size = UDim2.new(1, -170, 0, 22), Position = UDim2.fromOffset(14, 60), Text = (cleared and "Replay: +" .. Config.StoryReplayCoins .. " coins" or ("Reward: " .. reward.Icon .. " " .. reward.Name .. " + " .. chapter.Coins .. " coins" .. (chapter.Title and (" + title \"" .. chapter.Title .. "\"") or ""))), TextSize = 14, TextXAlignment = Enum.TextXAlignment.Left, TextColor3 = Config.Rarities[reward.Rarity], TextTruncate = Enum.TextTruncate.AtEnd, Parent = c })
		local text = cleared and "✅ REPLAY" or (unlocked and "▶ PLAY" or "🔒 LOCKED")
		local b = button(text, unlocked and (cleared and GREEN or PURPLE) or GRAY, UDim2.fromOffset(140, 50), c, { Position = UDim2.new(1, -152, 0.5, -25), TextSize = 18 })
		b.Activated:Connect(function()
			if not unlocked then
				toast("Beat Chapter " .. (state.StoryCleared + 1) .. " first!")
				return
			end
			closePanels()
			invoke(Remotes.StartStory, i)
		end)
	end
end

-- Star Road panel ----------------------------------------------------------------------------------------------------
local starPanel = makePanel("StarRoad", "⭐ STAR ROAD (FREE)", Vector2.new(860, 460), GOLD)
local starHeader = label({ Size = UDim2.new(1, -180, 0, 26), Text = "", TextSize = 18, TextXAlignment = Enum.TextXAlignment.Left, Parent = starPanel.Body })
local starBarBack = new("Frame", { Size = UDim2.new(1, -180, 0, 14), Position = UDim2.fromOffset(0, 30), BackgroundColor3 = CARD, Parent = starPanel.Body }, { corner(7) })
local starBarFill = new("Frame", { Size = UDim2.fromScale(0, 1), BackgroundColor3 = GOLD, Parent = starBarBack }, { corner(7) })
local boostButton = button("🌟 2x Star XP", PURPLE, UDim2.fromOffset(170, 44), starPanel.Body, { Position = UDim2.new(1, -170, 0, 0), TextSize = 16 })
boostButton.Activated:Connect(function()
	buyPass("StarBoost")
end)
label({ Size = UDim2.new(1, 0, 0, 20), Position = UDim2.fromOffset(0, 48), Text = "Rewards are given the moment you reach a tier. Star XP comes from matches, story fights, quests and daily rewards. No end date.", TextSize = 13, TextWrapped = true, TextXAlignment = Enum.TextXAlignment.Left, TextColor3 = Color3.fromRGB(220, 220, 240), Parent = starPanel.Body })
local starScroll = new("ScrollingFrame", {
	Size = UDim2.new(1, 0, 1, -80),
	Position = UDim2.fromOffset(0, 78),
	BackgroundTransparency = 1,
	BorderSizePixel = 0,
	ScrollBarThickness = 8,
	ScrollingDirection = Enum.ScrollingDirection.X,
	AutomaticCanvasSize = Enum.AutomaticSize.X,
	CanvasSize = UDim2.new(),
	Parent = starPanel.Body,
})
new("UIListLayout", { FillDirection = Enum.FillDirection.Horizontal, Padding = UDim.new(0, 8), SortOrder = Enum.SortOrder.LayoutOrder, Parent = starScroll })
local function rewardText(reward)
	local bits = {}
	if reward.Coins then
		table.insert(bits, "🪙 " .. reward.Coins)
	end
	if reward.Part then
		table.insert(bits, Config.Parts[reward.Part].Icon .. " " .. Config.Parts[reward.Part].Name)
	end
	if reward.Paint then
		table.insert(bits, "🎨 " .. Config.Paints[reward.Paint].Name .. " paint")
	end
	if reward.Title then
		table.insert(bits, "🏷️ \"" .. reward.Title .. "\"")
	end
	if reward.Revive then
		table.insert(bits, "💨 Second Wind")
	end
	return table.concat(bits, "\n")
end
starPanel.Refresh = function()
	clear(starScroll)
	local total = #Config.StarRoad
	if state.StarTier >= total then
		starHeader.Text = "Tier " .. total .. "/" .. total .. " · MAXED! Extra XP now gives bonus coins."
		starBarFill.Size = UDim2.fromScale(1, 1)
	else
		starHeader.Text = "Tier " .. state.StarTier .. "/" .. total .. " · " .. state.StarXP .. " / " .. state.StarNeed .. " XP to tier " .. (state.StarTier + 1)
		starBarFill.Size = UDim2.fromScale(math.clamp(state.StarXP / state.StarNeed, 0, 1), 1)
	end
	boostButton.Visible = not state.StarBoost and Config.GamePasses.StarBoost.Id ~= 0
	for tier, reward in Config.StarRoad do
		local done = tier <= state.StarTier
		local nextUp = tier == state.StarTier + 1
		local big = reward.Part ~= nil or reward.Paint ~= nil
		local c = new("Frame", { Size = UDim2.new(0, 120, 1, -14), BackgroundColor3 = done and Color3.fromRGB(80, 65, 25) or CARD, LayoutOrder = tier, Parent = starScroll }, { corner(12), stroke(done and GOLD or (nextUp and Color3.fromRGB(90, 230, 255) or (big and PURPLE or GRAY)), nextUp and 3 or 2) })
		label({ Size = UDim2.new(1, 0, 0, 30), Position = UDim2.fromOffset(0, 6), Text = tostring(tier), TextSize = 26, TextColor3 = done and GOLD or WHITE, Parent = c })
		label({ Size = UDim2.new(1, -10, 1, -80), Position = UDim2.fromOffset(5, 40), Text = rewardText(reward), TextSize = 14, TextWrapped = true, Parent = c })
		label({ Size = UDim2.new(1, 0, 0, 24), Position = UDim2.new(0, 0, 1, -30), Text = done and "✅ GOT IT" or (nextUp and "NEXT!" or "🔒"), TextSize = 15, TextColor3 = done and GREEN or (nextUp and Color3.fromRGB(90, 230, 255) or GRAY), Parent = c })
	end
	task.defer(function()
		local cardWidth = 128
		starScroll.CanvasPosition = Vector2.new(math.max(0, (state.StarTier - 2) * cardWidth), 0)
	end)
end

-- Quests panel ---------------------------------------------------------------------------------------------------------
local questPanel = makePanel("Quests", "📜 DAILY QUESTS", Vector2.new(640, 420), GREEN)
local questList = new("Frame", { Size = UDim2.fromScale(1, 1), BackgroundTransparency = 1, Parent = questPanel.Body }, {
	new("UIListLayout", { Padding = UDim.new(0, 8), SortOrder = Enum.SortOrder.LayoutOrder }),
})
questPanel.Refresh = function()
	clear(questList)
	label({ Size = UDim2.new(1, 0, 0, 24), Text = "3 new quests every day. Finish them for coins and Star XP!", TextSize = 15, TextColor3 = Color3.fromRGB(200, 255, 210), LayoutOrder = 0, Parent = questList })
	for i, q in state.Quests do
		local c = new("Frame", { Size = UDim2.new(1, 0, 0, 84), BackgroundColor3 = CARD, LayoutOrder = i, Parent = questList }, { corner(12), stroke(q.Claimed and GRAY or GREEN, 2) })
		label({ Size = UDim2.new(1, -170, 0, 26), Position = UDim2.fromOffset(12, 6), Text = q.Text, TextSize = 19, TextXAlignment = Enum.TextXAlignment.Left, Parent = c })
		label({ Size = UDim2.new(1, -170, 0, 20), Position = UDim2.fromOffset(12, 32), Text = "Reward: 🪙 " .. q.Coins .. " + ⭐ " .. q.XP .. " XP", TextSize = 14, TextXAlignment = Enum.TextXAlignment.Left, TextColor3 = GOLD, Parent = c })
		local back = new("Frame", { Size = UDim2.new(1, -180, 0, 12), Position = UDim2.fromOffset(12, 60), BackgroundColor3 = BG, Parent = c }, { corner(6) })
		new("Frame", { Size = UDim2.fromScale(math.clamp(q.Progress / q.Goal, 0, 1), 1), BackgroundColor3 = GREEN, Parent = back }, { corner(6) })
		label({ Size = UDim2.fromOffset(80, 16), Position = UDim2.new(1, -164, 0, 58), Text = math.floor(q.Progress) .. "/" .. q.Goal, TextSize = 13, Parent = c })
		local ready = q.Progress >= q.Goal and not q.Claimed
		local b = button(q.Claimed and "✅ DONE" or (ready and "CLAIM!" or "IN PROGRESS"), ready and GOLD or GRAY, UDim2.fromOffset(140, 44), c, { Position = UDim2.new(1, -150, 0.5, -22), TextSize = 16 })
		b.Activated:Connect(function()
			if ready then
				invoke(Remotes.ClaimQuest, i)
				sound(1.5, 0.5)
			end
		end)
	end
end

-- Shop panel -------------------------------------------------------------------------------------------------------------
local shopPanel = makePanel("Shop", "🛒 SHOP", Vector2.new(860, 600), GOLD)
label({ Size = UDim2.new(1, 0, 0, 22), Text = "Every item says exactly what you get. No random boxes, no timers.", TextSize = 15, TextColor3 = Color3.fromRGB(255, 235, 180), Parent = shopPanel.Body })
local shopGrid = scroller(shopPanel.Body, UDim2.new(1, 0, 1, -28), UDim2.fromOffset(0, 28))
new("UIGridLayout", { CellSize = UDim2.fromOffset(196, 210), CellPadding = UDim2.fromOffset(8, 8), SortOrder = Enum.SortOrder.LayoutOrder, Parent = shopGrid })
shopPanel.Refresh = function()
	clear(shopGrid)
	local order = 0
	local function shopCard(info, owned, onBuy, color)
		order += 1
		local c = card(shopGrid, order, color)
		label({ Size = UDim2.new(1, 0, 0, 50), Position = UDim2.fromOffset(0, 6), Text = info.Icon, TextSize = 40, Parent = c })
		label({ Size = UDim2.new(1, -10, 0, 24), Position = UDim2.fromOffset(5, 56), Text = info.Name, TextSize = 18, Parent = c })
		label({ Size = UDim2.new(1, -14, 0, 76), Position = UDim2.fromOffset(7, 82), Text = info.Desc, TextSize = 13, TextWrapped = true, TextYAlignment = Enum.TextYAlignment.Top, TextColor3 = Color3.fromRGB(215, 215, 235), Parent = c })
		local text, bcolor
		if owned then
			text, bcolor = "✅ OWNED", GRAY
		elseif info.Id == 0 then
			text, bcolor = "Not for sale yet", Color3.fromRGB(70, 70, 90)
		else
			text, bcolor = "R$ " .. info.Price, GREEN
		end
		local b = button(text, bcolor, UDim2.new(1, -14, 0, 38), c, { Position = UDim2.new(0, 7, 1, -44) })
		b.Activated:Connect(function()
			if not owned then
				onBuy()
			end
		end)
	end
	shopCard(Config.GamePasses.VIP, state.VIP, function()
		buyPass("VIP")
	end, GOLD)
	shopCard(Config.GamePasses.StarBoost, state.StarBoost, function()
		buyPass("StarBoost")
	end, Color3.fromRGB(255, 240, 120))
	for _, key in Config.ShopOrder do
		local info = Config.Products[key]
		local owned = (info.OneTime and state.StarterBought) or (info.Paint and state.Paints[info.Paint]) or false
		local desc = info
		if key == "SecondWind" and state.Revives > 0 then
			desc = table.clone(info)
			desc.Desc = info.Desc .. " You have " .. state.Revives .. " saved."
		end
		shopCard(desc, owned, function()
			buyProduct(key)
		end, key == "Starter" and GREEN or ACCENT)
	end
end

-- Help panel -------------------------------------------------------------------------------------------------------------
local helpPanel = makePanel("Help", "❓ HOW TO PLAY", Vector2.new(720, 600), ACCENT)
local helpScroll = scroller(helpPanel.Body)
new("UIListLayout", { Padding = UDim.new(0, 6), SortOrder = Enum.SortOrder.LayoutOrder, Parent = helpScroll })
do
	local ranks = {}
	for _, r in Config.Ranks do
		table.insert(ranks, r.Icon .. " " .. r.Name .. " (" .. r.Min .. "+)")
	end
	local lines = {
		"<b>1. MIX YOUR FIGHTER</b>\nYour <font color='#FFD23C'>HEAD</font> gives your special (Q). Your <font color='#FF6A6A'>ARMS</font> give your heavy attack (E). Your <font color='#6AD2FF'>LEGS</font> set your speed, jumps and weight. Every part works with every other part!",
		"<b>2. SMASH THEM OFF THE STAGE</b>\nHits add damage %. The higher someone's %, the farther they fly. Knock them past the glowing blast walls to take one of their 3 lives.",
		"<b>3. CONTROLS</b>\nA / D or the thumbstick: move · Space: jump (and air jumps) · Hold S: drop through platforms\nClick: Jab · E: Heavy · Q: Special · F: Dodge (you can't be hit while dodging) · R: use things in the lobby",
		"<b>4. BATTLE</b>\nStand on the red pad for 1v1 Ranked, or the blue pad for Free-for-All (up to 4). Waiting alone? A bot joins after a few seconds (bot matches give less and no trophies).",
		"<b>5. GET NEW PARTS</b>\nBuy them with coins at the Part Forge, win them from Story bosses, or reach them on the free Star Road.",
		"<b>6. COME BACK DAILY</b>\nDaily chest streak (7-day cycle), 3 new quests each day, and win streaks give up to +50% coins.",
		"<b>RANKS</b> (1v1 vs real players): win +" .. Config.TrophyWin .. " 🏆, lose -" .. Config.TrophyLoss .. "\n" .. table.concat(ranks, " · "),
	}
	for i, text in lines do
		label({ Size = UDim2.new(1, -14, 0, 0), AutomaticSize = Enum.AutomaticSize.Y, Text = text, RichText = true, TextSize = 16, TextWrapped = true, TextXAlignment = Enum.TextXAlignment.Left, LayoutOrder = i, Parent = helpScroll })
	end
end

-- Daily panel -------------------------------------------------------------------------------------------------------------
local dailyPanel = makePanel("Daily", "📅 DAILY REWARD", Vector2.new(760, 360), Color3.fromRGB(255, 200, 80))
local dailyRow = new("Frame", { Size = UDim2.new(1, 0, 0, 150), AnchorPoint = Vector2.new(0.5, 0), Position = UDim2.new(0.5, 0, 0, 30), BackgroundTransparency = 1, Parent = dailyPanel.Body }, {
	new("UIListLayout", { FillDirection = Enum.FillDirection.Horizontal, Padding = UDim.new(0, 6), SortOrder = Enum.SortOrder.LayoutOrder, HorizontalAlignment = Enum.HorizontalAlignment.Center }),
})
local dailyInfo = label({ Size = UDim2.new(1, 0, 0, 24), Text = "", TextSize = 16, TextColor3 = Color3.fromRGB(255, 230, 180), Parent = dailyPanel.Body })
local claimButton = button("CLAIM!", GOLD, UDim2.fromOffset(220, 52), dailyPanel.Body, { AnchorPoint = Vector2.new(0.5, 0), Position = UDim2.new(0.5, 0, 0, 196), TextSize = 22 })
claimButton.Activated:Connect(function()
	if state and state.CanClaimDaily then
		invoke(Remotes.ClaimDaily)
		closePanels()
	else
		closePanels()
	end
end)
dailyPanel.Refresh = function()
	clear(dailyRow)
	local today = state.CanClaimDaily and state.DailyNext or state.DailyStreak
	local index = math.max(1, (today - 1) % #Config.Daily + 1)
	for i, reward in Config.Daily do
		local isToday = i == index
		local c = new("Frame", { Size = UDim2.fromOffset(92, 140), BackgroundColor3 = isToday and Color3.fromRGB(90, 70, 20) or CARD, LayoutOrder = i, Parent = dailyRow }, { corner(12), stroke(isToday and GOLD or GRAY, isToday and 3 or 2) })
		label({ Size = UDim2.new(1, 0, 0, 26), Position = UDim2.fromOffset(0, 6), Text = "Day " .. i, TextSize = 18, Parent = c })
		label({ Size = UDim2.new(1, 0, 0, 40), Position = UDim2.fromOffset(0, 38), Text = i == 7 and "💰" or "🪙", TextSize = 32, Parent = c })
		label({ Size = UDim2.new(1, -6, 0, 50), Position = UDim2.fromOffset(3, 82), Text = reward.Coins .. " coins" .. (reward.XP and ("\n+" .. reward.XP .. " XP") or ""), TextSize = 14, TextWrapped = true, Parent = c })
	end
	if state.CanClaimDaily then
		dailyInfo.Text = "Day " .. state.DailyNext .. " of your streak! Missing a day starts you back at Day 1." .. (state.VIP and " (VIP: +50% coins)" or "")
		claimButton.Text = "CLAIM!"
		claimButton.BackgroundColor3 = GOLD
	else
		dailyInfo.Text = "Claimed! Your streak: " .. state.DailyStreak .. " days. Come back tomorrow."
		claimButton.Text = "OK"
		claimButton.BackgroundColor3 = GRAY
	end
end

-- Left menu + Fight button ---------------------------------------------------------------------------------------------------
local menu = new("Frame", {
	Size = UDim2.fromOffset(74, 0),
	AutomaticSize = Enum.AutomaticSize.Y,
	AnchorPoint = Vector2.new(0, 0.5),
	Position = UDim2.new(0, 8, 0.5, 0),
	BackgroundTransparency = 1,
	Parent = gui,
}, { new("UIListLayout", { Padding = UDim.new(0, 6), SortOrder = Enum.SortOrder.LayoutOrder }) })
local dots = {}
local menuItems = {
	{ "Build", "🔧", "Build", Color3.fromRGB(255, 160, 50) },
	{ "Story", "📖", "Story", PURPLE },
	{ "StarRoad", "⭐", "Stars", Color3.fromRGB(230, 180, 30) },
	{ "Quests", "📜", "Quests", GREEN },
	{ "Shop", "🛒", "Shop", PINK },
	{ "Daily", "📅", "Daily", Color3.fromRGB(255, 120, 60) },
	{ "Help", "❓", "Help", ACCENT },
}
for i, item in menuItems do
	local b = button(item[2] .. "\n" .. item[3], item[4], UDim2.fromOffset(70, 58), menu, { LayoutOrder = i, TextSize = 15 })
	b.Activated:Connect(function()
		if openName == item[1] then
			closePanels()
		else
			openPanel(item[1])
		end
	end)
	dots[item[1]] = new("Frame", { Size = UDim2.fromOffset(16, 16), Position = UDim2.new(1, -12, 0, -4), BackgroundColor3 = RED, Visible = false, Parent = b }, { corner(8), stroke(WHITE, 2) })
end

-- Shrink the tall menu and the wide Daily row on small (phone) screens so nothing is cut off.
local menuScale = new("UIScale", { Parent = menu })
local dailyScale = new("UIScale", { Parent = dailyRow })
local function fitScreen()
	local camera = Workspace.CurrentCamera
	if not camera then
		return
	end
	local vp = camera.ViewportSize
	menuScale.Scale = math.clamp((vp.Y - 150) / 450, 0.5, 1)
	dailyScale.Scale = math.clamp((math.min(vp.X * 0.94, 760) - 24) / 690, 0.4, 1)
end
fitScreen()
Workspace:GetPropertyChangedSignal("CurrentCamera"):Connect(fitScreen)
if Workspace.CurrentCamera then
	Workspace.CurrentCamera:GetPropertyChangedSignal("ViewportSize"):Connect(fitScreen)
end

local fightButton = button("⚔️ FIGHT!", RED, UDim2.fromOffset(210, 62), gui, { AnchorPoint = Vector2.new(0.5, 1), Position = UDim2.new(0.5, 0, 1, -16), TextSize = 28 })
local fightChoices = new("Frame", { Size = UDim2.fromOffset(500, 70), AnchorPoint = Vector2.new(0.5, 1), Position = UDim2.new(0.5, 0, 1, -86), BackgroundTransparency = 1, Visible = false, Parent = gui }, {
	new("UIListLayout", { FillDirection = Enum.FillDirection.Horizontal, Padding = UDim.new(0, 8), HorizontalAlignment = Enum.HorizontalAlignment.Center, SortOrder = Enum.SortOrder.LayoutOrder }),
})
local function choice(text, color, order, fn)
	local b = button(text, color, UDim2.fromOffset(158, 62), fightChoices, { LayoutOrder = order, TextSize = 16, TextWrapped = true })
	b.Activated:Connect(function()
		fightChoices.Visible = false
		fn()
	end)
end
choice("🏆 1v1 RANKED", RED, 1, function()
	Remotes.Queue:FireServer("Ranked")
end)
choice("💥 FREE-FOR-ALL\n(up to 4)", Color3.fromRGB(60, 140, 255), 2, function()
	Remotes.Queue:FireServer("FFA")
end)
choice("📖 STORY", PURPLE, 3, function()
	openPanel("Story")
end)
fightButton.Activated:Connect(function()
	fightChoices.Visible = not fightChoices.Visible
end)

local queueBar = new("Frame", { Size = UDim2.fromOffset(420, 56), AnchorPoint = Vector2.new(0.5, 1), Position = UDim2.new(0.5, 0, 1, -16), BackgroundColor3 = BG, Visible = false, Parent = gui }, { corner(14), stroke(GOLD, 2) })
local queueText = label({ Size = UDim2.new(1, -130, 1, 0), Position = UDim2.fromOffset(12, 0), Text = "", TextSize = 17, TextXAlignment = Enum.TextXAlignment.Left, Parent = queueBar })
local leaveButton = button("Leave", RED, UDim2.fromOffset(100, 40), queueBar, { Position = UDim2.new(1, -110, 0.5, -20) })
leaveButton.Activated:Connect(function()
	Remotes.Queue:FireServer(nil)
end)

-- Pop-ups: celebrate, offer, revive, results ---------------------------------------------------------------------------------
local function popupFrame(color, height)
	return new("Frame", {
		Size = UDim2.fromOffset(440, height),
		AnchorPoint = Vector2.new(0.5, 0.5),
		Position = UDim2.fromScale(0.5, 0.45),
		BackgroundColor3 = BG,
		Visible = false,
		ZIndex = 30,
		Parent = gui,
	}, { corner(18), stroke(color, 3), new("UISizeConstraint", { MaxSize = Vector2.new(440, height) }) })
end

local celebrate = popupFrame(GOLD, 280)
celebrate.Size = UDim2.new(0.92, 0, 0, 280)
local celIcon = label({ Size = UDim2.new(1, 0, 0, 70), Position = UDim2.fromOffset(0, 10), Text = "", TextSize = 56, Parent = celebrate })
local celTitle = label({ Size = UDim2.new(1, -20, 0, 40), Position = UDim2.fromOffset(10, 82), Text = "", TextSize = 30, TextColor3 = GOLD, Parent = celebrate })
local celText = label({ Size = UDim2.new(1, -30, 0, 80), Position = UDim2.fromOffset(15, 124), Text = "", TextSize = 17, TextWrapped = true, Parent = celebrate })
local celOk = button("AWESOME!", GREEN, UDim2.fromOffset(180, 46), celebrate, { AnchorPoint = Vector2.new(0.5, 1), Position = UDim2.new(0.5, 0, 1, -14), TextSize = 20 })
local celQueue = {}
local celShowing = false
local function confetti()
	for _ = 1, 26 do
		local piece = new("Frame", {
			Size = UDim2.fromOffset(10, 14),
			Position = UDim2.new(math.random(), 0, 0, -20),
			BackgroundColor3 = Color3.fromHSV(math.random(), 0.8, 1),
			Rotation = math.random(0, 360),
			ZIndex = 35,
			Parent = gui,
		})
		TweenService:Create(piece, TweenInfo.new(1.4 + math.random(), Enum.EasingStyle.Quad, Enum.EasingDirection.In), { Position = UDim2.fromScale(piece.Position.X.Scale + (math.random() - 0.5) * 0.2, 1.1), Rotation = piece.Rotation + 360 }):Play()
		Debris:AddItem(piece, 3)
	end
end
local function showNextCelebration()
	local item = table.remove(celQueue, 1)
	if not item then
		celShowing = false
		celebrate.Visible = false
		return
	end
	celShowing = true
	celIcon.Text = item.Icon or "🎉"
	celTitle.Text = item.Title or ""
	celText.Text = item.Text or ""
	celebrate.Visible = true
	confetti()
	sound(1.6, 0.6)
	local token = item
	task.delay(6, function()
		if celShowing and celIcon.Text == (token.Icon or "🎉") and celTitle.Text == (token.Title or "") then
			showNextCelebration()
		end
	end)
end
celOk.Activated:Connect(showNextCelebration)
local function celebrateMsg(msg)
	table.insert(celQueue, msg)
	if not celShowing then
		showNextCelebration()
	end
end

local offer = popupFrame(GREEN, 220)
offer.Size = UDim2.new(0.92, 0, 0, 220)
local offerText = label({ Size = UDim2.new(1, -30, 0, 100), Position = UDim2.fromOffset(15, 16), Text = "", TextSize = 18, TextWrapped = true, Parent = offer })
local offerBuy = button("", GREEN, UDim2.fromOffset(180, 48), offer, { AnchorPoint = Vector2.new(1, 1), Position = UDim2.new(0.5, -6, 1, -16) })
local offerNo = button("No thanks", GRAY, UDim2.fromOffset(150, 48), offer, { AnchorPoint = Vector2.new(0, 1), Position = UDim2.new(0.5, 6, 1, -16) })
local offerData = nil
offerBuy.Activated:Connect(function()
	offer.Visible = false
	if offerData then
		if offerData.Kind == "Pass" then
			buyPass(offerData.Key)
		else
			buyProduct(offerData.Key)
		end
	end
end)
offerNo.Activated:Connect(function()
	offer.Visible = false
end)

local revive = popupFrame(Color3.fromRGB(110, 200, 255), 240)
revive.Size = UDim2.new(0.92, 0, 0, 240)
local reviveText = label({ Size = UDim2.new(1, -30, 0, 120), Position = UDim2.fromOffset(15, 14), Text = "", TextSize = 18, TextWrapped = true, Parent = revive })
local reviveBuy = button("💨 Second Wind (R$ " .. Config.Products.SecondWind.Price .. ")", Color3.fromRGB(60, 160, 230), UDim2.fromOffset(240, 48), revive, { AnchorPoint = Vector2.new(1, 1), Position = UDim2.new(0.5, 40, 1, -16), TextSize = 16 })
local reviveNo = button("No thanks", GRAY, UDim2.fromOffset(120, 48), revive, { AnchorPoint = Vector2.new(0, 1), Position = UDim2.new(0.5, 48, 1, -16) })
reviveBuy.Activated:Connect(function()
	buyProduct("SecondWind")
end)
reviveNo.Activated:Connect(function()
	Remotes.RequestState:FireServer("DeclineRevive")
	revive.Visible = false
end)

local results = popupFrame(GOLD, 330)
results.Size = UDim2.new(0.92, 0, 0, 330)
local resTitle = label({ Size = UDim2.new(1, -20, 0, 56), Position = UDim2.fromOffset(10, 10), Text = "", TextSize = 42, Parent = results })
local resSub = label({ Size = UDim2.new(1, -20, 0, 24), Position = UDim2.fromOffset(10, 66), Text = "", TextSize = 17, TextColor3 = Color3.fromRGB(220, 220, 240), Parent = results })
local resLines = label({ Size = UDim2.new(1, -40, 0, 170), Position = UDim2.fromOffset(20, 96), Text = "", TextSize = 19, RichText = true, TextWrapped = true, TextYAlignment = Enum.TextYAlignment.Top, Parent = results })
local resOk = button("OK", GREEN, UDim2.fromOffset(160, 44), results, { AnchorPoint = Vector2.new(0.5, 1), Position = UDim2.new(0.5, 0, 1, -14), TextSize = 20 })
resOk.Activated:Connect(function()
	results.Visible = false
end)
local resToken = 0
local function showResults(msg)
	resToken += 1
	local token = resToken
	local lines = {}
	if msg.Story then
		resTitle.Text = msg.Won and "CHAPTER CLEARED!" or "DEFEATED"
		resTitle.TextColor3 = msg.Won and GOLD or RED
		resSub.Text = "Chapter " .. msg.Chapter .. ": " .. msg.ChapterName
		if msg.Won then
			table.insert(lines, "🪙 +" .. Format.Number(msg.Coins) .. " coins")
			table.insert(lines, "⭐ +" .. msg.XP .. " Star XP")
			if msg.Part then
				local part = Config.Parts[msg.Part]
				table.insert(lines, part.Icon .. " <font color='#FFD23C'>NEW PART: " .. part.Name .. "</font>")
			end
		else
			table.insert(lines, "No worries! Retry the chapter anytime from the Story menu.")
			table.insert(lines, "Tip: try a different part combo in the Build menu.")
		end
	else
		if msg.Won then
			resTitle.Text = "VICTORY!"
			resTitle.TextColor3 = GOLD
		elseif msg.Of > 2 then
			resTitle.Text = "#" .. msg.Place .. " of " .. msg.Of
			resTitle.TextColor3 = msg.Place == 2 and Color3.fromRGB(200, 210, 230) or WHITE
		else
			resTitle.Text = "DEFEAT"
			resTitle.TextColor3 = RED
		end
		resSub.Text = (msg.Ranked and "1v1 Ranked" or "Casual") .. (msg.Bots and " · vs bots (60% rewards, no trophies)" or "")
		table.insert(lines, "🪙 +" .. Format.Number(msg.Coins) .. " coins" .. ((msg.StreakBonus or 0) > 0 and (" (🔥 +" .. math.floor(msg.StreakBonus * 100 + 0.5) .. "% streak bonus)") or ""))
		table.insert(lines, "⭐ +" .. msg.XP .. " Star XP")
		table.insert(lines, "💥 KOs: " .. msg.KOs)
		if msg.Ranked then
			local delta = msg.Trophies
			table.insert(lines, (delta >= 0 and "<font color='#6CFF9A'>🏆 +" .. delta or "<font color='#FF7A7A'>🏆 " .. delta) .. " trophies</font> · " .. msg.Rank)
		end
		if msg.Won and msg.Streak >= 2 then
			table.insert(lines, "🔥 " .. msg.Streak .. " wins in a row!")
		end
	end
	resLines.Text = table.concat(lines, "\n")
	results.Visible = true
	sound(msg.Won and 1.6 or 0.8, 0.6)
	if msg.Won then
		confetti()
	end
	task.delay(7, function()
		if resToken == token then
			results.Visible = false
		end
	end)
end

-- Story dialogue -----------------------------------------------------------------------------------------------------
local letterTop = new("Frame", { Size = UDim2.new(1, 0, 0, 60), Position = UDim2.fromOffset(0, -60), BackgroundColor3 = Color3.new(0, 0, 0), BorderSizePixel = 0, Visible = false, ZIndex = 20, Parent = gui })
local dialogueBox = new("TextButton", {
	Size = UDim2.new(0.9, 0, 0, 160),
	AnchorPoint = Vector2.new(0.5, 1),
	Position = UDim2.new(0.5, 0, 1, -20),
	BackgroundColor3 = BG,
	BackgroundTransparency = 0.05,
	Text = "",
	AutoButtonColor = false,
	Visible = false,
	ZIndex = 21,
	Parent = gui,
}, { corner(18), stroke(WHITE, 3), new("UISizeConstraint", { MaxSize = Vector2.new(820, 160) }) })
local portrait = label({ Size = UDim2.fromOffset(110, 110), Position = UDim2.fromOffset(18, 24), Text = "", TextSize = 64, BackgroundTransparency = 0, BackgroundColor3 = CARD, ZIndex = 22, Parent = dialogueBox })
corner(55).Parent = portrait
local portraitStroke = stroke(WHITE, 4)
portraitStroke.Parent = portrait
local speakerName = label({ Size = UDim2.new(1, -170, 0, 30), Position = UDim2.fromOffset(146, 14), Text = "", TextSize = 24, TextXAlignment = Enum.TextXAlignment.Left, ZIndex = 22, Parent = dialogueBox })
local speechText = label({ Size = UDim2.new(1, -170, 0, 90), Position = UDim2.fromOffset(146, 46), Text = "", TextSize = 20, TextWrapped = true, TextXAlignment = Enum.TextXAlignment.Left, TextYAlignment = Enum.TextYAlignment.Top, ZIndex = 22, Parent = dialogueBox })
label({ Size = UDim2.fromOffset(240, 18), AnchorPoint = Vector2.new(1, 1), Position = UDim2.new(1, -16, 1, -8), Text = "Click / tap / Space to continue ▶", TextSize = 13, TextColor3 = Color3.fromRGB(180, 180, 210), TextXAlignment = Enum.TextXAlignment.Right, ZIndex = 22, Parent = dialogueBox })
local skipButton = button("Skip ⏭", GRAY, UDim2.fromOffset(90, 34), gui, { AnchorPoint = Vector2.new(1, 0), Position = UDim2.new(1, -12, 0, 70), Visible = false, ZIndex = 23 })

local dialogueLines, dialogueIndex = nil, 0
local typing = false
local typeToken = 0

local function finishDialogue()
	dialogueLines = nil
	dialogueBox.Visible = false
	letterTop.Visible = false
	skipButton.Visible = false
	Remotes.DialogueDone:FireServer()
end

local function showLine()
	local line = dialogueLines[dialogueIndex]
	local speaker = Config.Speakers[line.Speaker] or { Name = line.Speaker, Icon = "💬", Color = WHITE }
	local name = speaker.Name
	if line.Speaker == "You" then
		name = player.DisplayName
	end
	portrait.Text = speaker.Icon
	portraitStroke.Color = speaker.Color
	speakerName.Text = name
	speakerName.TextColor3 = speaker.Color
	speechText.Text = line.Text
	speechText.MaxVisibleGraphemes = 0
	typing = true
	typeToken += 1
	local token = typeToken
	sound(1.3, 0.25)
	task.spawn(function()
		local total = utf8.len(line.Text) or #line.Text
		local shown = 0
		while shown < total and typeToken == token do
			shown += 2
			speechText.MaxVisibleGraphemes = shown
			task.wait(1 / 45)
		end
		if typeToken == token then
			speechText.MaxVisibleGraphemes = -1
			typing = false
		end
	end)
end

local function advance()
	if not dialogueLines then
		return
	end
	if typing then
		typeToken += 1
		typing = false
		speechText.MaxVisibleGraphemes = -1
		return
	end
	dialogueIndex += 1
	if dialogueIndex > #dialogueLines then
		finishDialogue()
	else
		showLine()
	end
end

dialogueBox.Activated:Connect(advance)
skipButton.Activated:Connect(function()
	if dialogueLines then
		typeToken += 1
		finishDialogue()
	end
end)
UserInputService.InputBegan:Connect(function(input, processed)
	if processed or not dialogueLines then
		return
	end
	local key = input.KeyCode
	if key == Enum.KeyCode.Space or key == Enum.KeyCode.Return or key == Enum.KeyCode.R or key == Enum.KeyCode.ButtonA then
		advance()
	end
end)

Remotes.Dialogue.OnClientEvent:Connect(function(payload)
	closePanels()
	dialogueLines = payload.Lines
	dialogueIndex = 1
	if #dialogueLines == 0 then
		finishDialogue()
		return
	end
	dialogueBox.Visible = true
	letterTop.Visible = true
	letterTop.Position = UDim2.fromOffset(0, -60)
	skipButton.Visible = true
	showLine()
end)

-- Fight HUD -----------------------------------------------------------------------------------------------------------
local hud = new("Frame", { Size = UDim2.fromScale(1, 1), BackgroundTransparency = 1, Visible = false, Parent = gui })
local timerLabel = label({ Size = UDim2.fromOffset(160, 44), AnchorPoint = Vector2.new(0.5, 0), Position = UDim2.new(0.5, 0, 0, 6), Text = "", TextSize = 34, TextStrokeTransparency = 0.2, Parent = hud })
local bannerLabel = label({ Size = UDim2.fromOffset(600, 30), AnchorPoint = Vector2.new(0.5, 0), Position = UDim2.new(0.5, 0, 0, 50), Text = "", TextSize = 22, TextColor3 = GOLD, TextStrokeTransparency = 0.2, Parent = hud })
local bigLabel = label({ Size = UDim2.fromOffset(600, 140), AnchorPoint = Vector2.new(0.5, 0.5), Position = UDim2.fromScale(0.5, 0.4), Text = "", TextSize = 110, TextStrokeTransparency = 0, TextColor3 = GOLD, Parent = hud })
local splash = label({ Size = UDim2.fromOffset(700, 120), AnchorPoint = Vector2.new(0.5, 0.5), Position = UDim2.fromScale(0.5, 0.32), Text = "", TextSize = 90, TextStrokeTransparency = 0, TextTransparency = 1, TextStrokeColor3 = Color3.new(0, 0, 0), Parent = hud })
local cardsRow = new("Frame", { Size = UDim2.new(1, -20, 0, 96), AnchorPoint = Vector2.new(0.5, 1), Position = UDim2.new(0.5, 0, 1, -10), BackgroundTransparency = 1, Parent = hud }, {
	new("UIListLayout", { FillDirection = Enum.FillDirection.Horizontal, Padding = UDim.new(0, 10), HorizontalAlignment = Enum.HorizontalAlignment.Center, SortOrder = Enum.SortOrder.LayoutOrder }),
})
local hint = label({ Size = UDim2.fromOffset(700, 20), AnchorPoint = Vector2.new(0.5, 1), Position = UDim2.new(0.5, 0, 1, -112), Text = "Click jab · E heavy · Q special · F dodge · Space jump · S drop", TextSize = 14, TextColor3 = Color3.fromRGB(220, 220, 240), TextStrokeTransparency = 0.4, Parent = hud })
local cards = {} -- { Model, Percent, Stocks, Frame }

local splashToken = 0
local function showSplash(text, color)
	splashToken += 1
	local token = splashToken
	splash.Text = text
	splash.TextColor3 = color or WHITE
	splash.TextTransparency = 0
	splash.TextStrokeTransparency = 0
	splash.Size = UDim2.fromOffset(900, 160)
	TweenService:Create(splash, TweenInfo.new(0.25, Enum.EasingStyle.Back), { Size = UDim2.fromOffset(700, 120) }):Play()
	task.delay(1.1, function()
		if splashToken == token then
			TweenService:Create(splash, TweenInfo.new(0.4), { TextTransparency = 1, TextStrokeTransparency = 1 }):Play()
		end
	end)
end

local function rebuildCards()
	clear(cardsRow)
	cards = {}
	if not match then
		return
	end
	for i, f in match.Fighters do
		if f.Out and not f.Hero then
			continue -- beaten bots/minions drop off the bar so it never runs off-screen
		end
		local isMe = f.Model ~= nil and f.Model == player.Character
		local color = isMe and GREEN or (f.Boss and RED or (f.Hero and ACCENT or GRAY))
		local frame = new("Frame", { Size = UDim2.fromOffset(f.Boss and 200 or 150, 90), BackgroundColor3 = BG, BackgroundTransparency = f.Out and 0.6 or 0.1, LayoutOrder = i, Parent = cardsRow }, { corner(12), stroke(color, isMe and 3 or 2) })
		label({ Size = UDim2.new(1, -10, 0, 20), Position = UDim2.fromOffset(5, 4), Text = (isMe and "YOU" or f.Name), TextSize = 15, TextColor3 = color:Lerp(WHITE, 0.4), TextTruncate = Enum.TextTruncate.AtEnd, Parent = frame })
		local percent = label({ Size = UDim2.new(1, 0, 0, 44), Position = UDim2.fromOffset(0, 22), Text = "0%", TextSize = 40, TextStrokeTransparency = 0.3, Parent = frame })
		local stocks = string.rep("●", math.max(0, f.Stocks)) .. string.rep("○", math.max(0, (f.MaxStocks or 3) - f.Stocks))
		label({ Size = UDim2.new(1, 0, 0, 20), Position = UDim2.new(0, 0, 1, -24), Text = f.Out and "OUT" or stocks, TextSize = 18, TextColor3 = f.Out and RED or GOLD, Parent = frame })
		table.insert(cards, { Model = f.Model, Percent = percent, Out = f.Out })
	end
end

local function percentColor(damage)
	local t = math.clamp(damage / 150, 0, 1)
	if t < 0.5 then
		return WHITE:Lerp(Color3.fromRGB(255, 200, 60), t * 2)
	end
	return Color3.fromRGB(255, 200, 60):Lerp(Color3.fromRGB(230, 30, 40), (t - 0.5) * 2)
end

RunService.RenderStepped:Connect(function()
	if match then
		for _, c in cards do
			if c.Model and c.Model.Parent and not c.Out then
				local damage = c.Model:GetAttribute("Damage") or 0
				c.Percent.Text = math.floor(damage) .. "%"
				c.Percent.TextColor3 = percentColor(damage)
			end
		end
		local left = (match.EndsAt or 0) - serverNow()
		if match.Phase == "Countdown" then
			bigLabel.Text = left > 0 and tostring(math.ceil(left)) or ""
			timerLabel.Text = ""
		elseif match.Phase == "Fight" then
			timerLabel.Text = match.Kind == "Match" and Format.Time(left) or ""
		else
			timerLabel.Text = ""
		end
	end
	if queueMode then
		queueText.Text = "In " .. (queueMode == "Ranked" and "1v1 Ranked" or "Free-for-All") .. " queue · " .. Format.Time(serverNow() - queueSince)
	end
end)

local function refreshVisibility()
	local inFight = match ~= nil
	hud.Visible = inFight
	menu.Visible = not inFight
	fightButton.Visible = not inFight and queueMode == nil
	queueBar.Visible = not inFight and queueMode ~= nil
	if inFight then
		fightChoices.Visible = false
	end
	topBar.Visible = not inFight
	hint.Visible = inFight and (match.Kind == "Story" or (state ~= nil and state.Wins < 3))
end

-- Top bar + dots refresh -----------------------------------------------------------------------------------------------
local firstState = true
local function refresh()
	if not state then
		return
	end
	coinText.Text = "🪙 " .. Format.Number(state.Coins)
	local total = #Config.StarRoad
	starText.Text = "⭐ Tier " .. state.StarTier .. (state.StarTier >= total and " MAX" or "")
	starBar.Size = UDim2.new(state.StarTier >= total and 1 or math.clamp(state.StarXP / state.StarNeed, 0, 1), -28, 0, 4)
	local rank = Config.RankFor(state.Trophies)
	rankText.Text = rank.Icon .. " " .. rank.Name .. " " .. state.Trophies
	rankText.TextColor3 = rank.Color
	streakText.Text = "🔥 " .. state.WinStreak .. "  📅 " .. state.DailyStreak
	savingOff.Visible = state.SavingOff and not match
	local questReady = false
	for _, q in state.Quests do
		if q.Progress >= q.Goal and not q.Claimed then
			questReady = true
		end
	end
	dots.Quests.Visible = questReady
	dots.Daily.Visible = state.CanClaimDaily
	dots.Story.Visible = state.StoryCleared < #Config.Chapters
	if openName and panels[openName].Refresh then
		panels[openName].Refresh()
	end
	if firstState then
		firstState = false
		task.delay(1, function()
			while player:GetAttribute("IntroPlaying") do
				task.wait(0.2) -- let the intro finish first
			end
			if match then
				return
			end
			if not state.SeenHelp then
				openPanel("Help")
				Remotes.RequestState:FireServer("HelpSeen")
			elseif state.CanClaimDaily then
				openPanel("Daily")
			end
		end)
	end
end

-- Remote handlers ---------------------------------------------------------------------------------------------------------
Remotes.State.OnClientEvent:Connect(function(newState)
	state = newState
	refresh()
	refreshVisibility()
end)

Remotes.Match.OnClientEvent:Connect(function(payload)
	local wasIn = match ~= nil
	local oldPhase = match and match.Phase
	match = payload.Phase ~= "None" and payload or nil
	if match and not wasIn then
		closePanels()
		bigLabel.Text = ""
	end
	if match and match.Phase == "Fight" and oldPhase ~= "Fight" then
		showSplash(match.Kind == "Story" and (match.Banner or "FIGHT!") or "FIGHT!", GOLD)
	end
	savingOff.Visible = (state and state.SavingOff and not match) or false
	if not match then
		bigLabel.Text = ""
		revive.Visible = false
		if dialogueLines then
			finishDialogue()
		end
	end
	bannerLabel.Text = match and (match.Banner or (match.Ranked and "1v1 RANKED · " .. match.Arena or (match.Arena or ""))) or ""
	rebuildCards()
	refreshVisibility()
end)

Remotes.Notify.OnClientEvent:Connect(function(msg)
	local t = msg.Type
	if t == "Toast" then
		toast(msg.Text, msg.Color)
	elseif t == "Feed" then
		feedLine(msg.Text, msg.Color)
	elseif t == "Celebrate" then
		celebrateMsg(msg)
	elseif t == "Open" then
		openPanel(msg.Panel)
	elseif t == "Offer" then
		if match then
			return
		end
		offerData = msg
		local info = msg.Kind == "Pass" and Config.GamePasses[msg.Key] or Config.Products[msg.Key]
		offerText.Text = msg.Text
		offerBuy.Text = "Get it (R$ " .. info.Price .. ")"
		offer.Visible = true
	elseif t == "Queue" then
		queueMode = msg.Mode
		queueSince = msg.Since or serverNow()
		refreshVisibility()
		if msg.Mode then
			sound(1.4, 0.4)
		end
	elseif t == "KO" then
		local me = msg.Model == player.Character
		showSplash(me and "KO'd!" or "KO!", me and RED or GOLD)
		feedLine("💥 " .. msg.Name .. " got KO'd!" .. ((msg.Left or 0) > 0 and (" (" .. msg.Left .. " lives left)") or " OUT!"), Color3.fromRGB(255, 170, 90))
	elseif t == "Winner" then
		showSplash("GAME!", GOLD)
	elseif t == "Results" then
		task.delay(msg.Story and 0.3 or 1.2, function()
			showResults(msg)
		end)
	elseif t == "Revive" then
		reviveText.Text = "Out of lives!\nSecond Wind refills your 3 lives right here.\nOr retry the chapter for free anytime from the Story menu."
		revive.Visible = true
	elseif t == "ReviveClose" then
		revive.Visible = false
	elseif t == "StarTier" then
		showSplash("⭐ TIER " .. msg.Tier .. "!", GOLD)
		local reward = Config.StarRoad[msg.Tier]
		if reward then
			feedLine("⭐ Star Road tier " .. msg.Tier .. ": " .. rewardText(reward):gsub("\n", ", "), GOLD)
		end
	end
end)

task.delay(1, function()
	Remotes.RequestState:FireServer()
end)
refreshVisibility()
