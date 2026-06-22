# ============================================================
#  horarios_pdf.py
# ------------------------------------------------------------
#  • Recorre subcarpetas de "IMPRENTA TEMPORAL" que contengan "OK"
#  • Lee la HORA DE CREACIÓN de cada .pdf (ctime)
#  • Exporta:
#       1) CSV de eventos con hora exacta por PDF
#       2) CSV de estadísticas diarias (promedio, mediana, 1º y último)
#  • Grafica:
#       A) Dispersión de horas (puntos) por día
#       B) Línea de mediana diaria + curva de tendencia (rolling 7 días)
# ============================================================

import os
import datetime
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from tkinter import Tk, filedialog
import numpy as np

# ---------- Utilidades ----------
def _select_dir(title: str) -> Path | None:
    Tk().withdraw()
    ruta = filedialog.askdirectory(title=title)
    return Path(ruta) if ruta else None

def _segundos_desde_medianoche(dt: datetime.datetime) -> int:
    return dt.hour * 3600 + dt.minute * 60 + dt.second

def _hhmm_from_seconds(s: float) -> str:
    s = int(round(s))
    h = (s // 3600) % 24
    m = (s % 3600) // 60
    return f"{int(h):02d}:{int(m):02d}"

# ---------- Núcleo ----------
def analizar_horarios_pdf(base_dir: Path, ventana_tendencia: int = 7):
    # 1) Recolectar PDFs (solo en rutas que contengan "OK")
    registros = []
    for root, _, files in os.walk(base_dir):
        if "OK" not in root:
            continue
        for f in files:
            if f.lower().endswith(".pdf"):
                p = Path(root) / f
                ts = datetime.datetime.fromtimestamp(p.stat().st_ctime)
                registros.append({"path": str(p), "fecha_hora": ts})

    if not registros:
        print("⚠️ No se encontraron PDFs en carpetas 'OK'.")
        return

    df = pd.DataFrame(registros)
    df["Fecha"] = df["fecha_hora"].dt.date
    df["Hora"]  = df["fecha_hora"].dt.time
    df["Segs"]  = df["fecha_hora"].apply(_segundos_desde_medianoche)
    df["Hora_HHMM"] = df["Segs"].apply(_hhmm_from_seconds)
    df["Hora_decimal"] = df["Segs"] / 3600.0  # útil para análisis adicional

    # 2) Ordenar y exportar CSV de eventos
    df = df.sort_values(["Fecha", "fecha_hora"])
    out_dir = base_dir / "resultados"
    out_dir.mkdir(exist_ok=True)
    csv_eventos = out_dir / "horarios_pdf_eventos.csv"
    df_out = df[["Fecha", "Hora_HHMM", "Hora_decimal", "path"]]
    df_out.to_csv(csv_eventos, index=False)

    # 3) Estadísticas por día
    estadisticas = []
    for fecha, g in df.groupby("Fecha"):
        segs = g["Segs"].to_numpy()
        segs_sorted = np.sort(segs)
        hora_prom  = _hhmm_from_seconds(np.mean(segs))
        hora_med   = _hhmm_from_seconds(np.median(segs))
        hora_prim  = _hhmm_from_seconds(segs_sorted[0])
        hora_ult   = _hhmm_from_seconds(segs_sorted[-1])
        estadisticas.append({
            "Fecha": fecha,
            "Cantidad": len(segs),
            "Hora_promedio": hora_prom,
            "Hora_mediana": hora_med,
            "Primera_hora": hora_prim,
            "Ultima_hora": hora_ult
        })

    daily = pd.DataFrame(estadisticas).sort_values("Fecha")
    daily["Fecha"] = pd.to_datetime(daily["Fecha"])
    # Para tendencia usamos la mediana (más robusta)
    daily["Mediana_decimal"] = daily["Hora_mediana"].apply(lambda s: int(s.split(":")[0]) + int(s.split(":")[1])/60)
    daily["Tendencia_7d"] = daily["Mediana_decimal"].rolling(window=ventana_tendencia, center=True, min_periods=1).mean()

    csv_daily = out_dir / "horarios_pdf_estadisticas_diarias.csv"
    daily_out = daily.copy()
    # Guardamos también la tendencia como HH:MM aproximado
    daily_out["Tendencia_7d_HHMM"] = daily["Tendencia_7d"].apply(lambda x: _hhmm_from_seconds(x*3600))
    daily_out = daily_out[["Fecha", "Cantidad", "Hora_promedio", "Hora_mediana", "Primera_hora", "Ultima_hora", "Tendencia_7d_HHMM"]]
    daily_out.to_csv(csv_daily, index=False)

    # 4A) Gráfico de dispersión: cada PDF como punto a lo largo del día
    png_scatter = out_dir / "horarios_pdf_dispersion.png"
    plt.figure(figsize=(11,5.5))
    plt.scatter(pd.to_datetime(df["Fecha"]), df["Hora_decimal"], alpha=0.6, label="Hora por PDF")
    plt.title("Horarios de creación de PDFs (dispersión diaria)")
    plt.xlabel("Fecha")
    plt.ylabel("Hora del día")
    plt.yticks(range(0, 25, 2))
    plt.grid(True, linestyle="--", alpha=0.6)
    plt.legend()
    plt.tight_layout()
    plt.savefig(png_scatter)
    plt.show()

    # 4B) Mediana diaria + tendencia (rolling 7 días)
    png_tend = out_dir / "horarios_pdf_mediana_tendencia.png"
    plt.figure(figsize=(11,5.5))
    plt.plot(daily["Fecha"], daily["Mediana_decimal"], linewidth=1.8, label="Mediana diaria (hora)")
    plt.plot(daily["Fecha"], daily["Tendencia_7d"], linewidth=2.6, label=f"Tendencia ({ventana_tendencia} días)")
    plt.title("Hora mediana diaria de creación de PDFs (con tendencia)")
    plt.xlabel("Fecha")
    plt.ylabel("Hora del día")
    plt.yticks(range(0, 25, 2))
    plt.grid(True, linestyle="--", alpha=0.6)
    plt.legend()
    plt.tight_layout()
    plt.savefig(png_tend)
    plt.show()

    print("\n✅ Exportes:")
    print(f"   • CSV eventos: {csv_eventos}")
    print(f"   • CSV diarios: {csv_daily}")
    print(f"   • PNG dispersión: {png_scatter}")
    print(f"   • PNG mediana+tendencia: {png_tend}")

if __name__ == "__main__":
    base = _select_dir("Seleccionar carpeta base (Ej: Z:/PAPEL/IMPRENTA TEMPORAL/)")
    if base:
        analizar_horarios_pdf(base)
