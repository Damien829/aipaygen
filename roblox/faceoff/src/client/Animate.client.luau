-- Fighting animations, made in code (no uploaded animation assets needed).
-- Every attack, every part's special move, dodges and getting hit move the fighter's real
-- body joints (R15 Motor6Ds). Each client animates everyone it can see, layered on top of
-- Roblox's own walk/idle animations. Bots and bosses also get a walk cycle.
local CollectionService = game:GetService("CollectionService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")
local Workspace = game:GetService("Workspace")

local Config = require(ReplicatedStorage.Shared.Config)
local Remotes = require(ReplicatedStorage.Shared.Remotes)

local function A(x, y, z)
	return CFrame.Angles(math.rad(x or 0), math.rad(y or 0), math.rad(z or 0))
end
local function P(x, y, z)
	return CFrame.new(x or 0, y or 0, z or 0)
end

-- Joint short names -> { body part, Motor6D } (R15)
local JOINTS = {
	RS = { "RightUpperArm", "RightShoulder" },
	LS = { "LeftUpperArm", "LeftShoulder" },
	RE = { "RightLowerArm", "RightElbow" },
	LE = { "LeftLowerArm", "LeftElbow" },
	W = { "UpperTorso", "Waist" },
	N = { "Head", "Neck" },
	RH = { "RightUpperLeg", "RightHip" },
	LH = { "LeftUpperLeg", "LeftHip" },
	RK = { "RightLowerLeg", "RightKnee" },
	LK = { "LeftLowerLeg", "LeftKnee" },
	Root = { "LowerTorso", "Root" },
}

