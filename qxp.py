# ============================================================
#  intervalos_qxp.py
# ------------------------------------------------------------
#  • Recorre subcarpetas con archivos .qxp
#  • Calcula intervalos entre creaciones consecutivas por día
#  • Exporta CSV + gráfico con:
#      - Puntos individuales (intervalos)
#      - Línea diaria (mediana)
#      - Curva de tendencia (rolling 7 días)
#      - Barras verticales separando los días
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
                datos.append({"path": str(path), "fecha_hora": ts})

    if not datos:
        print("⚠️ No se encontraron archivos .qxp.")
        return

    df = pd.DataFrame(datos)
    df["fecha"] = df["fecha_hora"].dt.date
    resultados = []

    for fecha, grupo in df.groupby("fecha"):
        grupo = grupo.sort_values("fecha_hora")
        horas = grupo["fecha_hora"].tolist()
        rutas = grupo["path"].tolist()
        for i in range(len(horas)-1):
            delta = (horas[i+1] - horas[i]).total_seconds() / 60
            resultados.append({
                "Fecha": fecha,
                "Intervalo_min": round(delta, 2),
                "Archivo_anterior": Path(rutas[i]).name,
                "Archivo_actual": Path(rutas[i+1]).name,
                "Hora_anterior": horas[i].strftime("%H:%M:%S"),
                "Hora_actual": horas[i+1].strftime("%H:%M:%S")
            })

    if not resultados:
        print("⚠️ No hubo días con al menos dos QXP para calcular intervalos.")
        return

    out = pd.DataFrame(resultados).sort_values(["Fecha", "Hora_anterior"])
    out_dir = base_dir / "resultados"
    out_dir.mkdir(exist_ok=True)
    out_csv = out_dir / "intervalos_qxp.csv"
    out_png = out_dir / "intervalos_qxp.png"
    out.to_csv(out_csv, index=False)

    # --- Curvas: Mediana diaria y tendencia 7d ---
    daily = (out.groupby("Fecha", as_index=False)["Intervalo_min"]
                .median()
                .rename(columns={"Intervalo_min": "Mediana_diaria"}))
    daily["Fecha"] = pd.to_datetime(daily["Fecha"])
    daily = daily.sort_values("Fecha")
    daily["Tendencia_7d"] = daily["Mediana_diaria"].rolling(window=7, center=True, min_periods=1).mean()

    # --- Gráfico ---
    plt.figure(figsize=(11,5.5))
    plt.scatter(pd.to_datetime(out["Fecha"]), out["Intervalo_min"], alpha=0.6, label="Intervalos (min)")
    plt.plot(daily["Fecha"], daily["Mediana_diaria"], linewidth=1.8, label="Mediana diaria")
    plt.plot(daily["Fecha"], daily["Tendencia_7d"], linewidth=2.6, label="Tendencia (7 días)")

    # 🔹 Barras verticales separando los días
    fechas_unicas = daily["Fecha"].tolist()
    for f in fechas_unicas:
        plt.axvline(f, color="lightgray", linestyle="--", alpha=0.4, linewidth=0.8)

    plt.title("Intervalos entre creaciones de QXP por día (con tendencia)")
    plt.xlabel("Fecha")
    plt.ylabel("Intervalo (minutos)")
    plt.grid(True, linestyle="--", alpha=0.5)
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
