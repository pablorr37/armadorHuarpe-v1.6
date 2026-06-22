# ============================================================
#  tiempos_qxp.py
# ------------------------------------------------------------
#  • Recorre subcarpetas con archivos .qxp
#  • Calcula promedios diarios de intervalo entre creaciones
#  • Genera CSV + gráfico con curva suavizada (media móvil)
# ============================================================

import os
import datetime
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from tkinter import Tk, filedialog

def seleccionar_carpeta():
    Tk().withdraw()
    ruta = filedialog.askdirectory(title="Seleccionar carpeta base (Ej: Z:/PAPEL/En proceso/)")
    return Path(ruta) if ruta else None

def analizar_qxp(base_dir: Path):
    datos = []
    for root, _, files in os.walk(base_dir):
        for f in files:
            if f.lower().endswith(".qxp"):
                path = Path(root) / f
                ts = datetime.datetime.fromtimestamp(path.stat().st_ctime)
                datos.append(ts)

    if not datos:
        print("⚠️ No se encontraron archivos .qxp.")
        return

    df = pd.DataFrame({"fecha_hora": datos})
    df["fecha"] = df["fecha_hora"].dt.date
    resultados = []

    for fecha, grupo in df.groupby("fecha"):
        horas = sorted(grupo["fecha_hora"].tolist())
        if len(horas) > 1:
            difs = [(horas[i+1] - horas[i]).total_seconds()/60 for i in range(len(horas)-1)]
            prom = sum(difs) / len(difs)
        else:
            prom = 0
        resultados.append({
            "Fecha": fecha,
            "Promedio_min": round(prom, 2),
            "Cantidad": len(horas)
        })

    out = pd.DataFrame(resultados).sort_values("Fecha")
    out["Fecha"] = pd.to_datetime(out["Fecha"])
    out["Tendencia_7d"] = out["Promedio_min"].rolling(window=7, center=True, min_periods=1).mean()

    # --- Exportar ---
    out_dir = base_dir / "resultados"
    out_dir.mkdir(exist_ok=True)
    out_csv = out_dir / "promedios_qxp.csv"
    out_png = out_dir / "promedios_qxp.png"
    out.to_csv(out_csv, index=False)

    # --- Gráfico ---
    plt.figure(figsize=(10,5))
    plt.plot(out["Fecha"], out["Promedio_min"], marker="o", color="tab:blue", label="Promedio diario")
    plt.plot(out["Fecha"], out["Tendencia_7d"], color="tab:orange", linewidth=2.5, label="Tendencia (7 días)")
    plt.title("Promedio diario de intervalo entre QXP (con curva de tendencia)")
    plt.xlabel("Fecha")
    plt.ylabel("Promedio (minutos)")
    plt.grid(True, linestyle="--", alpha=0.6)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_png)
    plt.show()

    print(f"\n✅ CSV guardado en: {out_csv}")
    print(f"✅ Gráfico guardado en: {out_png}")

if __name__ == "__main__":
    base = seleccionar_carpeta()
    if base:
        analizar_qxp(base)
