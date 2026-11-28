-- Controls and camera: attacks, dodge, multi-jumps (from your legs), knockback, the flat
-- side-view arena movement, one-way platforms, the fight camera and mobile action buttons.
local CollectionService = game:GetService("CollectionService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")
local StarterGui = game:GetService("StarterGui")
local UserInputService = game:GetService("UserInputService")
local Workspace = game:GetService("Workspace")

local Config = require(ReplicatedStorage.Shared.Config)
local Remotes = require(ReplicatedStorage.Shared.Remotes)

local player = Players.LocalPlayer
local F = Config.Fight

local match = nil -- current arena state from the server (nil in the lobby)
local stunUntil = 0
local stunToken = nil
local parked = false
local airJumpsLeft = 0
local lastGroundJump = 0
local lastAirJump = 0
local freshJumpPress = false
local dashUntil = 0
local dashDir = Vector3.zero
local localCool = {} -- [kind] = os.clock() when ready
local shake = 0
local camPos = nil

local controls = nil
task.spawn(function()
	local ok, result = pcall(function()
		local module = require(player:WaitForChild("PlayerScripts"):WaitForChild("PlayerModule"))
		return module:GetControls()
	end)
	if ok then
		controls = result
	end
end)

local function parts()
	local character = player.Character
	local humanoid = character and character:FindFirstChildOfClass("Humanoid")
	local root = character and character:FindFirstChild("HumanoidRootPart")
	if humanoid and root then
		return character, humanoid, root
	end
	return nil, nil, nil
end

local function moveVector()
	if controls then
		local ok, mv = pcall(function()
			return controls:GetMoveVector()
		end)
		if ok and mv then
			return mv
		end
	end
	return Vector3.zero
end

local function setReset(enabled)
	task.spawn(function()
		for _ = 1, 10 do
			if pcall(function()
				StarterGui:SetCore("ResetButtonCallback", enabled)
			end) then
				return
			end
			task.wait(0.5)
		end
	end)
end

-- Server state ------------------------------------------------------------------------------------
Remotes.Match.OnClientEvent:Connect(function(state)
	local wasIn = match ~= nil
	if state.Phase == "None" then
		match = nil
	else
		match = state
	end
	local camera = Workspace.CurrentCamera
	if match and not wasIn then
		camPos = nil
		setReset(false)
	elseif not match and wasIn then
		camera.CameraType = Enum.CameraType.Custom
		local _, humanoid = parts()
		if humanoid then
			camera.CameraSubject = humanoid
		end
		for _, plat in CollectionService:GetTagged("SoftPlatform") do
			plat.CanCollide = true
		end
		setReset(true)
	end
end)

Remotes.Knockback.OnClientEvent:Connect(function(velocity, stun)
	local _, humanoid, root = parts()
	if not humanoid then
		return
	end
	local token = {}
	stunToken = token
	stunUntil = os.clock() + stun
	dashUntil = 0
	humanoid.PlatformStand = true
	root.AssemblyLinearVelocity = velocity
	shake = math.max(shake, math.clamp(velocity.Magnitude / 120, 0.2, 1.2))
	task.delay(stun, function()
		if stunToken == token and humanoid.Parent then
			humanoid.PlatformStand = false
			humanoid:ChangeState(Enum.HumanoidStateType.Freefall)
		end
	end)
end)

Remotes.Notify.OnClientEvent:Connect(function(msg)
	local _, humanoid, root = parts()
	if msg.Type == "Respawned" then
		stunUntil = 0
		stunToken = nil
		parked = false
		camPos = nil
		if humanoid then
			humanoid.PlatformStand = false
			root.Anchored = false
			root.AssemblyLinearVelocity = Vector3.zero
		end
		airJumpsLeft = player.Character and player.Character:GetAttribute("AirJumps") or 1
	elseif msg.Type == "Parked" then
		parked = true
		if root then
			root.AssemblyLinearVelocity = Vector3.zero
			root.Anchored = true
		end
	elseif msg.Type == "Cooldown" then
		localCool[msg.Kind] = os.clock() + msg.Seconds
	elseif msg.Type == "Hit" then
		local character = player.Character
		if character and (msg.Attacker == character or msg.Victim == character) then
			shake = math.max(shake, math.clamp(msg.Power / 160, 0.15, 0.8))
		end
	elseif msg.Type == "KO" then
		shake = math.max(shake, 1)
	end
end)

