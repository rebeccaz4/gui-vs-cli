"""
Builds a single desktop sandbox template with ALL Class A apps pre-installed.
Usage: python computer_env/provision/e2b/build_all_apps_template.py
"""
import sys
from pathlib import Path

from dotenv import load_dotenv
from e2b import Template, default_build_logger
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.apps.launcher_contract import build_wrapper_install_commands

ECLIPSE_RELEASE = "2024-12"
ECLIPSE_TARBALL = f"eclipse-java-{ECLIPSE_RELEASE}-R-linux-gtk-x86_64.tar.gz"
ECLIPSE_ARCHIVE_URL = (
    "https://archive.eclipse.org/technology/epp/downloads/release/"
    f"{ECLIPSE_RELEASE}/R/{ECLIPSE_TARBALL}"
)
BRAVE_VERSION = "1.89.143"
VSCODE_VERSION = "1.117.0-1776814346"
LIBREOFFICE_VERSION = "1:7.3.7-0ubuntu0.22.04.10"
ZOOM_VERSION = "7.0.0.1666"
BRAVE_DEB_URL = (
    "https://brave-browser-apt-release.s3.brave.com/pool/main/b/brave-browser/"
    f"brave-browser_{BRAVE_VERSION}_amd64.deb"
)
BRAVE_KEYRING_VERSION = "1.19"
BRAVE_KEYRING_DEB_URL = (
    "https://brave-browser-apt-release.s3.brave.com/pool/main/b/brave-keyring/"
    f"brave-keyring_{BRAVE_KEYRING_VERSION}-1.deb"
)
VSCODE_DEB_URL = (
    "https://packages.microsoft.com/repos/code/pool/main/c/code/"
    f"code_{VSCODE_VERSION}_amd64.deb"
)
ZOOM_DEB_URL = f"https://cdn.zoom.us/prod/{ZOOM_VERSION}/zoom_amd64.deb"

load_dotenv()

