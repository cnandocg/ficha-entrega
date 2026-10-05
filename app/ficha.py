#!/usr/bin/env python3
"""Ficha de Entrega: app auxiliar do PDV, aberto por Ctrl+F e operado so pelo teclado.

Fica residente e escondido. O atalho manda SIGUSR1 e a janela aparece com o
cursor no campo Nome. Esc esconde a janela e devolve o teclado ao PDV.

Uso:
  ficha.py                 inicia escondido (boot)
  ficha.py --mostrar       inicia ja mostrando
  ficha.py --teste-impressao
  ficha.py --teste         testes automaticos (sem imprimir)
"""
import datetime as dt
import json
import logging
import logging.handlers
import os
import re
import signal
import subprocess
import sys
import textwrap
import threading
import unicodedata

os.environ.setdefault("NO_AT_BRIDGE", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import impressora  # noqa: E402

BASE = os.path.expanduser("~/.ficha-entrega")
CONFIG = os.path.join(BASE, "config.json")
HIST_DIR = os.path.join(BASE, "historico")
LOG_DIR = os.path.join(BASE, "logs")
PIDFILE = "/tmp/ficha-entrega.pid"
FOCO_PDV = "/tmp/ficha-entrega.foco"
TITULO = "Ficha de Entrega"

PADRAO = {
    "printer": "auto",          # "auto" ou "vid:pid" (ex. 04b8:0202)
    "paper_width": 80,          # 80 ou 58 (mm)
    "encoding": "cp860",        # cp860 (portugues), cp850 ou sem_acento
    "history_days": 30,
    "shortcut": "CTRL+F",
    "auto_start": True,
    "caixa": "auto",            # "auto" le o codigo_pdv do Arius, ou um numero fixo ("22")
}
PDV_CFG = "/pdv/pdv.cfg"
CODIFICACOES = {"cp860": ("PC860 (português)", 3), "cp850": ("PC850 (multilíngue)", 2),
                "sem_acento": ("Sem acentos", 0)}

log = logging.getLogger("ficha")


# ======================================================================
# Configuracao, historico e log
# ======================================================================
def prepara_pastas():
    for d in (BASE, HIST_DIR, LOG_DIR):
        os.makedirs(d, exist_ok=True)
    h = logging.handlers.RotatingFileHandler(os.path.join(LOG_DIR, "app.log"),
                                             maxBytes=512 * 1024, backupCount=2, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    log.addHandler(h)
    log.setLevel(logging.INFO)


def carrega_config():
    cfg = dict(PADRAO)
    try:
        with open(CONFIG, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    if not os.path.exists(CONFIG):
        salva_config(cfg)
    return cfg


def salva_config(cfg):
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG)


def _arquivo_dia(data):
    return os.path.join(HIST_DIR, data + ".json")


def _le_dia(data):
    try:
        with open(_arquivo_dia(data), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _grava_dia(data, fichas):
    tmp = _arquivo_dia(data) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(fichas, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _arquivo_dia(data))


def numero_caixa(cfg):
    """Numero do caixa: o da config, ou o codigo_pdv do Arius (so leitura), ou o do hostname."""
    fixo = str(cfg.get("caixa", "auto")).strip()
    if fixo and fixo.lower() != "auto":
        return fixo
    try:
        with open(PDV_CFG, encoding="latin-1") as f:
            for linha in f:
                m = re.match(r"\s*codigo_pdv\s*=\s*(\d+)", linha)
                if m:
                    return m.group(1)
    except OSError:
        pass
    m = re.search(r"(\d+)$", os.uname().nodename)
    return m.group(1) if m else ""


def nova_ficha(dados):
    """Grava a ficha (status pendente) e devolve com id."""
    agora = dt.datetime.now()
    data = agora.strftime("%Y-%m-%d")
    fichas = _le_dia(data)
    seq = max([f["seq"] for f in fichas] or [0]) + 1
    ficha = dict(dados, seq=seq, id="ENT-%s-%03d" % (agora.strftime("%Y%m%d"), seq),
                 criada=agora.strftime("%Y-%m-%d %H:%M:%S"), status="pendente", impressoes=0)
    fichas.append(ficha)
    _grava_dia(data, fichas)
    log.info("Ficha criada %s (%d volumes)", ficha["id"], ficha["volumes"])
    return ficha


def atualiza_ficha(ficha):
    data = ficha["criada"][:10]
    fichas = [ficha if f["id"] == ficha["id"] else f for f in _le_dia(data)]
    _grava_dia(data, fichas)


def ultimas_fichas(limite=200):
    todas = []
    for arq in sorted(os.listdir(HIST_DIR), reverse=True):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", arq):
            todas.extend(reversed(_le_dia(arq[:10])))
            if len(todas) >= limite:
                break
    return todas[:limite]


def limpa_historico_antigo(dias):
    limite = (dt.date.today() - dt.timedelta(days=int(dias))).isoformat()
    for arq in os.listdir(HIST_DIR):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", arq) and arq[:10] < limite:
            os.remove(os.path.join(HIST_DIR, arq))
            log.info("Historico removido: %s", arq)


# ======================================================================
# Layout ESC/POS
# ======================================================================
ESC, GS = b"\x1b", b"\x1d"
INIT = ESC + b"@"
NEGRITO = ESC + b"E\x01"
NORMAL = ESC + b"E\x00" + GS + b"!\x00"
CENTRO = ESC + b"a\x01"
ESQUERDA = ESC + b"a\x00"
CORTE = b"\n\n\n\n" + GS + b"V\x42\x00"   # avanca e corte parcial


def tamanho(mult):  # 1..8, largura e altura iguais
    m = max(1, min(8, mult)) - 1
    return GS + b"!" + bytes([(m << 4) | m])


def so_altura(mult):
    return GS + b"!" + bytes([max(1, min(8, mult)) - 1])


def codifica(texto, encoding):
    if encoding == "sem_acento":
        return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore")
    out = bytearray()
    for ch in texto:
        try:
            out += ch.encode(encoding)
        except UnicodeEncodeError:  # caractere fora da tabela: tira o acento
            out += unicodedata.normalize("NFKD", ch).encode("ascii", "ignore") or b"?"
    return bytes(out)


def monta_volumes(ficha, volumes, largura_mm=80, encoding="cp860", teste=False):
    """Bytes ESC/POS de cada volume pedido (lista de numeros 1..N)."""
    cols = 48 if largura_mm >= 80 else 32
    big = 3 if cols >= 48 else 2          # destaque: volume e nome
    t = lambda s: codifica(s, encoding)  # noqa: E731
    tabela = CODIFICACOES.get(encoding, ("", 0))[1]
    linha = t("=" * cols + "\n")
    total = ficha["volumes"]

    def bloco(rotulo, valor, mult_w, mult_h):
        if not valor:
            return b""
        largura = max(8, cols // mult_w)
        b = ESQUERDA + NORMAL + NEGRITO + t(rotulo + ":\n")
        b += GS + b"!" + bytes([((mult_w - 1) << 4) | (mult_h - 1)]) + NEGRITO
        for ln in textwrap.wrap(valor.upper(), largura) or [""]:
            b += t(ln + "\n")
        return b + NORMAL + b"\n"

    saida = []
    for v in volumes:
        b = INIT + ESC + b"t" + bytes([tabela]) + ESC + b"3\x30"  # espacamento de linha
        b += CENTRO + NEGRITO + linha
        b += so_altura(2) + t(("TESTE DE IMPRESSÃO" if teste else "FICHA DE ENTREGA") + "\n")
        b += NORMAL + CENTRO + NEGRITO + linha + NORMAL
        # Linha pequena: numero da ficha, caixa e data (no 58 mm quebra em duas).
        c = ficha["criada"]
        data = "%s/%s/%s %s" % (c[8:10], c[5:7], c[:4], c[11:16])
        partes = [ficha["id"]] + (["CAIXA %s" % ficha["caixa"]] if ficha.get("caixa") else []) + [data]
        info = "   ".join(partes)
        if len(info) > cols:
            info = "   ".join(partes[:-1]) + "\n" + data
        b += CENTRO + t(info + "\n\n")
        b += bloco("CLIENTE", ficha["nome"], 2, 2)
        b += bloco("TELEFONE", ficha.get("telefone", ""), 2, 2)
        b += bloco("ENDEREÇO", ficha["endereco"], 1, 2)
        b += bloco("OBSERVAÇÃO", ficha.get("observacao", ""), 1, 2)
        b += bloco("EMBALADOR(A)", ficha.get("embalador", ""), 1, 2)
        if teste:
            b += ESQUERDA + t("Acentos: ã á é í ó ú ç à ê ô Ã É Ç\n")
            b += t("1234567890" * (cols // 10) + "1234567890"[:cols % 10] + "\n\n")
        # destaque: volume e nome
        b += CENTRO + NEGRITO + linha + b"\n"
        b += tamanho(big) + NEGRITO
        for ln in textwrap.wrap("VOLUME %d DE %d" % (v, total), cols // big):
            b += t(ln + "\n")
        b += b"\n"
        for ln in textwrap.wrap(ficha["nome"].upper(), cols // big)[:4]:
            b += t(ln + "\n")
        b += NORMAL + CENTRO + NEGRITO + b"\n" + linha + NORMAL
        b += CORTE
        saida.append(b)
    return saida


def imprime(ficha, cfg, volumes=None, teste=False):
    """Imprime (todos os volumes ou a lista dada). Levanta impressora.ErroImpressora."""
    volumes = volumes or list(range(1, ficha["volumes"] + 1))
    dados = b"".join(monta_volumes(ficha, volumes, cfg["paper_width"], cfg["encoding"], teste))
    imp = impressora.envia(dados, cfg["printer"])
    log.info("Impresso %s volumes %s em %s %s (%s:%s)", ficha["id"], volumes,
             imp["fabricante"], imp["modelo"], imp["vid"], imp["pid"])
    return imp


FICHA_TESTE = {"id": "TESTE", "nome": "Cliente Teste João", "telefone": "(74) 99999-9999",
               "endereco": "Rua São José, 123 - Centro", "observacao": "Açúcar e café. Entregar após as 18h.",
               "embalador": "Maria", "volumes": 1}


def ficha_teste(cfg):
    return dict(FICHA_TESTE, caixa=numero_caixa(cfg), criada=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


# ======================================================================
# Foco (o X do PDV nao tem gerenciador de janelas)
# ======================================================================
def _x(*args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def janela_pdv():
    """FocusProxy da tela visivel do Arius (quem recebe o teclado do PDV)."""
    for linha in _x("xwininfo", "-root", "-children").splitlines():
        if "arius-PdvDesktop" not in linha:
            continue
        w = linha.split()[0]
        if "IsViewable" not in _x("xwininfo", "-id", w):
            continue
        for filho in _x("xwininfo", "-id", w, "-children").splitlines():
            if '"FocusProxy"' in filho:
                return filho.split()[0]
        return w
    return ""


def devolve_foco_pdv():
    try:
        with open(FOCO_PDV) as f:
            alvo = f.read().strip()
    except OSError:
        alvo = ""
    info = _x("xwininfo", "-id", alvo) if alvo else ""
    # Janela que sumiu, ou a raiz (foco "solto" quando o PDV acabou de abrir): procura o PDV.
    if not alvo or "IsViewable" not in info or "(the root window)" in info:
        alvo = janela_pdv() or alvo
    if alvo:
        _x("xdotool", "windowfocus", alvo)


# ======================================================================
# Interface
# ======================================================================
def tela(rodar_gui):
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GLib, Gtk, Pango

    CSS = b"""
    window { background: #1e1e20; }
    .topo { background: #2b2b2f; padding: 10px 16px; }
    .topo label { color: #ffffff; font-size: 18px; font-weight: bold; }
    .topo label.id { color: #9a9aa0; font-size: 14px; font-weight: normal; }
    .corpo { padding: 14px 22px; }
    label { color: #e8e8e8; }
    label.rotulo { font-size: 14px; color: #b0b0b6; margin-top: 8px; }
    label.rotulo.obrig { color: #ffffff; }
    entry { background: #35353a; color: #ffffff; border: 2px solid #35353a; border-radius: 6px;
            font-size: 20px; padding: 6px 10px; box-shadow: none; caret-color: #ffffff; }
    entry:focus { border-color: #3584e4; background: #3b3b41; }
    entry.erro { border-color: #ff6b6b; }
    .rodape { background: #2b2b2f; padding: 8px 16px; }
    .rodape label { color: #a0a0a6; font-size: 13px; }
    .rodape label.tecla { color: #ffffff; font-weight: bold; background: #45454b;
                          border-radius: 4px; padding: 1px 6px; }
    .aviso { padding: 10px 16px; font-size: 16px; font-weight: bold; }
    .aviso.ok { background: #1f6f43; color: #ffffff; }
    .aviso.erro { background: #9b2c2c; color: #ffffff; }
    .aviso.info { background: #3584e4; color: #ffffff; }
    .grande { font-size: 30px; font-weight: bold; color: #ffffff; }
    .medio { font-size: 20px; color: #ffffff; }
    .pequeno { font-size: 14px; color: #b0b0b6; }
    treeview { background: #2b2b2f; color: #e8e8e8; font-size: 16px; }
    treeview:selected { background: #3584e4; color: #ffffff; }
    treeview header button { background: #35353a; color: #ffffff; font-weight: bold; border: none; }
    button.seletor { background: #35353a; color: #ffffff; font-size: 18px; border: 2px solid #35353a;
                     border-radius: 6px; box-shadow: none; padding: 6px 12px; }
    button.seletor:focus { border-color: #3584e4; background: #3b3b41; }
    """

    class Seletor(Gtk.Button):
        """Escolha por teclado: setas esquerda/direita ou espaco trocam o valor."""

        def __init__(self, opcoes, valor):
            super().__init__()
            self.get_style_context().add_class("seletor")
            self.connect("key-press-event", self._tecla)
            self.connect("clicked", lambda *_: self.passo(1))
            self.define(opcoes, valor)

        def define(self, opcoes, valor):
            self.opcoes = opcoes  # lista de (valor, texto)
            self.i = next((i for i, (v, _) in enumerate(opcoes) if v == valor), 0)
            self._mostra()

        def _mostra(self):
            self.set_label("◀  %s  ▶" % self.opcoes[self.i][1])

        def passo(self, d):
            self.i = (self.i + d) % len(self.opcoes)
            self._mostra()

        def _tecla(self, _w, ev):
            k = Gdk.keyval_name(ev.keyval)
            if k in ("Left", "KP_Left"):
                self.passo(-1)
                return True
            if k in ("Right", "KP_Right", "space"):
                self.passo(1)
                return True
            return False

        @property
        def valor(self):
            return self.opcoes[self.i][0]

    def rodape(itens):
        box = Gtk.Box(spacing=8)
        box.get_style_context().add_class("rodape")
        for tecla, texto in itens:
            a = Gtk.Label(label=tecla)
            a.get_style_context().add_class("tecla")
            box.pack_start(a, False, False, 0)
            box.pack_start(Gtk.Label(label=texto + "   "), False, False, 0)
        return box

    def lbl(texto, *classes, xalign=0):
        w = Gtk.Label(label=texto, xalign=xalign)
        w.set_line_wrap(True)
        w.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        for c in classes:
            w.get_style_context().add_class(c)
        return w

    class Janela(Gtk.Window):
        CAMPOS = [("nome", "Nome do cliente *", True), ("telefone", "Telefone", False),
                  ("endereco", "Endereço de entrega *", True), ("observacao", "Observação", False),
                  ("embalador", "Nome do embalador(a)", False),
                  ("volumes", "Quantidade de volumes *", True)]

        def __init__(self, cfg):
            super().__init__(title=TITULO)
            self.cfg = cfg
            self.set_default_size(720, 640)
            self.set_resizable(False)
            self.ocupado = False
            self.pendente = None  # ficha aguardando nova tentativa de impressao

            self.stack = Gtk.Stack()
            self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
            raiz = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            self.aviso = lbl("", "aviso")
            self.aviso.set_no_show_all(True)
            raiz.pack_start(self.aviso, False, False, 0)
            raiz.pack_start(self.stack, True, True, 0)
            self.add(raiz)

            self._monta_ficha()
            self._monta_confirma()
            self._monta_erro()
            self._monta_historico()
            self._monta_detalhe()
            self._monta_config()

            self.connect("key-press-event", self._tecla)
            self.connect("delete-event", lambda *_: self.esconde() or True)

        # ------------------------------------------------------------ telas
        def _pagina(self, nome, titulo, corpo, atalhos):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            topo = Gtk.Box()
            topo.get_style_context().add_class("topo")
            t = Gtk.Label(label=titulo, xalign=0)
            topo.pack_start(t, True, True, 0)
            idl = lbl("", "id", xalign=1)
            topo.pack_end(idl, False, False, 0)
            box.pack_start(topo, False, False, 0)
            corpo.get_style_context().add_class("corpo")
            box.pack_start(corpo, True, True, 0)
            box.pack_end(rodape(atalhos), False, False, 0)
            self.stack.add_named(box, nome)
            return idl

        def _monta_ficha(self):
            corpo = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            self.entradas = {}
            for chave, rotulo, obrig in self.CAMPOS:
                r = lbl(rotulo, "rotulo", *(["obrig"] if obrig else []))
                corpo.pack_start(r, False, False, 0)
                e = Gtk.Entry()
                if chave == "volumes":
                    e.set_max_length(2)
                    e.set_width_chars(4)
                    e.set_halign(Gtk.Align.START)
                    e.set_input_purpose(Gtk.InputPurpose.DIGITS)
                    e.connect("insert-text", self._so_digitos)
                elif chave == "telefone":
                    e.set_max_length(20)
                    e.connect("focus-out-event", self._formata_tel)
                else:
                    e.set_max_length({"observacao": 200, "embalador": 60}.get(chave, 120))
                e.connect("activate", self._enter_campo, chave)
                e.connect("changed", lambda w: w.get_style_context().remove_class("erro"))
                corpo.pack_start(e, False, False, 0)
                self.entradas[chave] = e
            self.id_ficha = self._pagina("ficha", "FICHA DE ENTREGA", corpo,
                                         [("Enter", "próximo / imprimir"), ("Ctrl+Enter", "imprimir"),
                                          ("F2", "últimas"), ("F3", "nova"), ("F9", "config"),
                                          ("Esc", "fechar")])

        def _monta_confirma(self):
            corpo = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            corpo.set_valign(Gtk.Align.CENTER)
            self.conf_vol = lbl("", "grande", xalign=0.5)
            self.conf_nome = lbl("", "grande", xalign=0.5)
            self.conf_end = lbl("", "medio", xalign=0.5)
            self.conf_msg = lbl("", "pequeno", xalign=0.5)
            for w in (self.conf_vol, self.conf_nome, self.conf_end, self.conf_msg):
                corpo.pack_start(w, False, False, 0)
            self._pagina("confirma", "CONFIRMAR IMPRESSÃO", corpo,
                         [("Enter", "imprimir"), ("Esc", "voltar e corrigir")])

        def _monta_erro(self):
            corpo = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            corpo.set_valign(Gtk.Align.CENTER)
            corpo.pack_start(lbl("ERRO DE IMPRESSÃO", "grande", xalign=0.5), False, False, 0)
            self.erro_msg = lbl("", "medio", xalign=0.5)
            corpo.pack_start(self.erro_msg, False, False, 0)
            corpo.pack_start(lbl("A ficha foi salva e pode ser reimpressa depois em F2 (Últimas).",
                                 "pequeno", xalign=0.5), False, False, 0)
            self._pagina("erro", "ERRO DE IMPRESSÃO", corpo,
                         [("Enter", "tentar novamente"), ("Esc", "cancelar")])

        def _monta_historico(self):
            corpo = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            self.lista = Gtk.ListStore(str, str, str, str, str, int)  # id, cliente, vol, hora, status, idx
            self.tv = Gtk.TreeView(model=self.lista)
            for i, (titulo, exp) in enumerate([("Nº", False), ("Cliente", True), ("Vol.", False),
                                               ("Data / hora", False), ("Situação", False)]):
                r = Gtk.CellRendererText()
                if i == 1:
                    r.set_property("ellipsize", Pango.EllipsizeMode.END)
                c = Gtk.TreeViewColumn(titulo, r, text=i)
                c.set_expand(exp)
                self.tv.append_column(c)
            self.tv.connect("row-activated", lambda tv, p, c: self._abre_detalhe())
            sw = Gtk.ScrolledWindow()
            sw.add(self.tv)
            corpo.pack_start(sw, True, True, 0)
            self._pagina("historico", "ÚLTIMAS ENTREGAS", corpo,
                         [("↑↓", "escolher"), ("Enter", "abrir"), ("F3", "nova ficha"), ("Esc", "voltar")])

        def _monta_detalhe(self):
            corpo = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            self.det = lbl("", "medio")
            self.det.set_selectable(False)
            corpo.pack_start(self.det, False, False, 0)
            self.vol_box = Gtk.Box(spacing=10)
            self.vol_box.pack_start(lbl("Reimprimir só o volume:", "medio"), False, False, 0)
            self.vol_entry = Gtk.Entry()
            self.vol_entry.set_max_length(2)
            self.vol_entry.set_width_chars(4)
            self.vol_entry.connect("insert-text", self._so_digitos)
            self.vol_entry.connect("activate", lambda *_: self._reimprime_volume())
            self.vol_box.pack_start(self.vol_entry, False, False, 0)
            self.vol_box.set_no_show_all(True)
            corpo.pack_start(self.vol_box, False, False, 10)
            self.id_det = self._pagina("detalhe", "ENTREGA", corpo,
                                       [("Enter", "reimprimir todos"), ("F2", "só um volume"),
                                        ("Esc", "voltar")])

        def _monta_config(self):
            corpo = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            self.c_imp = Seletor(self._opcoes_impressora(), self.cfg["printer"])
            self.c_larg = Seletor([(80, "80 mm"), (58, "58 mm")], self.cfg["paper_width"])
            self.c_cod = Seletor([(k, v[0]) for k, v in CODIFICACOES.items()], self.cfg["encoding"])
            self.c_dias = Seletor([(d, "%d dias" % d) for d in (7, 15, 30, 60, 90)], self.cfg["history_days"])
            for rot, w in (("Impressora", self.c_imp), ("Largura do papel", self.c_larg),
                           ("Acentuação (tabela da impressora)", self.c_cod),
                           ("Manter histórico por", self.c_dias)):
                corpo.pack_start(lbl(rot, "rotulo"), False, False, 0)
                w.set_halign(Gtk.Align.START)
                corpo.pack_start(w, False, False, 0)
            self.c_info = lbl("", "pequeno")
            corpo.pack_start(self.c_info, False, False, 12)
            self._pagina("config", "CONFIGURAÇÕES", corpo,
                         [("Tab", "próximo"), ("◀ ▶", "mudar"), ("F5", "teste de impressão"),
                          ("Ctrl+S", "salvar"), ("Esc", "voltar")])

        # ------------------------------------------------------------ util
        def _so_digitos(self, w, texto, n, pos):
            if not texto.isdigit():
                w.stop_emission_by_name("insert-text")

        def _formata_tel(self, w, *_):
            d = re.sub(r"\D", "", w.get_text())
            if len(d) == 11:
                w.set_text("(%s) %s-%s" % (d[:2], d[2:7], d[7:]))
            elif len(d) == 10:
                w.set_text("(%s) %s-%s" % (d[:2], d[2:6], d[6:]))
            return False

        def mostra_aviso(self, texto, tipo="info"):
            ctx = self.aviso.get_style_context()
            for c in ("ok", "erro", "info"):
                ctx.remove_class(c)
            if texto:
                ctx.add_class(tipo)
                self.aviso.set_text(texto)
                self.aviso.show()
            else:
                self.aviso.hide()

        def vai(self, nome, foco=None):
            """foco: widget para focar; None = nenhum campo (teclas so pela janela)."""
            self.stack.set_visible_child_name(nome)
            if foco is None:
                self.set_focus(None)
            else:
                foco.grab_focus()

        # ------------------------------------------------------------ ficha
        def limpa_ficha(self):
            for e in self.entradas.values():
                e.set_text("")
                e.get_style_context().remove_class("erro")
            self.id_ficha.set_text("")
            self.vai("ficha", self.entradas["nome"])

        def dados(self):
            g = {k: e.get_text().strip() for k, e in self.entradas.items()}
            self._formata_tel(self.entradas["telefone"])
            g["telefone"] = self.entradas["telefone"].get_text().strip()
            return g

        def valida(self):
            g = self.dados()
            faltando = None
            if not g["nome"]:
                faltando = "nome"
            elif not g["endereco"]:
                faltando = "endereco"
            elif not g["volumes"].isdigit() or not 1 <= int(g["volumes"]) <= 99:
                faltando = "volumes"
            if faltando:
                e = self.entradas[faltando]
                e.get_style_context().add_class("erro")
                msg = ("ATENÇÃO: volumes deve ser de 1 a 99." if faltando == "volumes"
                       else "ATENÇÃO: preencha os campos obrigatórios.")
                self.mostra_aviso(msg, "erro")
                self.vai("ficha", e)
                return None
            g["volumes"] = int(g["volumes"])
            return g

        def _enter_campo(self, _e, chave):
            ordem = [c[0] for c in self.CAMPOS]
            i = ordem.index(chave)
            if i < len(ordem) - 1:
                self.entradas[ordem[i + 1]].grab_focus()
            else:
                self.confirma()

        def confirma(self):
            g = self.valida()
            if not g:
                return
            self.mostra_aviso("")
            self.a_imprimir = g
            n = g["volumes"]
            self.conf_vol.set_text("%d VOLUME%s" % (n, "S" if n > 1 else ""))
            self.conf_nome.set_text(g["nome"].upper())
            self.conf_end.set_text(g["endereco"])
            self.conf_msg.set_text("Serão impressas %d fichas (uma por volume)." % n)
            self.vai("confirma")

        def imprime_nova(self):
            g = self.valida()
            if not g:
                return
            g["caixa"] = numero_caixa(self.cfg)
            ficha = nova_ficha(g)
            self._imprime(ficha, None)

        # ------------------------------------------------------------ impressao
        def _imprime(self, ficha, volumes, cfg=None):
            if self.ocupado:
                return
            cfg = cfg or self.cfg
            self.ocupado = True
            self.pendente = (ficha, volumes, cfg)
            self.mostra_aviso("Imprimindo %s…" % ficha["id"], "info")

            def trabalho():
                try:
                    imprime(ficha, cfg, volumes, teste=ficha.get("id") == "TESTE")
                    erro = None
                except impressora.ErroImpressora as e:
                    erro = str(e)
                except Exception as e:  # nao deixa a tela travada
                    erro = "Erro inesperado: %s" % e
                    log.exception("Erro inesperado na impressao")
                GLib.idle_add(self._fim_impressao, ficha, volumes, erro)

            threading.Thread(target=trabalho, daemon=True).start()

        def _fim_impressao(self, ficha, volumes, erro):
            self.ocupado = False
            if erro:
                log.warning("Erro de impressao %s: %s", ficha["id"], erro)
                self.erro_msg.set_text(erro)
                self.mostra_aviso("")
                self.vai("erro")
                return
            self.pendente = None
            if ficha["id"] == "TESTE":
                self.mostra_aviso("Teste de impressão enviado. Confira o papel.", "ok")
                return
            qtd = len(volumes) if volumes else ficha["volumes"]
            reimp = ficha["impressoes"] > 0
            ficha["impressoes"] += 1
            ficha["status"] = "impressa"
            atualiza_ficha(ficha)
            if reimp:
                log.info("Reimpressao %s volumes %s", ficha["id"], volumes or "todos")
            self.limpa_ficha()
            self.mostra_aviso("%s %s: %d ficha%s." % ("Reimpressa" if reimp else "Impressa", ficha["id"],
                                                      qtd, "s" if qtd > 1 else ""), "ok")

        # ------------------------------------------------------------ historico
        def abre_historico(self):
            self.mostra_aviso("")
            self.fichas = ultimas_fichas()
            self.lista.clear()
            for i, f in enumerate(self.fichas):
                c = f["criada"]
                self.lista.append(["%03d" % f["seq"], f["nome"], str(f["volumes"]),
                                   "%s/%s %s" % (c[8:10], c[5:7], c[11:16]),
                                   "impressa" if f["status"] == "impressa" else "NÃO IMPRESSA", i])
            self.vai("historico", self.tv)
            if self.fichas:
                self.tv.set_cursor(Gtk.TreePath(0), None, False)
            else:
                self.mostra_aviso("Nenhuma entrega registrada ainda.", "info")

        def _abre_detalhe(self):
            modelo, it = self.tv.get_selection().get_selected()
            if not it:
                return
            self.atual = self.fichas[modelo[it][5]]
            f = self.atual
            self.id_det.set_text(f["id"])
            linhas = ["Cliente:  %s" % f["nome"]]
            if f.get("telefone"):
                linhas.append("Telefone:  %s" % f["telefone"])
            linhas.append("Endereço:  %s" % f["endereco"])
            if f.get("observacao"):
                linhas.append("Observação:  %s" % f["observacao"])
            if f.get("embalador"):
                linhas.append("Embalador(a):  %s" % f["embalador"])
            linhas.append("Volumes:  %d" % f["volumes"] + ("     Caixa:  %s" % f["caixa"] if f.get("caixa") else ""))
            linhas.append("Criada:  %s   (%s, %d %s)" % (
                f["criada"][8:10] + "/" + f["criada"][5:7] + " " + f["criada"][11:16], f["status"],
                f["impressoes"], "impressão" if f["impressoes"] == 1 else "impressões"))
            self.det.set_text("\n\n".join(linhas))
            self.vol_box.hide()
            self.vai("detalhe")

        def _reimprime_volume(self):
            t = self.vol_entry.get_text()
            if not t.isdigit() or not 1 <= int(t) <= self.atual["volumes"]:
                self.mostra_aviso("Volume deve ser de 1 a %d." % self.atual["volumes"], "erro")
                return
            self.vol_box.hide()
            self._imprime(self.atual, [int(t)])

        # ------------------------------------------------------------ config
        def _opcoes_impressora(self):
            opc = [("auto", "Automática (detectar)")] + [
                ("%s:%s" % (d["vid"], d["pid"]), "%s %s" % (d["fabricante"], d["modelo"]))
                for d in impressora.lista_impressoras()]
            if self.cfg["printer"] not in [o[0] for o in opc]:
                opc.append((self.cfg["printer"], self.cfg["printer"] + " (não conectada)"))
            return opc

        def abre_config(self):
            self.mostra_aviso("")
            # Sempre a partir do que esta salvo, com a lista de impressoras atual.
            self.c_imp.define(self._opcoes_impressora(), self.cfg["printer"])
            self.c_larg.define(self.c_larg.opcoes, self.cfg["paper_width"])
            self.c_cod.define(self.c_cod.opcoes, self.cfg["encoding"])
            self.c_dias.define(self.c_dias.opcoes, self.cfg["history_days"])
            imp = impressora.acha_impressora(self.cfg["printer"])
            self.c_info.set_text(
                "Impressora encontrada agora: %s %s (USB %s:%s, driver %s)" % (
                    imp["fabricante"], imp["modelo"], imp["vid"], imp["pid"], imp["driver"] or "livre")
                if imp else "Nenhuma impressora USB encontrada agora.")
            self.c_info.set_text(self.c_info.get_text() + "\nNúmero do caixa impresso na ficha: %s" % (
                numero_caixa(self.cfg) or "não encontrado (defina \"caixa\" no config.json)"))
            self.vai("config", self.c_imp)

        def salva(self):
            self.cfg.update(printer=self.c_imp.valor, paper_width=self.c_larg.valor,
                            encoding=self.c_cod.valor, history_days=self.c_dias.valor)
            salva_config(self.cfg)
            log.info("Configuracao salva: %s", self.cfg)
            self.mostra_aviso("Configurações salvas.", "ok")

        def teste(self):
            # Testa com o que esta na tela, mesmo antes de salvar.
            self._imprime(ficha_teste(self.cfg), None, dict(self.cfg, printer=self.c_imp.valor,
                                                    paper_width=self.c_larg.valor, encoding=self.c_cod.valor))

        # ------------------------------------------------------------ teclado
        def _tecla(self, _w, ev):
            k = Gdk.keyval_name(ev.keyval) or ""
            ctrl = ev.state & Gdk.ModifierType.CONTROL_MASK
            pag = self.stack.get_visible_child_name()
            if self.ocupado:
                return True  # imprimindo: ignora teclas

            if k == "Escape":
                if pag == "ficha":
                    self.esconde()
                elif pag == "detalhe" and self.vol_box.get_visible():
                    self.vol_box.hide()
                    self.vai("detalhe")
                elif pag == "detalhe":
                    self.vai("historico", self.tv)
                elif pag == "confirma":
                    self.vai("ficha", self.entradas["volumes"])
                elif pag == "erro":
                    # A ficha ja foi salva: nao volta com os campos cheios (evita duplicar).
                    f = self.pendente[0] if self.pendente else None
                    self.pendente = None
                    self.limpa_ficha()
                    if f and f["id"] != "TESTE":
                        self.mostra_aviso("%s salva como NÃO IMPRESSA. Reimprima em F2." % f["id"], "erro")
                else:
                    self.mostra_aviso("")
                    self.vai("ficha", self.entradas["nome"])
                return True
            if k == "F3":
                self.mostra_aviso("")
                self.limpa_ficha()
                return True
            if pag == "ficha":
                if ctrl and k in ("Return", "KP_Enter"):
                    self.imprime_nova()
                    return True
                if k == "F2":
                    self.abre_historico()
                    return True
                if k == "F9":
                    self.abre_config()
                    return True
                return False
            if pag == "confirma" and k in ("Return", "KP_Enter"):
                self.imprime_nova()
                return True
            if pag == "erro" and k in ("Return", "KP_Enter") and self.pendente:
                self._imprime(*self.pendente)
                return True
            if pag == "detalhe":
                if self.vol_box.get_visible():
                    return False
                if k in ("Return", "KP_Enter"):
                    self._imprime(self.atual, None)
                    return True
                if k == "F2":
                    self.vol_entry.set_text("")
                    for w in self.vol_box.get_children():
                        w.show()
                    self.vol_box.show()  # show_all() nao funciona com no_show_all
                    self.vol_entry.grab_focus()
                    return True
            if pag == "config":
                if k == "F5":
                    self.teste()
                    return True
                if ctrl and k.lower() == "s":
                    self.salva()
                    return True
            return False

        # ------------------------------------------------------------ mostrar / esconder
        def mostra(self):
            limpa_historico_antigo(self.cfg["history_days"])
            if self.stack.get_visible_child_name() != "ficha" or not self.get_visible():
                self.mostra_aviso("")
                self.vai("ficha")
            self.show_all()
            if not self.aviso.get_text():
                self.aviso.hide()
            self.vol_box.hide()
            self.present()
            # Centraliza e foca (sem gerenciador de janelas, quem foca somos nos)
            GLib.timeout_add(80, self._foca)

        def _foca(self):
            gw = self.get_window()
            if gw is None:
                return True
            larg, alt = self.get_size()
            scr = self.get_screen()
            self.move((scr.get_width() - larg) // 2, max(0, (scr.get_height() - alt) // 2))
            xid = str(gw.get_xid())
            _x("xdotool", "windowraise", xid)
            _x("xdotool", "windowfocus", xid)
            if self.stack.get_visible_child_name() == "ficha":
                self.entradas["nome"].grab_focus()
            return False

        def esconde(self):
            self.hide()
            devolve_foco_pdv()

    def roda(mostrar):
        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
        cfg = carrega_config()
        jan = Janela(cfg)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, lambda: jan.mostra() or True)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: Gtk.main_quit() or False)
        imp = impressora.acha_impressora(cfg["printer"])
        log.info("Impressora detectada: %s", "%s %s (%s:%s)" % (imp["fabricante"], imp["modelo"], imp["vid"],
                                                                imp["pid"]) if imp else "nenhuma")
        if mostrar:
            jan.mostra()
        Gtk.main()

    rodar_gui(roda)


# ======================================================================
# Testes automaticos (sem impressora, sem tela)
# ======================================================================
def testes():
    global BASE, CONFIG, HIST_DIR, LOG_DIR
    import tempfile
    tmp = tempfile.mkdtemp()
    BASE, CONFIG = tmp, os.path.join(tmp, "config.json")
    HIST_DIR, LOG_DIR = os.path.join(tmp, "historico"), os.path.join(tmp, "logs")
    prepara_pastas()
    ok = True

    def confere(nome, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("OK  " if cond else "ERRO"), nome)

    cfg = carrega_config()
    confere("config padrao criada", os.path.exists(CONFIG) and cfg["paper_width"] == 80)
    f1 = nova_ficha({"nome": "João", "telefone": "", "endereco": "Rua A", "observacao": "", "volumes": 1})
    f3 = nova_ficha({"nome": "José da Silva", "telefone": "(74) 99999-9999", "endereco": "Rua São Paulo, 10",
                     "observacao": "Açúcar", "embalador": "Ana", "caixa": "22", "volumes": 3})
    confere("ids sequenciais", f1["id"].endswith("-001") and f3["id"].endswith("-002"))
    confere("teste 1: 1 volume = 1 impressao", len(monta_volumes(f1, [1])) == 1)
    vols = monta_volumes(f3, [1, 2, 3])
    confere("teste 2: 3 volumes = 3 impressoes", len(vols) == 3)
    confere("cada via tem VOLUME X DE 3", all(("VOLUME %d DE 3" % i).encode() in v for i, v in enumerate(vols, 1)))
    confere("cada via tem corte", all(v.count(CORTE) == 1 for v in vols))
    confere("cada via tem caixa e embalador", all(b"CAIXA 22" in v and b"EMBALADOR(A)" in v and b"ANA" in v
                                                  for v in vols))
    confere("caixa pequeno entre numero e data", re.search(rb"ENT-\d+-002   CAIXA 22   \d\d/\d\d/\d{4} ", vols[0]))
    confere("58mm: data quebra de linha", b"CAIXA 22\n" in monta_volumes(f3, [1], 58)[0])
    confere("embalador vazio nao imprime", b"EMBALADOR" not in monta_volumes(f1, [1])[0])
    confere("caixa fixo na config", numero_caixa({"caixa": "7"}) == "7")
    confere("caixa auto (pdv.cfg ou hostname)", numero_caixa({"caixa": "auto"}).isdigit())
    confere("cada via tem nome, telefone e endereco", all(b"JOS" in v and b"99999-9999" in v and b"RUA S" in v
                                                          for v in vols))
    confere("teste 3: acentos em PC860", "JOSÉ AÇÚCAR SÃO".encode("cp860") in
            b"".join(monta_volumes(dict(f3, nome="José Açúcar São"), [1])))
    confere("sem_acento remove acentos", codifica("João Açúcar", "sem_acento") == b"Joao Acucar")
    confere("teste 6: so um volume", len(monta_volumes(f3, [2])) == 1 and b"VOLUME 2 DE 3" in monta_volumes(f3, [2])[0])
    confere("58mm cabe no papel", all(len(l) <= 32 for l in
                                      codifica("=" * 32, "cp860").split(b"\n")))
    confere("historico lista mais recente primeiro", [f["id"] for f in ultimas_fichas()] == [f3["id"], f1["id"]])
    antigo = (dt.date.today() - dt.timedelta(days=40)).isoformat()
    _grava_dia(antigo, [dict(f1, criada=antigo + " 10:00:00")])
    limpa_historico_antigo(30)
    confere("historico antigo removido", not os.path.exists(_arquivo_dia(antigo)))
    print("\nTODOS OK" if ok else "\nFALHOU")
    return 0 if ok else 1


# ======================================================================
def main():
    if "--teste" in sys.argv:
        sys.exit(testes())
    prepara_pastas()
    if "--teste-impressao" in sys.argv:
        cfg = carrega_config()
        try:
            imp = imprime(ficha_teste(cfg), cfg, teste=True)
            print("Teste enviado para %s %s (USB %s:%s)." % (imp["fabricante"], imp["modelo"], imp["vid"], imp["pid"]))
            return
        except impressora.ErroImpressora as e:
            log.warning("Erro no teste de impressao: %s", e)
            print("ERRO DE IMPRESSÃO: %s" % e)
            sys.exit(1)

    # Uma instancia so: se ja houver, so pede para mostrar.
    try:
        with open(PIDFILE) as f:
            pid = int(f.read())
        os.kill(pid, 0)
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            if b"ficha.py" in f.read():
                if "--mostrar" in sys.argv:
                    os.kill(pid, signal.SIGUSR1)
                return
    except (OSError, ValueError):
        pass
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))

    log.info("Aplicacao iniciada (pid %d)", os.getpid())
    try:
        tela(lambda roda: roda("--mostrar" in sys.argv))
    finally:
        log.info("Aplicacao encerrada")
        try:
            os.remove(PIDFILE)
        except OSError:
            pass


if __name__ == "__main__":
    main()
