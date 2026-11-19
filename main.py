# -*- coding: utf-8 -*-
"""
CHEF STELLATO - Versione Android (Flet)
"""

import os
import re
import sys
import json
import time
import uuid
import hashlib
import threading
import unicodedata
from io import BytesIO
from urllib.parse import urljoin, urlparse, quote
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import flet as ft
from PIL import Image, ImageOps
from ddgs import DDGS
from recipe_scrapers import scrape_html
from deep_translator import GoogleTranslator, MyMemoryTranslator
from bs4 import BeautifulSoup

try:
    from langdetect import detect_langs, DetectorFactory
    DetectorFactory.seed = 0
except Exception:
    detect_langs = None

# ==========================================
# CONFIGURAZIONE DI BASE E PERCORSI ANDROID
# ==========================================

URL_WEB_APP = (
    "https://script.google.com/macros/s/"
    "AKfycbxIg03ij98Xm5vYFl9SPGQpONM-6NofbnKjl4F2sCzZVvfMDnibZJHA"
    "-4i05icycLUF/exec"
)  #[cite: 2]


def _ottieni_cartella_dati():
    for env_var in ("FLET_APP_STORAGE_DATA", "FLET_APP_STORAGE_TEMP"):
        val = os.environ.get(env_var)
        if val:
            os.makedirs(val, exist_ok=True)
            return val
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(base, exist_ok=True)
    return base


CARTELLA_CORRENTE = _ottieni_cartella_dati()
FILE_CONFIG = os.path.join(CARTELLA_CORRENTE, ".config_stellato.json")  #[cite: 2]

TEMPO_MASSIMO_RICERCA = 110  #[cite: 2]
CONVERTI_UNITA_US = True  #[cite: 2]

# ==========================================
# PALETTE COLORI
# ==========================================

COL_BG = "#f8f5f0"  #[cite: 2]
COL_ORO = "#a67c00"  #[cite: 2]
COL_BLU = "#1a3a5a"  #[cite: 2]
COL_ARANCIO = "#b85d0b"  #[cite: 2]
COL_CARD_BG = "#ffffff"  #[cite: 2]
COL_CARD_BORDER = "#e4ddcf"  #[cite: 2]
COL_VERDE_SALVIA = "#6f8f5b"  #[cite: 2]
COL_VERDE_SALVIA_SCURO = "#57724a"  #[cite: 2]

# ==========================================
# UTILITA' DI TESTO E LOG
# ==========================================

def senza_accenti(testo):
    forma = unicodedata.normalize("NFKD", str(testo or ""))
    return "".join(c for c in forma if not unicodedata.combining(c))  #[cite: 2]


def normalizza_spazi(testo):
    return re.sub(r"\s+", " ", str(testo or "")).strip()  #[cite: 2]


def chiave_piatto(testo):
    t = senza_accenti(normalizza_spazi(testo).lower().replace("\u2019", "'"))
    return re.sub(r"\s+", " ", t)  #[cite: 2]


FILE_LOG = os.path.join(CARTELLA_CORRENTE, "chef_stellato.log")  #[cite: 2]
_LOCK_LOG = threading.Lock()  #[cite: 2]


def log(messaggio):
    try:
        with _LOCK_LOG:
            if os.path.exists(FILE_LOG) and os.path.getsize(FILE_LOG) > 2 * 1024 * 1024:
                os.remove(FILE_LOG)
            with open(FILE_LOG, "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(messaggio) + "\n")
    except Exception:
        pass  #[cite: 2]


# ==========================================
# ATTIVAZIONE UNA TANTUM (POI OFFLINE)
# ==========================================

def _leggi_config():
    if not os.path.exists(FILE_CONFIG):
        return {}
    try:
        with open(FILE_CONFIG, "r", encoding="utf-8") as f:
            dati = json.load(f)
            return dati if isinstance(dati, dict) else {}
    except Exception:
        return {}


def _salva_config(dati):
    tmp = FILE_CONFIG + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dati, f, ensure_ascii=False)
        os.replace(tmp, FILE_CONFIG)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def e_gia_attivato():
    cfg = _leggi_config()
    return bool(cfg.get("attivato") and cfg.get("codice"))


def _ottieni_o_crea_token(cfg):
    token = cfg.get("token")
    if not token:
        token = hashlib.sha256(f"chef-stellato|{uuid.uuid4()}".encode("utf-8")).hexdigest()[:32]
        cfg["token"] = token
        _salva_config(cfg)
    return token


def verifica_o_attiva(codice):
    codice_pulito = codice.strip().upper()
    cfg = _leggi_config()
    token = _ottieni_o_crea_token(cfg)
    try:
        url = f"{URL_WEB_APP}?code={quote(codice_pulito)}&token={quote(token)}"  #[cite: 2]
        risposta = requests.get(url, timeout=(5, 12))
        risposta.raise_for_status()
        dati = risposta.json()
        if dati.get("status") == "success":
            cfg["attivato"] = True
            cfg["codice"] = codice_pulito
            cfg["token"] = token
            cfg["attivato_il"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _salva_config(cfg)
            return True, dati.get("message", "Attivazione completata.")  #[cite: 2]
        return False, dati.get("message", "Codice non valido.")  #[cite: 2]
    except requests.Timeout:
        return False, "Il server non ha risposto in tempo. Controlla la connessione."  #[cite: 2]
    except Exception as errore:
        return False, f"Errore di connessione: {errore}"  #[cite: 2]


# ==========================================
# CACHE SU DISCO
# ==========================================

class CacheDisco:
    def __init__(self, nome_file):
        self.percorso = os.path.join(CARTELLA_CORRENTE, nome_file)  #[cite: 2]
        self.lock = threading.RLock()  #[cite: 2]
        self.dati = {}  #[cite: 2]
        try:
            with open(self.percorso, "r", encoding="utf-8") as f:
                letti = json.load(f)
            if isinstance(letti, dict):
                self.dati = letti
        except Exception:
            self.dati = {}  #[cite: 2]

    def get(self, chiave, default=None):
        with self.lock:
            return self.dati.get(chiave, default)  #[cite: 2]

    def set(self, chiave, valore, salva=True):
        with self.lock:
            self.dati[chiave] = valore
        if salva:
            self.salva()  #[cite: 2]

    def valori(self):
        with self.lock:
            return list(self.dati.values())  #[cite: 2]

    def svuota(self):
        with self.lock:
            self.dati.clear()
        self.salva()  #[cite: 2]

    def __len__(self):
        with self.lock:
            return len(self.dati)  #[cite: 2]

    def salva(self):
        tmp = self.percorso + ".tmp"
        try:
            with self.lock:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.dati, f, ensure_ascii=False)
                os.replace(tmp, self.percorso)
        except Exception:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass  #[cite: 2]


CACHE_RICETTE = CacheDisco(".cache_ricette_v2.json")  #[cite: 2]
CACHE_FONTI = CacheDisco(".cache_fonti_v2.json")  #[cite: 2]
CACHE_TRADUZIONI = CacheDisco(".cache_traduzioni_v2.json")  #[cite: 2]

CARTELLA_CACHE_IMMAGINI = os.path.join(CARTELLA_CORRENTE, ".cache_immagini_v2")  #[cite: 2]
os.makedirs(CARTELLA_CACHE_IMMAGINI, exist_ok=True)  #[cite: 2]


def _nome_file(percorso):
    return re.split(r"[\\/]", str(percorso or ""))[-1]  #[cite: 2]


def svuota_cache_ricette(elimina_anche_immagini=True):
    CACHE_RICETTE.svuota()  #[cite: 2]
    if elimina_anche_immagini:
        try:
            for nome in os.listdir(CARTELLA_CACHE_IMMAGINI):
                percorso = os.path.join(CARTELLA_CACHE_IMMAGINI, nome)
                if os.path.isfile(percorso):
                    os.remove(percorso)
        except Exception:
            pass  #[cite: 2]


# ==========================================
# HTTP E RITMO DELLE RICHIESTE
# ==========================================

_thread_local = threading.local()  #[cite: 2]


def sessione_http():
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 13; Mobile) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Mobile Safari/537.36"
            ),
            "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
        })
        adapter = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=1)
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        _thread_local.session = s
    return _thread_local.session  #[cite: 2]


class Ritmo:
    def __init__(self, intervallo):
        self.intervallo = intervallo
        self.lock = threading.Lock()
        self.ultimo = 0.0  #[cite: 2]

    def attendi(self):
        with self.lock:
            attesa = self.ultimo + self.intervallo - time.monotonic()
            if attesa > 0:
                time.sleep(attesa)
            self.ultimo = time.monotonic()  #[cite: 2]


_ESECUTORE_TIMEOUT = ThreadPoolExecutor(max_workers=4)  #[cite: 2]


def esegui_con_timeout(funzione, secondi, *args):
    futuro = _ESECUTORE_TIMEOUT.submit(funzione, *args)
    return futuro.result(timeout=secondi)  #[cite: 2]


# ==========================================
# LINGUA E TRADUZIONE
# ==========================================

URL_GOOGLE = "https://translate.googleapis.com/translate_a/single"  #[cite: 2]
RITMO_TRADUZIONE = Ritmo(0.25)  #[cite: 2]


def testo_sembra_pagina_errore(testo):
    if not testo:
        return False
    basso = str(testo).lower()
    indizi = (
        "error 500", "error 404", "server error", "that's an error",
        "please try again later", "too many requests", "access denied",
        "403 forbidden",
    )
    return any(i in basso for i in indizi)  #[cite: 2]


def lingua_testo(testi, soglia=0.85):
    if detect_langs is None:
        return None
    campione = normalizza_spazi(" ".join(str(t) for t in testi))[:3000]
    if len(campione) < 80:
        return None
    try:
        risultati = detect_langs(campione)
    except Exception:
        return None
    if risultati and risultati[0].prob >= soglia:
        codice = risultati[0].lang
        return {"zh-cn": "zh-CN", "zh-tw": "zh-TW"}.get(codice, codice)
    return None  #[cite: 2]


def lingua_pagina(html):
    m = re.search(r"<html[^>]*\blang\s*=\s*[\"']?([A-Za-z]{2})", str(html)[:6000], re.IGNORECASE)
    return m.group(1).lower() if m else None  #[cite: 2]


def determina_lingua_origine(lingua_dichiarata, testi):
    rilevata = lingua_testo(testi, 0.9)
    if rilevata == "it":
        return "it"
    if rilevata and lingua_dichiarata and rilevata != lingua_dichiarata:
        return "auto"
    return rilevata or lingua_dichiarata or None  #[cite: 2]


_STATO_MOTORI = {
    "google": {"errori": 0, "pausa": 0.0, "soglia": 5, "durata": 25},
    "google_web": {"errori": 0, "pausa": 0.0, "soglia": 3, "durata": 20},
    "google_alt": {"errori": 0, "pausa": 0.0, "soglia": 3, "durata": 20},
    "mymemory": {"errori": 0, "pausa": 0.0, "soglia": 3, "durata": 60},
}
_LOCK_MOTORI = threading.Lock()  #[cite: 2]


def _motore_ok(nome):
    with _LOCK_MOTORI:
        return time.monotonic() >= _STATO_MOTORI[nome]["pausa"]  #[cite: 2]


def _esito_motore(nome, successo, pausa_forzata=None):
    with _LOCK_MOTORI:
        stato = _STATO_MOTORI[nome]
        if successo:
            stato["errori"] = 0
            return
        stato["errori"] += 1
        if pausa_forzata:
            stato["pausa"] = time.monotonic() + pausa_forzata
            stato["errori"] = 0
        elif stato["errori"] >= stato["soglia"]:
            stato["pausa"] = time.monotonic() + stato["durata"]
            stato["errori"] = 0  #[cite: 2]


_PAROLE_INGLESI = {
    "the", "and", "with", "until", "minutes", "stir", "heat", "remove",
    "serve", "place", "into", "over", "from", "cook", "bake", "add", "mix",
    "oven", "salt", "then", "your", "about",
}  #[cite: 2]


def sembra_inglese(testo):
    parole = re.findall(r"[a-z']+", str(testo).lower())
    if len(parole) < 6:
        return False
    n = sum(1 for p in parole if p in _PAROLE_INGLESI)
    return n >= 3 or (n / len(parole)) > 0.25  #[cite: 2]


def traduzione_valida(originale, tradotto, lingua_origine):
    if not tradotto or not str(tradotto).strip():
        return False
    if "MYMEMORY WARNING" in str(tradotto).upper():
        return False
    if testo_sembra_pagina_errore(tradotto) and not testo_sembra_pagina_errore(originale):
        return False
    if len(tradotto) > len(originale) * 4 + 60:
        return False
    o = originale.strip().lower()
    t = str(tradotto).strip().lower()
    if lingua_origine not in ("auto", "it") and t == o and len(o) >= 25 and len(o.split()) >= 4:
        return False
    if lingua_origine != "it" and sembra_inglese(tradotto):
        return False
    return True  #[cite: 2]


def dividi_frasi(testo, limite):
    testo = normalizza_spazi(testo)
    if len(testo) <= limite:
        return [testo]
    pezzi, corrente = [], ""
    for frase in re.split(r"(?<=[.!?;:])\s+", testo):
        while len(frase) > limite:
            taglio = frase.rfind(" ", 0, limite)
            if taglio <= 0:
                taglio = limite
            parte, frase = frase[:taglio].strip(), frase[taglio:].strip()
            if corrente:
                pezzi.append(corrente)
                corrente = ""
            if parte:
                pezzi.append(parte)
        if not frase:
            continue
        if corrente and len(corrente) + 1 + len(frase) > limite:
            pezzi.append(corrente)
            corrente = frase
        else:
            corrente = (corrente + " " + frase).strip()
    if corrente:
        pezzi.append(corrente)
    return pezzi  #[cite: 2]


def _google_testo(testo, lingua_origine):
    parametri = {"client": "gtx", "sl": lingua_origine, "tl": "it", "dt": "t"}
    RITMO_TRADUZIONE.attendi()
    try:
        r = sessione_http().post(URL_GOOGLE, params=parametri, data={"q": testo}, timeout=(4, 15))
        r.raise_for_status()
    except Exception:
        if len(testo) > 900:
            raise
        RITMO_TRADUZIONE.attendi()
        r = sessione_http().get(URL_GOOGLE, params=dict(parametri, q=testo), timeout=(4, 15))
        r.raise_for_status()
    dati = r.json()
    segmenti = dati[0] if isinstance(dati, list) and dati else []
    return "".join(s[0] for s in segmenti if s and s[0])  #[cite: 2]


_ULTIMI_ERRORI = {}  #[cite: 2]
_NOMI_MOTORI = {"google": "Google", "google_web": "Google web", "google_alt": "Google alt", "mymemory": "MyMemory"}  #[cite: 2]


