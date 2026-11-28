-- The fighting engine. Every fighter (player, bot, boss, training dummy) is a "rec".
-- Hits add damage %; the more % you have, the farther you fly. Leaving the blast zone = KO.
local Debris = game:GetService("Debris")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")
local TweenService = game:GetService("TweenService")
local Workspace = game:GetService("Workspace")

local Config = require(ReplicatedStorage.Shared.Config)
local Remotes = require(ReplicatedStorage.Shared.Remotes)
local Visuals = require(script.Parent.Visuals)

local F = Config.Fight

local Combat = {}
Combat.LobbyCtx = { Lobby = true, Name = "Lobby" }
Combat.Hooks = {} -- OnDamage(attacker, target, amount), OnSpecial(rec)

local fighters = {} -- [Model] = rec

local fx = Instance.new("Folder")
fx.Name = "FX"
fx.Parent = Workspace

local function now()
	return os.clock()
end

local function alive(rec)
	return rec.Root ~= nil and rec.Root.Parent ~= nil and rec.Humanoid ~= nil and rec.Humanoid.Health > 0
end
Combat.Alive = alive

local function legsStats(rec)
	local legs = Config.Parts[rec.Loadout.Legs]
	return legs and legs.Stats or Config.Parts.Sneakers.Stats
end
Combat.LegStats = legsStats

-- Sends an effect to everyone who can see this fight.
local function notifyCtx(ctx, payload)
	if ctx.Lobby then
		Remotes.Notify:FireAllClients(payload)
		return
	end
	for _, rec in fighters do
		if rec.Player and rec.Ctx == ctx then
			Remotes.Notify:FireClient(rec.Player, payload)
		end
	end
end
Combat.NotifyCtx = notifyCtx

local function flash(position, radius, color, duration)
	local ball = Visuals.Part({
		Name = "Flash",
		Shape = Enum.PartType.Ball,
		Size = Vector3.one * radius,
		Color = color,
		Material = Enum.Material.Neon,
		Transparency = 0.35,
		CanCollide = false,
		CanQuery = false,
		CanTouch = false,
		CastShadow = false,
		CFrame = CFrame.new(position),
		Parent = fx,
	})
	TweenService:Create(ball, TweenInfo.new(duration or 0.22), { Size = Vector3.one * radius * 2, Transparency = 1 }):Play()
	Debris:AddItem(ball, (duration or 0.22) + 0.05)
end
Combat.Flash = flash

local function highlight(rec, seconds, color)
	local h = Instance.new("Highlight")
	h.Name = "FXHighlight"
	h.FillColor = color
	h.FillTransparency = 0.55
	h.OutlineColor = color
	h.OutlineTransparency = 0
	h.DepthMode = Enum.HighlightDepthMode.Occluded
	h.Parent = rec.Model
	Debris:AddItem(h, seconds)
end

-- Registration -------------------------------------------------------------------------------
function Combat.Register(model, opts)
	local rec = {
		Model = model,
		Player = opts.Player,
		Name = opts.Name or model.Name,
		Humanoid = model:FindFirstChildOfClass("Humanoid"),
		Root = model:FindFirstChild("HumanoidRootPart"),
		Ctx = opts.Ctx or Combat.LobbyCtx,
		Loadout = opts.Loadout,
		Team = opts.Team,
		IsDummy = opts.IsDummy == true,
		IsNpc = opts.IsNpc == true,
		WeightMult = opts.Weight or 1,
		SpeedMult = opts.SpeedMult or 1,
		Scale = opts.Scale or 1,
		HitRadius = 1.6 * (opts.Scale or 1),
		Damage = 0,
		Cool = {},
		BusyUntil = 0,
		InvulnUntil = 0,
		StunUntil = 0,
		FrozenUntil = 0,
		LastHitAt = 0,
		Locked = false,
	}
	fighters[model] = rec
	model.AncestryChanged:Connect(function()
		if not model:IsDescendantOf(Workspace) and fighters[model] == rec then
			fighters[model] = nil
		end
	end)
	model:SetAttribute("Damage", 0)
	Combat.ApplyStats(rec)
	return rec
end

function Combat.Get(model)
	return model and fighters[model]
end