-- Animations: keyframes { time, pose }. A pose maps joints to offsets; missing joints rest.
-- +X rotation on a shoulder/hip swings that limb forward; -X on the waist leans forward.
local ANIMS = {
	-- Jab (alternates right and left)
	Light = {
		{ 0, {} },
		{ 0.05, { RS = A(95), RE = A(5), W = A(0, -28), LS = A(20), LE = A(70) } },
		{ 0.16, { RS = A(95), RE = A(5), W = A(0, -28), LS = A(20), LE = A(70) } },
		{ 0.3, {} },
	},
	LightLeft = {
		{ 0, {} },
		{ 0.05, { LS = A(95), LE = A(5), W = A(0, 28), RS = A(20), RE = A(70) } },
		{ 0.16, { LS = A(95), LE = A(5), W = A(0, 28), RS = A(20), RE = A(70) } },
		{ 0.3, {} },
	},

	-- ARMS (heavy attacks)
	Gloves = { -- Big Punch: wind up, then a haymaker
		{ 0, {} },
		{ 0.2, { RS = A(15, 0, 20), RE = A(80), W = A(0, 45), Root = P(0, -0.35, 0.3), LS = A(40), LE = A(60) } },
		{ 0.3, { RS = A(100), RE = A(0), W = A(-15, -50), Root = P(0, -0.2, -0.6), LS = A(-20), LE = A(40), RH = A(-25), LH = A(30) } },
		{ 0.55, { RS = A(100), W = A(-15, -50), Root = P(0, -0.2, -0.6), LS = A(-20), RH = A(-25), LH = A(30) } },
		{ 0.75, {} },
	},
	Spring = { -- Boing Punch: crouch, then a full-body stretch forward
		{ 0, {} },
		{ 0.22, { RS = A(30), RE = A(110), W = A(10, 30), Root = P(0, -0.6, 0.4), RH = A(40), RK = A(-60), LH = A(40), LK = A(-60) } },
		{ 0.32, { RS = A(92), RE = A(0), LS = A(-35), W = A(-25, -35), Root = P(0, 0, -0.9), RH = A(-30), LH = A(35) } },
		{ 0.6, { RS = A(92), LS = A(-35), W = A(-25, -35), Root = P(0, 0, -0.9), RH = A(-30), LH = A(35) } },
		{ 0.8, {} },
	},
	Drill = { -- Drill Rush: three fast alternating jabs, then a big finisher
		{ 0, {} },
		{ 0.12, { RS = A(30), RE = A(90), LS = A(30), LE = A(90), W = A(-10), Root = P(0, -0.3, 0) } },
		{ 0.17, { RS = A(95), W = A(-10, -25), LS = A(30), LE = A(90) } },
		{ 0.24, { LS = A(95), W = A(-10, 25), RS = A(30), RE = A(90) } },
		{ 0.31, { RS = A(95), W = A(-10, -25), LS = A(30), LE = A(90) } },
		{ 0.4, { RS = A(100), LS = A(100), W = A(-20), Root = P(0, 0, -0.7) } },
		{ 0.65, { RS = A(100), LS = A(100), W = A(-20), Root = P(0, 0, -0.7) } },
		{ 0.85, {} },
	},
	Hammer = { -- Ground Pound: both arms overhead, then a full-body slam
		{ 0, {} },
		{ 0.32, { RS = A(170, 0, -10), LS = A(170, 0, 10), RE = A(20), LE = A(20), W = A(18), N = A(15), Root = P(0, 0.4, 0) } },
		{ 0.44, { RS = A(55), LS = A(55), W = A(-45), N = A(-15), Root = P(0, -1.1, 0), RH = A(50), RK = A(-80), LH = A(50), LK = A(-80) } },
		{ 0.75, { RS = A(55), LS = A(55), W = A(-45), Root = P(0, -1.1, 0), RH = A(50), RK = A(-80), LH = A(50), LK = A(-80) } },
		{ 0.95, {} },
	},
	Claw = { -- Grab and Toss: grab in front, then spin and fling behind
		{ 0, {} },
		{ 0.16, { RS = A(90, 0, 15), LS = A(90, 0, -15), RE = A(30), LE = A(30), W = A(-15), Root = P(0, 0, -0.4) } },
		{ 0.3, { RS = A(90, 0, 70), LS = A(90, 0, 40), W = A(0, 120), Root = P(0, -0.2, 0) } },
		{ 0.42, { RS = A(60, 0, 100), LS = A(60, 0, 80), W = A(10, 170), Root = P(0, 0, 0) } },
		{ 0.65, {} },
	},
	Rocket = { -- Rocket Fist: brace, fire, recoil
		{ 0, {} },
		{ 0.18, { RS = A(70), RE = A(90), LS = A(60), LE = A(100), W = A(0, 25), Root = P(0, -0.4, 0) } },
		{ 0.24, { RS = A(95), RE = A(0), W = A(5, -30), Root = P(0, -0.2, 0.6), N = A(10) } },
		{ 0.5, { RS = A(95), W = A(5, -30), Root = P(0, -0.2, 0.6) } },
		{ 0.7, {} },
	},

	-- HEADS (special moves)
	Bolt = { -- Zap Burst: curl up, then explode into a star pose
		{ 0, {} },
		{ 0.16, { RS = A(40, 0, -40), LS = A(40, 0, 40), RE = A(100), LE = A(100), W = A(-25), N = A(-20), Root = P(0, -0.8, 0), RH = A(40), RK = A(-70), LH = A(40), LK = A(-70) } },
		{ 0.25, { RS = A(0, 0, 115), LS = A(0, 0, -115), W = A(12), N = A(20), Root = P(0, 0.5, 0), RH = A(0, 0, 25), LH = A(0, 0, -25) } },
		{ 0.45, { RS = A(0, 0, 115), LS = A(0, 0, -115), W = A(12), N = A(20), Root = P(0, 0.5, 0), RH = A(0, 0, 25), LH = A(0, 0, -25) } },
		{ 0.65, {} },
	},
	Blaster = { -- Laser: snap into a pointing pose
		{ 0, {} },
		{ 0.06, { RS = A(92), RE = A(0), LS = A(80), LE = A(40), N = A(-5), W = A(0, -15), Root = P(0, -0.2, 0) } },
		{ 0.25, { RS = A(92), LS = A(80), LE = A(40), W = A(0, -15), Root = P(0, -0.2, 0.3) } },
		{ 0.4, {} },
	},
	Magnet = { -- Magnet Pull: reach out, then yank back
		{ 0, {} },
		{ 0.15, { RS = A(95, 0, 10), LS = A(95, 0, -10), W = A(-15), Root = P(0, 0, -0.3) } },
		{ 0.35, { RS = A(40, 0, 30), LS = A(40, 0, -30), RE = A(110), LE = A(110), W = A(20), N = A(10), Root = P(0, -0.3, 0.5), RH = A(-20), LH = A(25) } },
		{ 0.55, { RS = A(40, 0, 30), LS = A(40, 0, -30), RE = A(110), LE = A(110), W = A(20), Root = P(0, -0.3, 0.5) } },
		{ 0.75, {} },
	},
	Frost = { -- Freeze Ray: two-handed cast
		{ 0, {} },
		{ 0.1, { RS = A(60, -20), LS = A(60, 20), RE = A(60), LE = A(60), W = A(10), Root = P(0, -0.3, 0) } },
		{ 0.16, { RS = A(90, -25), LS = A(90, 25), RE = A(0), LE = A(0), W = A(-10), Root = P(0, -0.3, -0.2) } },
		{ 0.45, { RS = A(90, -25), LS = A(90, 25), W = A(-10), Root = P(0, -0.3, -0.2) } },
		{ 0.6, {} },
	},
	Dragon = { -- Fireball: rear back, then breathe fire forward
		{ 0, {} },
		{ 0.2, { W = A(30), N = A(30), RS = A(-20, 0, 30), LS = A(-20, 0, -30), Root = P(0, 0, 0.4) } },
		{ 0.3, { W = A(-35), N = A(-30), RS = A(-45, 0, 20), LS = A(-45, 0, -20), Root = P(0, -0.3, -0.6), RH = A(-20), LH = A(35) } },
		{ 0.6, { W = A(-35), N = A(-30), RS = A(-45, 0, 20), LS = A(-45, 0, -20), Root = P(0, -0.3, -0.6) } },
		{ 0.85, {} },
	},
	Thunder = { -- Thunder Strike: raise a fist to the sky, then point at the target
		{ 0, {} },
		{ 0.15, { RS = A(178), RE = A(0), N = A(30), W = A(12), LS = A(0, 0, -40), Root = P(0, 0.3, 0) } },
		{ 0.6, { RS = A(178), N = A(30), W = A(12), LS = A(0, 0, -40), Root = P(0, 0.3, 0) } },
		{ 0.72, { RS = A(75), N = A(-10), W = A(-15), LS = A(-20), Root = P(0, -0.2, -0.3) } },
		{ 0.95, {} },
	},

	-- Movement and reactions
	Dodge = {
		{ 0, {} },
		{ 0.08, { Root = P(0, -1, 0) * A(-35), RS = A(60), LS = A(60), RE = A(90), LE = A(90), RH = A(70), RK = A(-90), LH = A(70), LK = A(-90) } },
		{ 0.28, { Root = P(0, -1, 0) * A(-35), RS = A(60), LS = A(60), RE = A(90), LE = A(90), RH = A(70), RK = A(-90), LH = A(70), LK = A(-90) } },
		{ 0.4, {} },
	},
	Hurt = {
		{ 0, {} },
		{ 0.06, { W = A(28), N = A(30), RS = A(40, 0, 70), LS = A(40, 0, -70), RH = A(-20), LH = A(30) } },
		{ 0.35, { W = A(20), N = A(20), RS = A(30, 0, 60), LS = A(30, 0, -60) } },
		{ 0.5, {} },
	},
}

