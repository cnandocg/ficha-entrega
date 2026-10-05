#!/bin/bash
# Chamado pelo xbindkeys no Ctrl+F: mostra a Ficha de Entrega por cima do PDV.
# O app fica residente; aqui so guardamos quem tinha o foco (o PDV) e pedimos
# para ele aparecer. Se nao estiver rodando, sobe na hora.

APP=/opt/ficha-entrega/app/ficha.py
PIDFILE=/tmp/ficha-entrega.pid
FOCO=/tmp/ficha-entrega.foco

export DISPLAY="${DISPLAY:-:0}"
export HOME="${HOME:-/root}"

# Guarda a janela do PDV para devolver o teclado no Esc
# (se a ficha ja estiver na frente, nao sobrescreve).
ATUAL=$(xdotool getwindowfocus 2>/dev/null)
RAIZ=$(xwininfo -root | awk '/Window id:/ {print $4}')
if [ -n "$ATUAL" ] && [ "$(printf '%d' "$RAIZ")" != "$ATUAL" ] \
   && [ "$(xdotool getwindowname "$ATUAL" 2>/dev/null)" != "Ficha de Entrega" ]; then
    echo "$ATUAL" > "$FOCO"
fi

PID=$(cat "$PIDFILE" 2>/dev/null)
if [ -n "$PID" ] && grep -q "ficha.py" "/proc/$PID/cmdline" 2>/dev/null; then
    kill -USR1 "$PID"
else
    setsid -f python3 "$APP" --mostrar >/dev/null 2>&1 < /dev/null
fi