function Combat.ForPlayer(player)
	return player.Character and fighters[player.Character]
end

function Combat.All()
	return fighters
end

-- Speed and jump from the legs, or 0 while frozen / locked (countdowns, dialogue).
function Combat.ApplyStats(rec)
	local humanoid = rec.Humanoid
	if not humanoid then
		return
	end
	local stats = legsStats(rec)
	humanoid.UseJumpPower = true
	if rec.Locked or rec.FrozenUntil > now() then
		humanoid.WalkSpeed = 0
		humanoid.JumpPower = 0
	else
		humanoid.WalkSpeed = stats.Speed * rec.SpeedMult
		humanoid.JumpPower = stats.JumpPower
	end
end

function Combat.SetLocked(rec, locked)
	rec.Locked = locked
	Combat.ApplyStats(rec)
end

function Combat.SetCtx(rec, ctx)
	rec.Ctx = ctx
	rec.Damage = 0
	rec.KOing = false
	rec.KOGraceUntil = now() + 1.5 -- a teleport takes a moment to reach the server; no instant KO
	rec.Out = false
	rec.Model:SetAttribute("Damage", 0)
	Visuals.SetDamageTag(rec.Model, 0, not ctx.Lobby)
end

local function weight(rec)
	return legsStats(rec).Weight * rec.WeightMult
end

local function setDamage(rec, value)
	rec.Damage = math.clamp(value, 0, F.MaxDamage)
	rec.Model:SetAttribute("Damage", rec.Damage)
	Visuals.SetDamageTag(rec.Model, rec.Damage, not rec.Ctx.Lobby or rec.IsDummy)
end
Combat.SetDamage = setDamage

-- Direction helpers (arenas are flat: everything moves along X) ----------------------------
local function facing(rec)
	local look = rec.Root.CFrame.LookVector
	if rec.Ctx.PlaneZ then
		return Vector3.new(look.X >= 0 and 1 or -1, 0, 0)
	end
	local flat = Vector3.new(look.X, 0, look.Z)
	if flat.Magnitude < 0.1 then
		return Vector3.new(0, 0, -1)
	end
	return flat.Unit
end

local function away(rec, fromPos, toPos)
	local d = toPos - fromPos
	if rec.Ctx.PlaneZ then
		if math.abs(d.X) < 0.05 then
			return facing(rec)
		end
		return Vector3.new(d.X >= 0 and 1 or -1, 0, 0)
	end
	local flat = Vector3.new(d.X, 0, d.Z)
	if flat.Magnitude < 0.1 then
		return facing(rec)
	end
	return flat.Unit
end

local function canHit(attacker, target)
	if target == attacker or target.Out or target.KOing or not alive(target) then
		return false
	end
	if target.Ctx ~= attacker.Ctx or attacker.IsDummy then
		return false
	end
	if attacker.Ctx.Lobby and not target.IsDummy then
		return false -- the lobby is safe: you can only hit training dummies
	end
	if attacker.Team and attacker.Team == target.Team then
		return false
	end
	if target.InvulnUntil > now() then
		return false
	end
	if target.Locked and not target.IsDummy then
		return false
	end
	return true
end

local function targetsNear(attacker, point, radius)
	local list = {}
	for _, target in fighters do
		if canHit(attacker, target) and (target.Root.Position - point).Magnitude <= radius + target.HitRadius then
			table.insert(list, target)
		end
	end
	return list
end

-- Hits and launches ------------------------------------------------------------------------------
function Combat.Launch(rec, velocity, stun)
	rec.StunUntil = now() + stun
	if rec.Player then
		Remotes.Knockback:FireClient(rec.Player, velocity, stun)
		return
	end
	local token = {}
	rec.StunToken = token
	rec.Humanoid.PlatformStand = true
	rec.Root.AssemblyLinearVelocity = velocity
	task.delay(stun, function()
		if rec.StunToken == token and rec.Humanoid.Parent then
			rec.Humanoid.PlatformStand = false
		end
	end)
end

