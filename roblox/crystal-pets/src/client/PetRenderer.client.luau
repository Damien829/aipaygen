-- Renders every player's equipped pets on the client (cheap for the server).
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local Config = require(ReplicatedStorage.Shared.Config)

local folder = Instance.new("Folder")
folder.Name = "ClientPets"
folder.Parent = workspace

local rendered = {} -- [Player] = { Part, ... }

local function makePet(name)
	local info = Config.Pets[name]
	if not info then
		return nil
	end
	local part = Instance.new("Part")
	part.Shape = Enum.PartType.Ball
	part.Size = Vector3.one * 1.6
	part.Material = Enum.Material.Neon
	part.Color = Config.Rarities[info.Rarity].Color
	part.Anchored = true
	part.CanCollide = false
	part.CanQuery = false
	part.CanTouch = false
	part.CastShadow = false

	local gui = Instance.new("BillboardGui")
	gui.Size = UDim2.fromOffset(44, 44)
	gui.StudsOffset = Vector3.new(0, 1.5, 0)
	gui.Adornee = part
	local label = Instance.new("TextLabel")
	label.Size = UDim2.fromScale(1, 1)
	label.BackgroundTransparency = 1
	label.TextScaled = true
	label.Text = info.Icon
	label.Parent = gui
	gui.Parent = part

	part.Parent = folder
	return part
end

local function clear(player)
	local list = rendered[player]
	if list then
		for _, part in list do
			part:Destroy()
		end
	end
	rendered[player] = nil
end

local function rebuild(player)
	clear(player)
	local equipped = player:GetAttribute("EquippedPets")
	if type(equipped) ~= "string" or equipped == "" then
		return
	end
	local list = {}
	for name in string.gmatch(equipped, "[^,]+") do
		local part = makePet(name)
		if part then
			table.insert(list, part)
		end
	end
	rendered[player] = list
end

local function track(player)
	rebuild(player)
	player:GetAttributeChangedSignal("EquippedPets"):Connect(function()
		rebuild(player)
	end)
end

for _, player in Players:GetPlayers() do
	track(player)
end
Players.PlayerAdded:Connect(track)
Players.PlayerRemoving:Connect(clear)

RunService.RenderStepped:Connect(function(dt)
	local alpha = 1 - math.exp(-12 * dt)
	local t = os.clock()
	for player, list in rendered do
		local root = player.Character and player.Character:FindFirstChild("HumanoidRootPart")
		if root then
			local count = #list
			for i, pet in list do
				local x = (i - (count + 1) / 2) * 3
				local z = 4 + (i % 2) * 2.5
				local bob = math.sin(t * 2 + i) * 0.4
				local target = root.CFrame * CFrame.new(x, -1.2 + bob, z)
				if pet:GetAttribute("Placed") then
					pet.CFrame = pet.CFrame:Lerp(target, alpha)
				else
					pet.CFrame = target
					pet:SetAttribute("Placed", true)
				end
			end
		end
	end
end)
