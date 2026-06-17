import os, json
vault = "/home/user/Documents/PluginVault"
obs = os.path.join(vault, ".obsidian")
os.makedirs(obs, exist_ok=True)
with open(os.path.join(obs, "core-plugins.json"), "w") as f:
    json.dump({"graph": False, "tag-pane": False, "daily-notes": False, "templates": False, "outline": False, "word-count": False, "backlinks": False}, f, indent=2)
with open(os.path.join(obs, "app.json"), "w") as f:
    json.dump({}, f)
