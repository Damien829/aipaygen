local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local Remotes = require(ReplicatedStorage.Shared.Remotes) -- creates the remotes first
local DataService = require(script.Parent.DataService)
local Economy = require(script.Parent.Economy)
local Pets = require(script.Parent.Pets)
local Mining = require(script.Parent.Mining)
local Cosmetics = require(script.Parent.Cosmetics)
local Monetization = require(script.Parent.Monetization)
local World = require(script.Parent.World)

Economy.Start()
Monetization.Init()

local crystals = World.Build({
	Mine = function(player, crystal)
		Mining.Mine(player, crystal, false)
	end,
	Unlock = Economy.UnlockZone,
	Hatch = Pets.Hatch,
})
Mining.Init(crystals)

Remotes.EquipPet.OnServerInvoke = Pets.Toggle
Remotes.Rebirth.OnServerInvoke = Economy.Rebirth
Remotes.ClaimDaily.OnServerInvoke = Economy.ClaimDaily
Remotes.Cosmetic.OnServerInvoke = Cosmetics.Handle
-- The client asks for its state once its UI is ready (the join-time push can arrive too early).
Remotes.RequestState.OnServerEvent:Connect(function(player)
	Economy.Push(player)
end)

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
	Economy.SetupPlayer(player)
	Economy.LoadPasses(player)
	Pets.Refresh(player)
	Cosmetics.Refresh(player)
	task.spawn(Economy.TrackFriends, player)
	task.delay(90, function()
		if player.Parent then
			Economy.Offer(player, "StarterPack", "New here? The Starter Pack gives 25K coins and a Wolf pet!")
		end
	end)
end

local function onPlayerRemoving(player)
	DataService.Release(player)
	Economy.ClearPlayer(player)
	Pets.ClearPlayer(player)
	Mining.ClearPlayer(player)
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
			DataService.Save(player)
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
