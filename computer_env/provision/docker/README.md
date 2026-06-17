# Docker Desktop Image

Build the phase-1 Linux desktop image from the repository root:

```bash
bash computer_env/provision/docker/build_image.sh
```

This image is intended for the `docker` environment backend in `computer_env/backends/docker/`.

The runtime mounts `/tmp` as `tmpfs` for desktop-session scratch data. It does
not mount `/home/user` as `tmpfs`, because that would hide credentials and
agent configuration baked into the image, such as `/home/user/.codex` and
`/home/user/.claude`.

Current Docker app coverage:

- `audacity`
- `blender`
- `chrome`
- `brave`
- `cloudcompare`
- `darktable`
- `drawio`
- `eclipse`
- `firefox`
- `freecad`
- `libreoffice_calc`
- `libreoffice_writer`
- `libreoffice_impress`
- `libreoffice_draw`
- `gedit`
- `galculator`
- `gimp`
- `github_desktop`
- `godot4`
- `inkscape`
- `kdenlive`
- `krita`
- `musescore3`
- `obs`
- `pcmanfm`
- `renderdoc`
- `shotcut`
- `thunderbird`
- `vlc`
- `vscode`
- `zoom`
- `obsidian`
- `zotero`

Notes:

- The image currently supports 33/33 apps from the evaluation suite.
- The image exposes noVNC on container port `6080`. The backend publishes it to a random localhost port.
- `linux/amd64` is the default target platform. On Apple Silicon hosts Docker Desktop will emulate it unless you build a native arm64 variant.
- The host only needs the Docker CLI; the Python backend uses the standard library rather than the Docker SDK.
