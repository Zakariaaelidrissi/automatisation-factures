import csv
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
RESULTATS = BASE / "resultats"

BLOQUANTES = {"DOUBLON_EXACT", "DOUBLON_RENUMEROTE", "ERREUR_TOTAL", "TAUX_TVA_ANORMAL", "ERREUR_CALCUL_TVA", "IBAN_MODIFIE", "IBAN_INVALIDE", "FACTURE_HORS_EXERCICE", "PAIEMENT_IBAN_HORS_REFERENTIEL"}
ACTIONS = {
    "DOUBLON_EXACT": "Ne pas comptabiliser ni payer ; demander l'avoir ou la confirmation au fournisseur",
    "DOUBLON_RENUMEROTE": "Ne pas comptabiliser ni payer ; vérifier auprès du fournisseur qu'il s'agit de la même prestation",
    "ERREUR_TOTAL": "Suspendre ; demander une facture rectificative",
    "TAUX_TVA_ANORMAL": "Suspendre ; vérifier le taux applicable et demander une facture rectificative",
    "ERREUR_CALCUL_TVA": "Suspendre ; demander une facture rectificative",
    "IBAN_MODIFIE": "Ne pas payer ; rappeler le fournisseur sur un numéro connu (risque de fraude au changement de RIB)",
    "IBAN_INVALIDE": "Ne pas payer ; faire confirmer les coordonnées bancaires",
    "FACTURE_HORS_EXERCICE": "Vérifier le rattachement à l'exercice ; provision ou charge à répartir",
    "SIREN_INVALIDE": "Faire corriger la mention légale ; vérifier l'identité du fournisseur",
    "TVA_INTRA_INCOHERENT": "Faire corriger le n° de TVA ; la TVA déductible est conditionnée à une mention valide",
    "DATE_INCOHERENTE": "Contrôler les dates auprès du fournisseur",
    "PAIEMENT_ANTERIEUR_FACTURE": "Contrôler les dates auprès du fournisseur",
    "ECART_PAIEMENT": "Régulariser auprès du fournisseur (complément, avoir ou remboursement)",
    "NON_PAYEE_ECHUE": "Relancer le circuit de validation et planifier le paiement",
    "PAIEMENT_EN_DOUBLE": "Demander le remboursement ou imputer sur la prochaine facture",
    "PAIEMENT_SANS_FACTURE": "Rechercher la facture manquante ; en attendant, compte d'attente",
    "PAIEMENT_IBAN_HORS_REFERENTIEL": "Alerter la trésorerie ; tenter le rappel du virement auprès de la banque",
}
GRAVITE_ORDRE = {"Haute": 0, "Moyenne": 1}


