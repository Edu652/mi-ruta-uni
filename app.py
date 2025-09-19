from flask import Flask, render_template, request
import pandas as pd
import json
from datetime import datetime, timedelta

app = Flask(__name__)

# Cargar rutas desde Excel
rutas_df = pd.read_excel("rutas.xlsx", engine="openpyxl")

# Cargar frases motivadoras
with open("frases_motivadoras.json", "r", encoding="utf-8") as f:
    frases = json.load(f)

@app.route("/")
def index():
    lugares = sorted(set(rutas_df["Origen"]).union(set(rutas_df["Destino"])))
    frase = frases[0]  # Se puede hacer aleatoria si se desea
    return render_template("index.html", lugares=lugares, frase=frase)

@app.route("/buscar", methods=["POST"])
def buscar():
    origen = request.form["origen"]
    destino = request.form["destino"]

    # Filtrar rutas posibles
    rutas_posibles = rutas_df[(rutas_df["Origen"] == origen) | (rutas_df["Destino"] == destino)]

    # Simular transbordos (simplificado)
    segmentos = []
    actuales = rutas_df[rutas_df["Origen"] == origen]
    for i, fila in actuales.iterrows():
        segmento = {
            "origen": fila["Origen"],
            "destino": fila["Destino"],
            "salida": fila["Salida"].strftime("%H:%M") if not pd.isna(fila["Salida"]) else "—",
            "llegada": fila["Llegada"].strftime("%H:%M") if not pd.isna(fila["Llegada"]) else "—",
            "precio": fila["Precio"]
        }
        segmentos.append(segmento)

    # Calcular resumen
    tiempo_total = timedelta()
    precio_total = 0
    llegada_final = None
    for seg in segmentos:
        try:
            h1 = datetime.strptime(seg["salida"], "%H:%M")
            h2 = datetime.strptime(seg["llegada"], "%H:%M")
            tiempo_total += (h2 - h1)
            llegada_final = seg["llegada"]
        except:
            pass
        precio_total += seg["precio"]

    return render_template("resultado.html", segmentos=segmentos,
                           tiempo_total=str(tiempo_total),
                           precio_total=round(precio_total, 2),
                           llegada_final=llegada_final)

if __name__ == "__main__":
    app.run(debug=True)
