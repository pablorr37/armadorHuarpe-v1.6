from pathlib import Path
base_dir = Path(r"\\192.168.0.181\vault\PAPEL\PRUEBA_SMBBUG")

for subpath in [
    "final",
    "final/mandar",
    "final/mandar/a pdf",
    "fue",
    "materiales"
]:
    print("Creando:", subpath)
    (base_dir / subpath).mkdir(parents=True, exist_ok=True)
print("✅ Todo creado correctamente")