def _ricorda_errore(nome, errore):
    risposta = getattr(errore, "response", None)
    if risposta is not None and getattr(risposta, "status_code", None):
        dettaglio = f"HTTP {risposta.status_code}"
    else:
        dettaglio = type(errore).__name__
        messaggio = str(errore).strip()
        if messaggio:
            dettaglio += f" ({messaggio[:60]})"
    _ULTIMI_ERRORI[nome] = dettaglio
    log(f"traduzione {nome}: {dettaglio}")  #[cite: 2]


def riepilogo_errori_traduzione():
    return " | ".join(f"{_NOMI_MOTORI.get(k, k)}: {v}" for k, v in list(_ULTIMI_ERRORI.items()))  #[cite: 2]


def _traduci_con_google(testi, lingua_origine, scaduto=None):
    out = [None] * len(testi)
    gruppi, corrente, lunghezza = [], [], 0
    for i, t in enumerate(testi):
        if corrente and (lunghezza + len(t) + 1 > 2800 or len(corrente) >= 30):
            gruppi.append(corrente)
            corrente, lunghezza = [], 0
        corrente.append(i)
        lunghezza += len(t) + 1
    if corrente:
        gruppi.append(corrente)

    for gruppo in gruppi:
        if (scaduto and scaduto()) or not _motore_ok("google"):
            break
        blocco = "\n".join(testi[i] for i in gruppo)
        try:
            risultato = _google_testo(blocco, lingua_origine)
            parti = risultato.split("\n")
            if len(parti) == len(gruppo):
                for i, p in zip(gruppo, parti):
                    out[i] = normalizza_spazi(p)
                _esito_motore("google", True)
                _ULTIMI_ERRORI.pop("google", None)
                continue
        except Exception as errore:
            _ricorda_errore("google", errore)
            _esito_motore("google", False)
        for i in gruppo:
            if (scaduto and scaduto()) or not _motore_ok("google"):
                break
            try:
                out[i] = normalizza_spazi(_google_testo(testi[i], lingua_origine))
                _esito_motore("google", True)
                _ULTIMI_ERRORI.pop("google", None)
            except Exception as errore:
                _ricorda_errore("google", errore)
                _esito_motore("google", False)
    return out  #[cite: 2]


def _grezzo_google_web(testo, lingua_origine):
    def lavora(pezzo):
        try:
            return GoogleTranslator(source=lingua_origine, target="it").translate(pezzo)
        except Exception as errore:
            if "language" in type(errore).__name__.lower() and lingua_origine != "auto":
                return GoogleTranslator(source="auto", target="it").translate(pezzo)
            raise
    RITMO_TRADUZIONE.attendi()
    return " ".join(str(esegui_con_timeout(lavora, 15, p) or "") for p in dividi_frasi(testo, 4000))  #[cite: 2]


def _grezzo_google_alt(testo, lingua_origine):
    pezzi = []
    for pezzo in dividi_frasi(testo, 800):
        RITMO_TRADUZIONE.attendi()
        r = sessione_http().get(
            "https://clients5.google.com/translate_a/t",
            params={"client": "dict-chrome-ex", "sl": lingua_origine, "tl": "it", "dt": "t", "q": pezzo},
            timeout=(4, 12),
        )
        r.raise_for_status()
        dati = r.json()
        if isinstance(dati, dict):
            pezzi.append("".join(x.get("trans", "") for x in dati.get("sentences", []) if isinstance(x, dict)))
        elif isinstance(dati, list) and dati:
            primo = dati[0]
            if isinstance(primo, list) and primo:
                primo = primo[0]
            pezzi.append(primo if isinstance(primo, str) else "")
    return " ".join(pezzi)  #[cite: 2]


def _crea_mymemory():
    ultimo_errore = None
    for destinazione in ("italian", "it-IT", "it"):
        try:
            return MyMemoryTranslator(source="auto", target=destinazione)
        except Exception as errore:
            ultimo_errore = errore
    raise ultimo_errore  #[cite: 2]


def _grezzo_mymemory(testo, lingua_origine=None):
    pezzi = []
    for pezzo in dividi_frasi(testo, 450):
        RITMO_TRADUZIONE.attendi()
        traduttore = _crea_mymemory()
        tradotto = normalizza_spazi(esegui_con_timeout(traduttore.translate, 8, pezzo))
        if "MYMEMORY WARNING" in tradotto.upper():
            raise RuntimeError("quota giornaliera esaurita")
        if not tradotto:
            raise RuntimeError("risposta vuota")
        pezzi.append(tradotto)
    return " ".join(pezzi)  #[cite: 2]


_MOTORI_RISERVA = (
    ("google_web", _grezzo_google_web),
    ("google_alt", _grezzo_google_alt),
    ("mymemory", _grezzo_mymemory),
)  #[cite: 2]


def _prova_motore(nome, funzione, testo, lingua_origine):
    if not _motore_ok(nome):
        return None
    try:
        risultato = normalizza_spazi(funzione(testo, lingua_origine))
        if not risultato:
            raise RuntimeError("risposta vuota")
        _esito_motore(nome, True)
        _ULTIMI_ERRORI.pop(nome, None)
        return risultato
    except Exception as errore:
        _ricorda_errore(nome, errore)
        quota = nome == "mymemory" and "quota" in str(errore).lower()
        _esito_motore(nome, False, pausa_forzata=3600 if quota else None)
        return None  #[cite: 2]


def _attendi_motori(scaduto, massimo=30):
    with _LOCK_MOTORI:
        ora = time.monotonic()
        riprese = [st["pausa"] for st in _STATO_MOTORI.values()]
    if not riprese or any(p <= ora for p in riprese):
        return
    fine = min(riprese)
    if fine - ora > massimo:
        return
    while time.monotonic() < fine:
        if scaduto and scaduto():
            return
        time.sleep(0.5)  #[cite: 2]


def _chiave_traduzione(lingua_origine, testo):
    return hashlib.sha1(f"{lingua_origine}|{testo}".encode("utf-8")).hexdigest()  #[cite: 2]


def traduci_testi(testi, lingua_origine, scaduto=None):
    righe = [normalizza_spazi(t) for t in testi]
    segmenti = []
    for i, riga in enumerate(righe):
        if riga:
            for pezzo in dividi_frasi(riga, 1500):
                segmenti.append((i, pezzo))

    tradotti = [None] * len(segmenti)
    da_fare = []
    for k, (_, pezzo) in enumerate(segmenti):
        in_cache = CACHE_TRADUZIONI.get(_chiave_traduzione(lingua_origine, pezzo))
        if in_cache:
            tradotti[k] = in_cache
        else:
            da_fare.append(k)

    if da_fare:
        _attendi_motori(scaduto)
        risultati = _traduci_con_google([segmenti[k][1] for k in da_fare], lingua_origine, scaduto)
        for k, r in zip(da_fare, risultati):
            if r and traduzione_valida(segmenti[k][1], r, lingua_origine):
                tradotti[k] = r

        for passaggio in range(2):
            mancanti = [k for k in da_fare if tradotti[k] is None]
            if not mancanti or (scaduto and scaduto()):
                break
            if passaggio == 1:
                _attendi_motori(scaduto)
            for k in mancanti:
                if scaduto and scaduto():
                    break
                for nome, funzione in _MOTORI_RISERVA:
                    r = _prova_motore(nome, funzione, segmenti[k][1], lingua_origine)
                    if r and traduzione_valida(segmenti[k][1], r, lingua_origine):
                        tradotti[k] = r
                        break

        for k in da_fare:
            if tradotti[k]:
                CACHE_TRADUZIONI.set(_chiave_traduzione(lingua_origine, segmenti[k][1]), tradotti[k], salva=False)
        CACHE_TRADUZIONI.salva()

    servizio_ok = not (da_fare and all(tradotti[k] is None for k in da_fare))
    parti_per_riga = {}
    for k, (i, _) in enumerate(segmenti):
        parti_per_riga.setdefault(i, []).append(tradotti[k])

    out, falliti = [], 0
    for i, riga in enumerate(righe):
        if not riga:
            out.append("")
            continue
        parti = parti_per_riga[i]
        if any(p is None for p in parti):
            out.append(riga)
            falliti += 1
        else:
            out.append(" ".join(parti))
    return out, falliti == 0, servizio_ok, falliti  #[cite: 2]


# ==========================================
# CONVERSIONE UNITA' ANGLOSASSONI -> METRICHE
# ==========================================

_FRAZIONI = {
    "½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3,
    "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875,
}  #[cite: 2]
_SIMBOLI_FRAZ = "".join(_FRAZIONI.keys())  #[cite: 2]
_N = (
    r"(\d+\s+\d+/\d+|\d+/\d+|\d+\s?[" + _SIMBOLI_FRAZ + r"]|[" + _SIMBOLI_FRAZ +
    r"]|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
)  #[cite: 2]


def _valore_numerico(testo):
    s = testo.strip()
    try:
        for simbolo, valore in _FRAZIONI.items():
            if simbolo in s:
                resto = s.replace(simbolo, "").strip()
                return (float(resto) if resto else 0.0) + valore
        if re.fullmatch(r"\d+\s+\d+/\d+", s):
            intero, frazione = s.split(None, 1)
            n, d = frazione.split("/")
            return int(intero) + int(n) / int(d)
        if "/" in s:
            n, d = s.split("/")
            return int(n) / int(d)
        return float(s.replace(",", ""))
    except Exception:
        return None  #[cite: 2]


def _num_it(valore):
    if valore >= 100:
        valore = round(valore / 5.0) * 5
        return str(int(valore))
    if valore >= 10:
        return str(int(round(valore)))
    testo = f"{valore:.1f}"
    if testo.endswith(".0"):
        testo = testo[:-2]
    return testo.replace(".", ",")  #[cite: 2]


def _crea_sostituzione(fattore, unita_piccola, unita_grande=None, soglia_grande=1000):
    def sostituisci(m):
        b = _valore_numerico(m.group(2))
        if b is None:
            return m.group(0)
        a = _valore_numerico(m.group(1)) if m.group(1) else None
        b *= fattore
        a = a * fattore if a is not None else None
        unita = unita_piccola
        if unita_grande and b >= soglia_grande:
            b, unita = b / 1000.0, unita_grande
            a = a / 1000.0 if a is not None else None
        if a is not None:
            return f"{_num_it(a)}-{_num_it(b)} {unita}"
        return f"{_num_it(b)} {unita}"
    return sostituisci  #[cite: 2]


def _pattern_unita(unita):
    return re.compile(
        r"(?<![\w/.])(?:" + _N + r"\s*(?:-|–|—|to)\s*)?" + _N + r"\s*-?\s*(?:" + unita + r")(?![A-Za-z])",
        re.IGNORECASE,
    )  #[cite: 2]


_CONVERSIONI = [
    (_pattern_unita(r"fl\.?\s*oz\.?|fluid\s+ounces?"), _crea_sostituzione(29.5735, "ml", "l")),
    (_pattern_unita(r"oz\.?|ounces?"), _crea_sostituzione(28.3495, "g", "kg")),
    (_pattern_unita(r"lbs?\.?|pounds?"), _crea_sostituzione(453.592, "g", "kg")),
    (_pattern_unita(r"cups?"), _crea_sostituzione(240.0, "ml", "l")),
]  #[cite: 2]

_RE_F_CON_C = [
    re.compile(r"(?<![\d.])\d{2,3}\s*(?:°|º|˚)\s*F\s*(?:\(\s*|/\s*)(\d{2,3})\s*(?:°|º|˚)?\s*C\s*\)?"),
    re.compile(r"(?<![\d.])\d{2,3}\s*degrees?\s*F\s*\(\s*(\d{2,3})\s*degrees?\s*C\s*\)", re.IGNORECASE),
]  #[cite: 2]
_RE_FAHRENHEIT = [
    re.compile(r"(?<![\d.])(\d{2,3})\s*(?:°|º|˚)\s*F(?![A-Za-z])"),
    re.compile(r"(?<![\d.])(\d{2,3})\s*degrees?\s*(?:F(?![A-Za-z])|Fahrenheit)", re.IGNORECASE),
    re.compile(r"(?<![\d.])(\d{2,3})\s*(?:°|º|˚)?\s*Fahrenheit", re.IGNORECASE),
]  #[cite: 2]
_RE_POLLICI_X = re.compile(
    r"(?<![\w/.])" + _N + r"\s*(?:x|×|by)\s*" + _N + r"\s*-?\s*(?:inch(?:es)?|in\.)(?![A-Za-z])",
    re.IGNORECASE,
)  #[cite: 2]
_RE_POLLICI = re.compile(
    r"(?<![\w/.])" + _N + r"\s*-?\s*(?:inch(?:es)?|in\.)(?![A-Za-z])",
    re.IGNORECASE,
)  #[cite: 2]
_RE_DOPPIO_METRICO = re.compile(
    r"\d[\d,\-]*\s(?:g|kg|ml|l)\s*\(\s*([\d.,\-]+\s*(?:g|grams?|kg|ml|l|litres?|liters?))\s*\)",
    re.IGNORECASE,
)  #[cite: 2]
_RE_DOPPIO_CELSIUS = re.compile(r"(\d+ °C)\s*\(\s*\d{2,3}\s*(?:°|º|˚)?\s*C\s*\)")  #[cite: 2]


def _cm(valore):
    cm = valore * 2.54
    return str(int(round(cm))) if cm >= 10 else _num_it(round(cm * 2) / 2)  #[cite: 2]


def converti_unita_us(testo):
    t = str(testo)
    if not re.search(r"oz|ounce|lb|pound|cup|°|º|˚|degree|fahrenheit|inch|in\.", t, re.IGNORECASE):
        return t
    for modello, funzione in _CONVERSIONI:
        t = modello.sub(funzione, t)

    def fahrenheit(m):
        gradi_f = int(m.group(1))
        gradi_c = round((gradi_f - 32) * 5 / 9 / 5.0) * 5
        return f"{int(gradi_c)} °C"

    for modello in _RE_F_CON_C:
        t = modello.sub(lambda m: f"{m.group(1)} °C", t)
    for modello in _RE_FAHRENHEIT:
        t = modello.sub(fahrenheit, t)

    def pollici_x(m):
        a, b = _valore_numerico(m.group(1)), _valore_numerico(m.group(2))
        if a is None or b is None:
            return m.group(0)
        return f"{_cm(a)} x {_cm(b)} cm"

    def pollici(m):
        v = _valore_numerico(m.group(1))
        return f"{_cm(v)} cm" if v is not None else m.group(0)

    t = _RE_POLLICI_X.sub(pollici_x, t)
    t = _RE_POLLICI.sub(pollici, t)
    t = _RE_DOPPIO_METRICO.sub(r"\1", t)
    t = _RE_DOPPIO_CELSIUS.sub(r"\1", t)
    return t  #[cite: 2]


