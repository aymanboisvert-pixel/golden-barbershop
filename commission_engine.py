from __future__ import annotations

import hashlib
import io
import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable

import pandas as pd


PAY_PERIOD_ANCHOR = date(2026, 9, 3)
OWNER = "Ayman"
SPECIAL_PRICE = Decimal("29.99")
SMALL_SALE_MAX = Decimal("14.99")


NAME_MAP = {
    "ayman": "Ayman",
    "carlos": "Carlos",
    "alexandre": "Alexandre",
    "alexandre thibaudeau": "Alexandre",
    "alex thib": "Alexandre",
    "charlo": "Charlo",
    "charlotte": "Charlo",
    "charles olivier marois": "Charlo",
    "edgar": "Edgard",
    "edgard": "Edgard",
    "jacob": "Jacob",
    "jakob": "Jacob",
    "noah": "Noah",
    "antoine": "Antoine",
}


TRANSACTION_COLUMNS = [
    "date",
    "barbier",
    "client",
    "vente_nette",
    "pourboire",
    "mode_paiement",
    "source",
    "transaction_id",
]


def _plain_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _key(value: object) -> str:
    text = unicodedata.normalize("NFKD", _plain_text(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text).strip().lower()
    return text


def normalize_barber(value: object) -> str:
    raw = _plain_text(value)
    if not raw:
        return "Non attribué"
    return NAME_MAP.get(_key(raw), raw.title())


def parse_money(value: object) -> Decimal:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return Decimal("0")
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if isinstance(value, (int, float)):
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = _plain_text(value)
    if not text:
        return Decimal("0")
    text = text.replace("\u00a0", "").replace("$", "").replace(" ", "")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    text = re.sub(r"[^0-9.\-]", "", text)
    try:
        return Decimal(text or "0").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return Decimal("0")


def parse_date(value: object) -> pd.Timestamp:
    text = _plain_text(value)
    if not text:
        return pd.NaT
    formats = (
        "%d-%b-%Y %I:%M %p %Z",
        "%d-%b-%Y %I:%M %p EDT",
        "%d-%b-%Y %I:%M %p EST",
        "%Y-%m-%d",
        "%d/%m/%Y",
    )
    for fmt in formats:
        try:
            return pd.Timestamp(datetime.strptime(text, fmt))
        except ValueError:
            pass
    months = {
        "janv": "Jan", "janvier": "Jan", "fevr": "Feb", "fevrier": "Feb",
        "mars": "Mar", "avr": "Apr", "avril": "Apr", "mai": "May",
        "juin": "Jun", "juil": "Jul", "juillet": "Jul", "aout": "Aug",
        "sept": "Sep", "septembre": "Sep", "oct": "Oct", "octobre": "Oct",
        "nov": "Nov", "novembre": "Nov", "dec": "Dec", "decembre": "Dec",
    }
    normalized = _key(text)
    for french, english in months.items():
        normalized = re.sub(rf"\b{french}\b", english, normalized, flags=re.IGNORECASE)
    return pd.to_datetime(normalized, errors="coerce", dayfirst=True)


def _read_csv(source: object, **kwargs: object) -> pd.DataFrame:
    if hasattr(source, "seek"):
        source.seek(0)
    try:
        return pd.read_csv(source, encoding="utf-8-sig", **kwargs)
    except UnicodeDecodeError:
        if hasattr(source, "seek"):
            source.seek(0)
        return pd.read_csv(source, encoding="latin-1", **kwargs)


def parse_clover_csv(source: object) -> pd.DataFrame:
    raw = _read_csv(source, dtype=str).fillna("")
    required = {
        "Date du paiement",
        "ID du paiement",
        "Mode de paiement",
        "Montant",
        "Montant des taxes",
        "Montant du pourboire",
        "Nom de l'employé au paiement",
        "Résultat",
    }
    missing = sorted(required - set(raw.columns))
    if missing:
        raise ValueError("Colonnes Clover manquantes : " + ", ".join(missing))

    rows = []
    for _, item in raw.iterrows():
        if _plain_text(item["Résultat"]).upper() != "SUCCESS":
            continue
        gross = parse_money(item["Montant"])
        taxes = parse_money(item["Montant des taxes"])
        refund = parse_money(item.get("Montant du remboursement", ""))
        net = max(Decimal("0"), gross - taxes - refund)
        payment_id = _plain_text(item["ID du paiement"])
        rows.append(
            {
                "date": parse_date(item["Date du paiement"]),
                "barbier": normalize_barber(item["Nom de l'employé au paiement"]),
                "client": _plain_text(item.get("Nom du client", "")),
                "vente_nette": float(net),
                "pourboire": float(parse_money(item["Montant du pourboire"])),
                "mode_paiement": _plain_text(item["Mode de paiement"]),
                "source": "Clover",
                "transaction_id": payment_id,
            }
        )
    return finalize_transactions(pd.DataFrame(rows, columns=TRANSACTION_COLUMNS))


def parse_cash_csv(source: object) -> pd.DataFrame:
    content = source
    if isinstance(source, bytes):
        content = io.BytesIO(source)
    raw = _read_csv(content, dtype=str, header=None).fillna("")
    header_index = None
    for idx, row in raw.iterrows():
        keys = {_key(value) for value in row.tolist()}
        if "date" in keys and "barbier" in keys and ("coupe" in keys or "coupe" in " ".join(keys)):
            header_index = idx
            break
    if header_index is None:
        raise ValueError("Impossible de trouver la ligne d'en-têtes Date / Barbier / Coupe dans le fichier CASH.")
    if hasattr(source, "seek"):
        source.seek(0)
    raw = _read_csv(source, dtype=str, header=header_index).fillna("")

    normalized = {_key(col): col for col in raw.columns}
    date_col = normalized.get("date")
    barber_col = normalized.get("barbier")
    client_col = normalized.get("client")
    sale_col = next((col for key, col in normalized.items() if key.startswith("coupe")), None)
    tip_col = next((col for key, col in normalized.items() if key.startswith("tip") or key.startswith("pourboire")), None)
    if not all((date_col, barber_col, sale_col)):
        raise ValueError("Le fichier CASH doit contenir Date, Barbier et Coupe ($).")

    rows = []
    for _, item in raw.iterrows():
        parsed_day = parse_date(item[date_col])
        sale = parse_money(item[sale_col])
        tip = parse_money(item[tip_col]) if tip_col else Decimal("0")
        if pd.isna(parsed_day) and sale == 0 and tip == 0:
            continue
        barber = normalize_barber(item[barber_col])
        client = _plain_text(item[client_col]) if client_col else ""
        signature = f"{parsed_day}|{barber}|{client}|{sale}|{tip}"
        transaction_id = "CASH-" + hashlib.sha1(signature.encode("utf-8")).hexdigest()[:14].upper()
        rows.append(
            {
                "date": parsed_day,
                "barbier": barber,
                "client": client,
                "vente_nette": float(sale),
                "pourboire": float(tip),
                "mode_paiement": "Cash",
                "source": "Google Sheet",
                "transaction_id": transaction_id,
            }
        )
    return finalize_transactions(pd.DataFrame(rows, columns=TRANSACTION_COLUMNS))


def finalize_transactions(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=TRANSACTION_COLUMNS)
    result = frame.copy()
    for col in TRANSACTION_COLUMNS:
        if col not in result.columns:
            result[col] = ""
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result["vente_nette"] = pd.to_numeric(result["vente_nette"], errors="coerce").fillna(0.0).round(2)
    result["pourboire"] = pd.to_numeric(result["pourboire"], errors="coerce").fillna(0.0).round(2)
    result["barbier"] = result["barbier"].map(normalize_barber)
    result = result.dropna(subset=["date"])
    result = result.drop_duplicates(subset=["source", "transaction_id"], keep="last")
    return result[TRANSACTION_COLUMNS].sort_values(["date", "barbier", "transaction_id"]).reset_index(drop=True)


def merge_transactions(frames: Iterable[pd.DataFrame]) -> pd.DataFrame:
    usable = [frame for frame in frames if frame is not None and not frame.empty]
    if not usable:
        return pd.DataFrame(columns=TRANSACTION_COLUMNS)
    return finalize_transactions(pd.concat(usable, ignore_index=True))


def period_bounds(value: object) -> tuple[date, date]:
    day = pd.Timestamp(value).date()
    offset = (day - PAY_PERIOD_ANCHOR).days
    index = offset // 14
    start = PAY_PERIOD_ANCHOR + timedelta(days=index * 14)
    return start, start + timedelta(days=13)


def period_label(start: date, end: date) -> str:
    months = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    if start.month == end.month:
        return f"{start.day}–{end.day} {months[end.month - 1]} {end.year}"
    return f"{start.day} {months[start.month - 1]}–{end.day} {months[end.month - 1]} {end.year}"


def add_commissions(frame: pd.DataFrame) -> pd.DataFrame:
    result = finalize_transactions(frame)
    if result.empty:
        for col in ["periode_debut", "periode_fin", "periode", "regle", "part_barbier", "revenu_entreprise", "a_verser"]:
            result[col] = []
        return result

    starts, ends, labels, rules, barber_parts, business_parts, payouts = [], [], [], [], [], [], []
    for _, item in result.iterrows():
        start, end = period_bounds(item["date"])
        net = Decimal(str(item["vente_nette"])).quantize(Decimal("0.01"))
        tip = Decimal(str(item["pourboire"])).quantize(Decimal("0.01"))
        barber = item["barbier"]
        if barber == OWNER:
            rule = "Ayman — 100 % entreprise"
            barber_part = Decimal("0")
            business_part = net + tip
            payout = Decimal("0")
        elif net == SPECIAL_PRICE:
            rule = "29,99 $ — 100 % entreprise"
            barber_part = Decimal("0")
            business_part = net
            payout = tip
        elif net <= SMALL_SALE_MAX:
            rule = "14,99 $ ou moins — 100 % entreprise"
            barber_part = Decimal("0")
            business_part = net
            payout = tip
        else:
            rule = "Vente normale — 70/30"
            barber_part = (net * Decimal("0.70")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            business_part = net - barber_part
            payout = barber_part + tip
        starts.append(pd.Timestamp(start)); ends.append(pd.Timestamp(end)); labels.append(period_label(start, end)); rules.append(rule)
        barber_parts.append(float(barber_part)); business_parts.append(float(business_part)); payouts.append(float(payout))

    result["periode_debut"] = starts
    result["periode_fin"] = ends
    result["periode"] = labels
    result["regle"] = rules
    result["part_barbier"] = barber_parts
    result["revenu_entreprise"] = business_parts
    result["a_verser"] = payouts
    return result