def lire(chemin):
    with open(chemin, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


def d(s):
    return date.fromisoformat(s) if s else None


factures = {f["fichier"]: f for f in lire(DATA / "factures_extraites.csv")}
fournisseurs = lire(DATA / "fournisseurs.csv")
aux = {r["nom"]: f"401{i:05d}" for i, r in enumerate(fournisseurs, start=1)}
charge = {r["nom"]: r["compte_charge"] for r in fournisseurs}
suivi = lire(RESULTATS / "rapprochement_factures.csv")
orphelines = lire(RESULTATS / "operations_non_rapprochees.csv")

brut = []
for a in lire(RESULTATS / "anomalies_factures.csv"):
    brut.append(dict(type=a["type"], gravite=a["gravite"], fichier=a["fichier"], fichier_lie=a["fichier_lie"], numero=a["numero"], fournisseur=a["fournisseur"], reference_banque="",
                     montant=float(a["total_ttc"]), detail=a["detail"]))
for a in lire(RESULTATS / "anomalies_paiements.csv"):
    brut.append(dict(type=a["type"], gravite=a["gravite"], fichier=a["fichier"], fichier_lie="", numero=a["numero"], fournisseur=a["fournisseur"], reference_banque=a["reference_banque"],
                     montant=float(a["montant"]), detail=a["detail"]))

doublon_paiement = {(a["fichier"], "IBAN") for a in brut if a["type"] == "PAIEMENT_IBAN_HORS_REFERENTIEL"} | {(a["fichier"], "DATE") for a in brut if a["type"] == "PAIEMENT_ANTERIEUR_FACTURE"}
anomalies = [a for a in brut if not ((a["type"] == "IBAN_MODIFIE" and (a["fichier"], "IBAN") in doublon_paiement) or (a["type"] == "DATE_INCOHERENTE" and (a["fichier"], "DATE") in doublon_paiement))]
anomalies.sort(key=lambda a: (GRAVITE_ORDRE[a["gravite"]], a["type"], a["fichier"], a["reference_banque"]))
bloquees = {a["fichier"] for a in anomalies if a["type"] in BLOQUANTES and a["fichier"]}

ecritures = []
for f in sorted(factures.values(), key=lambda x: (x["date_facture"], x["fichier"])):
    if f["fichier"] in bloquees:
        continue
    ht, tva, ttc = float(f["total_ht"]), float(f["montant_tva"]), float(f["total_ttc"])
    base = dict(journal="ACH", date=d(f["date_facture"]), piece=f["numero"], lib=f"{f['fournisseur']} - {f['numero']}")
    ecritures.append(dict(base, compte=charge[f["fournisseur"]], debit=ht, credit=0.0))
    if tva:
        ecritures.append(dict(base, compte="44566000", debit=tva, credit=0.0))
    ecritures.append(dict(base, compte=aux[f["fournisseur"]], debit=0.0, credit=ttc))
nb_achats = len(ecritures)
for s in sorted((x for x in suivi if x["reference_banque"]), key=lambda x: (x["date_paiement"], x["fichier"])):
    m = float(s["montant_paye"])
    base = dict(journal="BQ", date=d(s["date_paiement"]), piece=s["reference_banque"], lib=f"Règlement {s['fournisseur']} - {s['numero']}")
    ecritures.append(dict(base, compte=aux[s["fournisseur"]], debit=m, credit=0.0))
    ecritures.append(dict(base, compte="51200000", debit=0.0, credit=m))
for o in sorted(orphelines, key=lambda x: (x["date_operation"], x["reference_banque"])):
    m = -float(o["montant"])
    en_double = o["statut"] == "Paiement en double"
    compte = aux[o["fournisseur"]] if en_double and o["fournisseur"] in aux else "47100000"
    base = dict(journal="BQ", date=d(o["date_operation"]), piece=o["reference_banque"], lib=f"{o['statut']} - {o['fournisseur']}")
    ecritures.append(dict(base, compte=compte, debit=m, credit=0.0))
    ecritures.append(dict(base, compte="51200000", debit=0.0, credit=m))

with open(RESULTATS / "ecritures_comptables.csv", "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.writer(fh, delimiter=";")
    w.writerow(["journal", "date", "piece", "compte", "libelle", "debit", "credit"])
    for e in ecritures:
        w.writerow([e["journal"], e["date"].isoformat(), e["piece"], e["compte"], e["lib"], f"{e['debit']:.2f}".replace(".", ","), f"{e['credit']:.2f}".replace(".", ",")])

POLICE = "Arial"
bleu = PatternFill("solid", fgColor="1F3864")
gris = PatternFill("solid", fgColor="EEF1F6")
rouge = PatternFill("solid", fgColor="F8D7D7")
ambre = PatternFill("solid", fgColor="FBEBC8")
fin = Side(style="thin", color="C9CED8")
cadre = Border(top=fin, bottom=fin, left=fin, right=fin)
EURO = '#,##0.00;-#,##0.00;"-"'

wb = Workbook()


def feuille(nom, colonnes, lignes, largeurs, formats=None, premiere=False):
    ws = wb.active if premiere else wb.create_sheet()
    ws.title = nom
    for j, c in enumerate(colonnes, start=1):
        cell = ws.cell(row=1, column=j, value=c)
        cell.font = Font(name=POLICE, bold=True, color="FFFFFF", size=10)
        cell.fill = bleu
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for i, ligne in enumerate(lignes, start=2):
        for j, v in enumerate(ligne, start=1):
            cell = ws.cell(row=i, column=j, value=v)
            cell.font = Font(name=POLICE, size=10)
            cell.border = cadre
            if formats and formats.get(j):
                cell.number_format = formats[j]
    for j, w_ in enumerate(largeurs, start=1):
        ws.column_dimensions[get_column_letter(j)].width = w_
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(colonnes))}{max(len(lignes) + 1, 2)}"
    ws.row_dimensions[1].height = 28
    return ws


