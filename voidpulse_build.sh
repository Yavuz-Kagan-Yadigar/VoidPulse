#!/usr/bin/env bash
# =============================================================================
#  VoidPulse — Universal Package Builder v8
#  Supported formats: flatpak · deb · deb-multiarch · rpm · apk · appimage · appimage-multiarch
#
#  Example output:
#          org.voidpulse.VoidPulse.flatpak
#          voidpulse_1.0.0_amd64.deb
#          voidpulse_1.0.0_arm64.deb       ┐
#          voidpulse_1.0.0_armhf.deb       │ deb-multiarch
#          voidpulse_1.0.0_armel.deb       │
#          voidpulse_1.0.0_riscv64.deb     │
#          voidpulse_1.0.0_loong64.deb     ┘
#          voidpulse-1.0.0-1.noarch.rpm    (ARM auto-detected; pick a target with --target)
#          voidpulse-1.0.0-r0.apk          (Alpine Linux only)
#          VoidPulse-1.0.0-x86_64.AppImage
#          VoidPulse-1.0.0-aarch64.AppImage ┐
#          VoidPulse-1.0.0-armhf.AppImage   │ appimage-multiarch
#          VoidPulse-1.0.0-i686.AppImage    ┘
#
#  Usage : ./build-packages.sh [flatpak|deb|deb-multiarch|rpm|apk|appimage|appimage-multiarch|all]
#          With no argument, an interactive menu is shown.
#
#  Environment variables (overrides):
#    DEB_ARCH_TARGETS="arm64,armhf"          → deb-multiarch target architectures
#    RPM_TARGET_ARCH=aarch64                  → rpm target architecture
#    APPIMAGE_TARGET_ARCH=aarch64             → appimage single target architecture
#    APPIMAGE_ARCH_TARGETS="aarch64,armhf"   → appimage-multiarch targets
#    GPG_KEY_ID=<key-id>                      → sign with this key instead of
#                                               the first secret key found
#
#  openSUSE: the rpm target uses openSUSE package names automatically.
#  Alpine  : the apk target is skipped automatically on non-Alpine systems.
# =============================================================================
set -euo pipefail
IFS=$'\n\t'

# With set -e active, catch and report unexpected exits
trap 'echo -e "\033[0;31m[✗] ERROR: Script failed on line ${LINENO} (exit code: $?)\033[0m" >&2' ERR

