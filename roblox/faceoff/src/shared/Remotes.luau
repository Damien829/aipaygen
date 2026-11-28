-- Server creates the remotes; client waits for them. Same API on both sides.
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local EVENTS = {
	"State", -- server -> client: profile snapshot
	"Notify", -- server -> client: toasts, feed, hit/KO effects, open panel, offers
	"Match", -- server -> client: arena / match / story state
	"Attack", -- client -> server: "Light" | "Heavy" | "Special"
	"Dodge", -- client -> server
	"Knockback", -- server -> client: velocity, stun seconds
	"Dialogue", -- server -> client: story lines
	"DialogueDone", -- client -> server
	"Queue", -- client -> server: "Ranked" | "FFA" | nil (leave)
	"RequestState", -- client -> server
}
local FUNCTIONS = { "Equip", "BuyPart", "BuyPaint", "SetPaint", "ClaimDaily", "StartStory", "ClaimQuest", "SetTitle" }

local Remotes = {}

if RunService:IsServer() then
	local folder = Instance.new("Folder")
	folder.Name = "Remotes"
	for _, name in EVENTS do
		local remote = Instance.new("RemoteEvent")
		remote.Name = name
		remote.Parent = folder
		Remotes[name] = remote
	end
	for _, name in FUNCTIONS do
		local remote = Instance.new("RemoteFunction")
		remote.Name = name
		remote.Parent = folder
		Remotes[name] = remote
	end
	folder.Parent = ReplicatedStorage
else
	local folder = ReplicatedStorage:WaitForChild("Remotes")
	for _, name in EVENTS do
		Remotes[name] = folder:WaitForChild(name)
	end
	for _, name in FUNCTIONS do
		Remotes[name] = folder:WaitForChild(name)
	end
end

return Remotes