synthese = feuille("Synthèse", ["x"], [], [44, 16, 18, 14], premiere=True)

lignes_an = [[a["type"], a["gravite"], "Oui" if a["fichier"] in bloquees else "Non", a["fichier"] or a["reference_banque"], a["numero"], a["fournisseur"], a["montant"], a["detail"], ACTIONS[a["type"]]] for a in anomalies]
ws_an = feuille("Anomalies", ["Type", "Gravité", "Facture bloquée en compta", "Pièce (PDF ou réf. banque)", "N° facture", "Fournisseur", "Montant € (TTC ou virement)", "Constat", "Action recommandée"],
                lignes_an, [30, 10, 14, 24, 16, 34, 16, 70, 80], {7: EURO})
for i, a in enumerate(anomalies, start=2):
    ws_an.cell(row=i, column=2).fill = rouge if a["gravite"] == "Haute" else ambre
    for j in (8, 9):
        ws_an.cell(row=i, column=j).alignment = Alignment(wrap_text=True, vertical="top")

lignes_su = [[s["fichier"], s["fournisseur"], s["numero"], d(s["date_facture"]), d(s["echeance"]), float(s["total_ttc"]), s["statut"], s["methode"], s["reference_banque"], d(s["date_paiement"]),
              float(s["montant_paye"]) if s["montant_paye"] else None, float(s["ecart"]) if s["ecart"] else None, int(s["jours_apres_echeance"]) if s["jours_apres_echeance"] != "" else None] for s in suivi]
ws_su = feuille("Rapprochement", ["PDF", "Fournisseur", "N° facture", "Date facture", "Échéance", "TTC €", "Statut", "Méthode", "Réf. banque", "Date paiement", "Payé €", "Écart €", "Jours après échéance"],
                lignes_su, [14, 34, 16, 12, 12, 14, 18, 26, 18, 12, 14, 12, 12], {4: "dd/mm/yyyy", 5: "dd/mm/yyyy", 6: EURO, 10: "dd/mm/yyyy", 11: EURO, 12: EURO})

colonnes_ec = ["Journal", "Date", "Pièce", "Compte", "Libellé", "Débit €", "Crédit €"]
formats_ec = {2: "dd/mm/yyyy", 6: EURO, 7: EURO}
larg_ec = [9, 12, 20, 12, 70, 15, 15]
ws_ach = feuille("Écritures achats", colonnes_ec, [[e["journal"], e["date"], e["piece"], e["compte"], e["lib"], e["debit"], e["credit"]] for e in ecritures[:nb_achats]], larg_ec, formats_ec)
ws_bq = feuille("Écritures banque", colonnes_ec, [[e["journal"], e["date"], e["piece"], e["compte"], e["lib"], e["debit"], e["credit"]] for e in ecritures[nb_achats:]], larg_ec, formats_ec)
n_ach, n_bq, n_an, n_su = nb_achats + 1, len(ecritures) - nb_achats + 1, len(anomalies) + 1, len(suivi) + 1

soldes = [[r["nom"], aux[r["nom"]]] for r in fournisseurs]
ws_so = feuille("Soldes fournisseurs", ["Fournisseur", "Compte", "Factures comptabilisées €", "Règlements €", "Solde créditeur €"], soldes, [38, 12, 24, 18, 18], {3: EURO, 4: EURO, 5: EURO})
for i in range(2, len(soldes) + 2):
    ws_so.cell(row=i, column=3, value=f"=SUMIFS('Écritures achats'!$G$2:$G${n_ach},'Écritures achats'!$D$2:$D${n_ach},B{i})")
    ws_so.cell(row=i, column=4, value=f"=SUMIFS('Écritures banque'!$F$2:$F${n_bq},'Écritures banque'!$D$2:$D${n_bq},B{i})")
    ws_so.cell(row=i, column=5, value=f"=C{i}-D{i}")
    for j in (3, 4, 5):
        c = ws_so.cell(row=i, column=j)
        c.number_format, c.font, c.border = EURO, Font(name=POLICE, size=10), cadre
fin_so = len(soldes) + 2
ws_so.cell(row=fin_so, column=1, value="Total").font = Font(name=POLICE, bold=True, size=10)
for j, col in ((3, "C"), (4, "D"), (5, "E")):
    c = ws_so.cell(row=fin_so, column=j, value=f"=SUM({col}2:{col}{fin_so - 1})")
    c.number_format, c.font = EURO, Font(name=POLICE, bold=True, size=10)

