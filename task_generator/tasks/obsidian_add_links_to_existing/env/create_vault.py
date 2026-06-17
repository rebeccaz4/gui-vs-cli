import os, json
vault = "/home/user/Documents/LinkVault"
obs = os.path.join(vault, ".obsidian")
os.makedirs(obs, exist_ok=True)
with open(os.path.join(obs, "app.json"), "w") as f:
    json.dump({}, f)

notes = {
    "Python.md": "# Python\nA versatile programming language used for web dev, data science, and automation.",
    "JavaScript.md": "# JavaScript\nThe language of the web. Used for frontend and backend development.",
    "React.md": "# React\nA JavaScript library for building user interfaces. Created by Facebook.",
    "TypeScript.md": "# TypeScript\nA typed superset of JavaScript that compiles to plain JavaScript.",
    "Git.md": "# Git\nA distributed version control system for tracking changes in code.",
}
for name, content in notes.items():
    with open(os.path.join(vault, name), "w") as f:
        f.write(content)
