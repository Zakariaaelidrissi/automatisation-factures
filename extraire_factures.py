import csv
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import pdfplumber

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
RESULTATS = BASE / "resultats"
RESULTATS.mkdir(exist_ok=True)
MOIS = {m: i for i, m in enumerate(["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"], start=1)}

with open(DATA / "fournisseurs.csv", encoding="utf-8-sig") as fh:
    NOMS = [r["nom"] for r in csv.DictReader(fh, delimiter=";")]


def montant_fr(s):
    return round(float(s.replace(" ", "").replace("\xa0", "").replace(".", "").replace(",", ".")) * 100)


def montant_pt(s):
    return round(float(s) * 100)


def montant_c(s):
    return montant_fr(s)


def date_a(s):
    j, m, a = s.split("/")
    return date(int(a), int(m), int(j))


def date_b(s):
    j, m, a = s.split()
    return date(int(a), MOIS[m], int(j))


def date_c(s):
    j, m, a = s.split(".")
    return date(int(a), int(m), int(j))


def trouver(motif, texte, flags=0):
    m = re.search(motif, texte, flags)
    return m.group(1) if m else None


def commun(t):
    siren = trouver(r"SIREN\s*:?\s*(\d{3} ?\d{3} ?\d{3})(?!\d)", t)
    iban = trouver(r"\b(FR\d{2}[ \d]{22,30}\d)\b", t)
    return {
        "siren": siren.replace(" ", "") if siren else None,
        "tva_intra": trouver(r"TVA\s*(?:intracommunautaire)?\s*:?\s*(FR\d{11})(?!\d)", t),
        "iban": iban.replace(" ", "") if iban else None,
        "fournisseur": next((n for n in NOMS if n in t), None),
    }


def lire_a(t):
    r = commun(t)
    r.update(
        numero=trouver(r"^N° (?!TVA)(\S+)\s*$", t, re.M),
        date_facture=trouver(r"Date : (\d{2}/\d{2}/\d{4})", t),
        echeance=trouver(r"Échéance : (\d{2}/\d{2}/\d{4})", t),
        total_ht=trouver(r"Total HT ([\d ]+,\d{2}) €", t),
        taux_tva=trouver(r"TVA ([\d,]+) % [\d ]+,\d{2} €", t),
        montant_tva=trouver(r"TVA [\d,]+ % ([\d ]+,\d{2}) €", t),
        total_ttc=trouver(r"Total TTC ([\d ]+,\d{2}) €", t),
    )
    conv = montant_fr
    for k in ("date_facture", "echeance"):
        r[k] = date_a(r[k]) if r[k] else None
    r["taux_tva"] = r["taux_tva"].replace(",", ".") if r["taux_tva"] else None
    return r, conv


def lire_b(t):
    r = commun(t)
    r.update(
        numero=trouver(r"Réf\. facture : (\S+)", t),
        date_facture=trouver(r"Date d'émission : (\d{1,2} \S+ \d{4})", t),
        echeance=trouver(r"Date d'échéance : (\d{1,2} \S+ \d{4})", t),
        total_ht=trouver(r"Sous-total HT (\d+\.\d{2}) EUR", t),
        taux_tva=trouver(r"TVA \(([\d.]+)%\)", t),
        montant_tva=trouver(r"TVA \([\d.]+%\) (\d+\.\d{2}) EUR", t),
        total_ttc=trouver(r"Net à payer (\d+\.\d{2}) EUR", t),
    )
    for k in ("date_facture", "echeance"):
        r[k] = date_b(r[k]) if r[k] else None
    return r, montant_pt


def lire_c(t):
    r = commun(t)
    r.update(
        numero=trouver(r"Facture n° (\S+) du", t),
        date_facture=trouver(r"Facture n° \S+ du (\d{2}\.\d{2}\.\d{4})", t),
        echeance=trouver(r"avant le (\d{2}\.\d{2}\.\d{4})", t),
        total_ht=trouver(r"Montant HT : ([\d.]+,\d{2}) €", t),
        taux_tva=trouver(r"TVA ([\d,]+) % : [\d.]+,\d{2} €", t),
        montant_tva=trouver(r"TVA [\d,]+ % : ([\d.]+,\d{2}) €", t),
        total_ttc=trouver(r"Montant TTC à régler avant le \S+ : ([\d.]+,\d{2}) €", t),
    )
    for k in ("date_facture", "echeance"):
        r[k] = date_c(r[k]) if r[k] else None
    r["taux_tva"] = r["taux_tva"].replace(",", ".") if r["taux_tva"] else None
    return r, montant_c


