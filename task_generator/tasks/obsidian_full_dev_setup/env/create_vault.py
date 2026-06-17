import os, json
vault = "/home/user/Documents/FullDevVault"
obs = os.path.join(vault, ".obsidian")
os.makedirs(obs, exist_ok=True)
with open(os.path.join(obs, "app.json"), "w") as f:
    json.dump({
        "vimMode": False,
        "showLineNumber": False,
        "showFrontmatter": False,
        "readableLineLength": True,
        "strictLineBreaks": False
    }, f, indent=2)
with open(os.path.join(obs, "appearance.json"), "w") as f:
    json.dump({
        "baseFontSize": 16,
        "theme": "moonstone"
    }, f, indent=2)
with open(os.path.join(obs, "hotkeys.json"), "w") as f:
    json.dump({}, f)
