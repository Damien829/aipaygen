--[[
	Mix & Smash Animation Pack.

	Every animation is a list of keyframes, the same data an animation made in Roblox's
	Animation Editor holds: a time, a pose for each joint, and an easing curve into that pose.

	Joint directions (R15 rig, character faces -Z), checked in Studio:
	  shoulder / hip  +X = limb swings forward and up
	  elbow           +X = forearm bends up
	  knee            -X = bends (shin goes back)
	  waist / root    +Y = turns so the RIGHT shoulder comes forward
	  waist           -X = leans forward
	  shoulder +Z (right) / -Z (left) = arm out to the side

	Rules from fighting-game animation guides:
	  * jabs snap out with no wind-up and barely disturb the stance
	  * power shots load first (hips turn away), then the hips drive INTO the punch, weight goes
	    onto the front foot and the rear heel lifts
	  * strikes ease out fast (explosive start), retract with a little overshoot, then settle
	  * hips turn the body while the legs counter-turn so the feet stay planted
	  * knees stay soft; no popping up and down
]]

local Pack = {}

local function A(x, y, z)
	return CFrame.Angles(math.rad(x or 0), math.rad(y or 0), math.rad(z or 0))
end
local function P(x, y, z)
	return CFrame.new(x or 0, y or 0, z or 0)
end
Pack.A = A
Pack.P = P

