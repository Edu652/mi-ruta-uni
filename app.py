
from flask import Flask, request, jsonify, render_template
import pandas as pd
from datetime import datetime, timedelta

app = Flask(__name__)

# Cargar el archivo Excel
df = pd.read_excel("rutas.xlsx", engine="openpyxl")

def parse_time(t):
    try:
        return datetime.strptime(str(t), "%H:%M:%S")
    except:
        return None

def calcular_ruta(origen, destino, incluir_coche):
    rutas = df[df['Origen'].str.lower() == origen.lower()]
    if incluir_coche:
        rutas = pd.concat([rutas, df[df['Transporte'].str.contains("Coche", na=False)]])
    
    resultado = []
    tiempo_total = timedelta()
    precio_total = 0
    llegada_final = None

    for _, fila in rutas.iterrows():
        if fila['Destino'].lower() == destino.lower():
            tramo = {
                "origen": fila['Origen'],
                "destino": fila['Destino'],
                "salida": str(fila['Salida']) if pd.notna(fila['Salida']) else "",
                "llegada": str(fila['Llegada']) if pd.notna(fila['Llegada']) else "",
                "medio": fila['Transporte'],
                "precio": float(fila['Precio']) if pd.notna(fila['Precio']) else 0.0
            }
            resultado.append(tramo)

            if pd.notna(fila['Salida']) and pd.notna(fila['Llegada']):
                salida = parse_time(fila['Salida'])
                llegada = parse_time(fila['Llegada'])
                if salida and llegada:
                    tiempo_total += (llegada - salida)
                    llegada_final = llegada
            if pd.notna(fila['Precio']):
                precio_total += float(fila['Precio'])

    return {
        "tramos": resultado,
        "tiempo_total": str(tiempo_total),
        "precio_total": round(precio_total, 2),
        "llegada_final": llegada_final.strftime("%H:%M") if llegada_final else ""
    }

@app.route("/buscar", methods=["GET"])
def buscar():
    origen = request.args.get("origen")
    destino = request.args.get("destino")
    incluir_coche = request.args.get("coche") == "true"
    ruta = calcular_ruta(origen, destino, incluir_coche)
    return jsonify(ruta)

@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    app.run(debug=True)


