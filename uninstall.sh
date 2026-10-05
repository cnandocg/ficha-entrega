#!/bin/bash
# Atalho para: ./ficha-entrega.sh desinstalar (use --apagar-dados para apagar o historico)
exec "$(dirname "$0")/ficha-entrega.sh" desinstalar "$@"
