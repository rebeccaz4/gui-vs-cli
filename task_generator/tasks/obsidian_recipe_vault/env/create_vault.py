import os, json
vault = "/home/user/Documents/RecipeVault"
obs = os.path.join(vault, ".obsidian")
os.makedirs(obs, exist_ok=True)
with open(os.path.join(obs, "app.json"), "w") as f:
    json.dump({}, f)
