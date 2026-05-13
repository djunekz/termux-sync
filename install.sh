#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
#  termux-sync — Backup & Restore for Termux
#  https://github.com/djunekz/termux-sync
#  Open Source — MIT License
# ============================================================

set -euo pipefail

OFFICIAL_OWNER="djunekz"
OFFICIAL_REPO="termux-sync"
RELEASE_API="https://api.github.com/repos/${OFFICIAL_OWNER}/${OFFICIAL_REPO}/releases/latest"
INSTALL_DIR="$PREFIX/lib/termux-sync"
SCRIPT="$INSTALL_DIR/termux-sync.py"
CMD="$PREFIX/bin/termux-sync"
VERSION_FILE="$INSTALL_DIR/.version"

R='\033[0;31m'
G='\033[0;32m'
Y='\033[1;33m'
C='\033[0;36m'
D='\033[2m'
B='\033[1m'
N='\033[0m'

banner() {
cat << 'EOF'

  ████████╗███████╗██████╗ ███╗   ███╗██╗   ██╗██╗  ██╗
  ╚══██╔══╝██╔════╝██╔══██╗████╗ ████║██║   ██║╚██╗██╔╝
     ██║   █████╗  ██████╔╝██╔████╔██║██║   ██║ ╚███╔╝
     ██║   ██╔══╝  ██╔══██╗██║╚██╔╝██║██║   ██║ ██╔██╗
     ██║   ███████╗██║  ██║██║ ╚═╝ ██║╚██████╔╝██╔╝ ██╗
     ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═╝

EOF
}

STEP=0
step()  { STEP=$((STEP + 1)); printf "\n${C}[%d]${N} ${B}%s${N}\n" "$STEP" "$*"; }
ok()    { printf "     ${G}OK${N}   %s\n" "$*"; }
warn()  { printf "     ${Y}WARN${N} %s\n" "$*"; }
fail()  { printf "\n     ${R}FAIL${N} %s\n\n" "$*"; exit 1; }
info()  { printf "     ${D}--${N}   %s\n" "$*"; }
hr()    { printf "${D}%s${N}\n" "─────────────────────────────────────────────────────"; }

printf "${C}${B}"
banner
printf "${N}"
printf "  ${B}termux-sync${N}  ${D}Backup & Restore for Termux${N}\n"
printf "  ${D}https://github.com/${OFFICIAL_OWNER}/${OFFICIAL_REPO}${N}\n\n"
hr

if [[ "$OFFICIAL_OWNER" != "djunekz" || "$OFFICIAL_REPO" != "termux-sync" ]]; then
    printf "\n  ${R}${B}SECURITY WARNING${N}\n\n"
    printf "  ${R}Unofficial source detected!${N}\n"
    printf "  ${D}Expected : djunekz/termux-sync${N}\n"
    printf "  ${D}Got      : ${OFFICIAL_OWNER}/${OFFICIAL_REPO}${N}\n\n"
    printf "  ${Y}Only the official repository is supported.${N}\n"
    printf "  ${Y}Get the original script from:${N}\n"
    printf "  ${C}https://github.com/djunekz/termux-sync${N}\n\n"
    exit 1
fi

step "Updating package lists"
pkg update -y -q 2>/dev/null && ok "Package lists updated" \
    || warn "Could not update package lists (continuing)"

step "Installing Python"
pkg install -y python python-pip 2>/dev/null || fail "Failed to install Python"
ok "Python $(python --version 2>&1 | awk '{print $2}')"

step "Installing curl"
pkg install -y curl 2>/dev/null && ok "curl ready" \
    || fail "Failed to install curl"

step "Installing Python dependencies"
pip install --quiet rich 2>/dev/null && ok "rich" \
    || fail "Failed to install rich"

step "Fetching latest release from GitHub"
info "Source: https://github.com/${OFFICIAL_OWNER}/${OFFICIAL_REPO}/releases/latest"

RELEASE_RESPONSE=$(curl -sS \
    -H "Accept: application/vnd.github+json" \
    -w "\n%{http_code}" \
    "$RELEASE_API" 2>&1) \
    || fail "Cannot reach GitHub API. Check your internet connection."

RELEASE_HTTP=$(printf '%s' "$RELEASE_RESPONSE" | tail -1)
RELEASE_JSON=$(printf '%s' "$RELEASE_RESPONSE" | head -n -1)

if [[ "$RELEASE_HTTP" == "404" ]]; then
    printf "\n  ${R}${B}Repository not found (HTTP 404)${N}\n\n"
    printf "  ${R}Cannot find:${N} ${OFFICIAL_OWNER}/${OFFICIAL_REPO}\n\n"
    printf "  ${Y}This repository does not exist or has no releases.${N}\n"
    printf "  ${Y}Only the official source is supported:${N}\n"
    printf "  ${C}https://github.com/djunekz/termux-sync${N}\n\n"
    exit 1