# flatpak-builder --user must not run as root
[[ "$(id -u)" == "0" ]] && { echo -e "\033[0;31m[✗] ERROR: Do not run this script as root!\033[0m" >&2; exit 1; }

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
log()  { echo -e "${GREEN}[+]${NC} $*"; }
info() { echo -e "${CYAN}[i]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
die()  { echo -e "${RED}[✗] ERROR:${NC} $*" >&2; exit 1; }
sep()  { echo -e "${BOLD}────────────────────────────────────────────${NC}"; }

# ── Constants ─────────────────────────────────────────────────────────────────
APP_ID="org.voidpulse.VoidPulse"
APP_NAME="voidpulse"
APP_RELEASE="1"
APP_DESC="Touch- and OLED-friendly advanced music player"
APP_LICENSE="GPL-3.0-or-later"
APP_URL="https://github.com/Yavuz-Kagan-Yadigar/VoidPulse"
APP_MAINTAINER="Yavuz"

# ── Version prompt ────────────────────────────────────────────────────────────
sep
echo -e "${BOLD}  VoidPulse — Universal Package Builder v8${NC}"
sep
while true; do
    read -rp "  Enter version number (e.g. 1.2.0): " APP_VERSION
    [[ "${APP_VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] && break
    warn "Invalid format. Please use X.Y.Z (e.g. 1.2.0)."
done
info "Version: ${APP_VERSION} ✓"
sep

RUNTIME_NAME="org.gnome.Platform"
RUNTIME_VER="49"
SDK_NAME="org.gnome.Sdk"

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${SOURCE_DIR}/${APP_ID}-build"
REPO_DIR="${SOURCE_DIR}/${APP_ID}-repo"
BUNDLE="${SOURCE_DIR}/${APP_ID}.flatpak"
MANIFEST="${SOURCE_DIR}/${APP_ID}.yml"

FONT_URL="https://notofonts.github.io/music/fonts/NotoMusic/hinted/ttf/NotoMusic-Regular.ttf"
FONT_FILE="${SOURCE_DIR}/NotoMusic-Regular.ttf"

# ── Helper: check source files ───────────────────────────────────────────────
check_sources() {
    log "Checking source files..."
    for f in voidpulse.py "${APP_ID}.desktop" "${APP_ID}.svg"; do
        [[ -f "${SOURCE_DIR}/${f}" ]] || \
            die "Missing file: ${f}\n   Run the script from the project directory."
    done
    info "All source files present ✓"
}

# ── Helper: download the NotoMusic font ──────────────────────────────────────
download_font() {
    command -v curl &>/dev/null || die "curl not found. Please install curl."
    log "Downloading NotoMusic font..."
    if [[ ! -f "${FONT_FILE}" ]]; then
        curl -L --fail -o "${FONT_FILE}" "${FONT_URL}" || \
            die "Could not download NotoMusic font: ${FONT_URL}"
        info "Font saved: ${FONT_FILE}"
    else
        info "Font already present: ${FONT_FILE} ✓"
    fi
}

# ── Helper: fix ownership ─────────────────────────────────────────────────────
fix_ownership() {
    for _f in appdata.xml voidpulse-launcher "${APP_ID}.yml" \
              "${APP_ID}-build" "${APP_ID}-repo" "${APP_ID}.flatpak" \
              ".flatpak-builder" "NotoMusic-Regular.ttf"; do
        [[ -e "${SOURCE_DIR}/${_f}" ]] && \
            sudo chown -R "$(id -u):$(id -g)" "${SOURCE_DIR}/${_f}" 2>/dev/null || true
    done
}


# ── Helper: GPG key check and signing ────────────────────────────────────────
# GPG_KEY_ID: if empty, setup_gpg falls back to the first secret key on the
# system; if there is none either, signing is skipped with a warning.
# The :- default is what lets the environment win — a bare GPG_KEY_ID=""
# here would wipe the value the caller passed in before setup_gpg ever ran.
GPG_KEY_ID="${GPG_KEY_ID:-}"

setup_gpg() {
    # Take the key ID from the environment variable or ~/.rpmmacros
    if [[ -z "${GPG_KEY_ID}" ]]; then
        # Automatically pick the first secret key on the system
        GPG_KEY_ID=$(gpg --list-secret-keys --with-colons 2>/dev/null             | awk -F: '/^sec/{print $5; exit}') || true
    fi

    if [[ -z "${GPG_KEY_ID}" ]]; then
        warn "No GPG secret key found — signing will be skipped."
        warn "To create a key: gpg --full-generate-key"
        warn "Then re-run with the GPG_KEY_ID=<key-id> variable."
        GPG_KEY_ID=""
        return 0
    fi

    info "GPG signing key: ${GPG_KEY_ID} ✓"

    # ~/.rpmmacros is required for RPM signing
    local RPMM="${HOME}/.rpmmacros"
    if ! grep -q "%_gpg_name" "${RPMM}" 2>/dev/null; then
        echo "%_gpg_name ${GPG_KEY_ID}" >> "${RPMM}"
        info "~/.rpmmacros updated: %_gpg_name ${GPG_KEY_ID}"
    fi
}

sign_rpm() {
    local rpm_file="$1"
    [[ -z "${GPG_KEY_ID}" ]] && { warn "No GPG key — RPM not signed."; return 0; }
    command -v rpm &>/dev/null || { warn "rpm not found — signing skipped."; return 0; }
    log "Signing RPM: $(basename "${rpm_file}")"
    rpm --addsign "${rpm_file}" || warn "RPM signing failed — package is unsigned."
}

sign_deb() {
    local deb_file="$1"
    [[ -z "${GPG_KEY_ID}" ]] && { warn "No GPG key — DEB not signed."; return 0; }
    if command -v dpkg-sig &>/dev/null; then
        log "Signing DEB (dpkg-sig): $(basename "${deb_file}")"
        dpkg-sig --sign builder -k "${GPG_KEY_ID}" "${deb_file}" ||             warn "DEB signing failed — package is unsigned."
    elif command -v debsigs &>/dev/null; then
        log "Signing DEB (debsigs): $(basename "${deb_file}")"
        debsigs --sign=origin -k "${GPG_KEY_ID}" "${deb_file}" ||             warn "DEB signing failed — package is unsigned."
    else
        warn "dpkg-sig/debsigs not found — DEB not signed."
        warn "openSUSE: sudo zypper install dpkg-sig"
        warn "Debian  : sudo apt install dpkg-sig"
    fi
}

sign_appimage() {
    local ai_file="$1"
    [[ -z "${GPG_KEY_ID}" ]] && { warn "No GPG key — AppImage not signed." >&2; return 0; }
    log "Signing AppImage: $(basename "${ai_file}")" >&2
    gpg --batch --yes --detach-sign --armor         -u "${GPG_KEY_ID}" "${ai_file}" ||         warn "AppImage signing failed." >&2
    [[ -f "${ai_file}.asc" ]] && info "Signature file: ${ai_file}.asc" >&2
}

sign_flatpak_repo() {
    local repo_dir="$1"
    [[ -z "${GPG_KEY_ID}" ]] && { warn "No GPG key — Flatpak repo not signed."; return 0; }
    command -v flatpak &>/dev/null || return 0
    log "Signing Flatpak repo..."
    flatpak build-sign "${repo_dir}" --gpg-sign="${GPG_KEY_ID}" ||         warn "Flatpak repo signing failed."
    flatpak build-update-repo "${repo_dir}" --gpg-sign="${GPG_KEY_ID}" ||         warn "Flatpak repo update failed."
}

# =============================================================================
#  FLATPAK
# =============================================================================
build_flatpak() {
    sep
    echo -e "${BOLD}  VoidPulse → Flatpak Builder v8${NC}"
    sep

    check_sources

    log "Checking system tools..."
    command -v flatpak-builder &>/dev/null || \
        die "flatpak-builder not found. Install it with your package manager."

    fix_ownership

    log "Cleaning previous build artifacts..."
    for _item in "${BUILD_DIR}" "${REPO_DIR}" "${BUNDLE}" \
                 "${SOURCE_DIR}/appdata.xml" "${SOURCE_DIR}/voidpulse-launcher" \
                 "${MANIFEST}" "${SOURCE_DIR}/.flatpak-builder" \
                 "${FONT_FILE}"; do
        if [[ -e "${_item}" ]]; then
            rm -rf "${_item}"
            info "Deleted: ${_item}"
        fi
    done

    log "Adding Flathub remote..."
    flatpak remote-add --user --if-not-exists flathub \
        https://flathub.org/repo/flathub.flatpakrepo 2>/dev/null || true

    for pkg in "${RUNTIME_NAME}//${RUNTIME_VER}" "${SDK_NAME}//${RUNTIME_VER}"; do
        if ! flatpak info --user "${pkg}" &>/dev/null && \
           ! flatpak info        "${pkg}" &>/dev/null; then
            log "Installing: ${pkg}"
            flatpak install -y --user flathub "${pkg}"
        else
            info "Already installed: ${pkg} ✓"
        fi
    done

    download_font

    log "Generating AppStream metainfo..."
    cat > "${SOURCE_DIR}/appdata.xml" << APPDATA
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>org.voidpulse.VoidPulse</id>
  <metadata_license>CC0-1.0</metadata_license>
  <project_license>GPL-3.0-or-later</project_license>
  <name>VoidPulse</name>
  <summary>Touch and OLED friendly advanced music player</summary>
  <description>
    <p>Touch and OLED friendly advanced music player</p>
  </description>
  <launchable type="desktop-id">org.voidpulse.VoidPulse.desktop</launchable>
  <releases>
    <release version="${APP_VERSION}" date="$(date +%Y-%m-%d)"/>
  </releases>
  <url type="homepage">${APP_URL}</url>
  <developer_name>${APP_MAINTAINER}</developer_name>
  <content_rating type="oars-1.1"/>
</component>
APPDATA

    log "Generating launcher wrapper..."
    cat > "${SOURCE_DIR}/voidpulse-launcher" << 'LAUNCHER'
#!/bin/bash
exec python3 /app/lib/voidpulse/voidpulse.py "$@"
LAUNCHER
    chmod +x "${SOURCE_DIR}/voidpulse-launcher"

    log "Writing manifest: ${MANIFEST}"
    # voidpulse.py is no longer a single file — after the refactor constants.py
    # and the other helper modules live in separate files. Generate the Flatpak
    # manifest's build-commands / sources lists dynamically so they cover every
    # .py file.
    shopt -s nullglob
    local _py_modules=("${SOURCE_DIR}"/*.py)
    shopt -u nullglob
    [[ ${#_py_modules[@]} -eq 0 ]] && die "No .py files found in the source directory: ${SOURCE_DIR}"
    local FLATPAK_PY_INSTALL="" FLATPAK_PY_SOURCES=""
    for _pyfile in "${_py_modules[@]}"; do
        local _bn
        _bn="$(basename "${_pyfile}")"
        FLATPAK_PY_INSTALL+="      - install -Dm644 ${_bn} /app/lib/voidpulse/${_bn}
"
        FLATPAK_PY_SOURCES+="      - type: file
        path: ${_bn}
"
    done
    info "Python modules added to the manifest: ${#_py_modules[@]}"

    cat > "${MANIFEST}" << MANIFEST
app-id: ${APP_ID}
runtime: ${RUNTIME_NAME}
runtime-version: '${RUNTIME_VER}'
sdk: ${SDK_NAME}
command: voidpulse

finish-args:
  - --socket=wayland
  - --socket=fallback-x11
  - --share=ipc
  - --device=dri
  - --socket=pulseaudio
  - --filesystem=xdg-run/pipewire-0
  - --share=network
  - --filesystem=xdg-music
  - --filesystem=home:ro
  - --filesystem=xdg-config
  - --socket=session-bus
  - --own-name=org.mpris.MediaPlayer2.VoidPulse
  - --talk-name=org.gnome.SettingsDaemon.MediaKeys
  - --talk-name=org.freedesktop.login1

modules:

  - name: python-deps
    buildsystem: simple
    build-options:
      no-debuginfo: true
      no-debuginfo-compression: true
      build-args:
        - --share=network
    build-commands:
      - pip3 install --prefix=/app --no-cache-dir --quiet mutagen
      - pip3 install --prefix=/app --no-cache-dir --quiet PyQt6 PyQt6-Qt6 PyQt6-sip numpy soxr
    sources: []

  - name: voidpulse
    buildsystem: simple
    build-commands:
${FLATPAK_PY_INSTALL}      - install -Dm755 voidpulse-launcher /app/bin/voidpulse
      - install -Dm644 ${APP_ID}.desktop /app/share/applications/${APP_ID}.desktop
      - install -Dm644 ${APP_ID}.svg /app/share/icons/hicolor/scalable/apps/${APP_ID}.svg
      - install -Dm644 appdata.xml /app/share/metainfo/${APP_ID}.appdata.xml
      - install -Dm644 NotoMusic-Regular.ttf /app/share/fonts/truetype/NotoMusic/NotoMusic-Regular.ttf
    sources:
${FLATPAK_PY_SOURCES}      - type: file
        path: voidpulse-launcher
      - type: file
        path: ${APP_ID}.desktop
      - type: file
        path: ${APP_ID}.svg
      - type: file
        path: appdata.xml
      - type: file
        path: NotoMusic-Regular.ttf
MANIFEST

    sep
    log "Building Flatpak (fast when PyQt6 is cached)..."
    cd "${SOURCE_DIR}"

    flatpak-builder \
        --user \
        --force-clean \
        --disable-rofiles-fuse \
        --repo="${REPO_DIR}" \
        "${BUILD_DIR}" \
        "${MANIFEST}"

    sign_flatpak_repo "${REPO_DIR}"

    sep
    log "Creating bundle: ${BUNDLE}"
    log "  (~250 MB of content → 1-2 minutes)"

    local _GPG_BUNDLE_ARG=()
    [[ -n "${GPG_KEY_ID}" ]] && _GPG_BUNDLE_ARG=(--gpg-sign="${GPG_KEY_ID}")
    flatpak build-bundle \
        --runtime-repo="https://flathub.org/repo/flathub.flatpakrepo" \
        "${_GPG_BUNDLE_ARG[@]+"${_GPG_BUNDLE_ARG[@]}"}" \
        "${REPO_DIR}" \
        "${BUNDLE}" \
        "${APP_ID}"

    local BUNDLE_MB
    BUNDLE_MB=$(du -sh "${BUNDLE}" | cut -f1)
    sep
    echo -e "${GREEN}${BOLD}  ✓ Flatpak ready!${NC}"
    sep
    echo -e "  ${BOLD}Bundle  :${NC} ${BUNDLE}  (${BUNDLE_MB})"
    echo -e "  ${BOLD}Install :${NC} flatpak install --user ${BUNDLE}"
    echo -e "  ${BOLD}Run     :${NC} flatpak run ${APP_ID}"
    echo -e "  ${BOLD}Remove  :${NC} flatpak uninstall --user ${APP_ID}"
    sep
}

# =============================================================================
#  DEB (Debian / Ubuntu)
# =============================================================================
build_deb() {
    sep
    echo -e "${BOLD}  VoidPulse → DEB Builder v8${NC}"
    sep

    check_sources

    # ── Tool check ─────────────────────────────────────────────────────────────
    log "Checking system tools..."

    # openSUSE detection
    local IS_OPENSUSE_DEB=0
    if [[ -f /etc/os-release ]] && grep -qiE "opensuse|suse" /etc/os-release; then
        IS_OPENSUSE_DEB=1
        warn "openSUSE system detected — the DEB target is recommended only for Debian/Ubuntu."
        warn "Use the RPM target on openSUSE: $0 rpm"
    fi

    local missing_tools=()
    command -v dpkg-deb  &>/dev/null || missing_tools+=("dpkg-deb")
    command -v fakeroot  &>/dev/null || missing_tools+=("fakeroot")
    if [[ ${#missing_tools[@]} -gt 0 ]]; then
        if [[ "${IS_OPENSUSE_DEB}" -eq 1 ]]; then
            die "Missing tools:\n$(printf '   • %s\n' "${missing_tools[@]}")\n   openSUSE : sudo zypper install dpkg fakeroot\n   Note     : the RPM target is recommended on openSUSE: $0 rpm"
        else
            die "Missing tools:\n$(printf '   • %s\n' "${missing_tools[@]}")\n   Install: sudo apt install dpkg-dev fakeroot"
        fi
    fi
    info "Tools ready ✓"

    download_font

    # ── Directory layout ──────────────────────────────────────────────────────
    local ARCH
    if command -v dpkg &>/dev/null; then
        ARCH=$(dpkg --print-architecture 2>/dev/null || echo "amd64")
    else
        # No dpkg (openSUSE etc.) — resolve the machine from uname
        case "$(uname -m)" in
            x86_64)  ARCH="amd64"   ;;
            aarch64) ARCH="arm64"   ;;
            armv7*)  ARCH="armhf"   ;;
            *)       ARCH="$(uname -m)" ;;
        esac
    fi
    local PKG_NAME="${APP_NAME}_${APP_VERSION}_${ARCH}"
    local PKG_DIR="${SOURCE_DIR}/deb-build/${PKG_NAME}"
    local OUT_DEB="${SOURCE_DIR}/${PKG_NAME}.deb"

    log "Preparing build directory: ${PKG_DIR}"
    rm -rf "${SOURCE_DIR}/deb-build"
    mkdir -p \
        "${PKG_DIR}/DEBIAN" \
        "${PKG_DIR}/usr/bin" \
        "${PKG_DIR}/usr/lib/${APP_NAME}" \
        "${PKG_DIR}/usr/share/applications" \
        "${PKG_DIR}/usr/share/icons/hicolor/scalable/apps" \
        "${PKG_DIR}/usr/share/metainfo" \
        "${PKG_DIR}/usr/share/fonts/truetype/NotoMusic"

    # ── Place files ───────────────────────────────────────────────────────────
    log "Placing files..."
    shopt -s nullglob
    _py_modules=("${SOURCE_DIR}"/*.py)
    shopt -u nullglob
    [[ ${#_py_modules[@]} -eq 0 ]] && die "No .py files found in the source directory: ${SOURCE_DIR}"
    for _pyfile in "${_py_modules[@]}"; do
        install -Dm644 "${_pyfile}" "${PKG_DIR}/usr/lib/${APP_NAME}/$(basename "${_pyfile}")"
    done
    info "Python modules copied: ${#_py_modules[@]}"
    install -Dm644 "${SOURCE_DIR}/${APP_ID}.desktop"  "${PKG_DIR}/usr/share/applications/${APP_ID}.desktop"
    install -Dm644 "${SOURCE_DIR}/${APP_ID}.svg"      "${PKG_DIR}/usr/share/icons/hicolor/scalable/apps/${APP_ID}.svg"
    install -Dm644 "${FONT_FILE}"                     "${PKG_DIR}/usr/share/fonts/truetype/NotoMusic/NotoMusic-Regular.ttf"

    # ── AppStream metainfo ────────────────────────────────────────────────────
    cat > "${PKG_DIR}/usr/share/metainfo/${APP_ID}.appdata.xml" << APPDATA
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>org.voidpulse.VoidPulse</id>
  <metadata_license>CC0-1.0</metadata_license>
  <project_license>GPL-3.0-or-later</project_license>
  <name>VoidPulse</name>
  <summary>Touch and OLED friendly advanced music player</summary>
  <description>
    <p>Touch and OLED friendly advanced music player</p>
  </description>
  <launchable type="desktop-id">org.voidpulse.VoidPulse.desktop</launchable>
  <releases>
    <release version="${APP_VERSION}" date="$(date +%Y-%m-%d)"/>
  </releases>
  <url type="homepage">${APP_URL}</url>
  <developer_name>${APP_MAINTAINER}</developer_name>
  <content_rating type="oars-1.1"/>
</component>
APPDATA

    # ── Launcher ──────────────────────────────────────────────────────────────
    cat > "${PKG_DIR}/usr/bin/${APP_NAME}" << 'LAUNCHER'
#!/bin/bash
exec python3 /usr/lib/voidpulse/voidpulse.py "$@"
LAUNCHER
    chmod 755 "${PKG_DIR}/usr/bin/${APP_NAME}"

    # ── DEBIAN/control ────────────────────────────────────────────────────────
    log "Writing DEBIAN/control..."
    cat > "${PKG_DIR}/DEBIAN/control" << CONTROL
Package: ${APP_NAME}
Version: ${APP_VERSION}
Architecture: ${ARCH}
Maintainer: ${APP_MAINTAINER}
Description: ${APP_DESC}
 Touch- and OLED-friendly advanced music player.
 Wayland, GNOME/KDE integration, PipeWire, GStreamer
 spectrum visualization, MPRIS2 D-Bus and bit-perfect
 audio support.
Depends: python3 (>= 3.10), python3-pyqt6 | python3-qt6,
 python3-mutagen, python3-numpy, gstreamer1.0-plugins-good,
 gstreamer1.0-plugins-bad, gstreamer1.0-pulseaudio
Recommends: fonts-noto-music, python3-soxr
Homepage: ${APP_URL}
Section: sound
Priority: optional
CONTROL

    # ── DEBIAN/postinst — refresh the font cache ─────────────────────────────
    cat > "${PKG_DIR}/DEBIAN/postinst" << 'POSTINST'
#!/bin/sh
set -e
fc-cache -f /usr/share/fonts/truetype/NotoMusic/ 2>/dev/null || true
update-desktop-database /usr/share/applications/ 2>/dev/null || true
POSTINST
    chmod 755 "${PKG_DIR}/DEBIAN/postinst"

    # ── DEBIAN/postrm — cleanup ───────────────────────────────────────────────
    cat > "${PKG_DIR}/DEBIAN/postrm" << 'POSTRM'
#!/bin/sh
set -e
fc-cache -f 2>/dev/null || true
update-desktop-database /usr/share/applications/ 2>/dev/null || true
POSTRM
    chmod 755 "${PKG_DIR}/DEBIAN/postrm"

    # ── Compute sizes & build package ─────────────────────────────────────────
    local INSTALLED_SIZE
    INSTALLED_SIZE=$(du -sk "${PKG_DIR}" | cut -f1)
    echo "Installed-Size: ${INSTALLED_SIZE}" >> "${PKG_DIR}/DEBIAN/control"

    log "Building DEB package..."
    fakeroot dpkg-deb --build "${PKG_DIR}" "${OUT_DEB}"
    sign_deb "${OUT_DEB}"

    local DEB_MB
    DEB_MB=$(du -sh "${OUT_DEB}" | cut -f1)
    sep
    echo -e "${GREEN}${BOLD}  ✓ DEB package ready!${NC}"
    sep
    echo -e "  ${BOLD}Paket   :${NC} ${OUT_DEB}  (${DEB_MB})"
    echo -e "  ${BOLD}Install :${NC} sudo apt install ./${PKG_NAME}.deb"
    echo -e "  ${BOLD}Run     :${NC} ${APP_NAME}"
    echo -e "  ${BOLD}Remove  :${NC} sudo apt remove ${APP_NAME}"
    sep

    rm -rf "${SOURCE_DIR}/deb-build"
}

# =============================================================================
#  DEB — Multi-arch (arm64 · armhf · armel · riscv64 · loong64 · amd64)
#  Builds packages for every DEB architecture, phones and embedded targets included.
#  No cross-compilation needed; the app is Python (noarch), so only the
#  Architecture field in DEBIAN/control changes.
# =============================================================================
build_deb_multiarch() {
    sep
    echo -e "${BOLD}  VoidPulse → DEB Multi-Arch Builder v8${NC}"
    sep

    check_sources

    # ── Tool check ─────────────────────────────────────────────────────────────
    log "Checking system tools..."
    local IS_OPENSUSE_DEB=0
    if [[ -f /etc/os-release ]] && grep -qiE "opensuse|suse" /etc/os-release; then
        IS_OPENSUSE_DEB=1
        warn "openSUSE system detected — the DEB target is recommended only for Debian/Ubuntu."
    fi

    local missing_tools=()
    command -v dpkg-deb &>/dev/null || missing_tools+=("dpkg-deb")
    command -v fakeroot &>/dev/null || missing_tools+=("fakeroot")
    if [[ ${#missing_tools[@]} -gt 0 ]]; then
        if [[ "${IS_OPENSUSE_DEB}" -eq 1 ]]; then
            die "Missing tools:\n$(printf '   • %s\n' "${missing_tools[@]}")\n   openSUSE: sudo zypper install dpkg fakeroot"
        else
            die "Missing tools:\n$(printf '   • %s\n' "${missing_tools[@]}")\n   Install: sudo apt install dpkg-dev fakeroot"
        fi
    fi
    info "Tools ready ✓"

    download_font

    # ── Target architectures ──────────────────────────────────────────────────
    # DEB architecture name → dpkg Architecture field value
    # The app is pure Python, so a single source is used for every target.
    #
    #  Arch       | Description
    #  -----------|----------------------------------------------------------
    #  amd64      | x86-64 desktop / server
    #  arm64      | AArch64 — Raspberry Pi 4/5, Pine64, Apple Silicon (Linux)
    #  armhf      | ARMv7-A hard-float — PinePhone Pro, Librem 5, older SBCs
    #  armel      | ARMv4T+ soft-float — very old embedded ARM systems
    #  riscv64    | RISC-V 64-bit — VisionFive 2, StarFive SBCs
    #  loong64    | LoongArch 64-bit — Loongson 3A5000 and newer
    declare -A DEB_ARCH_MAP=(
        [amd64]="amd64"
        [arm64]="arm64"
        [armhf]="armhf"
        [armel]="armel"
        [riscv64]="riscv64"
        [loong64]="loong64"
    )

    # Target selection: ask interactively when no argument is given
    local SELECTED_ARCHES=()
    if [[ -n "${DEB_ARCH_TARGETS:-}" ]]; then
        # Overridable through an environment variable, e.g. DEB_ARCH_TARGETS="arm64,armhf"
        IFS=',' read -ra SELECTED_ARCHES <<< "${DEB_ARCH_TARGETS}"
    else
        echo ""
        echo -e "  Which architectures should the DEB package be built for?"
        echo -e "  ${BOLD}0)${NC} Hepsi (amd64 arm64 armhf armel riscv64 loong64)"
        echo -e "  ${BOLD}1)${NC} amd64    — x86-64 desktop/server"
        echo -e "  ${BOLD}2)${NC} arm64    — AArch64 (Raspberry Pi 4/5, Pine64, phones)"
        echo -e "  ${BOLD}3)${NC} armhf    — ARMv7-A hard-float (PinePhone, Librem 5)"
        echo -e "  ${BOLD}4)${NC} armel    — ARMv4T+ soft-float (older embedded ARM)"
        echo -e "  ${BOLD}5)${NC} riscv64  — RISC-V 64-bit"
        echo -e "  ${BOLD}6)${NC} loong64  — LoongArch 64-bit"
        echo ""
        read -rp "  Selection [0-6], comma-separated (e.g. 2,3): " arch_choice

        if [[ "${arch_choice}" == "0" || "${arch_choice}" == "all" ]]; then
            SELECTED_ARCHES=(amd64 arm64 armhf armel riscv64 loong64)
        else
            IFS=',' read -ra _tokens <<< "${arch_choice}"
            for t in "${_tokens[@]}"; do
                t="${t// /}"
                case "${t}" in
                    1) SELECTED_ARCHES+=(amd64)   ;;
                    2) SELECTED_ARCHES+=(arm64)   ;;
                    3) SELECTED_ARCHES+=(armhf)   ;;
                    4) SELECTED_ARCHES+=(armel)   ;;
                    5) SELECTED_ARCHES+=(riscv64) ;;
                    6) SELECTED_ARCHES+=(loong64) ;;
                    amd64|arm64|armhf|armel|riscv64|loong64) SELECTED_ARCHES+=("${t}") ;;
                    *) warn "Skipped unknown architecture: ${t}" ;;
                esac
            done
        fi
    fi

    [[ ${#SELECTED_ARCHES[@]} -eq 0 ]] && die "No architecture selected."
    info "Target architectures: ${SELECTED_ARCHES[*]}"
    sep

    local BUILT_DEBS=()

    for TARGET_ARCH in "${SELECTED_ARCHES[@]}"; do
        sep
        log "Building DEB → ${TARGET_ARCH}"

        local PKG_NAME="${APP_NAME}_${APP_VERSION}_${TARGET_ARCH}"
        local PKG_DIR="${SOURCE_DIR}/deb-build/${PKG_NAME}"
        local OUT_DEB="${SOURCE_DIR}/${PKG_NAME}.deb"

        rm -rf "${PKG_DIR}"
        mkdir -p \
            "${PKG_DIR}/DEBIAN" \
            "${PKG_DIR}/usr/bin" \
            "${PKG_DIR}/usr/lib/${APP_NAME}" \
            "${PKG_DIR}/usr/share/applications" \
            "${PKG_DIR}/usr/share/icons/hicolor/scalable/apps" \
            "${PKG_DIR}/usr/share/metainfo" \
            "${PKG_DIR}/usr/share/fonts/truetype/NotoMusic"

        # ── Place files ───────────────────────────────────────────────────────
        shopt -s nullglob
        _py_modules=("${SOURCE_DIR}"/*.py)
        shopt -u nullglob
        [[ ${#_py_modules[@]} -eq 0 ]] && die "No .py files found in the source directory: ${SOURCE_DIR}"
        for _pyfile in "${_py_modules[@]}"; do
            install -Dm644 "${_pyfile}" "${PKG_DIR}/usr/lib/${APP_NAME}/$(basename "${_pyfile}")"
        done
        info "Python modules copied: ${#_py_modules[@]}"
        install -Dm644 "${SOURCE_DIR}/${APP_ID}.desktop"  "${PKG_DIR}/usr/share/applications/${APP_ID}.desktop"
        install -Dm644 "${SOURCE_DIR}/${APP_ID}.svg"      "${PKG_DIR}/usr/share/icons/hicolor/scalable/apps/${APP_ID}.svg"
        install -Dm644 "${FONT_FILE}"                     "${PKG_DIR}/usr/share/fonts/truetype/NotoMusic/NotoMusic-Regular.ttf"

        # ── AppStream metainfo ────────────────────────────────────────────────
        cat > "${PKG_DIR}/usr/share/metainfo/${APP_ID}.appdata.xml" << APPDATA
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>org.voidpulse.VoidPulse</id>
  <metadata_license>CC0-1.0</metadata_license>
  <project_license>GPL-3.0-or-later</project_license>
  <name>VoidPulse</name>
  <summary>Touch and OLED friendly advanced music player</summary>
  <description>
    <p>Touch and OLED friendly advanced music player</p>
  </description>
  <launchable type="desktop-id">org.voidpulse.VoidPulse.desktop</launchable>
  <releases>
    <release version="${APP_VERSION}" date="$(date +%Y-%m-%d)"/>
  </releases>
  <url type="homepage">${APP_URL}</url>
  <developer_name>${APP_MAINTAINER}</developer_name>
  <content_rating type="oars-1.1"/>
</component>
APPDATA

        # ── Launcher ──────────────────────────────────────────────────────────
        cat > "${PKG_DIR}/usr/bin/${APP_NAME}" << 'LAUNCHER'
#!/bin/bash
exec python3 /usr/lib/voidpulse/voidpulse.py "$@"
LAUNCHER
        chmod 755 "${PKG_DIR}/usr/bin/${APP_NAME}"

        # ── Architecture-specific dependency note ────────────────────────────
        # arm64/armhf/armel: phone/SBC distros often ship python3-pyqt5 instead
        # of python3-pyqt6; both are listed in Depends.
        local PYQT_DEP="python3-pyqt6 | python3-qt6 | python3-pyqt5"
        local EXTRA_DEP=""
        case "${TARGET_ARCH}" in
            arm64|armhf|armel)
                # The GPU/GLES library is useful on ARM devices.
                # NOTE: an arch restriction ([arm64] etc.) is only valid in source
                # control files; in a binary .deb DEBIAN/control file it causes a
                # syntax error — do not use it here.
                EXTRA_DEP="Suggests: libgles2"
                ;;
        esac

        # ── DEBIAN/control ────────────────────────────────────────────────────
        cat > "${PKG_DIR}/DEBIAN/control" << CONTROL
Package: ${APP_NAME}
Version: ${APP_VERSION}
Architecture: ${TARGET_ARCH}
Maintainer: ${APP_MAINTAINER}
Description: ${APP_DESC}
 Touch- and OLED-friendly advanced music player.
 Wayland, GNOME/KDE integration, PipeWire, GStreamer
 spectrum visualization, MPRIS2 D-Bus and bit-perfect
 audio support.
Depends: python3 (>= 3.10), ${PYQT_DEP},
 python3-mutagen, python3-numpy, gstreamer1.0-plugins-good,
 gstreamer1.0-plugins-bad, gstreamer1.0-pulseaudio
Recommends: fonts-noto-music, python3-soxr
Homepage: ${APP_URL}
Section: sound
Priority: optional
CONTROL
        # Optional extra field (skipped when empty)
        [[ -n "${EXTRA_DEP}" ]] && echo "${EXTRA_DEP}" >> "${PKG_DIR}/DEBIAN/control"

        # ── postinst / postrm ─────────────────────────────────────────────────
        cat > "${PKG_DIR}/DEBIAN/postinst" << 'POSTINST'
#!/bin/sh
set -e
fc-cache -f /usr/share/fonts/truetype/NotoMusic/ 2>/dev/null || true
update-desktop-database /usr/share/applications/ 2>/dev/null || true
POSTINST
        chmod 755 "${PKG_DIR}/DEBIAN/postinst"

        cat > "${PKG_DIR}/DEBIAN/postrm" << 'POSTRM'
#!/bin/sh
set -e
fc-cache -f 2>/dev/null || true
update-desktop-database /usr/share/applications/ 2>/dev/null || true
POSTRM
        chmod 755 "${PKG_DIR}/DEBIAN/postrm"

        # ── Size & package ────────────────────────────────────────────────────
        local INSTALLED_SIZE
        INSTALLED_SIZE=$(du -sk "${PKG_DIR}" | cut -f1)
        echo "Installed-Size: ${INSTALLED_SIZE}" >> "${PKG_DIR}/DEBIAN/control"

        log "Building DEB package (${TARGET_ARCH})..."
        fakeroot dpkg-deb --build "${PKG_DIR}" "${OUT_DEB}"
        sign_deb "${OUT_DEB}"

        local DEB_MB
        DEB_MB=$(du -sh "${OUT_DEB}" | cut -f1)
        info "  ✓ ${OUT_DEB}  (${DEB_MB})"
        BUILT_DEBS+=("${OUT_DEB}")
    done

    rm -rf "${SOURCE_DIR}/deb-build"

    sep
    echo -e "${GREEN}${BOLD}  ✓ Multi-arch DEB packages ready!${NC}"
    sep
    for _deb in "${BUILT_DEBS[@]}"; do
        local _sz
        _sz=$(du -sh "${_deb}" | cut -f1)
        echo -e "  ${BOLD}Paket:${NC} ${_deb}  (${_sz})"
    done
    echo ""
    echo -e "  ${BOLD}Install :${NC} sudo apt install ./<package>.deb"
    echo -e "  ${BOLD}Run     :${NC} ${APP_NAME}"
    echo -e "  ${BOLD}Remove  :${NC} sudo apt remove ${APP_NAME}"
    echo ""
    echo -e "  ${BOLD}Note    :${NC} Copy the arm64/armhf/armel packages to the target device with SCP:"
    echo -e "            scp voidpulse_*_arm64.deb user@raspberrypi:~/"
    echo -e "            ssh user@raspberrypi sudo apt install ./voidpulse_*_arm64.deb"
    sep
}

# =============================================================================
#  RPM (Fedora / openSUSE / RHEL / Arch foreign packages)
# =============================================================================
build_rpm() {
    sep
    echo -e "${BOLD}  VoidPulse → RPM Builder v8${NC}"
    sep

    check_sources

    # ── Distro detection ───────────────────────────────────────────────────────
    local IS_OPENSUSE=0
    if [[ -f /etc/os-release ]]; then
        if grep -qiE "opensuse|suse" /etc/os-release; then
            IS_OPENSUSE=1
            info "openSUSE system detected ✓"
        fi
    fi

    # ── Tool check ─────────────────────────────────────────────────────────────
    log "Checking system tools..."
    local missing_tools=()
    command -v rpmbuild &>/dev/null || missing_tools+=("rpmbuild  (rpm-build / rpmdevtools)")
    if [[ ${#missing_tools[@]} -gt 0 ]]; then
        if [[ "${IS_OPENSUSE}" -eq 1 ]]; then
            die "Missing tools:\n$(printf '   • %s\n' "${missing_tools[@]}")\n   openSUSE : sudo zypper install rpm-build rpmdevtools"
        else
            die "Missing tools:\n$(printf '   • %s\n' "${missing_tools[@]}")\n   Fedora/RHEL : sudo dnf install rpm-build rpmdevtools\n   openSUSE    : sudo zypper install rpm-build"
        fi
    fi
    info "Tools ready ✓"

    # ── Target architecture detection ─────────────────────────────────────────
    # Overridable through the RPM_TARGET_ARCH environment variable.
    # The app is pure Python (noarch), so the same .rpm installs everywhere;
    # --target is still needed so rpmbuild uses the right %{_arch} macro.
    #
    #  uname -m    → RPM _target_cpu
    #  x86_64      → x86_64
    #  aarch64     → aarch64   (Raspberry Pi 4/5, Pine64, Librem 5, phones)
    #  armv7l      → armv7hl   (PinePhone Pro, older SBCs — hard-float)
    #  armv6l      → armv6hl
    #  riscv64     → riscv64
    local HOST_UNAME
    HOST_UNAME=$(uname -m)
    local RPM_CPU
    if [[ -n "${RPM_TARGET_ARCH:-}" ]]; then
        RPM_CPU="${RPM_TARGET_ARCH}"
        info "Target architecture (environment variable): ${RPM_CPU}"
    else
        case "${HOST_UNAME}" in
            x86_64)          RPM_CPU="x86_64"  ;;
            aarch64)         RPM_CPU="aarch64" ;;
            armv7l|armv7*)   RPM_CPU="armv7hl" ;;
            armv6l|armv6*)   RPM_CPU="armv6hl" ;;
            riscv64)         RPM_CPU="riscv64" ;;
            i?86)            RPM_CPU="i686"    ;;
            *)               RPM_CPU="${HOST_UNAME}" ;;
        esac
        info "Target architecture (auto-detected): ${RPM_CPU}"
    fi

    # A noarch package is produced; --target only decides rpmbuild's RPMS/<arch>/
    # directory and the architecture tag in the package name.
    local RPM_TARGET="${RPM_CPU}-linux"

    download_font

    # ── Set up the RPM directory layout ────────────────────────────────────────
    local RPM_ROOT="${SOURCE_DIR}/rpm-build"
    log "Creating RPM build tree: ${RPM_ROOT}"
    rm -rf "${RPM_ROOT}"
    mkdir -p "${RPM_ROOT}"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}

    # ── Create the source tarball ─────────────────────────────────────────────
    local TAR_NAME="${APP_NAME}-${APP_VERSION}"
    local TAR_DIR="${RPM_ROOT}/SOURCES/${TAR_NAME}"
    mkdir -p "${TAR_DIR}"

    shopt -s nullglob
    local _py_modules=("${SOURCE_DIR}"/*.py)
    shopt -u nullglob
    [[ ${#_py_modules[@]} -eq 0 ]] && die "No .py files found in the source directory: ${SOURCE_DIR}"
    cp "${_py_modules[@]}"                "${TAR_DIR}/"
    cp "${SOURCE_DIR}/${APP_ID}.desktop" "${TAR_DIR}/"
    cp "${SOURCE_DIR}/${APP_ID}.svg"     "${TAR_DIR}/"
    cp "${FONT_FILE}"                    "${TAR_DIR}/"
    info "Python modules copied: ${#_py_modules[@]}"

    tar -czf "${RPM_ROOT}/SOURCES/${TAR_NAME}.tar.gz" \
        -C "${RPM_ROOT}/SOURCES" "${TAR_NAME}"
    rm -rf "${TAR_DIR}"

    # ── Launcher script ───────────────────────────────────────────────────────
    cat > "${RPM_ROOT}/SOURCES/voidpulse-launcher.sh" << 'LAUNCHER'
#!/bin/bash
exec python3 /usr/lib/voidpulse/voidpulse.py "$@"
LAUNCHER

    # ── AppStream metainfo ────────────────────────────────────────────────────
    cat > "${RPM_ROOT}/SOURCES/${APP_ID}.appdata.xml" << APPDATA
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>org.voidpulse.VoidPulse</id>
  <metadata_license>CC0-1.0</metadata_license>
  <project_license>GPL-3.0-or-later</project_license>
  <name>VoidPulse</name>
  <summary>Touch and OLED friendly advanced music player</summary>
  <description>
    <p>Touch and OLED friendly advanced music player</p>
  </description>
  <launchable type="desktop-id">org.voidpulse.VoidPulse.desktop</launchable>
  <releases>
    <release version="${APP_VERSION}" date="$(date +%Y-%m-%d)"/>
  </releases>
  <url type="homepage">${APP_URL}</url>
  <developer_name>${APP_MAINTAINER}</developer_name>
  <content_rating type="oars-1.1"/>
</component>
APPDATA

    # ── SPEC file ────────────────────────────────────────────────────────────
    local SPEC="${RPM_ROOT}/SPECS/${APP_NAME}.spec"
    log "Writing SPEC file: ${SPEC}"

    # Package names per distro + architecture
    # openSUSE: python3-qt6, gstreamer-plugins-good/bad
    # Fedora  : python3-PyQt6, gstreamer1-plugins-good/bad-free
    # A PyQt5 fallback is added on ARM distros (the PyQt6 package may be missing)
    local PYQT_PKG PYQT_FALLBACK GST_GOOD GST_BAD MUTAGEN_PKG NUMPY_PKG SOXR_PKG
    local PYTHON_REQ FILES_LICENSE
    if [[ "${IS_OPENSUSE}" -eq 1 ]]; then
        PYQT_PKG="python3-qt6"
        GST_GOOD="gstreamer-plugins-good"
        GST_BAD="gstreamer-plugins-bad"
        MUTAGEN_PKG="python3-mutagen"
        NUMPY_PKG="python3-numpy"
        # openSUSE packages soxr under the versioned python31x- prefix (same
        # convention as its python313-numpy, unlike Fedora's plain python3-soxr).
        SOXR_PKG="python313-soxr"
        PYTHON_REQ="python3 >= 3.10"
        FILES_LICENSE="%doc /usr/lib/voidpulse/voidpulse.py"
    else
        PYQT_PKG="python3-PyQt6"
        GST_GOOD="gstreamer1-plugins-good"
        GST_BAD="gstreamer1-plugins-bad-free"
        MUTAGEN_PKG="python3-mutagen"
        NUMPY_PKG="python3-numpy"
        SOXR_PKG="python3-soxr"
        PYTHON_REQ="python3 >= 3.10"
        FILES_LICENSE="%license /usr/lib/voidpulse/voidpulse.py"
    fi
    # On ARM architectures, add python3-PyQt5 as a Suggests entry
    local ARM_SUGGESTS_LINE=""
    case "${RPM_CPU}" in
        aarch64|armv7hl|armv6hl)
            ARM_SUGGESTS_LINE="Suggests:       python3-PyQt5"
            ;;
    esac

    cat > "${SPEC}" << SPEC
Name:           ${APP_NAME}
Version:        ${APP_VERSION}
Release:        ${APP_RELEASE}%{?dist}
Summary:        ${APP_DESC}
License:        GPL-3.0-or-later
URL:            ${APP_URL}
Source0:        %{name}-%{version}.tar.gz
Source1:        voidpulse-launcher.sh
Source2:        ${APP_ID}.appdata.xml

# Python application — runs on every architecture
BuildArch:      noarch
BuildRequires:  python3

Requires:       ${PYTHON_REQ}
Requires:       ${PYQT_PKG}
Requires:       ${MUTAGEN_PKG}
Requires:       ${NUMPY_PKG}
Requires:       ${GST_GOOD}
Requires:       ${GST_BAD}
Suggests:       ${SOXR_PKG}
${ARM_SUGGESTS_LINE}

%description
Touch- and OLED-friendly advanced music player.
Wayland, GNOME/KDE integration, PipeWire, GStreamer
spectrum visualization, MPRIS2 D-Bus and bit-perfect
audio support.
ARM architectures (aarch64, armv7hl) are fully supported.

%prep
%autosetup

%install
# voidpulse.py is no longer a single file — after the refactor constants.py
# and the other helper modules live in separate files; install them all, or
# "ModuleNotFoundError" is raised.
mkdir -p %{buildroot}/usr/lib/voidpulse
for _pyfile in *.py; do
    install -Dm644 "\${_pyfile}" "%{buildroot}/usr/lib/voidpulse/\${_pyfile}"
done
install -Dm755 %{SOURCE1}               %{buildroot}/usr/bin/voidpulse
install -Dm644 ${APP_ID}.desktop        %{buildroot}/usr/share/applications/${APP_ID}.desktop
install -Dm644 ${APP_ID}.svg            %{buildroot}/usr/share/icons/hicolor/scalable/apps/${APP_ID}.svg
install -Dm644 %{SOURCE2}               %{buildroot}/usr/share/metainfo/${APP_ID}.appdata.xml
install -Dm644 NotoMusic-Regular.ttf    %{buildroot}/usr/share/fonts/NotoMusic/NotoMusic-Regular.ttf

%post
fc-cache -f /usr/share/fonts/NotoMusic/ 2>/dev/null || :
update-desktop-database /usr/share/applications/ 2>/dev/null || :

%postun
fc-cache -f 2>/dev/null || :
update-desktop-database /usr/share/applications/ 2>/dev/null || :

%files
${FILES_LICENSE}
/usr/bin/voidpulse
/usr/lib/voidpulse/*.py
/usr/share/applications/${APP_ID}.desktop
/usr/share/icons/hicolor/scalable/apps/${APP_ID}.svg
/usr/share/metainfo/${APP_ID}.appdata.xml
/usr/share/fonts/NotoMusic/NotoMusic-Regular.ttf

%changelog
* $(date '+%a %b %d %Y') ${APP_MAINTAINER} - ${APP_VERSION}-${APP_RELEASE}
- Initial package release; full ARM (aarch64/armv7hl) support added
SPEC

    # ── Build ─────────────────────────────────────────────────────────────────
    log "Building RPM (target: ${RPM_TARGET})..."
    rpmbuild \
        --define "_topdir ${RPM_ROOT}" \
        --target "${RPM_TARGET}" \
        -bb "${SPEC}"

    # ── Copy the output into the source directory ────────────────────────────
    local BUILT_RPM
    BUILT_RPM=$(find "${RPM_ROOT}/RPMS" -name "*.rpm" | head -1)
    [[ -n "${BUILT_RPM}" ]] || die "RPM file could not be created."
    local OUT_RPM="${SOURCE_DIR}/$(basename "${BUILT_RPM}")"
    cp "${BUILT_RPM}" "${OUT_RPM}"
    sign_rpm "${OUT_RPM}"

    local RPM_MB
    RPM_MB=$(du -sh "${OUT_RPM}" | cut -f1)
    sep
    echo -e "${GREEN}${BOLD}  ✓ RPM package ready!${NC}"
    sep
    echo -e "  ${BOLD}Paket   :${NC} ${OUT_RPM}  (${RPM_MB})"
    echo -e "  ${BOLD}Arch    :${NC} ${RPM_CPU} (noarch package — installs on every architecture)"
    echo -e "  ${BOLD}Install :${NC} sudo dnf install ${OUT_RPM}      # Fedora/RHEL/ARM"
    echo -e "              sudo zypper install ${OUT_RPM}  # openSUSE/ARM"
    echo -e "  ${BOLD}Run     :${NC} ${APP_NAME}"
    echo -e "  ${BOLD}Remove  :${NC} sudo dnf remove ${APP_NAME}"
    echo -e ""
    echo -e "  ${BOLD}Hint    :${NC} To copy to an ARM device with SCP:"
    echo -e "              scp $(basename "${OUT_RPM}") user@pihost:~/"
    echo -e "              ssh user@pihost sudo dnf install ./$(basename "${OUT_RPM}")"
    echo -e "  ${BOLD}Hint    :${NC} For another architecture: RPM_TARGET_ARCH=aarch64 $0 rpm"
    sep

    rm -rf "${RPM_ROOT}"
}

# =============================================================================
#  APK (Alpine Linux)
# =============================================================================
build_apk() {
    sep
    echo -e "${BOLD}  VoidPulse → APK (Alpine) Builder v8${NC}"
    sep

    # ── Alpine Linux check ────────────────────────────────────────────────────
    if ! grep -qi "alpine" /etc/os-release 2>/dev/null; then
        warn "This system is not Alpine Linux — skipping the APK step."
        warn "The APK package can only be built on Alpine Linux."
        return 0
    fi

    check_sources

    # ── Tool check ─────────────────────────────────────────────────────────────
    log "Checking system tools..."
    local missing_tools=()
    command -v abuild  &>/dev/null || missing_tools+=("abuild  (alpine-sdk)")
    command -v apk     &>/dev/null || missing_tools+=("apk     (alpine-sdk)")
    if [[ ${#missing_tools[@]} -gt 0 ]]; then
        warn "Missing tools: ${missing_tools[*]}"
        warn "This builder only runs on Alpine Linux."
        warn "Install: sudo apk add alpine-sdk abuild-rootbuild"
        warn "Then  : abuild-keygen -a -i   # create a signing key"
        die  "Tools required for the APK build are missing."
    fi
    info "Tools ready ✓"

    # ── abuild key check ──────────────────────────────────────────────────────
    local ABUILD_CONF="${HOME}/.abuild/abuild.conf"
    if [[ ! -f "${ABUILD_CONF}" ]]; then
        warn "abuild signing key not found: ${ABUILD_CONF}"
        warn "To create a key: abuild-keygen -a -i"
        die  "A signing key is required for the APK build."
    fi
    info "signing key present ✓"

    download_font

    # ── APKBUILD directory ────────────────────────────────────────────────────
    local APK_BUILD_DIR="${SOURCE_DIR}/apk-build/${APP_NAME}"
    rm -rf "${SOURCE_DIR}/apk-build"
    mkdir -p "${APK_BUILD_DIR}"

    # ── Create the source tarball ─────────────────────────────────────────────
    local TAR_NAME="${APP_NAME}-${APP_VERSION}"
    local TAR_DIR="/tmp/${TAR_NAME}"
    rm -rf "${TAR_DIR}"
    mkdir -p "${TAR_DIR}"

    shopt -s nullglob
    local _py_modules=("${SOURCE_DIR}"/*.py)
    shopt -u nullglob
    [[ ${#_py_modules[@]} -eq 0 ]] && die "No .py files found in the source directory: ${SOURCE_DIR}"
    cp "${_py_modules[@]}"                "${TAR_DIR}/"
    cp "${SOURCE_DIR}/${APP_ID}.desktop" "${TAR_DIR}/"
    cp "${SOURCE_DIR}/${APP_ID}.svg"     "${TAR_DIR}/"
    cp "${FONT_FILE}"                    "${TAR_DIR}/"
    info "Python modules copied: ${#_py_modules[@]}"

    tar -czf "${APK_BUILD_DIR}/${TAR_NAME}.tar.gz" \
        -C /tmp "${TAR_NAME}"
    rm -rf "${TAR_DIR}"

    # ── Launcher script ───────────────────────────────────────────────────────
    cat > "${APK_BUILD_DIR}/voidpulse-launcher.sh" << 'LAUNCHER'
#!/bin/sh
exec python3 /usr/lib/voidpulse/voidpulse.py "$@"
LAUNCHER

    # ── AppStream metainfo ────────────────────────────────────────────────────
    cat > "${APK_BUILD_DIR}/${APP_ID}.appdata.xml" << APPDATA
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>org.voidpulse.VoidPulse</id>
  <metadata_license>CC0-1.0</metadata_license>
  <project_license>GPL-3.0-or-later</project_license>
  <name>VoidPulse</name>
  <summary>Touch and OLED friendly advanced music player</summary>
  <description>
    <p>Touch and OLED friendly advanced music player</p>
  </description>
  <launchable type="desktop-id">org.voidpulse.VoidPulse.desktop</launchable>
  <releases>
    <release version="${APP_VERSION}" date="$(date +%Y-%m-%d)"/>
  </releases>
  <url type="homepage">${APP_URL}</url>
  <developer_name>${APP_MAINTAINER}</developer_name>
  <content_rating type="oars-1.1"/>
</component>
APPDATA

    # ── Compute SHA512 checksums ──────────────────────────────────────────────
    local SHA_TAR SHA_LAUNCHER SHA_META
    SHA_TAR=$(sha512sum "${APK_BUILD_DIR}/${TAR_NAME}.tar.gz"              | cut -d' ' -f1)
    SHA_LAUNCHER=$(sha512sum "${APK_BUILD_DIR}/voidpulse-launcher.sh"      | cut -d' ' -f1)
    SHA_META=$(sha512sum "${APK_BUILD_DIR}/${APP_ID}.appdata.xml"          | cut -d' ' -f1)
    local SHA_DT SHA_ICO
    SHA_DT=$(sha512sum "${SOURCE_DIR}/${APP_ID}.desktop"   | cut -d' ' -f1)
    SHA_ICO=$(sha512sum "${SOURCE_DIR}/${APP_ID}.svg"       | cut -d' ' -f1)
    local SHA_FONT
    SHA_FONT=$(sha512sum "${FONT_FILE}" | cut -d' ' -f1)

    # ── APKBUILD ──────────────────────────────────────────────────────────────
    local APKBUILD="${APK_BUILD_DIR}/APKBUILD"
    log "Writing APKBUILD: ${APKBUILD}"
    cat > "${APKBUILD}" << APKBUILD
# Maintainer: ${APP_MAINTAINER}
pkgname="${APP_NAME}"
pkgver="${APP_VERSION}"
pkgrel=0
pkgdesc="${APP_DESC}"
url="${APP_URL}"
arch="noarch"
license="GPL-3.0-or-later"
depends="
    python3
    py3-pyqt6
    py3-mutagen
    py3-numpy
    gst-plugins-good
    gst-plugins-bad
"
makedepends="python3"
install=""
subpackages=""

source="
    ${TAR_NAME}.tar.gz
    voidpulse-launcher.sh
    ${APP_ID}.appdata.xml
    ${APP_ID}.desktop::${SOURCE_DIR}/${APP_ID}.desktop
    ${APP_ID}.svg::${SOURCE_DIR}/${APP_ID}.svg
    NotoMusic-Regular.ttf::${FONT_FILE}
"
sha512sums="
${SHA_TAR}  ${TAR_NAME}.tar.gz
${SHA_LAUNCHER}  voidpulse-launcher.sh
${SHA_META}  ${APP_ID}.appdata.xml
${SHA_DT}  ${APP_ID}.desktop
${SHA_ICO}  ${APP_ID}.svg
${SHA_FONT}  NotoMusic-Regular.ttf
"

build() {
    # The Python module is only installed; no compilation needed
    :
}

check() {
    for _pyfile in "\${builddir}"/*.py; do
        python3 -c "import ast; ast.parse(open('\${_pyfile}').read())" \
            && echo "Syntax check passed: \$(basename "\${_pyfile}") ✓"
    done
}

package() {
    # Python modules — voidpulse.py is no longer a single file; after the refactor
    # constants.py and the other helper modules must be installed too.
    for _pyfile in "\${builddir}"/*.py; do
        install -Dm644 "\${_pyfile}" \
            "\${pkgdir}/usr/lib/voidpulse/\$(basename "\${_pyfile}")"
    done

    # Launcher
    install -Dm755 "\${srcdir}/voidpulse-launcher.sh" \
        "\${pkgdir}/usr/bin/voidpulse"

    # .desktop
    install -Dm644 "\${srcdir}/${APP_ID}.desktop" \
        "\${pkgdir}/usr/share/applications/${APP_ID}.desktop"

    # Icon
    install -Dm644 "\${srcdir}/${APP_ID}.svg" \
        "\${pkgdir}/usr/share/icons/hicolor/scalable/apps/${APP_ID}.svg"

    # AppStream metainfo
    install -Dm644 "\${srcdir}/${APP_ID}.appdata.xml" \
        "\${pkgdir}/usr/share/metainfo/${APP_ID}.appdata.xml"

    # NotoMusic font
    install -Dm644 "\${srcdir}/NotoMusic-Regular.ttf" \
        "\${pkgdir}/usr/share/fonts/misc/NotoMusic-Regular.ttf"
}

APKBUILD

    # ── Build with abuild ─────────────────────────────────────────────────────
    log "Building APK..."
    cd "${APK_BUILD_DIR}"

    # abuild expects its sources relative to its own location;
    # sha512sums were already written by hand, so force with -F
    REPODEST="${SOURCE_DIR}/apk-out" abuild -F -P "${SOURCE_DIR}/apk-out"

    # ── Locate the output ────────────────────────────────────────────────────
    local BUILT_APK
    BUILT_APK=$(find "${SOURCE_DIR}/apk-out" -name "${APP_NAME}-${APP_VERSION}*.apk" | head -1)
    [[ -n "${BUILT_APK}" ]] || die "APK file could not be created. Check the 'apk-out/' directory."
    local OUT_APK="${SOURCE_DIR}/$(basename "${BUILT_APK}")"
    cp "${BUILT_APK}" "${OUT_APK}"

    local APK_MB
    APK_MB=$(du -sh "${OUT_APK}" | cut -f1)
    sep
    echo -e "${GREEN}${BOLD}  ✓ APK package ready!${NC}"
    sep
    echo -e "  ${BOLD}Paket   :${NC} ${OUT_APK}  (${APK_MB})"
    echo -e "  ${BOLD}Install :${NC} sudo apk add --allow-untrusted ${OUT_APK}"
    echo -e "  ${BOLD}Run     :${NC} ${APP_NAME}"
    echo -e "  ${BOLD}Remove  :${NC} sudo apk del ${APP_NAME}"
    sep

    rm -rf "${SOURCE_DIR}/apk-build" "${SOURCE_DIR}/apk-out"
}

# =============================================================================
#  APPIMAGE — Full ARM support
#  Supported architectures: x86_64 · aarch64 · armhf · i686
#
#  Single arch (current system):   build_appimage
#  Multi-arch:                 build_appimage_multiarch  (selectable from the menu)
#
#  The architecture can be overridden with the APPIMAGE_TARGET_ARCH env variable.
#  Example: APPIMAGE_TARGET_ARCH=aarch64 ./build-flatpak.sh appimage
#
#  appimagetool → downloaded from AppImageKit GitHub releases/continuous.
#  A separate binary exists per architecture; the script picks one automatically.
#
#  Dependency note on ARM:
#    - Python3, PyQt6 (or PyQt5), mutagen, numpy, GStreamer
#      must be installed on the target system.
#    - The AppImage runtime (squashfuse-based) exists and works on ARM.
# =============================================================================

# ── Internal helper: download/verify appimagetool ────────────────────────────
# Output: writes the tool path to stdout
#
# NOTE: the x86_64 appimagetool is always used, whatever the target arch is.
# appimagetool supports cross-arch packaging; the target arch is given by the
# ARCH env variable (set inside _build_single_appimage).
# ARM/i686 binaries cannot run on an x86_64 host (Exec format error).
_get_appimagetool() {
    local TOOL="${SOURCE_DIR}/appimagetool-x86_64.AppImage"
    if [[ ! -x "${TOOL}" ]]; then
        log "Downloading appimagetool (x86_64)..." >&2
        curl -L --fail \
            -o "${TOOL}" \
            "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" || \
            die "Could not download appimagetool.\n   URL: https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
        chmod +x "${TOOL}"
        info "appimagetool saved: ${TOOL}" >&2
    else
        info "appimagetool already present: ${TOOL} ✓" >&2
    fi
    echo "${TOOL}"
}

# ── Internal helper: uname -m → AppImage ARCH tag ───────────────────────────
# AppImageKit expects its own tags in the ARCH env variable (unlike rpm/deb).
_uname_to_appimage_arch() {
    case "$1" in
        x86_64)          echo "x86_64"  ;;
        aarch64)         echo "aarch64" ;;
        armv7l|armv7*)   echo "armhf"   ;;
        armv6l|armv6*)   echo "armhf"   ;;   # armv6 uses the armhf tool as well
        i?86)            echo "i686"    ;;
        *)               echo "$1"      ;;   # unknown → try it as-is
    esac
}

# ── Internal helper: AppImage ARCH tag → appimagetool ARCH env value ─────────
# appimagetool extract_arch_from_text() only accepts specific strings:
#   "x86_64"      → x86_64
#   "i686" etc.   → i386 family (i686 matches)
#   "arm"         → armhf (32-bit ARM)
#   "arm_aarch64" → aarch64
# The "aarch64" and "armhf" tags we use in file names do not pass directly.
_arch_to_appimage_env() {
    case "$1" in
        x86_64)  echo "x86_64"      ;;
        aarch64) echo "arm_aarch64" ;;
        armhf)   echo "arm"         ;;
        i686)    echo "i686"        ;;
        *)       echo "$1"          ;;
    esac
}

# ── Internal helper: build AppDir + package AppImage ─────────────────────────
# $1 = target AppImage ARCH tag (x86_64, aarch64, armhf, i686)
_build_single_appimage() {
    # The whole function writes to stderr; only the final echo (the file path) goes to stdout.
    # This way OUT_AI=$(_build_single_appimage ...) captures a clean path.
    exec 3>&1 1>&2

    local TARGET_ARCH="$1"

    local APPDIR="${SOURCE_DIR}/AppDir-${TARGET_ARCH}"
    log "Creating AppDir (${TARGET_ARCH}): ${APPDIR}"
    rm -rf "${APPDIR}"
    mkdir -p \
        "${APPDIR}/usr/bin" \
        "${APPDIR}/usr/lib/${APP_NAME}" \
        "${APPDIR}/usr/share/applications" \
        "${APPDIR}/usr/share/icons/hicolor/scalable/apps" \
        "${APPDIR}/usr/share/metainfo" \
        "${APPDIR}/usr/share/fonts/NotoMusic"

    # ── Place files ───────────────────────────────────────────────────────────
    # NOTE: voidpulse.py is no longer a single file — after the refactor constants.py
    # and the other helper modules live in separate files. Copy them all, or
    # errors like "ModuleNotFoundError: No module named 'constants'" appear.
    shopt -s nullglob
    local _py_modules=("${SOURCE_DIR}"/*.py)
    shopt -u nullglob
    [[ ${#_py_modules[@]} -eq 0 ]] && die "No .py files found in the source directory: ${SOURCE_DIR}"
    for _pyfile in "${_py_modules[@]}"; do
        install -Dm644 "${_pyfile}" "${APPDIR}/usr/lib/${APP_NAME}/$(basename "${_pyfile}")"
    done
    info "Python modules copied: ${#_py_modules[@]}"
    install -Dm644 "${SOURCE_DIR}/${APP_ID}.desktop" "${APPDIR}/usr/share/applications/${APP_ID}.desktop"
    install -Dm644 "${SOURCE_DIR}/${APP_ID}.svg"     "${APPDIR}/usr/share/icons/hicolor/scalable/apps/${APP_ID}.svg"
    install -Dm644 "${FONT_FILE}"                    "${APPDIR}/usr/share/fonts/NotoMusic/NotoMusic-Regular.ttf"

    # AppDir root requirements
    cp "${SOURCE_DIR}/${APP_ID}.svg"     "${APPDIR}/${APP_ID}.svg"
    ln -sf "${APP_ID}.svg"               "${APPDIR}/.DirIcon"
    cp "${SOURCE_DIR}/${APP_ID}.desktop" "${APPDIR}/${APP_ID}.desktop"

    # ── AppStream metainfo ────────────────────────────────────────────────────
    cat > "${APPDIR}/usr/share/metainfo/${APP_ID}.appdata.xml" << APPDATA
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>org.voidpulse.VoidPulse</id>
  <metadata_license>CC0-1.0</metadata_license>
  <project_license>GPL-3.0-or-later</project_license>
  <name>VoidPulse</name>
  <summary>Touch and OLED friendly advanced music player</summary>
  <description>
    <p>Touch and OLED friendly advanced music player</p>
  </description>
  <launchable type="desktop-id">org.voidpulse.VoidPulse.desktop</launchable>
  <releases>
    <release version="${APP_VERSION}" date="$(date +%Y-%m-%d)"/>
  </releases>
  <url type="homepage">${APP_URL}</url>
  <developer_name>${APP_MAINTAINER}</developer_name>
  <content_rating type="oars-1.1"/>
</component>
APPDATA

    # ── AppRun — works on every architecture, ARM included ────────────────────
    cat > "${APPDIR}/AppRun" << 'APPRUN'
#!/bin/sh
# VoidPulse AppImage entry point — x86_64 / aarch64 / armhf / i686
HERE="$(dirname "$(readlink -f "${0}")")"
export PYTHONPATH="${HERE}/usr/lib/voidpulse:${PYTHONPATH:-}"
export XDG_DATA_DIRS="${HERE}/usr/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
export FONTCONFIG_PATH="${HERE}/usr/share/fonts:${FONTCONFIG_PATH:-}"
# Add the GStreamer plugin path too (falls back to the system install)
export GST_PLUGIN_PATH="${HERE}/usr/lib/gstreamer-1.0:${GST_PLUGIN_PATH:-}"
exec python3 "${HERE}/usr/lib/voidpulse/voidpulse.py" "$@"
APPRUN
    chmod +x "${APPDIR}/AppRun"

    # ── Obtain and run appimagetool ───────────────────────────────────────────
    local APPIMAGETOOL
    APPIMAGETOOL=$(_get_appimagetool "${TARGET_ARCH}")

    local OUT_APPIMAGE="${SOURCE_DIR}/VoidPulse-${APP_VERSION}-${TARGET_ARCH}.AppImage"
    log "Creating AppImage: $(basename "${OUT_APPIMAGE}")"

    # The appimagetool ARCH env value differs from the file-name tag:
    #   aarch64 → arm_aarch64 | armhf → arm | i686 → i686 | x86_64 → x86_64
    # APPIMAGE_EXTRACT_AND_RUN=1: extracts to /tmp and runs without needing FUSE.
    local ARCH_ENV
    ARCH_ENV=$(_arch_to_appimage_env "${TARGET_ARCH}")
    export ARCH="${ARCH_ENV}"
    APPIMAGE_EXTRACT_AND_RUN=1 "${APPIMAGETOOL}" \
        --no-appstream \
        "${APPDIR}" \
        "${OUT_APPIMAGE}" || \
        die "AppImage could not be created (${TARGET_ARCH}). Inspect the appimagetool output."
    unset ARCH

    chmod +x "${OUT_APPIMAGE}"
    sign_appimage "${OUT_APPIMAGE}"

    local AI_MB
    AI_MB=$(du -sh "${OUT_APPIMAGE}" | cut -f1)
    info "  ✓ ${OUT_APPIMAGE}  (${AI_MB})"

    rm -rf "${APPDIR}"
    echo "${OUT_APPIMAGE}" >&3  # return the file path to the caller (original stdout)
    exec 3>&-
}

# =============================================================================
#  build_appimage — single arch (current system or APPIMAGE_TARGET_ARCH)
# =============================================================================
build_appimage() {
    sep
    echo -e "${BOLD}  VoidPulse → AppImage Builder v8${NC}"
    sep

    check_sources

    log "Checking system tools..."
    local missing_tools=()
    command -v python3 &>/dev/null || missing_tools+=("python3")
    command -v curl    &>/dev/null || missing_tools+=("curl")
    command -v desktop-file-validate &>/dev/null || \
        warn "desktop-file-validate not found, validation will be skipped."
    [[ ${#missing_tools[@]} -gt 0 ]] && \
        die "Missing tools:\n$(printf '   • %s\n' "${missing_tools[@]}")"
    info "Tools ready ✓"

    # Target architecture: environment variable > uname -m
    local TARGET_ARCH
    if [[ -n "${APPIMAGE_TARGET_ARCH:-}" ]]; then
        TARGET_ARCH="${APPIMAGE_TARGET_ARCH}"
        info "Target architecture (environment variable): ${TARGET_ARCH}"
    else
        TARGET_ARCH=$(_uname_to_appimage_arch "$(uname -m)")
        info "Target architecture (auto-detected): ${TARGET_ARCH}"
    fi

    download_font

    local OUT_APPIMAGE
    OUT_APPIMAGE=$(_build_single_appimage "${TARGET_ARCH}")

    local AI_MB
    AI_MB=$(du -sh "${OUT_APPIMAGE}" | cut -f1)
    sep
    echo -e "${GREEN}${BOLD}  ✓ AppImage ready!${NC}"
    sep
    echo -e "  ${BOLD}Dosya   :${NC} ${OUT_APPIMAGE}  (${AI_MB})"
    echo -e "  ${BOLD}Arch    :${NC} ${TARGET_ARCH}"
    echo -e "  ${BOLD}Run     :${NC} chmod +x $(basename "${OUT_APPIMAGE}") && ./$(basename "${OUT_APPIMAGE}")"
    echo -e "  ${BOLD}Note    :${NC} Python3, PyQt6/5, mutagen, numpy and GStreamer must be installed on the target system."
    echo -e "  ${BOLD}Hint    :${NC} Other architecture: APPIMAGE_TARGET_ARCH=aarch64 $0 appimage"
    sep
}

# =============================================================================
#  build_appimage_multiarch — build AppImages for every ARM + x86 architecture
#  Architectures: x86_64 · aarch64 · armhf · i686
# =============================================================================
build_appimage_multiarch() {
    sep
    echo -e "${BOLD}  VoidPulse → AppImage Multi-Arch Builder v8${NC}"
    sep

    check_sources

    log "Checking system tools..."
    local missing_tools=()
    command -v python3 &>/dev/null || missing_tools+=("python3")
    command -v curl    &>/dev/null || missing_tools+=("curl")
    [[ ${#missing_tools[@]} -gt 0 ]] && \
        die "Missing tools:\n$(printf '   • %s\n' "${missing_tools[@]}")"
    info "Tools ready ✓"

    # ── Target selection ──────────────────────────────────────────────────────
    local SELECTED_AI_ARCHES=()
    if [[ -n "${APPIMAGE_ARCH_TARGETS:-}" ]]; then
        IFS=',' read -ra SELECTED_AI_ARCHES <<< "${APPIMAGE_ARCH_TARGETS}"
    else
        echo ""
        echo -e "  Which architectures should the AppImage be built for?"
        echo -e "  ${BOLD}0)${NC} Hepsi (x86_64 aarch64 armhf i686)"
        echo -e "  ${BOLD}1)${NC} x86_64   — Desktop / server"
        echo -e "  ${BOLD}2)${NC} aarch64  — ARM 64-bit (Raspberry Pi 4/5, Pine64, phones)"
        echo -e "  ${BOLD}3)${NC} armhf    — ARM 32-bit hard-float (PinePhone Pro, Librem 5, older SBCs)"
        echo -e "  ${BOLD}4)${NC} i686     — x86 32-bit (older PCs)"
        echo ""
        read -rp "  Selection [0-4], comma-separated (e.g. 2,3): " ai_choice

        if [[ "${ai_choice}" == "0" || "${ai_choice}" == "all" ]]; then
            SELECTED_AI_ARCHES=(x86_64 aarch64 armhf i686)
        else
            IFS=',' read -ra _tokens <<< "${ai_choice}"
            for t in "${_tokens[@]}"; do
                t="${t// /}"
                case "${t}" in
                    1) SELECTED_AI_ARCHES+=(x86_64)  ;;
                    2) SELECTED_AI_ARCHES+=(aarch64) ;;
                    3) SELECTED_AI_ARCHES+=(armhf)   ;;
                    4) SELECTED_AI_ARCHES+=(i686)    ;;
                    x86_64|aarch64|armhf|i686) SELECTED_AI_ARCHES+=("${t}") ;;
                    *) warn "Skipped unknown architecture: ${t}" ;;
                esac
            done
        fi
    fi

    [[ ${#SELECTED_AI_ARCHES[@]} -eq 0 ]] && die "No architecture selected."
    info "Target architectures: ${SELECTED_AI_ARCHES[*]}"

    download_font

    local BUILT_AIS=()
    for TARGET_ARCH in "${SELECTED_AI_ARCHES[@]}"; do
        sep
        local OUT_AI
        OUT_AI=$(_build_single_appimage "${TARGET_ARCH}")
        BUILT_AIS+=("${OUT_AI}")
    done

    sep
    echo -e "${GREEN}${BOLD}  ✓ Multi-arch AppImages ready!${NC}"
    sep
    for _ai in "${BUILT_AIS[@]}"; do
        local _sz
        _sz=$(du -sh "${_ai}" | cut -f1)
        echo -e "  ${BOLD}Dosya:${NC} ${_ai}  (${_sz})"
    done
    echo ""
    echo -e "  ${BOLD}Run     :${NC} chmod +x VoidPulse-*.AppImage && ./VoidPulse-*-aarch64.AppImage"
    echo -e "  ${BOLD}Note    :${NC} Python3, PyQt6/5, mutagen, numpy and GStreamer must be installed on the target system."
    echo -e "  ${BOLD}Hint    :${NC} To copy to an ARM device:"
    echo -e "              scp VoidPulse-${APP_VERSION}-aarch64.AppImage user@pihost:~/"
    echo -e "              ssh user@pihost 'chmod +x ~/VoidPulse-*.AppImage && ~/VoidPulse-*.AppImage'"
    sep
}

# =============================================================================
#  Menu / argument handling
# =============================================================================
show_menu() {
    sep
    echo -e "${BOLD}  VoidPulse — Universal Package Builder v8${NC}"
    sep
    echo -e "  Which package do you want to build?"
    echo -e ""
    echo -e "  ${BOLD}1)${NC} flatpak           — Sandboxed universal Linux package"
    echo -e "  ${BOLD}2)${NC} deb               — Debian / Ubuntu / Linux Mint (current architecture)"
    echo -e "  ${BOLD}3)${NC} deb-multiarch     — DEB: arm64, armhf, armel, riscv64, loong64, amd64"
    echo -e "  ${BOLD}4)${NC} rpm               — Fedora / openSUSE / RHEL / CentOS (ARM auto-detect)"
    echo -e "  ${BOLD}5)${NC} apk               — Alpine Linux"
    echo -e "  ${BOLD}6)${NC} appimage          — Portable single file (current architecture)"
    echo -e "  ${BOLD}7)${NC} appimage-multiarch — AppImage: x86_64, aarch64, armhf, i686"
    echo -e "  ${BOLD}8)${NC} all               — Build everything"
    echo -e "  ${BOLD}q)${NC} Quit"
    echo ""
    read -rp "  Selection [1-8/q], comma-separated (e.g. 3,6,7): " choice

    # q / Q → quit immediately
    [[ "${choice}" =~ ^[qQ]$ ]] && { echo "Quit."; exit 0; }

    # Turn the comma-separated list into an array via IFS
    IFS=',' read -ra selections <<< "${choice}"

    # Resolve each token and run them in order (a seen-set avoids duplicates)
    declare -A _seen=()
    for token in "${selections[@]}"; do
        token="${token// /}"  # strip spaces
        # "8" or "all" → expand
        if [[ "${token}" == "8" || "${token}" == "all" ]]; then
            for t in 1 2 3 4 5 6 7; do
                [[ -v _seen[$t] ]] && continue
                _seen[$t]=1
                case "$t" in
                    1) build_flatpak            ;;
                    2) build_deb               ;;
                    3) build_deb_multiarch     ;;
                    4) build_rpm               ;;
                    5) build_apk               ;;
                    6) build_appimage          ;;
                    7) build_appimage_multiarch ;;
                esac
            done
            break
        fi
        [[ -v _seen[$token] ]] && continue
        _seen[$token]=1
        case "${token}" in
            1|flatpak)            build_flatpak            ;;
            2|deb)                build_deb               ;;
            3|deb-multiarch)      build_deb_multiarch     ;;
            4|rpm)                build_rpm               ;;
            5|apk)                build_apk               ;;
            6|appimage)           build_appimage          ;;
            7|appimage-multiarch) build_appimage_multiarch ;;
            *) die "Invalid selection: ${token}" ;;
        esac
    done
}

# ── GPG setup (after the functions are defined) ───────────────────────────────
setup_gpg

# ── APK is skipped on openSUSE — the guard inside build_apk() handles it ──────
# When run with the all argument, the APK step is skipped automatically on openSUSE.

# ── Entry point ───────────────────────────────────────────────────────────────
case "${1:-menu}" in
    flatpak)             build_flatpak            ;;
    deb)                 build_deb               ;;
    deb-multiarch)       build_deb_multiarch     ;;
    rpm)                 build_rpm               ;;
    apk)                 build_apk               ;;
    appimage)            build_appimage          ;;
    appimage-multiarch)  build_appimage_multiarch ;;
    all)
        build_flatpak
        build_deb
        build_deb_multiarch
        build_rpm
        build_apk
        build_appimage
        build_appimage_multiarch
        ;;
    menu)    show_menu     ;;
    *)
        echo -e "Usage: $0 [flatpak|deb|deb-multiarch|rpm|apk|appimage|appimage-multiarch|all]"
        echo -e "With no argument, an interactive menu is shown."
        exit 1
        ;;
esac