# ==========================================
# IMMAGINI, ESTRAZIONE E RICERCA
# ==========================================

def normalizza_url_immagine(url_immagine, url_pagina):
    if not url_immagine:
        return None
    url_immagine = str(url_immagine).strip()
    if not url_immagine or url_immagine.startswith("data:"):
        return None
    if url_immagine.startswith("//"):
        return "https:" + url_immagine
    return urljoin(url_pagina, url_immagine)  #[cite: 2]


def _immagine_da_valore(valore, url_pagina):
    if isinstance(valore, list) and valore:
        valore = valore[0]
    if isinstance(valore, dict):
        valore = valore.get("url") or valore.get("contentUrl")
    return normalizza_url_immagine(valore, url_pagina) if valore else None  #[cite: 2]


def estrai_immagine_da_html(html, url_pagina):
    try:
        soup = BeautifulSoup(html, "html.parser")
        for nome_tag, attributi, attributo_url in (
            ("meta", {"property": "og:image"}, "content"),
            ("meta", {"property": "og:image:url"}, "content"),
            ("meta", {"name": "twitter:image"}, "content"),
            ("meta", {"property": "twitter:image"}, "content"),
            ("link", {"rel": "image_src"}, "href"),
        ):
            tag = soup.find(nome_tag, attributi)
            if tag and tag.get(attributo_url):
                url = normalizza_url_immagine(tag.get(attributo_url), url_pagina)
                if url:
                    return url
    except Exception:
        pass
    return None  #[cite: 2]


def percorso_cache_immagine(url_immagine):
    digest = hashlib.sha256(str(url_immagine).encode("utf-8")).hexdigest()[:24]
    return os.path.join(CARTELLA_CACHE_IMMAGINI, digest + ".jpg")  #[cite: 2]


def scarica_e_salva_immagine(url_immagine, url_pagina=""):
    url_immagine = normalizza_url_immagine(url_immagine, url_pagina)
    if not url_immagine:
        return None
    percorso = percorso_cache_immagine(url_immagine)
    if os.path.exists(percorso) and os.path.getsize(percorso) > 0:
        return percorso
    tmp = percorso + ".tmp.jpg"
    try:
        risposta = sessione_http().get(
            url_immagine, timeout=(5, 15), allow_redirects=True,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                     "Referer": url_pagina or ""},
        )
        risposta.raise_for_status()
        tipo = risposta.headers.get("Content-Type", "").lower()
        if tipo and "image" not in tipo and "octet-stream" not in tipo:
            return None
        if not risposta.content or len(risposta.content) > 15 * 1024 * 1024:
            return None
        immagine = Image.open(BytesIO(risposta.content))
        immagine.load()
        immagine = ImageOps.exif_transpose(immagine)
        larghezza, altezza = immagine.size
        if min(larghezza, altezza) < 200 or larghezza * altezza < 60000:
            return None
        if max(larghezza, altezza) > 3 * min(larghezza, altezza):
            return None
        if immagine.mode in ("RGBA", "LA") or (immagine.mode == "P" and "transparency" in immagine.info):
            immagine = immagine.convert("RGBA")
            sfondo = Image.new("RGB", immagine.size, (255, 255, 255))
            sfondo.paste(immagine, mask=immagine.split()[-1])
            immagine = sfondo
        else:
            immagine = immagine.convert("RGB")
        if max(immagine.size) > 1200:
            immagine.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
        immagine.save(tmp, "JPEG", quality=88, optimize=True)
        os.replace(tmp, percorso)
        return percorso
    except Exception as errore:
        log(f"immagine scartata {url_immagine}: {type(errore).__name__}: {errore}")
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return None  #[cite: 2]


def ottieni_immagine_locale(dati):
    percorso = dati.get("immagine_locale")
    if percorso and os.path.exists(percorso) and os.path.getsize(percorso) > 0:
        return percorso
    if percorso:
        locale = os.path.join(CARTELLA_CACHE_IMMAGINI, _nome_file(percorso))
        if os.path.exists(locale) and os.path.getsize(locale) > 0:
            dati["immagine_locale"] = locale
            return locale
    url = dati.get("immagine")
    if not url:
        return None
    percorso = scarica_e_salva_immagine(url, dati.get("fonte_immagine") or dati.get("fonte", ""))
    if percorso:
        dati["immagine_locale"] = percorso
        if dati.get("chiave"):
            CACHE_RICETTE.set(dati["chiave"], dati)
    return percorso  #[cite: 2]


_STOP = {
    "recipe", "recipes", "ricetta", "ricette", "receta", "recetas", "rezept", "recette",
    "how", "make", "with", "the", "and", "for", "from", "best", "easy", "classic", "authentic",
    "traditional", "original", "homemade", "style", "ingredienti", "ingredients", "procedimento",
    "tradizionale", "originale", "della", "dello", "delle", "degli", "alla", "alle", "allo",
    "agli", "con", "del", "dei", "nel", "nei", "per", "una", "uno", "les", "des", "aux", "sur",
    "der", "die", "das", "dem", "und", "mit", "von", "los", "las", "por", "para",
    "que", "recept", "kak", "для", "как", "по", "из", "рецепт", "классический",
}  #[cite: 2]
_VOCALI_FINALI = set("aeiouys" + "аеёиоуыэюяьй")  #[cite: 2]


def _token(testo):
    t = senza_accenti(str(testo).lower().replace("\u2019", "'"))
    return [p for p in re.findall(r"[a-z0-9\u0400-\u04ff]+", t) if len(p) > 2 and p not in _STOP]  #[cite: 2]


def _radice(parola):
    if len(parola) > 4 and parola[-1] in _VOCALI_FINALI:
        return parola[:-1]
    return parola  #[cite: 2]


def _uguali(a, b):
    if a == b:
        return True
    corta, lunga = (a, b) if len(a) <= len(b) else (b, a)
    return len(corta) >= 3 and lunga.startswith(corta) and len(lunga) - len(corta) <= 2  #[cite: 2]


def rilevanza(testo, varianti):
    nel_testo = [_radice(p) for p in _token(testo)]
    if not nel_testo:
        return 0.0
    migliore = 0.0
    for variante in varianti:
        parole = [_radice(p) for p in _token(variante)]
        if not parole:
            continue
        trovate = sum(1 for p in parole if any(_uguali(p, q) for q in nel_testo))
        migliore = max(migliore, trovate / len(parole))
    return migliore  #[cite: 2]


SOGLIA_RILEVANZA = 0.5  #[cite: 2]


def chiama_metodo(scraper, nome_metodo, default):
    try:
        metodo = getattr(scraper, nome_metodo, None)
        if metodo:
            return metodo()
    except Exception:
        pass
    return default  #[cite: 2]


def spezza_in_step(istruzioni):
    if not istruzioni:
        return []
    if isinstance(istruzioni, str):
        return [s.strip() for s in istruzioni.split("\n") if s.strip()]
    passi = []
    if isinstance(istruzioni, list):
        for s in istruzioni:
            if isinstance(s, str):
                testo = s
            elif isinstance(s, dict):
                testo = s.get("text") or s.get("content") or s.get("name") or ""
            else:
                testo = ""
            if isinstance(testo, str) and testo.strip():
                passi.append(testo.strip())
    return passi  #[cite: 2]


def _pulisci_passi(passi):
    puliti = []
    for passo in passi:
        passo = normalizza_spazi(passo)
        if re.fullmatch(r"(?:step\s*)?\d{1,2}\.?", passo, re.IGNORECASE):
            continue
        passo = re.sub(r"^(?:step\s*)?\d{1,2}\s*[.):\-]\s+", "", passo, flags=re.IGNORECASE)
        if passo and not testo_sembra_pagina_errore(passo):
            puliti.append(passo)
    if len(puliti) == 1 and len(puliti[0]) > 600:
        frasi = re.split(r"(?<=[.!?])\s+", puliti[0])
        gruppi, corrente = [], ""
        for frase in frasi:
            if corrente and len(corrente) + len(frase) > 260:
                gruppi.append(corrente)
                corrente = frase
            else:
                corrente = (corrente + " " + frase).strip()
        if corrente:
            gruppi.append(corrente)
        puliti = gruppi
    return puliti  #[cite: 2]


def _normalizza_tempo_ricetta(valore):
    if valore is None:
        return None
    if isinstance(valore, (int, float)):
        return str(int(valore)) if valore > 0 else None
    testo = str(valore).strip()
    if not testo:
        return None
    m = re.fullmatch(r"P(?:\d+D)?T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?", testo.upper())
    if m:
        totale = int(round(float(m.group(1) or 0) * 60 + float(m.group(2) or 0) + float(m.group(3) or 0) / 60))
        return str(totale) if totale > 0 else None
    m = re.search(r"(\d+)\s*(?:h|ore?|hours?|std|heures?)\s*(?:e|and|und|et)?\s*(\d+)?\s*(?:m|min|mins|minuti?|minutes?)?", testo, re.IGNORECASE)
    if m:
        return str(int(m.group(1)) * 60 + int(m.group(2) or 0))
    m = re.search(r"(\d+)\s*(?:m|min|mins|minuti?|minutes?)", testo, re.IGNORECASE)
    if m:
        return str(int(m.group(1)))
    if re.fullmatch(r"\d+(?:\.0+)?", testo):
        return str(int(float(testo))) if float(testo) > 0 else None
    return None  #[cite: 2]


def _trova_recipe_jsonld(html):
    def cerca(nodo):
        if isinstance(nodo, dict):
            tipo = nodo.get("@type", [])
            tipi = [tipo] if isinstance(tipo, str) else (tipo or [])
            if "Recipe" in tipi:
                return nodo
            for v in nodo.values():
                if isinstance(v, (dict, list)):
                    r = cerca(v)
                    if r:
                        return r
        elif isinstance(nodo, list):
            for v in nodo:
                r = cerca(v)
                if r:
                    return r
        return None
    try:
        soup = BeautifulSoup(html, "html.parser")
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                contenuto = json.loads(script.get_text(strip=True))
            except Exception:
                continue
            r = cerca(contenuto)
            if r:
                return r
    except Exception:
        pass
    return None  #[cite: 2]


