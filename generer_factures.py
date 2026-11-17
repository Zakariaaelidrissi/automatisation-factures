import calendar
import csv
import random
import unicodedata
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

SEED = 2026
BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
FACTURES = DATA / "factures"
DEBUT, FIN = date(2026, 1, 1), date(2026, 10, 31)
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]

rng = random.Random(SEED)


def luhn_ok(s):
    total = 0
    for i, ch in enumerate(reversed(s)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            d -= 9 if d > 9 else 0
        total += d
    return total % 10 == 0


def nouveau_siren():
    base = f"{rng.randint(30_000_000, 98_999_999)}"
    return next(base + str(c) for c in range(10) if luhn_ok(base + str(c)))


def cle_tva(siren):
    return f"{(12 + 3 * (int(siren) % 97)) % 97:02d}"


def nouvel_iban():
    banque = rng.choice(["30004", "30003", "20041", "10278", "12548", "11315", "18206"])
    guichet = f"{rng.randint(0, 99999):05d}"
    compte = f"{rng.randint(0, 99_999_999_999):011d}"
    cle = 97 - ((89 * int(banque) + 15 * int(guichet) + 3 * int(compte)) % 97)
    bban = f"{banque}{guichet}{compte}{cle:02d}"
    controle = 98 - (int(bban + "152700") % 97)
    return f"FR{controle:02d}{bban}"


def groupes(s, n=4):
    return " ".join(s[i:i + n] for i in range(0, len(s), n))


def sans_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def jour_ouvre(d, sens=1):
    while d.weekday() >= 5:
        d += timedelta(days=sens)
    return d


def fin_de_mois(d):
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def fmt_a(c):
    return f"{c / 100:,.2f}".replace(",", " ").replace(".", ",")


def fmt_b(c):
    return f"{c / 100:.2f}"


def fmt_c(c):
    return f"{c / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def d_a(d):
    return d.strftime("%d/%m/%Y")


def d_b(d):
    return f"{d.day} {MOIS[d.month - 1]} {d.year}"


def d_c(d):
    return d.strftime("%d.%m.%Y")


CLIENT = {"nom": "Biscuiterie Ker Avel SAS", "adresse1": "ZA du Moulin Neuf", "adresse2": "29000 Quimper", "siren": nouveau_siren()}

FOURNISSEURS = [
    dict(nom="Laiterie du Trégor SARL", rue="14 route de Lannion", ville="22300 Ploumilliau", compte="601100", tva=550, layout="A", par_mois=4, delai=30, fin_mois=False, mode="VIR",
         fmt="F2026-{n:04d}", produits=[("Beurre doux 82 % en plaque de 25 kg", "kg", 6.10, 8.40, 600, 2400), ("Beurre pâtissier tourage 84 %", "kg", 7.20, 9.10, 300, 1200), ("Crème UHT 35 %", "L", 3.10, 4.20, 200, 900)]),
    dict(nom="Minoterie Kerdreux SAS", rue="3 chemin du Moulin", ville="29270 Carhaix-Plouguer", compte="601200", tva=550, layout="A", par_mois=3, delai=30, fin_mois=False, mode="VIR",
         fmt="FA-26-{n:05d}", produits=[("Farine de blé T55 en sac de 25 kg", "kg", 0.62, 0.88, 6000, 20000), ("Farine de blé T45 en sac de 25 kg", "kg", 0.70, 0.95, 3000, 9000)]),
    dict(nom="Sucreries de l'Ouest SA", rue="Zone industrielle de la Gare", ville="44110 Châteaubriant", compte="601300", tva=550, layout="B", par_mois=2, delai=45, fin_mois=True, mode="VIR",
         fmt="{n:05d}/2026", produits=[("Sucre blanc cristallisé", "kg", 0.78, 1.04, 5000, 12000), ("Sucre glace", "kg", 0.95, 1.25, 1500, 4000)]),
    dict(nom="Cacaoteries Duval SAS", rue="27 quai des Chargeurs", ville="35400 Saint-Malo", compte="601400", tva=550, layout="B", par_mois=2, delai=60, fin_mois=False, mode="VIR",
         fmt="CD{n:06d}", produits=[("Poudre de cacao 22-24 %", "kg", 4.80, 9.20, 400, 1200), ("Pépites de chocolat noir 52 %", "kg", 6.90, 10.40, 300, 900)]),
    dict(nom="Ovoproduits Bretons SARL", rue="Kerhuel", ville="56300 Pontivy", compte="601500", tva=550, layout="C", par_mois=2, delai=30, fin_mois=False, mode="VIR",
         fmt="2026-{n:03d}", produits=[("Œufs entiers liquides pasteurisés", "kg", 1.85, 2.60, 800, 2400)]),
    dict(nom="Cartonnages Le Gall SAS", rue="8 rue de l'Industrie", ville="29800 Landerneau", compte="602600", tva=2000, layout="A", par_mois=2, delai=45, fin_mois=True, mode="VIR",
         fmt="FC{n:05d}", produits=[("Étuis carton 12 sachets, impression 4 couleurs", "u", 0.21, 0.34, 8000, 20000), ("Cartons d'expédition 40 x 30 x 20", "u", 0.55, 0.78, 3000, 7000)]),
    dict(nom="Plastiques Armor SARL", rue="Parc d'activités de Kerlann", ville="22190 Plérin", compte="602610", tva=2000, layout="C", par_mois=1, delai=30, fin_mois=False, mode="VIR",
         fmt="PA/{n:04d}", produits=[("Film polypropylène alimentaire, bobine 600 mm", "kg", 3.40, 4.10, 400, 900)]),
    dict(nom="Énergie Océane SA", rue="1 esplanade de la Mer", ville="44000 Nantes", compte="606100", tva=2000, layout="B", par_mois=1, delai=30, fin_mois=False, mode="PRLV",
         fmt="EO{n:07d}", produits=[("Électricité {mois} 2026, consommation et acheminement", "forfait", 9200, 14400, 1, 1)]),
    dict(nom="Transports Penhoët SARL", rue="5 rue du Port", ville="29200 Brest", compte="624100", tva=2000, layout="C", par_mois=4, delai=30, fin_mois=False, mode="VIR",
         fmt="T{n:05d}", produits=[("Transport palettes, tournée Bretagne-Île-de-France", "forfait", 650, 1400, 1, 2), ("Transport palettes, export Benelux", "forfait", 1500, 2600, 1, 1)]),
    dict(nom="Maintenance Industrielle Kervella SAS", rue="12 rue Jean Monnet", ville="29000 Quimper", compte="615500", tva=2000, layout="A", par_mois=1, delai=30, fin_mois=False, mode="VIR",
         fmt="MIK-{n:04d}", produits=[("Intervention de maintenance four tunnel", "h", 68, 82, 6, 40), ("Pièces détachées four et ensacheuse", "lot", 150, 1800, 1, 3)]),
    dict(nom="Cabinet Lemaire Conseil SARL", rue="9 place de la Liberté", ville="29000 Quimper", compte="622600", tva=2000, layout="C", par_mois=1, delai=30, fin_mois=False, mode="VIR",
         fmt="LC-{n:04d}", produits=[("Honoraires de tenue comptable et paie, {mois} 2026", "forfait", 1850, 1850, 1, 1)]),
    dict(nom="SCI Les Hortensias", rue="2 rue des Hortensias", ville="29000 Quimper", compte="613200", tva=2000, layout="C", par_mois=1, delai=0, fin_mois=False, mode="PRLV",
         fmt="L26-{n:03d}", produits=[("Loyer commercial entrepôt, {mois} 2026", "forfait", 7500, 7500, 1, 1)]),
    dict(nom="Télécom Bretagne Pro SA", rue="30 avenue de Keradennec", ville="29000 Quimper", compte="626000", tva=2000, layout="B", par_mois=1, delai=15, fin_mois=False, mode="PRLV",
         fmt="TBP{n:08d}", produits=[("Abonnements téléphonie et fibre, {mois} 2026", "forfait", 540, 690, 1, 1)]),
    dict(nom="Propreté Services Ouest SARL", rue="6 rue des Artisans", ville="29000 Quimper", compte="615600", tva=2000, layout="A", par_mois=1, delai=30, fin_mois=False, mode="VIR",
         fmt="PSO{n:05d}", produits=[("Nettoyage des locaux de production, {mois} 2026", "forfait", 2150, 2350, 1, 1)]),
]
for f in FOURNISSEURS:
    f["siren"] = nouveau_siren()
    f["tva_intra"] = f"FR{cle_tva(f['siren'])}{f['siren']}"
    f["iban"] = nouvel_iban()
    f["couleur"] = rng.choice([colors.HexColor("#1f4e79"), colors.HexColor("#7a2e2e"), colors.HexColor("#2e6b4f"), colors.HexColor("#4a3b7a")])
PAR_NOM = {f["nom"]: f for f in FOURNISSEURS}


def calcul(lignes, taux):
    ht = sum(l["total"] for l in lignes)
    tva = round(ht * taux / 10000)
    return ht, tva, ht + tva


def construire_lignes(f, mois):
    k = 1 if len(f["produits"]) == 1 else rng.randint(1, min(3, len(f["produits"])))
    lignes = []
    for desig, unite, pmin, pmax, qmin, qmax in rng.sample(f["produits"], k):
        pu = round(rng.uniform(pmin, pmax), 2)
        q = rng.randint(qmin, qmax) if qmax > qmin else qmin
        if unite in ("kg", "L", "u") and q > 100:
            q = round(q, -1)
        lignes.append({"designation": desig.format(mois=MOIS[mois - 1]), "unite": unite, "qte": q, "pu": round(pu * 100), "total": round(q * pu * 100)})
    return lignes


def jours_de_facturation(f, mois):
    nb = f["par_mois"]
    dernier = calendar.monthrange(2026, mois)[1]
    if f["fmt"].startswith("L26"):
        jours = [1]
    elif f["compte"] == "622600":
        jours = [rng.randint(24, 28)]
    elif f["compte"] == "606100":
        jours = [rng.randint(8, 12)]
    else:
        jours = sorted(rng.sample(range(2, dernier - 1), nb))
    return [jour_ouvre(date(2026, mois, j)) for j in jours]


factures = []
for f in FOURNISSEURS:
    n = rng.randint(100, 900)
    for mois in range(1, 11):
        for d in jours_de_facturation(f, mois):
            n += rng.randint(1, 4)
            lignes = construire_lignes(f, mois)
            ht, tva, ttc = calcul(lignes, f["tva"])
            if f["fin_mois"]:
                ech = fin_de_mois(d + timedelta(days=45))
            else:
                ech = d + timedelta(days=f["delai"])
            factures.append(dict(fournisseur=f["nom"], numero=f["fmt"].format(n=n), date=d, echeance=ech, lignes=lignes, taux=f["tva"], ht=ht, tva=tva, ttc=ttc,
                                 siren=f["siren"], tva_intra=f["tva_intra"], iban=f["iban"], payee=False, paiements=[], anomalies=[]))


def date_paiement(fa):
    f = PAR_NOM[fa["fournisseur"]]
    if f["mode"] == "PRLV":
        return jour_ouvre(fa["echeance"])
    return jour_ouvre(fa["echeance"] + timedelta(days=rng.randint(-4, 5)))


def libelle_paiement(fa):
    f = PAR_NOM[fa["fournisseur"]]
    nom = sans_accents(f["nom"]).upper()[:26]
    if f["mode"] == "PRLV":
        return f"PRLV SEPA {nom} {fa['numero']}"
    tirage = rng.random()
    if tirage < 0.55:
        return f"VIR SEPA {nom} {fa['numero']}"
    if tirage < 0.75:
        return f"VIR SEPA {nom} FACT {fa['numero']}"
    return f"VIR SEPA {nom}"


for fa in factures:
    dp = date_paiement(fa)
    if dp <= FIN:
        fa["paiements"].append(dict(date=dp, montant=fa["ttc"], libelle=libelle_paiement(fa), iban=fa["iban"]))

utilises = set()
anomalies = []
releve_extra = []


def choisir(n, condition):
    candidats = [fa for fa in factures if id(fa) not in utilises and condition(fa)]
    tires = rng.sample(candidats, n)
    utilises.update(id(t) for t in tires)
    return tires


def noter(type_, fa=None, detail="", ligne=None):
    anomalies.append(dict(type=type_, fa=fa, ligne=ligne, detail=detail))


payee = lambda fa: bool(fa["paiements"]) and date(2026, 2, 1) <= fa["date"] <= date(2026, 8, 31)
marchandises = lambda fa: payee(fa) and fa["taux"] == 550
services = lambda fa: payee(fa) and fa["taux"] == 2000 and PAR_NOM[fa["fournisseur"]]["mode"] == "VIR"

copies = []
for i, fa in enumerate(choisir(4, lambda x: payee(x) and PAR_NOM[x["fournisseur"]]["mode"] == "VIR")):
    c = dict(fa, paiements=[], anomalies=[], copie=True)
    copies.append(c)
    noter("DOUBLON_EXACT", c, f"Même facture {fa['numero']} reçue une seconde fois")
    if i < 2:
        p = fa["paiements"][0]
        p2 = dict(p, date=jour_ouvre(p["date"] + timedelta(days=rng.randint(5, 12))))
        fa["paiements"].append(p2)
        noter("PAIEMENT_EN_DOUBLE", fa, f"Facture {fa['numero']} payée deux fois ({p['montant'] / 100:.2f} EUR)", ligne=p2)
for fa in choisir(2, services):
    c = dict(fa, paiements=[], anomalies=[], copie=True, numero=fa["numero"] + "-B")
    copies.append(c)
    noter("DOUBLON_RENUMEROTE", c, f"Facture {fa['numero']} ré-émise sous le numéro {c['numero']}, mêmes date et montants")
for fa in choisir(3, payee):
    delta = rng.choice([-1, 1]) * rng.randint(1250, 18000)
    fa["ttc"] += delta
    fa["paiements"][0]["montant"] = fa["ttc"]
    noter("ERREUR_TOTAL", fa, f"TTC imprimé {fa['ttc'] / 100:.2f} au lieu de {(fa['ht'] + fa['tva']) / 100:.2f}")
for fa, nouveau in zip(choisir(2, marchandises) + choisir(1, services), [2000, 2000, 1000]):
    ancien = fa["taux"]
    fa["taux"] = nouveau
    fa["tva"] = round(fa["ht"] * nouveau / 10000)
    fa["ttc"] = fa["ht"] + fa["tva"]
    fa["paiements"][0]["montant"] = fa["ttc"]
    noter("TAUX_TVA_ANORMAL", fa, f"Taux de {nouveau / 100:g} % appliqué au lieu de {ancien / 100:g} %")
for fa in choisir(2, payee):
    bon = fa["siren"]
    fa["siren"] = bon[:-1] + str((int(bon[-1]) + rng.randint(1, 9)) % 10)
    noter("SIREN_INVALIDE", fa, f"SIREN imprimé {fa['siren']} au lieu de {bon}")
for fa in choisir(1, payee):
    fa["tva_intra"] = f"FR{(int(cle_tva(fa['siren'])) + 7) % 100:02d}{fa['siren']}"
    noter("TVA_INTRA_INCOHERENT", fa, "Clé du numéro de TVA intracommunautaire erronée")
for fa in choisir(2, lambda x: payee(x) and PAR_NOM[x["fournisseur"]]["mode"] == "VIR"):
    nouvel = nouvel_iban()
    fa["iban"] = nouvel
    fa["paiements"][0]["iban"] = nouvel
    noter("IBAN_MODIFIE", fa, "IBAN de la facture différent du RIB habituel du fournisseur, paiement effectué sur ce nouvel IBAN")
for fa in choisir(6, lambda x: bool(x["paiements"]) and x["date"] <= date(2026, 7, 31) and PAR_NOM[x["fournisseur"]]["mode"] == "VIR"):
    fa["paiements"] = []
    noter("NON_PAYEE_ECHUE", fa, f"Échéance du {fa['echeance'].isoformat()} dépassée, aucun paiement")
for fa, mode in zip(choisir(3, payee), ["ht", "escompte", "transposition"]):
    p = fa["paiements"][0]
    if mode == "ht":
        p["montant"] = fa["ht"]
        detail = "Paiement du montant HT au lieu du TTC"
    elif mode == "escompte":
        p["montant"] = round(fa["ttc"] * 0.98)
        detail = "Paiement avec un escompte de 2 % non prévu"
    else:
        chiffres = f"{fa['ttc']}"
        p["montant"] = int(chiffres[:-3] + chiffres[-2] + chiffres[-3] + chiffres[-1]) if chiffres[-2] != chiffres[-3] else fa["ttc"] + 900
        detail = "Montant payé avec deux chiffres inversés"
    noter("ECART_PAIEMENT", fa, f"{detail} ({p['montant'] / 100:.2f} EUR payés pour {fa['ttc'] / 100:.2f} EUR)")
a, b = choisir(2, lambda x: payee(x) and PAR_NOM[x["fournisseur"]]["mode"] == "VIR")
a["date"] = jour_ouvre(a["paiements"][0]["date"] + timedelta(days=6))
noter("DATE_INCOHERENTE", a, "Date de facture postérieure à la date de paiement")
b["echeance"] = b["date"] - timedelta(days=12)
noter("DATE_INCOHERENTE", b, "Échéance antérieure à la date de facture")
extras = []
for f in rng.sample([x for x in FOURNISSEURS if x["tva"] == 550 and x["mode"] == "VIR"], 2):
    d = jour_ouvre(date(2025, 12, rng.randint(8, 19)))
    lignes = construire_lignes(f, 12)
    ht, tva, ttc = calcul(lignes, f["tva"])
    fa = dict(fournisseur=f["nom"], numero=f["fmt"].format(n=rng.randint(50, 99)), date=d, echeance=d + timedelta(days=f["delai"]), lignes=lignes, taux=f["tva"], ht=ht, tva=tva, ttc=ttc,
              siren=f["siren"], tva_intra=f["tva_intra"], iban=f["iban"], payee=False, paiements=[], anomalies=[])
    fa["paiements"].append(dict(date=date_paiement(fa), montant=ttc, libelle=libelle_paiement(fa), iban=f["iban"]))
    extras.append(fa)
    noter("FACTURE_HORS_EXERCICE", fa, f"Facture datée du {d.isoformat()}, hors de la période 2026")
for f in rng.sample([x for x in FOURNISSEURS if x["mode"] == "VIR"], 3):
    d = jour_ouvre(date(2026, rng.randint(3, 9), rng.randint(2, 26)))
    montant = round(rng.uniform(900, 7800) * 100)
    ligne = dict(date=d, montant=montant, libelle=f"VIR SEPA {sans_accents(f['nom']).upper()[:26]}", iban=f["iban"])
    releve_extra.append(ligne)
    noter("PAIEMENT_SANS_FACTURE", None, f"Paiement de {montant / 100:.2f} EUR à {f['nom']} sans facture correspondante", ligne=ligne)

toutes = factures + copies + extras
rng.shuffle(toutes)
for i, fa in enumerate(toutes, start=1):
    fa["fichier"] = f"scan_{i:04d}.pdf"
    fa["tva_taux_txt"] = f"{fa['taux'] / 100:g}"


def siren_txt(s):
    return f"{s[:3]} {s[3:6]} {s[6:]}"


def dessiner_a(c, fa):
    f = PAR_NOM[fa["fournisseur"]]
    W, H = A4
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, H - 25 * mm, f["nom"])
    c.setFont("Helvetica", 9)
    y = H - 31 * mm
    for t in [f["rue"], f["ville"], f"SIREN {siren_txt(fa['siren'])}", f"N° TVA intracommunautaire : {fa['tva_intra']}"]:
        c.drawString(20 * mm, y, t)
        y -= 4.6 * mm
    c.setFont("Helvetica-Bold", 20)
    c.drawRightString(W - 20 * mm, H - 25 * mm, "FACTURE")
    c.setFont("Helvetica", 10)
    c.drawRightString(W - 20 * mm, H - 33 * mm, f"N° {fa['numero']}")
    c.drawRightString(W - 20 * mm, H - 38 * mm, f"Date : {d_a(fa['date'])}")
    c.drawRightString(W - 20 * mm, H - 43 * mm, f"Échéance : {d_a(fa['echeance'])}")
    c.rect(115 * mm, H - 75 * mm, 75 * mm, 22 * mm)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(118 * mm, H - 58 * mm, "Facturé à :")
    c.setFont("Helvetica", 9)
    for i, t in enumerate([CLIENT["nom"], CLIENT["adresse1"], CLIENT["adresse2"]]):
        c.drawString(118 * mm, H - (62 + 4.2 * i) * mm, t)
    y = H - 95 * mm
    c.setFont("Helvetica-Bold", 9)
    for x, t in [(20, "Désignation"), (110, "Qté"), (127, "Unité"), (147, "P.U. HT"), (172, "Total HT")]:
        c.drawString(x * mm, y, t)
    c.line(20 * mm, y - 2 * mm, 190 * mm, y - 2 * mm)
    c.setFont("Helvetica", 9)
    for l in fa["lignes"]:
        y -= 7 * mm
        c.drawString(20 * mm, y, l["designation"][:58])
        c.drawString(110 * mm, y, f"{l['qte']:g}")
        c.drawString(127 * mm, y, l["unite"])
        c.drawRightString(165 * mm, y, fmt_a(l["pu"]))
        c.drawRightString(190 * mm, y, fmt_a(l["total"]))
    y -= 14 * mm
    for lib, val, gras in [("Total HT", fa["ht"], False), (f"TVA {fa['tva_taux_txt'].replace('.', ',')} %", fa["tva"], False), ("Total TTC", fa["ttc"], True)]:
        c.setFont("Helvetica-Bold" if gras else "Helvetica", 10)
        c.drawString(130 * mm, y, lib)
        c.drawRightString(190 * mm, y, f"{fmt_a(val)} €")
        y -= 6 * mm
    c.setFont("Helvetica", 8)
    pied = [f"Conditions de paiement : {(fa['echeance'] - fa['date']).days} jours. Règlement par virement : IBAN {groupes(fa['iban'])}",
            "En cas de retard de paiement : pénalité de 3 fois le taux d'intérêt légal et indemnité forfaitaire de recouvrement de 40 €."]
    for i, t in enumerate(pied):
        c.drawString(20 * mm, (28 - 4.5 * i) * mm, t)


