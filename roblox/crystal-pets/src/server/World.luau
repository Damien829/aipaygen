-- Builds the whole map procedurally so the project works with an empty baseplate.
local Lighting = game:GetService("Lighting")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Workspace = game:GetService("Workspace")

local Config = require(ReplicatedStorage.Shared.Config)
local Format = require(ReplicatedStorage.Shared.Format)

local World = {}

local function newPart(props)
	local part = Instance.new("Part")
	part.Anchored = true
	part.TopSurface = Enum.SurfaceType.Smooth
	part.BottomSurface = Enum.SurfaceType.Smooth
	local parent
	for k, v in props do
		if k == "Parent" then
			parent = v
		else
			part[k] = v
		end
	end
	part.Parent = parent
	return part
end

local function addLabel(adornee, text, offsetY, width)
	local gui = Instance.new("BillboardGui")
	gui.Size = UDim2.fromOffset(width or 240, 70)
	gui.StudsOffset = Vector3.new(0, offsetY, 0)
	gui.MaxDistance = 90
	gui.Adornee = adornee
	local label = Instance.new("TextLabel")
	label.Size = UDim2.fromScale(1, 1)
	label.BackgroundTransparency = 1
	label.TextScaled = true
	label.Font = Enum.Font.GothamBold
	label.TextColor3 = Color3.new(1, 1, 1)
	label.TextStrokeTransparency = 0
	label.Text = text
	label.Parent = gui
	gui.Parent = adornee
end

local function addPrompt(parent, actionText, objectText, hold, distance)
	local prompt = Instance.new("ProximityPrompt")
	prompt.ActionText = actionText
	prompt.ObjectText = objectText
	prompt.HoldDuration = hold
	prompt.MaxActivationDistance = distance
	prompt.RequiresLineOfSight = false
	prompt.Parent = parent
	return prompt
end

function World.Build(handlers)
	-- Clear template leftovers.
	for _, name in { "Baseplate", "SpawnLocation" } do
		local old = Workspace:FindFirstChild(name)
		if old then
			old:Destroy()
		end
	end

	Lighting.ClockTime = 14
	Lighting.Brightness = 3
	Lighting.OutdoorAmbient = Color3.fromRGB(150, 150, 170)

	local world = Instance.new("Folder")
	world.Name = "World"
	world.Parent = Workspace
	local crystals = Instance.new("Folder")
	crystals.Name = "Crystals"
	crystals.Parent = Workspace

	local rng = Random.new(1337)

	local spawn = Instance.new("SpawnLocation")
	spawn.Anchored = true
	spawn.Size = Vector3.new(12, 1, 12)
	spawn.Position = Vector3.new(0, 0.5, 0)
	spawn.Neutral = true
	spawn.Duration = 0
	spawn.Color = Color3.fromRGB(255, 220, 90)
	spawn.Material = Enum.Material.Neon
	spawn.Parent = world

	-- Positions crystals must keep clear (spawn, eggs, unlock stands).
	local function flat(v)
		return Vector3.new(v.X, 0, v.Z)
	end

	for _, zone in Config.Zones do
		newPart({
			Name = zone.Id .. "Floor",
			Size = Vector3.new(160, 2, 160),
			Position = zone.Center + Vector3.new(0, -1, 0),
			Color = zone.FloorColor,
			Material = zone.Material,
			Parent = world,
		})

		local avoid = { zone.Center }
		if zone.Stand then
			table.insert(avoid, zone.Stand)
		end
		for _, egg in Config.Eggs do
			if egg.Zone == zone.Id then
				table.insert(avoid, zone.Center + egg.Offset)
			end
		end

		-- Unlock pedestal (zones with a cost).
		if zone.Stand then
			local pedestal = newPart({
				Name = zone.Id .. "Unlock",
				Size = Vector3.new(6, 1, 6),
				Position = zone.Stand + Vector3.new(0, 0.5, 0),
				Color = zone.CrystalColor,
				Material = Enum.Material.Neon,
				Parent = world,
			})
			addLabel(pedestal, "Unlock " .. zone.Name .. "\n" .. Format.Number(zone.Cost) .. " coins", 5)
			local prompt = addPrompt(pedestal, "Unlock", zone.Name, 0.5, 12)
			prompt.Triggered:Connect(function(player)
				handlers.Unlock(player, zone.Id)
			end)
		end

		-- Crystals.
		local placed, tries, points = 0, 0, {}
		while placed < zone.CrystalCount and tries < 3000 do
			tries += 1
			local position = zone.Center + Vector3.new(rng:NextNumber(-70, 70), 0, rng:NextNumber(-70, 70))
			local ok = true
			for _, a in avoid do
				if (flat(position) - flat(a)).Magnitude < 14 then
					ok = false
					break
				end
			end
			if ok then
				for _, p in points do
					if (flat(position) - flat(p)).Magnitude < 7 then
						ok = false
						break
					end
				end
			end
			if ok then
				placed += 1
				table.insert(points, position)
				local crystal = newPart({
					Name = "Crystal",
					Size = Vector3.new(3, 4, 3),
					CFrame = CFrame.new(position + Vector3.new(0, 2.5, 0))
						* CFrame.Angles(0, math.rad(rng:NextNumber(0, 360)), 0)
						* CFrame.Angles(math.rad(45), 0, math.rad(45)),
					Color = zone.CrystalColor,
					Material = Enum.Material.Neon,
					CanCollide = false,
					Parent = crystals,
				})
				crystal:SetAttribute("Zone", zone.Id)
				crystal:SetAttribute("Active", true)
				local prompt = addPrompt(crystal, "Mine", zone.Name, 0, 12)
				prompt.Triggered:Connect(function(player)
					handlers.Mine(player, crystal)
				end)
			end
		end
	end

	-- Eggs.
	for key, egg in Config.Eggs do
		local zone = Config.ZoneById[egg.Zone]
		local base = zone.Center + egg.Offset
		local pedestal = newPart({
			Name = key .. "EggStand",
			Size = Vector3.new(8, 1, 8),
			Position = base + Vector3.new(0, 0.5, 0),
			Color = Color3.fromRGB(40, 40, 55),
			Material = Enum.Material.Metal,
			Parent = world,
		})
		local orb = newPart({
			Name = key .. "Egg",
			Shape = Enum.PartType.Ball,
			Size = Vector3.new(5, 6, 5),
			Position = base + Vector3.new(0, 4.5, 0),
			Color = egg.Color,
			Material = Enum.Material.Neon,
			CanCollide = false,
			Parent = world,
		})
		addLabel(orb, egg.Name .. "\n" .. Format.Number(egg.Cost) .. " coins", 5)
		local prompt = addPrompt(pedestal, "Hatch", egg.Name, 0.4, 12)
		prompt.Triggered:Connect(function(player)
			handlers.Hatch(player, key)
		end)
	end

	return crystals
end

return World
