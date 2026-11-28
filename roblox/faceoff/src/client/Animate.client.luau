-- Fighting animations, made in code (no uploaded animation assets needed).
-- In an arena every fighter holds a boxing guard (fists up, knees bent). Attacks start from the
-- guard, snap out, follow through and settle back into it. The upper body is posed directly
-- (so it reads clearly), the legs are layered on top of Roblox's own walk animation, and bots
-- get a walk cycle. Hits freeze both fighters for a split second so every punch lands hard.
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

-- Joint short names -> { body part, joint name } (R15; works with Motor6D or AnimationConstraint)
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
local UPPER = { RS = true, LS = true, RE = true, LE = true, W = true, N = true }

-- Joint directions (checked against the R15 rig, character faces -Z):
--   shoulder/hip +X = limb swings forward/up; elbow +X = forearm bends up; knee -X = bends
--   (shin goes back); waist/root +Y = turn so the RIGHT shoulder comes forward; waist -X = lean in.
-- Fighting-animation rules used here (from fighting-game animation guides):
--   * a jab snaps out with no wind-up and barely disturbs the stance
--   * power punches load first (hips turn away), then the hips turn INTO the punch, weight
--     shifts onto the front foot and the rear heel lifts
--   * a little overshoot on the way back, then settle into the guard
--   * hips turn the whole body while the legs counter-turn so the feet stay planted
--   * knees stay soft; no popping up and down

-- A pose helper: hip turn (Root yaw) with the feet kept planted, plus any joint overrides.
local function pose(hipYaw, joints)
	joints = joints or {}
	local root = A(0, hipYaw)
	if joints.Shift then
		root = root * joints.Shift
		joints.Shift = nil
	end
	joints.Root = root
	joints.RH = (joints.RH or A(14)) * A(0, -hipYaw)
	joints.LH = (joints.LH or A(18)) * A(0, -hipYaw)
	return joints
end

-- The guard: orthodox stance (left side forward), lead fist out, rear fist by the chin.
local GUARD = pose(-16, {
	LS = A(62, 0, 10),
	LE = A(96),
	RS = A(46, 0, -14),
	RE = A(114),
	W = A(-6, -6),
	N = A(4, 20),
	RK = A(-24),
	LK = A(-18),
	Shift = P(0, -0.12, 0),
})
local REST = { RH = CFrame.identity, LH = CFrame.identity, RK = CFrame.identity, LK = CFrame.identity, Root = CFrame.identity }

