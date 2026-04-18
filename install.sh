#!/data/data/com.termux/files/usr/bin/bash

#  termux-sync — Backup & Restore for Termux
#  https://github.com/djunekz/termux-sync
#  Open Source — MIT License

set -euo pipefail

R='\033[0;31m'
G='\033[0;32m'
Y='\033[1;33m'
C='\033[0;36m'
W='\033[1;37m'
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
step()  {
    STEP=$((STEP + 1))
    printf "\n${C}[%d]${N} ${B}%s${N}\n" "$STEP" "$*"
}
ok()    { printf "     ${G}OK${N}   %s\n" "$*"; }
warn()  { printf "     ${Y}WARN${N} %s\n" "$*"; }
fail()  { printf "\n     ${R}FAIL${N} %s\n\n" "$*"; exit 1; }
info()  { printf "     ${D}--${N}   %s\n" "$*"; }
hr()    { printf "${D}%s${N}\n" "─────────────────────────────────────────────────────"; }

printf "${C}${B}"
banner
printf "${N}"
printf "  ${B}termux-sync${N}  ${D}Backup & Restore for Termux${N}\n"
printf "  ${D}https://github.com/djunekz/termux-sync${N}\n\n"
hr

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$INSTALL_DIR/termux-sync.py"

if [[ ! -f "$SCRIPT" ]]; then
    fail "termux-sync.py not found in $INSTALL_DIR"
fi

step "Updating package lists"
if pkg update -y -q 2>/dev/null; then
    ok "Package lists updated"
else
    warn "Could not update package lists (continuing)"
fi

step "Installing Python"
if pkg install -y python python-pip 2>/dev/null; then
    PY_VER=$(python --version 2>&1 | awk '{print $2}')
    ok "Python $PY_VER"
else
    fail "Failed to install Python"
fi

step "Installing Python dependencies"
DEPS=(rich)
for dep in "${DEPS[@]}"; do
    if pip install --quiet "$dep" 2>/dev/null; then
        ok "$dep"
    else
        fail "Failed to install $dep"
    fi
done

step "Setting permissions"
chmod +x "$SCRIPT"
ok "termux-sync.py is executable"

step "Installing termux-sync command"

BIN_DIR="$PREFIX/bin"
CMD="$BIN_DIR/termux-sync"

rm -f "$CMD"

printf '#!/data/data/com.termux/files/usr/bin/bash\nexec python "%s" "$@"\n' "$SCRIPT" > "$CMD"
chmod +x "$CMD"

WRITTEN_PATH=$(grep 'exec python' "$CMD" | sed 's/exec python "//;s/" "\$@"//')
if [[ "$WRITTEN_PATH" != "$SCRIPT" ]]; then
    fail "Launcher path mismatch! Got: $WRITTEN_PATH — Expected: $SCRIPT"
fi

ok "Installed to $CMD"
info "Script path: $SCRIPT"
info "Run from anywhere: termux-sync"

step "Configuring shell"
ALIAS_LINE="alias termux-sync=\"python $SCRIPT\""
ADDED=0
for RC in "$HOME/.bashrc" "$HOME/.zshrc"; do
    if [[ -f "$RC" ]]; then
        if grep -q "termux-sync" "$RC" 2>/dev/null; then
            ok "Already configured in $(basename "$RC")"
        else
            { echo ""; echo "# termux-sync"; echo "$ALIAS_LINE"; } >> "$RC"
            ok "Alias added to $(basename "$RC")"
            ADDED=1
        fi
    fi
done
if [[ $ADDED -eq 0 && ! -f "$HOME/.bashrc" ]]; then
    info "No .bashrc or .zshrc found — the bin command above is sufficient"
fi

step "Checking optional tools"
command -v git     &>/dev/null && ok "git found"     || warn "git not found   — install: pkg install git"
command -v rclone  &>/dev/null && ok "rclone found"  || warn "rclone not found — install: pkg install rclone  (needed for Google Drive)"

printf "\n"
hr
printf "\n  ${G}${B}Installation complete.${N}\n\n"
printf "  ${D}First-time setup:${N}\n"
printf "    ${C}termux-sync setup${N}\n\n"
printf "  ${D}Create a backup:${N}\n"
printf "    ${C}termux-sync backup${N}\n\n"
printf "  ${D}Restore from backup:${N}\n"
printf "    ${C}termux-sync restore${N}\n\n"
hr
printf "\n"
