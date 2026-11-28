-- Game pass + developer product handling. Receipts are idempotent and saved immediately.
local MarketplaceService = game:GetService("MarketplaceService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Config = require(ReplicatedStorage.Shared.Config)
local Format = require(ReplicatedStorage.Shared.Format)
local DataService = require(script.Parent.DataService)
local Economy = require(script.Parent.Economy)
local Cosmetics = require(script.Parent.Cosmetics)

local Monetization = {}

local MAX_RECEIPTS = 50

local function findByProductId(productId)
	for key, info in Config.Products do
		if info.Id ~= 0 and info.Id == productId then
			return key, info
		end
	end
end

local function findCosmetic(productId)
	for key, info in Config.Cosmetics do
		if info.Id and info.Id ~= 0 and info.Id == productId then
			return key
		end
	end
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

	local cosmeticId = findCosmetic(receipt.ProductId)
	local key, info
	if not cosmeticId then
		key, info = findByProductId(receipt.ProductId)
		if not key then
			warn("[Monetization] Unknown product id", receipt.ProductId)
			return Enum.ProductPurchaseDecision.NotProcessedYet
		end
	end

	if cosmeticId then
		Cosmetics.Grant(player, cosmeticId)
	elseif info.Coins then
		local amount = info.Coins * (1 + data.Rebirths)
		Economy.AddCoins(player, amount)
		Economy.Toast(player, "+" .. Format.Number(amount) .. " coins!")
		if info.Pet and Config.Pets[info.Pet] then
			data.Pets[info.Pet] = (data.Pets[info.Pet] or 0) + 1
		end
		if info.OneTime then
			data.StarterBought = true
		end
		Economy.Push(player)
	elseif info.BoostSeconds then
		data.BoostUntil = math.max(os.time(), data.BoostUntil) + info.BoostSeconds
		Economy.Toast(player, "2x Boost active!")
		Economy.Push(player)
	end

	table.insert(data.Receipts, receipt.PurchaseId)
	while #data.Receipts > MAX_RECEIPTS do
		table.remove(data.Receipts, 1)
	end

	if not DataService.Save(player) then
		-- Could not persist the receipt; make Roblox retry later rather than risk a double grant.
		table.remove(data.Receipts)
		return Enum.ProductPurchaseDecision.NotProcessedYet
	end
	return Enum.ProductPurchaseDecision.PurchaseGranted
end

function Monetization.Init()
	MarketplaceService.ProcessReceipt = processReceipt

	MarketplaceService.PromptSubscriptionPurchaseFinished:Connect(function(player, subscriptionId)
		if subscriptionId == Config.Subscription.Id then
			task.spawn(function()
				Economy.RefreshClub(player)
				Cosmetics.Refresh(player)
				if Economy.IsClub(player) then
					Economy.Toast(player, "Welcome to " .. Config.Subscription.Name .. "!")
				end
			end)
		end
	end)

	MarketplaceService.PromptGamePassPurchaseFinished:Connect(function(player, passId, wasPurchased)
		if not wasPurchased then
			return
		end
		for key, info in Config.GamePasses do
			if info.Id ~= 0 and info.Id == passId then
				Economy.GrantPass(player, key)
				return
			end
		end
	end)
end

return Monetization
