-- Lobby queue pads -> 1v1 Ranked or Free-for-All rounds. A bot fills in if you wait alone,
-- so nobody ever sits in an empty queue. 3 lives each; last one standing wins.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Workspace = game:GetService("Workspace")

local Config = require(ReplicatedStorage.Shared.Config)
local Remotes = require(ReplicatedStorage.Shared.Remotes)
local Arena = require(script.Parent.Arena)
local Combat = require(script.Parent.Combat)
local DataService = require(script.Parent.DataService)
local Npc = require(script.Parent.Npc)
local Profile = require(script.Parent.Profile)

local F = Config.Fight

local Match = {}

local MODES = { Ranked = { Max = 2, Title = "1v1 RANKED" }, FFA = { Max = F.FFAMax, Title = "FREE-FOR-ALL" } }

local queues = { Ranked = {}, FFA = {} }
local joinedAt = {} -- [Player] = os.clock()
local queueOf = {} -- [Player] = mode
local ffaReadyAt = nil -- when the FFA queue reached 2 players
local entryOf = {} -- [Player] = entry while in a match
local pads = {} -- [mode] = { Part = BasePart, Label = TextLabel }
local lobbySpawn = CFrame.new(0, 5, 0)
local rng = Random.new()
local busyToastAt = {} -- [Player] = os.clock() of the last "arenas busy" toast

local function serverNow()
	return Workspace:GetServerTimeNow()
end

function Match.LobbyCFrame()
	local angle = rng:NextNumber(0, math.pi * 2)
	return lobbySpawn * CFrame.new(math.cos(angle) * 6, 0, math.sin(angle) * 6)
end

-- Queues ------------------------------------------------------------------------------------------
local function leaveQueue(player, quiet)
	local mode = queueOf[player]
	if not mode then
		return
	end
	local index = table.find(queues[mode], player)
	if index then
		table.remove(queues[mode], index)
	end
	queueOf[player] = nil
	joinedAt[player] = nil
	if not quiet and player.Parent then
		Remotes.Notify:FireClient(player, { Type = "Queue", Mode = nil })
	end
end

local function joinQueue(player, mode)
	table.insert(queues[mode], player)
	queueOf[player] = mode
	joinedAt[player] = os.clock()
	Remotes.Notify:FireClient(player, { Type = "Queue", Mode = mode, Since = serverNow() })
end

local function onPad(position, pad)
	local part = pad.Part
	local offset = position - part.Position
	return Vector3.new(offset.X, 0, offset.Z).Magnitude < math.min(part.Size.Y, part.Size.Z) / 2 and offset.Y > -2 and offset.Y < 9
end

-- Sends the current arena / match state to every player still in it.
function Match.Broadcast(ctx)
	local fighters = {}
	for _, entry in ctx.Entries do
		table.insert(fighters, {
			Name = entry.Name,
			Model = entry.Rec and entry.Rec.Model,
			Stocks = entry.Stocks,
			MaxStocks = entry.MaxStocks,
			Out = entry.Out,
			Bot = entry.Player == nil,
			Boss = entry.Boss,
			Hero = entry.Player ~= nil,
		})
	end
	local payload = {
		Phase = ctx.Phase,
		Kind = ctx.Kind,
		Mode = ctx.Mode,
		Ranked = ctx.Ranked,
		Arena = ctx.Name,
		Origin = ctx.Origin,
		PlaneZ = ctx.PlaneZ,
		StageHalf = ctx.StageHalf,
		Bounds = ctx.Bounds,
		EndsAt = ctx.EndsAt,
		Banner = ctx.Banner,
		Fighters = fighters,
	}
	for _, entry in ctx.Entries do
		local player = entry.Player
		if player and player.Parent and entryOf[player] == entry and not entry.Left then
			Remotes.Match:FireClient(player, payload)
		end
	end
end

-- Puts a player's current character into the arena at `position`.
function Match.Place(entry, ctx, position, invuln)
	local rec = Combat.ForPlayer(entry.Player)
	if not rec then
		return nil
	end
	Combat.SetCtx(rec, ctx)
	rec.Entry = entry
	rec.Team = entry.Team
	entry.Rec = rec
	Combat.Respawn(rec, Arena.Facing(ctx, position), invuln or 0.5)
	Combat.SetLocked(rec, ctx.Phase ~= "Fight")
	return rec
end

