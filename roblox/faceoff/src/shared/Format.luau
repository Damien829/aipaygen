local Format = {}

local SUFFIXES = { "", "K", "M", "B", "T", "Qa", "Qi", "Sx", "Sp", "Oc", "No", "Dc" }

function Format.Number(n)
	n = math.floor(n)
	if n < 1000 then
		return tostring(n)
	end
	local index = math.min(math.floor(math.log10(n) / 3), #SUFFIXES - 1)
	local text = string.format("%.2f", n / 10 ^ (index * 3))
	-- 999,999 rounds to "1000.00K"; move up a suffix instead.
	if tonumber(text) >= 1000 and index < #SUFFIXES - 1 then
		index += 1
		text = string.format("%.2f", n / 10 ^ (index * 3))
	end
	text = text:gsub("%.?0+$", "")
	return text .. SUFFIXES[index + 1]
end

function Format.Time(seconds)
	seconds = math.max(0, math.floor(seconds))
	return string.format("%d:%02d", seconds // 60, seconds % 60)
end

return Format
