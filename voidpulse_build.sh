#!/usr/bin/env bash
# =============================================================================
#  VoidPulse — Universal Package Builder v8
#  Desteklenen formatlar: flatpak · deb · deb-multiarch · rpm · apk · appimage · appimage-multiarch
#
#  Output örnekleri:
#          org.voidpulse.VoidPulse.flatpak
#          voidpulse_1.0.0_amd64.deb
#          voidpulse_1.0.0_arm64.deb       ┐
#          voidpulse_1.0.0_armhf.deb       │ deb-multiarch
#          voidpulse_1.0.0_armel.deb       │
#          voidpulse_1.0.0_riscv64.deb     │
#          voidpulse_1.0.0_loong64.deb     ┘
#          voidpulse-1.0.0-1.noarch.rpm    (ARM otomatik algılama; --target ile hedef seçilir)
#          voidpulse-1.0.0-r0.apk          (yalnızca Alpine Linux)
#          VoidPulse-1.0.0-x86_64.AppImage
#          VoidPulse-1.0.0-aarch64.AppImage ┐
#          VoidPulse-1.0.0-armhf.AppImage   │ appimage-multiarch
#          VoidPulse-1.0.0-i686.AppImage    ┘
#
#  Usage : ./build-packages.sh [flatpak|deb|deb-multiarch|rpm|apk|appimage|appimage-multiarch|all]
#          Argüman verilmezse interaktif menü açılır.
#
#  Ortam değişkenleri (override):
#    DEB_ARCH_TARGETS="arm64,armhf"          → deb-multiarch hedef mimarileri
#    RPM_TARGET_ARCH=aarch64                  → rpm hedef mimari
#    APPIMAGE_TARGET_ARCH=aarch64             → appimage tek hedef mimari
#    APPIMAGE_ARCH_TARGETS="aarch64,armhf"   → appimage-multiarch hedefleri
#
#  openSUSE: rpm hedefi openSUSE paket adlarını otomatik kullanır.
#  Alpine  : apk hedefi Alpine dışı sistemlerde otomatik atlanır.
# =============================================================================
set -euo pipefail
IFS=$'\n\t'

# set -e aktifken beklenmedik çıkışları yakala ve raporla
trap 'echo -e "\033[0;31m[✗] HATA: Script satır ${LINENO} üzerinde başarısız oldu (exit code: $?)\033[0m" >&2' ERR

# flatpak-builder --user root olarak çalışmamalı
[[ "$(id -u)" == "0" ]] && { echo -e "\033[0;31m[✗] HATA: Bu scripti root olarak çalıştırmayın!\033[0m" >&2; exit 1; }