-- Attacks + dodge -----------------------------------------------------------------------------------------
local function attack(kind)
	local character = player.Character
	if not character or os.clock() < stunUntil or parked then
		return
	end
	if (localCool[kind] or 0) > os.clock() then
		return
	end
	Remotes.Attack:FireServer(kind)
end

local function dodge()
	local character, humanoid, root = parts()
	if not character or os.clock() < stunUntil or parked or humanoid.WalkSpeed == 0 then
		return -- also skips while frozen or locked (countdown, dialogue)
	end
	if (localCool.Dodge or 0) > os.clock() then
		return
	end
	local legs = Config.Parts[character:GetAttribute("Legs") or "Sneakers"]
	local cooldown = legs and legs.Stats and legs.Stats.DodgeCooldown or F.DodgeCooldown
	localCool.Dodge = os.clock() + cooldown
	Remotes.Dodge:FireServer()
	local dir = humanoid.MoveDirection
	if match then
		local mv = moveVector()
		local x = math.abs(mv.X) > 0.1 and mv.X or root.CFrame.LookVector.X
		dir = Vector3.new(x >= 0 and 1 or -1, 0, 0)
	elseif dir.Magnitude < 0.1 then
		local look = root.CFrame.LookVector
		dir = Vector3.new(look.X, 0, look.Z)
	end
	if dir.Magnitude > 0.01 then
		dashDir = dir.Unit
		dashUntil = os.clock() + 0.16
	end
end

UserInputService.InputBegan:Connect(function(input, processed)
	if input.KeyCode == Enum.KeyCode.Space or input.KeyCode == Enum.KeyCode.ButtonA then
		freshJumpPress = true
	end
	if processed then
		return
	end
	local key = input.KeyCode
	local t = input.UserInputType
	if t == Enum.UserInputType.MouseButton1 or key == Enum.KeyCode.ButtonX then
		attack("Light")
	elseif key == Enum.KeyCode.E or key == Enum.KeyCode.ButtonY or (t == Enum.UserInputType.MouseButton2 and match) then
		attack("Heavy")
	elseif key == Enum.KeyCode.Q or key == Enum.KeyCode.ButtonB then
		attack("Special")
	elseif key == Enum.KeyCode.F or key == Enum.KeyCode.ButtonR1 then
		dodge()
	end
end)

-- Extra air jumps from your legs ----------------------------------------------------------------------------
UserInputService.JumpRequest:Connect(function()
	local character, humanoid, root = parts()
	if not character or os.clock() < stunUntil or parked then
		return
	end
	local now = os.clock()
	local state = humanoid:GetState()
	local inAir = state == Enum.HumanoidStateType.Freefall or state == Enum.HumanoidStateType.Jumping
	if not inAir then
		return
	end
	-- Holding the key repeats JumpRequest; only a new press spends an air jump (touch taps always count).
	local keyboard = UserInputService:IsKeyDown(Enum.KeyCode.Space)
	if keyboard and not freshJumpPress then
		return
	end
	freshJumpPress = false
	if now - lastGroundJump < 0.18 or now - lastAirJump < 0.2 or airJumpsLeft <= 0 then
		return
	end
	airJumpsLeft -= 1
	lastAirJump = now
	local move = humanoid.MoveDirection
	if match then
		move = Vector3.new(moveVector().X, 0, 0)
		if move.Magnitude > 1 then
			move = move.Unit
		end
	end
	if character:GetAttribute("AirDash") then
		local dir = move.Magnitude > 0.1 and move.Unit or Vector3.new(root.CFrame.LookVector.X, 0, match and 0 or root.CFrame.LookVector.Z)
		if dir.Magnitude > 0.01 then
			dir = dir.Unit
		end
		root.AssemblyLinearVelocity = dir * 70 + Vector3.new(0, humanoid.JumpPower * 0.65, 0)
	else
		root.AssemblyLinearVelocity = Vector3.new(move.X * humanoid.WalkSpeed * 1.15, humanoid.JumpPower, move.Z * humanoid.WalkSpeed * 1.15)
	end
	humanoid:ChangeState(Enum.HumanoidStateType.Freefall)
end)

