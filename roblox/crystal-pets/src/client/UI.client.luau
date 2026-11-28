-- Entire UI is built in code: HUD, panels (Pets / Shop / Rebirth / Daily), toasts, hatch popup.
local Debris = game:GetService("Debris")
local MarketplaceService = game:GetService("MarketplaceService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")

local Config = require(ReplicatedStorage.Shared.Config)
local Format = require(ReplicatedStorage.Shared.Format)
local Remotes = require(ReplicatedStorage.Shared.Remotes)

local player = Players.LocalPlayer

local BG = Color3.fromRGB(24, 26, 44)
local CARD = Color3.fromRGB(38, 42, 70)
local ACCENT = Color3.fromRGB(98, 126, 255)
local GOLD = Color3.fromRGB(255, 205, 70)
local GREEN = Color3.fromRGB(70, 200, 120)
local RED = Color3.fromRGB(230, 80, 90)
local WHITE = Color3.new(1, 1, 1)

local state = nil
local stateAt = os.clock()

-- Helpers ----------------------------------------------------------------
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
	return new("UICorner", { CornerRadius = UDim.new(0, radius or 8) })
end

local function label(props)
	props.BackgroundTransparency = 1
	props.Font = props.Font or Enum.Font.GothamBold
	props.TextColor3 = props.TextColor3 or WHITE
	props.TextSize = props.TextSize or 16
	return new("TextLabel", props)
end

local function button(text, color, size, parent)
	return new("TextButton", {
		Text = text,
		Font = Enum.Font.GothamBold,
		TextSize = 16,
		TextColor3 = WHITE,
		BackgroundColor3 = color,
		Size = size,
		Parent = parent,
	}, { corner(8) })
end

local gui = new("ScreenGui", {
	Name = "CrystalUI",
	ResetOnSpawn = false,
	ZIndexBehavior = Enum.ZIndexBehavior.Sibling,
	Parent = player:WaitForChild("PlayerGui"),
})

-- Toast --------------------------------------------------------------------
local toastLabel = label({
	Size = UDim2.fromOffset(460, 40),
	AnchorPoint = Vector2.new(0.5, 0),
	Position = UDim2.new(0.5, 0, 0, 14),
	BackgroundTransparency = 0.2,
	BackgroundColor3 = BG,
	TextTransparency = 1,
	Visible = false,
	Parent = gui,
})
toastLabel.BackgroundTransparency = 1
corner(10).Parent = toastLabel
local toastToken = 0

local function toast(text)
	toastToken += 1
	local token = toastToken
	toastLabel.Text = text
	toastLabel.Visible = true
	toastLabel.TextTransparency = 0
	toastLabel.BackgroundTransparency = 0.2
	task.delay(2.5, function()
		if token == toastToken then
			TweenService:Create(toastLabel, TweenInfo.new(0.4), { TextTransparency = 1, BackgroundTransparency = 1 }):Play()
		end
	end)
end

-- Floating "+N" text ---------------------------------------------------------
local function floatText(position, text)
	local anchor = Instance.new("Part")
	anchor.Anchored = true
	anchor.CanCollide = false
	anchor.CanQuery = false
	anchor.CanTouch = false
	anchor.Transparency = 1
	anchor.Size = Vector3.one * 0.1
	anchor.Position = position + Vector3.new(0, 2, 0)
	local bb = Instance.new("BillboardGui")
	bb.Size = UDim2.fromOffset(120, 30)
	bb.AlwaysOnTop = true
	bb.Adornee = anchor
	local lbl = label({
		Size = UDim2.fromScale(1, 1),
		Text = text,
		TextColor3 = GOLD,
		TextScaled = true,
		TextStrokeTransparency = 0.3,
		Parent = bb,
	})
	bb.Parent = anchor
	anchor.Parent = workspace
	TweenService:Create(anchor, TweenInfo.new(0.8), { Position = anchor.Position + Vector3.new(0, 4, 0) }):Play()
	TweenService:Create(lbl, TweenInfo.new(0.8), { TextTransparency = 1, TextStrokeTransparency = 1 }):Play()
	Debris:AddItem(anchor, 1)
end

