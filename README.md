# Ficha de Entrega

Aplicativo auxiliar para o **PDV Arius** (Linux): o operador aperta **Ctrl+F**, preenche a ficha
de entrega só pelo teclado e imprime **uma via por volume** na mesma impressora térmica do caixa.
**Esc** fecha e o PDV volta a receber o teclado. O PDV nunca é fechado.

```
PDV aberto → Ctrl+F → nome, telefone, endereço, observação, embalador(a), volumes → Enter → Enter → imprime → Esc → PDV
```

## Instalação (em cada caixa)

Pode ser feita com o PDV aberto (ele não é reiniciado). Prefira fora de venda: no final sai uma
ficha de teste na impressora.

```bash
sudo apt-get update; sudo apt-get install -y git
git clone https://github.com/<usuario>/ficha-entrega.git
cd ficha-entrega
sudo ./install.sh
```

Para instalar sem imprimir a ficha de teste: `sudo ./install.sh --sem-teste`.
Se o `apt-get update` der erro de um repositório quebrado (ex. `buster-backports`), pode seguir:
o `apt-get install` e o instalador usam o cache.

Depois de instalar, a pasta do clone pode ser apagada: tudo fica em `/opt/ficha-entrega`
(mas mantenha-a se for atualizar com `git pull`).

## Ativar, desativar e conferir

Funcionam de qualquer pasta:

| Comando | O que faz |
|---|---|
| `sudo /opt/ficha-entrega/ficha-entrega.sh status` | Mostra se está instalada, ativa, rodando e qual impressora foi encontrada |
| `sudo /opt/ficha-entrega/ficha-entrega.sh desativar` | Desliga o Ctrl+F (continua desligado depois de reiniciar) |
| `sudo /opt/ficha-entrega/ficha-entrega.sh ativar` | Liga o Ctrl+F de novo (na hora, sem reiniciar o PDV) |
| `sudo /opt/ficha-entrega/ficha-entrega.sh teste-impressao` | Imprime a ficha de teste |
| `sudo /opt/ficha-entrega/ficha-entrega.sh desinstalar` | Remove tudo; mantém histórico e config em `/root/.ficha-entrega` |
| `sudo /opt/ficha-entrega/ficha-entrega.sh desinstalar --apagar-dados` | Remove tudo, inclusive histórico e config |

Da pasta do clone também funcionam `sudo ./install.sh` e `sudo ./uninstall.sh`.

Resultado esperado do `status`:

```
Instalada:        sim
Ativada:          sim
No inicia_pdv:    sim
Atalho rodando:   sim
App residente:    sim
Impressora:       EPSON TM-T20 (USB 04b8:0202, driver usblp)
```

## Atualizar

```bash
cd ficha-entrega && git pull && sudo ./install.sh --sem-teste
```

Configuração e histórico são mantidos. Se a pasta do clone foi apagada, clone de novo e rode `sudo ./install.sh`.

## Publicar este repositório (técnico, uma vez)

```bash
git init -b main && git add . && git commit -m "Ficha de Entrega para PDV Arius"
git remote add origin https://github.com/<usuario>/ficha-entrega.git
git push -u origin main
```

No `push` a senha é um token do GitHub (Settings → Developer settings → Personal access tokens).
Repositório **público** clona nos caixas sem senha (não há senhas nem dados de clientes aqui);
**privado** pede usuário e token em cada `git clone`.

Detalhes da instalação em [INSTALACAO.md](INSTALACAO.md).

## Documentação

| Arquivo | Para quê |
|---|---|
| [INSTALACAO.md](INSTALACAO.md) | Instalar, atualizar, desinstalar |
| [CONFIGURACAO.md](CONFIGURACAO.md) | Impressora, papel, acentos, histórico |
| [OPERACAO.md](OPERACAO.md) | Uso no caixa (teclas) — para treinar o operador |
| [TESTES.md](TESTES.md) | Roteiro de testes de aceite |

## Como funciona (resumo técnico)

| Parte | Solução |
|---|---|
| Tela | Python 3 + GTK3 (já presente no Ubuntu do caixa). App residente e escondido (~30 MB RAM). |
| Atalho | `xbindkeys` captura Ctrl+F no X do caixa e chama `app/abrir-ficha.sh`, que mostra o app. |
| Foco | O X do PDV não tem gerenciador de janelas: o app guarda a janela do PDV, foca a ficha e, no Esc, devolve o foco ao PDV. |
| Impressão | ESC/POS direto no USB, sem CUPS e sem driver. Detecta a impressora sozinha (qualquer modelo/fabricante). |
| Nº do caixa | Lido automaticamente do `codigo_pdv` do Arius (`/pdv/pdv.cfg`, só leitura) e impresso em cada via. |
| Dados | Arquivos JSON em `/root/.ficha-entrega/` (sem banco de dados). Histórico apagado após N dias. |
| Boot | Uma linha no `/pdv/inicia_pdv` (antes do `java -jar`) sobe o atalho e o app. Backup em `/pdv/inicia_pdv.antes-ficha`. |

### Por que Ctrl+F

No mapeamento de teclas do Arius o **Ctrl não faz nada** e o **F sozinho é "Função"**. Com o atalho,
Ctrl+F fica com a ficha e nunca chega ao PDV; F e F1 continuam abrindo o menu de Função normalmente.
Evitados: **Shift** (no Arius = Totaliza Venda) e **Ctrl+Alt+F1..F12** (troca de terminal no Linux).

### Impressora compartilhada com o PDV

O Arius usa a impressora direto pelo USB e a "segura" enquanto o PDV está aberto. Como o PDV e a
ficha nunca imprimem ao mesmo tempo, a ficha **pega a impressora emprestada** por uma fração de
segundo: solta a interface USB pelo sysfs, imprime e solta de novo. Na próxima impressão do PDV o
kernel devolve a interface para ele automaticamente (testado). **Não imprima a ficha no exato
momento em que o PDV está imprimindo um cupom.**

A impressora é encontrada pelo USB (classe de impressora ou fabricante conhecido: Epson, Bematech,
Elgin, Bixolon, Star, Citizen, genéricas). Trocar o modelo não exige reconfigurar.

## Arquivos

```
ficha-entrega.sh        instalar | ativar | desativar | status | teste-impressao | desinstalar
install.sh              atalho para: ficha-entrega.sh instalar
uninstall.sh            atalho para: ficha-entrega.sh desinstalar
app/ficha.py            o aplicativo (tela, histórico, layout da impressão)
app/impressora.py       detecção da impressora e envio ESC/POS pelo USB
app/abrir-ficha.sh      chamado pelo atalho
app/xbindkeysrc         definição do atalho Ctrl+F
```
