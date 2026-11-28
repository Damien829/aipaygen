-- Computer fighters: matchmaking bots, story minions, bosses and the lobby's training dummies.
local CollectionService = game:GetService("CollectionService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Workspace = game:GetService("Workspace")

local Config = require(ReplicatedStorage.Shared.Config)
local Combat = require(script.Parent.Combat)
local Visuals = require(script.Parent.Visuals)

local Npc = {}

local function fallbackRig(color)
	-- Only used if Roblox can't build a normal body (very rare).
	local model = Instance.new("Model")
	local root = Visuals.Part({ Name = "HumanoidRootPart", Anchored = false, Size = Vector3.new(2, 2, 1), Transparency = 1, Parent = model })
	local torso = Visuals.Part({ Name = "UpperTorso", Anchored = false, Size = Vector3.new(2, 2, 1), Color = color, CFrame = root.CFrame, Parent = model })
	local head = Visuals.Part({ Name = "Head", Anchored = false, Size = Vector3.new(1.2, 1.2, 1.2), Color = color, CFrame = root.CFrame * CFrame.new(0, 1.6, 0), Parent = model })
	for _, part in { torso, head } do
		local weld = Instance.new("WeldConstraint")
		weld.Part0 = root
		weld.Part1 = part
		weld.Parent = part
	end
	local humanoid = Instance.new("Humanoid")
	humanoid.HipHeight = 2
	humanoid.Parent = model
	model.PrimaryPart = root
	return model
end

-- Robot builds, so every bot is a real character, not a plain block body.
-- Scale = body proportions; the rest are gadgets welded onto the body.
local KITS = {
	Brawler = { Height = 1.05, Width = 1.2, Depth = 1.1, Head = 1.0, Material = "Metal", Eye = "Visor", Pads = true, Core = true },
	Speedster = { Height = 1.0, Width = 0.85, Depth = 0.9, Head = 0.95, Material = "SmoothPlastic", Eye = "Visor", Fins = true, Stripes = true },
	Tank = { Height = 1.1, Width = 1.3, Depth = 1.25, Head = 0.9, Material = "DiamondPlate", Eye = "Visor", Pads = true, Pack = true },
	Scout = { Height = 0.92, Width = 0.95, Depth = 0.95, Head = 1.15, Material = "SmoothPlastic", Eye = "Visor", Antenna = true, Pack = true },
	Gremlin = { Height = 0.85, Width = 1.0, Depth = 1.0, Head = 1.35, Material = "Metal", Eye = "Cyclops", Antenna = true, Core = true },
}
local KIT_ORDER = { "Brawler", "Speedster", "Tank", "Scout", "Gremlin" }
Npc.KitOrder = KIT_ORDER

local function kitFor(def)
	if def.Kit and KITS[def.Kit] then
		return def.Kit
	end
	local hash = 0
	for i = 1, #def.Name do
		hash += string.byte(def.Name, i) * i
	end
	return KIT_ORDER[hash % #KIT_ORDER + 1]
end

local function gadget(model, body, size, offset, color, material, shape)
	if not body then
		return
	end
	local part = Visuals.Part({
		Name = "Gadget",
		Anchored = false,
		Shape = shape or Enum.PartType.Block,
		Size = size,
		Color = color,
		Material = material,
		CanCollide = false,
		CanQuery = false,
		CanTouch = false,
		Massless = true,
		CastShadow = false,
		CFrame = body.CFrame * offset,
	})
	local weld = Instance.new("WeldConstraint")
	weld.Part0 = body
	weld.Part1 = part
	weld.Parent = part
	part.Parent = model:FindFirstChild("RobotKit") or model
	return part
end

-- Adds the eyes, armor and gadgets for the bot's build (after any scaling).
local function addKit(model, def)
	local kit = KITS[kitFor(def)]
	local folder = Instance.new("Folder")
	folder.Name = "RobotKit"
	folder.Parent = model
	local color = def.Color or Color3.fromRGB(200, 200, 210)
	local trim = color:Lerp(Color3.new(1, 1, 1), 0.55)
	local glow = def.Glow or Color3.fromHSV((color:ToHSV() + 0.5) % 1, 0.8, 1)
	local material = Enum.Material[kit.Material]
	for _, part in model:GetChildren() do
		if part:IsA("BasePart") and part.Name ~= "HumanoidRootPart" then
			part.Material = material
		end
	end
	local head = model:FindFirstChild("Head")
	local torso = model:FindFirstChild("UpperTorso")
	if head then
		local face = head:FindFirstChildOfClass("Decal")
		if face then
			face:Destroy() -- robots get glowing eyes instead
		end
		local s = head.Size
		if kit.Eye == "Cyclops" then
			gadget(model, head, Vector3.one * s.Y * 0.5, CFrame.new(0, s.Y * 0.08, -s.Z * 0.42), glow, Enum.Material.Neon, Enum.PartType.Ball)
		else
			gadget(model, head, Vector3.new(s.X * 0.85, s.Y * 0.22, 0.12), CFrame.new(0, s.Y * 0.1, -s.Z * 0.5 - 0.04), glow, Enum.Material.Neon)
		end
		if kit.Antenna then
			gadget(model, head, Vector3.new(0.12, s.Y * 0.7, 0.12), CFrame.new(s.X * 0.3, s.Y * 0.8, 0), trim, Enum.Material.Metal)
			gadget(model, head, Vector3.one * 0.32, CFrame.new(s.X * 0.3, s.Y * 1.15, 0), glow, Enum.Material.Neon, Enum.PartType.Ball)
		end
	end
	if torso then
		local s = torso.Size
		if kit.Core then
			gadget(model, torso, Vector3.one * s.Y * 0.32, CFrame.new(0, s.Y * 0.1, -s.Z * 0.48), glow, Enum.Material.Neon, Enum.PartType.Ball)
		end
		if kit.Pack then
			gadget(model, torso, Vector3.new(s.X * 0.7, s.Y * 0.75, 0.55), CFrame.new(0, 0, s.Z * 0.5 + 0.27), trim, Enum.Material.Metal)
			for _, x in { -0.2, 0.2 } do
				gadget(model, torso, Vector3.one * 0.35, CFrame.new(s.X * x, -s.Y * 0.45, s.Z * 0.5 + 0.3), glow, Enum.Material.Neon, Enum.PartType.Ball)
			end
		end
		if kit.Fins then
			for _, x in { -1, 1 } do
				gadget(model, torso, Vector3.new(0.12, s.Y * 0.8, 0.9), CFrame.new(s.X * 0.25 * x, s.Y * 0.1, s.Z * 0.5 + 0.4) * CFrame.Angles(math.rad(-25), 0, math.rad(15 * x)), glow, Enum.Material.Neon)
			end
		end
	end
	if kit.Pads then
		for _, name in { "RightUpperArm", "LeftUpperArm" } do
			local arm = model:FindFirstChild(name)
			if arm then
				local s = arm.Size
				gadget(model, arm, Vector3.new(s.X * 1.7, s.Y * 0.35, s.Z * 1.7), CFrame.new(0, s.Y * 0.4, 0), trim, Enum.Material.Metal)
			end
		end
	end
	if kit.Stripes then
		for _, name in { "RightUpperLeg", "LeftUpperLeg" } do
			local leg = model:FindFirstChild(name)
			if leg then
				local s = leg.Size
				gadget(model, leg, Vector3.new(s.X + 0.05, s.Y * 0.15, s.Z + 0.05), CFrame.new(0, 0, 0), glow, Enum.Material.Neon)
			end
		end
	end
end

local function buildRig(def)
	local kit = KITS[kitFor(def)]
	local desc = Instance.new("HumanoidDescription")
	desc.HeightScale = kit.Height
	desc.WidthScale = kit.Width
	desc.DepthScale = kit.Depth
	desc.HeadScale = kit.Head
	local color = def.Color or Color3.fromRGB(200, 200, 210)
	local dark = color:Lerp(Color3.new(0, 0, 0), 0.25)
	desc.HeadColor = color
	desc.TorsoColor = dark
	desc.LeftArmColor = color
	desc.RightArmColor = color
	desc.LeftLegColor = dark
	desc.RightLegColor = dark
	local ok, model = pcall(function()
		return Players:CreateHumanoidModelFromDescription(desc, Enum.HumanoidRigType.R15)
	end)
	if not ok or not model then
		warn("[Npc] Could not build a body, using a simple one:", model)
		model = fallbackRig(color)
	end
	-- Newer avatars use physics joints (AnimationConstraint + ball sockets). Bots are simulated on the
	-- server, so swap those for classic Motor6Ds, which every client can animate smoothly.
	local swaps = {}
	for _, d in model:GetDescendants() do
		if d:IsA("AnimationConstraint") or d:IsA("BallSocketConstraint") then
			table.insert(swaps, d)
		end
	end
	for _, d in swaps do
		if d:IsA("AnimationConstraint") and d.Attachment0 and d.Attachment1 then
			local motor = Instance.new("Motor6D")
			motor.Name = d.Name
			motor.Part0 = d.Attachment0.Parent
			motor.Part1 = d.Attachment1.Parent
			motor.C0 = d.Attachment0.CFrame
			motor.C1 = d.Attachment1.CFrame
			motor.Parent = d.Parent
		end
		d:Destroy()
	end
	model.Name = def.Name
	local humanoid = model:FindFirstChildOfClass("Humanoid")
	humanoid.DisplayDistanceType = Enum.HumanoidDisplayDistanceType.None
	humanoid.BreakJointsOnDeath = false
	humanoid.MaxHealth = 1e6
	humanoid.Health = 1e6
	humanoid:SetStateEnabled(Enum.HumanoidStateType.Dead, false)
	return model
end

-- Creates a fighter NPC in a context. Returns its combat rec.
function Npc.Spawn(ctx, def, position, team, parent)
	local model = buildRig(def)
	local scale = def.Scale or 1
	if scale ~= 1 then
		pcall(function()
			model:ScaleTo(scale)
		end)
	end
	addKit(model, def)
	Visuals.Dress(model, def.Loadout, def.Paint, scale)
	for _, part in model:GetDescendants() do
		if part:IsA("BasePart") then
			part.CollisionGroup = "NpcBody" -- bots drop through soft platforms instead of bonking their heads
		end
	end
	local spawnPos = position + Vector3.new(0, 3 * (scale - 1), 0)
	if ctx.PlaneZ then
		model:PivotTo(CFrame.lookAt(spawnPos, spawnPos + Vector3.new(ctx.Origin.X >= spawnPos.X and 1 or -1, 0, 0)))
	else
		model:PivotTo(CFrame.new(spawnPos))
	end
	model.Parent = parent or ctx.Model or Workspace
	local root = model:FindFirstChild("HumanoidRootPart")
	if root then
		pcall(function()
			root:SetNetworkOwner(nil)
		end)
	end
	CollectionService:AddTag(model, "NpcFighter") -- clients give it a walk cycle
	local sub = def.Boss and "★ BOSS ★" or (def.IsDummy and "Hit me!" or "")
	Visuals.Tag(model, def.Name, sub, def.Boss and Color3.fromRGB(255, 90, 90) or Color3.new(1, 1, 1), Color3.fromRGB(255, 200, 80))
	local rec = Combat.Register(model, {
		Name = def.Name,
		Ctx = ctx,
		Loadout = def.Loadout,
		Team = team,
		IsNpc = true,
		IsDummy = def.IsDummy,
		Weight = def.Weight,
		SpeedMult = def.Speed,
		Scale = scale,
	})
	rec.Def = def
	Combat.SetCtx(rec, ctx)
	if def.IsDummy then
		Visuals.SetDamageTag(model, 0, true)
	else
		Npc.StartAI(rec)
	end
	return rec
end

local function nearestEnemy(rec)
	local best, bestDist = nil, math.huge
	for _, other in Combat.All() do
		if other ~= rec and other.Ctx == rec.Ctx and not other.Out and not other.IsDummy and Combat.Alive(other) and (not rec.Team or other.Team ~= rec.Team) then
			local d = (other.Root.Position - rec.Root.Position).Magnitude
			if d < bestDist then
				best, bestDist = other, d
			end
		end
	end
	return best
end

local function face(rec, dirX)
	local pos = rec.Root.Position
	rec.Root.CFrame = CFrame.lookAt(pos, pos + Vector3.new(dirX, 0, 0))
end

function Npc.StartAI(rec)
	task.spawn(function()
		local skill = rec.Def.Skill or 0.5
		local airJumps = 0
		local lastJump = 0
		local dropUntil = 0
		local ghost = false
		local function setGhost(on)
			if on == ghost then
				return
			end
			ghost = on
			for _, part in rec.Model:GetDescendants() do
				if part:IsA("BasePart") then
					part.CollisionGroup = on and "NpcGhost" or "NpcBody"
				end
			end
		end
		local rng = Random.new()
		while rec.Model.Parent and Combat.Get(rec.Model) == rec do
			task.wait(0.1)
			local humanoid, root = rec.Humanoid, rec.Root
			if not humanoid or not root or not root.Parent then
				break
			end
			local t = os.clock()
			if rec.Out or rec.KOing or rec.Locked or rec.StunUntil > t or rec.FrozenUntil > t then
				humanoid:Move(Vector3.zero)
				continue
			end
			local ctx = rec.Ctx
			if not ctx.PlaneZ then
				continue
			end
			local pos = root.Position
			local grounded = humanoid.FloorMaterial ~= Enum.Material.Air
			if grounded then
				airJumps = Combat.LegStats(rec).AirJumps
			end
			-- One-way platforms for bots: pass through while rising or dropping, solid when landing.
			setGhost(root.AssemblyLinearVelocity.Y > 1 or t < dropUntil)

			-- Off the stage: head back and jump.
			local offX = pos.X - ctx.Origin.X
			local offStage = math.abs(offX) > ctx.StageHalf + 1 or (math.abs(offX) > ctx.StageHalf - 1 and pos.Y < ctx.Origin.Y - 1)
			if offStage then
				local dirX = offX > 0 and -1 or 1
				humanoid:Move(Vector3.new(dirX, 0, 0))
				if grounded then
					humanoid.Jump = true
				elseif root.AssemblyLinearVelocity.Y < 4 and airJumps > 0 and t - lastJump > 0.35 then
					airJumps -= 1
					lastJump = t
					root.AssemblyLinearVelocity = Vector3.new(dirX * humanoid.WalkSpeed * 1.3, humanoid.JumpPower, 0)
				end
				continue
			end

			local target = nearestEnemy(rec)
			if not target then
				humanoid:Move(Vector3.zero)
				continue
			end
			local tp = target.Root.Position
			local dx, dy = tp.X - pos.X, tp.Y - pos.Y
			local dist = math.abs(dx)
			local dirX = dx >= 0 and 1 or -1
			local reach = 4.5 * rec.Scale + target.HitRadius
			local nearEdge = math.abs(pos.X + dirX * 3 - ctx.Origin.X) > ctx.StageHalf - 2
			if dist < 2.6 and math.abs(dy) < 3 and not nearEdge then
				humanoid:Move(Vector3.new(-dirX, 0, 0)) -- too close: step back to punching distance
			elseif dist > reach * 0.8 and not (nearEdge and grounded and dy < 2) then
				humanoid:Move(Vector3.new(dirX, 0, 0))
			else
				humanoid:Move(Vector3.zero)
			end
			-- Follow the target up onto platforms (jump + air jumps) or drop down through them.
			if dy > 5 and grounded and t - lastJump > 1.1 and target.Humanoid.FloorMaterial ~= Enum.Material.Air then
				humanoid.Jump = true
				lastJump = t
			elseif dy > 3 and not grounded and airJumps > 0 and root.AssemblyLinearVelocity.Y < 4 and t - lastJump > 0.3 then
				airJumps -= 1
				lastJump = t
				root.AssemblyLinearVelocity = Vector3.new(dirX * humanoid.WalkSpeed, humanoid.JumpPower, 0)
			elseif dy < -5 and grounded and pos.Y - ctx.Origin.Y > 6 then
				dropUntil = t + 0.45
			end

			if rng:NextNumber() < skill * 0.55 then
				local special = Config.Parts[rec.Loadout.Head].Move
				local heavy = Config.Parts[rec.Loadout.Arms].Move
				local level = math.abs(dy) < 4 * rec.Scale
				local kind
				if dist < reach and level then
					local roll = rng:NextNumber()
					if target.Damage > 60 and roll < 0.55 then
						kind = "Heavy"
					elseif roll < 0.2 then
						kind = "Special"
					else
						kind = "Light"
					end
				elseif
					(special.Type == "Projectile" and level and dist < special.Speed * special.Life)
					or (special.Type == "Strike" and dist < special.Range)
					or (special.Type == "Pull" and dist < special.Radius * rec.Scale)
				then
					kind = "Special"
				elseif level and ((heavy.Range or 0) >= 9 and dist < heavy.Range * rec.Scale + 1 or heavy.Type == "Projectile") then
					kind = "Heavy"
				end
				if kind then
					face(rec, dirX)
					Combat.Attack(rec, kind)
				end
			end
			if dist < 7 and rng:NextNumber() < skill * 0.04 then
				Combat.Dodge(rec)
			end
		end
	end)
end

-- Matchmaking bot with a random build.
function Npc.RandomBot(rng)
	local function pick(slot)
		local list = Config.PartOrder[slot]
		return list[rng:NextInteger(1, #list)]
	end
	return {
		Name = Config.BotNames[rng:NextInteger(1, #Config.BotNames)],
		Loadout = { Head = pick("Head"), Arms = pick("Arms"), Legs = pick("Legs") },
		Color = Color3.fromHSV(rng:NextNumber(), 0.55, 0.9),
		Kit = KIT_ORDER[rng:NextInteger(1, #KIT_ORDER)],
		Scale = 1,
		Weight = 1,
		Speed = 0.9,
		Skill = 0.6,
	}
end

-- Training dummy in the lobby: takes hits, shows %, walks itself back home.
function Npc.SpawnDummy(position, parent)
	local def = {
		Name = "Training Dummy",
		Loadout = { Head = "Bolt", Arms = "Gloves", Legs = "Treads" },
		Color = Color3.fromRGB(255, 200, 120),
		Weight = 0.55,
		Speed = 0,
		IsDummy = true,
	}
	local rec = Npc.Spawn(Combat.LobbyCtx, def, position, nil, parent)
	local home = CFrame.new(position)
	task.spawn(function()
		while rec.Model.Parent do
			task.wait(0.5)
			local root = rec.Root
			if not root or not root.Parent then
				break
			end
			local idle = os.clock() - rec.LastHitAt
			local far = (root.Position - home.Position).Magnitude > 4
			if root.Position.Y < -40 or (far and idle > 2.5) then
				Combat.Respawn(rec, home, 0)
			elseif idle > 8 and rec.Damage > 0 then
				Combat.SetDamage(rec, 0)
			end
		end
	end)
	return rec
end

return Npc