-- Keyframes { time, pose, ease }. ease "out" = explosive start (strikes); default = smooth.
-- A pose lists only what leaves the guard.
local ANIMS = {
	Light = { -- lead jab: fast, no wind-up
		{ 0.0, {} },
		{ 0.05, pose(-26, { LS = A(90, 0, 3), LE = A(2), W = A(-8, -10), N = A(4, 30), RS = A(48, 0, -14), RE = A(114), RK = A(-24), LK = A(-16) }), "out" },
		{ 0.1, pose(-26, { LS = A(90, 0, 3), LE = A(2), W = A(-8, -10), N = A(4, 30), RS = A(48, 0, -14), RE = A(114), RK = A(-24), LK = A(-16) }) },
		{ 0.15, pose(-14, { LS = A(52, 0, 12), LE = A(104) }) },
		{ 0.24, {} },
	},
	LightLeft = { -- rear cross: small load, hips turn through, rear heel lifts
		{ 0.0, {} },
		{ 0.05, pose(-24, { W = A(-4, -10), Shift = P(0, -0.15, 0.05) }) },
		{ 0.12, pose(28, { RS = A(92, 0, -6), RE = A(2), LS = A(56, 0, 14), LE = A(110), W = A(-12, 14), N = A(4, -22), RK = A(-32), LK = A(-12), Shift = P(0, -0.15, -0.3) }), "out" },
		{ 0.18, pose(28, { RS = A(92, 0, -6), RE = A(2), LS = A(56, 0, 14), LE = A(110), W = A(-12, 14), N = A(4, -22), RK = A(-32), LK = A(-12), Shift = P(0, -0.15, -0.3) }) },
		{ 0.27, pose(-22, { RS = A(40, 0, -16), RE = A(118), W = A(-4, -10) }) },
		{ 0.36, {} },
	},

	-- ARMS (heavy attacks)
	Gloves = { -- Big Punch: load the hips back, then a full-body haymaker
		{ 0.0, {} },
		{ 0.2, pose(-34, { RS = A(25, 0, 35), RE = A(112), LS = A(60, 0, 15), LE = A(95), W = A(2, -20), N = A(0, 30), RK = A(-40), LK = A(-32), Shift = P(0, -0.2, 0.2) }) },
		{ 0.3, pose(40, { RS = A(96, 0, -10), RE = A(0), LS = A(45, 0, 25), LE = A(110), W = A(-14, 22), N = A(6, -32), RH = A(-12), LH = A(32), RK = A(-14), LK = A(-30), Shift = P(0, -0.18, -0.5) }), "out" },
		{ 0.48, pose(40, { RS = A(96, 0, -10), RE = A(0), LS = A(45, 0, 25), LE = A(110), W = A(-14, 22), N = A(6, -32), RH = A(-12), LH = A(32), RK = A(-14), LK = A(-30), Shift = P(0, -0.18, -0.5) }) },
		{ 0.62, pose(-22, { RS = A(40, 0, -18), RE = A(118), W = A(-4, -10) }) },
		{ 0.85, {} },
	},
	Spring = { -- Boing Punch: coil low, then lunge into a long punch
		{ 0.0, {} },
		{ 0.22, pose(-30, { RS = A(25, 0, 25), RE = A(125), W = A(6, -15), RK = A(-55), LK = A(-55), RH = A(35), LH = A(35), Shift = P(0, -0.3, 0.25) }) },
		{ 0.32, pose(32, { RS = A(94), RE = A(0), LS = A(25, 0, 25), LE = A(95), W = A(-24, 18), N = A(10, -30), RH = A(-30), LH = A(45), LK = A(-20), RK = A(-6), Shift = P(0, -0.22, -0.85) }), "out" },
		{ 0.58, pose(32, { RS = A(94), RE = A(0), LS = A(25, 0, 25), LE = A(95), W = A(-24, 18), N = A(10, -30), RH = A(-30), LH = A(45), LK = A(-20), RK = A(-6), Shift = P(0, -0.22, -0.85) }) },
		{ 0.85, {} },
	},
	Drill = { -- Drill Rush: jab, cross, jab, then a two-fisted finisher
		{ 0.0, {} },
		{ 0.1, pose(-26, { LS = A(90, 0, 3), LE = A(2), W = A(-8, -10), N = A(4, 30) }), "out" },
		{ 0.18, pose(28, { RS = A(92, 0, -6), RE = A(2), W = A(-12, 14), N = A(4, -22), RK = A(-32) }), "out" },
		{ 0.26, pose(-26, { LS = A(90, 0, 3), LE = A(2), W = A(-8, -10), N = A(4, 30) }), "out" },
		{ 0.36, pose(10, { RS = A(96, 0, -12), RE = A(0), LS = A(96, 0, 12), LE = A(0), W = A(-22), RH = A(-18), LH = A(34), LK = A(-28), Shift = P(0, -0.2, -0.5) }), "out" },
		{ 0.6, pose(10, { RS = A(96, 0, -12), RE = A(0), LS = A(96, 0, 12), LE = A(0), W = A(-22), RH = A(-18), LH = A(34), LK = A(-28), Shift = P(0, -0.2, -0.5) }) },
		{ 0.85, {} },
	},
	Hammer = { -- Ground Pound: both fists high overhead, then smash down with the whole body
		{ 0.0, {} },
		{ 0.32, pose(0, { RS = A(165, 0, -15), RE = A(25), LS = A(165, 0, 15), LE = A(25), W = A(14), N = A(18), RK = A(-10), LK = A(-10), Shift = P(0, 0.05, 0.1) }) },
		{ 0.43, pose(0, { RS = A(62, 0, -10), RE = A(10), LS = A(62, 0, 10), LE = A(10), W = A(-40), N = A(-12), RH = A(48), RK = A(-62), LH = A(48), LK = A(-62), Shift = P(0, -0.5, -0.2) }), "out" },
		{ 0.72, pose(0, { RS = A(62, 0, -10), RE = A(10), LS = A(62, 0, 10), LE = A(10), W = A(-40), N = A(-12), RH = A(48), RK = A(-62), LH = A(48), LK = A(-62), Shift = P(0, -0.5, -0.2) }) },
		{ 1.0, {} },
	},
	Claw = { -- Grab and Toss: reach and grab, then turn the whole body and fling behind
		{ 0.0, {} },
		{ 0.16, pose(0, { RS = A(88, 0, 18), RE = A(20), LS = A(88, 0, -18), LE = A(20), W = A(-16), Shift = P(0, -0.1, -0.35) }), "out" },
		{ 0.3, pose(-60, { RS = A(80, 0, 30), RE = A(30), LS = A(80, 0, 60), LE = A(30), W = A(-4, -40) }) },
		{ 0.44, pose(-90, { RS = A(55, 0, 60), RE = A(10), LS = A(50, 0, 95), LE = A(10), W = A(6, -60), N = A(0, 40) }), "out" },
		{ 0.75, {} },
	},
	Rocket = { -- Rocket Fist: brace, fire, recoil
		{ 0.0, {} },
		{ 0.16, pose(-24, { RS = A(55), RE = A(120), LS = A(60), LE = A(100), W = A(0, -10), RK = A(-38), LK = A(-34), Shift = P(0, -0.2, 0.1) }) },
		{ 0.23, pose(26, { RS = A(95), RE = A(0), W = A(-10, 12), N = A(4, -24), Shift = P(0, -0.15, -0.25) }), "out" },
		{ 0.38, pose(20, { RS = A(102), RE = A(0), W = A(10, 10), N = A(10, -20), Shift = P(0, -0.1, 0.3) }) },
		{ 0.75, {} },
	},

	-- HEADS (special moves)
	Bolt = { -- Zap Burst: gather energy low, then explode into a star
		{ 0.0, {} },
		{ 0.15, pose(0, { RS = A(40, 0, -35), RE = A(120), LS = A(40, 0, 35), LE = A(120), W = A(-18), N = A(-18), RH = A(35), RK = A(-55), LH = A(35), LK = A(-55), Shift = P(0, -0.32, 0) }) },
		{ 0.24, pose(0, { RS = A(10, 0, 115), RE = A(0), LS = A(10, 0, -115), LE = A(0), W = A(10), N = A(20), RH = A(4, 0, 16), LH = A(4, 0, -16), RK = A(-6), LK = A(-6) }), "out" },
		{ 0.46, pose(0, { RS = A(10, 0, 115), RE = A(0), LS = A(10, 0, -115), LE = A(0), W = A(10), N = A(20), RH = A(4, 0, 16), LH = A(4, 0, -16), RK = A(-6), LK = A(-6) }) },
		{ 0.75, {} },
	},
	Blaster = { -- Laser: snap into a pointing pose, kick back on the shot
		{ 0.0, {} },
		{ 0.07, pose(24, { RS = A(92), RE = A(0), LS = A(70, 0, -20), LE = A(80), W = A(-6, 8), N = A(0, -22) }), "out" },
		{ 0.14, pose(22, { RS = A(102), RE = A(0), LS = A(70, 0, -20), LE = A(80), W = A(6, 8), N = A(4, -22), Shift = P(0, -0.1, 0.15) }) },
		{ 0.4, pose(24, { RS = A(92), RE = A(0), LS = A(70, 0, -20), LE = A(80), W = A(-6, 8), N = A(0, -22) }) },
		{ 0.6, {} },
	},
	Magnet = { -- Magnet Pull: reach out with both hands, then heave back
		{ 0.0, {} },
		{ 0.16, pose(0, { RS = A(92, 0, 8), RE = A(0), LS = A(92, 0, -8), LE = A(0), W = A(-16), Shift = P(0, -0.1, -0.3) }), "out" },
		{ 0.36, pose(0, { RS = A(40, 0, 25), RE = A(115), LS = A(40, 0, -25), LE = A(115), W = A(18), N = A(10), RH = A(-15), LH = A(28), LK = A(-25), Shift = P(0, -0.15, 0.4) }) },
		{ 0.55, pose(0, { RS = A(40, 0, 25), RE = A(115), LS = A(40, 0, -25), LE = A(115), W = A(18), N = A(10), RH = A(-15), LH = A(28), LK = A(-25), Shift = P(0, -0.15, 0.4) }) },
		{ 0.8, {} },
	},
	Frost = { -- Freeze Ray: draw back, then a two-handed cast
		{ 0.0, {} },
		{ 0.1, pose(0, { RS = A(55, -20), RE = A(70), LS = A(55, 20), LE = A(70), W = A(10), Shift = P(0, -0.15, 0.15) }) },
		{ 0.17, pose(0, { RS = A(92, -22), RE = A(0), LS = A(92, 22), LE = A(0), W = A(-12), N = A(-6), LH = A(30), LK = A(-25), Shift = P(0, -0.15, -0.25) }), "out" },
		{ 0.45, pose(0, { RS = A(92, -22), RE = A(0), LS = A(92, 22), LE = A(0), W = A(-12), N = A(-6), LH = A(30), LK = A(-25), Shift = P(0, -0.15, -0.25) }) },
		{ 0.7, {} },
	},
	Dragon = { -- Fireball: rear back, then breathe fire forward
		{ 0.0, {} },
		{ 0.2, pose(0, { W = A(26), N = A(28), RS = A(10, 0, 40), RE = A(60), LS = A(10, 0, -40), LE = A(60), Shift = P(0, 0, 0.3) }) },
		{ 0.3, pose(0, { W = A(-32), N = A(-26), RS = A(-30, 0, 25), RE = A(20), LS = A(-30, 0, -25), LE = A(20), RH = A(-20), LH = A(35), LK = A(-25), Shift = P(0, -0.15, -0.5) }), "out" },
		{ 0.6, pose(0, { W = A(-32), N = A(-26), RS = A(-30, 0, 25), RE = A(20), LS = A(-30, 0, -25), LE = A(20), RH = A(-20), LH = A(35), LK = A(-25), Shift = P(0, -0.15, -0.5) }) },
		{ 0.9, {} },
	},
	Thunder = { -- Thunder Strike: fist to the sky, then point the bolt down
		{ 0.0, {} },
		{ 0.15, pose(10, { RS = A(175, 0, -5), RE = A(0), N = A(28), W = A(12), LS = A(20, 0, -30), LE = A(40) }) },
		{ 0.6, pose(10, { RS = A(175, 0, -5), RE = A(0), N = A(28), W = A(12), LS = A(20, 0, -30), LE = A(40) }) },
		{ 0.72, pose(25, { RS = A(80), RE = A(0), N = A(-10, -15), W = A(-14, 10), LS = A(30, 0, -20), LE = A(60), Shift = P(0, -0.15, -0.3) }), "out" },
		{ 1.0, {} },
	},

	-- Movement and reactions
	Dodge = { -- duck and cover
		{ 0.0, {} },
		{ 0.07, pose(0, { RS = A(85, 0, 10), RE = A(140), LS = A(85, 0, -10), LE = A(140), W = A(-30, 0, 10), N = A(-20), RH = A(55), RK = A(-80), LH = A(55), LK = A(-80), Shift = P(0, -0.55, 0) }), "out" },
		{ 0.27, pose(0, { RS = A(85, 0, 10), RE = A(140), LS = A(85, 0, -10), LE = A(140), W = A(-30, 0, 10), N = A(-20), RH = A(55), RK = A(-80), LH = A(55), LK = A(-80), Shift = P(0, -0.55, 0) }) },
		{ 0.42, {} },
	},
	Flinch = { -- small hit: head snaps back, guard stays up
		{ 0.0, {} },
		{ 0.04, pose(-10, { W = A(14, 8), N = A(18, 10), LS = A(70, 0, 14), LE = A(110), RS = A(55, 0, -10), RE = A(120), Shift = P(0, -0.12, 0.15) }), "out" },
		{ 0.24, {} },
	},
	Hurt = { -- big hit: knocked off balance, arms thrown out
		{ 0.0, {} },
		{ 0.05, pose(0, { W = A(30, 0, 8), N = A(32), RS = A(30, 0, 65), RE = A(30), LS = A(30, 0, -65), LE = A(30), RH = A(-20), LH = A(30), Shift = P(0, 0, 0.2) }), "out" },
		{ 0.3, pose(0, { W = A(20, 0, 5), N = A(20), RS = A(25, 0, 50), RE = A(40), LS = A(25, 0, -50), LE = A(40) }) },
		{ 0.5, {} },
	},
}

