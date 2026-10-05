"""Impressao ESC/POS direto no USB, compartilhando a impressora com o PDV.

O Arius usa a impressora pelo usbfs (libusb/usb4java): ele "pega" a interface
USB e so solta quando o PDV fecha. Como o PDV e a ficha nunca imprimem ao mesmo
tempo, a ficha pega a impressora emprestada:

  1. acha a impressora no sysfs (qualquer modelo; nao depende de /dev/usb/lpN);
  2. se outro driver estiver com a interface (usbfs do Arius ou usblp),
     solta pelo sysfs (unbind);
  3. pega a interface pelo usbfs, envia os bytes e solta;
  4. devolve como estava: se era o usblp, religa; se era o Arius, nao precisa
     fazer nada, o kernel devolve a interface na proxima impressao dele.

Sem dependencias alem da biblioteca padrao do Python (ioctl via fcntl).
"""
import fcntl
import glob
import os
import struct
import time
import ctypes

SYSFS = "/sys/bus/usb/devices"

# Fabricantes de impressora termica comuns no varejo (idVendor).
FABRICANTES = {
    "04b8": "Epson", "0b1b": "Bematech", "20d1": "Elgin", "0dd4": "Custom",
    "1504": "Bixolon", "0519": "Star", "154f": "SNBC", "0416": "Winbond/Generica",
    "0483": "Generica (STM)", "1fc9": "Generica (NXP)", "28e9": "Generica (GD32)",
    "6868": "Generica", "0fe6": "Generica (ICS)", "1659": "Generica (Prolific)",
    "2730": "Citizen", "1d90": "Citizen",
}

# ioctls do usbfs (linux/usbdevice_fs.h), x86_64
USBDEVFS_CLAIMINTERFACE = 0x8004550F
USBDEVFS_RELEASEINTERFACE = 0x80045510
USBDEVFS_BULK = 0xC0185502


class ErroImpressora(Exception):
    pass


def _le(caminho, padrao=""):
    try:
        with open(caminho) as f:
            return f.read().strip()
    except OSError:
        return padrao


def _driver(intf):
    link = os.path.join(SYSFS, intf, "driver")
    return os.path.basename(os.readlink(link)) if os.path.islink(link) else ""


def _endpoint_saida(intf):
    for ep in sorted(glob.glob(os.path.join(SYSFS, intf, "ep_*"))):
        if _le(ep + "/type") == "Bulk" and _le(ep + "/direction") == "out":
            return int(_le(ep + "/bEndpointAddress"), 16)
    return None


def lista_impressoras():
    """Todas as interfaces USB que parecem impressora termica."""
    achadas = []
    for intf_path in sorted(glob.glob(os.path.join(SYSFS, "*:*"))):
        intf = os.path.basename(intf_path)
        dev = os.path.join(SYSFS, intf.split(":")[0])
        vid, pid = _le(dev + "/idVendor"), _le(dev + "/idProduct")
        classe = _le(intf_path + "/bInterfaceClass")
        if classe != "07" and vid not in FABRICANTES:
            continue
        if classe in ("03", "09", "0e"):  # HID, hub, video: nunca e impressora
            continue
        ep = _endpoint_saida(intf)
        if ep is None:
            continue
        achadas.append({
            "interface": intf,
            "numero": int(_le(intf_path + "/bInterfaceNumber", "0"), 16),
            "vid": vid, "pid": pid,
            "fabricante": _le(dev + "/manufacturer") or FABRICANTES.get(vid, vid),
            "modelo": _le(dev + "/product") or pid,
            "serie": _le(dev + "/serial"),
            "no": "/dev/bus/usb/%03d/%03d" % (int(_le(dev + "/busnum")), int(_le(dev + "/devnum"))),
            "endpoint": ep,
            "driver": _driver(intf),
        })
    # classe 07 primeiro, depois Epson, depois o resto
    achadas.sort(key=lambda d: (_le(os.path.join(SYSFS, d["interface"], "bInterfaceClass")) != "07",
                                d["vid"] != "04b8"))
    return achadas


def acha_impressora(preferida=""):
    """preferida: 'auto' / '' ou 'vid:pid' (ex. 04b8:0202)."""
    todas = lista_impressoras()
    if preferida and preferida != "auto":
        todas = [d for d in todas if "%s:%s" % (d["vid"], d["pid"]) == preferida.lower()] or todas
    return todas[0] if todas else None


def _sysfs_driver(driver, acao, intf):
    with open("/sys/bus/usb/drivers/%s/%s" % (driver, acao), "w") as f:
        f.write(intf)


def envia(dados, preferida="", timeout_ms=5000, tentativas_ocupada=10):
    """Envia bytes ESC/POS. Devolve a impressora usada. Levanta ErroImpressora."""
    imp = acha_impressora(preferida)
    if not imp:
        raise ErroImpressora("Nenhuma impressora USB encontrada.")

    intf, driver_antes = imp["interface"], imp["driver"]

    # Solta a interface de quem estiver com ela (usblp ou o Arius via usbfs).
    if driver_antes:
        try:
            _sysfs_driver(driver_antes, "unbind", intf)
        except OSError as e:
            raise ErroImpressora("Nao consegui liberar a impressora (%s)." % e)

    try:
        fd = os.open(imp["no"], os.O_RDWR)
    except OSError as e:
        _devolve(intf, driver_antes)
        raise ErroImpressora("Nao consegui abrir a impressora (%s)." % e)

    num = struct.pack("I", imp["numero"])
    try:
        # O PDV pode pegar de volta no meio do caminho: tenta algumas vezes.
        for i in range(tentativas_ocupada):
            try:
                fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, num)
                break
            except OSError:
                if i == tentativas_ocupada - 1:
                    raise ErroImpressora("Impressora ocupada pelo PDV. Tente de novo.")
                time.sleep(0.2)
        try:
            enviados = 0
            while enviados < len(dados):
                bloco = dados[enviados:enviados + 4096]
                buf = ctypes.create_string_buffer(bloco, len(bloco))
                req = struct.pack("IIIxxxxQ", imp["endpoint"], len(bloco), timeout_ms,
                                  ctypes.addressof(buf))
                req = bytearray(req)
                try:
                    fcntl.ioctl(fd, USBDEVFS_BULK, req)
                except OSError as e:
                    raise ErroImpressora("A impressora nao respondeu (%s). "
                                         "Verifique se esta ligada e com papel." % e.strerror)
                enviados += len(bloco)
        finally:
            try:
                fcntl.ioctl(fd, USBDEVFS_RELEASEINTERFACE, num)
            except OSError:
                pass
    finally:
        os.close(fd)
        _devolve(intf, driver_antes)
    return imp


def _devolve(intf, driver_antes):
    # usblp precisa ser religado; o usbfs (Arius) se religa sozinho na proxima
    # impressao dele, entao nao mexe.
    if driver_antes and driver_antes != "usbfs":
        try:
            _sysfs_driver(driver_antes, "bind", intf)
        except OSError:
            pass
