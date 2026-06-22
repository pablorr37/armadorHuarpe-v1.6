# ============================================================
#  tiempos_pdf.py
# ------------------------------------------------------------
#  • Recorre subcarpetas (solo “OK”) con archivos .pdf
#  • Calcula:
#      - Promedio diario de intervalo entre PDFs
#      - Hora promedio del día
#  • Genera CSV + 2 gráficos con curvas suavizadas
# ============================================================

import os
import datetime
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from tkinter import Tk, filedialog
import numpy as np

def seleccionar_carpeta():
    Tk().withdraw()
    ruta = filedialog.askdirectory(title="Seleccionar carpeta base (Ej: Z:/PAPEL/IMPRENTA TEMPORAL/)")
    return Path(ruta) if ruta else None

def analizar_pdf(base_dir: Path):
    datos = []
    for root, _, files in os.walk(base_dir):
        if "OK" not in root:
            continue
        for f in files:
            if f.lower().endswith(".pdf"):
                path = Path(root) / f
                ts = datetime.datetime.fromtimestamp(path.stat().st_ctime)
                datos.append(ts)

    if not datos:
        print("⚠️ No se encontraron archivos .pdf.")
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
        # Hora promedio
        segundos = [h.hour*3600 + h.minute*60 + h.second for h in horas]
        hora_prom = datetime.time(int(np.mean(segundos)//3600), int((np.mean(segundos)%3600)//60))
        resultados.append({
            "Fecha": fecha,
            "Promedio_min": round(prom, 2),
            "Hora_promedio": hora_prom.strftime("%H:%M"),
            "Cantidad": len(horas)
        })

    out = pd.DataFrame(resultados).sort_values("Fecha")
    out["Fecha"] = pd.to_datetime(out["Fecha"])
    out["Tendencia_7d"] = out["Promedio_min"].rolling(window=7, center=True, min_periods=1).mean()

    # --- Exportar ---
    out_dir = base_dir / "resultados"
    out_dir.mkdir(exist_ok=True)
    out_csv = out_dir / "promedios_pdf.csv"
    out_png1 = out_dir / "promedios_pdf_intervalo.png"
    out_png2 = out_dir / "promedios_pdf_hora.png"
    out.to_csv(out_csv, index=False)

    # --- Gráfico 1: Intervalos promedio ---
    plt.figure(figsize=(10,5))
    plt.plot(out["Fecha"], out["Promedio_min"], marker="o", color="tab:blue", label="Promedio diario")
    plt.plot(out["Fecha"], out["Tendencia_7d"], color="tab:orange", linewidth=2.5, label="Tendencia (7 días)")
    plt.title("Promedio diario de intervalo entre PDFs (con curva de tendencia)")
    plt.xlabel("Fecha")
    plt.ylabel("Promedio (minutos)")
    plt.grid(True, linestyle="--", alpha=0.6)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_png1)
    plt.show()

    # --- Gráfico 2: Hora promedio ---
    plt.figure(figsize=(10,5))
    horas_float = [int(h.split(":")[0]) + int(h.split(":")[1])/60 for h in out["Hora_promedio"]]
    tendencia_hora = pd.Series(horas_float).rolling(window=7, center=True, min_periods=1).mean()
    plt.plot(out["Fecha"], horas_float, marker="o", color="tab:green", label="Hora promedio")
    plt.plot(out["Fecha"], tendencia_hora, color="tab:red", linewidth=2.5, label="Tendencia (7 días)")
    plt.title("Hora promedio diaria de creación de PDFs (con curva de tendencia)")
    plt.xlabel("Fecha")
    plt.ylabel("Hora del día")
    plt.yticks(range(0, 25, 2))
    plt.grid(True, linestyle="--", alpha=0.6)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_png2)
    plt.show()

    print(f"\n✅ CSV guardado en: {out_csv}")
    print(f"✅ Gráficos guardados en: {out_png1}, {out_png2}")

if __name__ == "__main__":
    base = seleccionar_carpeta()
    if base:
        analizar_pdf(base)