-- Fill in missing joints with "rest" so every keyframe can be blended.
for _, frames in ANIMS do
	for _, frame in frames do
		for joint in JOINTS do
			frame[2][joint] = frame[2][joint] or CFrame.identity
		end
	end
end

local playing = {} -- [Model] = { Frames, Start }
local trailCache = {} -- [Model] = { Trail }
local trailToken = {} -- [Model] = token
local leftNext = {} -- [Model] = bool (alternate jabs)
local applied = {} -- [Motor6D] = { Offset, Result }
local motorCache = {} -- [Model] = { [joint] = Motor6D }

local function motors(model)
	local cached = motorCache[model]
	if cached and cached.RS and cached.RS:IsDescendantOf(model) then -- rebuild if the body was swapped
		return cached
	end
	cached = {}
	local found = false
	for joint, spec in JOINTS do
		local part = model:FindFirstChild(spec[1])
		local motor = part and part:FindFirstChild(spec[2])
		-- Classic rigs use Motor6D; avatars with the newer joint system use AnimationConstraint.
		-- Both have a Transform that the Animator drives, so both can be animated the same way.
		if motor and (motor:IsA("Motor6D") or motor:IsA("AnimationConstraint")) then
			cached[joint] = motor
			found = true
		end
	end
	if not found or not cached.RS or not cached.W then
		return cached -- not fully loaded yet: don't cache, try again next time
	end
	motorCache[model] = cached
	model.AncestryChanged:Connect(function()
		if not model:IsDescendantOf(Workspace) then
			motorCache[model] = nil
			trailCache[model] = nil
			trailToken[model] = nil
			playing[model] = nil
			leftNext[model] = nil
		end
	end)
	return cached
end

-- Glowing streaks behind the hands and feet while an attack plays (only on this client).
local TRAIL_LIMBS = { "RightHand", "LeftHand", "RightFoot", "LeftFoot" }

local function trails(model)
	local cached = trailCache[model]
	if cached then
		return cached
	end
	cached = {}
	for _, limbName in TRAIL_LIMBS do
		local limb = model:FindFirstChild(limbName)
		if limb and limb:IsA("BasePart") then
			local a0 = Instance.new("Attachment")
			a0.Name = "TrailTop"
			a0.Position = Vector3.new(0, 0.35, 0)
			a0.Parent = limb
			local a1 = Instance.new("Attachment")
			a1.Name = "TrailBottom"
			a1.Position = Vector3.new(0, -0.35, 0)
			a1.Parent = limb
			local trail = Instance.new("Trail")
			trail.Attachment0 = a0
			trail.Attachment1 = a1
			trail.Lifetime = 0.22
			trail.MinLength = 0.05
			trail.FaceCamera = true
			trail.LightEmission = 1
			trail.Transparency = NumberSequence.new(0.1, 1)
			trail.WidthScale = NumberSequence.new(1, 0.2)
			trail.Enabled = false
			trail.Parent = limb
			table.insert(cached, trail)
		end
	end
	trailCache[model] = cached
	return cached
