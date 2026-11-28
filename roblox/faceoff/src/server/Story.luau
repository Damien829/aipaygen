-- Story mode: The Scrapyard Saga. Dialogue, waves of Junk Bots, then a boss who drops a part.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Config = require(ReplicatedStorage.Shared.Config)
local Remotes = require(ReplicatedStorage.Shared.Remotes)
local Arena = require(script.Parent.Arena)
local Combat = require(script.Parent.Combat)
local DataService = require(script.Parent.DataService)
local Match = require(script.Parent.Match)
local Npc = require(script.Parent.Npc)
local Profile = require(script.Parent.Profile)

local F = Config.Fight

local Story = {}

local runs = {} -- [Player] = run

local function dialogue(run, lines)
	local player = run.Player
	local list = {}
	for _, line in lines do
		table.insert(list, { Speaker = line[1], Text = line[2] })
	end
	run.WaitingDialogue = true
	Remotes.Dialogue:FireClient(player, { Lines = list })
	local deadline = os.clock() + 10 + #lines * 8 -- never hang if the client never answers
	while run.WaitingDialogue and os.clock() < deadline and player.Parent and not run.Done do
		task.wait(0.1)
	end
	run.WaitingDialogue = false
end

local function setPhase(run, phase, banner)
	local ctx = run.Ctx
	ctx.Phase = phase
	ctx.Banner = banner
	for _, entry in ctx.Entries do
		if entry.Rec and not entry.Out then
			Combat.SetLocked(entry.Rec, phase ~= "Fight")
		end
	end
	Match.Broadcast(ctx)
end

local function enemiesLeft(ctx)
	local count = 0
	for _, entry in ctx.Entries do
		if not entry.Player and not entry.Out then
			count += 1
		end
	end
	return count
end

local function spawnEnemy(run, def, position)
	local ctx = run.Ctx
	local entry = { Name = def.Name, Stocks = def.Stocks or 1, MaxStocks = def.Stocks or 1, KOs = 0, Ctx = ctx, Team = "Junk", Boss = def.Boss }
	local rec = Npc.Spawn(ctx, def, position, "Junk")
	rec.Entry = entry
	entry.Rec = rec
	table.insert(ctx.Entries, entry)
	Combat.SetLocked(rec, ctx.Phase ~= "Fight")
	return entry
end

local function onKO(run, rec, position)
	local ctx = run.Ctx
	local entry = rec.Entry
	if not entry or entry.Out or run.Done then
		return
	end
	Match.Park(rec)
	entry.Stocks -= 1
	local b = ctx.Bounds
	local spot = Vector3.new(math.clamp(position.X, b.MinX, b.MaxX), math.clamp(position.Y, b.MinY, b.MaxY), ctx.PlaneZ)
	Combat.NotifyCtx(ctx, { Type = "KO", Position = spot, Name = entry.Name, Model = rec.Model, Left = entry.Stocks })
	if not entry.Player and rec.LastHitBy and rec.LastHitBy.Entry and rec.LastHitBy.Entry.Player then
		rec.LastHitBy.Entry.KOs += 1
	end
	if entry.Stocks <= 0 then
		entry.Out = true
		rec.Out = true
		if not entry.Player then
			task.delay(0.3, function()
				if rec.Model.Parent then
					rec.Model:Destroy()
				end
			end)
		end
		Match.Broadcast(ctx)
		return
	end
	Match.Broadcast(ctx)
	task.wait(F.RespawnDelay)
	if run.Done or entry.Out or Combat.Get(rec.Model) ~= rec then
		return
	end
	Arena.Halo(ctx, ctx.RespawnPoint)
	Combat.Respawn(rec, Arena.Facing(ctx, ctx.RespawnPoint + Vector3.new(0, 3 * (rec.Scale - 1), 0)))
end

local function revive(run)
	local entry = run.Entry
	entry.Out = false
	entry.Stocks = entry.MaxStocks
	local rec = Combat.ForPlayer(run.Player)
	if rec then
		rec.Out = false
		rec.Entry = entry
		entry.Rec = rec
		Arena.Halo(run.Ctx, run.Ctx.RespawnPoint)
		Combat.Respawn(rec, Arena.Facing(run.Ctx, run.Ctx.RespawnPoint))
	end
	Profile.Celebrate(run.Player, "SECOND WIND!", "Your 3 lives are back. Go get 'em!", "💨")
	Match.Broadcast(run.Ctx)
end

-- Out of lives: use a saved Second Wind, or offer one (only if the product is set up).
local function tryRevive(run)
	local player = run.Player
	local data = DataService.Get(player)
	if not data then
		return false
	end
	if data.Revives > 0 then
		data.Revives -= 1
		Profile.Push(player)
		revive(run)
		return true
	end
	if Config.Products.SecondWind.Id == 0 then
		return false
	end
	-- No countdown is shown: the player decides, and "No thanks" ends it right away.
	-- The time limit is only a quiet safety net in case the pop-up is ignored.
	run.ReviveDeclined = false
	Remotes.Notify:FireClient(player, { Type = "Revive" })
	local deadline = os.clock() + Config.ReviveWindow
	while os.clock() < deadline and player.Parent and not run.Done and not run.ReviveDeclined do
		task.wait(0.2)
		if data.Revives > 0 then
			data.Revives -= 1
			Profile.Push(player)
			Remotes.Notify:FireClient(player, { Type = "ReviveClose" })
			revive(run)
			return true
		end
	end
	Remotes.Notify:FireClient(player, { Type = "ReviveClose" })
	return false
