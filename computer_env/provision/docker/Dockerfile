FROM ubuntu:22.04

ARG TARGETARCH
ARG ECLIPSE_RELEASE=2024-12
ARG BRAVE_VERSION=1.89.143
ARG BRAVE_KEYRING_VERSION=1.19
ARG VSCODE_VERSION=1.117.0-1776814346
ARG LIBREOFFICE_VERSION=1:7.3.7-0ubuntu0.22.04.10
ARG ZOOM_VERSION=7.0.0.1666

ENV ECLIPSE_TARBALL=eclipse-java-${ECLIPSE_RELEASE}-R-linux-gtk-x86_64.tar.gz
ENV ECLIPSE_ARCHIVE_URL=https://archive.eclipse.org/technology/epp/downloads/release/${ECLIPSE_RELEASE}/R/${ECLIPSE_TARBALL}
ENV FIREFOX_ARCHIVE_URL=https://download.mozilla.org/?product=firefox-esr-latest-ssl&os=linux64&lang=en-US
ENV BRAVE_KEYRING_DEB_URL=https://brave-browser-apt-release.s3.brave.com/pool/main/b/brave-keyring/brave-keyring_${BRAVE_KEYRING_VERSION}-1.deb
ENV BRAVE_DEB_URL=https://brave-browser-apt-release.s3.brave.com/pool/main/b/brave-browser/brave-browser_${BRAVE_VERSION}_amd64.deb
ENV VSCODE_DEB_URL=https://packages.microsoft.com/repos/code/pool/main/c/code/code_${VSCODE_VERSION}_amd64.deb
ENV ZOOM_DEB_URL=https://cdn.zoom.us/prod/${ZOOM_VERSION}/zoom_amd64.deb

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:0
ENV HOME=/home/user
ENV USER=user
ENV SHELL=/bin/bash
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV XDG_RUNTIME_DIR=/tmp/runtime-user

