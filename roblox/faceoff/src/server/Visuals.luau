-- Builds the visible robot parts (from Config look specs) onto characters and pedestals,
-- plus small helpers for parts, signs and name tags.
local CollectionService = game:GetService("CollectionService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Config = require(ReplicatedStorage.Shared.Config)

local Visuals = {}

local SHAPES = {
	Block = Enum.PartType.Block,
	Ball = Enum.PartType.Ball,
	Cylinder = Enum.PartType.Cylinder,
	Wedge = Enum.PartType.Wedge,
}

-- Body parts to attach to, R15 name first, then R6.
local ATTACH = {
	Head = { { "Head" }, { "Head" } },
	Hand = { { "RightHand", "Right Arm" }, { "LeftHand", "Left Arm" } },
	Foot = { { "RightFoot", "Right Leg" }, { "LeftFoot", "Left Leg" } },
}
local SLOT_ATTACH = { Head = "Head", Arms = "Hand", Legs = "Foot" }
-- R6 limbs are 2 studs long and centered, so hand/foot pieces move down to the limb's end.
local R6_DROP = Vector3.new(0, -0.8, 0)

function Visuals.Part(props)
	local part = Instance.new("Part")
	part.Anchored = props.Anchored ~= false
	part.TopSurface = Enum.SurfaceType.Smooth
	part.BottomSurface = Enum.SurfaceType.Smooth
	for k, v in props do
		if k ~= "Parent" and k ~= "Anchored" then
			part[k] = v
		end
	end
	part.Parent = props.Parent
	return part
end

local function paintPiece(piece, spec, paintKey)
	local paint = Config.Paints[paintKey or "Default"]
	if paint and paint.Color and not spec.Keep then
		piece.Color = paint.Color
		piece.Material = Enum.Material[paint.Material or "SmoothPlastic"]
		if paint.Rainbow then
			CollectionService:AddTag(piece, "RainbowPart")
		end
	else
		piece.Color = spec.Color
		piece.Material = Enum.Material[spec.Material or "SmoothPlastic"]
	end
end

local function makePiece(spec, paintKey, scale)
	local piece = Instance.new("Part")
	piece.Name = "MixPiece"
	piece.Shape = SHAPES[spec.Shape] or Enum.PartType.Block
	piece.Size = spec.Size * scale
	piece.CanCollide = false
	piece.CanQuery = false
	piece.CanTouch = false
	piece.Massless = true
	piece.CastShadow = false
	piece.TopSurface = Enum.SurfaceType.Smooth
	piece.BottomSurface = Enum.SurfaceType.Smooth
	paintPiece(piece, spec, paintKey)
	return piece
end

local function mirror(offset)
	-- Mirror across the body's left/right plane (good enough for our simple shapes).
	local x, y, z, r00, r01, r02, r10, r11, r12, r20, r21, r22 = offset:GetComponents()
	return CFrame.new(-x, y, z, r00, -r01, -r02, -r10, r11, r12, -r20, r21, r22)
end

local function findBodyPart(model, names)
	for i, name in names do
		local found = model:FindFirstChild(name)
		if found and found:IsA("BasePart") then
			return found, i == 2 -- second name = R6
		end
	end
	return nil, false
end

-- Puts the loadout's parts on a character (or NPC). `scale` grows pieces for big bosses.
function Visuals.Dress(model, loadout, paintKey, scale)
	scale = scale or 1
	local old = model:FindFirstChild("MixParts")
	if old then
		old:Destroy()
	end
	local folder = Instance.new("Folder")
	folder.Name = "MixParts"
	for _, slot in Config.Slots do
		local part = Config.Parts[loadout[slot]]
		if part then
			local attach = ATTACH[SLOT_ATTACH[slot]]
			local sides = slot == "Head" and 1 or 2
			for side = 1, sides do
				local body, isR6 = findBodyPart(model, attach[side])
				if body then
					for _, spec in part.Look do
						local piece = makePiece(spec, paintKey, scale)
						local offset = spec.Offset
						if side == 2 then
							offset = mirror(offset)
						end
						offset = offset - offset.Position + offset.Position * scale
						if isR6 and slot ~= "Head" then
							offset = CFrame.new(R6_DROP * scale) * offset
						end
						piece.CFrame = body.CFrame * offset
						local weld = Instance.new("WeldConstraint")
						weld.Part0 = body
						weld.Part1 = piece
						weld.Parent = piece
						piece.Parent = folder
					end
				end
			end
		end
	end
	folder.Parent = model
	model:SetAttribute("Head", loadout.Head)
	model:SetAttribute("Arms", loadout.Arms)
	model:SetAttribute("Legs", loadout.Legs)
	model:SetAttribute("Paint", paintKey or "Default")
	local legs = Config.Parts[loadout.Legs]
	local stats = legs and legs.Stats or Config.Parts.Sneakers.Stats
	model:SetAttribute("AirJumps", stats.AirJumps)
	model:SetAttribute("AirDash", stats.AirDash == true)
	model:SetAttribute("Glide", stats.Glide == true)
end

-- A standalone model of one part for a pedestal. Pieces are laid out as if worn.
function Visuals.Display(partKey, paintKey, cframe, scale)
	local part = Config.Parts[partKey]
	local model = Instance.new("Model")
	model.Name = "Display_" .. partKey
	scale = scale or 2.2
	local core = Visuals.Part({
		Name = "Core",
		Size = Vector3.new(0.2, 0.2, 0.2),
		Transparency = 1,
		CanCollide = false,
		CanQuery = false,
		CFrame = cframe,
		Parent = model,
	})
	model.PrimaryPart = core
	local sides = part.Slot == "Head" and { 0 } or { -0.9, 0.9 }
	for i, sideX in sides do
		for _, spec in part.Look do
			local piece = makePiece(spec, paintKey, scale)
			piece.Anchored = true
			local offset = spec.Offset
			if i == 2 then
				offset = mirror(offset)
			end
			offset = offset - offset.Position + offset.Position * scale
			piece.CFrame = cframe * CFrame.new(sideX * scale, 0, 0) * offset
			piece.Parent = model
		end
	end
	if part.Slot == "Head" then
		-- A plain head block so helmets and visors have something to sit on.
		Visuals.Part({
			Name = "HeadBase",
			Size = Vector3.new(1.2, 1.2, 1.2) * scale,
			Color = Color3.fromRGB(235, 235, 240),
			Material = Enum.Material.SmoothPlastic,
			CanCollide = false,
			CFrame = cframe,
			Parent = model,
		})
	end
	CollectionService:AddTag(model, "Spin")
	return model
end

-- Floating text over a part. Returns the label so callers can update it.
-- Sizes are given in pixels but drawn in studs, so far-away signs shrink instead of crowding the screen.
-- `pop` (studs): the sign stays hidden until you walk this close, then pops up (animated on the client).
-- Leave `pop` nil for big landmark titles that should always show.
local PIXELS_PER_STUD = 22
function Visuals.Sign(adornee, text, color, size, offset, pop)
	size = size or UDim2.fromOffset(240, 60)
	local gui = Instance.new("BillboardGui")
	gui.Name = "Sign"
	gui.Size = UDim2.fromScale(size.X.Offset / PIXELS_PER_STUD, size.Y.Offset / PIXELS_PER_STUD)
	gui.StudsOffset = offset or Vector3.new(0, 4, 0)
	gui.AlwaysOnTop = false
	gui.LightInfluence = 0
	gui.MaxDistance = pop and (pop + 15) or 400
	local label = Instance.new("TextLabel")
	label.Size = UDim2.fromScale(1, 1)
	label.BackgroundTransparency = 1
	label.Font = Enum.Font.FredokaOne
	label.TextScaled = true
	label.TextColor3 = color or Color3.new(1, 1, 1)
	label.TextStrokeTransparency = 0
	label.TextStrokeColor3 = Color3.fromRGB(20, 15, 35)
	label.RichText = true
	label.Text = text
	label.Parent = gui
	if pop then
		local scale = Instance.new("UIScale")
		scale.Name = "Pop"
		scale.Scale = 0
		scale.Parent = label
		gui:SetAttribute("PopRange", pop)
		CollectionService:AddTag(gui, "PopSign")
	end
	gui.Adornee = adornee
	gui.Parent = adornee
	return label
end

-- Name tag + rank line + damage % over a fighter's head.
function Visuals.Tag(model, name, subText, nameColor, subColor)
	local head = model:FindFirstChild("Head")
	if not head then
		return nil
	end
	local old = head:FindFirstChild("FighterTag")
	if old then
		old:Destroy()
	end
	local gui = Instance.new("BillboardGui")
	gui.Name = "FighterTag"
	gui.Size = UDim2.fromOffset(200, 74)
	gui.StudsOffsetWorldSpace = Vector3.new(0, 3.2, 0)
	gui.AlwaysOnTop = true
	gui.MaxDistance = 140
	gui.LightInfluence = 0
	local function line(nameText, y, h, color, textName)
		local label = Instance.new("TextLabel")
		label.Name = textName
		label.Size = UDim2.fromScale(1, h)
		label.Position = UDim2.fromScale(0, y)
		label.BackgroundTransparency = 1
		label.Font = Enum.Font.FredokaOne
		label.TextScaled = true
		label.TextColor3 = color
		label.TextStrokeTransparency = 0.3
		label.Text = nameText
		label.Parent = gui
		return label
	end
	line("", 0, 0.42, Color3.new(1, 1, 1), "Damage").Visible = false
	line(name, 0.42, 0.32, nameColor or Color3.new(1, 1, 1), "Name")
	line(subText or "", 0.74, 0.26, subColor or Color3.fromRGB(200, 200, 220), "Sub")
	gui.Parent = head
	return gui
end

-- Damage % color: white at 0%, yellow, orange, then deep red past 150%.
function Visuals.DamageColor(damage)
	local t = math.clamp(damage / 150, 0, 1)
	if t < 0.5 then
		return Color3.new(1, 1, 1):Lerp(Color3.fromRGB(255, 200, 60), t * 2)
	end
	return Color3.fromRGB(255, 200, 60):Lerp(Color3.fromRGB(220, 20, 30), (t - 0.5) * 2)
end

function Visuals.SetDamageTag(model, damage, show)
	local head = model:FindFirstChild("Head")
	local gui = head and head:FindFirstChild("FighterTag")
	local label = gui and gui:FindFirstChild("Damage")
	local sub = gui and gui:FindFirstChild("Sub")
	if sub then
		sub.Visible = not show -- in fights, the rank line hides so the % is easy to read
	end
	if label then
		label.Visible = show
		label.Text = math.floor(damage) .. "%"
		label.TextColor3 = Visuals.DamageColor(damage)
	end
end

return Visuals