# ── Renkler ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
log()  { echo -e "${GREEN}[+]${NC} $*"; }
info() { echo -e "${CYAN}[i]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
die()  { echo -e "${RED}[✗] HATA:${NC} $*" >&2; exit 1; }
sep()  { echo -e "${BOLD}────────────────────────────────────────────${NC}"; }

# ── Sabitler ──────────────────────────────────────────────────────────────────
APP_ID="org.voidpulse.VoidPulse"
APP_NAME="voidpulse"
APP_RELEASE="1"
APP_DESC="Touch ve OLED dostu gelişmiş müzik çalar"
APP_LICENSE="GPL-3.0-or-later"
APP_URL="https://github.com/Yavuz-Kagan-Yadigar/VoidPulse"
APP_MAINTAINER="Yavuz"

# ── Versiyon sorgusu ──────────────────────────────────────────────────────────
sep
echo -e "${BOLD}  VoidPulse — Universal Package Builder v8${NC}"
sep
while true; do
    read -rp "  Versiyon numarası girin (örn. 1.2.0): " APP_VERSION
    [[ "${APP_VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] && break
    warn "Geçersiz format. Lütfen X.Y.Z biçiminde girin (örn. 1.2.0)."
done
info "Versiyon: ${APP_VERSION} ✓"
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

# ── Yardımcı: kaynak dosyaları kontrol et ────────────────────────────────────
check_sources() {
    log "Kaynak dosyaları kontrol ediliyor..."
    for f in voidpulse.py "${APP_ID}.desktop" "${APP_ID}.svg"; do
        [[ -f "${SOURCE_DIR}/${f}" ]] || \
            die "Eksik dosya: ${f}\n   Scripti proje dizininden çalıştırın."
    done
    info "Tüm kaynak dosyalar mevcut ✓"
}

# ── Yardımcı: NotoMusic fontunu indir ────────────────────────────────────────
download_font() {
    command -v curl &>/dev/null || die "curl bulunamadı. Lütfen curl kurun."
    log "NotoMusic fontu indiriliyor..."
    if [[ ! -f "${FONT_FILE}" ]]; then
        curl -L --fail -o "${FONT_FILE}" "${FONT_URL}" || \
            die "NotoMusic fontu indirilemedi: ${FONT_URL}"
        info "Font kaydedildi: ${FONT_FILE}"
    else
        info "Font zaten mevcut: ${FONT_FILE} ✓"
    fi
}

# ── Yardımcı: sahiplik düzelt ─────────────────────────────────────────────────
fix_ownership() {
    for _f in appdata.xml voidpulse-launcher "${APP_ID}.yml" \
              "${APP_ID}-build" "${APP_ID}-repo" "${APP_ID}.flatpak" \
              ".flatpak-builder" "NotoMusic-Regular.ttf"; do
        [[ -e "${SOURCE_DIR}/${_f}" ]] && \
            sudo chown -R "$(id -u):$(id -g)" "${SOURCE_DIR}/${_f}" 2>/dev/null || true
    done
}


# ── Yardımcı: GPG anahtar kontrolü ve imzalama ───────────────────────────────
# GPG_KEY_ID: boşsa imzalama atlanır (uyarı verilir).
GPG_KEY_ID=""

setup_gpg() {
    # Ortam değişkeni veya ~/.rpmmacros'tan anahtar ID'si al
    if [[ -z "${GPG_KEY_ID}" ]]; then
        # Sistemdeki ilk gizli anahtarı otomatik seç
        GPG_KEY_ID=$(gpg --list-secret-keys --with-colons 2>/dev/null             | awk -F: '/^sec/{print $5; exit}') || true
    fi

    if [[ -z "${GPG_KEY_ID}" ]]; then
        warn "GPG gizli anahtarı bulunamadı — imzalama atlanacak."
        warn "Anahtar oluşturmak için: gpg --full-generate-key"
        warn "Sonra GPG_KEY_ID=<key-id> değişkeniyle tekrar çalıştırın."
        GPG_KEY_ID=""
        return 0
    fi

    info "GPG imzalama anahtarı: ${GPG_KEY_ID} ✓"

    # RPM imzalama için ~/.rpmmacros gerekli
    local RPMM="${HOME}/.rpmmacros"
    if ! grep -q "%_gpg_name" "${RPMM}" 2>/dev/null; then
        echo "%_gpg_name ${GPG_KEY_ID}" >> "${RPMM}"
        info "~/.rpmmacros güncellendi: %_gpg_name ${GPG_KEY_ID}"
    fi
}

sign_rpm() {
    local rpm_file="$1"
    [[ -z "${GPG_KEY_ID}" ]] && { warn "GPG anahtarı yok — RPM imzalanmadı."; return 0; }
    command -v rpm &>/dev/null || { warn "rpm bulunamadı — imzalama atlandı."; return 0; }
    log "RPM imzalanıyor: $(basename "${rpm_file}")"
    rpm --addsign "${rpm_file}" || warn "RPM imzalama başarısız — paket imzasız."
}

sign_deb() {
    local deb_file="$1"
    [[ -z "${GPG_KEY_ID}" ]] && { warn "GPG anahtarı yok — DEB imzalanmadı."; return 0; }
    if command -v dpkg-sig &>/dev/null; then
        log "DEB imzalanıyor (dpkg-sig): $(basename "${deb_file}")"
        dpkg-sig --sign builder -k "${GPG_KEY_ID}" "${deb_file}" ||             warn "DEB imzalama başarısız — paket imzasız."
    elif command -v debsigs &>/dev/null; then
        log "DEB imzalanıyor (debsigs): $(basename "${deb_file}")"
        debsigs --sign=origin -k "${GPG_KEY_ID}" "${deb_file}" ||             warn "DEB imzalama başarısız — paket imzasız."
    else
        warn "dpkg-sig/debsigs bulunamadı — DEB imzalanmadı."
        warn "openSUSE: sudo zypper install dpkg-sig"
        warn "Debian  : sudo apt install dpkg-sig"
    fi
}

sign_appimage() {
    local ai_file="$1"
    [[ -z "${GPG_KEY_ID}" ]] && { warn "GPG anahtarı yok — AppImage imzalanmadı." >&2; return 0; }
    log "AppImage imzalanıyor: $(basename "${ai_file}")" >&2
    gpg --batch --yes --detach-sign --armor         -u "${GPG_KEY_ID}" "${ai_file}" ||         warn "AppImage imzalama başarısız." >&2
    [[ -f "${ai_file}.asc" ]] && info "İmza dosyası: ${ai_file}.asc" >&2
}

sign_flatpak_repo() {
    local repo_dir="$1"
    [[ -z "${GPG_KEY_ID}" ]] && { warn "GPG anahtarı yok — Flatpak repo imzalanmadı."; return 0; }
    command -v flatpak &>/dev/null || return 0
    log "Flatpak repo imzalanıyor..."
    flatpak build-sign "${repo_dir}" --gpg-sign="${GPG_KEY_ID}" ||         warn "Flatpak repo imzalama başarısız."
    flatpak build-update-repo "${repo_dir}" --gpg-sign="${GPG_KEY_ID}" ||         warn "Flatpak repo güncelleme başarısız."
}

# =============================================================================
#  FLATPAK
# =============================================================================
build_flatpak() {
    sep
    echo -e "${BOLD}  VoidPulse → Flatpak Builder v8${NC}"
    sep

    check_sources

    log "Sistem araçları kontrol ediliyor..."
    command -v flatpak-builder &>/dev/null || \
        die "flatpak-builder bulunamadı. Paket yöneticinizle kurun."

    fix_ownership

    log "Önceki derleme artefaktları temizleniyor..."
    for _item in "${BUILD_DIR}" "${REPO_DIR}" "${BUNDLE}" \
                 "${SOURCE_DIR}/appdata.xml" "${SOURCE_DIR}/voidpulse-launcher" \
                 "${MANIFEST}" "${SOURCE_DIR}/.flatpak-builder" \
                 "${FONT_FILE}"; do
        if [[ -e "${_item}" ]]; then
            rm -rf "${_item}"
            info "Silindi: ${_item}"
        fi
    done

    log "Flathub remote ekleniyor..."
    flatpak remote-add --user --if-not-exists flathub \
        https://flathub.org/repo/flathub.flatpakrepo 2>/dev/null || true

    for pkg in "${RUNTIME_NAME}//${RUNTIME_VER}" "${SDK_NAME}//${RUNTIME_VER}"; do
        if ! flatpak info --user "${pkg}" &>/dev/null && \
           ! flatpak info        "${pkg}" &>/dev/null; then
            log "Kuruluyor: ${pkg}"
            flatpak install -y --user flathub "${pkg}"
        else
            info "Zaten kurulu: ${pkg} ✓"
        fi
    done

    download_font

    log "AppStream metainfo oluşturuluyor..."
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

    log "Başlatıcı sarmalayıcı oluşturuluyor..."
    cat > "${SOURCE_DIR}/voidpulse-launcher" << 'LAUNCHER'
#!/bin/bash
exec python3 /app/lib/voidpulse/voidpulse.py "$@"
LAUNCHER
    chmod +x "${SOURCE_DIR}/voidpulse-launcher"

    log "Manifest yazılıyor: ${MANIFEST}"
    # voidpulse.py artık tek dosya değil — refactor sonrası constants.py ve
    # diğer yardımcı modüller ayrı dosyalarda. Flatpak manifestindeki
    # build-commands / sources listelerini tüm .py dosyalarını kapsayacak
    # şekilde dinamik olarak üret.
    shopt -s nullglob
    local _py_modules=("${SOURCE_DIR}"/*.py)
    shopt -u nullglob
    [[ ${#_py_modules[@]} -eq 0 ]] && die "Kaynak dizinde hiç .py dosyası bulunamadı: ${SOURCE_DIR}"
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
    info "Manifeste eklenen Python modülleri: ${#_py_modules[@]} adet"

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
    log "Flatpak derleniyor (PyQt6 önbellekteyse hızlı)..."
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
    log "Bundle oluşturuluyor: ${BUNDLE}"
    log "  (~250 MB içerik → 1-2 dakika)"

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
    echo -e "${GREEN}${BOLD}  ✓ Flatpak hazır!${NC}"
    sep
    echo -e "  ${BOLD}Bundle  :${NC} ${BUNDLE}  (${BUNDLE_MB})"
    echo -e "  ${BOLD}Kur     :${NC} flatpak install --user ${BUNDLE}"
    echo -e "  ${BOLD}Çalıştır:${NC} flatpak run ${APP_ID}"
    echo -e "  ${BOLD}Kaldır  :${NC} flatpak uninstall --user ${APP_ID}"
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

    # ── Araç kontrolü ──────────────────────────────────────────────────────────
    log "Sistem araçları kontrol ediliyor..."

    # openSUSE algılama
    local IS_OPENSUSE_DEB=0
    if [[ -f /etc/os-release ]] && grep -qiE "opensuse|suse" /etc/os-release; then
        IS_OPENSUSE_DEB=1
        warn "openSUSE sistemi algılandı — DEB hedefi yalnızca Debian/Ubuntu için önerilir."
        warn "openSUSE için RPM hedefini kullanın: $0 rpm"
    fi

    local missing_tools=()
    command -v dpkg-deb  &>/dev/null || missing_tools+=("dpkg-deb")
    command -v fakeroot  &>/dev/null || missing_tools+=("fakeroot")
    if [[ ${#missing_tools[@]} -gt 0 ]]; then
        if [[ "${IS_OPENSUSE_DEB}" -eq 1 ]]; then
            die "Eksik araçlar:\n$(printf '   • %s\n' "${missing_tools[@]}")\n   openSUSE : sudo zypper install dpkg fakeroot\n   Not      : openSUSE için RPM hedefi önerilir: $0 rpm"
        else
            die "Eksik araçlar:\n$(printf '   • %s\n' "${missing_tools[@]}")\n   Kurun: sudo apt install dpkg-dev fakeroot"
        fi
    fi
    info "Araçlar hazır ✓"

    download_font

    # ── Dizin yapısı ──────────────────────────────────────────────────────────
    local ARCH
    if command -v dpkg &>/dev/null; then
        ARCH=$(dpkg --print-architecture 2>/dev/null || echo "amd64")
    else
        # dpkg yok (openSUSE vb.) — makineyi uname'den çöz
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

    log "Derleme dizini hazırlanıyor: ${PKG_DIR}"
    rm -rf "${SOURCE_DIR}/deb-build"
    mkdir -p \
        "${PKG_DIR}/DEBIAN" \
        "${PKG_DIR}/usr/bin" \
        "${PKG_DIR}/usr/lib/${APP_NAME}" \
        "${PKG_DIR}/usr/share/applications" \
        "${PKG_DIR}/usr/share/icons/hicolor/scalable/apps" \
        "${PKG_DIR}/usr/share/metainfo" \
        "${PKG_DIR}/usr/share/fonts/truetype/NotoMusic"

    # ── Dosyaları yerleştir ───────────────────────────────────────────────────
    log "Dosyalar yerleştiriliyor..."
    shopt -s nullglob
    _py_modules=("${SOURCE_DIR}"/*.py)
    shopt -u nullglob
    [[ ${#_py_modules[@]} -eq 0 ]] && die "Kaynak dizinde hiç .py dosyası bulunamadı: ${SOURCE_DIR}"
    for _pyfile in "${_py_modules[@]}"; do
        install -Dm644 "${_pyfile}" "${PKG_DIR}/usr/lib/${APP_NAME}/$(basename "${_pyfile}")"
    done
    info "Kopyalanan Python modülleri: ${#_py_modules[@]} adet"
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

    # ── Başlatıcı ─────────────────────────────────────────────────────────────
    cat > "${PKG_DIR}/usr/bin/${APP_NAME}" << 'LAUNCHER'
#!/bin/bash
exec python3 /usr/lib/voidpulse/voidpulse.py "$@"
LAUNCHER
    chmod 755 "${PKG_DIR}/usr/bin/${APP_NAME}"

    # ── DEBIAN/control ────────────────────────────────────────────────────────
    log "DEBIAN/control yazılıyor..."
    cat > "${PKG_DIR}/DEBIAN/control" << CONTROL
Package: ${APP_NAME}
Version: ${APP_VERSION}
Architecture: ${ARCH}
Maintainer: ${APP_MAINTAINER}
Description: ${APP_DESC}
 Touch ve OLED dostu gelişmiş müzik çalar.
 Wayland, GNOME/KDE entegrasyonu, PipeWire, GStreamer
 spektrum görselleştirme, MPRIS2 D-Bus ve bit-perfect
 ses desteği sunar.
Depends: python3 (>= 3.10), python3-pyqt6 | python3-qt6,
 python3-mutagen, python3-numpy, gstreamer1.0-plugins-good,
 gstreamer1.0-plugins-bad, gstreamer1.0-pulseaudio
Recommends: fonts-noto-music, python3-soxr
Homepage: ${APP_URL}
Section: sound
Priority: optional
CONTROL

    # ── DEBIAN/postinst — font önbelleği güncelle ────────────────────────────
    cat > "${PKG_DIR}/DEBIAN/postinst" << 'POSTINST'
#!/bin/sh
set -e
fc-cache -f /usr/share/fonts/truetype/NotoMusic/ 2>/dev/null || true
update-desktop-database /usr/share/applications/ 2>/dev/null || true
POSTINST
    chmod 755 "${PKG_DIR}/DEBIAN/postinst"

    # ── DEBIAN/postrm — temizlik ──────────────────────────────────────────────
    cat > "${PKG_DIR}/DEBIAN/postrm" << 'POSTRM'
#!/bin/sh
set -e
fc-cache -f 2>/dev/null || true
update-desktop-database /usr/share/applications/ 2>/dev/null || true
POSTRM
    chmod 755 "${PKG_DIR}/DEBIAN/postrm"

    # ── Boyutları hesapla & paket oluştur ─────────────────────────────────────
    local INSTALLED_SIZE
    INSTALLED_SIZE=$(du -sk "${PKG_DIR}" | cut -f1)
    echo "Installed-Size: ${INSTALLED_SIZE}" >> "${PKG_DIR}/DEBIAN/control"

    log "DEB paketi oluşturuluyor..."
    fakeroot dpkg-deb --build "${PKG_DIR}" "${OUT_DEB}"
    sign_deb "${OUT_DEB}"

    local DEB_MB
    DEB_MB=$(du -sh "${OUT_DEB}" | cut -f1)
    sep
    echo -e "${GREEN}${BOLD}  ✓ DEB paketi hazır!${NC}"
    sep
    echo -e "  ${BOLD}Paket   :${NC} ${OUT_DEB}  (${DEB_MB})"
    echo -e "  ${BOLD}Kur     :${NC} sudo apt install ./${PKG_NAME}.deb"
    echo -e "  ${BOLD}Çalıştır:${NC} ${APP_NAME}"
    echo -e "  ${BOLD}Kaldır  :${NC} sudo apt remove ${APP_NAME}"
    sep

    rm -rf "${SOURCE_DIR}/deb-build"
}

# =============================================================================
#  DEB — Çoklu Mimari (arm64 · armhf · armel · riscv64 · loong64 · amd64)
#  Telefon ve gömülü hedefler dahil tüm DEB mimarileri için paket üretir.
#  Cross-derleme gerekmez; uygulama Python (noarch) olduğundan yalnızca
#  DEBIAN/control'deki Architecture alanı değiştirilir.
# =============================================================================
build_deb_multiarch() {
    sep
    echo -e "${BOLD}  VoidPulse → DEB Multi-Arch Builder v8${NC}"
    sep

    check_sources

    # ── Araç kontrolü ──────────────────────────────────────────────────────────
    log "Sistem araçları kontrol ediliyor..."
    local IS_OPENSUSE_DEB=0
    if [[ -f /etc/os-release ]] && grep -qiE "opensuse|suse" /etc/os-release; then
        IS_OPENSUSE_DEB=1
        warn "openSUSE sistemi algılandı — DEB hedefi yalnızca Debian/Ubuntu için önerilir."
    fi

    local missing_tools=()
    command -v dpkg-deb &>/dev/null || missing_tools+=("dpkg-deb")
    command -v fakeroot &>/dev/null || missing_tools+=("fakeroot")
    if [[ ${#missing_tools[@]} -gt 0 ]]; then
        if [[ "${IS_OPENSUSE_DEB}" -eq 1 ]]; then
            die "Eksik araçlar:\n$(printf '   • %s\n' "${missing_tools[@]}")\n   openSUSE: sudo zypper install dpkg fakeroot"
        else
            die "Eksik araçlar:\n$(printf '   • %s\n' "${missing_tools[@]}")\n   Kurun: sudo apt install dpkg-dev fakeroot"
        fi
    fi
    info "Araçlar hazır ✓"

    download_font

    # ── Hedef mimariler ───────────────────────────────────────────────────────
    # DEB mimarisi adı → dpkg Architecture alanı değeri
    # Uygulama saf Python olduğundan tüm hedefler için tek kaynak kullanılır.
    #
    #  Mimari     | Açıklama
    #  -----------|----------------------------------------------------------
    #  amd64      | x86-64 masaüstü / sunucu
    #  arm64      | AArch64 — Raspberry Pi 4/5, Pine64, Apple Silicon (Linux)
    #  armhf      | ARMv7-A hard-float — PinePhone Pro, Librem 5, eski SBC'ler
    #  armel      | ARMv4T+ soft-float — çok eski ARM gömülü sistemler
    #  riscv64    | RISC-V 64-bit — VisionFive 2, StarFive SBC'ler
    #  loong64    | LoongArch 64-bit — Loongson 3A5000 ve üzeri
    declare -A DEB_ARCH_MAP=(
        [amd64]="amd64"
        [arm64]="arm64"
        [armhf]="armhf"
        [armel]="armel"
        [riscv64]="riscv64"
        [loong64]="loong64"
    )

    # Hedef seçimi: argüman verilmezse interaktif sor
    local SELECTED_ARCHES=()
    if [[ -n "${DEB_ARCH_TARGETS:-}" ]]; then
        # DEB_ARCH_TARGETS="arm64,armhf" gibi ortam değişkeniyle override
        IFS=',' read -ra SELECTED_ARCHES <<< "${DEB_ARCH_TARGETS}"
    else
        echo ""
        echo -e "  Hangi mimariler için DEB paketi oluşturulsun?"
        echo -e "  ${BOLD}0)${NC} Hepsi (amd64 arm64 armhf armel riscv64 loong64)"
        echo -e "  ${BOLD}1)${NC} amd64    — x86-64 masaüstü/sunucu"
        echo -e "  ${BOLD}2)${NC} arm64    — AArch64 (Raspberry Pi 4/5, Pine64, telefon)"
        echo -e "  ${BOLD}3)${NC} armhf    — ARMv7-A hard-float (PinePhone, Librem 5)"
        echo -e "  ${BOLD}4)${NC} armel    — ARMv4T+ soft-float (eski gömülü ARM)"
        echo -e "  ${BOLD}5)${NC} riscv64  — RISC-V 64-bit"
        echo -e "  ${BOLD}6)${NC} loong64  — LoongArch 64-bit"
        echo ""
        read -rp "  Seçim [0-6], virgülle ayır (örn. 2,3): " arch_choice

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
                    *) warn "Bilinmeyen mimari atlandı: ${t}" ;;
                esac
            done
        fi
    fi

    [[ ${#SELECTED_ARCHES[@]} -eq 0 ]] && die "Hiçbir mimari seçilmedi."
    info "Hedef mimariler: ${SELECTED_ARCHES[*]}"
    sep

    local BUILT_DEBS=()

    for TARGET_ARCH in "${SELECTED_ARCHES[@]}"; do
        sep
        log "DEB oluşturuluyor → ${TARGET_ARCH}"

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

        # ── Dosyaları yerleştir ───────────────────────────────────────────────
        shopt -s nullglob
        _py_modules=("${SOURCE_DIR}"/*.py)
        shopt -u nullglob
        [[ ${#_py_modules[@]} -eq 0 ]] && die "Kaynak dizinde hiç .py dosyası bulunamadı: ${SOURCE_DIR}"
        for _pyfile in "${_py_modules[@]}"; do
            install -Dm644 "${_pyfile}" "${PKG_DIR}/usr/lib/${APP_NAME}/$(basename "${_pyfile}")"
        done
        info "Kopyalanan Python modülleri: ${#_py_modules[@]} adet"
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

        # ── Başlatıcı ─────────────────────────────────────────────────────────
        cat > "${PKG_DIR}/usr/bin/${APP_NAME}" << 'LAUNCHER'
#!/bin/bash
exec python3 /usr/lib/voidpulse/voidpulse.py "$@"
LAUNCHER
        chmod 755 "${PKG_DIR}/usr/bin/${APP_NAME}"

        # ── Mimari'ye özgü bağımlılık notu ───────────────────────────────────
        # arm64/armhf/armel: telefon/SBC dağıtımları python3-pyqt6 yerine
        # python3-pyqt5 sunabilir; Depends'e her ikisi de eklendi.
        local PYQT_DEP="python3-pyqt6 | python3-qt6 | python3-pyqt5"
        local EXTRA_DEP=""
        case "${TARGET_ARCH}" in
            arm64|armhf|armel)
                # GPU/GLES kütüphanesi ARM cihazlarda işe yarar.
                # NOT: arch kısıtlaması ([arm64] vb.) yalnızca kaynak kontrol
                # dosyalarında geçerlidir; ikili .deb DEBIAN/control dosyasında
                # söz dizimi hatasına neden olur — burada kullanmayın.
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
 Touch ve OLED dostu gelişmiş müzik çalar.
 Wayland, GNOME/KDE entegrasyonu, PipeWire, GStreamer
 spektrum görselleştirme, MPRIS2 D-Bus ve bit-perfect
 ses desteği sunar.
Depends: python3 (>= 3.10), ${PYQT_DEP},
 python3-mutagen, python3-numpy, gstreamer1.0-plugins-good,
 gstreamer1.0-plugins-bad, gstreamer1.0-pulseaudio
Recommends: fonts-noto-music, python3-soxr
Homepage: ${APP_URL}
Section: sound
Priority: optional
CONTROL
        # Opsiyonel ek alan (boşsa atla)
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

        # ── Boyut & paket ─────────────────────────────────────────────────────
        local INSTALLED_SIZE
        INSTALLED_SIZE=$(du -sk "${PKG_DIR}" | cut -f1)
        echo "Installed-Size: ${INSTALLED_SIZE}" >> "${PKG_DIR}/DEBIAN/control"

        log "DEB paketi oluşturuluyor (${TARGET_ARCH})..."
        fakeroot dpkg-deb --build "${PKG_DIR}" "${OUT_DEB}"
        sign_deb "${OUT_DEB}"

        local DEB_MB
        DEB_MB=$(du -sh "${OUT_DEB}" | cut -f1)
        info "  ✓ ${OUT_DEB}  (${DEB_MB})"
        BUILT_DEBS+=("${OUT_DEB}")
    done

    rm -rf "${SOURCE_DIR}/deb-build"

    sep
    echo -e "${GREEN}${BOLD}  ✓ Çoklu mimari DEB paketleri hazır!${NC}"
    sep
    for _deb in "${BUILT_DEBS[@]}"; do
        local _sz
        _sz=$(du -sh "${_deb}" | cut -f1)
        echo -e "  ${BOLD}Paket:${NC} ${_deb}  (${_sz})"
    done
    echo ""
    echo -e "  ${BOLD}Kur     :${NC} sudo apt install ./<paket>.deb"
    echo -e "  ${BOLD}Çalıştır:${NC} ${APP_NAME}"
    echo -e "  ${BOLD}Kaldır  :${NC} sudo apt remove ${APP_NAME}"
    echo ""
    echo -e "  ${BOLD}Not     :${NC} arm64/armhf/armel paketlerini hedef cihaza SCP ile kopyalayın:"
    echo -e "            scp voidpulse_*_arm64.deb user@raspberrypi:~/"
    echo -e "            ssh user@raspberrypi sudo apt install ./voidpulse_*_arm64.deb"
    sep
}

# =============================================================================
#  RPM (Fedora / openSUSE / RHEL / Arch yabancı paketler)
# =============================================================================
build_rpm() {
    sep
    echo -e "${BOLD}  VoidPulse → RPM Builder v8${NC}"
    sep

    check_sources

    # ── Dağıtım algılama ───────────────────────────────────────────────────────
    local IS_OPENSUSE=0
    if [[ -f /etc/os-release ]]; then
        if grep -qiE "opensuse|suse" /etc/os-release; then
            IS_OPENSUSE=1
            info "openSUSE sistemi algılandı ✓"
        fi
    fi

    # ── Araç kontrolü ──────────────────────────────────────────────────────────
    log "Sistem araçları kontrol ediliyor..."
    local missing_tools=()
    command -v rpmbuild &>/dev/null || missing_tools+=("rpmbuild  (rpm-build / rpmdevtools)")
    if [[ ${#missing_tools[@]} -gt 0 ]]; then
        if [[ "${IS_OPENSUSE}" -eq 1 ]]; then
            die "Eksik araçlar:\n$(printf '   • %s\n' "${missing_tools[@]}")\n   openSUSE : sudo zypper install rpm-build rpmdevtools"
        else
            die "Eksik araçlar:\n$(printf '   • %s\n' "${missing_tools[@]}")\n   Fedora/RHEL : sudo dnf install rpm-build rpmdevtools\n   openSUSE    : sudo zypper install rpm-build"
        fi
    fi
    info "Araçlar hazır ✓"

    # ── Hedef mimari algılama ─────────────────────────────────────────────────
    # RPM_TARGET_ARCH ortam değişkeniyle override edilebilir.
    # Uygulama saf Python (noarch) olduğundan aynı .rpm tüm mimarilerde kurulur;
    # ancak rpmbuild'in doğru %{_arch} makrosunu kullanması için --target gerekir.
    #
    #  uname -m    → RPM _target_cpu
    #  x86_64      → x86_64
    #  aarch64     → aarch64   (Raspberry Pi 4/5, Pine64, Librem 5, telefon)
    #  armv7l      → armv7hl   (PinePhone Pro, eski SBC — hard-float)
    #  armv6l      → armv6hl
    #  riscv64     → riscv64
    local HOST_UNAME
    HOST_UNAME=$(uname -m)
    local RPM_CPU
    if [[ -n "${RPM_TARGET_ARCH:-}" ]]; then
        RPM_CPU="${RPM_TARGET_ARCH}"
        info "Hedef mimari (ortam değişkeni): ${RPM_CPU}"
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
        info "Hedef mimari (otomatik): ${RPM_CPU}"
    fi

    # noarch paket üretilir; --target yalnızca rpmbuild'in RPMS/<arch>/ dizinini
    # ve paket adındaki mimari etiketini belirler.
    local RPM_TARGET="${RPM_CPU}-linux"

    download_font

    # ── RPM dizin yapısını kur ─────────────────────────────────────────────────
    local RPM_ROOT="${SOURCE_DIR}/rpm-build"
    log "RPM derleme ağacı oluşturuluyor: ${RPM_ROOT}"
    rm -rf "${RPM_ROOT}"
    mkdir -p "${RPM_ROOT}"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}

    # ── Kaynak tarball oluştur ────────────────────────────────────────────────
    local TAR_NAME="${APP_NAME}-${APP_VERSION}"
    local TAR_DIR="${RPM_ROOT}/SOURCES/${TAR_NAME}"
    mkdir -p "${TAR_DIR}"

    shopt -s nullglob
    local _py_modules=("${SOURCE_DIR}"/*.py)
    shopt -u nullglob
    [[ ${#_py_modules[@]} -eq 0 ]] && die "Kaynak dizinde hiç .py dosyası bulunamadı: ${SOURCE_DIR}"
    cp "${_py_modules[@]}"                "${TAR_DIR}/"
    cp "${SOURCE_DIR}/${APP_ID}.desktop" "${TAR_DIR}/"
    cp "${SOURCE_DIR}/${APP_ID}.svg"     "${TAR_DIR}/"
    cp "${FONT_FILE}"                    "${TAR_DIR}/"
    info "Kopyalanan Python modülleri: ${#_py_modules[@]} adet"

    tar -czf "${RPM_ROOT}/SOURCES/${TAR_NAME}.tar.gz" \
        -C "${RPM_ROOT}/SOURCES" "${TAR_NAME}"
    rm -rf "${TAR_DIR}"

    # ── Başlatıcı script ──────────────────────────────────────────────────────
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

    # ── SPEC dosyası ─────────────────────────────────────────────────────────
    local SPEC="${RPM_ROOT}/SPECS/${APP_NAME}.spec"
    log "SPEC dosyası yazılıyor: ${SPEC}"

    # Dağıtım + mimari'ye göre paket adları
    # openSUSE: python3-qt6, gstreamer-plugins-good/bad
    # Fedora  : python3-PyQt6, gstreamer1-plugins-good/bad-free
    # ARM dağıtımlarında PyQt5 fallback eklenir (PyQt6 paketi eksik olabilir)
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
    # ARM mimarilerinde python3-PyQt5 Suggests olarak ekle
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

# Python uygulaması — tüm mimarilerde çalışır
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
Touch ve OLED dostu gelişmiş müzik çalar.
Wayland, GNOME/KDE entegrasyonu, PipeWire, GStreamer
spektrum görselleştirme, MPRIS2 D-Bus ve bit-perfect
ses desteği sunar.
ARM mimarileri (aarch64, armv7hl) tam olarak desteklenir.

%prep
%autosetup

%install
# voidpulse.py artık tek dosya değil — refactor sonrası constants.py ve
# diğer yardımcı modüller ayrı dosyalarda; hepsini kur, yoksa
# "ModuleNotFoundError" oluşur.
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
- İlk paket sürümü; ARM (aarch64/armv7hl) tam destek eklendi
SPEC

    # ── Derle ─────────────────────────────────────────────────────────────────
    log "RPM derleniyor (hedef: ${RPM_TARGET})..."
    rpmbuild \
        --define "_topdir ${RPM_ROOT}" \
        --target "${RPM_TARGET}" \
        -bb "${SPEC}"

    # ── Çıktıyı kaynak dizinine kopyala ──────────────────────────────────────
    local BUILT_RPM
    BUILT_RPM=$(find "${RPM_ROOT}/RPMS" -name "*.rpm" | head -1)
    [[ -n "${BUILT_RPM}" ]] || die "RPM dosyası oluşturulamadı."
    local OUT_RPM="${SOURCE_DIR}/$(basename "${BUILT_RPM}")"
    cp "${BUILT_RPM}" "${OUT_RPM}"
    sign_rpm "${OUT_RPM}"

    local RPM_MB
    RPM_MB=$(du -sh "${OUT_RPM}" | cut -f1)
    sep
    echo -e "${GREEN}${BOLD}  ✓ RPM paketi hazır!${NC}"
    sep
    echo -e "  ${BOLD}Paket   :${NC} ${OUT_RPM}  (${RPM_MB})"
    echo -e "  ${BOLD}Mimari  :${NC} ${RPM_CPU} (noarch paket — tüm mimarilerde kurulur)"
    echo -e "  ${BOLD}Kur     :${NC} sudo dnf install ${OUT_RPM}      # Fedora/RHEL/ARM"
    echo -e "              sudo zypper install ${OUT_RPM}  # openSUSE/ARM"
    echo -e "  ${BOLD}Çalıştır:${NC} ${APP_NAME}"
    echo -e "  ${BOLD}Kaldır  :${NC} sudo dnf remove ${APP_NAME}"
    echo -e ""
    echo -e "  ${BOLD}İpucu   :${NC} ARM cihaza SCP ile kopyalamak için:"
    echo -e "              scp $(basename "${OUT_RPM}") user@pihost:~/"
    echo -e "              ssh user@pihost sudo dnf install ./$(basename "${OUT_RPM}")"
    echo -e "  ${BOLD}İpucu   :${NC} Farklı mimari için: RPM_TARGET_ARCH=aarch64 $0 rpm"
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

    # ── Alpine Linux kontrolü ─────────────────────────────────────────────────
    if ! grep -qi "alpine" /etc/os-release 2>/dev/null; then
        warn "Bu sistem Alpine Linux değil — APK adımı atlanıyor."
        warn "APK paketi yalnızca Alpine Linux üzerinde oluşturulabilir."
        return 0
    fi

    check_sources

    # ── Araç kontrolü ──────────────────────────────────────────────────────────
    log "Sistem araçları kontrol ediliyor..."
    local missing_tools=()
    command -v abuild  &>/dev/null || missing_tools+=("abuild  (alpine-sdk)")
    command -v apk     &>/dev/null || missing_tools+=("apk     (alpine-sdk)")
    if [[ ${#missing_tools[@]} -gt 0 ]]; then
        warn "Eksik araçlar: ${missing_tools[*]}"
        warn "Bu builder yalnızca Alpine Linux üzerinde çalışır."
        warn "Kurun: sudo apk add alpine-sdk abuild-rootbuild"
        warn "Sonra : abuild-keygen -a -i   # imzalama anahtarı oluştur"
        die  "APK derlemesi için gereken araçlar eksik."
    fi
    info "Araçlar hazır ✓"

    # ── abuild anahtarı kontrolü ──────────────────────────────────────────────
    local ABUILD_CONF="${HOME}/.abuild/abuild.conf"
    if [[ ! -f "${ABUILD_CONF}" ]]; then
        warn "abuild imzalama anahtarı bulunamadı: ${ABUILD_CONF}"
        warn "Anahtar oluşturmak için: abuild-keygen -a -i"
        die  "APK derlemesi için imzalama anahtarı gerekli."
    fi
    info "imzalama anahtarı mevcut ✓"

    download_font

    # ── APKBUILD dizini ───────────────────────────────────────────────────────
    local APK_BUILD_DIR="${SOURCE_DIR}/apk-build/${APP_NAME}"
    rm -rf "${SOURCE_DIR}/apk-build"
    mkdir -p "${APK_BUILD_DIR}"

    # ── Kaynak tarball oluştur ────────────────────────────────────────────────
    local TAR_NAME="${APP_NAME}-${APP_VERSION}"
    local TAR_DIR="/tmp/${TAR_NAME}"
    rm -rf "${TAR_DIR}"
    mkdir -p "${TAR_DIR}"

    shopt -s nullglob
    local _py_modules=("${SOURCE_DIR}"/*.py)
    shopt -u nullglob
    [[ ${#_py_modules[@]} -eq 0 ]] && die "Kaynak dizinde hiç .py dosyası bulunamadı: ${SOURCE_DIR}"
    cp "${_py_modules[@]}"                "${TAR_DIR}/"
    cp "${SOURCE_DIR}/${APP_ID}.desktop" "${TAR_DIR}/"
    cp "${SOURCE_DIR}/${APP_ID}.svg"     "${TAR_DIR}/"
    cp "${FONT_FILE}"                    "${TAR_DIR}/"
    info "Kopyalanan Python modülleri: ${#_py_modules[@]} adet"

    tar -czf "${APK_BUILD_DIR}/${TAR_NAME}.tar.gz" \
        -C /tmp "${TAR_NAME}"
    rm -rf "${TAR_DIR}"

    # ── Başlatıcı script ──────────────────────────────────────────────────────
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

    # ── SHA512 toplamları hesapla ─────────────────────────────────────────────
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
    log "APKBUILD yazılıyor: ${APKBUILD}"
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
    # Python modülü sadece kurulur, derleme gerekmez
    :
}

check() {
    for _pyfile in "\${builddir}"/*.py; do
        python3 -c "import ast; ast.parse(open('\${_pyfile}').read())" \
            && echo "Sözdizimi kontrolü geçti: \$(basename "\${_pyfile}") ✓"
    done
}

package() {
    # Python modülleri — voidpulse.py artık tek dosya değil, refactor sonrası
    # constants.py ve diğer yardımcı modüller de kurulmalı.
    for _pyfile in "\${builddir}"/*.py; do
        install -Dm644 "\${_pyfile}" \
            "\${pkgdir}/usr/lib/voidpulse/\$(basename "\${_pyfile}")"
    done

    # Başlatıcı
    install -Dm755 "\${srcdir}/voidpulse-launcher.sh" \
        "\${pkgdir}/usr/bin/voidpulse"

    # .desktop
    install -Dm644 "\${srcdir}/${APP_ID}.desktop" \
        "\${pkgdir}/usr/share/applications/${APP_ID}.desktop"

    # İkon
    install -Dm644 "\${srcdir}/${APP_ID}.svg" \
        "\${pkgdir}/usr/share/icons/hicolor/scalable/apps/${APP_ID}.svg"

    # AppStream metainfo
    install -Dm644 "\${srcdir}/${APP_ID}.appdata.xml" \
        "\${pkgdir}/usr/share/metainfo/${APP_ID}.appdata.xml"

    # NotoMusic fontu
    install -Dm644 "\${srcdir}/NotoMusic-Regular.ttf" \
        "\${pkgdir}/usr/share/fonts/misc/NotoMusic-Regular.ttf"
}

APKBUILD

    # ── abuild ile derle ──────────────────────────────────────────────────────
    log "APK derleniyor..."
    cd "${APK_BUILD_DIR}"

    # abuild checksum kaynakları kendi konumuna göre bekler;
    # sha512sums zaten elle eklendi, -F ile zorla
    REPODEST="${SOURCE_DIR}/apk-out" abuild -F -P "${SOURCE_DIR}/apk-out"

    # ── Çıktıyı bul ──────────────────────────────────────────────────────────
    local BUILT_APK
    BUILT_APK=$(find "${SOURCE_DIR}/apk-out" -name "${APP_NAME}-${APP_VERSION}*.apk" | head -1)
    [[ -n "${BUILT_APK}" ]] || die "APK dosyası oluşturulamadı. 'apk-out/' dizinini kontrol edin."
    local OUT_APK="${SOURCE_DIR}/$(basename "${BUILT_APK}")"
    cp "${BUILT_APK}" "${OUT_APK}"

    local APK_MB
    APK_MB=$(du -sh "${OUT_APK}" | cut -f1)
    sep
    echo -e "${GREEN}${BOLD}  ✓ APK paketi hazır!${NC}"
    sep
    echo -e "  ${BOLD}Paket   :${NC} ${OUT_APK}  (${APK_MB})"
    echo -e "  ${BOLD}Kur     :${NC} sudo apk add --allow-untrusted ${OUT_APK}"
    echo -e "  ${BOLD}Çalıştır:${NC} ${APP_NAME}"
    echo -e "  ${BOLD}Kaldır  :${NC} sudo apk del ${APP_NAME}"
    sep

    rm -rf "${SOURCE_DIR}/apk-build" "${SOURCE_DIR}/apk-out"
}

# =============================================================================
#  APPIMAGE — Tam ARM Desteği
#  Desteklenen mimariler: x86_64 · aarch64 · armhf · i686
#
#  Tek mimari (mevcut sistem): build_appimage
#  Çoklu mimari:               build_appimage_multiarch  (menüden seçilebilir)
#
#  APPIMAGE_TARGET_ARCH ortam değişkeniyle mimari override edilebilir.
#  Örnek: APPIMAGE_TARGET_ARCH=aarch64 ./build-flatpak.sh appimage
#
#  appimagetool → AppImageKit GitHub releases/continuous'dan indirilir.
#  Her mimari için ayrı binary mevcuttur; script otomatik seçer.
#
#  ARM'da bağımlılık notu:
#    - Python3, PyQt6 (veya PyQt5), mutagen, numpy, GStreamer
#      hedef sistemde kurulu olmalıdır.
#    - AppImage runtime'ı (squashfuse tabanlı) ARM için mevcut ve çalışır.
# =============================================================================

# ── İç yardımcı: appimagetool indir/doğrula ──────────────────────────────────
# Çıktı: stdout'a tool yolunu yazar
#
# NOT: Hedef mimari ne olursa olsun her zaman x86_64 appimagetool kullanılır.
# appimagetool çapraz mimari paketlemeyi destekler; hedef mimari ARCH env
# değişkeniyle belirtilir (_build_single_appimage içinde set edilir).
# ARM/i686 binary'leri x86_64 host'ta çalıştırılamaz (Exec format error).
_get_appimagetool() {
    local TOOL="${SOURCE_DIR}/appimagetool-x86_64.AppImage"
    if [[ ! -x "${TOOL}" ]]; then
        log "appimagetool indiriliyor (x86_64)..." >&2
        curl -L --fail \
            -o "${TOOL}" \
            "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" || \
            die "appimagetool indirilemedi.\n   URL: https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
        chmod +x "${TOOL}"
        info "appimagetool kaydedildi: ${TOOL}" >&2
    else
        info "appimagetool zaten mevcut: ${TOOL} ✓" >&2
    fi
    echo "${TOOL}"
}

# ── İç yardımcı: uname -m → AppImage ARCH etiketi ───────────────────────────
# AppImageKit, ARCH env değişkeninde kendi etiketlerini bekler (rpm/deb'den farklı).
_uname_to_appimage_arch() {
    case "$1" in
        x86_64)          echo "x86_64"  ;;
        aarch64)         echo "aarch64" ;;
        armv7l|armv7*)   echo "armhf"   ;;
        armv6l|armv6*)   echo "armhf"   ;;   # armv6 için de armhf tool kullanılır
        i?86)            echo "i686"    ;;
        *)               echo "$1"      ;;   # bilinmeyen → olduğu gibi dene
    esac
}

# ── İç yardımcı: AppImage ARCH etiketi → appimagetool ARCH env değeri ────────
# appimagetool extract_arch_from_text() yalnızca belirli string'leri kabul eder:
#   "x86_64"      → x86_64
#   "i686" vb.    → i386 ailesi (i686 eşleşir)
#   "arm"         → armhf (32-bit ARM)
#   "arm_aarch64" → aarch64
# Dosya adında kullandığımız "aarch64" ve "armhf" etiketleri doğrudan geçmez.
_arch_to_appimage_env() {
    case "$1" in
        x86_64)  echo "x86_64"      ;;
        aarch64) echo "arm_aarch64" ;;
        armhf)   echo "arm"         ;;
        i686)    echo "i686"        ;;
        *)       echo "$1"          ;;
    esac
}

# ── İç yardımcı: AppDir oluştur + AppImage paketle ───────────────────────────
# $1 = hedef AppImage ARCH etiketi (x86_64, aarch64, armhf, i686)
_build_single_appimage() {
    # Tüm fonksiyon stderr'e yazar; yalnızca son echo (dosya yolu) stdout'a gider.
    # Bu sayede OUT_AI=$(_build_single_appimage ...) temiz path yakalar.
    exec 3>&1 1>&2

    local TARGET_ARCH="$1"

    local APPDIR="${SOURCE_DIR}/AppDir-${TARGET_ARCH}"
    log "AppDir oluşturuluyor (${TARGET_ARCH}): ${APPDIR}"
    rm -rf "${APPDIR}"
    mkdir -p \
        "${APPDIR}/usr/bin" \
        "${APPDIR}/usr/lib/${APP_NAME}" \
        "${APPDIR}/usr/share/applications" \
        "${APPDIR}/usr/share/icons/hicolor/scalable/apps" \
        "${APPDIR}/usr/share/metainfo" \
        "${APPDIR}/usr/share/fonts/NotoMusic"

    # ── Dosyaları yerleştir ───────────────────────────────────────────────────
    # NOT: voidpulse.py artık tek dosya değil — refactor sonrası constants.py
    # ve diğer yardımcı modüller ayrı dosyalarda. Hepsini kopyala, yoksa
    # "ModuleNotFoundError: No module named 'constants'" gibi hatalar oluşur.
    shopt -s nullglob
    local _py_modules=("${SOURCE_DIR}"/*.py)
    shopt -u nullglob
    [[ ${#_py_modules[@]} -eq 0 ]] && die "Kaynak dizinde hiç .py dosyası bulunamadı: ${SOURCE_DIR}"
    for _pyfile in "${_py_modules[@]}"; do
        install -Dm644 "${_pyfile}" "${APPDIR}/usr/lib/${APP_NAME}/$(basename "${_pyfile}")"
    done
    info "Kopyalanan Python modülleri: ${#_py_modules[@]} adet"
    install -Dm644 "${SOURCE_DIR}/${APP_ID}.desktop" "${APPDIR}/usr/share/applications/${APP_ID}.desktop"
    install -Dm644 "${SOURCE_DIR}/${APP_ID}.svg"     "${APPDIR}/usr/share/icons/hicolor/scalable/apps/${APP_ID}.svg"
    install -Dm644 "${FONT_FILE}"                    "${APPDIR}/usr/share/fonts/NotoMusic/NotoMusic-Regular.ttf"

    # AppDir kökü gereksinimleri
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

    # ── AppRun — ARM dahil tüm mimarilerde çalışır ────────────────────────────
    cat > "${APPDIR}/AppRun" << 'APPRUN'
#!/bin/sh
# VoidPulse AppImage giriş noktası — x86_64 / aarch64 / armhf / i686
HERE="$(dirname "$(readlink -f "${0}")")"
export PYTHONPATH="${HERE}/usr/lib/voidpulse:${PYTHONPATH:-}"
export XDG_DATA_DIRS="${HERE}/usr/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
export FONTCONFIG_PATH="${HERE}/usr/share/fonts:${FONTCONFIG_PATH:-}"
# GStreamer eklenti yolunu da ekle (sistem kurulumuna geri düşer)
export GST_PLUGIN_PATH="${HERE}/usr/lib/gstreamer-1.0:${GST_PLUGIN_PATH:-}"
exec python3 "${HERE}/usr/lib/voidpulse/voidpulse.py" "$@"
APPRUN
    chmod +x "${APPDIR}/AppRun"

    # ── appimagetool edin ve çalıştır ─────────────────────────────────────────
    local APPIMAGETOOL
    APPIMAGETOOL=$(_get_appimagetool "${TARGET_ARCH}")

    local OUT_APPIMAGE="${SOURCE_DIR}/VoidPulse-${APP_VERSION}-${TARGET_ARCH}.AppImage"
    log "AppImage oluşturuluyor: $(basename "${OUT_APPIMAGE}")"

    # appimagetool ARCH env değeri dosya adı etiketinden farklıdır:
    #   aarch64 → arm_aarch64 | armhf → arm | i686 → i686 | x86_64 → x86_64
    # APPIMAGE_EXTRACT_AND_RUN=1: FUSE gerektirmeden /tmp'ye açarak çalıştırır.
    local ARCH_ENV
    ARCH_ENV=$(_arch_to_appimage_env "${TARGET_ARCH}")
    export ARCH="${ARCH_ENV}"
    APPIMAGE_EXTRACT_AND_RUN=1 "${APPIMAGETOOL}" \
        --no-appstream \
        "${APPDIR}" \
        "${OUT_APPIMAGE}" || \
        die "AppImage oluşturulamadı (${TARGET_ARCH}). appimagetool çıktısını inceleyin."
    unset ARCH

    chmod +x "${OUT_APPIMAGE}"
    sign_appimage "${OUT_APPIMAGE}"

    local AI_MB
    AI_MB=$(du -sh "${OUT_APPIMAGE}" | cut -f1)
    info "  ✓ ${OUT_APPIMAGE}  (${AI_MB})"

    rm -rf "${APPDIR}"
    echo "${OUT_APPIMAGE}" >&3  # çağırana dosya yolunu döndür (orijinal stdout)
    exec 3>&-
}

# =============================================================================
#  build_appimage — Tek mimari (mevcut sistem veya APPIMAGE_TARGET_ARCH)
# =============================================================================
build_appimage() {
    sep
    echo -e "${BOLD}  VoidPulse → AppImage Builder v8${NC}"
    sep

    check_sources

    log "Sistem araçları kontrol ediliyor..."
    local missing_tools=()
    command -v python3 &>/dev/null || missing_tools+=("python3")
    command -v curl    &>/dev/null || missing_tools+=("curl")
    command -v desktop-file-validate &>/dev/null || \
        warn "desktop-file-validate bulunamadı, doğrulama atlanacak."
    [[ ${#missing_tools[@]} -gt 0 ]] && \
        die "Eksik araçlar:\n$(printf '   • %s\n' "${missing_tools[@]}")"
    info "Araçlar hazır ✓"

    # Hedef mimari: ortam değişkeni > uname -m
    local TARGET_ARCH
    if [[ -n "${APPIMAGE_TARGET_ARCH:-}" ]]; then
        TARGET_ARCH="${APPIMAGE_TARGET_ARCH}"
        info "Hedef mimari (ortam değişkeni): ${TARGET_ARCH}"
    else
        TARGET_ARCH=$(_uname_to_appimage_arch "$(uname -m)")
        info "Hedef mimari (otomatik): ${TARGET_ARCH}"
    fi

    download_font

    local OUT_APPIMAGE
    OUT_APPIMAGE=$(_build_single_appimage "${TARGET_ARCH}")

    local AI_MB
    AI_MB=$(du -sh "${OUT_APPIMAGE}" | cut -f1)
    sep
    echo -e "${GREEN}${BOLD}  ✓ AppImage hazır!${NC}"
    sep
    echo -e "  ${BOLD}Dosya   :${NC} ${OUT_APPIMAGE}  (${AI_MB})"
    echo -e "  ${BOLD}Mimari  :${NC} ${TARGET_ARCH}"
    echo -e "  ${BOLD}Çalıştır:${NC} chmod +x $(basename "${OUT_APPIMAGE}") && ./$(basename "${OUT_APPIMAGE}")"
    echo -e "  ${BOLD}Not     :${NC} Python3, PyQt6/5, mutagen, numpy ve GStreamer hedef sistemde kurulu olmalıdır."
    echo -e "  ${BOLD}İpucu   :${NC} Farklı mimari: APPIMAGE_TARGET_ARCH=aarch64 $0 appimage"
    sep
}

# =============================================================================
#  build_appimage_multiarch — Tüm ARM + x86 mimarileri için AppImage üret
#  Mimariler: x86_64 · aarch64 · armhf · i686
# =============================================================================
build_appimage_multiarch() {
    sep
    echo -e "${BOLD}  VoidPulse → AppImage Multi-Arch Builder v8${NC}"
    sep

    check_sources

    log "Sistem araçları kontrol ediliyor..."
    local missing_tools=()
    command -v python3 &>/dev/null || missing_tools+=("python3")
    command -v curl    &>/dev/null || missing_tools+=("curl")
    [[ ${#missing_tools[@]} -gt 0 ]] && \
        die "Eksik araçlar:\n$(printf '   • %s\n' "${missing_tools[@]}")"
    info "Araçlar hazır ✓"

    # ── Hedef seçimi ──────────────────────────────────────────────────────────
    local SELECTED_AI_ARCHES=()
    if [[ -n "${APPIMAGE_ARCH_TARGETS:-}" ]]; then
        IFS=',' read -ra SELECTED_AI_ARCHES <<< "${APPIMAGE_ARCH_TARGETS}"
    else
        echo ""
        echo -e "  Hangi mimariler için AppImage oluşturulsun?"
        echo -e "  ${BOLD}0)${NC} Hepsi (x86_64 aarch64 armhf i686)"
        echo -e "  ${BOLD}1)${NC} x86_64   — Masaüstü / sunucu"
        echo -e "  ${BOLD}2)${NC} aarch64  — ARM 64-bit (Raspberry Pi 4/5, Pine64, telefon)"
        echo -e "  ${BOLD}3)${NC} armhf    — ARM 32-bit hard-float (PinePhone Pro, Librem 5, eski SBC)"
        echo -e "  ${BOLD}4)${NC} i686     — x86 32-bit (eski PC)"
        echo ""
        read -rp "  Seçim [0-4], virgülle ayır (örn. 2,3): " ai_choice

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
                    *) warn "Bilinmeyen mimari atlandı: ${t}" ;;
                esac
            done
        fi
    fi

    [[ ${#SELECTED_AI_ARCHES[@]} -eq 0 ]] && die "Hiçbir mimari seçilmedi."
    info "Hedef mimariler: ${SELECTED_AI_ARCHES[*]}"

    download_font

    local BUILT_AIS=()
    for TARGET_ARCH in "${SELECTED_AI_ARCHES[@]}"; do
        sep
        local OUT_AI
        OUT_AI=$(_build_single_appimage "${TARGET_ARCH}")
        BUILT_AIS+=("${OUT_AI}")
    done

    sep
    echo -e "${GREEN}${BOLD}  ✓ Çoklu mimari AppImage'lar hazır!${NC}"
    sep
    for _ai in "${BUILT_AIS[@]}"; do
        local _sz
        _sz=$(du -sh "${_ai}" | cut -f1)
        echo -e "  ${BOLD}Dosya:${NC} ${_ai}  (${_sz})"
    done
    echo ""
    echo -e "  ${BOLD}Çalıştır:${NC} chmod +x VoidPulse-*.AppImage && ./VoidPulse-*-aarch64.AppImage"
    echo -e "  ${BOLD}Not     :${NC} Python3, PyQt6/5, mutagen, numpy ve GStreamer hedef sistemde kurulu olmalıdır."
    echo -e "  ${BOLD}İpucu   :${NC} ARM cihaza kopyalamak için:"
    echo -e "              scp VoidPulse-${APP_VERSION}-aarch64.AppImage user@pihost:~/"
    echo -e "              ssh user@pihost 'chmod +x ~/VoidPulse-*.AppImage && ~/VoidPulse-*.AppImage'"
    sep
}

# =============================================================================
#  Menü / Argüman işleme
# =============================================================================
show_menu() {
    sep
    echo -e "${BOLD}  VoidPulse — Universal Package Builder v8${NC}"
    sep
    echo -e "  Hangi paketi oluşturmak istiyorsunuz?"
    echo -e ""
    echo -e "  ${BOLD}1)${NC} flatpak           — Sandbox'lı evrensel Linux paketi"
    echo -e "  ${BOLD}2)${NC} deb               — Debian / Ubuntu / Linux Mint (mevcut mimari)"
    echo -e "  ${BOLD}3)${NC} deb-multiarch     — DEB: arm64, armhf, armel, riscv64, loong64, amd64"
    echo -e "  ${BOLD}4)${NC} rpm               — Fedora / openSUSE / RHEL / CentOS (ARM otomatik algılama)"
    echo -e "  ${BOLD}5)${NC} apk               — Alpine Linux"
    echo -e "  ${BOLD}6)${NC} appimage          — Taşınabilir tek dosya (mevcut mimari)"
    echo -e "  ${BOLD}7)${NC} appimage-multiarch — AppImage: x86_64, aarch64, armhf, i686"
    echo -e "  ${BOLD}8)${NC} all               — Hepsini derle"
    echo -e "  ${BOLD}q)${NC} Çıkış"
    echo ""
    read -rp "  Seçim [1-8/q], virgülle ayır (örn. 3,6,7): " choice

    # q / Q → direkt çıkış
    [[ "${choice}" =~ ^[qQ]$ ]] && { echo "Çıkış."; exit 0; }

    # Virgülle ayrılmış listeyi IFS üzerinden dizi yap
    IFS=',' read -ra selections <<< "${choice}"

    # Her token'i çöz, sıralı çalıştır (tekrarları önlemek için izleme seti)
    declare -A _seen=()
    for token in "${selections[@]}"; do
        token="${token// /}"  # boşlukları temizle
        # "8" veya "all" → expand et
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
            *) die "Geçersiz seçim: ${token}" ;;
        esac
    done
}

# ── GPG kurulumu (fonksiyonlar tanındıktan sonra) ─────────────────────────────
setup_gpg

# ── openSUSE'da APK atlanır — build_apk() içi guard zaten hallediyor ──────────
# all argümanıyla çalıştırıldığında openSUSE'da APK adımı otomatik atlanır.

# ── Giriş noktası ─────────────────────────────────────────────────────────────
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
        echo -e "Kullanım: $0 [flatpak|deb|deb-multiarch|rpm|apk|appimage|appimage-multiarch|all]"
        echo -e "Argüman verilmezse interaktif menü açılır."
        exit 1
        ;;
esac