def _etichette_testuali(html):
    out = {"difficolta": None, "prep": None, "cottura": None}
    try:
        testo = normalizza_spazi(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
        m = re.search(r"difficolt[aà]\s*[:\-]?\s*(facilissim[ao]|facile|medio[\s-]+facile|medi[ao]|medio[\s-]+difficile|difficile)", testo, re.IGNORECASE)
        if m:
            out["difficolta"] = m.group(1)
        tempo = r"(\d+(?:\s*(?:h|ore?|min|minuti?))?(?:\s*(?:e|\+)\s*\d+\s*(?:min|minuti?))?)"
        m = re.search(r"preparazione\s*[:\-]?\s*" + tempo, testo, re.IGNORECASE)
        if m:
            out["prep"] = _normalizza_tempo_ricetta(m.group(1))
        m = re.search(r"cottura\s*[:\-]?\s*" + tempo, testo, re.IGNORECASE)
        if m:
            out["cottura"] = _normalizza_tempo_ricetta(m.group(1))
    except Exception:
        pass
    return out  #[cite: 2]


_INDIZI_SEGNAPOSTO = (
    "placeholder", "no-image", "noimage", "no_image", "immagine-non-disponibile",
    "image-not-available", "default-image", "coming-soon", "logo",
)  #[cite: 2]
_RE_SOLO_QUANTITA = re.compile(
    r"^[\d/.,]+\s*(g|gr|kg|mg|ml|cl|dl|l|lt|oz|lb|pz|pezzi?|cucchiai?o?|cucchiaini?|tazze?|bicchiere|pizzico|"
    r"confezion[ei]|spicch(?:io|i)|foglia|foglie|ramett[oi]|fett[ae])?\s*(di)?\.?$",
    re.IGNORECASE,
)  #[cite: 2]


def _crea_scraper(html, url):
    for argomenti in ({"wild_mode": True}, {"supported_only": False}, {}):
        try:
            return scrape_html(html, org_url=url, **argomenti)
        except TypeError:
            continue
        except Exception:
            return None
    return None  #[cite: 2]


def analizza_pagina(url_finale, html):
    titolo, ingredienti, istruzioni = "", [], []
    difficolta = prep = cottura = totale = immagine = None

    scraper = _crea_scraper(html, url_finale)
    if scraper:
        titolo = chiama_metodo(scraper, "title", "") or ""
        ingredienti = chiama_metodo(scraper, "ingredients", []) or []
        istruzioni = chiama_metodo(scraper, "instructions_list", None) or chiama_metodo(scraper, "instructions", None) or []
        difficolta = chiama_metodo(scraper, "difficulty", None)
        prep = chiama_metodo(scraper, "prep_time", None)
        cottura = chiama_metodo(scraper, "cook_time", None)
        totale = chiama_metodo(scraper, "total_time", None)
        immagine = normalizza_url_immagine(chiama_metodo(scraper, "image", None), url_finale)

    jl = _trova_recipe_jsonld(html)
    if jl:
        if not str(titolo).strip():
            titolo = str(jl.get("name") or "").strip()
        ing_jl = jl.get("recipeIngredient") or jl.get("ingredients") or []
        if isinstance(ing_jl, str):
            ing_jl = [i for i in ing_jl.split("\n") if i.strip()]
        if len([i for i in ingredienti if str(i).strip()]) < 2:
            ingredienti = [str(i).strip() for i in ing_jl if str(i).strip()]
        if not istruzioni:
            raw = jl.get("recipeInstructions") or []
            if isinstance(raw, str):
                istruzioni = spezza_in_step(raw)
            elif isinstance(raw, list):
                passi = []
                for s in raw:
                    if isinstance(s, dict) and isinstance(s.get("itemListElement"), list):
                        passi.extend(spezza_in_step(s["itemListElement"]))
                    else:
                        passi.extend(spezza_in_step([s]))
                istruzioni = passi
        difficolta = difficolta or jl.get("difficulty") or jl.get("recipeDifficulty")
        prep = prep or jl.get("prepTime")
        cottura = cottura or jl.get("cookTime")
        totale = totale or jl.get("totalTime")
        if not immagine:
            immagine = _immagine_da_valore(jl.get("image"), url_finale)
    if not immagine:
        immagine = estrai_immagine_da_html(html, url_finale)

    titolo = normalizza_spazi(titolo)
    if not titolo or testo_sembra_pagina_errore(titolo):
        return None

    passi = _pulisci_passi(spezza_in_step(istruzioni))
    if not passi:
        return None

    puliti = []
    for ing in ingredienti or []:
        ing = normalizza_spazi(ing)
        if not ing or testo_sembra_pagina_errore(ing) or _RE_SOLO_QUANTITA.match(ing):
            continue
        puliti.append(re.sub(r"\b(\d+)\.0+\b", r"\1", ing))
    if len(puliti) < 2:
        return None

    if not (difficolta and prep and cottura):
        extra = _etichette_testuali(html)
        difficolta = difficolta or extra["difficolta"]
        prep = prep or extra["prep"]
        cottura = cottura or extra["cottura"]

    prep_min = _normalizza_tempo_ricetta(prep)
    cott_min = _normalizza_tempo_ricetta(cottura)
    tot_min = _normalizza_tempo_ricetta(totale)
    if not cott_min and prep_min and tot_min and int(tot_min) > int(prep_min):
        cott_min = str(int(tot_min) - int(prep_min))

    if immagine and any(i in str(immagine).lower() for i in _INDIZI_SEGNAPOSTO):
        immagine = None

    return {
        "titolo_originale": titolo,
        "ingredienti_originali": puliti,
        "istruzioni_originali": passi,
        "difficolta_originale": difficolta,
        "tempo_prep": prep_min,
        "tempo_cottura": cott_min,
        "immagine": immagine,
        "fonte": url_finale,
        "lingua_pagina": lingua_pagina(html),
    }  #[cite: 2]


def scarica_pagina(url):
    try:
        r = sessione_http().get(url, timeout=(4, 9), allow_redirects=True)
        r.raise_for_status()
        tipo = r.headers.get("Content-Type", "").lower()
        if tipo and "html" not in tipo and "xml" not in tipo:
            return None
        if len(r.content) > 6_000_000:
            return None
        if not r.encoding or (r.encoding.lower() in ("iso-8859-1", "latin-1") and "charset" not in tipo):
            r.encoding = r.apparent_encoding or "utf-8"
        return r.url or url, r.text
    except Exception as errore:
        log(f"pagina non scaricabile {url}: {type(errore).__name__}")
        return None  #[cite: 2]


class Piatto:
    def __init__(self, etichetta, ita, orig=None, eng=None, nazione=None):
        self.etichetta = etichetta
        self.ita = ita
        self.orig = orig
        self.eng = eng
        self.nazione = nazione
        self.chiave = chiave_piatto(f"{nazione}:{etichetta}" if nazione else etichetta)

    @property
    def varianti(self):
        visti, out = set(), []
        for v in (self.ita, self.orig, self.eng):
            if v and chiave_piatto(v) not in visti:
                visti.add(chiave_piatto(v))
                out.append(v)
        return out  #[cite: 2]


DOMINI_ITALIANI = (
    "giallozafferano.it", "cucchiaio.it", "lacucinaitaliana.it", "fattoincasadabenedetta.it",
    "buonissimo.org", "sale-pepe.it", "cookaround.com", "misya.info", "tavolartegusto.it",
    "ricetteperbimby.it", "agrodolce.it", "donnamoderna.com", "dissapore.com", "galbani.it",
)  #[cite: 2]
DOMINI_ESTERI = (
    "bbcgoodfood.com", "seriouseats.com", "allrecipes.com", "simplyrecipes.com", "recipetineats.com",
    "foodnetwork.com", "bonappetit.com", "epicurious.com", "jamieoliver.com", "themediterraneandish.com",
    "marmiton.org", "cuisineaz.com", "chefkoch.de", "gutekueche.at", "recetasgratis.net",
    "directoalpaladar.com", "pinchofyum.com", "natashaskitchen.com", "povar.ru", "eda.ru",
    "russianfood.com", "tasty.co", "food.com", "delish.com", "thespruceeats.com",
)  #[cite: 2]
DOMINI_ESCLUSI = (
    "pinterest", "youtube", "youtu.be", "facebook", "instagram", "tiktok", "twitter.",
    "x.com", "reddit", "amazon", "ebay", "wikipedia", "tripadvisor", "cookidoo",
    "blog.giallozafferano.it", ".pdf",
)  #[cite: 2]


def bonus_dominio(url, italiano):
    u = str(url).lower()
    primaria, secondaria = (DOMINI_ITALIANI, DOMINI_ESTERI) if italiano else (DOMINI_ESTERI, DOMINI_ITALIANI)
    for i, d in enumerate(primaria):
        if d in u:
            return max(12, 40 - i)
    for d in secondaria:
        if d in u:
            return 8
    return 0  #[cite: 2]


def punteggio_ricetta(r, posizione, rilev, italiano):
    s = 100 - 3 * posizione + bonus_dominio(r["fonte"], italiano) + 60 * rilev
    if r.get("immagine"):
        s += 30
    if len(r["ingredienti_originali"]) >= 4:
        s += 8
    if len(r["istruzioni_originali"]) >= 3:
        s += 8
    return s  #[cite: 2]


RITMO_RICERCA = Ritmo(0.9)  #[cite: 2]


def cerca_ddgs(query, regione, max_risultati=10, tentativi=2):
    for tentativo in range(tentativi):
        try:
            RITMO_RICERCA.attendi()
            with DDGS(timeout=8) as ddgs:
                risultati = list(ddgs.text(query, region=regione, safesearch="moderate", max_results=max_risultati))
            log(f"ricerca '{query}' [{regione}] -> {len(risultati)} risultati")
            if risultati:
                return risultati
        except Exception as errore:
            log(f"ricerca '{query}' [{regione}] ERRORE {type(errore).__name__}: {errore}")
        if tentativo < tentativi - 1:
            time.sleep(0.8 * (tentativo + 1))
    return []  #[cite: 2]


NAZIONI_META = {
    "Francia": {"lingua": "fr", "ddg": "fr-fr", "parola": "recette"},
    "Gran Bretagna": {"lingua": "en", "ddg": "uk-en", "parola": "recipe"},
    "Russia": {"lingua": "ru", "ddg": "ru-ru", "parola": "рецепт"},
    "Germania": {"lingua": "de", "ddg": "de-de", "parola": "Rezept"},
    "Austria": {"lingua": "de", "ddg": "at-de", "parola": "Rezept"},
    "Belgio": {"lingua": "fr", "ddg": "be-fr", "parola": "recette"},
    "Svizzera": {"lingua": "de", "ddg": "ch-de", "parola": "Rezept"},
    "Messico": {"lingua": "es", "ddg": "mx-es", "parola": "receta"},
}  #[cite: 2]


def piano_query(p):
    if not p.nazione:
        return [
            (f"{p.ita} ricetta", "it-it"),
            (f"{p.ita} ricetta ingredienti procedimento", "it-it"),
            (f"{p.ita} recipe", "wt-wt"),
        ]
    meta = NAZIONI_META.get(p.nazione, {})
    eng = p.eng or p.orig or p.ita
    orig = p.orig or p.ita
    piano = [(f"{eng} recipe", "wt-wt")]
    if chiave_piatto(orig) != chiave_piatto(eng):
        piano.append((f"{orig} {meta.get('parola', 'recipe')}", meta.get("ddg", "wt-wt")))
    piano.append((f"{eng} traditional recipe ingredients instructions", "wt-wt"))
    piano.append((f"{p.ita} ricetta", "it-it"))
    return piano  #[cite: 2]


def analizza_url(url, piatto, posizione, titolo_ricerca=""):
    pagina = scarica_pagina(url)
    if not pagina:
        return None
    url_finale, html = pagina
    r = analizza_pagina(url_finale, html)
    if not r:
        return None
    testo_verifica = f"{r['titolo_originale']} {urlparse(url_finale).path} {titolo_ricerca}"
    rilev = rilevanza(testo_verifica, piatto.varianti)
    if rilev < SOGLIA_RILEVANZA:
        return None
    r["rilevanza"] = rilev
    r["posizione"] = posizione
    r["punteggio"] = punteggio_ricetta(r, posizione, rilev, piatto.nazione is None)
    return r  #[cite: 2]


def _analizza_parallelo(candidati, piatto, posizione_base):
    risultati = []
    if not candidati:
        return risultati
    with ThreadPoolExecutor(max_workers=min(6, len(candidati))) as ex:
        futuri = [
            ex.submit(analizza_url, c["href"], piatto, posizione_base + i, c.get("title", ""))
            for i, c in enumerate(candidati)
        ]
        for f in as_completed(futuri):
            try:
                r = f.result()
            except Exception:
                r = None
            if r:
                risultati.append(r)
    return risultati  #[cite: 2]


def raccogli_ricette_valide(piatto, scaduto):
    valide, visti = [], set()
    for indice, (query, regione) in enumerate(piano_query(piatto)):
        if scaduto():
            break
        nuovi = []
        for pos, c in enumerate(cerca_ddgs(query, regione)):
            link = str(c.get("href") or "").strip()
            if not link.startswith("http") or link in visti:
                continue
            visti.add(link)
            if any(d in link.lower() for d in DOMINI_ESCLUSI):
                continue
            c["_ordine"] = pos
            nuovi.append(c)
        nuovi.sort(key=lambda c: (-bonus_dominio(c["href"], piatto.nazione is None), c["_ordine"]))
        valide.extend(_analizza_parallelo(nuovi[:8], piatto, indice * 5))
        buone = [v for v in valide if v.get("immagine")]
        if len(buone) >= 2 or (len(valide) >= 4 and indice >= 1):
            break
    return valide  #[cite: 2]


def cerca_themealdb(piatto):
    for nome in piatto.varianti:
        try:
            r = sessione_http().get(
                "https://www.themealdb.com/api/json/v1/1/search.php",
                params={"s": nome}, timeout=(3, 6),
            )
            r.raise_for_status()
            pasti = (r.json() or {}).get("meals") or []
        except Exception:
            continue
        for pasto in pasti[:3]:
            titolo = str(pasto.get("strMeal") or "").strip()
            if not titolo or rilevanza(titolo, piatto.varianti) < SOGLIA_RILEVANZA:
                continue
            ingredienti = []
            for i in range(1, 21):
                ing = str(pasto.get(f"strIngredient{i}") or "").strip()
                if ing:
                    ingredienti.append(f"{str(pasto.get(f'strMeasure{i}') or '').strip()} {ing}".strip())
            passi = _pulisci_passi(spezza_in_step(str(pasto.get("strInstructions") or "")))
            if len(ingredienti) < 2 or not passi:
                continue
            return {
                "titolo_originale": titolo, "ingredienti_originali": ingredienti,
                "istruzioni_originali": passi, "difficolta_originale": None,
                "tempo_prep": None, "tempo_cottura": None,
                "immagine": pasto.get("strMealThumb") or None,
                "fonte": f"https://www.themealdb.com/meal/{pasto.get('idMeal', '')}",
                "lingua_pagina": "en", "rilevanza": 1.0, "posizione": 99, "punteggio": 40.0,
            }
    return None  #[cite: 2]


def immagine_wikipedia(piatto):
    for lingua_wiki in ("it", "en"):
        for nome in piatto.varianti[:2]:
            try:
                r = sessione_http().get(
                    f"https://{lingua_wiki}.wikipedia.org/w/api.php",
                    params={
                        "action": "query", "format": "json", "generator": "search",
                        "gsrsearch": nome, "gsrlimit": 3, "prop": "pageimages",
                        "piprop": "thumbnail", "pithumbsize": 900,
                    },
                    timeout=(4, 8),
                )
                r.raise_for_status()
                pagine = ((r.json() or {}).get("query") or {}).get("pages") or {}
                for p in sorted(pagine.values(), key=lambda x: x.get("index", 99)):
                    miniatura = (p.get("thumbnail") or {}).get("source")
                    if miniatura and rilevanza(p.get("title", ""), piatto.varianti) >= SOGLIA_RILEVANZA:
                        pagina_wiki = f"https://{lingua_wiki}.wikipedia.org/wiki/{quote(p['title'].replace(' ', '_'))}"
                        return miniatura, pagina_wiki
            except Exception:
                continue
    return None, None  #[cite: 2]


NOMI_LINGUE = {
    "fr": "francese", "en": "inglese", "de": "tedesco", "ru": "russo", "es": "spagnolo",
    "nl": "olandese", "pt": "portoghese", "tr": "turco", "sq": "albanese", "ro": "rumeno",
    "ca": "catalano", "sv": "svedese", "pl": "polacco", "uk": "ucraino", "auto": "lingua originale",
}  #[cite: 2]


def da_lingua(codice):
    nome = NOMI_LINGUE.get(codice, codice)
    return ("dall'" if nome[:1] in "aeiou" else "dal ") + nome  #[cite: 2]


def prepara_italiano(cand, stato, scaduto):
    titolo = cand["titolo_originale"]
    ingredienti = cand["ingredienti_originali"]
    passi = cand["istruzioni_originali"]
    testi = [titolo, *ingredienti, *passi]

    lingua = determina_lingua_origine(cand.get("lingua_pagina"), testi)
    if lingua == "it":
        return {
            "ok": True, "servizio": True, "titolo": titolo, "ingredienti": ingredienti,
            "istruzioni": passi, "lingua": "it", "tradotta": False,
        }

    sl = lingua or "auto"
    sorgente = testi
    if CONVERTI_UNITA_US and sl == "en":
        sorgente = [converti_unita_us(t) for t in testi]
    stato(f"Traduco in italiano {da_lingua(sl)} ({len(testi)} testi)...")
    tradotti, completa, servizio, falliti = traduci_testi(sorgente, sl, scaduto)

    motivo = None
    if not completa:
        motivo = f"{falliti} righe su {len(testi)} non tradotte"
    else:
        lingua_out = lingua_testo(tradotti, 0.95)
        if lingua_out == "en" or (sl != "auto" and lingua_out == sl):
            motivo = f"risultato ancora in '{lingua_out}'"
            completa = False
        elif lingua_out is None and sembra_inglese(" ".join(tradotti)):
            motivo = "risultato che sembra inglese"
            completa = False
    if not completa:
        return {"ok": False, "servizio": servizio, "motivo": motivo}

    n_ing = len(ingredienti)
    return {
        "ok": True, "servizio": True, "lingua": sl, "tradotta": True,
        "titolo": tradotti[0] or titolo,
        "ingredienti": tradotti[1:1 + n_ing],
        "istruzioni": tradotti[1 + n_ing:],
    }  #[cite: 2]


def _stima_difficolta(valore, n_elementi):
    v = str(valore or "").strip().lower()
    if v:
        if any(x in v for x in ("facilissim", "easy", "simple", "einfach", "facile", "facil", "легк")) and "difficile" not in v:
            return "Facile"
        if any(x in v for x in ("difficil", "hard", "advanced", "challeng", "schwer", "сложн")):
            return "Difficile"
        if any(x in v for x in ("medi", "moder", "intermediate", "more effort", "normal", "mittel")):
            return "Media"
    if n_elementi < 10:
        return "Facile"
    if n_elementi < 22:
        return "Media"
    return "Difficile"  #[cite: 2]


def cerca_e_estrae_ricetta(piatto, callback_stato=None, annulla=None):
    def stato(msg):
        if callback_stato:
            try:
                callback_stato(msg)
            except Exception:
                pass

    inizio = time.monotonic()

    def scaduto():
        return (annulla is not None and annulla.is_set()) or (time.monotonic() - inizio > TEMPO_MASSIMO_RICERCA)

    in_cache = CACHE_RICETTE.get(piatto.chiave)
    if in_cache:
        return in_cache, None

    stato("Cerco la ricetta sul web...")
    valide = []

    url_memorizzato = CACHE_FONTI.get(piatto.chiave)
    if url_memorizzato:
        r = analizza_url(url_memorizzato, piatto, 0)
        if r:
            valide.append(r)
    if not valide:
        valide = raccogli_ricette_valide(piatto, scaduto)
    if not valide and not scaduto():
        stato("Provo con una fonte alternativa...")
        r = cerca_themealdb(piatto)
        if r:
            valide.append(r)

    if annulla is not None and annulla.is_set():
        return None, "Ricerca annullata."
    if not valide:
        return None, "Ricetta non trovata.\nProva con il nome completo del piatto (anche in inglese)."

    valide.sort(key=lambda c: (-c["punteggio"], c["posizione"]))

    scelta, esito, servizio_ok, motivi = None, None, True, []
    for cand in valide[:3]:
        if scaduto():
            break
        e = prepara_italiano(cand, stato, scaduto)
        if e["ok"]:
            scelta, esito = cand, e
            break
        servizio_ok = servizio_ok and e["servizio"]
        if e.get("motivo"):
            motivi.append(e["motivo"])
        if not e["servizio"]:
            break
    if not scelta:
        if annulla is not None and annulla.is_set():
            return None, "Ricerca annullata."
        messaggio = "Ho trovato la ricetta ma non sono riuscito a tradurla completamente in italiano.\n"
        if not servizio_ok:
            messaggio += "Il servizio di traduzione non risponde (rete, blocco temporaneo o limite raggiunto).\n"
        messaggio += "Riprova tra qualche minuto: non mostro ricette tradotte a meta'."
        dettagli = " | ".join(x for x in (riepilogo_errori_traduzione(), "; ".join(motivi)) if x)
        if dettagli:
            messaggio += f"\n\nDettagli tecnici: {dettagli}"
        return None, messaggio

    stato("Scarico la foto del piatto finito...")
    immagine_url = immagine_locale = immagine_fonte = None
    for cand in [scelta] + [c for c in valide if c is not scelta][:3]:
        if cand.get("immagine"):
            percorso = scarica_e_salva_immagine(cand["immagine"], cand["fonte"])
            if percorso:
                immagine_url, immagine_locale, immagine_fonte = cand["immagine"], percorso, cand["fonte"]
                break
    if not immagine_locale and not scaduto():
        miniatura, pagina_wiki = immagine_wikipedia(piatto)
        if miniatura:
            percorso = scarica_e_salva_immagine(miniatura, pagina_wiki or "")
            if percorso:
                immagine_url, immagine_locale, immagine_fonte = miniatura, percorso, pagina_wiki

    difficolta = _stima_difficolta(
        scelta.get("difficolta_originale"),
        len(scelta["ingredienti_originali"]) + len(scelta["istruzioni_originali"]),
    )

    fonte = scelta["fonte"]
    if esito["tradotta"]:
        fonte += f"  (tradotta {da_lingua(esito['lingua'])})"

    dati = {
        "chiave": piatto.chiave,
        "titolo": esito["titolo"],
        "ingredienti": esito["ingredienti"],
        "istruzioni": esito["istruzioni"],
        "tempo_prep": f"{scelta['tempo_prep']} min" if scelta.get("tempo_prep") else "Non specificato",
        "tempo_cottura": f"{scelta['tempo_cottura']} min" if scelta.get("tempo_cottura") else "Non specificato",
        "difficolta": difficolta,
        "immagine": immagine_url,
        "immagine_locale": immagine_locale,
        "fonte_immagine": immagine_fonte if immagine_fonte != scelta["fonte"] else None,
        "fonte": fonte,
    }
    CACHE_FONTI.set(piatto.chiave, scelta["fonte"])
    CACHE_RICETTE.set(piatto.chiave, dati)
    return dati, None  #[cite: 2]


# ==========================================
# DATABASE REGIONI E NAZIONI
# ==========================================

DATABASE_REGIONI_ITALIA = {
    "Abruzzo": ["Arrosticini", "Virtù teramane", "Brodetto di pesce alla vastese", "Scrippelle 'mbusse", "Pallotte cacio e ova", "Pizz e foje", "Timballo abruzzese", "Pecora alla callara", "Bocconotti di Castel frentano", "Sagne e fagioli", "Parrozzo abruzzese", "Cicerchiata", "Fiadoni abruzzesi", "Pizza scima", "Baccalà alla pizzaiola", "Coratella d'agnello alla teramana", "Zuppa di ceci e castagne abruzzese", "Tacchino all'abruzzese", "Pizza dolce abruzzese", "Cif e ciaf abruzzese"],
    "Basilicata": ["Peperoni cruschi", "Pasta con la mollica lucana", "Acquasale", "Baccalà alla lucana", "Cialledda lucana", "Cavatelli alla lucana", "Ciambotta lucana", "Pasta al ferretto alla lucana", "Agnello alla lucana", "Pignata di pecora", "Migliaccio lucano", "Focaccia di grano duro", "Panecotto lucano", "Crapiata materana", "Salsiccia con verdure", "Biscotti con la sugna", "Strascinati alla potentina", "Calzoncelli lucani", "Strazzate lucane", "Taralli al naspro"],
    "Calabria": ["'Nduja su crostini", "Pasta alla calabrese", "Fileja alla tropeana", "Tartufo di pizzo calabro", "Melanzane ripiene alla calabrese", "Frittole calabresi", "Stocco alla mammolese", "Capretto al forno calabrese", "Polpette di melanzane", "Zippole calabresi", "Pitta 'mpigliata", "Cuzzupe calabresi", "Risotto con soppressata e cipolla rossa di Tropea", "Peperoncini ripieni alla calabrese", "Licurdia calabrese", "Sagne chine", "Turdilli calabresi", "Pesce spada alla bagnarese", "Nacatole calabresi", "Frittata calabrese"],
    "Campania": ["Pizza Margherita napoletana", "Spaghetti alle vongole", "Scialatielli ai frutti di mare", "Ragù napoletano", "Sartù", "Pasta e patate con la provola", "Impepata di cozze", "Genovese napoletana", "Baccalà alla napoletana", "Casatiello napoletano", "Struffoli", "Sfogliatella napoletana", "Pastiera napoletana", "Babà napoletano", "Zeppole di San Giuseppe napoletane", "Mozzarella in carrozza", "Frittata di pasta napoletana", "Spaghetti alla Nerano", "Insalata di rinforzo", "Delizia al limone"],
    "Emilia-Romagna": ["Tortellini in brodo", "Lasagne alla bolognese", "Tagliatelle al ragù", "Cotoletta alla bolognese", "Piadina romagnola con crudo, squacquerone e rucola", "Zampone e cotechino con lenticchie", "Crescentine", "Erbazzone reggiano", "Spoja lorda", "Tardura", "Anolini in brodo", "Gramigna con salsiccia", "Cappelletti romagnoli", "Bassotti", "Torta di riso emiliana", "Zuppa inglese", "Friggione bolognese", "Certosino bolognese", "Confettura di mosto romagnola", "Crescentina fritta emiliana"],
    "Friuli-Venezia Giulia": ["Jota triestina", "Frico friulano", "Cjarsons", "Gulasch alla triestina", "Gnocchi di zucca friulani", "Musetto e brovada", "Gnocchi di susine friulani", "Blecs friulani", "Baccalà alla triestina", "Gnocchetti de gries", "Orzo e fagioli friulano", "Esse di Raveo", "Strucolo", "Presnitz triestino", "Gubana", "Palacinka", "Toc' in braide", "Pinza triestina", "Cevapcici alla triestina", "Putizza friulana"],
    "Lazio": ["carbonara", "Bucatini all'amatriciana", "Cacio e pepe", "Saltimbocca alla romana", "Coda alla vaccinara", "Abbacchio alla scottadito", "Tozzetti viterbesi", "Carciofi alla giudia", "Trippa alla romana", "Gricia romana", "Fiori di zucca in pastella", "Puntarelle alla romana", "Supplì al telefono", "Pajata alla romana", "Minestra di broccoli e arzilla", "Maritozzi con la panna", "Bignè di San Giuseppe romani", "Torta di ricotta romana", "Pangiallo romano", "Ciambelline al vino"],
    "Liguria": ["Trofie al pesto genovese", "Focaccia genovese", "Farinata di ceci", "Cima alla genovese", "Pansoti con salsa di noci", "Torta pasqualina", "Minestrone alla genovese", "Buridda di pesce", "Coniglio alla ligure", "Ciuppin", "Acciughe al verde", "Panissa ligure", "Stoccafisso accomodato", "Sardenaira", "Corzetti genovesi", "Latte dolce fritto", "Canestrelli liguri", "Pandolce genovese", "Baci di Alassio", "Frisceu"],
    "Lombardia": ["Risotto alla milanese", "Cotoletta alla milanese", "Ossobuco alla milanese", "Casoncelli bergamaschi", "Polenta taragna", "Pizzoccheri della Valtellina", "Cassoeula", "Tortelli cremaschi", "Mondeghili milanesi", "Busecca milanese", "Pan meino", "Panettone milanese", "Colomba pasquale", "Torrone di Cremona", "Sbrisolona mantovana", "Tortelli di zucca mantovani", "Agnolini in brodo mantovani", "Bossolà bresciano", "Nervetti in insalata", "Crema fritta lombarda"],
    "Marche": ["Vincisgrassi", "Brodetto di pesce all'anconetana", "Olive all'ascolana", "Coniglio in porchetta marchigiano", "Calcioni marchigiani", "Stoccafisso all'anconetana", "Passatelli marchigiani", "Crescia sfogliata", "Porchetta marchigiana", "Frustingo", "Cavallucci marchigiani", "Ciambelline al mosto marchigiane", "Tacchino in porchetta marchigiano", "Maccheroncini di Campofilone", "Pasticciata fanese", "Crema fritta", "Pollo in potacchio", "Castagnole marchigiane", "Bostrengo marchigiano", "Canocchie alla marchigiana"],
    "Molise": ["Cavatelli al sugo vedovo", "Pampanella molisana", "Cipollata isernina", "Brodetto di pesce termolese", "Caciocavallo di Agnone alla griglia", "Tacconelle e fagioli", "Polenta con salsiccia molisana", "Torcinelli molisani", "Fiadoni molisani", "Fusilli al ragù di pecora", "Zuppa di cardi molisana", "Celli chieni", "Pigna di Pasqua molisana", "Baccalà con peperoni cruschi molisano", "Maccheroni alla molisana", "Taralli al finocchio molisani", "Ferratelle", "Polpette di baccalà molisane", "Ciambotta molisana", "Frittata di Pasqua"],
    "Piemonte": ["Bagna cauda", "Ravioli del plin", "Vitello tonnato piemontese", "Brasato al Barolo", "Bollito misto piemontese", "Fritto misto piemontese", "Peperoni alla piemontese", "Tajarin al tartufo", "Finanziera", "Risotto al Barolo", "Carne cruda all'albese", "Gnocchi alla bava piemontesi", "Panissa vercellese", "Gnocchi all'ossolana", "Bunet piemontese", "Zabaione con Moscato", "Torta di nocciole delle Langhe", "Baci di dama", "Gianduiotto", "Krumiri di Casale"],
    "Puglia": ["Orecchiette con le cime di rapa", "Focaccia barese", "Taralli pugliesi", "Burratine ripiene", "Tiella di riso patate e cozze", "Pasticciotto leccese", "Panzerotti pugliesi", "Fave e cicoria", "Purè di fave pugliese", "Bombette pugliesi", "Braciole al sugo pugliesi", "Polpo alla pignata", "Ciceri e tria", "Cartellate pugliesi", "Pittule pugliesi", "Friselle con pomodoro", "Seppie ripiene al forno", "Sagne 'ncannulate", "Agnello al forno con patate pugliesi", "Zeppole di San Giuseppe pugliesi"],
    "Sardegna": ["Culurgiones sardi", "Malloreddus alla campidanese", "Porceddu sardo", "Fregola con le arselle", "Pane carasau", "Sebadas", "Linguine con bottarga e pomodorini", "Pane frattau", "Zuppa gallurese al forno", "Agnello al mirto", "Coccois prenas", "Sa panada", "Cordula sarda", "Orziadas", "Burrida alla cagliaritana", "Pardulas sarde", "Arantzada nugoresa", "Ricci di mare alla sarda", "Acciuleddi", "Papassinos sardi"],
    "Sicilia": ["Pasta alla Norma", "Caponata siciliana", "Arancini siciliani", "Pasta con le sarde", "Pasta ncasciata", "Sarde a beccafico siciliane", "Pani ca meusa", "Involtini di pesce spada", "Peperonata siciliana", "Cannoli siciliani", "Cassata siciliana", "Granita siciliana con brioche", "Frutta martorana", "Panelle siciliane", "Falsomagro siciliano", "Busiate al pesto trapanese", "Sfincione palermitano", "Biancomangiare", "Gelo di melone palermitano", "Genovesi di Erice"],
    "Toscana": ["Ribollita toscana", "Bistecca alla fiorentina", "Pappa al pomodoro", "Panzanella toscana", "Cacciucco alla livornese", "Peposo alla fornacina", "Crostini toscani", "Pici all'aglione", "Trippa alla fiorentina", "Fagioli all'uccelletto", "Schiacciata toscana", "Cantucci con Vin Santo", "Panforte di Siena", "Ricciarelli senesi", "Castagnaccio toscano", "Coniglio alla cacciatora toscana", "Arista di maiale toscana", "Acquacotta maremmana", "Zuppa di farro toscana", "Torta della nonna"],
    "Trentino-Alto Adige": ["Canederli trentini", "Schlutzkrapfen", "Spatzle", "Strudel di mele trentino", "Gulasch tirolese", "Orzotto trentino", "Carrè di maiale affumicato con crauti", "Tortel di patate", "Strangolapreti trentini", "Arrosto di maiale alle mele", "Zuppa d'orzo trentina", "Canederli allo speck", "Krapfen", "Torta di carote", "Crostoli trentini", "Torta di grano saraceno trentina", "Cervo in umido trentino", "Risotto mele e speck", "Zelten altoatesino", "Smacafam trentino"],
    "Umbria": ["Strangozzi", "Torta al testo umbra", "Porchetta umbra", "Lenticchie di Castelluccio", "Palombaccia alla ghiotta umbra", "Pappardelle al cinghiale", "Imbrecciata", "Bruschetta al tartufo nero", "Umbricelli all'umbra", "Pasta alla norcina", "Friccò all'eugubina", "Panpepato umbro", "Torciglione umbro", "Ciaramicola", "Fave al guanciale umbre", "Zuppa di farro", "Pollo in porchetta", "Rocciata umbra", "Crescionda spoletina", "Torta di Pasqua al formaggio umbra"],
    "Valle d'Aosta": ["Fonduta valdostana", "Polenta concia valdostana", "Gnocchetti valdostani", "Zuppa valpellinentze", "Costoletta alla valdostana", "Tegole valdostane", "Torcetti al burro", "Riso e castagne", "Minestra di porri e patate", "Camoscio alla valdostana", "Crespelle alla valdostana", "Trota al burro", "Riso valdostano", "Flantze", "Crema di Cogne", "Caffè valdostano", "Polenta e salsiccia valdostana", "Cervo con polenta", "Carbonada valdostana", "Mècoulin di Cogne"],
    "Veneto": ["Risotto al radicchio di Treviso", "Baccalà alla vicentina", "Fegato alla veneziana", "Bigoli in salsa", "Sarde in saor", "Polenta e gamberetti", "Risi e bisi", "Risotto all'amarone", "Sopa coada", "Seppie al nero", "Oca arrosto con mele", "Zaleti", "Bussolà vicentino", "Baicoli veneziani", "Fritole veneziane", "Casunzei ampezzani", "Fregolotta trevigiana", "Radicchio alla griglia", "Moleche fritte", "Baccalà mantecato"],
}  #[cite: 2]

DATABASE_NAZIONI_RAW = {
    "Francia": [
        "Zuppa di cipolle|Soupe à l'oignon|French onion soup", "Vichyssoise|Vichyssoise|Vichyssoise",
        "Quiche lorraine|Quiche lorraine|Quiche Lorraine", "Rillettes|Rillettes de porc|Pork rillettes",
        "Lumache alla borgognona|Escargots de Bourgogne|Escargots", "Terrine di foie gras|Terrine de foie gras|Foie gras terrine",
        "Coq au vin|Coq au vin|Coq au vin", "Boeuf bourguignon|Boeuf bourguignon|Beef bourguignon",
        "Ratatouille|Ratatouille|Ratatouille", "Bouillabaisse|Bouillabaisse|Bouillabaisse",
        "Cassoulet|Cassoulet|Cassoulet", "Fondant al cioccolato|Fondant au chocolat|Chocolate lava cake",
        "Blanquette di vitello|Blanquette de veau|Veal blanquette", "Bistecca al pepe|Steak au poivre|Steak au poivre",
        "Gougères|Gougères|Gougères cheese puffs", "Choucroute alsaziana|Choucroute garnie|Choucroute garnie",
        "Gratin dauphinois|Gratin dauphinois|Gratin dauphinois", "Tartiflette|Tartiflette|Tartiflette",
        "Crêpes Suzette|Crêpes Suzette|Crêpes Suzette", "Tarte Tatin|Tarte Tatin|Tarte Tatin",
        "Profiteroles|Profiteroles|Profiteroles", "Macarons|Macarons|French macarons",
        "Crème brûlée|Crème brûlée|Crème brûlée", "Mousse al cioccolato|Mousse au chocolat|Chocolate mousse",
        "Éclair al cioccolato|Éclair au chocolat|Chocolate éclair", "Madeleine|Madeleines|Madeleines",
        "Clafoutis alle ciliegie|Clafoutis aux cerises|Cherry clafoutis", "Île flottante|Île flottante|Floating island dessert",
        "Millefoglie|Mille-feuille|Mille-feuille", "Canelé|Cannelés de Bordeaux|Canelés",
        "Galette des rois|Galette des rois|Galette des rois", "Torta al limone|Tarte au citron|Lemon tart",
        "Soufflé al formaggio|Soufflé au fromage|Cheese soufflé", "Insalata nizzarda|Salade niçoise|Salade niçoise",
        "Croque monsieur|Croque-monsieur|Croque monsieur", "Croque madame|Croque-madame|Croque madame",
        "Patate alla sarladese|Pommes de terre sarladaises|Sarladaise potatoes", "Flamiche ai porri|Flamiche aux poireaux|Leek flamiche",
        "Pollo alla basca|Poulet basquaise|Chicken basquaise", "Pot-au-feu|Pot-au-feu|Pot-au-feu",
        "Hachis Parmentier|Hachis Parmentier|Hachis Parmentier", "Tarte tropézienne|Tarte tropézienne|Tarte tropézienne",
        "Andouillette alla senape|Andouillette à la moutarde|Andouillette with mustard sauce", "Omelette alla francese|Omelette française|French omelette",
        "Pissaladière|Pissaladière|Pissaladière", "Croissant",
        "Toast alla francese|French toast", "Lontano bretone",
        "Paris-Brest|Paris-Brest|Paris-Brest", "Tian provenzale",
    ],
    "Gran Bretagna": [
        "Zuppa di piselli e menta|Pea and mint soup", "Scotch egg|Scotch eggs", "Fisherman's pie|Fisherman's pie",
        "Cottage pie|Cottage pie", "Fish and chips|Fish and chips", "Roast beef con Yorkshire pudding|Roast beef with Yorkshire pudding",
        "Shepherd's pie|Shepherd's pie", "Beef Wellington|Beef Wellington", "Full English breakfast|Full English breakfast",
        "Cornish pasty|Cornish pasty", "Bangers and mash|Bangers and mash", "Steak and kidney pie|Steak and kidney pie",
        "Toad in the hole", "Chicken tikka masala|Chicken tikka masala", "Haggis|Insaccato scozzese",
        "Victoria sponge cake|Victoria sponge cake", "Scones|Scones", "Sticky toffee pudding|Sticky toffee pudding",
        "Apple crumble|crumble di mele", "Trifle|Trifle", "Bread and butter pudding|Bread and butter pudding",
        "Eton mess|Eton mess", "Budino di Natale|Christmas pudding", "Battenberg cake|Torta a scacchi inglese",
        "Bakewell tart|Bakewell tart", "Treacle tart|Treacle tart", "Banoffee pie|con banane",
        "Lemon posset|Lemon posset", "Ploughman's lunch|Ploughman's lunch", "Lancashire hotpot|Lancashire hotpot",
        "Steak and ale pie|Steak and ale pie", "Pork pie|Pork pie", "Bubble and squeak",
        "Cullen skink|Cullen skink", "Welsh cakes|Welsh cakes", "Coronation chicken|Coronation chicken",
        "Jacket potato|Jacket potato", "Spotted dick|Spotted dick", "Sausage roll|Sausage rolls",
        "Welsh rarebit|Welsh rarebit", "Mince pies|Mince pies", "Eccles cakes|Eccles cakes",
        "Scouse|Scouse", "Lemon drizzle cake|Lemon drizzle cake", "Cawl|Stufato tradizionale gallese",
        "Chelsea buns|Chelsea buns", "Chicken and leek pie|Chicken and leek pie", "Parkin|Parkin",
        "Cranachan|Cranachan", "Kedgeree|Kedgeree",
    ],
    "Russia": [
        "Borscht|Борщ|Borscht", "Solyanka|Солянка|Solyanka soup", "Ukha|Уха|Ukha Russian fish soup",
        "Shchi|Щи|Shchi cabbage soup", "Okroshka|Окрошка|Okroshka", "Insalata Olivier|Салат Оливье|Olivier salad",
        "Vinegret|Винегрет|Vinegret beet salad", "Blini|Блины|Blini", "Pirozhki|Пирожки|Pirozhki",
        "Botvinya|Ботвинья|Botvinya", "Manzo alla Stroganoff|Бефстроганов|Beef Stroganoff", "Pelmeni|Пельмени|Pelmeni",
        "Kasha di grano saraceno|Гречневая каша|Buckwheat kasha", "Polpette russe|Котлеты|Russian kotlety meat patties",
        "Pollo alla Kiev|Котлета по-киевски|Chicken Kiev", "Plov|Плов|Plov", "Medovik|Медовик|Medovik honey cake",
        "Torta Napoleon|Торт Наполеон|Napoleon cake", "Syrniki|Сырники|Syrniki", "Vatrushka|Ватрушка|Vatrushka",
        "Pryaniki|Пряники|Pryanik Russian gingerbread", "Kissel|Кисель|Kissel", "Kulich|Кулич|Kulich Easter bread",
        "Rassolnik|Рассольник|Rassolnik soup", "Draniki|Драники|Draniki potato pancakes",
        "Zuppa di funghi|Грибной суп|Russian mushroom soup", "Aringa sotto la pelliccia|Селёдка под шубой|Herring under a fur coat",
        "Cavolo stufato|Тушёная капуста|Russian braised cabbage", "Manty|Манты|Manti dumplings", "Kurnik|Курник|Kurnik chicken pie",
        "Kulebyaka|Кулебяка|Kulebyaka", "Zrazy|Зразы|Zrazy", "Tefteli|Тефтели|Tefteli meatballs",
        "Smetannik|Сметанник|Smetannik sour cream cake", "Kartoshka|Пирожное картошка|Kartoshka cake", "Pastila di Belev|Белёвская пастила|Belevskaya pastila",
        "Zefir|Зефир|Zefir", "Kutia|Кутья|Kutia", "Kholodets|Холодец|Kholodets", "Vareniki|Вареники|Vareniki",
        "Paskha|Пасха|Paskha Easter cheese dessert", "Blini con caviale|Блины с красной икрой|Blini with red caviar",
        "Golubtsy|Голубцы|Golubtsy stuffed cabbage rolls", "Ptichye moloko", "Tort Praga",
        "Zuppa di piselli russa|Гороховый суп|Russian pea soup", "Kalitki|Kalitki", "Pollo tabaka|Цыплёнок табака|Chicken tabaka",
        "Pirog con cavolo|Пирог с капустой|Russian cabbage pie", "Insalata di cetrioli e panna acida|Салат из огурцов со сметаной|Russian cucumber salad with sour cream",
    ],
    "Germania": [
        "Zuppa di patate|Kartoffelsuppe|German potato soup", "Gulaschsuppe|Gulaschsuppe|Goulash soup",
        "Maultaschensuppe|Maultaschensuppe|Maultaschen soup", "Insalata di patate tedesca|Kartoffelsalat|German potato salad",
        "Insalata di wurstel|Wurstsalat|German sausage salad", "Bratwurst con crauti|Bratwurst mit Sauerkraut|Bratwurst with sauerkraut",
        "Schnitzel|Schweineschnitzel|German schnitzel", "Eisbein|Eisbein|Eisbein", "Rouladen|Rinderrouladen|Beef rouladen",
        "Sauerbraten|Sauerbraten|Sauerbraten", "Currywurst|Currywurst|Currywurst", "Königsberger Klopse|Königsberger Klopse|Königsberger Klopse",
        "Kassler|Kasseler|Kassler pork", "Käsespätzle|Käsespätzle|Käsespätzle", "Leberkäse|Leberkäse|Leberkäse",
        "Pretzel|Laugenbrezel|Soft pretzels", "Apfelstrudel|Apfelstrudel|Apple strudel", "Foresta Nera|Schwarzwälder Kirschtorte|Black Forest cake",
        "Bienenstich|Bienenstich|Bienenstich cake", "Crèpes|pfannkuchen", "Stollen|Christstollen|Christstollen",
        "Berliner|Berliner Pfannkuchen|Berliner doughnuts", "Baumkuchen|Baumkuchen|Baumkuchen", "Cheesecake tedesca|Käsekuchen|German cheesecake",
        "Lebkuchen|Lebkuchen|Lebkuchen", "Dampfnudeln|Dampfnudeln|Dampfnudeln", "Schweinshaxe|Schweinshaxe|Roasted pork knuckle",
        "Bratkartoffeln|Bratkartoffeln|German fried potatoes", "Kartoffelpuffer|Kartoffelpuffer|Kartoffelpuffer",
        "Zuppa di asparagi tedesca|Spargelsuppe|German asparagus soup", "Zwiebelkuchen|Zwiebelkuchen|Zwiebelkuchen",
        "Flammkuchen|Flammkuchen|Flammkuchen", "Buletten alla berlinese", "Frikadellen|Frikadellen|Frikadellen",
        "Weißwurst|Weißwurst|Weisswurst", "Obatzda|Obatzda|Obatzda", "Kartoffelklöße|Kartoffelklöße|Kartoffelklöße potato dumplings",
        "Kaiserschmarrn", "Cavolo rosso brasato|Rotkohl|Braised red cabbage", "Himmel und Erde|Himmel und Erde|Himmel und Erde",
        "Spätzle|Spätzle|Spaetzle", "Ofenschlupfer|Ofenschlupfer|Ofenschlupfer", "Quarkbällchen|Quarkbällchen|Quarkbällchen",
        "Apfelküchle|Apfelküchle|German apple fritters", "Rote Grütze|Rote Grütze|Rote Grütze", "Linseneintopf|Linseneintopf|German lentil stew",
        "Zuppa di piselli tedesca|Erbsensuppe|German pea soup", "Hackbraten|Hackbraten|German meatloaf", "Grünkohl mit pinkel",
        "Zwetschgenkuchen|Ricetta tradizionale tedesca della torta di prugne",
    ],
    "Austria": [
        "Nockerlsuppe|Zuppa con gnocchetti di farina", "Gulasch viennese|Wiener Saftgulasch|Viennese goulash",
        "Wiener Schnitzel|Cotoletta alla viennese", "Tafelspitz|Tafelspitz|Tafelspitz",
        "Zwiebelrostbraten|Zwiebelrostbraten|Zwiebelrostbraten", "Backhendl|Backhendl|Backhendl",
        "Sauerbraten|Sauerbraten", "Kasnocken|Kasnocken|Kasnocken", "Sachertorte|Sachertorte|Sachertorte",
        "Apfelstrudel viennese|Wiener Apfelstrudel|Viennese apple strudel", "Linzer Torte|Linzer Torte|Linzer torte",
        "Salzburger Nockerl|Gnocchi di Salisburgo", "Kaiserschmarrn|Kaiserschmarrn|Kaiserschmarrn",
        "Palatschinken|Palatschinken|Palatschinken", "Punschkrapfen|Punschkrapfen|Punschkrapfen",
        "Esterhazy Torte|Esterházy-Torte|Esterházy torte", "Topfenknödel|A base di topfen",
        "Krapfen|Faschingskrapfen|Austrian Krapfen", "Guglhupf|Gugelhupf|Gugelhupf", "Marillenknödel|Marillenknödel|Marillenknödel",
        "Tiroler Gröstl|Tiroler Gröstl|Tiroler Gröstl", "Kaspressknödel|Kaspressknödel|Kaspressknödel",
        "Grießnockerlsuppe|Grießnockerlsuppe|Grießnockerlsuppe", "Speckknödel|Speckknödel|Speckknödel",
        "Schlipfkrapfen|Schlipfkrapfen|Schlipfkrapfen", "Buchteln|Buchteln|Buchteln", "Nuss-Palatschinken",
        "Topfenstrudel|Topfenstrudel|Topfenstrudel", "Kärntner Reindling|Kärntner Reindling|Reindling",
        "Erdäpfelsalat|Erdäpfelsalat|Austrian potato salad", "Germknödel|Germknödel|Germknödel", "Powidltascherl|Powidltascherl|Powidltascherl",
        "Vanillekipferl|Vanillekipferl|Vanillekipferl", "Linzer Augen|Linzer Augen|Linzer Augen", "Kardinalschnitte|Kardinalschnitte|Kardinalschnitte",
        "Ischler|Ischler Törtchen|Ischler cookies", "Pofesen|Pofesen|Pofesen", "Faschierte Laibchen|Faschierte Laibchen|Faschierte Laibchen",
        "Zillertaler Krapfen|Zillertaler Krapfen|Ciambelle", "Wiener Beuschel|Wiener Beuschel|Viennese Beuschel",
        "Zuppa di zucca stiriana|Steirische Kürbiscremesuppe|Styrian pumpkin soup", "Alt-Wiener Backfleisch|Alt-wiener Backfleisch",
        "Gulasch di patate|Erdäpfelgulasch|Austrian potato goulash", "Gulasch di finferli|Eierschwammerlgulasch|Chanterelle goulash",
        "Kaiserschöberl|Kaiserschöberl|Kaiserschöberl soup", "Grammelknödel|Grammelknödel|Grammelknödel", "Schaumrollen|Schaumrollen|Schaumrollen",
        "Vanillerostbraten|Vanillerostbraten|Vanillerostbraten", "Leberknödelsuppe|Leberknödelsuppe|Leberknödelsuppe",
        "Kirschmichel|Kirschmichel|Kirschmichel",
    ],
    "Belgio": [
        "Asperges à la flamande", "Waterzooi di pollo",
        "Croquettes au fromage", "Cozze e patatine|Moules-frites|Moules frites",
        "Carbonade fiamminga|Carbonnade flamande|Flemish beef and beer stew", "Waterzooi di pesce",
        "Stoemp|Stoemp|Stoemp", "Vol-au-vent|Vol-au-vent|Belgian vol-au-vent", "Filet américain|Filet américain|Filet americain",
        "Waffle di Liegi|Gaufres de Liège|Liège waffles", "Waffle di Bruxelles|Gaufres de Bruxelles|Brussels waffles",
        "Speculoos|Speculoos|Speculoos cookies", "Pralines belghe|Pralines belges|Belgian chocolate pralines",
        "Mousse al cioccolato belga", "Tarte au sucre|Tarte au sucre|Belgian sugar tart",
        "Indivia belga gratinata", "Boulets alla liegese|Boulets à la liégeoise|Boulets liégeois",
        "Frites belghe|Frites belges|Belgian fries", "Pomodori ripieni di gamberetti|Tomates aux crevettes grises|Tomates crevettes",
        "Insalata liegese|Salade liégeoise|Salade liégeoise", "Coniglio alla birra",
        "Coniglio alla gueuze|Lapin à la gueuze|Rabbit in gueuze beer", "Biscotti alle mandorle|Kletskopje",
        "Lapin à la Tournaisienne", "Sole meunière",
        "Cougnou|Cougnou|Cougnou bread", "Rijsttaart|Rijsttaart|Belgian rice tart", "Crostata al latte",
        "Indivia belga al salmone", "Merveilleux|Merveilleux|Merveilleux", "Lapin aux pruneaux|Coniglio alle prugne",
        "Hutsepot|Hutsepot|Hutsepot Flemish stew", "Pistolets|Pistolets belges|Belgian pistolets bread rolls", "Pannenkoeken|Pannenkoeken|Belgian pancakes",
        "Boudin blanc|Boudin blanc de Liège|Boudin blanc", "Zuppa al cerfoglio|Soupe au cerfeuil|Chervil soup",
        "Crocchette di gamberetti|Croquettes aux crevettes grises|Shrimp croquettes", "Tarte au Mastellen",
        "Pane di zucchero belga", "Couque de Dinant belga|biscotti al miele", "Cavoletti di Bruxelles|Choux de Bruxelles|Brussels sprouts",
        "Fricadelle|Fricadelle|Fricadelle", "Pain à la grecque|Pain à la grecque|Pain à la grecque", "Lierse vlaaike|Lierse vlaaike|Lierse vlaaike",
        "Jodenkoeken|Jodenkoeken|Jodenkoeken", "Pâté gaumais|Pâté gaumais|Pâté gaumais", "Polpette in salsa di pomodoro|Boulettes sauce tomate|Belgian meatballs in tomato sauce",
        "Zuppa di porri belga|Soupe aux poireaux|Belgian leek soup", "Tarte alla rabarbaro|Tarte à la rhubarbe|Rhubarb tart", "Gratin di cavolfiore belga|Chou-fleur gratiné|Belgian cauliflower gratin",
    ],
    "Svizzera": [
        "Zuppa d'orzo grigionese|Bündner Gerstensuppe|Bündner barley soup", "Rösti|Rösti|Rösti", "Capuns|Capuns|Capuns",
        "Fonduta al formaggio|Käsefondue|Swiss cheese fondue", "Raclette|Raclette|Raclette", "Züri Gschnätzlets|Zürcher Geschnetzeltes|Zurich-style veal",
        "Älplermagronen|Älplermagronen|Älplermagronen", "Cordon bleu|Cordon bleu|Swiss cordon bleu", "Spezzatino alla zurighese",
        "Torta di noci engadinese|Bündner Nusstorte|Engadine nut tart", "Torta di carote|Rüeblitorte|Swiss carrot cake",
        "Basler Leckerli|Basler Läckerli|Basler Leckerli", "Treccia svizzera|Swiss butter braid", "Meringhe della Gruyère|Meringues de la Gruyère|Gruyère meringues",
        "Zuger Kirschtorte|Zuger Kirschtorte|Zuger Kirschtorte", "Birchermüesli|Birchermüesli|Bircher muesli", "Maluns|Maluns|Maluns",
        "Polenta ticinese|Polenta ticinese|Ticino polenta", "Riz Casimir", "Saucisson vaudois|Saucisson vaudois|Saucisson vaudois",
        "Vermicelles", "Salsiccia di San Gallo|St. Galler Bratwurst|St. Gallen bratwurst", "Fonduta moitié-moitié|Fondue moitié-moitié|Moitié-moitié fondue",
        "Fondue chinoise|Fondue chinoise|Fondue chinoise", "Fondue bourguignonne|Fondue bourguignonne|Fondue bourguignonne",
        "Filetti di pesce persico", "Zuppa di farina di Basilea|Basler Mehlsuppe|Basler Mehlsuppe", "Berner Platte|Berner Platte|Berner Platte",
        "Kaseschnitte|Toast svizzero", "Le Maluns", "Pizokel|Bündner Pizokel|Bündner Pizokel",
        "Torta di pane ticinese|Torta di pane ticinese|Ticino bread cake", "Brasato con polenta",
        "Minestrone ticinese|Minestrone ticinese|Ticino minestrone", "Luzerner Chügelipastete|Luzerner Chügelipastete|Lucerne vol-au-vent",
        "Kirschwahe", "Cholera|Cholera Walliser Gemüsekuchen|Cholera tart Valais", "Gratin de cardons|Gratin de cardons genevois|Geneva cardoon gratin",
        "Malakoff|Malakoff vaudois|Malakoff fried cheese balls", "Gâteau du Vully|Gâteau du Vully|Gâteau du Vully", "Tarte à la raisinée|Tarte à la raisinée|Raisinée tart",
        "Pane alle pere|Birnbrot", "Fasnachtschüechli|Fasnachtschüechli|Fasnachtschüechli", "Brunsli",
        "Hörnli e Ghacktes|Hörnli mit Ghacktem|Hörnli with minced meat", "Insalata svizzera di cervelat", "Chäschüechli|Chäschüechli|Swiss cheese tart",
        "Gschwellti|Gschwellti mit Käse|Gschwellti Swiss boiled potatoes with cheese", "Zibelechuchen|Zibelechuchen|Swiss onion tart",
        "Risotto ticinese con luganighe",
    ],
    "Messico": [
        "Zuppa di tortilla|Sopa de tortilla|Tortilla soup", "Pozole|Pozole rojo|Pozole rojo", "Guacamole|Guacamole|Guacamole",
        "Ceviche|Ceviche mexicano|Mexican ceviche", "Tacos al pastor|Tacos al pastor|Tacos al pastor", "Enchiladas|Enchiladas rojas|Red enchiladas",
        "Chiles rellenos|Chiles rellenos|Chiles rellenos", "Mole poblano|Mole poblano|Mole poblano", "Carnitas|Carnitas|Carnitas",
        "Cochinita pibil|Cochinita pibil|Cochinita pibil", "Fajitas|Fajitas|Fajitas", "Tamales|Tamales|Tamales",
        "Chilaquiles|Chilaquiles|Chilaquiles", "Birria|Birria de res|Birria", "Churros|Churros|Churros",
        "Flan|Flan napolitano|Mexican flan", "Torta tres leches|Pastel de tres leches|Tres leches cake", "Buñuelos|Buñuelos|Mexican buñuelos",
        "Pan de muerto|Pan de muerto|Pan de muerto", "Tacos de pescado|Tacos de pescado|Fish tacos", "Tacos de barbacoa|Tacos de barbacoa|Barbacoa tacos",
        "Tostadas de tinga|Tostadas de tinga|Tostadas de tinga", "Quesadillas|Quesadillas|Quesadillas", "Sopes|Sopes|Sopes",
        "Gorditas|Gorditas|Gorditas", "Memelas", "Garnachas", "Pambazos|Pambazos|Pambazos",
        "Molletes|Molletes|Molletes", "Enfrijoladas|Enfrijoladas|Enfrijoladas", "Entomatadas|Entomatadas|Entomatadas",
        "Huevos rancheros|Huevos rancheros|Huevos rancheros", "Huevos alla messicana|Huevos a la mexicana|Mexican scrambled eggs",
        "Huevos divorciados|Huevos divorciados|Huevos divorciados", "Machaca con huevo|Machaca con huevo|Machaca con huevo",
        "Menudo|Menudo rojo|Menudo", "Zuppa di gamberi|Caldo de camarón|Mexican shrimp soup", "Aguachile|Aguachile|Aguachile",
        "Pesce alla veracruzana|Pescado a la veracruzana|Veracruz-style fish", "Gamberi all'aglio|Camarones al ajillo|Mexican garlic shrimp",
        "Pollo al mole|Pollo con mole|Chicken mole", "Mole negro oaxaqueño|Mole negro oaxaqueño|Oaxacan mole negro",
        "Chiles en nogada|Chiles en nogada|Chiles en nogada", "Elote|Elote|Elote Mexican street corn", "Esquites|Esquites|Esquites",
        "Atole|Atole de vainilla|Atole", "Riso messicano|Arroz mexicano|Mexican rice", "Frijoles de la olla|Frijoles de la olla|Frijoles de olla",
        "Salsa verde|Salsa verde|Mexican salsa verde", "Rajas con crema|Rajas con crema|Rajas poblanas con crema",
    ],
}  #[cite: 2]


def _crea_piatto_da_riga(riga, nazione):
    parti = [p.strip() for p in riga.split("|")]
    ita = parti[0]
    orig = parti[1] if len(parti) > 1 else None
    eng = parti[2] if len(parti) > 2 else orig
    etichetta = f"{ita} ({orig})" if (orig and chiave_piatto(orig) != chiave_piatto(ita)) else ita
    return Piatto(etichetta, ita, orig, eng, nazione)  #[cite: 2]


DATABASE_NAZIONI = {
    nazione: [_crea_piatto_da_riga(r, nazione) for r in righe]
    for nazione, righe in DATABASE_NAZIONI_RAW.items()
}  #[cite: 2]
PIATTI_REGIONI = {
    regione: [Piatto(nome, nome) for nome in nomi]
    for regione, nomi in DATABASE_REGIONI_ITALIA.items()
}  #[cite: 2]


def normalizza_nome_regione(testo):
    testo = str(testo or "").strip().lower().replace("\u2019", "'")
    testo = senza_accenti(testo)
    return re.sub(r"[-\s']+", " ", testo).strip()  #[cite: 2]


_INDICE_REGIONI_ITALIA = {normalizza_nome_regione(n): n for n in DATABASE_REGIONI_ITALIA}  #[cite: 2]


def cerca_ricette_per_regione(nome_regione):
    nome = _INDICE_REGIONI_ITALIA.get(normalizza_nome_regione(nome_regione))
    if not nome:
        return None, []
    return nome, PIATTI_REGIONI[nome]  #[cite: 2]


# ==========================================
# INTERFACCIA GRAFICA FLET (ANDROID)
# ==========================================

def main(page: ft.Page):
    page.title = "Chef Stellato"  #[cite: 2]
    page.bgcolor = COL_BG  #[cite: 2]
    page.theme_mode = ft.ThemeMode.LIGHT
    page.scroll = ft.ScrollMode.AUTO
    page.padding = 16

    stato_ricerca = {"in_corso": False}

    def mostra_avviso(titolo, testo):
        dlg = ft.AlertDialog(
            title=ft.Text(titolo, weight=ft.FontWeight.BOLD, color=COL_BLU),
            content=ft.Text(testo, color="#333333"),
            actions=[ft.TextButton("OK", on_click=lambda e: page.close(dlg))],
        )
        page.open(dlg)

    def mostra_dettaglio_ricetta(dati):
        img_locale = ottieni_immagine_locale(dati)
        controlli_img = []
        if img_locale and os.path.exists(img_locale):
            controlli_img.append(
                ft.Container(
                    content=ft.Image(src=img_locale, height=210, fit=ft.ImageFit.COVER, border_radius=12),
                    border_radius=12,
                    clip_behavior=ft.ClipBehavior.HARD_EDGE,
                )
            )
        elif dati.get("immagine"):
            controlli_img.append(
                ft.Container(
                    content=ft.Image(src=dati["immagine"], height=210, fit=ft.ImageFit.COVER, border_radius=12),
                    border_radius=12,
                    clip_behavior=ft.ClipBehavior.HARD_EDGE,
                )
            )

        def card_meta(icona, etichetta, valore):
            return ft.Container(
                expand=True,
                bgcolor=COL_CARD_BG,
                border=ft.border.all(1, COL_CARD_BORDER),
                border_radius=10,
                padding=10,
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=2,
                    controls=[
                        ft.Text(icona, size=18),
                        ft.Text(etichetta, size=10, weight=ft.FontWeight.BOLD, color="#888888"),
                        ft.Text(str(valore), size=12, weight=ft.FontWeight.BOLD, color=COL_BLU, text_align=ft.TextAlign.CENTER),
                    ],
                ),
            )

        lista_ingredienti = [
            ft.Text(f"• {ing}", size=13, color="#333333") for ing in dati.get("ingredienti", [])
        ]

        lista_step = []
        for idx, step in enumerate(dati.get("istruzioni", []), start=1):
            lista_step.append(
                ft.Container(
                    bgcolor=COL_CARD_BG,
                    border=ft.border.all(1, COL_CARD_BORDER),
                    border_radius=10,
                    padding=10,
                    content=ft.Row(
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            ft.Container(
                                width=28,
                                height=28,
                                bgcolor=COL_ARANCIO,
                                border_radius=14,
                                alignment=ft.alignment.center,
                                content=ft.Text(str(idx), color="white", weight=ft.FontWeight.BOLD, size=12),
                            ),
                            ft.Text(step, size=13, color="#333333", expand=True),
                        ],
                    ),
                )
            )

        testo_fonte = f"Fonte: {dati.get('fonte', '')}"
        if dati.get("fonte_immagine"):
            testo_fonte += f"\nFoto: {dati['fonte_immagine']}"

        dlg_ricetta = ft.AlertDialog(
            modal=True,
            title=ft.Text(dati.get("titolo", "Ricetta"), size=18, weight=ft.FontWeight.BOLD, color=COL_ORO),
            content=ft.Container(
                width=420,
                height=520,
                content=ft.Column(
                    scroll=ft.ScrollMode.AUTO,
                    spacing=12,
                    controls=[
                        *controlli_img,
                        ft.Row(
                            controls=[
                                card_meta("⭐", "DIFFICOLTÀ", dati.get("difficolta", "Media")),
                                card_meta("⏱️", "PREP", dati.get("tempo_prep", "N/D")),
                                card_meta("🔥", "COTTURA", dati.get("tempo_cottura", "N/D")),
                            ]
                        ),
                        ft.Text("🧂 Ingredienti", size=15, weight=ft.FontWeight.BOLD, color=COL_BLU),
                        ft.Container(
                            bgcolor=COL_CARD_BG,
                            border=ft.border.all(1, COL_CARD_BORDER),
                            border_radius=10,
                            padding=12,
                            content=ft.Column(spacing=4, controls=lista_ingredienti),
                        ),
                        ft.Text("👩‍🍳 Preparazione passo-passo", size=15, weight=ft.FontWeight.BOLD, color=COL_BLU),
                        ft.Column(spacing=8, controls=lista_step),
                        ft.Text(testo_fonte, size=11, color="#777777"),
                    ],
                ),
            ),
            actions=[
                ft.ElevatedButton(
                    "Chiudi Ricetta",
                    bgcolor=COL_BLU,
                    color="white",
                    on_click=lambda e: page.close(dlg_ricetta),
                )
            ],
        )
        page.open(dlg_ricetta)

    def mostra_schermata_attivazione():
        page.controls.clear()
        campo_codice = ft.TextField(
            label="Codice di attivazione (es. A001)",
            hint_text="Inserisci il codice da A001 ad A100",
            text_align=ft.TextAlign.CENTER,
            bgcolor="white",
            border_color=COL_BLU,
        )
        testo_esito = ft.Text("", color="#a33a3a", size=12, text_align=ft.TextAlign.CENTER)
        bottone_attiva = ft.ElevatedButton(
            "ATTIVA ORA",
            bgcolor=COL_ARANCIO,
            color="white",
            height=46,
        )
        progresso = ft.ProgressRing(visible=False, width=24, height=24, color=COL_ARANCIO)

        def on_attiva(e):
            cod = (campo_codice.value or "").strip()
            if not cod:
                testo_esito.value = "Inserisci un codice di attivazione valido."
                page.update()
                return
            bottone_attiva.disabled = True
            progresso.visible = True
            testo_esito.value = "Verifica del codice in corso..."
            testo_esito.color = COL_BLU
            page.update()

            def lavoro():
                ok, msg = verifica_o_attiva(cod)

                def dopo():
                    progresso.visible = False
                    if ok:
                        mostra_schermata_principale()
                    else:
                        bottone_attiva.disabled = False
                        testo_esito.color = "#a33a3a"
                        testo_esito.value = msg
                        page.update()

                page.run_thread(dopo)

            threading.Thread(target=lavoro, daemon=True).start()

        bottone_attiva.on_click = on_attiva
        campo_codice.on_submit = on_attiva

        page.add(
            ft.Container(
                padding=ft.padding.only(top=30),
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=16,
                    controls=[
                        ft.Text("Chef Stellato", size=28, weight=ft.FontWeight.BOLD, color=COL_ORO),
                        ft.Text(
                            "Prima attivazione richiesta (connessione internet necessaria).\n"
                            "Dopo l'attivazione non ti verrà più richiesto.",
                            size=13,
                            color="#444444",
                            text_align=ft.TextAlign.CENTER,
                        ),
                        campo_codice,
                        ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[bottone_attiva, progresso]),
                        testo_esito,
                    ],
                ),
            )
        )
        page.update()

    def mostra_schermata_principale():
        page.controls.clear()

        campo_ricerca = ft.TextField(
            label="Cerca una ricetta",
            hint_text="Digita il nome di una ricetta...",
            bgcolor="white",
            border_color=COL_ARANCIO,
        )
        campo_regione = ft.TextField(
            label="Regione italiana",
            hint_text="Es. Toscana...",
            bgcolor="white",
            border_color=COL_VERDE_SALVIA,
            text_size=13,
        )
        dropdown_nazione = ft.Dropdown(
            label="Nazione",
            bgcolor="white",
            border_color=COL_BLU,
            text_size=13,
            options=[ft.dropdown.Option(n) for n in DATABASE_NAZIONI.keys()],
        )

        btn_cerca = ft.ElevatedButton(
            "TROVA LA RICETTA STEP BY STEP",
            bgcolor=COL_ARANCIO,
            color="white",
            height=46,
        )

        def avvia_ricerca(piatto=None):
            if stato_ricerca["in_corso"]:
                return
            if piatto is None:
                testo = (campo_ricerca.value or "").strip()
                if not testo:
                    mostra_avviso("Attenzione", "Per favore, scrivi una ricetta.")
                    return
                piatto = Piatto(testo, testo)

            stato_ricerca["in_corso"] = True
            btn_cerca.disabled = True
            annulla = threading.Event()
            stato_lbl = ft.Text("Ricetta in caricamento dal web...\nUn istante di pazienza.", color=COL_BLU, text_align=ft.TextAlign.CENTER)

            def annulla_click(e):
                annulla.set()
                page.close(dlg_loading)

            dlg_loading = ft.AlertDialog(
                modal=True,
                title=ft.Text("Attendere", color=COL_BLU, weight=ft.FontWeight.BOLD),
                content=ft.Column(
                    tight=True,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=14,
                    controls=[ft.ProgressRing(color=COL_ARANCIO), stato_lbl],
                ),
                actions=[ft.TextButton("Annulla", on_click=annulla_click)],
            )
            page.open(dlg_loading)

            def aggiorna_stato(msg):
                if not annulla.is_set():
                    stato_lbl.value = msg
                    page.run_thread(page.update)

            def esegui_bg():
                try:
                    dati, errore = cerca_e_estrae_ricetta(piatto, callback_stato=aggiorna_stato, annulla=annulla)
                except Exception as exc:
                    dati, errore = None, f"Errore imprevisto: {exc}"

                def fine():
                    stato_ricerca["in_corso"] = False
                    btn_cerca.disabled = False
                    try:
                        page.close(dlg_loading)
                    except Exception:
                        pass
                    page.update()
                    if annulla.is_set():
                        return
                    if errore:
                        mostra_avviso("Errore", errore)
                    elif dati:
                        mostra_dettaglio_ricetta(dati)

                page.run_thread(fine)

            threading.Thread(target=esegui_bg, daemon=True).start()

        btn_cerca.on_click = lambda e: avvia_ricerca(None)
        campo_ricerca.on_submit = lambda e: avvia_ricerca(None)

        def apri_elenco_piatti(titolo, piatti):
            if not piatti:
                mostra_avviso("Errore", "Nessuna ricetta disponibile.")
                return

            col_lista = ft.ListView(expand=True, spacing=4)
            for p in piatti:
                gia = " ✓" if CACHE_RICETTE.get(p.chiave) else ""
                col_lista.controls.append(
                    ft.ListTile(
                        title=ft.Text(f"{p.etichetta}{gia}", size=13),
                        on_click=lambda e, piatto_scelto=p: (
                            page.close(dlg_elenco),
                            setattr(campo_ricerca, "value", piatto_scelto.etichetta),
                            page.update(),
                            avvia_ricerca(piatto_scelto),
                        ),
                    )
                )

            dlg_elenco = ft.AlertDialog(
                title=ft.Text(titolo, size=16, weight=ft.FontWeight.BOLD, color=COL_BLU),
                content=ft.Container(width=400, height=420, content=col_lista),
                actions=[ft.TextButton("Chiudi", on_click=lambda e: page.close(dlg_elenco))],
            )
            page.open(dlg_elenco)

        def cerca_regione(e):
            val = (campo_regione.value or "").strip()
            if not val:
                mostra_avviso("Attenzione", "Inserisci il nome di una regione italiana.")
                return
            nome_reg, piatti_reg = cerca_ricette_per_regione(val)
            if not nome_reg:
                mostra_avviso("Errore", "Regione non riconosciuta.\nScrivi il nome di una regione italiana (es. Toscana, Sicilia, Veneto...).")
                return
            apri_elenco_piatti(f"Ricette tipiche: {nome_reg}", piatti_reg)

        campo_regione.on_submit = cerca_regione

        def cerca_nazione(e):
            scelta = dropdown_nazione.value
            if not scelta or scelta not in DATABASE_NAZIONI:
                mostra_avviso("Attenzione", "Seleziona una nazione valida dal menu.")
                return
            apri_elenco_piatti(f"Ricette tradizionali: {scelta}", DATABASE_NAZIONI[scelta])

        def apri_salvate(e):
            if not len(CACHE_RICETTE):
                mostra_avviso("Ricette Salvate", "Non hai ancora nessuna ricetta salvata.\nCercane una per iniziare a costruire il tuo ricettario personale.")
                return
            ricette_ord = sorted(CACHE_RICETTE.valori(), key=lambda d: str(d.get("titolo", "")).lower())
            lista_s = ft.ListView(expand=True, spacing=4)
            for d in ricette_ord:
                lista_s.controls.append(
                    ft.ListTile(
                        title=ft.Text(d.get("titolo", "Senza titolo"), size=13),
                        subtitle=ft.Text("Salvata", size=11, color="#777777"),
                        on_click=lambda ev, dati_scelti=d: (
                            page.close(dlg_salvate),
                            mostra_dettaglio_ricetta(dati_scelti),
                        ),
                    )
                )

            def svuota_tutto(ev):
                svuota_cache_ricette()
                page.close(dlg_salvate)
                mostra_avviso("Ricette Salvate", "Tutte le ricette salvate sono state eliminate.")

            dlg_salvate = ft.AlertDialog(
                title=ft.Text(f"Le tue ricette salvate ({len(CACHE_RICETTE)})", size=16, weight=ft.FontWeight.BOLD, color=COL_BLU),
                content=ft.Container(width=400, height=400, content=lista_s),
                actions=[
                    ft.TextButton("Svuota", on_click=svuota_tutto),
                    ft.TextButton("Chiudi", on_click=lambda ev: page.close(dlg_salvate)),
                ],
            )
            page.open(dlg_salvate)

        def apri_info(e):
            mostra_avviso(
                "Note Legali & Informazioni",
                "Chef Stellato è un'applicazione puramente informativa che facilita la ricerca e la consultazione di "
                "ricette disponibili pubblicamente sul web.\n\nI testi, le immagini e le informazioni estratte "
                "appartengono ai rispettivi proprietari e creatori dei siti di origine.\n\nL'applicazione agisce come "
                "semplice strumento di aggregazione e indica sempre la fonte originale.\n\nInclude ricette tradizionali e "
                "dolci tipici da Francia, Gran Bretagna, Russia, Germania, Austria, Belgio, Svizzera e Messico.",
            )

        scheda_regione = ft.Container(
            expand=True,
            bgcolor=COL_CARD_BG,
            border=ft.border.all(2, COL_VERDE_SALVIA),
            border_radius=12,
            padding=12,
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8,
                controls=[
                    ft.Text("🍝 Per Regione", size=13, weight=ft.FontWeight.BOLD, color=COL_VERDE_SALVIA_SCURO),
                    campo_regione,
                    ft.ElevatedButton("TROVA", bgcolor=COL_VERDE_SALVIA, color="white", on_click=cerca_regione),
                ],
            ),
        )

        scheda_nazioni = ft.Container(
            expand=True,
            bgcolor=COL_CARD_BG,
            border=ft.border.all(2, COL_BLU),
            border_radius=12,
            padding=12,
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8,
                controls=[
                    ft.Text("🌍 Dal Mondo", size=13, weight=ft.FontWeight.BOLD, color=COL_BLU),
                    dropdown_nazione,
                    ft.ElevatedButton("VEDI PIATTI", bgcolor=COL_BLU, color="white", on_click=cerca_nazione),
                ],
            ),
        )

        page.add(
            ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=14,
                controls=[
                    ft.Text("Chef Stellato", size=28, weight=ft.FontWeight.BOLD, color=COL_ORO),
                    campo_ricerca,
                    btn_cerca,
                    ft.Row(spacing=10, controls=[scheda_regione, scheda_nazioni]),
                    ft.TextButton("📚 Le Mie Ricette Salvate", on_click=apri_salvate),
                    ft.TextButton("ℹ️ Note Legali & Info", on_click=apri_info),
                ],
            )
        )
        page.update()

    if e_gia_attivato():
        mostra_schermata_principale()
    else:
        mostra_schermata_attivazione()


if __name__ == "__main__":
    ft.app(target=main)
