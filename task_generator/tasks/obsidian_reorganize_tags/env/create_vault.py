import os, json
vault = "/home/user/Documents/TagVault"
obs = os.path.join(vault, ".obsidian")
os.makedirs(obs, exist_ok=True)
with open(os.path.join(obs, "app.json"), "w") as f:
    json.dump({}, f)

notes = {
    "Meeting Notes.md": "# Meeting Notes\nDiscussed project timeline and deliverables.",
    "Project Plan.md": "# Project Plan\nPhase 1: Design\nPhase 2: Implementation\nPhase 3: Testing",
    "Reading List.md": "# Reading List\n- Clean Code\n- The Pragmatic Programmer\n- Refactoring",
    "Quick Ideas.md": "# Quick Ideas\n- Try using a graph database\n- Explore WebAssembly\n- Build a CLI tool",
    "Weekly Review.md": "# Weekly Review\nThis week was productive. Completed all sprint tasks.",
    "Contacts.md": "# Contacts\n- Alice: alice@example.com\n- Bob: bob@example.com",
}
for name, content in notes.items():
    with open(os.path.join(vault, name), "w") as f:
        f.write(content)
