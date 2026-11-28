-- Plays the Mix & Smash Animation Pack (src/shared/AnimPack.luau) on every fighter this client sees.
--
-- In a fight the whole body is posed in layers:
--   base   = guard stance (breathing + boxer's bounce), shuffle-steps when moving,
--            a tucked pose in the air, or a tumble when launched
--   action = the keyframed attack / dodge / reaction on top, with easing curves and
--            overlapping action (forearms whip after the shoulder, the head settles last)
-- Every change of pose is smoothed, so nothing ever snaps. In the lobby only the upper body is
-- posed while an attack plays, over Roblox's own walk animation.
local CollectionService = game:GetService("CollectionService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")
local TweenService = game:GetService("TweenService")
local Workspace = game:GetService("Workspace")

local Config = require(ReplicatedStorage.Shared.Config)
local Pack = require(ReplicatedStorage.Shared.AnimPack)
local Remotes = require(ReplicatedStorage.Shared.Remotes)

local A, P = Pack.A, Pack.P
local JOINTS, UPPER, LAG = Pack.Joints, Pack.Upper, Pack.Lag
local GUARD, AIR, TUMBLE, ANIMS = Pack.Guard, Pack.Air, Pack.Tumble, Pack.Anims
local IDENTITY = CFrame.new()
local DEFAULT_EASE = { Enum.EasingStyle.Sine, Enum.EasingDirection.InOut }

local state = {} -- [Model] = per-fighter animation state

local function info(model)
	local s = state[model]
	if not s then
		s = { Pose = {}, Applied = {}, Weight = 0, Phase = math.random() * 10, TumbleUntil = 0, Move = 0, Step = 0 }
		state[model] = s
	end
	return s
end

local function motors(model, s)
	local cached = s.Motors
	if cached and cached.RS and cached.RS:IsDescendantOf(model) then
		return cached
	end
	cached = {}
	for joint, spec in JOINTS do
		local part = model:FindFirstChild(spec[1])
		local motor = part and part:FindFirstChild(spec[2])
		if motor and (motor:IsA("Motor6D") or motor:IsA("AnimationConstraint")) then
			cached[joint] = motor
		end
	end
	if cached.RS and cached.W then
		s.Motors = cached
		s.Pose = {}
		s.Applied = {}
	end
	return cached
end

-- Glowing streaks behind the hands and feet while an attack plays ---------------------------------
local TRAIL_LIMBS = { "RightHand", "LeftHand", "RightFoot", "LeftFoot" }
local function trails(model, s)
	if s.Trails then
		return s.Trails
	end
	s.Trails = {}
	for _, limbName in TRAIL_LIMBS do
		local limb = model:FindFirstChild(limbName)
		if limb and limb:IsA("BasePart") then
			local a0 = Instance.new("Attachment")
			a0.Position = Vector3.new(0, 0.35, 0)
			a0.Parent = limb
			local a1 = Instance.new("Attachment")
			a1.Position = Vector3.new(0, -0.35, 0)
			a1.Parent = limb
			local trail = Instance.new("Trail")
			trail.Attachment0 = a0
			trail.Attachment1 = a1
			trail.Lifetime = 0.18
			trail.MinLength = 0.05
			trail.FaceCamera = true
			trail.LightEmission = 1
			trail.Transparency = NumberSequence.new(0.2, 1)
			trail.WidthScale = NumberSequence.new(1, 0.1)
			trail.Enabled = false
			trail.Parent = limb
			table.insert(s.Trails, trail)
		end
	end
	return s.Trails
end

local COMBO = { "Jab", "Cross", "LeadHook", "RearHook" }
local QUIET = { Flinch = true, BodyFlinch = true, Hurt = true, Dodge = true }
local function streak(model, s, key, seconds)
	if QUIET[key] then
		return
	end
	local part = Config.Parts[key]
	local color = part and part.Move and part.Move.Color or Color3.new(1, 1, 1)
	local token = {}
	s.TrailToken = token
	for _, trail in trails(model, s) do
		trail.Color = ColorSequence.new(color)
		trail.Enabled = true
	end
	task.delay(seconds, function()
		if s.TrailToken == token then
			for _, trail in trails(model, s) do
				trail.Enabled = false
			end
		end
	end)
end

local function play(model, key)
	if not model or not model:IsA("Model") then
		return
	end
	local s = info(model)
	if key == "Light" then
		-- Clicking strings a boxing combination: jab, cross, lead hook, rear hook.
		local now = os.clock()
		if now - (s.LastLight or 0) > 0.9 then
			s.Combo = 0
		end
		s.LastLight = now
		s.Combo = (s.Combo or 0) % #COMBO + 1
		key = COMBO[s.Combo]
	end
	local frames = ANIMS[key]
	if frames then
		s.Anim = { Frames = frames, Start = os.clock(), Key = key }
		streak(model, s, key, frames[#frames][1] * 0.65)
	end
end

-- Sampling ----------------------------------------------------------------------------------------------
local function ease(alpha, spec)
	spec = spec or DEFAULT_EASE
	return TweenService:GetValue(math.clamp(alpha, 0, 1), spec[1], spec[2])
end

-- The keyframed pose of `joint` at time t; joints a keyframe skips come from `base`.
local function sample(frames, t, joint, base)
	if t <= 0 then
		return frames[1][2][joint] or base
	end
	for i = 1, #frames - 1 do
		local a, b = frames[i], frames[i + 1]
		if t < b[1] then
			local alpha = ease((t - a[1]) / (b[1] - a[1]), b[3])
			local pa = a[2][joint] or base
			local pb = b[2][joint] or base
			return pa:Lerp(pb, alpha)
		end
	end
	return base
end

-- Roblox rounds a Transform slightly when it applies it, so compare with a small tolerance.
local function same(a, b)
	return (a.Position - b.Position).Magnitude < 1e-3 and a.LookVector:Dot(b.LookVector) > 0.99999 and a.UpVector:Dot(b.UpVector) > 0.99999
end

-- The pose Roblox's own Animator gave this joint this frame (players in the lobby).
local function animatorPose(s, joint, motor, owned)
	if owned then
		return IDENTITY
	end
	local current = motor.Transform
	local prev = s.Applied[joint]
	if prev and same(current, prev.Result) then
		return prev.Base
	end
	return current
end

-- Ground check (for the air pose and the shuffle) -----------------------------------------------------------
local rayParams = RaycastParams.new()
rayParams.FilterType = Enum.RaycastFilterType.Exclude
local function grounded(model, root, humanoid)
	if math.abs(root.AssemblyLinearVelocity.Y) > 9 then
		return false
	end
	local ignore = { model }
	for _, name in { "FX", "LocalFX" } do
		local folder = Workspace:FindFirstChild(name)
		if folder then
			table.insert(ignore, folder)
		end
	end
	rayParams.FilterDescendantsInstances = ignore
	local reach = (humanoid and humanoid.HipHeight or 2) + root.Size.Y / 2 + 1.2
	return Workspace:Raycast(root.Position, Vector3.new(0, -reach, 0), rayParams) ~= nil
end

-- The base layer for one joint.
local function basePose(joint, s, now, layer)
	if layer == "Tumble" then
		local p = TUMBLE[joint] or IDENTITY
		if joint == "RS" or joint == "LS" or joint == "RH" or joint == "LH" then
			return p * A(math.sin(now * 18 + s.Phase) * 12)
		end
		return p
	elseif layer == "Air" then
		return AIR[joint] or IDENTITY
	end
	local p = GUARD[joint] or IDENTITY
	local t = now + s.Phase
	if joint == "Root" then
		-- Boxer's bounce + a gentle side-to-side weight shift (small, so it never "pops").
		local bob = math.abs(math.sin(t * 4.2)) * 0.045 * (1 - s.Move) + math.abs(math.cos(s.Step)) * 0.06 * s.Move
		return p * P(math.sin(t * 2.1) * 0.035, bob, 0)
	elseif joint == "W" then
		return p * A(math.sin(t * 2) * 1.5, math.sin(t * 2.1) * 2)
	elseif joint == "LS" or joint == "RS" then
		return p * A(math.sin(t * 2.6 + (joint == "LS" and 0 or 1.3)) * 3)
	elseif joint == "N" then
		return p * A(math.sin(t * 2 + 0.6) * 1.5)
	elseif s.Move > 0.01 then
		-- Shuffle step: short, quick steps that keep the stance.
		local swing = math.sin(s.Step) * s.Move
		if joint == "RH" then
			return p * A(swing * 20)
		elseif joint == "LH" then
			return p * A(-swing * 20)
		elseif joint == "RK" then
			return p * A(-math.max(0, -swing) * 30)
		elseif joint == "LK" then
			return p * A(-math.max(0, swing) * 30)
		end
	end
	return p
end

local function animateModel(model, dt, now)
	local s = info(model)
	local set = motors(model, s)
	if not set.RS then
		return
	end
	local root = model:FindFirstChild("HumanoidRootPart")
	if not root then
		return
	end
	local humanoid = model:FindFirstChildOfClass("Humanoid")
	local fighting = model:GetAttribute("Fighting") == true
	local owned = CollectionService:HasTag(model, "NpcFighter") -- bots: nothing else animates them

	local anim = s.Anim
	local t = anim and (now - anim.Start) or 0
	if anim and t >= anim.Frames[#anim.Frames][1] then
		s.Anim = nil
		anim = nil
	end

	-- Which base layer?
	local layer = "Ground"
	if fighting then
		if now < s.TumbleUntil then
			layer = "Tumble"
		elseif not grounded(model, root, humanoid) then
			layer = "Air"
		end
	end
	local v = root.AssemblyLinearVelocity
	local speed = Vector3.new(v.X, 0, v.Z).Magnitude
	s.Move += (math.clamp(speed / 14, 0, 1) - s.Move) * math.min(1, dt * 10)
	s.Step += dt * (6 + speed * 0.45)

	-- How much of our pose to apply: all of it in a fight (and on bots); eased in and out for
	-- attacks in the lobby, over Roblox's own walk animation.
	local target = (fighting or anim or owned) and 1 or 0
	s.Weight += math.clamp(target - s.Weight, -dt * 6, dt * 14)
	local w = s.Weight
	-- Sharp during strikes, softer between layers (air, ground, tumble).
	local follow = 1 - math.exp(-dt * (anim and 45 or 16))

	for joint, motor in set do
		local base = animatorPose(s, joint, motor, owned)
		local lobbyLegs = not fighting and not owned and not UPPER[joint]
		if w <= 0.001 or lobbyLegs then
			-- Leave Roblox's own animation alone.
			s.Applied[joint] = { Result = base, Base = base }
			s.Pose[joint] = nil
		else
			local layerPose
			if fighting then
				layerPose = basePose(joint, s, now, layer)
			elseif owned then
				layerPose = IDENTITY -- lobby dummies stand naturally
			else
				layerPose = base
			end
			local goal = anim and sample(anim.Frames, t - (LAG[joint] or 0), joint, layerPose) or layerPose
			local smoothed = s.Pose[joint] and s.Pose[joint]:Lerp(goal, follow) or goal
			s.Pose[joint] = smoothed
			local result = (fighting or owned) and smoothed or base:Lerp(smoothed, w)
			motor.Transform = result
			s.Applied[joint] = { Result = result, Base = base }
		end
	end
end

RunService.PreSimulation:Connect(function(dt)
	local now = os.clock()
	for _, model in CollectionService:GetTagged("Fighter") do
		if model:IsA("Model") and model:IsDescendantOf(Workspace) then
			animateModel(model, dt, now)
		end
	end
	for model in state do
		if not model:IsDescendantOf(Workspace) then
			state[model] = nil
		end
	end
end)

Remotes.Notify.OnClientEvent:Connect(function(msg)
	if msg.Type == "Anim" then
		play(msg.Model, msg.Anim)
	elseif msg.Type == "Hit" then
		-- Hitlag: the attacker's swing freezes on contact, then the victim reacts.
		local hitlag = msg.Hitlag or 0.06
		local attacker = msg.Attacker and state[msg.Attacker]
		if attacker and attacker.Anim then
			attacker.Anim.Start += hitlag
		end
		local victim = msg.Victim
		if victim then
			local s = info(victim)
			if msg.Tumble then
				local stun = math.clamp(0.12 + (msg.Power or 70) * 0.0042, 0.3, 1.1)
				s.TumbleUntil = os.clock() + hitlag + stun
				task.delay(hitlag * 0.5, function()
					play(victim, "Hurt")
				end)
			else
				task.delay(hitlag * 0.5, function()
					play(victim, math.random() < 0.5 and "Flinch" or "BodyFlinch")
				end)
			end
		end
	elseif msg.Type == "KO" then
		local s = msg.Model and state[msg.Model]
		if s then
			s.TumbleUntil = 0
		end
	end
end)
