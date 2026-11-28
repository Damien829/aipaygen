-- Game pass + developer product handling. Receipts are idempotent and saved immediately.
-- Every product grants exactly what its description says. No random rewards are sold.
local MarketplaceService = game:GetService("MarketplaceService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Config = require(ReplicatedStorage.Shared.Config)
local Format = require(ReplicatedStorage.Shared.Format)
local DataService = require(script.Parent.DataService)
local Profile = require(script.Parent.Profile)

local Monetization = {}

local MAX_RECEIPTS = 50
local GOLD = Color3.fromRGB(255, 205, 70)

local function findByProductId(productId)
	for key, info in Config.Products do
		if info.Id ~= 0 and info.Id == productId then
			return key, info
		end
	end
	return nil, nil
end

-- Grants the product. Returns false only if nothing could be granted (unknown product).
local function grant(player, data, productId)
	local key, info = findByProductId(productId)
	if not key then
		warn("[Monetization] Unknown product id", productId)
		return false
	end
	if info.OneTime and data.StarterBought then
		-- Bought twice somehow (two prompts open at once): give the coin value instead of nothing.
		data.Coins += 1500
		Profile.Toast(player, "You already had the " .. info.Name .. ", so you got 1,500 coins instead.")
		Profile.Push(player)
		return true
	end
	if info.Coins then
		data.Coins += info.Coins
		Profile.Toast(player, "+" .. Format.Number(info.Coins) .. " coins!", GOLD)
	end
	if info.Parts then
		for _, partKey in info.Parts do
			Profile.GrantPart(player, partKey, true)
		end
	end
	if info.Paint then
		Profile.GrantPaint(player, info.Paint, true)
	end
	if info.Revive then
		data.Revives += info.Revive
	end
	if info.OneTime then
		data.StarterBought = true
	end
	Profile.Celebrate(player, info.Name .. "!", info.Desc, info.Icon)
	Profile.Feed(player.DisplayName .. " got the " .. info.Name .. "!", GOLD)
	Profile.Push(player)
	return true
end

local function processReceipt(receipt)
	local player = Players:GetPlayerByUserId(receipt.PlayerId)
	local data = player and DataService.Get(player)
	if not player or not data then
		return Enum.ProductPurchaseDecision.NotProcessedYet
	end
	if table.find(data.Receipts, receipt.PurchaseId) then
		return Enum.ProductPurchaseDecision.PurchaseGranted
	end

	if not grant(player, data, receipt.ProductId) then
		return Enum.ProductPurchaseDecision.NotProcessedYet
	end

	table.insert(data.Receipts, receipt.PurchaseId)
	while #data.Receipts > MAX_RECEIPTS do
		table.remove(data.Receipts, 1)
	end

	if not DataService.Save(player) then
		-- Could not persist yet. The item is already granted, so KEEP the receipt id in memory:
		-- Roblox will retry, the table.find check above then confirms it without a second grant,
		-- and the normal autosave / leave-save persists the data and the receipt together.
		return Enum.ProductPurchaseDecision.NotProcessedYet
	end
	return Enum.ProductPurchaseDecision.PurchaseGranted
end

function Monetization.Init()
	MarketplaceService.ProcessReceipt = processReceipt

	MarketplaceService.PromptGamePassPurchaseFinished:Connect(function(player, passId, wasPurchased)
		if not wasPurchased then
			return
		end
		for key, info in Config.GamePasses do
			if info.Id ~= 0 and info.Id == passId then
				Profile.GrantPass(player, key)
				if key == "VIP" then
					Profile.DressCharacter(player) -- Royal paint becomes available
				end
				return
			end
		end
	end)
end

return Monetization