local function hookCharacter(character)
	stunUntil = 0
	stunToken = nil
	parked = false
	dashUntil = 0
	local humanoid = character:WaitForChild("Humanoid", 10)
	if not humanoid then
		return
	end
	airJumpsLeft = character:GetAttribute("AirJumps") or 1
	humanoid.StateChanged:Connect(function(_, new)
		if new == Enum.HumanoidStateType.Landed or new == Enum.HumanoidStateType.Running then
			airJumpsLeft = character:GetAttribute("AirJumps") or 1
		elseif new == Enum.HumanoidStateType.Jumping then
			lastGroundJump = os.clock()
		end
	end)
	if match then
		Workspace.CurrentCamera.CameraType = Enum.CameraType.Scriptable
	end
end
player.CharacterAdded:Connect(hookCharacter)
if player.Character then
	task.spawn(hookCharacter, player.Character)
end

-- Per-frame movement (runs right after Roblox's own controls so it can override them) ---------------------------
local function softPlatforms(root, humanoid, dropping)
	local feet = root.Position.Y - humanoid.HipHeight - root.Size.Y / 2
	local rising = root.AssemblyLinearVelocity.Y > 2 -- jumping up through it
	for _, plat in CollectionService:GetTagged("SoftPlatform") do
		local top = plat.Position.Y + plat.Size.Y / 2
		plat.CanCollide = not dropping and not rising and feet >= top - 0.7
	end
end

RunService:BindToRenderStep("MixControl", Enum.RenderPriority.Input.Value + 1, function()
	local character, humanoid, root = parts()
	if not character then
		return
	end
	local now = os.clock()
	local stunned = now < stunUntil
	if stunned and not parked then
		-- Fly upright (no tumbling), so the camera and controls stay readable.
		local look = root.CFrame.LookVector
		local flat = Vector3.new(look.X, 0, look.Z)
		if flat.Magnitude > 0.1 then
			root.CFrame = CFrame.lookAt(root.Position, root.Position + flat)
		end
		root.AssemblyAngularVelocity = Vector3.zero
	end
	if match and not parked then
		local mv = moveVector()
		if not stunned then
			humanoid:Move(Vector3.new(mv.X, 0, 0), false)
		end
		local z = match.PlaneZ
		if math.abs(root.Position.Z - z) > 0.05 then
			root.CFrame = root.CFrame + Vector3.new(0, 0, z - root.Position.Z)
		end
		local v = root.AssemblyLinearVelocity
		if math.abs(v.Z) > 0.01 then
			root.AssemblyLinearVelocity = Vector3.new(v.X, v.Y, 0)
		end
		softPlatforms(root, humanoid, mv.Z > 0.6)
	end
	if now < dashUntil and not stunned and not parked then
		local v = root.AssemblyLinearVelocity
		root.AssemblyLinearVelocity = Vector3.new(dashDir.X * F.DodgeSpeed, math.max(v.Y, -8), dashDir.Z * F.DodgeSpeed)
	end
	if character:GetAttribute("Glide") and not stunned and not parked then
		local held = UserInputService:IsKeyDown(Enum.KeyCode.Space) or humanoid.Jump
		local v = root.AssemblyLinearVelocity
		if held and v.Y < -10 then
			root.AssemblyLinearVelocity = Vector3.new(v.X, -10, v.Z)
		end
	end
end)

-- Fight camera: a side view that follows everyone and zooms with the spread -----------------------------------
RunService:BindToRenderStep("MixCamera", Enum.RenderPriority.Camera.Value + 1, function(dt)
	local camera = Workspace.CurrentCamera
	if not match then
		if shake > 0 then
			shake = math.max(0, shake - dt * 3)
		end
		return
	end
	camera.CameraType = Enum.CameraType.Scriptable
	local b = match.Bounds
	local minX, maxX, minY, maxY = math.huge, -math.huge, math.huge, -math.huge
	local count = 0
	local function add(model)
		local root = model and model:FindFirstChild("HumanoidRootPart")
		if root then
			local p = root.Position
			if p.X > b.MinX and p.X < b.MaxX and p.Y > b.MinY and p.Y < b.MaxY then
				minX, maxX = math.min(minX, p.X), math.max(maxX, p.X)
				minY, maxY = math.min(minY, p.Y), math.max(maxY, p.Y)
				count += 1
			end
		end
	end
	for _, fighter in match.Fighters do
		if not fighter.Out then
			add(fighter.Model)
		end
	end
	local origin = match.Origin
	if count == 0 then
		minX, maxX, minY, maxY = origin.X - 20, origin.X + 20, origin.Y, origin.Y + 10
	end
	local cx = math.clamp((minX + maxX) / 2, b.MinX + 25, b.MaxX - 25)
	local cy = math.clamp((minY + maxY) / 2, b.MinY + 25, b.MaxY - 30)
	local spread = math.max((maxX - minX) * 0.85, (maxY - minY) * 1.5)
	local dist = math.clamp(spread + 34, 46, 120)
	local target = Vector3.new(cx, cy + 7, match.PlaneZ + dist)
	if not camPos then
		camPos = target
	end
	camPos = camPos:Lerp(target, 1 - math.exp(-dt * 5))
	local cf = CFrame.lookAt(camPos, Vector3.new(camPos.X, camPos.Y - 7, match.PlaneZ))
	if shake > 0 then
		shake = math.max(0, shake - dt * 3)
		local s = shake * 0.6
		cf = cf * CFrame.new((math.random() - 0.5) * s, (math.random() - 0.5) * s, 0)
	end
	camera.CFrame = cf
end)

-- Mobile action buttons -----------------------------------------------------------------------------------------
if UserInputService.TouchEnabled then
	local gui = Instance.new("ScreenGui")
	gui.Name = "MixButtons"
	gui.ResetOnSpawn = false
	gui.Parent = player:WaitForChild("PlayerGui")
	local buttons = {
		{ "Light", "👊", "Jab", UDim2.new(1, -96, 1, -230), Color3.fromRGB(240, 240, 250) },
		{ "Heavy", "💪", "Heavy", UDim2.new(1, -176, 1, -190), Color3.fromRGB(255, 90, 90) },
		{ "Special", "✨", "Special", UDim2.new(1, -170, 1, -280), Color3.fromRGB(255, 210, 60) },
		{ "Dodge", "💨", "Dodge", UDim2.new(1, -92, 1, -320), Color3.fromRGB(110, 200, 255) },
	}
	for _, spec in buttons do
		local kind = spec[1]
		local b = Instance.new("TextButton")
		b.Name = kind
		b.Size = UDim2.fromOffset(70, 70)
		b.Position = spec[4]
		b.BackgroundColor3 = spec[5]
		b.BackgroundTransparency = 0.25
		b.Text = spec[2] .. "\n" .. spec[3]
		b.TextSize = 15
		b.Font = Enum.Font.FredokaOne
		b.TextColor3 = Color3.fromRGB(20, 20, 30)
		b.AutoButtonColor = true
		local corner = Instance.new("UICorner")
		corner.CornerRadius = UDim.new(1, 0)
		corner.Parent = b
		b.Parent = gui
		b.Activated:Connect(function()
			if kind == "Dodge" then
				dodge()
			else
				attack(kind)
			end
		end)
		RunService.Heartbeat:Connect(function()
			local ready = (localCool[kind] or 0) <= os.clock()
			b.BackgroundTransparency = ready and 0.25 or 0.7
		end)
	end
end
