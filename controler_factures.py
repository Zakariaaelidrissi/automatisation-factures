import csv
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
RESULTATS = BASE / "resultats"
RESULTATS.mkdir(exist_ok=True)
DEBUT, FIN = date(2026, 1, 1), date(2026, 10, 31)

GRAVITE = {
    "IBAN_MODIFIE": "Haute",
    "DOUBLON_EXACT": "Haute",
    "DOUBLON_RENUMEROTE": "Haute",
    "ERREUR_TOTAL": "Haute",
    "TAUX_TVA_ANORMAL": "Haute",
    "SIREN_INVALIDE": "Moyenne",
    "TVA_INTRA_INCOHERENT": "Moyenne",
    "IBAN_INVALIDE": "Haute",
    "ERREUR_CALCUL_TVA": "Moyenne",
    "DATE_INCOHERENTE": "Moyenne",
    "FACTURE_HORS_EXERCICE": "Moyenne",
}


def lire(nom):
    with open(DATA / nom, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


def luhn_ok(s):
    total = 0
    for i, ch in enumerate(reversed(s)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            d -= 9 if d > 9 else 0
        total += d
    return total % 10 == 0


def cle_tva(siren):
    return f"{(12 + 3 * (int(siren) % 97)) % 97:02d}"


def iban_ok(iban):
    if len(iban) != 27 or not iban.startswith("FR"):
        return False
    rearrange = iban[4:] + iban[:4]
    return int("".join(str(int(c, 36)) for c in rearrange)) % 97 == 1


def cents(s):
    return round(float(s) * 100)


factures = lire("factures_extraites.csv")
ref = {r["nom"]: r for r in lire("fournisseurs.csv")}
for f in factures:
    f["date"] = date.fromisoformat(f["date_facture"])
    f["ech"] = date.fromisoformat(f["echeance"])
    f["ht"], f["tva"], f["ttc"] = cents(f["total_ht"]), cents(f["montant_tva"]), cents(f["total_ttc"])

anomalies = []


def signaler(type_, f, detail, lie=""):
    anomalies.append(dict(type=type_, gravite=GRAVITE[type_], fichier=f["fichier"], fichier_lie=lie, numero=f["numero"], fournisseur=f["fournisseur"],
                          total_ttc=f["total_ttc"], detail=detail))


for f in factures:
    r = ref.get(f["fournisseur"])
    if not luhn_ok(f["siren"]):
        signaler("SIREN_INVALIDE", f, f"SIREN {f['siren']} : clé de Luhn incorrecte (référentiel : {r['siren'] if r else 'inconnu'})")
    base = f["tva_intra"][4:]
    if f["tva_intra"][2:4] != cle_tva(base):
        signaler("TVA_INTRA_INCOHERENT", f, f"N° TVA {f['tva_intra']} : clé attendue {cle_tva(base)}")
    if not iban_ok(f["iban"]):
        signaler("IBAN_INVALIDE", f, f"IBAN {f['iban']} : clé de contrôle mod 97 incorrecte")
    if r and f["iban"] != r["iban"]:
        signaler("IBAN_MODIFIE", f, f"IBAN de la facture différent du référentiel ({r['iban'][-6:]} attendu, {f['iban'][-6:]} reçu)")
    if f["ht"] + f["tva"] != f["ttc"]:
        signaler("ERREUR_TOTAL", f, f"HT + TVA = {(f['ht'] + f['tva']) / 100:.2f} mais TTC imprimé {f['ttc'] / 100:.2f}")
    attendu = round(f["ht"] * float(f["taux_tva"]) / 100)
    if abs(attendu - f["tva"]) > 1:
        signaler("ERREUR_CALCUL_TVA", f, f"TVA calculée {attendu / 100:.2f} mais imprimée {f['tva'] / 100:.2f}")
    if r and float(f["taux_tva"]) != float(r["taux_tva_habituel"]):
        signaler("TAUX_TVA_ANORMAL", f, f"Taux {float(f['taux_tva']):g} % au lieu de {float(r['taux_tva_habituel']):g} % habituel")
    if f["ech"] < f["date"]:
        signaler("DATE_INCOHERENTE", f, "Échéance antérieure à la date de facture")
    if not DEBUT <= f["date"] <= FIN:
        signaler("FACTURE_HORS_EXERCICE", f, f"Date {f['date_facture']} hors de la période {DEBUT.isoformat()} à {FIN.isoformat()}")

par_numero = defaultdict(list)
par_empreinte = defaultdict(list)
for f in sorted(factures, key=lambda x: x["fichier"]):
    par_numero[(f["fournisseur"], f["numero"])].append(f)
    par_empreinte[(f["fournisseur"], f["date_facture"], f["ttc"])].append(f)
vus = set()
for groupe in par_numero.values():
    for autre in groupe[1:]:
        signaler("DOUBLON_EXACT", autre, f"Même numéro {autre['numero']} que {groupe[0]['fichier']}", lie=groupe[0]["fichier"])
        vus.add(frozenset((autre["fichier"], groupe[0]["fichier"])))
for groupe in par_empreinte.values():
    for autre in groupe[1:]:
        if frozenset((autre["fichier"], groupe[0]["fichier"])) not in vus:
            signaler("DOUBLON_RENUMEROTE", autre, f"Mêmes fournisseur, date et montant que {groupe[0]['fichier']} ({groupe[0]['numero']} / {autre['numero']})", lie=groupe[0]["fichier"])

anomalies.sort(key=lambda a: (a["type"], a["fichier"]))
colonnes = ["type", "gravite", "fichier", "fichier_lie", "numero", "fournisseur", "total_ttc", "detail"]
with open(RESULTATS / "anomalies_factures.csv", "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.DictWriter(fh, fieldnames=colonnes, delimiter=";")
    w.writeheader()
    w.writerows(anomalies)

sortie = []
p = sortie.append
p(f"Factures contrôlées : {len(factures)}")
p(f"Anomalies détectées : {len(anomalies)} sur {len({a['fichier'] for a in anomalies})} factures")
p("")
p(f"{'Contrôle':<26}{'Gravité':<10}{'Détectées':>10}")
for t, n in sorted(Counter(a["type"] for a in anomalies).items()):
    p(f"{t:<26}{GRAVITE[t]:<10}{n:>10}")
montant_en_cause = sum(cents(a["total_ttc"]) for a in anomalies if a["type"] in ("DOUBLON_EXACT", "DOUBLON_RENUMEROTE"))
p("")
p(f"Montant TTC des doublons détectés : {montant_en_cause / 100:,.2f} €".replace(",", " "))

verite_chemin = DATA / "scenario_anomalies.csv"
if verite_chemin.exists():
    verite = [r for r in lire("scenario_anomalies.csv") if r["fichier"]]
    types_verite = {r["type"] for r in verite} & set(GRAVITE)
    p("")
    p("Contrôle contre le corrigé caché (évaluation uniquement ; les anomalies de paiement sont traitées à l'étape suivante)")
    p(f"{'Type':<26}{'Injectées':>10}{'Trouvées':>10}{'Fausses alertes':>17}")
    tot_i = tot_t = tot_f = 0
    manques, fausses = [], []
    for t in sorted(GRAVITE):
        v = [r for r in verite if r["type"] == t]
        d = [a for a in anomalies if a["type"] == t]
        trouvees = 0
        for r in v:
            if any(a["fichier"] == r["fichier"] or a["fichier_lie"] == r["fichier"] for a in d):
                trouvees += 1
            else:
                manques.append((t, r["fichier"], r["detail"]))
        faux = [a for a in d if not any(r["fichier"] in (a["fichier"], a["fichier_lie"]) for r in v)]
        fausses += [(t, a["fichier"], a["detail"]) for a in faux]
        tot_i += len(v)
        tot_t += trouvees
        tot_f += len(faux)
        p(f"{t:<26}{len(v):>10}{trouvees:>10}{len(faux):>17}")
    p(f"{'Total':<26}{tot_i:>10}{tot_t:>10}{tot_f:>17}")
    for t, fich, d in manques:
        p(f"  NON DÉTECTÉE {t} {fich} : {d}")
    for t, fich, d in fausses:
        p(f"  FAUSSE ALERTE {t} {fich} : {d}")

texte = "\n".join(sortie)
(RESULTATS / "controle_factures.txt").write_text(texte, encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")
print(texte)