def dessiner_b(c, fa):
    f = PAR_NOM[fa["fournisseur"]]
    W, H = A4
    c.setFillColor(f["couleur"])
    c.rect(0, H - 32 * mm, W, 32 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(18 * mm, H - 20 * mm, f["nom"])
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(W / 2, H - 45 * mm, "Facture")
    c.setFont("Helvetica", 10)
    for i, t in enumerate([f"Réf. facture : {fa['numero']}", f"Date d'émission : {d_b(fa['date'])}", f"Date d'échéance : {d_b(fa['echeance'])}"]):
        c.drawString(18 * mm, H - (55 + 5.5 * i) * mm, t)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(18 * mm, H - 77 * mm, "Émetteur")
    c.drawString(110 * mm, H - 77 * mm, "Client")
    c.setFont("Helvetica", 9)
    for i, t in enumerate([f["nom"], f["rue"], f["ville"], f"SIREN : {fa['siren']}", f"TVA : {fa['tva_intra']}"]):
        c.drawString(18 * mm, H - (82 + 4.5 * i) * mm, t)
    for i, t in enumerate([CLIENT["nom"], CLIENT["adresse1"], CLIENT["adresse2"], f"SIREN : {CLIENT['siren']}"]):
        c.drawString(110 * mm, H - (82 + 4.5 * i) * mm, t)
    y = H - 115 * mm
    c.setFillColor(colors.HexColor("#e8ecf2"))
    c.rect(18 * mm, y - 2 * mm, 174 * mm, 7 * mm, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9)
    for x, t in [(20, "Description"), (115, "Quantité"), (140, "Prix unitaire"), (172, "Total")]:
        c.drawString(x * mm, y, t)
    c.setFont("Helvetica", 9)
    for l in fa["lignes"]:
        y -= 8 * mm
        c.drawString(20 * mm, y, l["designation"][:60])
        c.drawString(115 * mm, y, f"{l['qte']:g} {l['unite']}")
        c.drawString(140 * mm, y, f"{fmt_b(l['pu'])} EUR")
        c.drawString(172 * mm, y, f"{fmt_b(l['total'])} EUR")
    y -= 16 * mm
    for lib, val, gras in [("Sous-total HT", fa["ht"], False), (f"TVA ({fa['tva_taux_txt']}%)", fa["tva"], False), ("Net à payer", fa["ttc"], True)]:
        c.setFont("Helvetica-Bold" if gras else "Helvetica", 10)
        c.drawString(125 * mm, y, lib)
        c.drawString(165 * mm, y, f"{fmt_b(val)} EUR")
        y -= 6 * mm
    c.setFont("Helvetica", 8)
    c.drawString(18 * mm, 25 * mm, f"Coordonnées bancaires - IBAN : {groupes(fa['iban'])}  BIC : AGRIFRPP")
    c.drawString(18 * mm, 20.5 * mm, "Paiement à réception ou à la date d'échéance. Pas d'escompte pour paiement anticipé.")


def dessiner_c(c, fa):
    f = PAR_NOM[fa["fournisseur"]]
    W, H = A4
    c.setFont("Helvetica-Bold", 11)
    c.drawString(22 * mm, H - 22 * mm, f["nom"])
    c.setFont("Helvetica", 9)
    c.drawString(22 * mm, H - 27 * mm, f"{f['rue']}, {f['ville']}")
    c.setFont("Helvetica-Bold", 13)
    c.drawString(22 * mm, H - 50 * mm, f"Facture n° {fa['numero']} du {d_c(fa['date'])}")
    c.setFont("Helvetica", 9)
    c.drawString(22 * mm, H - 58 * mm, f"Client : {CLIENT['nom']}, {CLIENT['adresse1']}, {CLIENT['adresse2']}")
    y = H - 72 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(22 * mm, y, "Détail de la prestation")
    c.setFont("Helvetica", 10)
    for l in fa["lignes"]:
        y -= 7 * mm
        c.drawString(25 * mm, y, f"- {l['designation'][:62]} : {l['qte']:g} x {fmt_c(l['pu'])} €")
    y -= 18 * mm
    for lib, val, gras in [("Montant HT", fa["ht"], False), (f"TVA {fa['tva_taux_txt'].replace('.', ',')} %", fa["tva"], False),
                           (f"Montant TTC à régler avant le {d_c(fa['echeance'])}", fa["ttc"], True)]:
        c.setFont("Helvetica-Bold" if gras else "Helvetica", 10.5)
        c.drawString(22 * mm, y, f"{lib} : {fmt_c(val)} €")
        y -= 6.5 * mm
    c.setFont("Helvetica", 8)
    c.drawString(22 * mm, 30 * mm, f"SIREN {fa['siren']} - N° TVA {fa['tva_intra']}")
    c.drawString(22 * mm, 25.5 * mm, f"Virement sur le compte {fa['iban']}")
    c.drawString(22 * mm, 21 * mm, f"Indemnité forfaitaire de recouvrement en cas de retard : 40 €")


DESSIN = {"A": dessiner_a, "B": dessiner_b, "C": dessiner_c}
FACTURES.mkdir(parents=True, exist_ok=True)
for ancien in FACTURES.glob("*.pdf"):
    ancien.unlink()
for fa in toutes:
    c = canvas.Canvas(str(FACTURES / fa["fichier"]), pagesize=A4, pageCompression=0)
    c.setTitle(fa["fichier"])
    c.setAuthor("")
    DESSIN[PAR_NOM[fa["fournisseur"]]["layout"]](c, fa)
    c.showPage()
    c.save()

salaires = [dict(date=jour_ouvre(date(2026, m, calendar.monthrange(2026, m)[1]), -1), montant=round(rng.uniform(52000, 58000) * 100), libelle=f"VIR SALAIRES {MOIS[m - 1].upper()} 2026", iban="")
            for m in range(1, 11)]
bruit = list(salaires)
for m in range(1, 11):
    bruit.append(dict(date=jour_ouvre(date(2026, m, 15)), montant=round(rng.uniform(20000, 24000) * 100), libelle="PRLV URSSAF", iban=""))
    bruit.append(dict(date=jour_ouvre(date(2026, m, 20)), montant=round(rng.uniform(8000, 26000) * 100), libelle="PAIEMENT TVA DGFIP", iban=""))
    bruit.append(dict(date=jour_ouvre(date(2026, m, 5)), montant=round(rng.uniform(480, 520) * 100), libelle="FRAIS DE TENUE DE COMPTE ET COMMISSIONS", iban=""))
operations = []
for ligne in bruit:
    operations.append(dict(date=ligne["date"], montant=-ligne["montant"], libelle=ligne["libelle"], iban=ligne["iban"], ligne=ligne))
for client in ["CENTRALE ACHATS MARCHE PLUS", "GROSSISTE VAL D'ARMOR", "ENSEIGNES DISTRIB OUEST", "EXPORT BENELUX GOURMAND"]:
    for _ in range(rng.randint(14, 20)):
        d = jour_ouvre(date(2026, rng.randint(1, 10), rng.randint(1, 28)))
        operations.append(dict(date=d, montant=round(rng.uniform(18000, 140000) * 100), libelle=f"VIR SEPA RECU {client} REMISE {rng.randint(1000, 9999)}", iban=nouvel_iban(), ligne=None))
for fa in toutes:
    for p in fa["paiements"]:
        if p["date"] <= FIN:
            operations.append(dict(date=p["date"], montant=-p["montant"], libelle=p["libelle"], iban=p["iban"], ligne=p))
for p in releve_extra:
    operations.append(dict(date=p["date"], montant=-p["montant"], libelle=p["libelle"], iban=p["iban"], ligne=p))
operations.sort(key=lambda o: (o["date"], o["montant"]))
reference = {}
for i, o in enumerate(operations, start=1):
    o["ref"] = f"OP{o['date']:%y%m%d}-{i:04d}"
    if o["ligne"] is not None:
        reference[id(o["ligne"])] = o["ref"]

DATA.mkdir(exist_ok=True)


def ecrire(nom, colonnes, lignes):
    with open(DATA / nom, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(colonnes)
        w.writerows(lignes)


ecrire("releve_bancaire.csv", ["reference_banque", "date_operation", "libelle", "montant", "iban_contrepartie"],
       [(o["ref"], o["date"].isoformat(), o["libelle"], f"{o['montant'] / 100:.2f}", o["iban"]) for o in operations])
ecrire("fournisseurs.csv", ["siren", "nom", "iban", "taux_tva_habituel", "compte_charge", "delai_paiement_jours", "mode_paiement"],
       [(f["siren"], f["nom"], f["iban"], f"{f['tva'] / 100:g}", f["compte"], f["delai"], f["mode"]) for f in FOURNISSEURS])
ecrire("verite_extraction.csv", ["fichier", "fournisseur", "siren", "numero", "date_facture", "echeance", "total_ht", "taux_tva", "montant_tva", "total_ttc", "iban", "mise_en_page"],
       [(fa["fichier"], fa["fournisseur"], fa["siren"], fa["numero"], fa["date"].isoformat(), fa["echeance"].isoformat(), f"{fa['ht'] / 100:.2f}", fa["tva_taux_txt"],
         f"{fa['tva'] / 100:.2f}", f"{fa['ttc'] / 100:.2f}", fa["iban"], PAR_NOM[fa["fournisseur"]]["layout"]) for fa in sorted(toutes, key=lambda x: x["fichier"])])
lignes_anomalies = []
for a in anomalies:
    fichier = a["fa"]["fichier"] if a["fa"] else ""
    numero = a["fa"]["numero"] if a["fa"] else ""
    fournisseur = a["fa"]["fournisseur"] if a["fa"] else ""
    lignes_anomalies.append((a["type"], fichier, numero, fournisseur, reference.get(id(a["ligne"]), "") if a["ligne"] else "", a["detail"]))
lignes_anomalies.sort(key=lambda x: (x[0], x[1], x[4]))
ecrire("scenario_anomalies.csv", ["type", "fichier", "numero", "fournisseur", "reference_banque", "detail"], lignes_anomalies)

print(f"Factures PDF : {len(toutes)} dans {FACTURES.relative_to(BASE)}")
print(f"Fournisseurs : {len(FOURNISSEURS)} ; mises en page : " + ", ".join(f"{k} = {sum(1 for fa in toutes if PAR_NOM[fa['fournisseur']]['layout'] == k)}" for k in 'ABC'))
print(f"Total TTC des factures : {sum(fa['ttc'] for fa in toutes) / 100:,.0f} €".replace(",", " "))
print(f"Relevé bancaire : {len(operations)} opérations ({sum(1 for o in operations if o['libelle'].startswith(('VIR SEPA', 'PRLV SEPA')) and o['montant'] < 0)} paiements fournisseurs)")
print(f"Anomalies cachées : {len(anomalies)}")
for t in sorted({a['type'] for a in anomalies}):
    print(f"  {t:<24}{sum(1 for a in anomalies if a['type'] == t)}")
print("Fichiers : releve_bancaire.csv, fournisseurs.csv, verite_extraction.csv, scenario_anomalies.csv (corrigé, jamais lu par les scripts)")
