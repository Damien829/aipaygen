-- Cinematic intro: a camera fly-over of the lobby with big titles, then it lands behind you.
-- New players see the full tour; returning players get a short title shot. Always skippable.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")
local UserInputService = game:GetService("UserInputService")
local Workspace = game:GetService("Workspace")

local Remotes = require(ReplicatedStorage.Shared.Remotes)

local player = Players.LocalPlayer
player:SetAttribute("IntroPlaying", true) -- the UI waits for this before opening any panel

local function look(from, at)
	return CFrame.lookAt(from, at)
end

local SHOTS = {
	{
		From = look(Vector3.new(-70, 75, 150), Vector3.new(0, 10, -20)),
		To = look(Vector3.new(70, 60, 120), Vector3.new(0, 10, -20)),
		Time = 3.2,
		Title = "MIX & SMASH",
		Caption = "Build a fighter from parts. Smash everyone off the stage!",
	},
	{
		From = look(Vector3.new(-45, 28, -35), Vector3.new(0, 6, -82)),
		To = look(Vector3.new(45, 28, -35), Vector3.new(0, 6, -82)),
		Time = 2.8,
		Title = "⚔️ BATTLE",
		Caption = "Step on a pad: 1v1 Ranked or Free-for-All. Climb from Bronze to Champion!",
	},
	{
		From = look(Vector3.new(55, 22, -30), Vector3.new(90, 6, 0)),
		To = look(Vector3.new(55, 22, 30), Vector3.new(90, 6, 0)),
		Time = 2.8,
		Title = "🔧 PART FORGE",
		Caption = "18 heads, arms and legs. Every combo works. Find your favorite!",
	},
	{
		From = look(Vector3.new(-18, 16, -62), Vector3.new(0, 10, -98)),
		To = look(Vector3.new(18, 14, -70), Vector3.new(0, 10, -98)),
		Time = 2.8,
		Title = "📖 STORY",
		Caption = "Dr. Junk stole every part in Mix City. Beat his bosses and win them back!",
	},
}

-- UI ---------------------------------------------------------------------------------------------
local gui = Instance.new("ScreenGui")
gui.Name = "MixIntro"
gui.IgnoreGuiInset = true
gui.DisplayOrder = 50
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")

local function bar(top)
	local f = Instance.new("Frame")
	f.BackgroundColor3 = Color3.new(0, 0, 0)
	f.BorderSizePixel = 0
	f.Size = UDim2.fromScale(1, 0.12)
	f.Position = top and UDim2.fromScale(0, 0) or UDim2.fromScale(0, 0.88)
	f.Parent = gui
	return f
end
bar(true)
bar(false)

local title = Instance.new("TextLabel")
title.BackgroundTransparency = 1
title.AnchorPoint = Vector2.new(0.5, 0.5)
title.Position = UDim2.fromScale(0.5, 0.42)
title.Size = UDim2.fromScale(0.8, 0.16)
title.Font = Enum.Font.FredokaOne
title.TextScaled = true
title.TextColor3 = Color3.fromRGB(255, 215, 70)
title.TextStrokeTransparency = 0
title.TextStrokeColor3 = Color3.fromRGB(40, 20, 60)
title.Text = ""
title.Parent = gui
local titleScale = Instance.new("UIScale")
titleScale.Parent = title

local caption = Instance.new("TextLabel")
caption.BackgroundTransparency = 1
caption.AnchorPoint = Vector2.new(0.5, 0.5)
caption.Position = UDim2.fromScale(0.5, 0.94)
caption.Size = UDim2.fromScale(0.85, 0.06)
caption.Font = Enum.Font.FredokaOne
caption.TextScaled = true
caption.TextColor3 = Color3.new(1, 1, 1)
caption.Text = ""
caption.Parent = gui

local skip = Instance.new("TextButton")
skip.AnchorPoint = Vector2.new(1, 0.5)
skip.Position = UDim2.new(1, -16, 0.06, 0)
skip.Size = UDim2.fromOffset(120, 40)
skip.BackgroundColor3 = Color3.fromRGB(60, 55, 90)
skip.TextColor3 = Color3.new(1, 1, 1)
skip.Font = Enum.Font.FredokaOne
skip.TextSize = 20
skip.Text = "Skip ⏭"
skip.Parent = gui
local corner = Instance.new("UICorner")
corner.CornerRadius = UDim.new(0, 10)
corner.Parent = skip

-- Flow ---------------------------------------------------------------------------------------------
local skipped = false
local function finish()
	if not gui.Parent then
		return
	end
	gui:Destroy()
	local camera = Workspace.CurrentCamera
	camera.CameraType = Enum.CameraType.Custom
	local character = player.Character
	local humanoid = character and character:FindFirstChildOfClass("Humanoid")
	if humanoid then
		camera.CameraSubject = humanoid
	end
	local mixUI = player.PlayerGui:FindFirstChild("MixUI")
	if mixUI then
		mixUI.Enabled = true
	end
	local actions = player.PlayerGui:FindFirstChild("MixActions")
	if actions then
		actions.Enabled = true
	end
	player:SetAttribute("IntroPlaying", false)
end
skip.Activated:Connect(function()
	skipped = true
	finish()
end)
UserInputService.InputBegan:Connect(function(input)
	if input.KeyCode == Enum.KeyCode.Escape or input.KeyCode == Enum.KeyCode.Return then
		skipped = true
		finish()
	end
end)

local function showText(t, c)
	title.Text = t
	caption.Text = c
	titleScale.Scale = 0.4
	TweenService:Create(titleScale, TweenInfo.new(0.45, Enum.EasingStyle.Back, Enum.EasingDirection.Out), { Scale = 1 }):Play()
end

task.spawn(function()
	-- Wait for the lobby and your profile (to know whether you're new).
	local lobby = Workspace:WaitForChild("Lobby", 30)
	local seenHelp = false
	local got = false
	local conn = Remotes.State.OnClientEvent:Connect(function(state)
		seenHelp = state.SeenHelp == true
		got = true
	end)
	local waited = 0
	while not got and waited < 6 do
		waited += task.wait(0.1)
	end
	conn:Disconnect()
	if not lobby or skipped then
		finish()
		return
	end
	for _, name in { "MixUI", "MixActions" } do
		local other = player.PlayerGui:FindFirstChild(name)
		if other then
			other.Enabled = false
		end
	end
	local camera = Workspace.CurrentCamera
	camera.CameraType = Enum.CameraType.Scriptable
	local shots = seenHelp and { SHOTS[1] } or SHOTS
	for _, shot in shots do
		if skipped then
			return
		end
		camera.CFrame = shot.From
		showText(shot.Title, shot.Caption)
		local tween = TweenService:Create(camera, TweenInfo.new(shot.Time, Enum.EasingStyle.Sine, Enum.EasingDirection.InOut), { CFrame = shot.To })
		tween:Play()
		task.wait(shot.Time)
	end
	if skipped then
		return
	end
	-- Swoop down behind your fighter.
	local character = player.Character or player.CharacterAdded:Wait()
	local root = character:WaitForChild("HumanoidRootPart", 5)
	if root then
		showText("LET'S GO!", "Click to jab · E heavy · Q special · F dodge")
		local behind = root.CFrame * CFrame.new(0, 4, 12)
		local tween = TweenService:Create(camera, TweenInfo.new(1.3, Enum.EasingStyle.Quad, Enum.EasingDirection.Out), { CFrame = CFrame.lookAt(behind.Position, root.Position + Vector3.new(0, 2, 0)) })
		tween:Play()
		task.wait(1.4)
	end
	finish()
end)
