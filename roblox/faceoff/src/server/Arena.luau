-- Builds fight stages in code, far away from the lobby. Each match or story run borrows a slot.
local CollectionService = game:GetService("CollectionService")
local Debris = game:GetService("Debris")
local PhysicsService = game:GetService("PhysicsService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Workspace = game:GetService("Workspace")

local Config = require(ReplicatedStorage.Shared.Config)
local Visuals = require(script.Parent.Visuals)

local F = Config.Fight
local P = Visuals.Part

local Arena = {}

local SLOTS = 12 -- one per player at the recommended server size of 12
local used = {}

-- NPCs (server-simulated) pass through soft platforms; players get one-way platforms on their client.
pcall(function()
	PhysicsService:RegisterCollisionGroup("SoftPlatform")
	PhysicsService:RegisterCollisionGroup("NpcBody")
	PhysicsService:CollisionGroupSetCollidable("SoftPlatform", "NpcBody", false)
end)

local folder = Instance.new("Folder")
folder.Name = "Arenas"
folder.Parent = Workspace

function Arena.Acquire()
	for i = 1, SLOTS do
		if not used[i] then
			used[i] = true
			return i
		end
	end
	return nil
end

function Arena.Release(ctx)
	if ctx.Released then
		return
	end
	ctx.Released = true
	if ctx.Model then
		ctx.Model:Destroy()
	end
	used[ctx.Slot] = nil
end

-- Frees a slot whose arena was never built (an error during Build).
function Arena.FreeSlot(slot)
	used[slot] = nil
end

local function deco(model, theme, origin, rng)
	local backZ = origin.Z - 26
	local width = theme.Width + 120
	for i = 1, 16 do
		local x = origin.X - width / 2 + (i - 0.5) * (width / 16) + rng:NextNumber(-3, 3)
		local y = origin.Y + rng:NextNumber(-25, 50)
		local pos = Vector3.new(x, y, backZ + rng:NextNumber(-3, 3))
		if theme.Deco == "Gears" then
			local d = rng:NextNumber(8, 18)
			P({ Shape = Enum.PartType.Cylinder, Size = Vector3.new(2, d, d), CFrame = CFrame.new(pos) * CFrame.Angles(0, math.rad(90), 0), Color = theme.Accent, Material = Enum.Material.Metal, CanCollide = false, Parent = model })
			P({ Shape = Enum.PartType.Cylinder, Size = Vector3.new(2.4, d * 0.35, d * 0.35), CFrame = CFrame.new(pos) * CFrame.Angles(0, math.rad(90), 0), Color = theme.Backdrop, Material = Enum.Material.Metal, CanCollide = false, Parent = model })
		elseif theme.Deco == "City" then
			local h = rng:NextNumber(30, 90)
			local base = Vector3.new(x, origin.Y - 40 + h / 2, backZ - 6)
			P({ Size = Vector3.new(10, h, 8), CFrame = CFrame.new(base), Color = Color3.fromRGB(30, 30, 50), Material = Enum.Material.SmoothPlastic, CanCollide = false, Parent = model })
			for w = 1, math.floor(h / 10) do
				P({ Size = Vector3.new(7, 1, 8.4), CFrame = CFrame.new(base + Vector3.new(0, -h / 2 + w * 10 - 4, 0)), Color = (w % 2 == 0) and theme.Accent or Color3.fromRGB(80, 220, 255), Material = Enum.Material.Neon, CanCollide = false, Parent = model })
			end
		elseif theme.Deco == "Clouds" then
			local s = rng:NextNumber(8, 16)
			P({ Shape = Enum.PartType.Ball, Size = Vector3.one * s, CFrame = CFrame.new(pos), Color = Color3.new(1, 1, 1), Material = Enum.Material.SmoothPlastic, CanCollide = false, Parent = model })
			P({ Shape = Enum.PartType.Ball, Size = Vector3.one * s * 0.7, CFrame = CFrame.new(pos + Vector3.new(s * 0.6, -1, 0)), Color = Color3.fromRGB(240, 245, 255), Material = Enum.Material.SmoothPlastic, CanCollide = false, Parent = model })
		elseif theme.Deco == "Ice" then
			local h = rng:NextNumber(6, 20)
			P({ Size = Vector3.new(4, h, 4), CFrame = CFrame.new(pos) * CFrame.Angles(0, 0, math.rad(rng:NextNumber(-25, 25))), Color = Color3.fromRGB(170, 235, 255), Material = Enum.Material.Glass, Transparency = 0.2, CanCollide = false, Parent = model })
		elseif theme.Deco == "Lava" then
			P({ Size = Vector3.new(6, rng:NextNumber(10, 40), 6), CFrame = CFrame.new(pos), Color = Color3.fromRGB(70, 35, 30), Material = Enum.Material.Basalt, CanCollide = false, Parent = model })
		else -- Junk
			if rng:NextNumber() < 0.5 then
				local d = rng:NextNumber(5, 9)
				P({ Shape = Enum.PartType.Cylinder, Size = Vector3.new(2.5, d, d), CFrame = CFrame.new(pos) * CFrame.Angles(0, math.rad(90), 0), Color = Color3.fromRGB(35, 35, 40), Material = Enum.Material.SmoothPlastic, CanCollide = false, Parent = model })
			else
				P({ Size = Vector3.new(rng:NextNumber(5, 10), rng:NextNumber(4, 9), 5), CFrame = CFrame.new(pos) * CFrame.Angles(0, 0, math.rad(rng:NextNumber(-30, 30))), Color = Color3.fromHSV(rng:NextNumber(), 0.6, 0.7), Material = Enum.Material.CorrodedMetal, CanCollide = false, Parent = model })
			end
		end
	end
	if theme.Deco == "Lava" then
		P({ Size = Vector3.new(width + 60, 2, 80), CFrame = CFrame.new(origin + Vector3.new(0, -F.BlastBottom + 6, 0)), Color = Color3.fromRGB(255, 90, 20), Material = Enum.Material.Neon, CanCollide = false, Parent = model })
	end
end

function Arena.Build(slot, themeKey)
	local theme = Config.Arenas[themeKey]
	local origin = Vector3.new(1400 + (slot - 1) * 600, 80, 0) -- stage top surface
	local model = Instance.new("Model")
	model.Name = "Arena" .. slot .. "_" .. themeKey
	local half = theme.Width / 2

	-- Main stage
	P({ Name = "Stage", Size = Vector3.new(theme.Width, 8, 16), CFrame = CFrame.new(origin - Vector3.new(0, 4, 0)), Color = theme.Floor, Material = Enum.Material[theme.FloorMaterial], Parent = model })
	P({ Name = "Under", Size = Vector3.new(theme.Width * 0.7, 16, 13), CFrame = CFrame.new(origin - Vector3.new(0, 16, 0)), Color = theme.Floor:Lerp(Color3.new(0, 0, 0), 0.35), Material = Enum.Material[theme.FloorMaterial], Parent = model })
	P({ Name = "Trim", Size = Vector3.new(theme.Width + 0.2, 0.6, 0.6), CFrame = CFrame.new(origin + Vector3.new(0, -0.3, 8)), Color = theme.Accent, Material = Enum.Material.Neon, CanCollide = false, Parent = model })
	for _, side in { -1, 1 } do
		P({ Name = "EdgeGlow", Size = Vector3.new(0.6, 8, 16.2), CFrame = CFrame.new(origin + Vector3.new(side * half, -4, 0)), Color = theme.Accent, Material = Enum.Material.Neon, CanCollide = false, Parent = model })
	end

	-- Soft platforms (jump up through them, hold S to drop)
	local soft = {}
	for _, spec in theme.Platforms do
		local x, h, w = spec[1], spec[2], spec[3]
		local plat = P({ Name = "SoftPlatform", Size = Vector3.new(w, 1.2, 10), CFrame = CFrame.new(origin + Vector3.new(x, h - 0.6, 0)), Color = theme.Floor:Lerp(Color3.new(1, 1, 1), 0.25), Material = Enum.Material.SmoothPlastic, Parent = model })
		P({ Size = Vector3.new(w, 0.3, 10.2), CFrame = CFrame.new(origin + Vector3.new(x, h - 1.2, 0)), Color = theme.Accent, Material = Enum.Material.Neon, CanCollide = false, Parent = model })
		CollectionService:AddTag(plat, "SoftPlatform")
		plat.CollisionGroup = "SoftPlatform"
		table.insert(soft, plat)
	end

	-- Backdrop
	P({ Name = "Backdrop", Size = Vector3.new(theme.Width + 2 * F.BlastSide + 60, F.BlastTop + F.BlastBottom + 40, 2), CFrame = CFrame.new(origin + Vector3.new(0, (F.BlastTop - F.BlastBottom) / 2, -34)), Color = theme.Backdrop, Material = Enum.Material.SmoothPlastic, CanCollide = false, Parent = model })
	deco(model, theme, origin, Random.new(slot * 97 + #themeKey))

	-- Blast zone walls (glowing, you pass through them... and get KO'd)
	local bounds = {
		MinX = origin.X - half - F.BlastSide,
		MaxX = origin.X + half + F.BlastSide,
		MinY = origin.Y - F.BlastBottom,
		MaxY = origin.Y + F.BlastTop,
	}
	local height = F.BlastTop + F.BlastBottom
	local midY = (bounds.MinY + bounds.MaxY) / 2
	for _, x in { bounds.MinX, bounds.MaxX } do
		P({ Name = "BlastWall", Size = Vector3.new(1, height, 24), CFrame = CFrame.new(x, midY, origin.Z), Color = Color3.fromRGB(255, 40, 90), Material = Enum.Material.Neon, Transparency = 0.82, CanCollide = false, CanQuery = false, Parent = model })
	end
	P({ Name = "BlastFloor", Size = Vector3.new(bounds.MaxX - bounds.MinX, 1, 24), CFrame = CFrame.new(origin.X, bounds.MinY, origin.Z), Color = Color3.fromRGB(255, 40, 90), Material = Enum.Material.Neon, Transparency = 0.7, CanCollide = false, CanQuery = false, Parent = model })

	-- Name sign above the stage
	local signAnchor = P({ Name = "SignAnchor", Size = Vector3.new(1, 1, 1), Transparency = 1, CanCollide = false, CanQuery = false, CFrame = CFrame.new(origin + Vector3.new(0, 46, -20)), Parent = model })
	Visuals.Sign(signAnchor, theme.Name, theme.Accent, UDim2.fromOffset(420, 70), Vector3.zero, 400)

	model.Parent = folder

	local spawns = {
		origin + Vector3.new(-half * 0.55, 3.5, 0),
		origin + Vector3.new(half * 0.55, 3.5, 0),
		origin + Vector3.new(-half * 0.2, 3.5, 0),
		origin + Vector3.new(half * 0.2, 3.5, 0),
		origin + Vector3.new(-half * 0.8, 3.5, 0),
		origin + Vector3.new(half * 0.8, 3.5, 0),
	}
	return {
		Slot = slot,
		Name = theme.Name,
		Theme = themeKey,
		Origin = origin,
		PlaneZ = origin.Z,
		Bounds = bounds,
		Spawns = spawns,
		RespawnPoint = origin + Vector3.new(0, 34, 0),
		StageHalf = half,
		Model = model,
		Soft = soft,
	}
end

-- A CFrame at `position` facing the middle of the stage.
function Arena.Facing(ctx, position)
	local dx = ctx.Origin.X - position.X
	local dir = Vector3.new(dx >= 0 and 1 or -1, 0, 0)
	return CFrame.lookAt(position, position + dir)
end

-- A short-lived glowing platform under a respawning fighter.
function Arena.Halo(ctx, position)
	local halo = P({ Name = "Halo", Size = Vector3.new(7, 0.6, 7), CFrame = CFrame.new(position - Vector3.new(0, 3.4, 0)), Color = Color3.fromRGB(255, 230, 120), Material = Enum.Material.Neon, Transparency = 0.2, Parent = ctx.Model })
	Debris:AddItem(halo, F.RespawnInvuln + 0.4)
end

return Arena