function Combat.Freeze(rec, seconds)
	rec.FrozenUntil = now() + seconds
	local old = rec.Model:FindFirstChild("IceBlock")
	if old then
		old:Destroy()
	end
	local ice = Visuals.Part({
		Name = "IceBlock",
		Anchored = false,
		Size = Vector3.new(4, 6, 4) * rec.Scale,
		Color = Color3.fromRGB(170, 230, 255),
		Material = Enum.Material.Ice,
		Transparency = 0.4,
		CanCollide = false,
		CanQuery = false,
		CanTouch = false,
		Massless = true,
		CFrame = rec.Root.CFrame,
		Parent = rec.Model,
	})
	local weld = Instance.new("WeldConstraint")
	weld.Part0 = rec.Root
	weld.Part1 = ice
	weld.Parent = ice
	Combat.ApplyStats(rec)
	task.delay(seconds, function()
		if rec.FrozenUntil <= now() + 0.02 then
			if ice.Parent then
				ice:Destroy()
			end
			Combat.ApplyStats(rec)
		end
	end)
end

-- opts: Damage, Speed (fixed launch speed), Angle
function Combat.Hit(attacker, target, move, dir, opts)
	opts = opts or {}
	local amount = opts.Damage or move.Damage
	setDamage(target, target.Damage + amount)
	if Combat.Hooks.OnDamage then
		Combat.Hooks.OnDamage(attacker, target, amount)
	end
	target.LastHitBy = attacker
	target.LastHitAt = now()

	local speed = opts.Speed or (move.Base + move.Growth * target.Damage) * weight(target)
	local angle = math.rad(opts.Angle or move.Angle or 30)
	local flat = Vector3.new(dir.X, 0, dir.Z)
	if flat.Magnitude < 0.01 then
		flat = Vector3.new(1, 0, 0)
	end
	flat = flat.Unit
	local velocity = flat * math.cos(angle) * speed + Vector3.new(0, math.sin(angle) * speed, 0)
	local stun = math.clamp(F.HitstunBase + speed * F.HitstunPerSpeed, F.HitstunBase, F.HitstunMax)
	Combat.Launch(target, velocity, stun)
	if move.Freeze then
		Combat.Freeze(target, move.Freeze)
	end
	notifyCtx(attacker.Ctx, {
		Type = "Hit",
		Position = target.Root.Position,
		Amount = amount,
		Power = speed,
		Color = move.Color,
		Victim = target.Model,
		Attacker = attacker.Model,
	})
end

-- Moves ---------------------------------------------------------------------------------------
local function spawnProjectile(rec, move, dir)
	local scale = rec.Scale
	local start = rec.Root.Position + dir * (2 * scale) + Vector3.new(0, 0.6 * scale, 0)
	local size = move.Radius * scale
	local ball = Visuals.Part({
		Name = "Projectile",
		Shape = Enum.PartType.Ball,
		Size = Vector3.one * size,
		Color = move.Color,
		Material = Enum.Material.Neon,
		CanCollide = false,
		CanQuery = false,
		CanTouch = false,
		CastShadow = false,
		CFrame = CFrame.new(start),
		Parent = fx,
	})
	local light = Instance.new("PointLight")
	light.Color = move.Color
	light.Range = 10
	light.Brightness = 2
	light.Parent = ball
	local elapsed = 0
	local conn
	local function finish()
		if conn then
			conn:Disconnect()
			conn = nil
		end
		if ball.Parent then
			flash(ball.Position, size, move.Color, 0.15)
			ball:Destroy()
		end
	end
	conn = RunService.Heartbeat:Connect(function(dt)
		elapsed += dt
		if elapsed > move.Life or not ball.Parent then
			finish()
			return
		end
		local pos = ball.Position + dir * move.Speed * dt
		ball.CFrame = CFrame.new(pos)
		local hits = targetsNear(rec, pos, size * 0.5)
		if hits[1] then
			Combat.Hit(rec, hits[1], move, dir)
			finish()
		end
	end)
end