end

local TRAIL_COLORS = {
	Light = Color3.fromRGB(255, 255, 255),
	LightLeft = Color3.fromRGB(255, 255, 255),
	Dodge = Color3.fromRGB(120, 210, 255),
}
local function streak(model, key, seconds)
	if key == "Hurt" then
		return
	end
	local color = TRAIL_COLORS[key]
	if not color then
		local part = Config.Parts[key]
		color = part and part.Move and part.Move.Color or Color3.fromRGB(255, 220, 120)
	end
	local token = {}
	trailToken[model] = token
	for _, trail in trails(model) do
		trail.Color = ColorSequence.new(color)
		trail.Enabled = true
	end
	task.delay(seconds, function()
		if trailToken[model] == token then
			for _, trail in trails(model) do
				trail.Enabled = false
			end
		end
	end)
end

local function play(model, key)
	if not model or not model:IsA("Model") then
		return
	end
	if key == "Light" then
		if leftNext[model] then
			key = "LightLeft"
		end
		leftNext[model] = not leftNext[model]
	end
	local frames = ANIMS[key]
	if frames then
		motors(model)
		playing[model] = { Frames = frames, Start = os.clock() }
		streak(model, key, frames[#frames][1])
	end
end

local function sample(frames, t)
	local last = frames[#frames]
	if t >= last[1] then
		return nil -- finished
	end
	for i = 1, #frames - 1 do
		local a, b = frames[i], frames[i + 1]
		if t >= a[1] and t < b[1] then
			local alpha = (t - a[1]) / (b[1] - a[1])
			alpha = alpha * alpha * (3 - 2 * alpha) -- smoothstep
			return a[2], b[2], alpha
		end
	end
	return nil
end

-- Writes our offset on top of whatever Roblox's Animator set this frame, without ever stacking
-- up on joints the Animator doesn't touch.
local function setOffset(motor, offset)
	local current = motor.Transform
	local prev = applied[motor]
	if prev and current == prev.Result then
		current = current * prev.Offset:Inverse()
	end
	local result = current * offset
	motor.Transform = result
	applied[motor] = { Offset = offset, Result = result }
end

local walkPhase = {} -- [Model] = number

RunService.PreSimulation:Connect(function(dt)
	local now = os.clock()
	-- Attack / dodge / hurt animations
	for model, anim in playing do
		local set = motorCache[model]
		if not set or not model.Parent then
			playing[model] = nil
			continue
		end
		local a, b, alpha = sample(anim.Frames, now - anim.Start)
		if not a then
			playing[model] = nil
			for _, motor in set do
				setOffset(motor, CFrame.identity)
			end
		else
			for joint, motor in set do
				setOffset(motor, a[joint]:Lerp(b[joint], alpha))
			end
		end
	end
	-- Walk cycle for bots and bosses (they have no Roblox Animate script)
	for _, model in CollectionService:GetTagged("NpcFighter") do
		do
			do
				if model:IsA("Model") and model:IsDescendantOf(Workspace) and not playing[model] then
					local root = model:FindFirstChild("HumanoidRootPart")
					local set = motors(model)
					if root and set.RH then
						local v = root.AssemblyLinearVelocity
						local speed = Vector3.new(v.X, 0, v.Z).Magnitude
						local amount = math.clamp(speed / 18, 0, 1)
						walkPhase[model] = (walkPhase[model] or 0) + dt * (4 + speed * 0.35)
						local s = math.sin(walkPhase[model]) * amount
						local bob = math.sin(now * 2) * 0.04 * (1 - amount)
						setOffset(set.RH, A(s * 40))
						setOffset(set.LH, A(-s * 40))
						if set.RS then
							setOffset(set.RS, A(-s * 35))
						end
						if set.LS then
							setOffset(set.LS, A(s * 35))
						end
						if set.Root then
							setOffset(set.Root, P(0, bob, 0))
						end
					end
				end
			end
		end
	end
end)

Remotes.Notify.OnClientEvent:Connect(function(msg)
	if msg.Type == "Anim" then
		play(msg.Model, msg.Anim)
	elseif msg.Type == "Hit" and msg.Victim and (msg.Power or 0) > 25 then
		play(msg.Victim, "Hurt")
	end
end)
