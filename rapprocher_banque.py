import csv
import re
import sys
import unicodedata
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
RESULTATS = BASE / "resultats"
RESULTATS.mkdir(exist_ok=True)
TOLERANCE_RETARD = 7


def lire(chemin):
    with open(chemin, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


def sans_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def cents(s):
    return round(float(s) * 100)


factures = lire(DATA / "factures_extraites.csv")
fournisseurs = {r["nom"]: r for r in lire(DATA / "fournisseurs.csv")}
releve = lire(DATA / "releve_bancaire.csv")
doublons = {a["fichier"] for a in lire(RESULTATS / "anomalies_factures.csv") if a["type"] in ("DOUBLON_EXACT", "DOUBLON_RENUMEROTE")}

for f in factures:
    f["date"] = date.fromisoformat(f["date_facture"])
    f["ech"] = date.fromisoformat(f["echeance"])
    f["ttc_c"] = cents(f["total_ttc"])
cles = {n: sans_accents(n).upper()[:26] for n in fournisseurs}
par_iban = {r["iban"]: n for n, r in fournisseurs.items()}
arrete = max(date.fromisoformat(o["date_operation"]) for o in releve)

operations, ignorees = [], Counter()
for o in releve:
    o["date"] = date.fromisoformat(o["date_operation"])
    o["montant_c"] = cents(o["montant"])
    lib = o["libelle"]
    if o["montant_c"] < 0 and lib.startswith(("VIR SEPA ", "PRLV SEPA ")) and "RECU" not in lib:
        o["fournisseur"] = next((n for n, k in cles.items() if k in lib), None) or par_iban.get(o["iban_contrepartie"])
        operations.append(o)
    else:
        ignorees["Encaissements clients" if o["montant_c"] > 0 else "Autres débits (salaires, charges, banque)"] += 1

a_rapprocher = [f for f in factures if f["fichier"] not in doublons]
affectation, methodes = {}, {}
op_prises, fac_prises = set(), set()


def numero_dans(f, o):
    return re.search(r"(?<![A-Z0-9\-])" + re.escape(f["numero"]) + r"(?![A-Z0-9\-])", o["libelle"]) is not None


def passe(nom, condition, score):
    paires = []
    for i, o in enumerate(operations):
        if i in op_prises or not o["fournisseur"]:
            continue
        for j, f in enumerate(a_rapprocher):
            if j in fac_prises or f["fournisseur"] != o["fournisseur"]:
                continue
            if condition(f, o):
                paires.append((score(f, o), i, j))
    for _, i, j in sorted(paires):
        if i not in op_prises and j not in fac_prises:
            op_prises.add(i)
            fac_prises.add(j)
            affectation[j] = i
            methodes[j] = nom


distance = lambda f, o: abs((o["date"] - f["ech"]).days)
egal = lambda f, o: -o["montant_c"] == f["ttc_c"]
apres = lambda f, o: o["date"] >= f["date"] - timedelta(days=10)

passe("Numéro et montant", lambda f, o: egal(f, o) and numero_dans(f, o) and apres(f, o), distance)
passe("Montant seul", lambda f, o: egal(f, o) and apres(f, o) and o["date"] <= f["ech"] + timedelta(days=60), distance)
passe("Numéro, montant différent", lambda f, o: numero_dans(f, o) and apres(f, o), lambda f, o: abs(-o["montant_c"] - f["ttc_c"]))
passe("Approchée (montant proche)", lambda f, o: abs(-o["montant_c"] - f["ttc_c"]) <= 0.2 * f["ttc_c"] and f["date"] - timedelta(days=10) <= o["date"] <= f["ech"] + timedelta(days=15),
      lambda f, o: abs(-o["montant_c"] - f["ttc_c"]) / f["ttc_c"] * 1000 + distance(f, o))

anomalies = []


def signaler(type_, gravite, f, o, detail):
    anomalies.append(dict(type=type_, gravite=gravite, fichier=f["fichier"] if f else "", numero=f["numero"] if f else "", fournisseur=(f or o)["fournisseur"],
                          reference_banque=o["reference_banque"] if o else "", montant=f"{(-o['montant_c'] if o else f['ttc_c']) / 100:.2f}", detail=detail))


suivi = []
for j, f in enumerate(a_rapprocher):
    ligne = dict(fichier=f["fichier"], fournisseur=f["fournisseur"], numero=f["numero"], date_facture=f["date_facture"], echeance=f["echeance"], total_ttc=f["total_ttc"],
                 statut="", methode="", reference_banque="", date_paiement="", montant_paye="", ecart="", jours_apres_echeance="")
    if j in affectation:
        o = operations[affectation[j]]
        paye = -o["montant_c"]
        ecart = paye - f["ttc_c"]
        ligne.update(methode=methodes[j], reference_banque=o["reference_banque"], date_paiement=o["date_operation"], montant_paye=f"{paye / 100:.2f}", ecart=f"{ecart / 100:.2f}",
                     jours_apres_echeance=(o["date"] - f["ech"]).days, statut="Rapprochée" if ecart == 0 else "Écart de paiement")
        if ecart:
            signaler("ECART_PAIEMENT", "Haute", f, o, f"Payé {paye / 100:.2f} € pour {f['ttc_c'] / 100:.2f} € dus ({100 * ecart / f['ttc_c']:+.1f} %)")
        if o["date"] < f["date"]:
            signaler("PAIEMENT_ANTERIEUR_FACTURE", "Moyenne", f, o, f"Paiement du {o['date_operation']} antérieur à la date de facture {f['date_facture']}")
        ref_iban = fournisseurs[f["fournisseur"]]["iban"]
        if o["iban_contrepartie"] and o["iban_contrepartie"] != ref_iban:
            signaler("PAIEMENT_IBAN_HORS_REFERENTIEL", "Haute", f, o, f"Paiement viré sur ...{o['iban_contrepartie'][-6:]} au lieu de l'IBAN du référentiel ...{ref_iban[-6:]}")
    elif f["ech"] + timedelta(days=TOLERANCE_RETARD) < arrete:
        ligne["statut"] = "Non payée, échue"
        signaler("NON_PAYEE_ECHUE", "Haute", f, None, f"Échéance du {f['echeance']} dépassée de {(arrete - f['ech']).days} jours, aucun paiement trouvé")
    else:
        ligne["statut"] = "Non échue"
    suivi.append(ligne)

payees = [(operations[i], a_rapprocher[j]) for j, i in affectation.items()]
orphelines = []
for i, o in enumerate(operations):
    if i in op_prises:
        continue
    premier = next((p for p, f in payees if f["fournisseur"] == o["fournisseur"] and p["montant_c"] == o["montant_c"] and timedelta(0) < o["date"] - p["date"] <= timedelta(days=45)), None)
    if premier:
        statut = "Paiement en double"
        signaler("PAIEMENT_EN_DOUBLE", "Haute", None, o, f"Même montant déjà réglé le {premier['date_operation']} ({premier['reference_banque']})")
    else:
        statut = "Paiement sans facture"
        signaler("PAIEMENT_SANS_FACTURE", "Haute", None, o, "Aucune facture correspondante dans le dossier")
    orphelines.append(dict(reference_banque=o["reference_banque"], date_operation=o["date_operation"], libelle=o["libelle"], montant=o["montant"], fournisseur=o["fournisseur"] or "", statut=statut))

anomalies.sort(key=lambda a: (a["type"], a["fichier"], a["reference_banque"]))


def ecrire(nom, lignes):
    with open(RESULTATS / nom, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(lignes[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(lignes)


ecrire("rapprochement_factures.csv", suivi)
if orphelines:
    ecrire("operations_non_rapprochees.csv", orphelines)
if anomalies:
    ecrire("anomalies_paiements.csv", anomalies)

sortie = []
p = sortie.append
p(f"Factures à rapprocher : {len(a_rapprocher)} (doublons écartés : {len(doublons)})")
p(f"Opérations bancaires : {len(releve)} dont {len(operations)} paiements fournisseurs ; " + " ; ".join(f"{k} : {v}" for k, v in ignorees.items()))
p(f"Date d'arrêté du relevé : {arrete.isoformat()}")
p("")
statuts = Counter(l["statut"] for l in suivi)
for k, v in sorted(statuts.items()):
    montant = sum(cents(l["total_ttc"]) for l in suivi if l["statut"] == k)
    p(f"  {k:<20}{v:>4} factures" + f"{montant / 100:>16,.2f} €".replace(",", " "))
p("")
p("Méthode de rapprochement : " + " ; ".join(f"{k} = {v}" for k, v in Counter(methodes.values()).most_common()))
retards = [int(l["jours_apres_echeance"]) for l in suivi if l["jours_apres_echeance"] != ""]
p(f"Délai moyen de paiement par rapport à l'échéance : {sum(retards) / len(retards):+.1f} jours ; paiements au-delà de {TOLERANCE_RETARD} jours de retard : {sum(1 for r in retards if r > TOLERANCE_RETARD)}")
p("")
p(f"{'Anomalie de paiement':<34}{'Gravité':<10}{'Nb':>4}{'Montant €':>14}")
for t in sorted({a["type"] for a in anomalies}):
    sel = [a for a in anomalies if a["type"] == t]
    p(f"{t:<34}{sel[0]['gravite']:<10}{len(sel):>4}{sum(float(a['montant']) for a in sel):>14,.2f}".replace(",", " "))

verite_chemin = DATA / "scenario_anomalies.csv"
if verite_chemin.exists():
    correspondance = {"NON_PAYEE_ECHUE": "NON_PAYEE_ECHUE", "ECART_PAIEMENT": "ECART_PAIEMENT", "PAIEMENT_EN_DOUBLE": "PAIEMENT_EN_DOUBLE", "PAIEMENT_SANS_FACTURE": "PAIEMENT_SANS_FACTURE",
                      "IBAN_MODIFIE": "PAIEMENT_IBAN_HORS_REFERENTIEL", "DATE_INCOHERENTE": "PAIEMENT_ANTERIEUR_FACTURE"}
    par_ref = ("PAIEMENT_EN_DOUBLE", "PAIEMENT_SANS_FACTURE")
    verite = [r for r in lire(verite_chemin) if r["type"] in correspondance and not (r["type"] == "DATE_INCOHERENTE" and "postérieure" not in r["detail"])]
    p("")
    p("Contrôle contre le corrigé caché (évaluation uniquement)")
    p(f"{'Type':<34}{'Injectées':>10}{'Trouvées':>10}{'Fausses alertes':>17}")
    ti = tt = tf = 0
    details = []
    for t, d in correspondance.items():
        cle = "reference_banque" if t in par_ref else "fichier"
        v = [r for r in verite if r["type"] == t]
        trouves = {a[cle] for a in anomalies if a["type"] == d}
        attendus = {r[cle] for r in v}
        ok, faux, manque = trouves & attendus, trouves - attendus, attendus - trouves
        p(f"{d:<34}{len(attendus):>10}{len(ok):>10}{len(faux):>17}")
        ti, tt, tf = ti + len(attendus), tt + len(ok), tf + len(faux)
        details += [f"  NON DÉTECTÉE {d} {m}" for m in manque] + [f"  FAUSSE ALERTE {d} {x}" for x in faux]
    p(f"{'Total':<34}{ti:>10}{tt:>10}{tf:>17}")
    sortie += details

texte = "\n".join(sortie)
(RESULTATS / "rapprochement.txt").write_text(texte, encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")
print(texte)
