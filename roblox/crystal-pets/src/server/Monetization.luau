-- Game pass + developer product handling. Receipts are idempotent and saved immediately.
local MarketplaceService = game:GetService("MarketplaceService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Config = require(ReplicatedStorage.Shared.Config)
local Format = require(ReplicatedStorage.Shared.Format)
local DataService = require(script.Parent.DataService)
local Economy = require(script.Parent.Economy)

local Monetization = {}

local MAX_RECEIPTS = 50

local function findByProductId(productId)
	for key, info in Config.Products do
		if info.Id ~= 0 and info.Id == productId then
			return key, info
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

	local key, info = findByProductId(receipt.ProductId)
	if not key then
		warn("[Monetization] Unknown product id", receipt.ProductId)
		return Enum.ProductPurchaseDecision.NotProcessedYet
	end

	if info.Coins then
		local amount = info.Coins * (1 + data.Rebirths)
		Economy.AddCoins(player, amount)
		Economy.Toast(player, "+" .. Format.Number(amount) .. " coins!")
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