template = (
    Template()
    .from_template("desktop")
    .set_user("root")

    # 1. Add all third-party repos + GPG keys, then single apt-get update
    .run_cmd([
        # Opera
        "curl -fsSL https://deb.opera.com/archive.key "
        "| gpg --dearmor > /usr/share/keyrings/opera.gpg",
        'echo "deb [signed-by=/usr/share/keyrings/opera.gpg] '
        'https://deb.opera.com/opera-stable/ stable non-free" '
        "> /etc/apt/sources.list.d/opera-stable.list",
        # Sublime Text
        "wget -qO - https://download.sublimetext.com/sublimehq-pub.gpg "
        "| gpg --dearmor > /usr/share/keyrings/sublimehq.gpg",
        'echo "deb [signed-by=/usr/share/keyrings/sublimehq.gpg] '
        'https://download.sublimetext.com/ apt/stable/" '
        "> /etc/apt/sources.list.d/sublime-text.list",
        # OBS Studio PPA
        "add-apt-repository -y ppa:obsproject/obs-studio",
        # Single apt-get update for all repos
        "apt-get update",
    ])

    # 2. Install all apt packages in one pass
    .apt_install([
        f"libreoffice={LIBREOFFICE_VERSION}",
        "opera-stable",
        "thunderbird",
        "sublime-text",
        "blender",
        "obs-studio",
        "vlc",
        "default-jdk",  # needed for Eclipse
        # Vision-heavy / creative apps
        "gimp",
        "inkscape",
        "krita",
        "kdenlive",
        "darktable",
        # Batch 1 additions
        "audacity",
        "musescore3",
        "shotcut",
        "freecad",
        "cloudcompare",
        # NOTE: Ubuntu 22.04's renderdoc 1.18 segfaults inside librenderdoc.so's
        # library constructor in containers. We install the official 1.36 tarball
        # below in step 3e instead.
        # Audio stack — required by audacity, shotcut, kdenlive, obs, zoom, etc.
        # Without a virtual sink the e2b container has no PortAudio device and
        # audacity asserts in getPlayDevIndex().
        "pulseaudio",
        "pulseaudio-utils",
        # Utilities needed later in the build
        "unzip",
    ])

    # 2a-musescore. Pre-seed MuseScore3 prefs so the first-run wizard, Start Center,
    # Tour, and splash do not appear. Discovered via _explore_musescore.py probing.
    .run_cmd([
        "mkdir -p /home/user/.config/MuseScore /etc/skel/.config/MuseScore",
        "cat > /home/user/.config/MuseScore/MuseScore3.ini << 'INI'\n"
        "[application]\n"
        "startup\\firstStart=false\n"
        "[ui]\n"
        "application\\startup\\showStartCenter=false\n"
        "application\\startup\\showTours=false\n"
        "application\\startup\\showSplashScreen=false\n"
        "application\\startup\\showNavigator=false\n"
        "application\\startup\\showPlayPanel=false\n"
        "INI",
        "cp /home/user/.config/MuseScore/MuseScore3.ini /etc/skel/.config/MuseScore/MuseScore3.ini",
        "chown -R user:user /home/user/.config/MuseScore",
    ])

    # 2a. PulseAudio: load a null sink so PortAudio sees a usable output device,
    # and ensure the daemon autostarts in the user's desktop session.
    .run_cmd([
        # Append null sink + default to system pulse config (read on every start)
        "grep -q 'module-null-sink sink_name=virtual_speaker' /etc/pulse/default.pa "
        "|| printf '\\nload-module module-null-sink sink_name=virtual_speaker "
        "sink_properties=device.description=Virtual_Speaker\\n"
        "set-default-sink virtual_speaker\\n' >> /etc/pulse/default.pa",
        # Force XDG autostart entry (apt-installed one is sometimes hidden)
        "mkdir -p /etc/xdg/autostart",
        "cat > /etc/xdg/autostart/pulseaudio.desktop << 'DESKTOP'\n"
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=PulseAudio Sound System\n"
        "Exec=pulseaudio --start --exit-idle-time=-1\n"
        "NoDisplay=true\n"
        "X-GNOME-Autostart-enabled=true\n"
        "DESKTOP",
        # Pre-create per-user pulse config dir
        "mkdir -p /home/user/.config/pulse",
        "chown -R user:user /home/user/.config",
    ])

    # 2b. Zotero tarball (.tar.xz)
    .run_cmd([
        "apt-get install -y xz-utils",
        "wget -q -O /tmp/zotero.tar.bz2 "
        "'https://download.zotero.org/client/release/7.0.15/Zotero-7.0.15_linux-x86_64.tar.bz2'",
        "mkdir -p /opt/zotero",
        "tar -xjf /tmp/zotero.tar.bz2 -C /opt/zotero --strip-components=1",
        "rm /tmp/zotero.tar.bz2",
        "bash /opt/zotero/set_launcher_icon || true",
        "ln -sf /opt/zotero/zotero /usr/local/bin/zotero",
        "cat > /usr/share/applications/zotero.desktop << 'DESKTOP'\n"
        "[Desktop Entry]\n"
        "Name=Zotero\n"
        "Type=Application\n"
        "Exec=/opt/zotero/zotero\n"
        "Icon=/opt/zotero/chrome/icons/default/default48.png\n"
        "Categories=Office;Education;\n"
        "DESKTOP",
    ])

    # 3. Download and install .deb packages
    .run_cmd([
        # Brave keyring + browser
        f"wget -q -O /tmp/brave-keyring.deb {BRAVE_KEYRING_DEB_URL}",
        "apt-get install -y /tmp/brave-keyring.deb",
        "rm /tmp/brave-keyring.deb",
        # Brave
        f"wget -q -O /tmp/brave-browser.deb {BRAVE_DEB_URL}",
        "apt-get install -y /tmp/brave-browser.deb",
        "rm /tmp/brave-browser.deb",
        # VS Code
        f"wget -q -O /tmp/code.deb {VSCODE_DEB_URL}",
        "apt-get install -y /tmp/code.deb",
        "rm /tmp/code.deb",
        # Obsidian
        "wget -q -O /tmp/obsidian.deb "
        "https://github.com/obsidianmd/obsidian-releases/releases/download/v1.7.7/obsidian_1.7.7_amd64.deb",
        "apt-get install -y /tmp/obsidian.deb",
        "rm /tmp/obsidian.deb",
        # GitHub Desktop
        "wget -q -O /tmp/github-desktop.deb "
        "'https://github.com/shiftkey/desktop/releases/download/release-3.4.12-linux1/GitHubDesktop-linux-amd64-3.4.12-linux1.deb'",
        "apt-get install -y /tmp/github-desktop.deb",
        "rm /tmp/github-desktop.deb",
        # draw.io Desktop
        "wget -q -O /tmp/drawio.deb "
        "https://github.com/jgraph/drawio-desktop/releases/download/v26.0.9/drawio-amd64-26.0.9.deb",
        "apt-get install -y /tmp/drawio.deb",
        "rm /tmp/drawio.deb",
        # Zoom
        f"wget -q -O /tmp/zoom.deb {ZOOM_DEB_URL}",
        "apt-get install -y /tmp/zoom.deb",
        "rm /tmp/zoom.deb",
    ])

    # 3b. Godot 4 (standalone binary)
    .run_cmd([
        "wget -q -O /tmp/godot.zip "
        "https://github.com/godotengine/godot/releases/download/4.3-stable/Godot_v4.3-stable_linux.x86_64.zip",
        "unzip -q /tmp/godot.zip -d /tmp/godot-extract",
        "mv /tmp/godot-extract/Godot_v4.3-stable_linux.x86_64 /usr/local/bin/godot4",
        "chmod +x /usr/local/bin/godot4",
        "rm -rf /tmp/godot.zip /tmp/godot-extract",
        "cat > /usr/share/applications/godot4.desktop << 'DESKTOP'\n"
        "[Desktop Entry]\n"
        "Name=Godot Engine\n"
        "Type=Application\n"
        "Exec=/usr/local/bin/godot4\n"
        "Icon=applications-games\n"
        "Categories=Development;IDE;Game;\n"
        "DESKTOP",
    ])

    # 3d. RenderDoc — official 1.36 tarball.
    # The Ubuntu 22.04 apt package (1.18) segfaults in librenderdoc.so's library
    # constructor before main() runs, regardless of GL/Vulkan env vars.
    .run_cmd([
        "wget -q -O /tmp/renderdoc.tar.gz "
        "https://renderdoc.org/stable/1.36/renderdoc_1.36.tar.gz",
        "tar -xzf /tmp/renderdoc.tar.gz -C /opt",
        "rm /tmp/renderdoc.tar.gz",
        "ln -sf /opt/renderdoc_1.36/bin/qrenderdoc /usr/local/bin/qrenderdoc",
        "ln -sf /opt/renderdoc_1.36/bin/renderdoccmd /usr/local/bin/renderdoccmd",
        "printf '%s\\n' '[Desktop Entry]' 'Name=RenderDoc' 'Type=Application' "
        "'Exec=/usr/local/bin/qrenderdoc %f' 'Icon=applications-development' "
        "'Terminal=false' 'Categories=Development;' "
        "'MimeType=application/x-renderdoc-capture;' "
        "> /usr/share/applications/renderdoc.desktop",
    ])

    # 4. Tarball installs (Eclipse)
    # Use the archived release tarball directly instead of eclipse.org's
    # download.php mirror redirect endpoint, which is brittle in unattended
    # builds and started returning server errors for this pinned release.
    .run_cmd([
        f"wget -q -O /tmp/eclipse.tar.gz '{ECLIPSE_ARCHIVE_URL}'",
        "tar -xzf /tmp/eclipse.tar.gz -C /opt/",
        "rm /tmp/eclipse.tar.gz",
        "ln -sf /opt/eclipse/eclipse /usr/local/bin/eclipse",
        # Eclipse .desktop file
        'cat > /usr/share/applications/eclipse.desktop << \'DESKTOP\'\n'
        '[Desktop Entry]\n'
        'Name=Eclipse IDE\n'
        'Type=Application\n'
        'Exec=/opt/eclipse/eclipse\n'
        'Icon=/opt/eclipse/icon.xpm\n'
        'Categories=Development;IDE;\n'
        'DESKTOP',
    ])

    # 5. Install Python dependencies for agent + verifiers
    .apt_install([
        "python3-tk", "python3-dev",                    # pyautogui
        "gir1.2-atspi-2.0", "at-spi2-core", "xdotool", # galculator (AT-SPI)
    ])
    .run_cmd([
        "pip install pyautogui pyperclip python-xlib "   # agent interaction
        "websocket-client "                              # browsers (CDP)
        "marionette_driver "                             # firefox
        "Pillow "                                        # gimp, darktable, krita
        "pyyaml",                                        # obsidian
    ])

    # 6. Disable GNOME Keyring prompt for Electron apps (draw.io, VS Code,
    #    GitHub Desktop, Obsidian) by using --password-store=basic
    .run_cmd([
        "apt-get install -y -qq gnome-keyring libsecret-1-0 dbus-x11",
        # Tell Electron apps to use basic (plaintext) password storage
        # instead of gnome-keyring, which avoids the keyring prompt entirely
        "mkdir -p /home/user/.config",
        "echo 'export ELECTRON_OZONE_PLATFORM_HINT=auto' >> /home/user/.profile",
        # Create wrapper scripts that pass --password-store=basic
        "for app in drawio github-desktop obsidian code; do "
        "  desktop_file=$(find /usr/share/applications -name \"*${app}*\" -print -quit 2>/dev/null); "
        "  if [ -n \"$desktop_file\" ]; then "
        "    sed -i 's|Exec=\\(.*\\)|Exec=\\1 --password-store=basic|' \"$desktop_file\"; "
        "  fi; "
        "done",
        "chown -R user:user /home/user/.config",
    ])

    .run_cmd(build_wrapper_install_commands())

    .set_user("user")
    .set_workdir("/home/user")
)

Template.build(
    template,
    alias="desktop-all-apps",
    cpu_count=2,
    memory_mb=2048,
    on_build_logs=default_build_logger(),
)

print("Template 'desktop-all-apps' built successfully.")