def detecter(t):
    if "Réf. facture" in t:
        return "B", lire_b
    if "Désignation" in t and "FACTURE" in t:
        return "A", lire_a
    if re.search(r"Facture n° \S+ du", t):
        return "C", lire_c
    return None, None


CHAMPS = ["fichier", "mise_en_page", "fournisseur", "siren", "tva_intra", "numero", "date_facture", "echeance", "total_ht", "taux_tva", "montant_tva", "total_ttc", "iban"]
MONTANTS = ("total_ht", "montant_tva", "total_ttc")

lignes, illisibles = [], []
fichiers = sorted((DATA / "factures").glob("*.pdf"))
for chemin in fichiers:
    with pdfplumber.open(chemin) as pdf:
        texte = "\n".join((p.extract_text() or "").replace("\xa0", " ") for p in pdf.pages)
    layout, lecteur = detecter(texte)
    if lecteur is None:
        illisibles.append(chemin.name)
        continue
    r, conv = lecteur(texte)
    for k in MONTANTS:
        r[k] = conv(r[k]) if r[k] else None
    r["fichier"], r["mise_en_page"] = chemin.name, layout
    lignes.append(r)


def cellule(k, v):
    if v is None:
        return ""
    if k in MONTANTS:
        return f"{v / 100:.2f}"
    if isinstance(v, date):
        return v.isoformat()
    return v


with open(DATA / "factures_extraites.csv", "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.writer(fh, delimiter=";")
    w.writerow(CHAMPS)
    for r in lignes:
        w.writerow([cellule(k, r[k]) for k in CHAMPS])

sortie = []
p = sortie.append
p(f"Fichiers PDF lus : {len(fichiers)}")
p(f"Extraits : {len(lignes)} ; illisibles : {len(illisibles)} {illisibles if illisibles else ''}")
p("Mises en page : " + ", ".join(f"{k} = {v}" for k, v in sorted(Counter(r['mise_en_page'] for r in lignes).items())))
manquants = Counter(k for r in lignes for k in CHAMPS if r.get(k) is None)
p("Champs non trouvés : " + (", ".join(f"{k} ({v})" for k, v in manquants.items()) if manquants else "aucun"))

verite_chemin = DATA / "verite_extraction.csv"
if verite_chemin.exists():
    with open(verite_chemin, encoding="utf-8-sig") as fh:
        verite = {r["fichier"]: r for r in csv.DictReader(fh, delimiter=";")}
    colonnes = ["fournisseur", "siren", "numero", "date_facture", "echeance", "total_ht", "taux_tva", "montant_tva", "total_ttc", "iban"]
    bons, total, erreurs, par_layout = Counter(), Counter(), [], defaultdict(lambda: [0, 0])
    for r in lignes:
        v = verite[r["fichier"]]
        ok_fichier = True
        for k in colonnes:
            total[k] += 1
            lu = cellule(k, r[k])
            if str(lu) == v[k] or (k == "taux_tva" and lu and float(lu) == float(v[k])):
                bons[k] += 1
            else:
                ok_fichier = False
                erreurs.append((r["fichier"], k, lu, v[k]))
        par_layout[r["mise_en_page"]][0] += ok_fichier
        par_layout[r["mise_en_page"]][1] += 1
    p("")
    p("Contrôle de l'extraction contre le fichier de vérité (évaluation uniquement)")
    for k in colonnes:
        p(f"  {k:<14}{bons[k]:>4} / {total[k]:<4}{100 * bons[k] / total[k]:>7.1f} %")
    for k, (a, b) in sorted(par_layout.items()):
        p(f"  Mise en page {k} : {a} / {b} factures lues sans aucune erreur")
    p(f"  Factures lues sans aucune erreur : {sum(a for a, _ in par_layout.values())} / {sum(b for _, b in par_layout.values())}")
    for e in erreurs[:15]:
        p(f"  ECART {e[0]} {e[1]} : lu '{e[2]}' ; attendu '{e[3]}'")

texte_sortie = "\n".join(sortie)
(RESULTATS / "extraction.txt").write_text(texte_sortie, encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")
print(texte_sortie)