-- Hatch popup -------------------------------------------------------------
local popup = new("Frame", {
	Size = UDim2.fromOffset(300, 220),
	AnchorPoint = Vector2.new(0.5, 0.5),
	Position = UDim2.fromScale(0.5, 0.45),
	BackgroundColor3 = BG,
	Visible = false,
	Parent = gui,
}, { corner(16), new("UIScale", { Scale = 0 }), new("UIStroke", { Thickness = 4, Color = WHITE }) })
local popupIcon = label({ Size = UDim2.new(1, 0, 0.5, 0), TextScaled = true, Parent = popup })
local popupName = label({ Size = UDim2.new(1, 0, 0, 34), Position = UDim2.fromScale(0, 0.52), TextSize = 28, Parent = popup })
local popupRarity = label({ Size = UDim2.new(1, 0, 0, 24), Position = UDim2.fromScale(0, 0.7), TextSize = 20, Parent = popup })
local popupMult = label({ Size = UDim2.new(1, 0, 0, 24), Position = UDim2.fromScale(0, 0.84), TextColor3 = GOLD, Parent = popup })
local popupToken = 0

local function showHatch(info)
	popupToken += 1
	local token = popupToken
	local color = Config.Rarities[info.Rarity].Color
	popupIcon.Text = info.Icon
	popupName.Text = info.Pet .. "!"
	popupRarity.Text = info.Rarity
	popupRarity.TextColor3 = color
	popupMult.Text = "+" .. string.format("%g", info.Mult) .. "x coins"
	popup.UIStroke.Color = color
	popup.Visible = true
	local scale = popup.UIScale
	scale.Scale = 0
	TweenService:Create(scale, TweenInfo.new(0.35, Enum.EasingStyle.Back), { Scale = 1 }):Play()
	task.delay(2.8, function()
		if token == popupToken then
			local tween = TweenService:Create(scale, TweenInfo.new(0.25), { Scale = 0 })
			tween:Play()
			tween.Completed:Wait()
			if token == popupToken then
				popup.Visible = false
			end
		end
	end)
end

-- HUD ----------------------------------------------------------------------
local hud = new("Frame", {
	Size = UDim2.fromOffset(240, 132),
	Position = UDim2.fromOffset(12, 12),
	BackgroundColor3 = BG,
	BackgroundTransparency = 0.15,
	Parent = gui,
}, {
	corner(10),
	new("UIPadding", { PaddingLeft = UDim.new(0, 12), PaddingTop = UDim.new(0, 6) }),
	new("UIListLayout", { SortOrder = Enum.SortOrder.LayoutOrder }),
})
local function hudLine(order, color)
	return label({
		Size = UDim2.new(1, 0, 0, 24),
		LayoutOrder = order,
		TextColor3 = color,
		TextXAlignment = Enum.TextXAlignment.Left,
		Parent = hud,
	})
end
local coinsLabel = hudLine(1, GOLD)
local rebirthLabel = hudLine(2, WHITE)
local multLabel = hudLine(3, GREEN)
local boostLabel = hudLine(4, ACCENT)
local friendLabel = hudLine(5, Color3.fromRGB(255, 150, 210))
coinsLabel.TextSize = 20

local function refreshHud()
	if not state then
		return
	end
	coinsLabel.Text = "Coins: " .. Format.Number(state.Coins)
	rebirthLabel.Text = "Rebirths: " .. state.Rebirths
	multLabel.Text = "Multiplier: x" .. string.format("%.2f", state.Multiplier)
	local serverNow = state.ServerTime + (os.clock() - stateAt)
	local remaining = state.BoostUntil - serverNow
	boostLabel.Text = remaining > 0 and ("2x Boost: " .. Format.Time(remaining)) or (state.Club and "Crystal Club active" or "")
	friendLabel.Text = state.FriendBonus > 0 and string.format("Friends bonus: +%d%%", math.floor(state.FriendBonus * 100 + 0.5)) or "Play with friends: +10% each"
end

task.spawn(function()
	while true do
		task.wait(0.5)
		refreshHud()
	end
end)

-- Panels -------------------------------------------------------------------
local panel = new("Frame", {
	Size = UDim2.fromOffset(480, 380),
	AnchorPoint = Vector2.new(0.5, 0.5),
	Position = UDim2.fromScale(0.5, 0.5),
	BackgroundColor3 = BG,
	Visible = false,
	Parent = gui,
}, { corner(14), new("UIStroke", { Thickness = 2, Color = ACCENT }) })
local panelTitle = label({
	Size = UDim2.new(1, -60, 0, 36),
	Position = UDim2.fromOffset(14, 6),
	TextSize = 22,
	TextXAlignment = Enum.TextXAlignment.Left,
	Parent = panel,
})
local closeButton = button("X", RED, UDim2.fromOffset(32, 32), panel)
closeButton.Position = UDim2.new(1, -42, 0, 8)
local content = new("Frame", {
	Size = UDim2.new(1, -24, 1, -56),
	Position = UDim2.fromOffset(12, 48),
	BackgroundTransparency = 1,
	Parent = panel,
})