local playing = {} -- [Model] = { Frames, Start }
local trailCache = {} -- [Model] = { Trail }
local trailToken = {} -- [Model] = token
local leftNext = {} -- [Model] = bool (alternate jabs)
local applied = {} -- [joint] = { Result, Base }
local motorCache = {} -- [Model] = { [joint] = Motor6D or AnimationConstraint }
local weights = {} -- [Model] = 0..1 (how strongly our pose is applied to the upper body)
local walkPhase = {} -- [Model] = number

local function motors(model)
	local cached = motorCache[model]
	if cached and cached.RS and cached.RS:IsDescendantOf(model) then -- rebuild if the body was swapped
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
	if not cached.RS or not cached.W then
		return cached -- not fully loaded yet: don't cache, try again next time
	end
	motorCache[model] = cached
	return cached
end

-- Glowing streaks behind the hands and feet while an attack plays.
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
			a0.Position = Vector3.new(0, 0.35, 0)
			a0.Parent = limb
			local a1 = Instance.new("Attachment")
			a1.Position = Vector3.new(0, -0.35, 0)
			a1.Parent = limb
			local trail = Instance.new("Trail")
			trail.Attachment0 = a0
			trail.Attachment1 = a1
			trail.Lifetime = 0.2
			trail.MinLength = 0.05
			trail.FaceCamera = true
			trail.LightEmission = 1
			trail.Transparency = NumberSequence.new(0.15, 1)
			trail.WidthScale = NumberSequence.new(1, 0.1)
			trail.Enabled = false
			trail.Parent = limb
			table.insert(cached, trail)
		end
	end
	trailCache[model] = cached
	return cached
