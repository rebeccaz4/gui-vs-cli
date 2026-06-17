import os, json
vault = "/home/user/Documents/EditorVault"
obs = os.path.join(vault, ".obsidian")
os.makedirs(obs, exist_ok=True)
with open(os.path.join(obs, "app.json"), "w") as f:
    json.dump({"spellcheck": False, "strictLineBreaks": False, "readableLineLength": True, "foldHeading": False, "foldIndent": False, "showLineNumber": False}, f, indent=2)