local function strike(rec, move)
	local range = move.Range * rec.Scale
	local origin = rec.Root.Position
	local best, bestDist = nil, range
	for _, target in fighters do
		if canHit(rec, target) then
			local d = (target.Root.Position - origin).Magnitude
			if d < bestDist then
				best, bestDist = target, d
			end
		end
	end
	local spot = best and best.Root.Position or (origin + facing(rec) * range * 0.4)
	local marker = Visuals.Part({
		Name = "StrikeMarker",
		Shape = Enum.PartType.Cylinder,
		Size = Vector3.new(0.3, move.Radius * 2, move.Radius * 2),
		CFrame = CFrame.new(spot - Vector3.new(0, 2.5, 0)) * CFrame.Angles(0, 0, math.rad(90)),
		Color = move.Color,
		Material = Enum.Material.Neon,
		Transparency = 0.45,
		CanCollide = false,
		CanQuery = false,
		CanTouch = false,
		Parent = fx,
	})
	Debris:AddItem(marker, move.Delay + 0.1)
	task.wait(move.Delay)
	if not alive(rec) then
		return
	end
	local bolt = Visuals.Part({
		Name = "Bolt",
		Size = Vector3.new(1.4, 40, 1.4),
		CFrame = CFrame.new(spot + Vector3.new(0, 18, 0)),
		Color = move.Color,
		Material = Enum.Material.Neon,
		CanCollide = false,
		CanQuery = false,
		CanTouch = false,
		Parent = fx,
	})
	Debris:AddItem(bolt, 0.18)
	flash(spot, move.Radius, move.Color, 0.25)
	for _, target in targetsNear(rec, spot, move.Radius) do
		Combat.Hit(rec, target, move, away(rec, rec.Root.Position, target.Root.Position))
	end
end

local function execute(rec, move)
	local started = now()
	if move.Windup > 0 then
		task.wait(move.Windup)
	end
	-- Getting hit during the wind-up cancels the move (like a real fighting game).
	if not alive(rec) or rec.LastHitAt > started or rec.Out or rec.KOing then
		return
	end
	local root = rec.Root
	local scale = rec.Scale
	local dir = facing(rec)
	local kind = move.Type
	if kind == "Melee" or kind == "Throw" then
		local center = root.Position + dir * (move.Range * 0.6 * scale)
		flash(center, move.Radius * scale, move.Color)
		for _, target in targetsNear(rec, center, move.Radius * scale) do
			Combat.Hit(rec, target, move, kind == "Throw" and -dir or dir)
		end
	elseif kind == "Multi" then
		for i = 1, move.Hits do
			if not alive(rec) or rec.StunUntil > now() then
				return
			end
			local center = rec.Root.Position + dir * (move.Range * 0.6 * scale)
			flash(center, move.Radius * scale * 0.8, move.Color, 0.1)
			for _, target in targetsNear(rec, center, move.Radius * scale) do
				if i < move.Hits then
					Combat.Hit(rec, target, move, dir, { Speed = 10, Angle = 10 })
				else
					Combat.Hit(rec, target, move, dir)
				end
			end
			if i < move.Hits then
				task.wait(move.Interval)
			end
		end
	elseif kind == "Burst" then
		flash(root.Position, move.Radius * scale, move.Color, 0.3)
		for _, target in targetsNear(rec, root.Position, move.Radius * scale) do
			Combat.Hit(rec, target, move, away(rec, root.Position, target.Root.Position))
		end
	elseif kind == "Pull" then
		flash(root.Position, move.Radius * scale, move.Color, 0.35)
		for _, target in targetsNear(rec, root.Position, move.Radius * scale) do
			local toward = away(rec, target.Root.Position, root.Position)
			Combat.Hit(rec, target, move, toward, { Speed = move.Pull, Angle = 12 })
		end
	elseif kind == "Projectile" then
		spawnProjectile(rec, move, dir)
	elseif kind == "Strike" then
		strike(rec, move)
	end
end