local builders = {}
local current, lastSig = nil, nil

local function rebuild()
	content:ClearAllChildren()
	if current and state then
		builders[current].build(content)
		lastSig = builders[current].sig(state)
	end
end

local function closePanel()
	current = nil
	panel.Visible = false
end

local function openPanel(name)
	if current == name then
		return closePanel()
	end
	if not state then
		return
	end
	current = name
	panelTitle.Text = builders[name].title
	panel.Visible = true
	rebuild()
end
closeButton.Activated:Connect(closePanel)

local function refreshPanel()
	if current and state and builders[current].sig(state) ~= lastSig then
		rebuild()
	end
end

local function scrollList(parent, layout)
	return new("ScrollingFrame", {
		Size = UDim2.fromScale(1, 1),
		BackgroundTransparency = 1,
		BorderSizePixel = 0,
		CanvasSize = UDim2.new(),
		AutomaticCanvasSize = Enum.AutomaticSize.Y,
		ScrollBarThickness = 6,
		Parent = parent,
	}, { layout })
end

-- Pets ----------------------------------------------------------------------
builders.Pets = {
	title = "Your Pets",
	sig = function(s)
		local parts = {}
		for name, n in s.Pets do
			table.insert(parts, name .. n)
		end
		table.sort(parts)
		return table.concat(parts, "|") .. ";" .. table.concat(s.Equipped, ",") .. ";" .. s.Slots
	end,
	build = function(c)
		local s = state
		label({
			Size = UDim2.new(1, 0, 0, 22),
			Text = string.format("Equipped %d / %d  -  tap a pet to equip / unequip", #s.Equipped, s.Slots),
			TextSize = 14,
			Parent = c,
		})
		local holder = new("Frame", {
			Size = UDim2.new(1, 0, 1, -26),
			Position = UDim2.fromOffset(0, 26),
			BackgroundTransparency = 1,
			Parent = c,
		})
		local scroll = scrollList(holder, new("UIGridLayout", {
			CellSize = UDim2.fromOffset(100, 112),
			CellPadding = UDim2.fromOffset(8, 8),
		}))

		local names = {}
		for name in s.Pets do
			table.insert(names, name)
		end
		table.sort(names, function(a, b)
			local pa, pb = Config.Pets[a], Config.Pets[b]
			if pa.Mult ~= pb.Mult then
				return pa.Mult > pb.Mult
			end
			return a < b
		end)

		if #names == 0 then
			label({
				Size = UDim2.new(1, 0, 0, 60),
				Text = "No pets yet!\nHatch eggs at the pedestals near spawn.",
				TextSize = 16,
				Parent = holder,
			})
		end

		for _, name in names do
			local info = Config.Pets[name]
			local equippedCount = 0
			for _, e in s.Equipped do
				if e == name then
					equippedCount += 1
				end
			end
			local card = new("TextButton", { Text = "", BackgroundColor3 = CARD, Parent = scroll }, {
				corner(10),
				new("UIStroke", { Color = Config.Rarities[info.Rarity].Color, Thickness = equippedCount > 0 and 3 or 1 }),
			})
			label({ Size = UDim2.new(1, 0, 0.42, 0), Text = info.Icon, TextScaled = true, Parent = card })
			label({ Size = UDim2.new(1, 0, 0, 18), Position = UDim2.fromScale(0, 0.44), Text = name, TextSize = 14, Parent = card })
			label({
				Size = UDim2.new(1, 0, 0, 16), Position = UDim2.fromScale(0, 0.6),
				Text = string.format("x%d  (%d equipped)", s.Pets[name], equippedCount),
				TextSize = 11, TextColor3 = Color3.fromRGB(200, 200, 220), Parent = card,
			})
			label({
				Size = UDim2.new(1, 0, 0, 16), Position = UDim2.fromScale(0, 0.77),
				Text = "+" .. string.format("%g", info.Mult) .. "x", TextSize = 14, TextColor3 = GOLD, Parent = card,
			})
			card.Activated:Connect(function()
				task.spawn(function()
					Remotes.EquipPet:InvokeServer(name)
				end)
			end)
		end
	end,
}

-- Shop ----------------------------------------------------------------------
local function promptPass(info)
	if info.Id == 0 then
		return toast("Set this pass's Id in Config.luau first (see README).")
	end
	MarketplaceService:PromptGamePassPurchase(player, info.Id)
end

local function promptProduct(info)
	if info.Id == 0 then
		return toast("Set this product's Id in Config.luau first (see README).")
	end
	MarketplaceService:PromptProductPurchase(player, info.Id)
end

local function promptSubscription()
	if Config.Subscription.Id == "" then
		return toast("Set the subscription Id in Config.luau first (see README).")
	end
	MarketplaceService:PromptSubscriptionPurchase(player, Config.Subscription.Id)
end

builders.Shop = {
	title = "Shop",
	sig = function(s)
		local owned = {}
		for _, key in Config.PassOrder do
			table.insert(owned, tostring(s.Passes[key] == true))
		end
		return table.concat(owned, ",") .. tostring(s.Club) .. tostring(s.StarterBought)
	end,
	build = function(c)
		local scroll = scrollList(c, new("UIListLayout", { Padding = UDim.new(0, 6), SortOrder = Enum.SortOrder.LayoutOrder }))
		local order = 0
		local function row(name, desc, buttonText, buttonColor, onClick)
			order += 1
			local frame = new("Frame", {
				Size = UDim2.new(1, -10, 0, 56), BackgroundColor3 = CARD, LayoutOrder = order, Parent = scroll,
			}, { corner(10) })
			label({
				Size = UDim2.new(1, -140, 0, 24), Position = UDim2.fromOffset(12, 4), Text = name,
				TextXAlignment = Enum.TextXAlignment.Left, Parent = frame,
			})
			label({
				Size = UDim2.new(1, -140, 0, 22), Position = UDim2.fromOffset(12, 28), Text = desc, TextSize = 12,
				TextColor3 = Color3.fromRGB(190, 195, 220), TextXAlignment = Enum.TextXAlignment.Left, Parent = frame,
			})
			local buy = button(buttonText, buttonColor, UDim2.fromOffset(110, 36), frame)
			buy.Position = UDim2.new(1, -120, 0.5, -18)
			if onClick then
				buy.Activated:Connect(onClick)
			else
				buy.AutoButtonColor = false
			end
		end
		local sub = Config.Subscription
		if state.Club then
			row(sub.Name, sub.Desc, "Active", GREEN, nil)
		else
			row(sub.Name .. " (monthly)", sub.Desc, "R$ " .. sub.Price .. "/mo", Color3.fromRGB(170, 90, 255), promptSubscription)
		end
		for _, key in Config.PassOrder do
			local info = Config.GamePasses[key]
			if state.Passes[key] then
				row(info.Name, info.Desc, "Owned", GREEN, nil)
			else
				row(info.Name, info.Desc, "R$ " .. info.Price, ACCENT, function()
					promptPass(info)
				end)
			end
		end
		for _, key in Config.ProductOrder do
			local info = Config.Products[key]
			if not (info.OneTime and state.StarterBought) then
				local desc = "Double all coins for 15 minutes."
				if info.Coins then
					desc = "+" .. Format.Number(info.Coins) .. " coins" .. (info.Pet and (" + " .. info.Pet .. " pet") or " (x rebirths)")
				end
				row(info.Name, desc, "R$ " .. info.Price, GOLD, function()
					promptProduct(info)
				end)
			end
		end
	end,
}

-- Style (cosmetic trails) -----------------------------------------------------
builders.Style = {
	title = "Style - Trails",
	sig = function(s)
		local owned = {}
		for _, key in Config.CosmeticOrder do
			table.insert(owned, tostring(s.OwnedCosmetics[key] == true))
		end
		return table.concat(owned, ",") .. ";" .. s.EquippedTrail .. tostring(s.Club)
	end,
	build = function(c)
		local scroll = scrollList(c, new("UIListLayout", { Padding = UDim.new(0, 6), SortOrder = Enum.SortOrder.LayoutOrder }))
		for i, key in Config.CosmeticOrder do
			local info = Config.Cosmetics[key]
			local frame = new("Frame", {
				Size = UDim2.new(1, -10, 0, 52), BackgroundColor3 = CARD, LayoutOrder = i, Parent = scroll,
			}, { corner(10) })
			local swatch = new("Frame", {
				Size = UDim2.fromOffset(28, 28), Position = UDim2.fromOffset(12, 12), BackgroundColor3 = WHITE, Parent = frame,
			}, { corner(6) })
			local stops = {}
			for j, color in info.Colors do
				table.insert(stops, ColorSequenceKeypoint.new(#info.Colors == 1 and 0 or (j - 1) / (#info.Colors - 1), color))
			end
			if #stops == 1 then
				table.insert(stops, ColorSequenceKeypoint.new(1, info.Colors[1]))
			end
			new("UIGradient", { Color = ColorSequence.new(stops), Parent = swatch })
			label({
				Size = UDim2.new(1, -170, 1, 0), Position = UDim2.fromOffset(52, 0), Text = info.Name,
				TextXAlignment = Enum.TextXAlignment.Left, Parent = frame,
			})
			local owned = state.OwnedCosmetics[key] == true or (info.ClubOnly == true and state.Club == true)
			local text, color, onClick
			if owned and state.EquippedTrail == key then
				text, color = "Unequip", GREEN
				onClick = function()
					Remotes.Cosmetic:InvokeServer("Equip", "")
				end
			elseif owned then
				text, color = "Equip", ACCENT
				onClick = function()
					Remotes.Cosmetic:InvokeServer("Equip", key)
				end
			elseif info.Cost then
				text, color = Format.Number(info.Cost) .. " coins", GOLD
				onClick = function()
					Remotes.Cosmetic:InvokeServer("Buy", key)
				end
			elseif info.ClubOnly then
				text, color = "Club only", Color3.fromRGB(170, 90, 255)
				onClick = promptSubscription
			else
				text, color = "R$ " .. info.Price, RED
				onClick = function()
					promptProduct(info)
				end
			end
			local b = button(text, color, UDim2.fromOffset(116, 34), frame)
			b.Position = UDim2.new(1, -126, 0.5, -17)
			b.TextSize = 14
			b.Activated:Connect(function()
				task.spawn(onClick)
			end)
		end
	end,
}

-- Rebirth -------------------------------------------------------------------
builders.Rebirth = {
	title = "Rebirth",
	sig = function(s)
		return s.Rebirths .. ":" .. s.RebirthCost .. ":" .. tostring(s.Coins >= s.RebirthCost)
	end,
	build = function(c)
		local s = state
		label({
			Size = UDim2.new(1, 0, 0, 120),
			TextWrapped = true,
			TextSize = 18,
			Text = string.format(
				"Rebirths: %d\nCost: %s coins\n\nResets your coins and zones (you keep all pets).\nEach rebirth gives a permanent +%d%% coins.",
				s.Rebirths, Format.Number(s.RebirthCost), Config.RebirthBonus * 100
			),
			Parent = c,
		})
		local canRebirth = s.Coins >= s.RebirthCost
		local go = button(canRebirth and "REBIRTH!" or "Not enough coins", canRebirth and GREEN or Color3.fromRGB(90, 90, 110), UDim2.fromOffset(240, 50), c)
		go.Position = UDim2.new(0.5, -120, 0, 150)
		go.TextSize = 20
		go.Activated:Connect(function()
			if canRebirth then
				task.spawn(function()
					Remotes.Rebirth:InvokeServer()
				end)
			end
		end)
	end,
}

-- Daily ---------------------------------------------------------------------
builders.Daily = {
	title = "Daily Reward",
	sig = function(s)
		return tostring(s.DailyReady) .. ":" .. s.DailyStreak .. ":" .. s.Rebirths
	end,
	build = function(c)
		local s = state
		local row = new("Frame", { Size = UDim2.new(1, 0, 0, 90), BackgroundTransparency = 1, Parent = c }, {
			new("UIListLayout", { FillDirection = Enum.FillDirection.Horizontal, Padding = UDim.new(0, 6) }),
		})
		local nextDay = s.DailyStreak % #Config.DailyRewards + 1
		for i, reward in Config.DailyRewards do
			local box = new("Frame", {
				Size = UDim2.fromOffset(60, 84), BackgroundColor3 = i == nextDay and ACCENT or CARD, Parent = row,
			}, { corner(8) })
			label({ Size = UDim2.new(1, 0, 0, 24), Text = "Day " .. i, TextSize = 13, Parent = box })
			label({
				Size = UDim2.new(1, 0, 0, 40), Position = UDim2.fromOffset(0, 30),
				Text = "+" .. Format.Number(reward * (1 + s.Rebirths)), TextSize = 13, TextColor3 = GOLD, Parent = box,
			})
		end
		label({
			Size = UDim2.new(1, 0, 0, 60), Position = UDim2.fromOffset(0, 110), TextWrapped = true, TextSize = 14,
			Text = "Come back every day to keep your streak going. VIP doubles every reward!", Parent = c,
		})
		local claim = button(s.DailyReady and "CLAIM" or "Come back later", s.DailyReady and GREEN or Color3.fromRGB(90, 90, 110), UDim2.fromOffset(240, 50), c)
		claim.Position = UDim2.new(0.5, -120, 0, 190)
		claim.TextSize = 20
		claim.Activated:Connect(function()
			if s.DailyReady then
				task.spawn(function()
					Remotes.ClaimDaily:InvokeServer()
				end)
			end
		end)
	end,
}

-- Bottom bar ----------------------------------------------------------------
local bar = new("Frame", {
	Size = UDim2.fromOffset(480, 52),
	AnchorPoint = Vector2.new(0.5, 1),
	Position = UDim2.new(0.5, 0, 1, -14),
	BackgroundTransparency = 1,
	Parent = gui,
}, {
	new("UIListLayout", {
		FillDirection = Enum.FillDirection.Horizontal,
		HorizontalAlignment = Enum.HorizontalAlignment.Center,
		Padding = UDim.new(0, 8),
	}),
})
local dailyDot
for _, entry in { { "Pets", ACCENT }, { "Style", Color3.fromRGB(170, 90, 255) }, { "Shop", GOLD }, { "Rebirth", GREEN }, { "Daily", RED } } do
	local name, color = entry[1], entry[2]
	local b = button(name, color, UDim2.fromOffset(86, 48), bar)
	b.TextSize = 18
	b.Activated:Connect(function()
		openPanel(name)
	end)
	if name == "Daily" then
		dailyDot = new("Frame", {
			Size = UDim2.fromOffset(16, 16), Position = UDim2.new(1, -8, 0, -8), BackgroundColor3 = WHITE,
			Visible = false, Parent = b,
		}, { new("UICorner", { CornerRadius = UDim.new(1, 0) }) })
	end
end

-- Contextual purchase offer card -----------------------------------------------
local offerFrame = new("Frame", {
	Size = UDim2.fromOffset(290, 100),
	AnchorPoint = Vector2.new(1, 1),
	Position = UDim2.new(1, -14, 1, -84),
	BackgroundColor3 = BG,
	Visible = false,
	Parent = gui,
}, { corner(12), new("UIStroke", { Thickness = 2, Color = GOLD }) })
local offerText = label({
	Size = UDim2.new(1, -16, 0, 46), Position = UDim2.fromOffset(8, 6), TextWrapped = true, TextSize = 14,
	TextXAlignment = Enum.TextXAlignment.Left, Parent = offerFrame,
})
local offerBuy = button("Buy", GOLD, UDim2.fromOffset(130, 32), offerFrame)
offerBuy.Position = UDim2.fromOffset(8, 58)
local offerClose = button("No thanks", Color3.fromRGB(90, 90, 110), UDim2.fromOffset(110, 32), offerFrame)
offerClose.Position = UDim2.fromOffset(150, 58)
local offerProduct, offerToken = nil, 0

local function showOffer(info)
	local product = Config.Products[info.Product]
	if not product then
		return
	end
	offerToken += 1
	local token = offerToken
	offerProduct = product
	offerText.Text = info.Text
	offerBuy.Text = "R$ " .. product.Price
	offerFrame.Visible = true
	task.delay(20, function()
		if token == offerToken then
			offerFrame.Visible = false
		end
	end)
end

offerBuy.Activated:Connect(function()
	if offerProduct then
		promptProduct(offerProduct)
	end
	offerFrame.Visible = false
	offerToken += 1
end)
offerClose.Activated:Connect(function()
	offerFrame.Visible = false
	offerToken += 1
end)

-- Remote handlers --------------------------------------------------------------
Remotes.State.OnClientEvent:Connect(function(newState)
	state = newState
	stateAt = os.clock()
	dailyDot.Visible = newState.DailyReady
	refreshHud()
	refreshPanel()
end)

-- Keep asking until the server has our state (it may still be loading our data).
task.spawn(function()
	while not state do
		Remotes.RequestState:FireServer()
		task.wait(2)
	end
end)

Remotes.Notify.OnClientEvent:Connect(function(info)
	if info.Type == "Toast" then
		toast(info.Text)
	elseif info.Type == "Mine" then
		floatText(info.Position, "+" .. Format.Number(info.Amount))
	elseif info.Type == "Hatch" then
		showHatch(info)
	elseif info.Type == "Offer" then
		showOffer(info)
	end
end)
