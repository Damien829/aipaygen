local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")
local Workspace = game:GetService("Workspace")

local Config = require(ReplicatedStorage.Shared.Config)
local Remotes = require(ReplicatedStorage.Shared.Remotes) -- creates the remotes first
local DataService = require(script.Parent.DataService)
local Combat = require(script.Parent.Combat)
local Profile = require(script.Parent.Profile)
local Monetization = require(script.Parent.Monetization)
local Lobby = require(script.Parent.Lobby)
local Match = require(script.Parent.Match)
local Story = require(script.Parent.Story)

Workspace.Gravity = Config.Gravity
Players.CharacterAutoLoads = true

Monetization.Init()
local lobbyInfo = Lobby.Build()
Match.Init(lobbyInfo)
Story.Init()

-- Quest hooks from combat
Combat.Hooks.OnDamage = function(attacker, target, amount)
	if attacker.Player then
		Profile.Quest(attacker.Player, target.IsDummy and "Train" or "Damage", amount)
	end
end
Combat.Hooks.OnSpecial = function(rec)
	if rec.Player and not rec.Ctx.Lobby then
		Profile.Quest(rec.Player, "Special", 1)
	end
end
Profile.OnLoadoutChanged = function(player)
	local rec = Combat.ForPlayer(player)
	if rec then
		Combat.ApplyStats(rec)
	end
end

-- Remotes ---------------------------------------------------------------------------------------
Remotes.Equip.OnServerInvoke = function(player, slot, key)
	return Profile.Equip(player, slot, key)
end
Remotes.BuyPart.OnServerInvoke = function(player, key)
	if type(key) ~= "string" then
		return false
	end
	return Profile.BuyPart(player, key)
end
Remotes.BuyPaint.OnServerInvoke = function(player, key)
	if type(key) ~= "string" then
		return false
	end
	return Profile.BuyPaint(player, key)
end
Remotes.SetPaint.OnServerInvoke = function(player, key)
	if type(key) ~= "string" then
		return false
	end
	return Profile.SetPaint(player, key)
end
Remotes.ClaimDaily.OnServerInvoke = Profile.ClaimDaily
Remotes.ClaimQuest.OnServerInvoke = Profile.ClaimQuest
Remotes.SetTitle.OnServerInvoke = Profile.SetTitle
-- The client asks for its state once its UI is ready (the join-time push can arrive too early).
Remotes.RequestState.OnServerEvent:Connect(function(player, what)
	if what == "HelpSeen" then
		Profile.MarkHelpSeen(player)
	end
	Profile.Push(player)
end)

-- Characters ---------------------------------------------------------------------------------------
local function onCharacter(player, character)
	local humanoid = character:WaitForChild("Humanoid", 10)
	local root = character:WaitForChild("HumanoidRootPart", 10)
	if not humanoid or not root or not player.Parent then
		return
	end
	-- Nothing in this game deals health damage: KOs come from the blast zones.
	humanoid.BreakJointsOnDeath = false
	humanoid.MaxHealth = 1e6
	humanoid.Health = 1e6
	local data = DataService.Get(player)
	if not data then
		return
	end
	Combat.Register(character, { Player = player, Name = player.DisplayName, Loadout = data.Loadout })
	Profile.DressCharacter(player)
	Profile.RefreshTag(player)
	-- Avatar bundles can swap body parts once the appearance loads: dress again then.
	task.spawn(function()
		if not player:HasAppearanceLoaded() then
			player.CharacterAppearanceLoaded:Wait()
		end
		if player.Character == character and character.Parent then
			Profile.DressCharacter(player)
			Profile.RefreshTag(player)
		end
	end)
	if not Match.OnCharacter(player) then
		character:PivotTo(Match.LobbyCFrame())
	end
end

local function onPlayerAdded(player)
	local data = DataService.Load(player)
	if not data then
		player:Kick("Could not load your data. Please rejoin in a minute.")
		return
	end
	if not player.Parent then
		DataService.Release(player) -- left while loading
		return
	end
	Profile.SetupPlayer(player)
	Profile.LoadPasses(player) -- yields (one web call per pass)
	if not player.Parent then
		DataService.Release(player)
		return
	end
	player.CharacterAdded:Connect(function(character)
		onCharacter(player, character)
	end)
	if player.Character then
		task.spawn(onCharacter, player, player.Character)
	end
	Profile.Push(player)

	-- One honest, skippable VIP suggestion for players who stay a while (never mid-fight).
	task.delay(420, function()
		if player.Parent and not Profile.GetActivity(player) then
			Profile.Offer(player, "Pass", "VIP", "Enjoying Mix & Smash? VIP gives +50% coins and Star XP forever, a gold name and the Royal paint.")
		end
	end)
end

local function onPlayerRemoving(player)
	Match.ClearPlayer(player)
	Story.ClearPlayer(player)
	DataService.Release(player)
	Profile.ClearPlayer(player)
end

Players.PlayerAdded:Connect(function(player)
	task.spawn(onPlayerAdded, player)
end)
Players.PlayerRemoving:Connect(onPlayerRemoving)
for _, player in Players:GetPlayers() do
	task.spawn(onPlayerAdded, player)
end

-- Autosave every minute.
task.spawn(function()
	while true do
		task.wait(60)
		for _, player in Players:GetPlayers() do
			task.spawn(DataService.Save, player)
		end
	end
end)

game:BindToClose(function()
	local pending = 0
	for _, player in Players:GetPlayers() do
		pending += 1
		task.spawn(function()
			DataService.Save(player, true)
			pending -= 1
		end)
	end
	local deadline = os.clock() + 25
	while pending > 0 and os.clock() < deadline do
		task.wait()
	end
	if RunService:IsStudio() then
		task.wait(0.5)
	end
end)
