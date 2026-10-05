# Configuração

## Pela tela (no caixa)

Com a ficha aberta (Ctrl+F), aperte **F9**:

| Opção | Valores |
|---|---|
| Impressora | **Automática (detectar)** ou um modelo específico conectado |
| Largura do papel | 80 mm (48 colunas) ou 58 mm (32 colunas) |
| Acentuação | **PC860 (português)**, PC850 ou Sem acentos |
| Manter histórico por | 7, 15, 30, 60 ou 90 dias |

Teclas: **Tab** muda de opção, **◀ ▶** (ou Espaço) troca o valor, **F5** imprime um teste com o que
está na tela (antes de salvar), **Ctrl+S** salva, **Esc** volta sem salvar.

## Pelo arquivo

`/root/.ficha-entrega/config.json`:

```json
{
  "printer": "auto",
  "paper_width": 80,
  "encoding": "cp860",
  "history_days": 30,
  "shortcut": "CTRL+F",
  "auto_start": true,
  "caixa": "auto"
}
```

| Campo | Significado |
|---|---|
| `printer` | `"auto"` detecta sozinho. Para fixar, use `"vid:pid"` do `lsusb` (ex. `"04b8:0202"`). Se a fixada não estiver conectada, usa a que encontrar. |
| `paper_width` | `80` ou `58` |
| `encoding` | `"cp860"` (padrão), `"cp850"` ou `"sem_acento"` |
| `history_days` | dias de histórico; arquivos mais antigos são apagados ao abrir a ficha |
| `shortcut` | informativo; o atalho real está em `/opt/ficha-entrega/app/xbindkeysrc` |
| `caixa` | `"auto"`: lê o `codigo_pdv` do `/pdv/pdv.cfg` do Arius (só leitura); se não achar, usa o número do nome da máquina (`pdv22` → 22). Ou um número fixo, ex. `"22"`. O valor detectado aparece na tela F9. |
| `auto_start` | informativo; o início automático é ligado/desligado por `ativar`/`desativar` |

Depois de editar o arquivo à mão, reinicie o app: `sudo /opt/ficha-entrega/ficha-entrega.sh ativar`
(ou feche e abra o PDV).

## Impressora

- **Detecção:** qualquer dispositivo USB de classe impressora, ou de fabricante conhecido de
  impressora térmica, com saída de dados. Veja o que foi encontrado em `status` ou na tela F9.
- **Sem CUPS:** a impressão é ESC/POS direto no USB. Não é preciso instalar driver nem cadastrar impressora.
- **Acentos saindo errado** (ex. `Jo£o`): troque a acentuação para PC850 e imprima o teste (F5).
  Se nenhuma tabela funcionar, use "Sem acentos".
- **Texto cortado na direita:** a largura do papel está errada (58 mm configurado como 80 mm).
- **Impressora não Epson:** a maioria das térmicas (Elgin i9, Bematech em modo ESC/POS, genéricas)
  aceita os mesmos comandos. Bematech em modo nativo (ESC/Bema) precisa ser posta em modo ESC/POS.

## Arquivos e log

```
/root/.ficha-entrega/
├── config.json
├── historico/AAAA-MM-DD.json   uma lista de fichas por dia
└── logs/app.log                 até ~1,5 MB (rotaciona sozinho)
```

O log registra: início/fim do app, impressora detectada, ficha criada, impressão, reimpressão e
erros. Não registra telefone, endereço nem observação.