function Match.SendHome(player)
	entryOf[player] = nil
	Profile.SetActivity(player, nil)
	if not player.Parent then
		return
	end
	local rec = Combat.ForPlayer(player)
	if rec then
		Combat.SetCtx(rec, Combat.LobbyCtx)
		rec.Entry = nil
		rec.Team = nil
		rec.Locked = false
		Combat.Respawn(rec, Match.LobbyCFrame(), 1)
	end
	Remotes.Match:FireClient(player, { Phase = "None" })
end

function Match.Track(player, entry)
	entryOf[player] = entry
end

function Match.EntryOf(player)
	return entryOf[player]
end

-- Stops a KO'd fighter where they are until they respawn (so they don't fall forever).
function Match.Park(rec)
	if rec.Root and rec.Root.Parent then
		rec.Root.AssemblyLinearVelocity = Vector3.zero
		rec.Root.Anchored = true
	end
	if rec.Player then
		Remotes.Notify:FireClient(rec.Player, { Type = "Parked" })
	end
end

local function unpark(rec)
	if rec.Root and rec.Root.Parent then
		rec.Root.Anchored = false
	end
end
Match.Unpark = unpark

-- Results ------------------------------------------------------------------------------------------
local function award(ctx, entry)
	if entry.Rewarded or not entry.Player then
		return
	end
	entry.Rewarded = true
	local player = entry.Player
	if not player.Parent then
		return
	end
	local won = entry.Place == 1
	local summary = Profile.MatchResult(player, {
		Won = won,
		Placement = entry.Place,
		Players = #ctx.Entries,
		KOs = entry.KOs,
		Ranked = ctx.Ranked,
		Bots = ctx.HasBots,
	})
	if summary then
		Remotes.Notify:FireClient(player, {
			Type = "Results",
			Won = won,
			Place = entry.Place,
			Of = #ctx.Entries,
			KOs = entry.KOs,
			Coins = summary.Coins,
			XP = summary.XP,
			Trophies = summary.Trophies,
			Streak = summary.Streak,
			StreakBonus = summary.StreakBonus,
			Rank = summary.Rank,
			Ranked = ctx.Ranked,
			Bots = ctx.HasBots,
		})
	end
	if entry.Rec then
		entry.Rec.Out = true
		Combat.SetLocked(entry.Rec, true)
	end
	task.delay(4.5, function()
		if entryOf[player] == entry then
			if entry.Rec then
				unpark(entry.Rec)
			end
			Match.SendHome(player)
		end
	end)
end

local function aliveEntries(ctx)
	local list = {}
	for _, entry in ctx.Entries do
		if not entry.Out then
			table.insert(list, entry)
		end
	end
	return list
end

local function eliminate(ctx, entry)
	if entry.Out then
		return
	end
	entry.Out = true
	if entry.Rec then
		entry.Rec.Out = true
	end
	local remaining = #aliveEntries(ctx)
	entry.Place = remaining + 1
	if entry.Player and remaining > 1 then
		award(ctx, entry) -- free-for-all: you get your results now and can queue again
	end
	if not entry.Player and entry.Rec and entry.Rec.Model.Parent then
		entry.Rec.Model:Destroy()
	end
end

local function onKO(ctx, rec, position)
	local entry = rec.Entry
	if not entry or entry.Out or ctx.Done then
		return
	end
	Match.Park(rec)
	entry.Stocks -= 1
	local killer = rec.LastHitBy
	if killer and killer ~= rec and killer.Entry and os.clock() - rec.LastHitAt <= F.KOCreditSeconds then
		killer.Entry.KOs += 1
	end
	local b = ctx.Bounds
	local spot = Vector3.new(math.clamp(position.X, b.MinX, b.MaxX), math.clamp(position.Y, b.MinY, b.MaxY), ctx.PlaneZ)
	Combat.NotifyCtx(ctx, { Type = "KO", Position = spot, Name = entry.Name, Model = rec.Model, Left = entry.Stocks })
	if entry.Stocks <= 0 then
		eliminate(ctx, entry)
		Match.Broadcast(ctx)
		return
	end
	Match.Broadcast(ctx)
	task.wait(F.RespawnDelay)
	if ctx.Done or entry.Out or Combat.Get(rec.Model) ~= rec then
		return
	end
	unpark(rec)
	Arena.Halo(ctx, ctx.RespawnPoint)
	Combat.Respawn(rec, Arena.Facing(ctx, ctx.RespawnPoint + Vector3.new(0, 3 * (rec.Scale - 1), 0)))