RUN test "${TARGETARCH}" = "amd64" || \
    (echo "This phase-1 desktop image currently supports only linux/amd64. Build with --platform linux/amd64." >&2 && exit 1)

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    wget && \
    rm -rf /var/lib/apt/lists/*

# Configure wget for better reliability with retries and timeouts
RUN echo "retry_connrefused = on" >> /etc/wgetrc && \
    echo "tries = 5" >> /etc/wgetrc && \
    echo "timeout = 30" >> /etc/wgetrc

RUN mkdir -p /etc/apt/keyrings && \
    curl -fsSLo /tmp/opera.key https://deb.opera.com/archive.key && \
    gpg --dearmor -o /usr/share/keyrings/opera.gpg /tmp/opera.key && \
    echo "deb [signed-by=/usr/share/keyrings/opera.gpg] https://deb.opera.com/opera-stable/ stable non-free" \
      > /etc/apt/sources.list.d/opera-stable.list && \
    curl -fsSLo /tmp/sublime.key https://download.sublimetext.com/sublimehq-pub.gpg && \
    gpg --dearmor -o /usr/share/keyrings/sublimehq.gpg /tmp/sublime.key && \
    echo "deb [signed-by=/usr/share/keyrings/sublimehq.gpg] https://download.sublimetext.com/ apt/stable/" \
      > /etc/apt/sources.list.d/sublime-text.list && \
    rm -f /tmp/opera.key /tmp/sublime.key

# Brave browser - skip if network fails
RUN curl -fsSLo /tmp/brave.key https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg && \
    gpg --dearmor -o /usr/share/keyrings/brave-browser.gpg /tmp/brave.key && \
    echo "deb [signed-by=/usr/share/keyrings/brave-browser.gpg] https://brave-browser-apt-release.s3.brave.com/ stable main" \
      > /etc/apt/sources.list.d/brave-browser-release.list && \
    rm -f /tmp/brave.key || echo "Warning: Brave repo setup failed, will skip Brave installation"

RUN apt-get update && apt-get install -y --no-install-recommends \
    audacity \
    blender \
    bzip2 \
    ca-certificates \
    cloudcompare \
    curl \
    darktable \
    default-jdk \
    dbus-x11 \
    ffmpeg \
    freecad \
    gimp \
    galculator \
    gedit \
    git \
    gnupg \
    kdenlive \
    inkscape \
    krita \
    libsecret-1-0 \
    gtk2-engines-pixbuf \
    libasound2 \
    libatk-bridge2.0-0 \
    libdbus-glib-1-2 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnss3 \
    libreoffice=${LIBREOFFICE_VERSION} \
    musescore3 \
    locales \
    novnc \
    obs-studio \
    opera-stable \
    pcmanfm \
    playerctl \
    procps \
    python3 \
    python3-dev \
    python3-pip \
    python3-setuptools \
    python3-tk \
    python3-venv \
    pulseaudio \
    pulseaudio-utils \
    scrot \
    shotcut \
    software-properties-common \
    sublime-text \
    sudo \
    tar \
    thunderbird \
    unzip \
    vlc \
    websockify \
    x11-utils \
    x11vnc \
    xclip \
    xauth \
    xdotool \
    xfce4 \
    xfce4-terminal \
    xfonts-base \
    xfonts-scalable \
    xz-utils \
    xvfb && \
    rm -rf /var/lib/apt/lists/*

RUN locale-gen en_US.UTF-8

RUN useradd -m -s /bin/bash user && \
    usermod -aG sudo user && \
    echo "user ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/user && \
    chmod 0440 /etc/sudoers.d/user && \
    mkdir -p /home/user/Downloads /tmp/runtime-user && \
    chown -R user:user /home/user /tmp/runtime-user

RUN pip3 install --no-cache-dir --default-timeout=1000 -i https://pypi.tuna.tsinghua.edu.cn/simple \
    marionette_driver \
    openpyxl \
    pillow \
    pyautogui \
    pyperclip \
    python-docx \
    python-pptx \
    python-xlib

RUN wget --timeout=300 --tries=3 --progress=bar:force -O /tmp/google-chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt-get update && \
    apt-get install -y /tmp/google-chrome.deb && \
    rm -f /tmp/google-chrome.deb && \
    rm -rf /var/lib/apt/lists/*

RUN wget --timeout=300 --tries=3 --progress=bar:force -O /tmp/code.deb "${VSCODE_DEB_URL}" && \
    apt-get update && \
    apt-get install -y /tmp/code.deb && \
    rm -f /tmp/code.deb && \
    rm -rf /var/lib/apt/lists/*

RUN wget --timeout=300 --tries=3 --progress=bar:force -O /tmp/obsidian.deb https://github.com/obsidianmd/obsidian-releases/releases/download/v1.7.7/obsidian_1.7.7_amd64.deb && \
    apt-get update && \
    apt-get install -y /tmp/obsidian.deb && \
    rm -f /tmp/obsidian.deb && \
    rm -rf /var/lib/apt/lists/*

RUN wget --timeout=300 --tries=3 --progress=bar:force -O /tmp/github-desktop.deb https://github.com/shiftkey/desktop/releases/download/release-3.4.12-linux1/GitHubDesktop-linux-amd64-3.4.12-linux1.deb && \
    apt-get update && \
    apt-get install -y /tmp/github-desktop.deb && \
    rm -f /tmp/github-desktop.deb && \
    rm -rf /var/lib/apt/lists/*

RUN wget --timeout=300 --tries=3 --progress=bar:force -O /tmp/drawio.deb https://github.com/jgraph/drawio-desktop/releases/download/v26.0.9/drawio-amd64-26.0.9.deb && \
    apt-get update && \
    apt-get install -y /tmp/drawio.deb && \
    rm -f /tmp/drawio.deb && \
    rm -rf /var/lib/apt/lists/*

RUN wget --timeout=300 --tries=3 --progress=bar:force -O /tmp/zoom.deb "${ZOOM_DEB_URL}" && \
    apt-get update && \
    apt-get install -y /tmp/zoom.deb && \
    rm -f /tmp/zoom.deb && \
    rm -rf /var/lib/apt/lists/*

# Match the E2B desktop template and bypass keyring prompts for Chromium/Electron
# apps that otherwise block the first interaction.
RUN for app in google-chrome brave-browser drawio github-desktop obsidian code; do \
      desktop_file=$(find /usr/share/applications -name "*${app}*.desktop" -print -quit 2>/dev/null); \
      if [ -n "$desktop_file" ] && ! grep -q -- '--password-store=basic' "$desktop_file"; then \
        sed -i 's|Exec=\\(.*\\)|Exec=\\1 --password-store=basic|' "$desktop_file"; \
      fi; \
    done

RUN wget --timeout=300 --tries=3 --progress=bar:force -O- https://download.zotero.org/client/release/7.0.15/Zotero-7.0.15_linux-x86_64.tar.bz2 \
      | tar -xj -C /opt && \
    ln -sf /opt/Zotero_linux-x86_64/zotero /usr/local/bin/zotero && \
    mkdir -p /usr/share/applications && \
    cp /opt/Zotero_linux-x86_64/zotero.desktop /usr/share/applications/zotero.desktop && \
    sed -i 's|Exec=.*|Exec=/opt/Zotero_linux-x86_64/zotero|g' /usr/share/applications/zotero.desktop

# Eclipse - temporarily disabled due to slow download
# RUN wget --timeout=300 --tries=3 --progress=bar:force -O /tmp/eclipse.tar.gz "${ECLIPSE_ARCHIVE_URL}" && \
#     tar -xzf /tmp/eclipse.tar.gz -C /opt/ && \
#     rm -f /tmp/eclipse.tar.gz && \
#     ln -sf /opt/eclipse/eclipse /usr/local/bin/eclipse && \
#     printf '%s\n' \
#       '[Desktop Entry]' \
#       'Name=Eclipse IDE' \
#       'Type=Application' \
#       'Exec=/opt/eclipse/eclipse' \
#       'Icon=/opt/eclipse/icon.xpm' \
#       'Categories=Development;IDE;' \
#       > /usr/share/applications/eclipse.desktop

# Firefox ESR - temporarily disabled due to slow download
# RUN wget --timeout=300 --tries=3 --progress=bar:force -O /tmp/firefox-esr.tar.xz "${FIREFOX_ARCHIVE_URL}" && \
#     tar -xJf /tmp/firefox-esr.tar.xz -C /opt/ && \
#     rm -f /tmp/firefox-esr.tar.xz && \
#     mv /opt/firefox /opt/firefox-esr && \
#     ln -sf /opt/firefox-esr/firefox /usr/local/bin/firefox-bin && \
#     printf '%s\n' \
#       '[Desktop Entry]' \
#       'Name=Firefox ESR' \
#       'Type=Application' \
#       'Exec=/opt/firefox-esr/firefox %u' \
#       'Icon=/opt/firefox-esr/browser/chrome/icons/default/default128.png' \
#       'Categories=Network;WebBrowser;' \
#       > /usr/share/applications/firefox-esr.desktop

RUN wget --timeout=300 --tries=3 --progress=bar:force -O /tmp/godot4.zip https://github.com/godotengine/godot/releases/download/4.3-stable/Godot_v4.3-stable_linux.x86_64.zip && \
    unzip -q /tmp/godot4.zip -d /tmp/godot4-extract && \
    mv /tmp/godot4-extract/Godot_v4.3-stable_linux.x86_64 /usr/local/bin/godot4 && \
    chmod +x /usr/local/bin/godot4 && \
    rm -rf /tmp/godot4.zip /tmp/godot4-extract && \
    printf '%s\n' \
      '[Desktop Entry]' \
      'Name=Godot Engine' \
      'Type=Application' \
      'Exec=/usr/local/bin/godot4' \
      'Icon=applications-games' \
      'Categories=Development;IDE;Game;' \
      > /usr/share/applications/godot4.desktop

RUN wget --timeout=300 --tries=3 --progress=bar:force -O /tmp/renderdoc.tar.gz https://renderdoc.org/stable/1.36/renderdoc_1.36.tar.gz && \
    tar -xzf /tmp/renderdoc.tar.gz -C /opt/ && \
    rm -f /tmp/renderdoc.tar.gz && \
    ln -sf /opt/renderdoc_1.36/bin/qrenderdoc /usr/local/bin/qrenderdoc && \
    ln -sf /opt/renderdoc_1.36/bin/renderdoccmd /usr/local/bin/renderdoccmd && \
    printf '%s\n' \
      '[Desktop Entry]' \
      'Name=RenderDoc' \
      'Type=Application' \
      'Exec=/usr/local/bin/qrenderdoc %f' \
      'Icon=applications-development' \
      'Terminal=false' \
      'Categories=Development;' \
      'MimeType=application/x-renderdoc-capture;' \
      > /usr/share/applications/renderdoc.desktop

RUN grep -q 'module-null-sink sink_name=virtual_speaker' /etc/pulse/default.pa || \
    printf '\nload-module module-null-sink sink_name=virtual_speaker sink_properties=device.description=Virtual_Speaker\nset-default-sink virtual_speaker\n' >> /etc/pulse/default.pa

COPY computer_env/provision/docker/entrypoint.sh /usr/local/bin/gui-synth-entrypoint.sh
COPY computer_env/provision/docker/healthcheck.sh /usr/local/bin/gui-synth-healthcheck.sh
COPY computer_env/provision/docker/build_image.sh /usr/local/bin/gui-synth-build-image.sh
COPY computer_env/provision/docker/install_app_wrappers.sh /usr/local/bin/gui-synth-install-app-wrappers.sh
COPY computer_env/provision/docker/install_app_wrappers.py /usr/local/bin/gui-synth-install-app-wrappers.py
COPY evaluation/apps/launcher_contract.py /usr/local/share/gui-synth/launcher_contract.py

RUN chmod +x \
    /usr/local/bin/gui-synth-entrypoint.sh \
    /usr/local/bin/gui-synth-healthcheck.sh \
    /usr/local/bin/gui-synth-build-image.sh \
    /usr/local/bin/gui-synth-install-app-wrappers.sh \
    /usr/local/bin/gui-synth-install-app-wrappers.py

RUN /usr/local/bin/gui-synth-install-app-wrappers.sh

USER user
WORKDIR /home/user

EXPOSE 6080
EXPOSE 5900

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=12 \
    CMD ["/usr/local/bin/gui-synth-healthcheck.sh"]

ENTRYPOINT ["/usr/local/bin/gui-synth-entrypoint.sh"]