ws = synthese
ws.delete_rows(1, 1)
ws.auto_filter.ref = None
ws.freeze_panes = None
ws.column_dimensions["A"].width = 46
for col, w_ in zip("BCD", (16, 20, 14)):
    ws.column_dimensions[col].width = w_
titre = ws.cell(row=1, column=1, value="Factures fournisseurs - Biscuiterie Ker Avel SAS (données fictives)")
titre.font = Font(name=POLICE, bold=True, size=13, color="1F3864")
ws.cell(row=2, column=1, value="Période : 1er janvier au 31 octobre 2026. Les chiffres ci-dessous sont des formules reliées aux autres onglets.").font = Font(name=POLICE, italic=True, size=9, color="555555")


def ligne(i, label, formule, fmt=None, gras=False):
    a = ws.cell(row=i, column=1, value=label)
    b = ws.cell(row=i, column=2, value=formule)
    a.font = Font(name=POLICE, size=10, bold=gras)
    b.font = Font(name=POLICE, size=10, bold=gras)
    a.border = b.border = cadre
    if fmt:
        b.number_format = fmt


def entete(i, textes):
    for j, t in enumerate(textes, start=1):
        c = ws.cell(row=i, column=j, value=t)
        c.font = Font(name=POLICE, bold=True, color="FFFFFF", size=10)
        c.fill = bleu


R = f"Rapprochement!$G$2:$G${n_su}"
entete(4, ["Volumes", "Valeur"])
ligne(5, "Factures PDF lues", f"=COUNTA(Rapprochement!$A$2:$A${n_su})+{len(factures) - len(suivi)}", "0")
ligne(6, "Factures rapprochées d'un paiement (écarts compris)", f'=COUNTIF({R},"Rapprochée")+COUNTIF({R},"Écart de paiement")', "0")
ligne(7, "Factures non échues", f'=COUNTIF({R},"Non échue")', "0")
ligne(8, "Factures comptabilisées (journal d'achats)", f"=COUNTA('Écritures achats'!$A$2:$A${n_ach})/3", "0")
ligne(9, "Factures bloquées en comptabilité", f'=COUNTIF(Anomalies!$C$2:$C${n_an},"Oui")', "0")
ligne(10, "Anomalies relevées", f"=COUNTA(Anomalies!$A$2:$A${n_an})", "0", True)
ligne(11, "dont gravité haute", f'=COUNTIF(Anomalies!$B$2:$B${n_an},"Haute")', "0")
ligne(12, "dont gravité moyenne", f'=COUNTIF(Anomalies!$B$2:$B${n_an},"Moyenne")', "0")
entete(14, ["Contrôles d'équilibre", "Valeur"])
ligne(15, "Journal d'achats : débit - crédit", f"=ROUND(SUM('Écritures achats'!$F$2:$F${n_ach})-SUM('Écritures achats'!$G$2:$G${n_ach}),2)", EURO)
ligne(16, "Journal de banque : débit - crédit", f"=ROUND(SUM('Écritures banque'!$F$2:$F${n_bq})-SUM('Écritures banque'!$G$2:$G${n_bq}),2)", EURO)
entete(18, ["Anomalies par type", "Nombre", "Montant concerné €", "Gravité"])
types = sorted({a["type"] for a in anomalies}, key=lambda t: (GRAVITE_ORDRE[next(a["gravite"] for a in anomalies if a["type"] == t)], t))
for k, t in enumerate(types, start=19):
    ws.cell(row=k, column=1, value=t)
    ws.cell(row=k, column=2, value=f"=COUNTIF(Anomalies!$A$2:$A${n_an},A{k})")
    ws.cell(row=k, column=3, value=f"=SUMIF(Anomalies!$A$2:$A${n_an},A{k},Anomalies!$G$2:$G${n_an})").number_format = EURO
    ws.cell(row=k, column=4, value=next(a["gravite"] for a in anomalies if a["type"] == t))
    for j in range(1, 5):
        ws.cell(row=k, column=j).font = Font(name=POLICE, size=10)
        ws.cell(row=k, column=j).border = cadre
ws.sheet_view.showGridLines = False
wb.save(RESULTATS / "rapport_factures.xlsx")

