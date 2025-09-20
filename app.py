from flask import Flask, render_template, request
import pandas as pd
import json
import random
from datetime import datetime, timedelta

app = Flask(__name__)

rutas_df = pd.read_excel("rutas.xlsx", engine="openpyxl")

with open("frases_motivadoras.json", "r", encoding="utf-8") as f:
    frases = json.load(f)

@app.route("/")
def index():
    lugares = sorted(set(rutas_df["Origen"]).union(set(rutas_df["Destino"])))
    frase = random.choice(frases)
    return render_template("index.html", lugares=lugares, frase=frase)

@app.route("/buscar", methods=["POST"])
def buscar():
    origen = request.form["origen"]
    destino = request.form["destino"]

    directas = rutas_df[(rutas_df["Origen"] == origen) & (rutas_df["Destino"] == destino)]

    intermedios = rutas_df[rutas_df["Origen"] == origen]["Destino"].unique()
    transbordos = []
    for punto in intermedios:
        tramo1 = rutas_df[(rutas_df["Origen"] == origen) & (rutas_df["Destino"] == punto)]
        tramo2 = rutas_df[(rutas_df["Origen"] == punto) & (rutas_df["Destino"] == destino)]
        if not tramo1.empty and not tramo2.empty:
            transbordos.append((tramo1.iloc[0], tramo2.iloc[0]))

    segmentos = []
    if not directas.empty:
        for _, fila in directas.iterrows():
            segmentos.append({
                "origen": fila["Origen"],
                "destino": fila["Destino"],
                "salida": fila["Salida"].strftime("%H:%M") if not pd.isna(fila["Salida"]) else "—",
                "llegada": fila["Llegada"].strftime("%H:%M") if not pd.isna(fila["Llegada"]) else "—",
                "precio": fila["Precio"]
            })
    elif transbordos:
        for tramo1, tramo2 in transbordos:
            for tramo in [tramo1, tramo2]:
                segmentos.append({
                    "origen": tramo["Origen"],
                    "destino": tramo["Destino"],
                    "salida": tramo["Salida"].strftime("%H:%M") if not pd.isna(tramo["Salida"]) else "—",
                    "llegada": tramo["Llegada"].strftime("%H:%M") if not pd.isna(tramo["Llegada"]) else "—",
                    "precio": tramo["Precio"]
                })

    tiempo_total = timedelta()
    precio_total = 0
    llegada_final = "—"
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