fi

if [[ "$RELEASE_HTTP" != "200" ]]; then
    fail "GitHub API returned HTTP $RELEASE_HTTP. Check your internet connection."
fi

RELEASE_TAG=$(echo "$RELEASE_JSON" | python3 -c \
    "import sys,json; print(json.load(sys.stdin).get('tag_name',''))")
[[ -z "$RELEASE_TAG" ]] && fail "Could not determine latest release tag"
ok "Latest release: $RELEASE_TAG"

TARBALL_URL=$(echo "$RELEASE_JSON" | python3 -c "
import sys, json, re
data = json.load(sys.stdin)
for a in data.get('assets', []):
    if re.match(r'termux-sync-v[\d.]+\.tar\.gz$', a['name']):
        print(a['browser_download_url'])
        sys.exit(0)
print(data.get('tarball_url', ''))
")
[[ -z "$TARBALL_URL" ]] && fail "Could not find release tarball"
info "Tarball : $TARBALL_URL"

SHA_URL=$(echo "$RELEASE_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for a in data.get('assets', []):
    if a['name'].endswith('.sha256') or a['name'] == 'SHA256SUMS':
        print(a['browser_download_url'])
        sys.exit(0)
print('')
")

step "Downloading release"
TMP_DIR=$(mktemp -d)
_tmp="$TMP_DIR"
trap 'rm -rf "$_tmp"' EXIT

TARBALL="$TMP_DIR/termux-sync.tar.gz"
curl -fsSL "$TARBALL_URL" -o "$TARBALL" || fail "Failed to download release tarball"
ok "Tarball downloaded"

if [[ -n "$SHA_URL" ]]; then
    SHA_FILE="$TMP_DIR/termux-sync.tar.gz.sha256"
    curl -fsSL "$SHA_URL" -o "$SHA_FILE" 2>/dev/null || true
    if [[ -f "$SHA_FILE" && -s "$SHA_FILE" ]]; then
        EXPECTED=$(awk '{print $1}' "$SHA_FILE")
        ACTUAL=$(sha256sum "$TARBALL" | awk '{print $1}')
        if [[ "$ACTUAL" != "$EXPECTED" ]]; then
            printf "\n  ${R}${B}Checksum verification FAILED.${N}\n"
            printf "  ${R}Expected: %s${N}\n" "$EXPECTED"
            printf "  ${R}Got:      %s${N}\n\n" "$ACTUAL"
            exit 1
        fi
        ok "SHA256 verified"
    else
        warn "SHA256 file empty or unavailable — skipping verification"
    fi
else
    warn "No SHA256 asset in release — skipping verification"
fi

step "Extracting termux-sync.py"
ENTRY=$(tar -tzf "$TARBALL" | grep -E '(^|/)termux-sync\.py$' | head -1)
[[ -z "$ENTRY" ]] && fail "termux-sync.py not found inside tarball"
tar -xzf "$TARBALL" -C "$TMP_DIR" "$ENTRY" 2>/dev/null \
    || fail "Failed to extract termux-sync.py"
ok "Extracted: $ENTRY"

step "Installing to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cp "$TMP_DIR/$ENTRY" "$SCRIPT"
echo "$RELEASE_TAG" > "$VERSION_FILE"
chmod +x "$SCRIPT"
ok "termux-sync.py installed ($RELEASE_TAG)"

step "Installing termux-sync command"
rm -f "$CMD"
printf '#!/data/data/com.termux/files/usr/bin/bash\nexec python "%s" "$@"\n' "$SCRIPT" > "$CMD"
chmod +x "$CMD"
ok "Installed to $CMD"

step "Cleaning shell config"
for RC in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.bash_profile" "$HOME/.profile"; do
    if [[ -f "$RC" ]] && grep -q "termux.sync\|termux_sync" "$RC" 2>/dev/null; then
        sed -i '/termux.sync\|termux_sync/d' "$RC"
        ok "Cleaned $(basename "$RC")"
    fi
done
info "No alias added — launcher in \$PREFIX/bin is sufficient"

step "Checking optional tools"
command -v git    &>/dev/null && ok "git found"    \
    || warn "git not found    — install: pkg install git"
command -v rclone &>/dev/null && ok "rclone found" \
    || warn "rclone not found — install: pkg install rclone  (needed for Google Drive)"

printf "\n"
hr
printf "\n  ${G}${B}termux-sync ${RELEASE_TAG} installed successfully!${N}\n\n"
printf "  ${D}First-time setup:${N}\n"
printf "    ${C}termux-sync setup${N}\n\n"
printf "  ${D}Create a backup:${N}\n"
printf "    ${C}termux-sync backup${N}\n\n"
printf "  ${D}Restore from backup:${N}\n"
printf "    ${C}termux-sync restore${N}\n\n"
hr
printf "\n"
