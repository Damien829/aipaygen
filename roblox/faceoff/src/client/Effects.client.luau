-- Local visual effects: hit sparks, KO blasts, spinning part displays, rainbow paint,
-- Star Road tiles lighting up, and prompt labels that match what you own.
local CollectionService = game:GetService("CollectionService")
local Debris = game:GetService("Debris")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")
local SoundService = game:GetService("SoundService")
local TweenService = game:GetService("TweenService")
local Workspace = game:GetService("Workspace")

local Config = require(ReplicatedStorage.Shared.Config)
local Format = require(ReplicatedStorage.Shared.Format)
local Remotes = require(ReplicatedStorage.Shared.Remotes)

local state = nil

local fxFolder = Instance.new("Folder")
fxFolder.Name = "LocalFX"
fxFolder.Parent = Workspace

local function sound(id, volume, speed, parent)
	local s = Instance.new("Sound")
	s.SoundId = id
	s.Volume = volume or 0.6
	s.PlaybackSpeed = speed or 1
	s.Parent = parent or SoundService
	s:Play()
	Debris:AddItem(s, 4)
end

local function burst(position, color, size, count, speed)
	for _ = 1, count do
		local p = Instance.new("Part")
		p.Anchored = true
		p.CanCollide = false
		p.CanQuery = false
		p.CanTouch = false
		p.CastShadow = false
		p.Material = Enum.Material.Neon
		p.Color = color
		p.Size = Vector3.one * size
		p.CFrame = CFrame.new(position)
		p.Parent = fxFolder
		local dir = Vector3.new(math.random() - 0.5, math.random() - 0.3, math.random() - 0.5)
		if dir.Magnitude < 0.01 then
			dir = Vector3.yAxis
		end
		local goal = position + dir.Unit * speed * (0.5 + math.random())
		TweenService:Create(p, TweenInfo.new(0.35, Enum.EasingStyle.Quad, Enum.EasingDirection.Out), { CFrame = CFrame.new(goal), Size = Vector3.one * 0.05, Transparency = 1 }):Play()
		Debris:AddItem(p, 0.4)
	end
end

local function ring(position, color, radius)
	local p = Instance.new("Part")
	p.Shape = Enum.PartType.Cylinder
	p.Anchored = true
	p.CanCollide = false
	p.CanQuery = false
	p.Material = Enum.Material.Neon
	p.Color = color
	p.Transparency = 0.2
	p.Size = Vector3.new(0.4, 2, 2)
	p.CFrame = CFrame.new(position) * CFrame.Angles(0, math.rad(90), 0)
	p.Parent = fxFolder
	TweenService:Create(p, TweenInfo.new(0.6, Enum.EasingStyle.Quad), { Size = Vector3.new(0.4, radius * 2, radius * 2), Transparency = 1 }):Play()
	Debris:AddItem(p, 0.65)
end

Remotes.Notify.OnClientEvent:Connect(function(msg)
	if msg.Type == "Hit" then
		local power = msg.Power or 30
		burst(msg.Position, msg.Color or Color3.new(1, 1, 1), 0.6, math.clamp(math.floor(power / 15), 4, 14), math.clamp(power / 12, 3, 12))
		sound("rbxasset://sounds/swordlunge.wav", math.clamp(power / 150, 0.3, 1), math.clamp(1.4 - power / 300, 0.7, 1.4))
		if power > 110 then
			ring(msg.Position, Color3.fromRGB(255, 240, 160), 8)
			sound("rbxasset://sounds/collide.wav", 0.8, 0.8)
		end
	elseif msg.Type == "KO" then
		local p = msg.Position
		ring(p, Color3.fromRGB(255, 60, 120), 30)
		ring(p, Color3.fromRGB(255, 220, 60), 18)
		burst(p, Color3.fromRGB(255, 120, 60), 1.4, 24, 26)
		local beam = Instance.new("Part")
		beam.Anchored = true
		beam.CanCollide = false
		beam.CanQuery = false
		beam.Material = Enum.Material.Neon
		beam.Color = Color3.fromRGB(255, 230, 120)
		beam.Size = Vector3.new(80, 3, 3)
		beam.CFrame = CFrame.new(p)
		beam.Parent = fxFolder
		TweenService:Create(beam, TweenInfo.new(0.5), { Size = Vector3.new(160, 0.2, 0.2), Transparency = 1 }):Play()
		Debris:AddItem(beam, 0.55)
		sound("rbxasset://sounds/collide.wav", 1, 0.6)
		sound("rbxasset://sounds/electronicpingshort.wav", 0.6, 0.5)
	elseif msg.Type == "StarTier" then
		sound("rbxasset://sounds/electronicpingshort.wav", 0.8, 1.6)
	end
end)

-- Spinning part displays + rainbow paint -----------------------------------------------------------------
local spinAngle = 0
local hue = 0
RunService.RenderStepped:Connect(function(dt)
	spinAngle += dt * 0.8
	for _, model in CollectionService:GetTagged("Spin") do
		local core = model.PrimaryPart
		if core then
			local base = model:GetAttribute("BaseCFrame")
			if not base then
				model:SetAttribute("BaseCFrame", core.CFrame)
				base = core.CFrame
			end
			model:PivotTo(base * CFrame.new(0, math.sin(spinAngle * 2) * 0.3, 0) * CFrame.Angles(0, spinAngle, 0))
		end
	end
	hue = (hue + dt * 0.25) % 1
	for _, part in CollectionService:GetTagged("RainbowPart") do
		part.Color = Color3.fromHSV(hue, 0.85, 1)
	end
end)