end

-- Waits until every enemy is out ("win"), the player is out ("lose") or the player left ("left").
local function fight(run)
	while true do
		task.wait(0.2)
		if not run.Player.Parent or run.Done then
			return "left"
		end
		if run.Entry.Out and not tryRevive(run) then
			return "lose"
		end
		if enemiesLeft(run.Ctx) == 0 then
			return "win"
		end
	end
end

local function cleanup(run)
	run.Done = true
	if runs[run.Player] == run then
		runs[run.Player] = nil
	end
	if run.Player.Parent and Match.EntryOf(run.Player) == run.Entry then
		Match.SendHome(run.Player)
	end
	Arena.Release(run.Ctx)
end

local function runStory(player, index, slot, holder)
	local chapter = Config.Chapters[index]
	local ctx = Arena.Build(slot, chapter.Arena)
	holder.Ctx = ctx
	local summary = nil
	ctx.Kind = "Story"
	ctx.Chapter = index
	ctx.Phase = "Dialogue"
	ctx.Entries = {}
	local entry = { Player = player, Name = player.DisplayName, Stocks = F.Stocks, MaxStocks = F.Stocks, KOs = 0, Ctx = ctx, Team = "Hero" }
	table.insert(ctx.Entries, entry)
	local run = { Player = player, Ctx = ctx, Entry = entry, Chapter = index }
	runs[player] = run
	Match.Track(player, entry)
	ctx.OnKO = function(rec, position)
		onKO(run, rec, position)
	end
	Match.Place(entry, ctx, ctx.Spawns[1])
	setPhase(run, "Dialogue", "Chapter " .. index .. ": " .. chapter.Name)

	local ok, result = pcall(function()
		dialogue(run, chapter.Intro)
		for w, wave in chapter.Waves do
			if run.Done then
				return "left"
			end
			setPhase(run, "Fight", "Wave " .. w .. " of " .. #chapter.Waves)
			local spots = { 2, 4, 6 }
			for i, def in wave do
				spawnEnemy(run, def, ctx.Spawns[spots[(i - 1) % #spots + 1]])
			end
			Match.Broadcast(ctx)
			local outcome = fight(run)
			if outcome ~= "win" then
				return outcome
			end
		end
		setPhase(run, "Dialogue", "BOSS: " .. chapter.Boss)
		dialogue(run, chapter.BossIntro)
		if run.Done then
			return "left"
		end
		spawnEnemy(run, chapter.BossDef, ctx.Spawns[2])
		setPhase(run, "Fight", "BOSS: " .. chapter.Boss)
		local outcome = fight(run)
		if outcome ~= "win" then
			return outcome
		end
		-- Pay out now, so leaving during the ending dialogue never loses the clear.
		summary = Profile.StoryResult(player, index)
		setPhase(run, "Dialogue", "VICTORY!")
		dialogue(run, chapter.Outro)
		return "win"
	end)
	if not ok then
		warn("[Story] error:", result)
		result = "lose"
	end

	if result ~= "left" and player.Parent then
		ctx.Phase = "Over"
		Remotes.Notify:FireClient(player, {
			Type = "Results",
			Story = true,
			Won = result == "win",
			Chapter = index,
			ChapterName = chapter.Name,
			Coins = summary and summary.Coins or 0,
			XP = summary and summary.XP or 0,
			Part = summary and summary.Part,
			First = summary and summary.First,
		})
		Match.Broadcast(ctx)
		task.wait(4.5)
	end
	cleanup(run)
end

function Story.Start(player, index)
	local data = DataService.Get(player)
	if not data or type(index) ~= "number" or not Config.Chapters[index] then
		return false
	end
	index = math.floor(index)
	if index > data.StoryCleared + 1 then
		Profile.Toast(player, "Beat Chapter " .. data.StoryCleared + 1 .. " first!")
		return false
	end
	if Profile.GetActivity(player) or runs[player] then
		Profile.Toast(player, "Finish your current fight first.")
		return false
	end
	if not Combat.ForPlayer(player) then
		return false
	end
	local slot = Arena.Acquire()
	if not slot then
		Profile.Toast(player, "All arenas are busy. Try again in a moment!")
		return false
	end
	Profile.SetActivity(player, "Story")
	task.spawn(function()
		local holder = {}
		local ok, err = pcall(runStory, player, index, slot, holder)
		if ok then
			return
		end
		-- Never leave the player stuck: send them home and free the arena.
		warn("[Story] run error:", err)
		runs[player] = nil
		if player.Parent then
			Match.SendHome(player)
		end
		if holder.Ctx then
			Arena.Release(holder.Ctx)
		else
			Arena.FreeSlot(slot)
		end
	end)
	return true
end

function Story.ClearPlayer(player)
	local run = runs[player]
	if run then
		run.Done = true
	end
end

function Story.Init()
	Remotes.StartStory.OnServerInvoke = Story.Start
	Remotes.RequestState.OnServerEvent:Connect(function(player, what)
		local run = runs[player]
		if run and what == "DeclineRevive" then
			run.ReviveDeclined = true
		end
	end)
	Remotes.DialogueDone.OnServerEvent:Connect(function(player)
		local run = runs[player]
		if run then
			run.WaitingDialogue = false
		end
	end)
	Players.PlayerRemoving:Connect(Story.ClearPlayer)
end

return Story