end
Match.HandleKO = onKO

local function finish(ctx)
	ctx.Done = true
	ctx.Phase = "Over"
	local alive = aliveEntries(ctx)
	table.sort(alive, function(a, b)
		if a.Stocks ~= b.Stocks then
			return a.Stocks > b.Stocks
		end
		local da = a.Rec and a.Rec.Damage or 999
		local db = b.Rec and b.Rec.Damage or 999
		return da < db
	end)
	for i, entry in alive do
		entry.Place = i
	end
	for _, entry in ctx.Entries do
		if entry.Player and not entry.Left then
			award(ctx, entry)
		end
	end
	local winner = alive[1]
	if winner then
		Combat.NotifyCtx(ctx, { Type = "Winner", Name = winner.Name })
	end
	Match.Broadcast(ctx)
	task.delay(5, function()
		for _, entry in ctx.Entries do
			if entry.Player and entryOf[entry.Player] == entry then
				Match.SendHome(entry.Player)
			end
		end
		Arena.Release(ctx)
	end)
end

local function runMatch(slot, mode, players, botCount, holder)
	local ctx = Arena.Build(slot, Config.PvPArenas[rng:NextInteger(1, #Config.PvPArenas)])
	holder.Ctx = ctx
	ctx.Kind = "Match"
	ctx.Mode = mode
	ctx.HasBots = botCount > 0
	ctx.Ranked = mode == "Ranked" and botCount == 0
	ctx.Phase = "Countdown"
	ctx.Entries = {}
	ctx.OnKO = function(rec, position)
		onKO(ctx, rec, position)
	end

	for i, player in players do
		local entry = { Player = player, Name = player.DisplayName, Stocks = F.Stocks, MaxStocks = F.Stocks, KOs = 0, Ctx = ctx, SpawnIndex = i }
		table.insert(ctx.Entries, entry)
		entryOf[player] = entry
		Match.Place(entry, ctx, ctx.Spawns[i])
	end
	for b = 1, botCount do
		local def = Npc.RandomBot(rng)
		local entry = { Name = def.Name, Stocks = F.Stocks, MaxStocks = F.Stocks, KOs = 0, Ctx = ctx }
		local rec = Npc.Spawn(ctx, def, ctx.Spawns[#players + b])
		rec.Entry = entry
		entry.Rec = rec
		Combat.SetLocked(rec, true)
		table.insert(ctx.Entries, entry)
	end

	ctx.EndsAt = serverNow() + F.CountdownSeconds
	Match.Broadcast(ctx)
	task.wait(F.CountdownSeconds)

	ctx.Phase = "Fight"
	ctx.EndsAt = serverNow() + F.MatchSeconds
	for _, entry in ctx.Entries do
		if entry.Rec then
			Combat.SetLocked(entry.Rec, false)
		end
	end
	Match.Broadcast(ctx)

	while true do
		task.wait(0.2)
		local alive = aliveEntries(ctx)
		local humans = 0
		for _, entry in alive do
			if entry.Player and entry.Player.Parent and not entry.Left then
				humans += 1
			end
		end
		if #alive <= 1 or humans == 0 or serverNow() >= ctx.EndsAt then
			break
		end
	end
	finish(ctx)
end

local function start(mode, players, botCount)
	local slot = Arena.Acquire()
	if not slot then
		for _, player in players do
			-- tick() retries 4x a second; only remind every 10 seconds.
			if not busyToastAt[player] or os.clock() - busyToastAt[player] > 10 then
				busyToastAt[player] = os.clock()
				Profile.Toast(player, "All arenas are busy. Your match starts in a moment!")
			end
		end
		return false
	end
	for _, player in players do
		leaveQueue(player, true)
		Profile.SetActivity(player, "Match")
		Remotes.Notify:FireClient(player, { Type = "Queue", Mode = nil })
	end
	task.spawn(function()
		local holder = {}
		local ok, err = pcall(runMatch, slot, mode, players, botCount, holder)
		if ok then
			return
		end
		-- Never leave anyone stuck in a broken match: send everyone home and free the arena.
		warn("[Match] match error:", err)
		for _, player in players do
			if player.Parent and (entryOf[player] or Profile.GetActivity(player) == "Match") then
				Match.SendHome(player)
			end
		end
		if holder.Ctx then
			holder.Ctx.Done = true
			Arena.Release(holder.Ctx)
		else
			Arena.FreeSlot(slot)
		end
	end)
	return true
end

local function tick()
	-- Pads -> queues
	for _, player in Players:GetPlayers() do
		local character = player.Character
		local root = character and character:FindFirstChild("HumanoidRootPart")
		local mode = nil
		if root and not Profile.GetActivity(player) and DataService.Get(player) then
			for key, pad in pads do
				if onPad(root.Position, pad) then
					mode = key
				end
			end
		end
		if mode ~= queueOf[player] then
			leaveQueue(player)
			if mode then
				joinQueue(player, mode)
			end
		end
	end

	local t = os.clock()
	local ranked = queues.Ranked
	while #ranked >= 2 do
		if not start("Ranked", { ranked[1], ranked[2] }, 0) then
			break
		end
	end
	if #ranked == 1 and t - joinedAt[ranked[1]] >= F.BotFillSeconds then
		start("Ranked", { ranked[1] }, 1)
	end

	local ffa = queues.FFA
	if #ffa >= 2 then
		ffaReadyAt = ffaReadyAt or t
	else
		ffaReadyAt = nil
	end
	if #ffa >= F.FFAMax or (ffaReadyAt and t - ffaReadyAt >= F.FFAWaitSeconds) then
		local group = {}
		for i = 1, math.min(#ffa, F.FFAMax) do
			group[i] = ffa[i]
		end
		if start("FFA", group, 0) then
			ffaReadyAt = nil
		end
	elseif #ffa == 1 and t - joinedAt[ffa[1]] >= F.BotFillSeconds then
		start("FFA", { ffa[1] }, 2)
	end

	-- Pad signs
	for key, pad in pads do
		local q = queues[key]
		local text = MODES[key].Title .. "\n" .. #q .. "/" .. MODES[key].Max .. " waiting"
		if #q == 1 then
			local left = math.max(0, math.ceil(F.BotFillSeconds - (t - joinedAt[q[1]])))
			text ..= "\nBot joins in " .. left .. "s"
		elseif key == "FFA" and ffaReadyAt then
			text ..= "\nStarts in " .. math.max(0, math.ceil(F.FFAWaitSeconds - (t - ffaReadyAt))) .. "s"
		elseif #q == 0 then
			text ..= "\nStand here to join!"
		end
		pad.Label.Text = text
	end
end

-- Character respawned (fell out of the world, reset, etc.) while in a match.
function Match.OnCharacter(player)
	local entry = entryOf[player]
	if not entry then
		return false
	end
	local ctx = entry.Ctx
	if entry.Out or ctx.Done then
		Match.SendHome(player)
		return true
	end
	Match.Place(entry, ctx, ctx.RespawnPoint, F.RespawnInvuln)
	Match.Broadcast(ctx)
	return true
end

function Match.ClearPlayer(player)
	leaveQueue(player, true)
	busyToastAt[player] = nil
	local entry = entryOf[player]
	entryOf[player] = nil
	if entry then
		entry.Left = true
		entry.Rewarded = true -- leaving early gives no rewards
		if entry.Ctx.Kind == "Match" then
			eliminate(entry.Ctx, entry)
			if not entry.Ctx.Done then
				Match.Broadcast(entry.Ctx)
			end
		end
	end
end

function Match.Init(info)
	pads = info.Pads
	lobbySpawn = info.Spawn
	Remotes.Queue.OnServerEvent:Connect(function(player, mode)
		if Profile.GetActivity(player) then
			return
		end
		local character = player.Character
		if not character then
			return
		end
		if mode == "Ranked" or mode == "FFA" then
			local pad = pads[mode].Part
			character:PivotTo(CFrame.new(pad.Position + Vector3.new(rng:NextNumber(-3, 3), 4, rng:NextNumber(-3, 3))))
		elseif mode == nil and queueOf[player] then
			local pad = pads[queueOf[player]].Part
			character:PivotTo(CFrame.new(pad.Position + Vector3.new(0, 4, 16)))
		end
	end)
	task.spawn(function()
		while true do
			task.wait(0.25)
			local ok, err = pcall(tick)
			if not ok then
				warn("[Match] tick error:", err)
			end
		end
	end)
end

return Match