end

local function streak(model, key, seconds)
	if key == "Hurt" or key == "Dodge" then
		return
	end
	local part = Config.Parts[key]
	local color = part and part.Move and part.Move.Color or Color3.new(1, 1, 1)
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
		playing[model] = { Frames = frames, Start = os.clock() }
		streak(model, key, frames[#frames][1] * 0.7)
	end
end

local function smooth(alpha)
	return alpha * alpha * (3 - 2 * alpha)
end

-- The pose for `joint` at time t, blended between keyframes; joints a keyframe skips use `guard`.
local function sample(frames, t, joint, guard)
	local rest = guard[joint] or CFrame.identity
	for i = 1, #frames - 1 do
		local a, b = frames[i], frames[i + 1]
		if t >= a[1] and t < b[1] then
			local raw = (t - a[1]) / (b[1] - a[1])
			-- "out" segments are strikes: explosive start, then ease into the hit pose.
			local alpha = b[3] == "out" and (1 - (1 - raw) ^ 3) or smooth(raw)
			local pa = a[2][joint] or rest
			local pb = b[2][joint] or rest
			return pa:Lerp(pb, alpha)
		end
	end
	return rest
end

-- Never stack on top of our own last write: on joints the Animator doesn't touch, Transform
-- still holds what we wrote last frame, so start again from the base we used then.
-- Roblox rounds a Transform slightly when it applies it, so compare with a small tolerance.
local function same(a, b)
	return (a.Position - b.Position).Magnitude < 1e-3 and a.LookVector:Dot(b.LookVector) > 0.99999 and a.UpVector:Dot(b.UpVector) > 0.99999
end

local function baseOf(motor, owned)
	if owned then
		return CFrame.identity -- bots: nothing else animates them, so always start from the rest pose
	end
	local current = motor.Transform
	local prev = applied[motor]
	if prev and same(current, prev.Result) then
		return prev.Base
	end
	return current
end

local function write(motor, base, result)
	motor.Transform = result
	applied[motor] = { Result = result, Base = base }
end

local function animateModel(model, dt, now)
	local set = motors(model)
	if not set.RS then
		return
	end
	local fighting = model:GetAttribute("Fighting") == true
	local anim = playing[model]
	local t = anim and (now - anim.Start) or 0
	if anim and t >= anim.Frames[#anim.Frames][1] then
		playing[model] = nil
		anim = nil
	end

	-- How strongly we pose the body: fully in a fight, eased in and out for lobby attacks.
	local target = (fighting or anim) and 1 or 0
	local w = weights[model] or 0
	w += math.clamp(target - w, -dt * 6, dt * 14)
	weights[model] = w
	local guard = fighting and GUARD or REST
	local npc = CollectionService:HasTag(model, "NpcFighter")

	-- Walk cycle for bots (they have no Roblox Animate script)
	local swing, bob = 0, 0
	if npc then
		local root = model:FindFirstChild("HumanoidRootPart")
		if root then
			local v = root.AssemblyLinearVelocity
			local speed = Vector3.new(v.X, 0, v.Z).Magnitude
			local amount = math.clamp(speed / 16, 0, 1)
			walkPhase[model] = (walkPhase[model] or 0) + dt * (5 + speed * 0.3)
			swing = math.sin(walkPhase[model]) * amount
			bob = math.abs(math.cos(walkPhase[model])) * 0.1 * amount
		end
	end

	for joint, motor in set do
		local base = baseOf(motor, npc)
		if UPPER[joint] then
			-- Arms, torso and head are posed directly (guard + attack), blended by the weight.
			local goal = anim and sample(anim.Frames, t, joint, guard) or (guard[joint] or CFrame.identity)
			if w <= 0.001 then
				write(motor, base, base)
			else
				write(motor, base, base:Lerp(goal, w))
			end
		else
			-- Legs and hips are layered on top of the walk animation.
			local offset = anim and sample(anim.Frames, t, joint, guard) or (guard[joint] or CFrame.identity)
			if joint == "Root" and fighting and not anim then
				-- A boxer's bounce: tiny, so it reads as alive, not as popping up and down.
				local phase = now * 4.2 + (walkPhase[model] or 0)
				offset = offset * P(math.sin(phase * 0.5) * 0.04, math.abs(math.sin(phase)) * 0.05, 0)
			end
			if npc then
				if joint == "RH" then
					offset = offset * A(swing * 38)
				elseif joint == "LH" then
					offset = offset * A(-swing * 38)
				elseif joint == "Root" then
					offset = offset * P(0, bob, 0)
				end
			end
			local weight = npc and 1 or w
			write(motor, base, base * CFrame.new():Lerp(offset, weight))
		end
	end
end

RunService.PreSimulation:Connect(function(dt)
	local now = os.clock()
	local seen = {}
	for _, model in CollectionService:GetTagged("Fighter") do
		if model:IsA("Model") and model:IsDescendantOf(Workspace) then
			seen[model] = true
			animateModel(model, dt, now)
		end
	end
	for model in playing do
		if not seen[model] then
			if model:IsDescendantOf(Workspace) then
				animateModel(model, dt, now)
			else
				playing[model] = nil
			end
		end
	end
	for model in motorCache do
		if not model:IsDescendantOf(Workspace) then
			motorCache[model] = nil
			trailCache[model] = nil
			trailToken[model] = nil
			weights[model] = nil
			walkPhase[model] = nil
			leftNext[model] = nil
		end
	end
end)

-- Hit-stop: the attacker's swing freezes for a split second when it connects.
Remotes.Notify.OnClientEvent:Connect(function(msg)
	if msg.Type == "Anim" then
		play(msg.Model, msg.Anim)
	elseif msg.Type == "Hit" then
		-- Hitlag: the attacker's swing freezes on contact, then the victim reacts.
		local hitlag = msg.Hitlag or 0.06
		local anim = msg.Attacker and playing[msg.Attacker]
		if anim then
			anim.Start += hitlag
		end
		if msg.Victim then
			local victim = msg.Victim
			task.delay(hitlag * 0.5, function()
				play(victim, msg.Tumble and "Hurt" or "Flinch")
			end)
		end
	end
end)
