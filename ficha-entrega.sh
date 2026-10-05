#!/bin/bash
# Ficha de Entrega para PDV Arius (Ctrl+F abre, Esc fecha).
#
# Uso: sudo ./ficha-entrega.sh {instalar|ativar|desativar|status|teste-impressao|desinstalar}

set -e

DESTINO=/opt/ficha-entrega
INICIA_PDV=/pdv/inicia_pdv
MARCA="# ficha-entrega"
FLAG="$DESTINO/ativo"
XBK_RC="$DESTINO/app/xbindkeysrc"
APP="$DESTINO/app/ficha.py"
ORIGEM="$(cd "$(dirname "$0")" && pwd)"

msg()  { echo -e "\e[1;32m[ficha]\e[0m $*"; }
aviso() { echo -e "\e[1;33m[ficha]\e[0m $*"; }
erro() { echo -e "\e[1;31m[ficha]\e[0m $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || erro "Rode como root (sudo)."

# Sessao X do caixa (startx do inicia_pdv), para agir sem reiniciar o PDV.
usa_x_do_caixa() {
    export DISPLAY=:0
    export HOME="${HOME:-/root}"
    local auth
    for auth in "$XAUTHORITY" /.Xauthority /root/.Xauthority $(ls -t /tmp/serverauth.* 2>/dev/null); do
        [ -f "$auth" ] || continue
        XAUTHORITY="$auth" xdpyinfo >/dev/null 2>&1 && { export XAUTHORITY="$auth"; return 0; }
    done
    xdpyinfo >/dev/null 2>&1
}

# So mexe no proprio xbindkeys (a calculadora tem o dela).
liga() {
    export HOME="${HOME:-/root}"   # no boot nao ha HOME; xbindkeys da segfault sem ele
    pkill -f "xbindkeys -f $XBK_RC" 2>/dev/null || true
    xbindkeys -f "$XBK_RC"
    inicia_app
}

# App residente e escondido, para abrir na hora do atalho.
inicia_app() {
    pgrep -f "^python3 $APP" >/dev/null && return 0
    rm -f /tmp/ficha-entrega.pid
    setsid -f python3 "$APP" >/dev/null 2>&1 < /dev/null
    for _ in $(seq 30); do
        [ -s /tmp/ficha-entrega.pid ] && return 0
        sleep 0.2
    done
    aviso "O aplicativo nao subiu. Veja /root/.ficha-entrega/logs/app.log"
}

desliga() {
    pkill -f "xbindkeys -f $XBK_RC" 2>/dev/null || true
    pkill -f "^python3 $APP" 2>/dev/null || true
}

instalar() {
    [ -f "$INICIA_PDV" ] || erro "$INICIA_PDV nao encontrado. Este e um PDV Arius?"
    [ -f "$ORIGEM/app/ficha.py" ] || erro "Rode a partir da pasta do repositorio (git clone)."

    msg "Instalando pacotes (xbindkeys, xdotool, python3-gi)..."
    # Alguns caixas tem repositorio quebrado no sources.list; nao trava por isso.
    apt-get update -qq || aviso "apt-get update com erros, seguindo com o cache atual."
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq xbindkeys xdotool x11-utils \
        python3-gi gir1.2-gtk-3.0 >/dev/null

    msg "Testando o aplicativo..."
    python3 "$ORIGEM/app/ficha.py" --teste >/dev/null || erro "Testes automaticos falharam."

    usa_x_do_caixa >/dev/null 2>&1 && desliga
    msg "Copiando para $DESTINO"
    mkdir -p "$DESTINO/app"
    install -m 755 "$ORIGEM/app/ficha.py" "$ORIGEM/app/abrir-ficha.sh" "$DESTINO/app/"
    install -m 644 "$ORIGEM/app/impressora.py" "$ORIGEM/app/xbindkeysrc" "$DESTINO/app/"
    install -m 755 "$ORIGEM/ficha-entrega.sh" "$DESTINO/"

    if ! grep -q "$MARCA" "$INICIA_PDV"; then
        cp -p "$INICIA_PDV" "$INICIA_PDV.antes-ficha"
        # Entra logo antes da linha que sobe o PDV (a que nao esta comentada).
        sed -i "0,/^java -jar AriusPdv.jar/s||$DESTINO/ficha-entrega.sh sessao $MARCA\n&|" "$INICIA_PDV"
        grep -q "$MARCA" "$INICIA_PDV" || erro "Nao achei 'java -jar AriusPdv.jar' em $INICIA_PDV."
        msg "inicia_pdv alterado (backup: $INICIA_PDV.antes-ficha)"
    fi

    ativar

    if [ "$1" != "--sem-teste" ]; then
        msg "Imprimindo ficha de teste..."
        python3 "$APP" --teste-impressao || aviso "Teste de impressao falhou. Confira a impressora e rode: $0 teste-impressao"
    fi
}

ativar() {
    [ -d "$DESTINO" ] || erro "Nao instalado. Rode: $0 instalar"
    touch "$FLAG"
    if usa_x_do_caixa; then
        liga
        msg "Ativada. Ctrl+F abre a ficha, Esc fecha."
    else
        msg "Ativada. Vale a partir do proximo inicio do PDV."
    fi
}

desativar() {
    rm -f "$FLAG"
    desliga
    msg "Desativada. Ctrl+F nao abre mais a ficha."
}

# Chamado pelo inicia_pdv, dentro do X, antes do Java subir.
sessao() {
    [ -f "$FLAG" ] && liga
    exit 0
}

status() {
    [ -d "$DESTINO" ] && echo "Instalada:        sim" || echo "Instalada:        nao"
    [ -f "$FLAG" ]    && echo "Ativada:          sim" || echo "Ativada:          nao"
    grep -q "$MARCA" "$INICIA_PDV" 2>/dev/null && echo "No inicia_pdv:    sim" || echo "No inicia_pdv:    nao"
    pgrep -f "xbindkeys -f $XBK_RC" >/dev/null && echo "Atalho rodando:   sim" || echo "Atalho rodando:   nao"
    pgrep -f "^python3 $APP" >/dev/null && echo "App residente:    sim" || echo "App residente:    nao"
    if [ -f "$DESTINO/app/impressora.py" ]; then
        python3 - "$DESTINO/app" <<'EOF'
import sys; sys.path.insert(0, sys.argv[1]); import impressora as i
d = i.acha_impressora()
print("Impressora:       " + ("%s %s (USB %s:%s, driver %s)" % (d["fabricante"], d["modelo"], d["vid"], d["pid"], d["driver"] or "livre") if d else "nenhuma encontrada"))
EOF
    fi
}

teste_impressao() {
    [ -f "$APP" ] || erro "Nao instalado. Rode: $0 instalar"
    python3 "$APP" --teste-impressao
}

desinstalar() {
    desativar
    if [ -f "$INICIA_PDV" ]; then
        sed -i "/$MARCA/d" "$INICIA_PDV"
        msg "Linha removida do inicia_pdv."
    fi
    rm -rf "$DESTINO"
    rm -f /tmp/ficha-entrega.pid /tmp/ficha-entrega.foco
    if [ "$1" = "--apagar-dados" ]; then
        rm -rf /root/.ficha-entrega
        msg "Historico e configuracao apagados."
    else
        msg "Historico e configuracao mantidos em /root/.ficha-entrega (apague com --apagar-dados)."
    fi
    msg "Removida. (Pacotes apt mantidos.)"
}

case "$1" in
    instalar)        instalar "$2" ;;
    ativar)          ativar ;;
    desativar)       desativar ;;
    sessao)          sessao ;;
    status)          status ;;
    teste-impressao) teste_impressao ;;
    desinstalar)     desinstalar "$2" ;;
    *) echo "Uso: $0 {instalar|ativar|desativar|status|teste-impressao|desinstalar}"; exit 1 ;;
esac
