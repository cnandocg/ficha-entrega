# Instalação

## Requisitos do caixa

- PDV Arius em Linux (testado em Ubuntu 20.04), PDV rodando como root.
- `/pdv/inicia_pdv` com a linha `java -jar AriusPdv.jar` (padrão Arius). Se não tiver, o instalador para e não altera nada.
- Impressora térmica USB ESC/POS (Epson TM-T20, TM-T20X e similares).
- Internet ou espelho do apt (só durante a instalação, para `xbindkeys` e `xdotool`).

Pode instalar **com o PDV aberto**; ele não é reiniciado. Prefira um momento sem venda: a instalação
leva ~1 minuto e no final **imprime uma ficha de teste**.

## Instalar

```bash
sudo apt-get update; sudo apt-get install -y git
git clone https://github.com/<usuario>/ficha-entrega.git
cd ficha-entrega
sudo ./install.sh
```

O instalador:

1. instala `xbindkeys`, `xdotool`, `x11-utils`, `python3-gi` (os que faltarem);
2. roda os testes automáticos do app;
3. copia para `/opt/ficha-entrega`;
4. adiciona **uma linha** no `/pdv/inicia_pdv` (backup em `/pdv/inicia_pdv.antes-ficha`);
5. cria `/root/.ficha-entrega/config.json` (na primeira execução);
6. liga o atalho Ctrl+F e o app residente na hora;
7. imprime a ficha de teste (pule com `sudo ./install.sh --sem-teste`).

Se o `apt-get update` reclamar de um repositório quebrado (ex.: `buster-backports`), o instalador
segue com o cache. Se o apt reclamar de *lock*, espere a atualização automática terminar e rode de novo.

## Conferir

```bash
sudo /opt/ficha-entrega/ficha-entrega.sh status
```

Tudo deve estar "sim" e a linha **Impressora** deve mostrar o modelo. Depois aperte **Ctrl+F** no caixa.
Recomendado: reiniciar o caixa uma vez e testar o Ctrl+F de novo (confirma o início automático).

## Comandos

| Comando | O que faz |
|---|---|
| `sudo ./install.sh` | Instala/atualiza (rodar da pasta do git clone) |
| `sudo /opt/ficha-entrega/ficha-entrega.sh status` | Situação e impressora detectada |
| `sudo /opt/ficha-entrega/ficha-entrega.sh teste-impressao` | Imprime a ficha de teste |
| `sudo /opt/ficha-entrega/ficha-entrega.sh desativar` | Desliga Ctrl+F (continua desligado após reiniciar) |
| `sudo /opt/ficha-entrega/ficha-entrega.sh ativar` | Liga de novo |
| `sudo ./uninstall.sh` | Remove tudo; mantém histórico/config em `/root/.ficha-entrega` |
| `sudo ./uninstall.sh --apagar-dados` | Remove tudo, inclusive histórico e config |

## Atualizar

```bash
cd ficha-entrega && git pull && sudo ./install.sh --sem-teste
```

A configuração e o histórico são mantidos.

## O que é alterado no caixa

- `/pdv/inicia_pdv`: **uma linha** antes do `java -jar` (`/opt/ficha-entrega/ficha-entrega.sh sessao # ficha-entrega`).
- `/opt/ficha-entrega/`: o aplicativo.
- `/root/.ficha-entrega/`: configuração, histórico e log.
- Pacotes apt citados acima.

Nada do PDV (jar, bancos, `pdv.cfg`, `CliSiTef.ini`) é tocado.

## Convivência com a calculadora (pdv-calculadora)

Os dois podem ficar instalados juntos: cada um tem seu próprio `xbindkeys` e sua linha no
`inicia_pdv`. Use a versão da calculadora que só desliga o próprio atalho (atualize com `git pull`).
