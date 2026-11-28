-- Crystal mining (manual via ProximityPrompt + Auto Collect pass).
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Config = require(ReplicatedStorage.Shared.Config)
local Remotes = require(ReplicatedStorage.Shared.Remotes)
local DataService = require(script.Parent.DataService)
local Economy = require(script.Parent.Economy)

local Mining = {}

local crystalsFolder
local lockedWarn = {} -- [Player] = os.clock()

function Mining.Mine(player, crystal, silent)
	if typeof(crystal) ~= "Instance" or crystal.Parent ~= crystalsFolder then
		return false
	end
	if not crystal:GetAttribute("Active") then
		return false
	end
	local data = DataService.Get(player)
	local zone = Config.ZoneById[crystal:GetAttribute("Zone")]
	if not data or not zone then
		return false
	end
	local root = player.Character and player.Character:FindFirstChild("HumanoidRootPart")
	if not root or (root.Position - crystal.Position).Magnitude > Config.MineRange then
		return false
	end
	if not data.Zones[zone.Id] then
		if not silent and (not lockedWarn[player] or os.clock() - lockedWarn[player] > 2) then
			lockedWarn[player] = os.clock()
			Economy.Toast(player, zone.Name .. " is locked! Find its unlock pedestal.")
		end
		return false
	end

	crystal:SetAttribute("Active", false)
	crystal.Transparency = 1
	local prompt = crystal:FindFirstChildOfClass("ProximityPrompt")
	if prompt then
		prompt.Enabled = false
	end

	local amount = math.max(1, math.floor(Config.CrystalValue * zone.Mult * Economy.GetMultiplier(player)))
	data.TotalMined += 1
	Economy.AddCoins(player, amount)
	Remotes.Notify:FireClient(player, { Type = "Mine", Amount = amount, Position = crystal.Position })

	task.delay(Config.CrystalRespawn, function()
		if crystal.Parent then
			crystal.Transparency = 0
			crystal:SetAttribute("Active", true)
			if prompt then
				prompt.Enabled = true
			end
		end
	end)
	return true
end

function Mining.Init(folder)
	crystalsFolder = folder
	task.spawn(function()
		while true do
			task.wait(1)
			for _, player in Players:GetPlayers() do
				if Economy.HasPass(player, "AutoCollect") then
					local root = player.Character and player.Character:FindFirstChild("HumanoidRootPart")
					if root then
						local mined = 0
						for _, crystal in crystalsFolder:GetChildren() do
							if
								crystal:GetAttribute("Active")
								and (crystal.Position - root.Position).Magnitude <= Config.AutoCollectRange
								and Mining.Mine(player, crystal, true)
							then
								mined += 1
								if mined >= Config.AutoCollectPerTick then
									break
								end
							end
						end
					end
				end
			end
		end
	end)
end

function Mining.ClearPlayer(player)
	lockedWarn[player] = nil
end

return Mining
