-- {{TITLE}} server entry. The server is the authority: validate every RemoteEvent.
local Players = game:GetService("Players")
Players.PlayerAdded:Connect(function(player)
	print("{{TITLE}}: welcome", player.Name)
end)
