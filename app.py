from flask import Flask, request, jsonify, render_template
import pandas as pd
from datetime import datetime, timedelta

app = Flask(__name__)

df = pd.read_excel("rutas.xlsx", engine="openpyxl")

def normalizar(texto):
    return str(texto).strip().lower()

def buscar_rutas(origen, destino, incluir_coche):
    origen = normalizar(origen)
    destino = normalizar(destino)
    rutas_posibles = []

    if incluir_coche:
        coche_df = df[df['Transporte'].str.contains("Coche", na=False)]
        df_ext = pd.concat([df, coche_df])
    else:
        df_ext = df.copy()

    for _, fila in df_ext.iterrows():
        if origen in normalizar(fila['Origen']) and destino in normalizar(fila['Destino']):
            rutas_posibles.append([fila])

    for _, tramo1 in df_ext.iterrows():
        if origen in normalizar(tramo1['Origen']):
            for _, tramo2 in df_ext.iterrows():
                if normalizar(tramo1['Destino']) in normalizar(tramo2['Origen']):
                    if destino in normalizar(tramo2['Destino']):
                        rutas_posibles.append([tramo1, tramo2])
                    else:
                        for _, tramo3 in df_ext.iterrows():
                            if normalizar(tramo2['Destino']) in normalizar(tramo3['Origen']) and destino in normalizar(tramo3['Destino']):
                                rutas_posibles.append([tramo1, tramo2, tramo3])

    return rutas_posibles

def convertir_a_json(ruta):
    tramos = []
    tiempo_total = timedelta()
    precio_total = 0
    llegada_final = None

    for tramo in ruta:
        salida = tramo['Salida'] if pd.notna(tramo['Salida']) else ""
        llegada = tramo['Llegada'] if pd.notna(tramo['Llegada']) else ""
        medio = tramo['Transporte']
        precio = float(tramo['Precio']) if pd.notna(tramo['Precio']) else 0.0

        tramos.append({
            "origen": tramo['Origen'],
            "destino": tramo['Destino'],
            "salida": str(salida),
            "llegada": str(llegada),
            "medio": medio,
            "precio": precio
        })

        if pd.notna(salida) and pd.notna(llegada):
            try:
                h_salida = datetime.strptime(str(salida), "%H:%M:%S")
                h_llegada = datetime.strptime(str(llegada), "%H:%M:%S")
                tiempo_total += (h_llegada - h_salida)
                llegada_final = h_llegada
            except:
                pass
        precio_total += precio

    return {
        "tramos": tramos,
        "tiempo_total": str(tiempo_total),
        "precio_total": round(precio_total, 2),
        "llegada_final": llegada_final.strftime("%H:%M") if llegada_final else ""
    }

@app.route("/buscar")
def buscar():
    origen = request.args.get("origen", "")
    destino = request.args.get("destino", "")
    incluir_coche = request.args.get("coche", "false") == "true"

    rutas = buscar_rutas(origen, destino, incluir_coche)
    if rutas:
        mejor_ruta = rutas[0]
        return jsonify(convertir_a_json(mejor_ruta))
    else:
        return jsonify({"tramos": [], "tiempo_total": "0:00:00", "precio_total": 0, "llegada_final": ""})

@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    app.run(debug=True)