couleurs = {"Haute": "#b3402a", "Moyenne": "#d9a03f"}
compte = Counter(a["type"] for a in anomalies)
ordre = sorted(types, key=lambda t: compte[t])
fig, ax = plt.subplots(figsize=(9, 5.2))
barres = ax.barh(ordre, [compte[t] for t in ordre], color=[couleurs[next(a["gravite"] for a in anomalies if a["type"] == t)] for t in ordre], height=0.62)
for b in barres:
    ax.text(b.get_width() + 0.06, b.get_y() + b.get_height() / 2, f"{int(b.get_width())}", va="center", fontsize=10)
ax.set_xlim(0, max(compte.values()) + 1)
ax.set_title("Anomalies détectées par type", loc="left", fontsize=13, fontweight="bold")
ax.spines[["top", "right"]].set_visible(False)
ax.tick_params(axis="x", labelsize=9)
ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=c) for c in couleurs.values()], labels=[f"Gravité {k.lower()}" for k in couleurs], loc="lower right", frameon=False)
fig.tight_layout()
fig.savefig(RESULTATS / "anomalies_par_type.png", dpi=150)
plt.close(fig)

correspondance = {"DATE_INCOHERENTE": {"DATE_INCOHERENTE", "PAIEMENT_ANTERIEUR_FACTURE"}, "IBAN_MODIFIE": {"IBAN_MODIFIE", "PAIEMENT_IBAN_HORS_REFERENTIEL"}}
sortie = []
p = sortie.append
total_ttc = sum(float(f["total_ttc"]) for f in factures.values())
p(f"Factures lues : {len(factures)} pour {total_ttc:,.2f} € TTC".replace(",", " "))
p(f"Factures comptabilisées : {len({e['piece'] for e in ecritures[:nb_achats]})} ; bloquées : {len(bloquees)}")
p(f"Écritures : {nb_achats} lignes au journal d'achats, {len(ecritures) - nb_achats} lignes au journal de banque")
p(f"Équilibre : débit achats {sum(e['debit'] for e in ecritures[:nb_achats]):,.2f} / crédit {sum(e['credit'] for e in ecritures[:nb_achats]):,.2f} ; "
  f"débit banque {sum(e['debit'] for e in ecritures[nb_achats:]):,.2f} / crédit {sum(e['credit'] for e in ecritures[nb_achats:]):,.2f}".replace(",", " "))
p(f"Anomalies : {len(anomalies)} (haute : {sum(1 for a in anomalies if a['gravite'] == 'Haute')}, moyenne : {sum(1 for a in anomalies if a['gravite'] == 'Moyenne')})")
for t in types:
    sel = [a for a in anomalies if a["type"] == t]
    p(f"  {t:<34}{len(sel):>3}{sum(a['montant'] for a in sel):>14,.2f} €".replace(",", " "))

verite_chemin = DATA / "scenario_anomalies.csv"
if verite_chemin.exists():
    verite = lire(verite_chemin)
    trouvees, manquees = 0, []
    for r in verite:
        familles = correspondance.get(r["type"], {r["type"]})
        ok = any(a["type"] in familles and ((r["reference_banque"] and a["reference_banque"] == r["reference_banque"]) or (not r["reference_banque"] and r["fichier"] in (a["fichier"], a["fichier_lie"])))
                 or (a["type"] in familles and r["reference_banque"] == "" and a["reference_banque"] == "" and r["fichier"] == a["fichier"]) for a in brut)
        trouvees += ok
        if not ok:
            manquees.append(r)
    faux = [a for a in anomalies if not any(a["type"] in correspondance.get(r["type"], {r["type"]}) and (a["reference_banque"] == r["reference_banque"] if r["reference_banque"] else r["fichier"] in (a["fichier"], a["fichier_lie"])) for r in verite)]
    p("")
    p(f"Contrôle contre le corrigé caché : {trouvees} anomalies retrouvées sur {len(verite)} injectées ; {len(faux)} fausse(s) alerte(s)")
    for r in manquees:
        p(f"  NON DÉTECTÉE {r['type']} {r['fichier'] or r['reference_banque']}")
    for a in faux:
        p(f"  FAUSSE ALERTE {a['type']} {a['fichier'] or a['reference_banque']}")

texte = "\n".join(sortie)
(RESULTATS / "rapport.txt").write_text(texte, encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")
print(texte)
