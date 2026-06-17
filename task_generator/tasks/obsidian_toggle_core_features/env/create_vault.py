import os, json
vault = "/home/user/Documents/ToggleVault"
obs = os.path.join(vault, ".obsidian")
os.makedirs(obs, exist_ok=True)
with open(os.path.join(obs, "core-plugins.json"), "w") as f:
    json.dump({"graph": True, "tag-pane": True, "starred": True, "outgoing-link": False, "page-preview": False}, f, indent=2)
with open(os.path.join(obs, "app.json"), "w") as f:
    json.dump({"spellcheck": False, "showLineNumber": False}, f, indent=2)
