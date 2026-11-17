import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ETAPES = ["generer_factures.py", "extraire_factures.py", "controler_factures.py", "rapprocher_banque.py", "produire_rapport.py"]

for i, script in enumerate(ETAPES, start=1):
    print(f"\n{'=' * 78}\nÉtape {i}/{len(ETAPES)} : {script}\n{'=' * 78}")
    if subprocess.run([sys.executable, str(BASE / script)], cwd=BASE).returncode:
        sys.exit(f"\nArrêt : {script} a échoué.")
print("\nTraitement terminé. Factures et relevé dans « data », rapport Excel et résultats dans « resultats ».")