-- Joint short names -> { body part, joint } (R15)
Pack.Joints = {
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
Pack.Upper = { RS = true, LS = true, RE = true, LE = true, W = true, N = true }

-- Overlapping action: these joints trail their parent by a few hundredths of a second,
-- so a punch whips (shoulder leads, forearm follows) and the head settles after the body.
Pack.Lag = { RE = 0.028, LE = 0.028, N = 0.04, RK = 0.02, LK = 0.02 }

-- Hip turn with planted feet: turn the root, counter-turn both hips.
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
Pack.pose = pose

local function merge(a, b)
	local out = table.clone(a)
	for k, v in b do
		out[k] = v
	end
	return out
end

-- BASE LAYERS -------------------------------------------------------------------------------------
-- The guard: orthodox stance (left side forward), lead fist out, rear fist by the chin.
Pack.Guard = pose(-16, {
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

-- In the air: knees tucked, guard loosened.
Pack.Air = pose(-8, {
	LS = A(50, 0, 25),
	LE = A(80),
	RS = A(40, 0, -25),
	RE = A(95),
	W = A(-10, -4),
	N = A(-4, 12),
	RH = A(42),
	RK = A(-70),
	LH = A(22),
	LK = A(-38),
})

-- Launched: arms and legs thrown out.
Pack.Tumble = pose(0, {
	LS = A(40, 0, -95),
	LE = A(30),
	RS = A(60, 0, 100),
	RE = A(40),
	W = A(25, 0, 10),
	N = A(30),
	RH = A(-30, 0, 20),
	RK = A(-40),
	LH = A(50, 0, -15),
	LK = A(-70),
})

-- KEYFRAMED ANIMATIONS ------------------------------------------------------------------------------
-- { time, pose, easing } where easing = { Enum.EasingStyle, Enum.EasingDirection } into that pose.
-- A pose lists only the joints that leave the guard.
local Out = { Enum.EasingStyle.Quart, Enum.EasingDirection.Out } -- explosive strike
local Snap = { Enum.EasingStyle.Quint, Enum.EasingDirection.Out } -- fastest strike
local Back = { Enum.EasingStyle.Back, Enum.EasingDirection.Out } -- overshoot then settle
local Smooth = { Enum.EasingStyle.Sine, Enum.EasingDirection.InOut } -- loads and returns
local Load = { Enum.EasingStyle.Quad, Enum.EasingDirection.InOut }

-- Strike poses (reused by several moves)
local JAB = pose(-28, { LS = A(91, 0, 2), LE = A(0), RS = A(48, 0, -14), RE = A(116), W = A(-8, -10), N = A(4, 32), RK = A(-24), LK = A(-15), Shift = P(0, -0.13, -0.08) })
local JAB_BACK = pose(-14, { LS = A(54, 0, 12), LE = A(104) })
local CROSS_LOAD = pose(-24, { W = A(-4, -12), RS = A(42, 0, -16), RE = A(120), Shift = P(0, -0.16, 0.06) })
local CROSS = pose(30, { RS = A(92, 0, -5), RE = A(0), LS = A(58, 0, 16), LE = A(112), W = A(-12, 14), N = A(4, -24), RK = A(-34), LK = A(-12), Shift = P(0, -0.15, -0.32) })
local LHOOK_LOAD = pose(-30, { LS = A(60, 0, -30), LE = A(95), W = A(-6, -14), Shift = P(0, -0.18, 0) })
local LHOOK = pose(26, { LS = A(84, 0, -78), LE = A(92), RS = A(50, 0, -12), RE = A(118), W = A(-10, 20), N = A(4, -10), LK = A(-28), Shift = P(0, -0.18, -0.12) })
local RHOOK_LOAD = pose(-34, { RS = A(58, 0, 30), RE = A(95), W = A(-6, -18), RK = A(-36), Shift = P(0, -0.18, 0.05) })
local RHOOK = pose(40, { RS = A(84, 0, 80), RE = A(92), LS = A(56, 0, 14), LE = A(112), W = A(-10, 22), N = A(4, -26), RK = A(-36), LK = A(-14), Shift = P(0, -0.18, -0.2) })
local UPPER_LOAD = pose(-18, { RS = A(18, 0, -8), RE = A(104), W = A(-14, -10), N = A(-8, 18), RH = A(42), RK = A(-62), LH = A(40), LK = A(-56), Shift = P(0, -0.42, 0.05) })
local UPPER = pose(26, { RS = A(128, 0, -12), RE = A(92), LS = A(52, 0, 18), LE = A(110), W = A(10, 16), N = A(14, -18), RH = A(4), RK = A(-10), LH = A(10), LK = A(-12), Shift = P(0, 0.02, -0.15) })

Pack.Anims = {
	-- Basic attacks (click): the jab and cross alternate.
	Jab = {
		{ 0.0, {} },
		{ 0.045, JAB, Snap },
		{ 0.1, merge(JAB, { LS = A(93, 0, 1) }) },
		{ 0.17, JAB_BACK, Load },
		{ 0.27, {}, Smooth },
	},
	Cross = {
		{ 0.0, {} },
		{ 0.06, CROSS_LOAD, Load },
		{ 0.13, CROSS, Out },
		{ 0.2, merge(CROSS, { RS = A(94, 0, -5) }) },
		{ 0.3, pose(-20, { RS = A(40, 0, -18), RE = A(118), W = A(-4, -10) }), Load },
		{ 0.42, {}, Smooth },
	},

	LeadHook = {
		{ 0.0, {} },
		{ 0.07, LHOOK_LOAD, Load },
		{ 0.15, LHOOK, Out },
		{ 0.22, merge(LHOOK, { LS = A(84, 0, -82) }) },
		{ 0.33, pose(-20, { LS = A(58, 0, 14), LE = A(100) }), Back },
		{ 0.44, {}, Smooth },
	},
	RearHook = {
		{ 0.0, {} },
		{ 0.08, RHOOK_LOAD, Load },
		{ 0.17, RHOOK, Out },
		{ 0.24, merge(RHOOK, { RS = A(84, 0, 84) }) },
		{ 0.36, pose(-22, { RS = A(42, 0, -16), RE = A(118) }), Back },
		{ 0.48, {}, Smooth },
	},

	-- ARMS (heavy attacks, E)
	Gloves = { -- Big Punch: an overhand haymaker
		{ 0.0, {} },
		{ 0.12, pose(-26, { RS = A(30, 0, 30), RE = A(110), W = A(0, -16), N = A(0, 26), Shift = P(0, -0.15, 0.12) }), Load },
		{ 0.22, pose(-36, { RS = A(70, 0, 50), RE = A(100), LS = A(60, 0, 15), LE = A(95), W = A(6, -24), N = A(2, 30), RK = A(-42), LK = A(-30), Shift = P(0, -0.22, 0.22) }), Smooth },
		{ 0.31, pose(42, { RS = A(100, 0, -14), RE = A(4), LS = A(42, 0, 26), LE = A(112), W = A(-18, 24), N = A(8, -32), RH = A(-12), LH = A(34), RK = A(-14), LK = A(-32), Shift = P(0, -0.2, -0.55) }), Out },
		{ 0.46, pose(42, { RS = A(96, 0, -12), RE = A(2), LS = A(42, 0, 26), LE = A(112), W = A(-16, 22), N = A(8, -30), RH = A(-12), LH = A(34), RK = A(-14), LK = A(-32), Shift = P(0, -0.2, -0.5) }) },
		{ 0.62, pose(-22, { RS = A(40, 0, -18), RE = A(118), W = A(-4, -10) }), Back },
		{ 0.82, {}, Smooth },
	},
	Spring = { -- Boing Punch: coil low, then a long lunging punch
		{ 0.0, {} },
		{ 0.22, pose(-30, { RS = A(25, 0, 25), RE = A(125), W = A(6, -15), RK = A(-55), LK = A(-55), RH = A(35), LH = A(35), Shift = P(0, -0.32, 0.25) }), Load },
		{ 0.31, pose(34, { RS = A(94), RE = A(0), LS = A(25, 0, 25), LE = A(95), W = A(-24, 18), N = A(10, -30), RH = A(-30), LH = A(46), LK = A(-20), RK = A(-6), Shift = P(0, -0.22, -0.9) }), Snap },
		{ 0.56, pose(34, { RS = A(92), RE = A(2), LS = A(25, 0, 25), LE = A(95), W = A(-22, 18), N = A(10, -28), RH = A(-30), LH = A(46), LK = A(-20), RK = A(-6), Shift = P(0, -0.22, -0.85) }) },
		{ 0.7, pose(-18, { RS = A(42, 0, -16), RE = A(118) }), Back },
		{ 0.86, {}, Smooth },
	},
	Drill = { -- Drill Rush: jab, cross, lead hook, then a rising uppercut
		{ 0.0, {} },
		{ 0.05, JAB, Snap },
		{ 0.1, JAB_BACK, Load },
		{ 0.16, CROSS, Out },
		{ 0.21, LHOOK_LOAD, Load },
		{ 0.27, LHOOK, Out },
		{ 0.33, UPPER_LOAD, Load },
		{ 0.4, UPPER, Out },
		{ 0.58, merge(UPPER, { RS = A(132, 0, -12) }) },
		{ 0.85, {}, Smooth },
	},
	Hammer = { -- Ground Pound: double fists high overhead, then smash down with the whole body
		{ 0.0, {} },
		{ 0.18, pose(0, { RS = A(120, 0, -20), RE = A(40), LS = A(120, 0, 20), LE = A(40), W = A(6), N = A(10), Shift = P(0, -0.05, 0.08) }), Load },
		{ 0.33, pose(0, { RS = A(168, 0, -12), RE = A(22), LS = A(168, 0, 12), LE = A(22), W = A(16), N = A(20), RK = A(-8), LK = A(-8), Shift = P(0, 0.04, 0.12) }), Smooth },
		{ 0.43, pose(0, { RS = A(60, 0, -10), RE = A(8), LS = A(60, 0, 10), LE = A(8), W = A(-42), N = A(-14), RH = A(48), RK = A(-64), LH = A(48), LK = A(-64), Shift = P(0, -0.52, -0.2) }), Snap },
		{ 0.72, pose(0, { RS = A(62, 0, -10), RE = A(10), LS = A(62, 0, 10), LE = A(10), W = A(-38), N = A(-10), RH = A(46), RK = A(-60), LH = A(46), LK = A(-60), Shift = P(0, -0.5, -0.2) }) },
		{ 1.0, {}, Smooth },
	},
	Claw = { -- Grab and Toss: reach and grab, then turn the whole body and fling behind
		{ 0.0, {} },
		{ 0.15, pose(0, { RS = A(88, 0, 18), RE = A(22), LS = A(88, 0, -18), LE = A(22), W = A(-16), Shift = P(0, -0.12, -0.35) }), Out },
		{ 0.22, pose(0, { RS = A(84, 0, 10), RE = A(45), LS = A(84, 0, -10), LE = A(45), W = A(-10), Shift = P(0, -0.15, -0.2) }), Load },
		{ 0.34, pose(-70, { RS = A(80, 0, 35), RE = A(30), LS = A(80, 0, 65), LE = A(30), W = A(-4, -40), N = A(0, 20) }), Smooth },
		{ 0.44, pose(-100, { RS = A(55, 0, 65), RE = A(8), LS = A(48, 0, 100), LE = A(8), W = A(6, -60), N = A(0, 45) }), Out },
		{ 0.62, pose(-60, { RS = A(46, 0, -10), RE = A(110), LS = A(58, 0, 12), LE = A(96) }), Back },
		{ 0.82, {}, Smooth },
	},
	Rocket = { -- Rocket Fist: brace, fire, recoil
		{ 0.0, {} },
		{ 0.16, pose(-24, { RS = A(55), RE = A(122), LS = A(60), LE = A(100), W = A(0, -12), RK = A(-38), LK = A(-34), Shift = P(0, -0.22, 0.1) }), Load },
		{ 0.22, pose(26, { RS = A(95), RE = A(0), W = A(-10, 12), N = A(4, -24), Shift = P(0, -0.15, -0.25) }), Snap },
		{ 0.34, pose(20, { RS = A(104), RE = A(0), W = A(12, 10), N = A(12, -20), Shift = P(0, -0.1, 0.32) }), Back },
		{ 0.5, pose(16, { RS = A(96), RE = A(4), W = A(2, 10), Shift = P(0, -0.12, 0.15) }), Smooth },
		{ 0.75, {}, Smooth },
	},

	-- HEADS (special moves, Q)
	Bolt = { -- Zap Burst: gather energy low, then explode into a star
		{ 0.0, {} },
		{ 0.15, pose(0, { RS = A(40, 0, -35), RE = A(122), LS = A(40, 0, 35), LE = A(122), W = A(-18), N = A(-18), RH = A(35), RK = A(-56), LH = A(35), LK = A(-56), Shift = P(0, -0.34, 0) }), Load },
		{ 0.23, pose(0, { RS = A(10, 0, 118), RE = A(0), LS = A(10, 0, -118), LE = A(0), W = A(12), N = A(22), RH = A(4, 0, 18), LH = A(4, 0, -18), RK = A(-6), LK = A(-6), Shift = P(0, 0.02, 0) }), Snap },
		{ 0.46, pose(0, { RS = A(14, 0, 112), RE = A(4), LS = A(14, 0, -112), LE = A(4), W = A(8), N = A(18), RH = A(4, 0, 16), LH = A(4, 0, -16), RK = A(-8), LK = A(-8) }) },
		{ 0.75, {}, Smooth },
	},
	Blaster = { -- Laser: snap into a pointing pose, kick back on the shot
		{ 0.0, {} },
		{ 0.07, pose(24, { RS = A(92), RE = A(0), LS = A(70, 0, -20), LE = A(80), W = A(-6, 8), N = A(0, -22) }), Snap },
		{ 0.13, pose(22, { RS = A(104), RE = A(0), LS = A(70, 0, -20), LE = A(80), W = A(8, 8), N = A(6, -22), Shift = P(0, -0.1, 0.18) }), Out },
		{ 0.4, pose(24, { RS = A(92), RE = A(2), LS = A(70, 0, -20), LE = A(80), W = A(-4, 8), N = A(0, -22) }), Smooth },
		{ 0.6, {}, Smooth },
	},
	Magnet = { -- Magnet Pull: reach out with both hands, then heave back
		{ 0.0, {} },
		{ 0.16, pose(0, { RS = A(92, 0, 8), RE = A(0), LS = A(92, 0, -8), LE = A(0), W = A(-16), Shift = P(0, -0.12, -0.3) }), Out },
		{ 0.36, pose(0, { RS = A(40, 0, 25), RE = A(118), LS = A(40, 0, -25), LE = A(118), W = A(20), N = A(10), RH = A(-15), LH = A(28), LK = A(-25), Shift = P(0, -0.16, 0.42) }), Load },
		{ 0.56, pose(0, { RS = A(42, 0, 22), RE = A(115), LS = A(42, 0, -22), LE = A(115), W = A(16), N = A(8), RH = A(-12), LH = A(26), LK = A(-24), Shift = P(0, -0.15, 0.38) }) },
		{ 0.8, {}, Smooth },
	},
	Frost = { -- Freeze Ray: draw back, then a two-handed cast
		{ 0.0, {} },
		{ 0.1, pose(0, { RS = A(55, -20), RE = A(72), LS = A(55, 20), LE = A(72), W = A(10), Shift = P(0, -0.15, 0.15) }), Load },
		{ 0.17, pose(0, { RS = A(92, -22), RE = A(0), LS = A(92, 22), LE = A(0), W = A(-12), N = A(-6), LH = A(30), LK = A(-25), Shift = P(0, -0.15, -0.25) }), Snap },
		{ 0.45, pose(0, { RS = A(90, -22), RE = A(4), LS = A(90, 22), LE = A(4), W = A(-10), N = A(-4), LH = A(30), LK = A(-25), Shift = P(0, -0.15, -0.22) }) },
		{ 0.7, {}, Smooth },
	},
	Dragon = { -- Fireball: rear back, then breathe fire forward
		{ 0.0, {} },
		{ 0.2, pose(0, { W = A(26), N = A(28), RS = A(10, 0, 40), RE = A(60), LS = A(10, 0, -40), LE = A(60), Shift = P(0, 0, 0.3) }), Load },
		{ 0.3, pose(0, { W = A(-32), N = A(-26), RS = A(-30, 0, 25), RE = A(20), LS = A(-30, 0, -25), LE = A(20), RH = A(-20), LH = A(35), LK = A(-25), Shift = P(0, -0.15, -0.5) }), Snap },
		{ 0.6, pose(0, { W = A(-28), N = A(-22), RS = A(-26, 0, 25), RE = A(22), LS = A(-26, 0, -25), LE = A(22), RH = A(-20), LH = A(35), LK = A(-25), Shift = P(0, -0.15, -0.45) }) },
		{ 0.9, {}, Smooth },
	},
	Thunder = { -- Thunder Strike: fist to the sky, then point the bolt down
		{ 0.0, {} },
		{ 0.15, pose(10, { RS = A(176, 0, -5), RE = A(0), N = A(28), W = A(12), LS = A(20, 0, -30), LE = A(40) }), Out },
		{ 0.6, pose(10, { RS = A(172, 0, -5), RE = A(4), N = A(26), W = A(10), LS = A(20, 0, -30), LE = A(40) }) },
		{ 0.72, pose(26, { RS = A(80), RE = A(0), N = A(-10, -15), W = A(-14, 10), LS = A(30, 0, -20), LE = A(60), Shift = P(0, -0.15, -0.3) }), Snap },
		{ 1.0, {}, Smooth },
	},

	-- Defense and reactions
	Dodge = { -- slip under and roll the shoulders
		{ 0.0, {} },
		{ 0.07, pose(-30, { RS = A(80, 0, 10), RE = A(140), LS = A(85, 0, -10), LE = A(140), W = A(-32, 0, 14), N = A(-20, 10), RH = A(55), RK = A(-82), LH = A(55), LK = A(-82), Shift = P(0, -0.55, 0) }), Out },
		{ 0.27, pose(20, { RS = A(80, 0, 10), RE = A(140), LS = A(85, 0, -10), LE = A(140), W = A(-26, 0, -12), N = A(-18, -10), RH = A(52), RK = A(-78), LH = A(52), LK = A(-78), Shift = P(0, -0.5, 0) }), Smooth },
		{ 0.42, {}, Smooth },
	},
	Flinch = { -- small hit: head snaps back, guard stays up
		{ 0.0, {} },
		{ 0.04, pose(-10, { W = A(14, 8), N = A(20, 12), LS = A(70, 0, 14), LE = A(110), RS = A(55, 0, -10), RE = A(122), Shift = P(0, -0.12, 0.16) }), Snap },
		{ 0.12, pose(-12, { W = A(8, 4), N = A(10, 6), Shift = P(0, -0.12, 0.08) }), Smooth },
		{ 0.26, {}, Smooth },
	},
	BodyFlinch = { -- small hit to the body: fold forward
		{ 0.0, {} },
		{ 0.04, pose(-14, { W = A(-18, 0), N = A(-14), LS = A(40, 0, -10), LE = A(120), RS = A(40, 0, 10), RE = A(125), RK = A(-34), LK = A(-28), Shift = P(0, -0.22, 0.12) }), Snap },
		{ 0.28, {}, Smooth },
	},
	Hurt = { -- big hit: knocked off balance
		{ 0.0, {} },
		{ 0.05, pose(0, { W = A(30, 0, 8), N = A(32), RS = A(30, 0, 65), RE = A(30), LS = A(30, 0, -65), LE = A(30), RH = A(-20), LH = A(30), Shift = P(0, 0, 0.2) }), Snap },
		{ 0.3, pose(0, { W = A(22, 0, 5), N = A(22), RS = A(25, 0, 50), RE = A(40), LS = A(25, 0, -50), LE = A(40) }), Smooth },
		{ 0.5, {}, Smooth },
	},
}

-- Which animation each attack plays (heavy = arm part, special = head part).
function Pack.For(kind, loadout)
	if kind == "Heavy" then
		return loadout.Arms
	elseif kind == "Special" then
		return loadout.Head
	end
	return nil
end

return Pack
