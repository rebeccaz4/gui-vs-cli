#!/usr/bin/env bash
set -euo pipefail

export DISPLAY="${DISPLAY:-:0}"
export HOME="${HOME:-/home/user}"
export USER="${USER:-user}"
export SHELL="${SHELL:-/bin/bash}"
export SCREEN_WIDTH="${SCREEN_WIDTH:-1920}"
export SCREEN_HEIGHT="${SCREEN_HEIGHT:-1080}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/runtime-user}"
export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"

mkdir -p "${XDG_RUNTIME_DIR}" "${HOME}/.config" "${HOME}/.cache" "${HOME}/.local/bin"
chmod 700 "${XDG_RUNTIME_DIR}"

seed_musescore_profile() {
  local musescore_config_dir="${HOME}/.config/MuseScore"
  local musescore_config_file="${musescore_config_dir}/MuseScore3.ini"
  local musescore_docs_dir="${HOME}/Documents/MuseScore3"

  if [[ -f "${musescore_config_file}" ]]; then
    return
  fi

  mkdir -p \
    "${musescore_config_dir}" \
    "${HOME}/.local/share/MuseScore/MuseScore3" \
    "${musescore_docs_dir}/Extensions" \
    "${musescore_docs_dir}/Images" \
    "${musescore_docs_dir}/Plugins" \
    "${musescore_docs_dir}/Scores" \
    "${musescore_docs_dir}/SoundFonts" \
    "${musescore_docs_dir}/Styles" \
    "${musescore_docs_dir}/Templates"

  cat >"${musescore_config_file}" <<EOF
[application]
paths\myExtensions=${musescore_docs_dir}/Extensions
paths\myImages=${musescore_docs_dir}/Images
paths\myPlugins=${musescore_docs_dir}/Plugins
paths\myScores=${musescore_docs_dir}/Scores
paths\mySoundfonts=${musescore_docs_dir}/SoundFonts
paths\myStyles=${musescore_docs_dir}/Styles
paths\myTemplates=${musescore_docs_dir}/Templates
playback\playRepeats=true
startup\firstStart=false
workspace=Basic

[ui]
application\language=system
application\startup\showTours=false
EOF
}

seed_xfce_panel_profile() {
  local panel_dir="${HOME}/.config/xfce4/xfconf/xfce-perchannel-xml"
  local panel_file="${panel_dir}/xfce4-panel.xml"
  local default_panel_file="/etc/xdg/xfce4/panel/default.xml"

  if [[ -f "${panel_file}" ]] || [[ ! -f "${default_panel_file}" ]]; then
    return
  fi

  mkdir -p "${panel_dir}"
  cp "${default_panel_file}" "${panel_file}"
}

patch_xfce_launchers() {
  python3 - <<'PY'
from pathlib import Path
import xml.etree.ElementTree as ET

replacements = {
    "xfce4-terminal-emulator.desktop": {
        "exec": "Exec=/home/user/.local/bin/gui-synth-terminal %U\n",
        "source": Path("/usr/share/applications/xfce4-terminal-emulator.desktop"),
        "panel_dir": Path("/home/user/.config/xfce4/panel/launcher-17"),
        "panel_file": "gui-synth-terminal.desktop",
    },
    "xfce4-file-manager.desktop": {
        "exec": "Exec=/home/user/.local/bin/gui-synth-file-manager %U\n",
        "source": Path("/usr/share/applications/xfce4-file-manager.desktop"),
        "panel_dir": Path("/home/user/.config/xfce4/panel/launcher-18"),
        "panel_file": "gui-synth-file-manager.desktop",
    },
    "xfce4-web-browser.desktop": {
        "exec": "Exec=/home/user/.local/bin/gui-synth-web-browser %U\n",
        "source": Path("/usr/share/applications/xfce4-web-browser.desktop"),
        "panel_dir": Path("/home/user/.config/xfce4/panel/launcher-19"),
        "panel_file": "gui-synth-web-browser.desktop",
    },
}

bin_dir = Path("/home/user/.local/bin")
bin_dir.mkdir(parents=True, exist_ok=True)
scripts = {
    "gui-synth-terminal": "#!/usr/bin/env bash\nexec /usr/bin/xfce4-terminal \"$@\"\n",
    "gui-synth-file-manager": "#!/usr/bin/env bash\nexec /usr/bin/thunar \"$@\"\n",
    "gui-synth-web-browser": (
        "#!/usr/bin/env bash\n"
        "exec /usr/bin/brave-browser-stable --no-sandbox --disable-gpu "
        "--password-store=basic --no-first-run --no-default-browser-check \"$@\"\n"
    ),
}
for name, content in scripts.items():
    path = bin_dir / name
    path.write_text(content)
    path.chmod(0o755)

apps_dir = Path("/home/user/.local/share/applications")
apps_dir.mkdir(parents=True, exist_ok=True)

def rewrite_desktop_file(source: Path, destination: Path, exec_line: str) -> None:
    if source.exists():
        lines = source.read_text().splitlines(keepends=True)
    else:
        lines = ["[Desktop Entry]\n", "Version=1.0\n", "Type=Application\n"]
    updated = []
    replaced = False
    for line in lines:
        if line.startswith("Exec="):
            updated.append(exec_line)
            replaced = True
        else:
            updated.append(line)
    if not replaced:
        updated.append(exec_line)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(updated))

