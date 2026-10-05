# Testes de aceite

Faça com o **caixa fechado** (fora de venda). Antes de digitar, confira que a ficha está na frente.

## Automáticos (sem impressora)

```bash
python3 app/ficha.py --teste
```

Confere: ids sequenciais, 1 volume = 1 via, 3 volumes = 3 vias, "VOLUME X DE N" e corte em cada via,
nome/telefone/endereço em cada via, acentos em PC860, remoção de acentos, reimpressão de um volume,
largura 58 mm, ordem do histórico e limpeza do histórico antigo. Deve terminar em `TODOS OK`.
O instalador roda esses testes e para se algum falhar.

## Roteiro no caixa

| # | Teste | Como | Esperado |
|---|---|---|---|
| 1 | 1 volume | Ficha com Volumes = 1, Enter, Enter | 1 via, "VOLUME 1 DE 1" |
| 2 | 3 volumes | Volumes = 3 | 3 vias (1 DE 3, 2 DE 3, 3 DE 3), cada uma cortada |
| 3 | Acentos | Nome "João José", endereço "Rua São Paulo", obs "Açúcar" | Acentos corretos no papel |
| 4 | Impressora desligada | Desligue a impressora e imprima | "ERRO DE IMPRESSÃO"; Enter (com ela ligada) imprime; Esc deixa a ficha como NÃO IMPRESSA em F2 |
| 5 | Reimprimir | F2, escolher a ficha, Enter | Todas as vias de novo |
| 6 | Reimprimir um volume | F2, ficha, F2, "2", Enter | Só "VOLUME 2 DE 3" |
| 7 | Fechar | Esc na ficha | Ficha some, **PDV responde ao teclado** |
| 8 | Abrir sobre o PDV | Com o PDV na frente, Ctrl+F | Ficha aparece com cursor em Nome |
| 9 | Só teclado | Fazer 1 a 8 sem mouse | Tudo funciona |
| 10 | Reiniciar | Reiniciar o Linux, abrir o PDV, Ctrl+F | Ficha abre (`status`: tudo "sim") |
| 11 | Cupom depois da ficha | Imprimir uma ficha e em seguida uma venda com cupom | Cupom sai normalmente |

O teste 11 é o mais importante em caixas onde o Arius usa a mesma impressora: confirma que o PDV
recupera a impressora depois do empréstimo.

## Resultado no PDV 22 (05/10/2026, Epson TM-T20 04b8:0202)

| # | Resultado |
|---|---|
| Automáticos | ✅ TODOS OK |
| 1 | ✅ (ficha de teste, 1 via) |
| 2 | ✅ com 2 volumes (2 vias) |
| 3 | ✅ acentos conferidos no papel (PC860) |
| 4 | ⏳ pendente: precisa desligar a impressora |
| 5 | ✅ |
| 6 | ✅ (só o volume 2) |
| 7 | ✅ foco voltou ao PDV (FocusProxy) |
| 8 | ✅ (teclas simuladas no X do caixa) |
| 9 | ✅ |
| 10 | ⏳ pendente: reiniciar o caixa |
| 11 | ⏳ pendente: no PDV 22 o Arius está configurado para a TM-T20X (0e27) e não usa a TM-T20; o empréstimo foi validado simulando o Arius |
