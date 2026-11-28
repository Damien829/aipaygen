-- Draws each player's equipped trail (replicated through the "Trail" player attribute).
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Config = require(ReplicatedStorage.Shared.Config)

local function colorSequence(colors)
	local stops = {}
	for i, color in colors do
		table.insert(stops, ColorSequenceKeypoint.new(#colors == 1 and 0 or (i - 1) / (#colors - 1), color))
	end
	if #stops == 1 then
		table.insert(stops, ColorSequenceKeypoint.new(1, colors[1]))
	end
	return ColorSequence.new(stops)
end

local function apply(player)
	local character = player.Character
	local root = character and character:FindFirstChild("HumanoidRootPart")
	if not root then
		return
	end
	for _, name in { "StyleTrail", "TrailA0", "TrailA1" } do
		local old = root:FindFirstChild(name)
		if old then
			old:Destroy()
		end
	end

	local id = player:GetAttribute("Trail")
	local info = type(id) == "string" and Config.Cosmetics[id]
	if not info then
		return
	end

	local a0 = Instance.new("Attachment")
	a0.Name = "TrailA0"
	a0.Position = Vector3.new(0, 0.8, 0)
	a0.Parent = root
	local a1 = Instance.new("Attachment")
	a1.Name = "TrailA1"
	a1.Position = Vector3.new(0, -0.8, 0)
	a1.Parent = root

	local trail = Instance.new("Trail")
	trail.Name = "StyleTrail"
	trail.Attachment0 = a0
	trail.Attachment1 = a1
	trail.Lifetime = 0.9
	trail.LightEmission = 1
	trail.Transparency = NumberSequence.new(0.1, 1)
	trail.Color = colorSequence(info.Colors)
	trail.Parent = root
end

local function track(player)
	player:GetAttributeChangedSignal("Trail"):Connect(function()
		apply(player)
	end)
	player.CharacterAdded:Connect(function(character)
		character:WaitForChild("HumanoidRootPart", 10)
		apply(player)
	end)
	apply(player)
end

for _, player in Players:GetPlayers() do
	track(player)
end
Players.PlayerAdded:Connect(track)