-- Star Road tiles + prompt labels follow your progress ----------------------------------------------------
local function paintTiles()
	if not state then
		return
	end
	local lobby = Workspace:FindFirstChild("Lobby")
	local road = lobby and lobby:FindFirstChild("StarRoad")
	if not road then
		return
	end
	for _, tile in road:GetChildren() do
		local tier = tile:GetAttribute("Tier")
		if tier then
			if tier <= state.StarTier then
				tile.Color = Color3.fromRGB(255, 205, 50)
				tile.Material = Enum.Material.Neon
			elseif tier == state.StarTier + 1 then
				tile.Color = Color3.fromRGB(90, 230, 255)
				tile.Material = Enum.Material.Neon
			else
				tile.Color = Color3.fromRGB(90, 90, 110)
				tile.Material = Enum.Material.SmoothPlastic
			end
		end
	end
end

local promptCache = nil
local function labelPrompts()
	if not state then
		return
	end
	if not promptCache or #promptCache < 28 then -- 18 parts + 10 paints (rebuild if the lobby was still loading)
		local lobby = Workspace:FindFirstChild("Lobby")
		if not lobby then
			return
		end
		promptCache = {}
		for _, pp in lobby:GetDescendants() do
			if pp:IsA("ProximityPrompt") and (pp:GetAttribute("PartKey") or pp:GetAttribute("PaintKey")) then
				table.insert(promptCache, pp)
			end
		end
	end
	for _, pp in promptCache do
		do
			local partKey = pp:GetAttribute("PartKey")
			local paintKey = pp:GetAttribute("PaintKey")
			if partKey then
				local part = Config.Parts[partKey]
				if state.Loadout[part.Slot] == partKey then
					pp.ActionText = "Equipped ✓"
				elseif state.Owned[partKey] then
					pp.ActionText = "Equip"
				elseif part.Price then
					pp.ActionText = "Buy (" .. Format.Number(part.Price) .. " coins)"
				else
					pp.ActionText = "Locked: " .. part.Source
				end
			elseif paintKey then
				local paint = Config.Paints[paintKey]
				if state.Paint == paintKey then
					pp.ActionText = "In use ✓"
				elseif state.Paints[paintKey] then
					pp.ActionText = "Use paint"
				elseif paint.Price then
					pp.ActionText = "Buy (" .. Format.Number(paint.Price) .. " coins)"
				elseif paint.Product then
					pp.ActionText = "Buy (R$ " .. Config.Products[paint.Product].Price .. ")"
				elseif paint.Pass then
					pp.ActionText = "Get VIP"
				else
					pp.ActionText = "Locked: " .. paint.Source
				end
			end
		end
	end
end

Remotes.State.OnClientEvent:Connect(function(newState)
	state = newState
	paintTiles()
	labelPrompts()
end)
task.delay(2, function()
	Remotes.RequestState:FireServer()
end)

-- Pop-up signs: lobby labels stay hidden until you walk close, then bounce in (and shrink away
-- when you leave), so the lobby never looks crowded.
local player = game:GetService("Players").LocalPlayer
local shown = {} -- [BillboardGui] = true while popped up
local POP_IN = TweenInfo.new(0.28, Enum.EasingStyle.Back, Enum.EasingDirection.Out)
local POP_OUT = TweenInfo.new(0.15, Enum.EasingStyle.Quad, Enum.EasingDirection.In)

local function setShown(gui, show)
	local label = gui:FindFirstChildOfClass("TextLabel")
	local scale = label and label:FindFirstChild("Pop")
	if not scale then
		return
	end
	if show then
		shown[gui] = true
		gui.Enabled = true
		TweenService:Create(scale, POP_IN, { Scale = 1 }):Play()
	else
		shown[gui] = nil
		local tween = TweenService:Create(scale, POP_OUT, { Scale = 0 })
		tween.Completed:Connect(function()
			if not shown[gui] then
				gui.Enabled = false
			end
		end)
		tween:Play()
	end
end

CollectionService:GetInstanceAddedSignal("PopSign"):Connect(function(gui)
	gui.Enabled = false
end)
for _, gui in CollectionService:GetTagged("PopSign") do
	gui.Enabled = false
end

task.spawn(function()
	while true do
		task.wait(0.15)
		local character = player.Character
		local root = character and character:FindFirstChild("HumanoidRootPart")
		local here = root and root.Position
		for _, gui in CollectionService:GetTagged("PopSign") do
			local adornee = gui.Adornee
			local near = false
			if here and adornee and adornee:IsA("BasePart") then
				local range = gui:GetAttribute("PopRange") or 15
				local spot = adornee.Position + gui.StudsOffset
				local flat = Vector3.new(spot.X - here.X, 0, spot.Z - here.Z)
				near = flat.Magnitude <= range and math.abs(spot.Y - here.Y) < range + 20
			end
			if near ~= (shown[gui] == true) then
				setShown(gui, near)
			end
		end
		for gui in shown do
			if not gui.Parent then
				shown[gui] = nil
			end
		end
	end
end)