for desktop_id, config in replacements.items():
    rewrite_desktop_file(config["source"], apps_dir / desktop_id, config["exec"])
    rewrite_desktop_file(config["source"], config["panel_dir"] / config["panel_file"], config["exec"])

panel_xml = Path("/home/user/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml")
if panel_xml.exists():
    tree = ET.parse(panel_xml)
    root = tree.getroot()
    overrides = {
        "plugin-17": "gui-synth-terminal.desktop",
        "plugin-18": "gui-synth-file-manager.desktop",
        "plugin-19": "gui-synth-web-browser.desktop",
    }
    for prop in root.iter("property"):
        plugin_name = prop.attrib.get("name")
        if plugin_name not in overrides:
            continue
        for child in prop.findall("property"):
            if child.attrib.get("name") != "items":
                continue
            for value in child.findall("value"):
                value.attrib["value"] = overrides[plugin_name]
    tree.write(panel_xml, encoding="UTF-8", xml_declaration=True)
PY
}

seed_musescore_profile
seed_xfce_panel_profile
patch_xfce_launchers

cleanup() {
  pkill -P $$ >/dev/null 2>&1 || true
  jobs -p | xargs -r kill >/dev/null 2>&1 || true
}
trap cleanup EXIT TERM INT

start_desktop_component() {
  local command="$1"
  local log_path="$2"

  bash -lc "export DISPLAY='${DISPLAY}'; export HOME='${HOME}'; export USER='${USER}'; export XDG_RUNTIME_DIR='${XDG_RUNTIME_DIR}'; export DBUS_SESSION_BUS_ADDRESS='${DBUS_SESSION_BUS_ADDRESS}'; ${command}" >"${log_path}" 2>&1 &
}

wait_for_process() {
  local pattern="$1"
  local label="$2"

  for _ in $(seq 1 40); do
    if pgrep -af "${pattern}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done

  echo "Failed to start ${label}" >&2
  return 1
}

dbus-daemon --session --address="${DBUS_SESSION_BUS_ADDRESS}" --fork

Xvfb "${DISPLAY}" -screen 0 "${SCREEN_WIDTH}x${SCREEN_HEIGHT}x24" -ac +extension RANDR >/tmp/xvfb.log 2>&1 &

until DISPLAY="${DISPLAY}" xdpyinfo >/dev/null 2>&1; do
  sleep 0.2
done

pulseaudio --start --exit-idle-time=-1 >/tmp/pulseaudio.log 2>&1 || true

# Avoid xfce4-session here: under Docker's default seccomp profile on this host,
# GLib's spawn path can fail with "Failed to close file descriptor for child
# process (Operation not permitted)" when launching core XFCE children. Start
# the desktop components directly so the root window is replaced by a usable UI.
start_desktop_component "xfwm4 --replace" /tmp/xfwm4.log
wait_for_process '(^|[[:space:]])xfwm4([[:space:]]|$)' "xfwm4"

start_desktop_component "xfsettingsd" /tmp/xfsettingsd.log
wait_for_process '(^|[[:space:]])xfsettingsd([[:space:]]|$)' "xfsettingsd"

start_desktop_component "xfce4-panel" /tmp/xfce4-panel.log
wait_for_process '(^|[[:space:]])xfce4-panel([[:space:]]|$)' "xfce4-panel"

start_desktop_component "xfdesktop" /tmp/xfdesktop.log
wait_for_process '(^|[[:space:]])xfdesktop([[:space:]]|$)' "xfdesktop"

start_desktop_component "Thunar --daemon" /tmp/thunar.log
x11vnc -display "${DISPLAY}" -forever -shared -nopw -rfbport 5900 >/tmp/x11vnc.log 2>&1 &
websockify --web=/usr/share/novnc/ 6080 localhost:5900 >/tmp/websockify.log 2>&1 &

# Remove container-internal timeout to avoid conflicts with docker exec timeout
# The docker exec timeout is sufficient for enforcing time limits

while true; do
  sleep 3600
done
