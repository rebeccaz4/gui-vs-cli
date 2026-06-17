import os, json
vault = "/home/user/Documents/ThemeVault"
obs = os.path.join(vault, ".obsidian")
os.makedirs(obs, exist_ok=True)
with open(os.path.join(obs, "appearance.json"), "w") as f:
    json.dump({"baseFontSize": 16, "theme": "obsidian", "accentColor": "#7C3AED"}, f, indent=2)
with open(os.path.join(obs, "app.json"), "w") as f:
    json.dump({}, f)