-- kind: "Light" (jab), "Heavy" (arms), "Special" (head). Returns true if the move started.
function Combat.Attack(rec, kind)
	if not rec or not alive(rec) or rec.Locked or rec.Out or rec.KOing or rec.IsDummy then
		return false
	end
	local t = now()
	if rec.StunUntil > t or rec.FrozenUntil > t or rec.BusyUntil > t then
		return false
	end
	local move
	if kind == "Light" then
		move = Config.Light
	elseif kind == "Heavy" then
		local part = Config.Parts[rec.Loadout.Arms]
		move = part and part.Move
	elseif kind == "Special" then
		local part = Config.Parts[rec.Loadout.Head]
		move = part and part.Move
	end
	if not move or (rec.Cool[kind] or 0) > t then
		return false
	end
	rec.Cool[kind] = t + move.Cooldown
	rec.BusyUntil = t + move.Windup + 0.08
	if kind == "Special" and Combat.Hooks.OnSpecial then
		Combat.Hooks.OnSpecial(rec)
	end
	if rec.Player then
		Remotes.Notify:FireClient(rec.Player, { Type = "Cooldown", Kind = kind, Seconds = move.Cooldown })
	end
	local animKey = kind == "Light" and "Light" or (kind == "Heavy" and rec.Loadout.Arms or rec.Loadout.Head)
	notifyCtx(rec.Ctx, { Type = "Anim", Model = rec.Model, Anim = animKey })
	task.spawn(execute, rec, move)
	return true
end

function Combat.Dodge(rec)
	if not rec or not alive(rec) or rec.Locked or rec.Out or rec.KOing then
		return false
	end
	local t = now()
	if rec.StunUntil > t or rec.FrozenUntil > t then
		return false
	end
	if (rec.Cool.Dodge or 0) > t then
		return false
	end
	rec.Cool.Dodge = t + (legsStats(rec).DodgeCooldown or F.DodgeCooldown)
	rec.InvulnUntil = math.max(rec.InvulnUntil, t + F.DodgeTime)
	highlight(rec, F.DodgeTime, Color3.new(1, 1, 1))
	notifyCtx(rec.Ctx, { Type = "Anim", Model = rec.Model, Anim = "Dodge" })
	return true
end

function Combat.Respawn(rec, cframe, invuln)
	setDamage(rec, 0)
	rec.StunUntil = 0
	rec.FrozenUntil = 0
	rec.StunToken = nil
	rec.LastHitBy = nil
	rec.KOing = false
	local seconds = invuln or F.RespawnInvuln
	rec.KOGraceUntil = now() + 1.5
	rec.InvulnUntil = now() + seconds
	highlight(rec, seconds, Color3.fromRGB(255, 240, 120))
	local ice = rec.Model:FindFirstChild("IceBlock")
	if ice then
		ice:Destroy()
	end
	if rec.Root then
		rec.Root.Anchored = false -- un-park after a KO
		if not rec.Player then
			-- Anchoring drops manual network ownership; give the NPC back to the server.
			pcall(function()
				rec.Root:SetNetworkOwner(nil)
			end)
		end
		rec.Root.AssemblyLinearVelocity = Vector3.zero
	end
	rec.Model:PivotTo(cframe)
	if rec.Player then
		Remotes.Notify:FireClient(rec.Player, { Type = "Respawned" })
	elseif rec.Humanoid then
		rec.Humanoid.PlatformStand = false
	end
	Combat.ApplyStats(rec)
end

-- Blast zones + keeping NPCs on the fight plane -------------------------------------------------
RunService.Heartbeat:Connect(function()
	for _, rec in fighters do
		local ctx = rec.Ctx
		if ctx.Bounds and not rec.Out and not rec.KOing and rec.Root and rec.Root.Parent and (rec.KOGraceUntil or 0) < now() then
			local p = rec.Root.Position
			local b = ctx.Bounds
			if p.X < b.MinX or p.X > b.MaxX or p.Y < b.MinY or p.Y > b.MaxY then
				rec.KOing = true
				if ctx.OnKO then
					task.spawn(ctx.OnKO, rec, p)
				end
			elseif not rec.Player and ctx.PlaneZ and math.abs(p.Z - ctx.PlaneZ) > 0.3 then
				rec.Root.CFrame = rec.Root.CFrame + Vector3.new(0, 0, ctx.PlaneZ - p.Z)
			end
		end
	end
end)

Remotes.Attack.OnServerEvent:Connect(function(player, kind)
	if kind == "Light" or kind == "Heavy" or kind == "Special" then
		Combat.Attack(Combat.ForPlayer(player), kind)
	end
end)

Remotes.Dodge.OnServerEvent:Connect(function(player)
	Combat.Dodge(Combat.ForPlayer(player))
end)

Players.PlayerRemoving:Connect(function(player)
	local character = player.Character
	if character then
		fighters[character] = nil
	end
end)

return Combat
