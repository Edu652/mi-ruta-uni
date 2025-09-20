from flask import Flask, render_template, request
import pandas as pd
import json
import random
from datetime import datetime, timedelta

app = Flask(__name__)

# --- Carga de Datos ---
try:
    # Leemos el archivo Excel
    rutas_df = pd.read_excel("rutas.xlsx", engine="openpyxl")

    # Corregimos el formato de hora para que acepte segundos (HH:MM:SS)
    rutas_df["Salida"] = pd.to_datetime(rutas_df["Salida"], format='%H:%M:%S', errors='coerce').dt.time
    rutas_df["Llegada"] = pd.to_datetime(rutas_df["Llegada"], format='%H:%M:%S', errors='coerce').dt.time

    # Eliminamos cualquier fila donde la conversión de hora haya fallado.
    filas_originales = len(rutas_df)
    rutas_df.dropna(subset=['Salida', 'Llegada'], inplace=True)
    filas_limpias = len(rutas_df)
    
    if filas_originales > filas_limpias:
        print(f"ADVERTENCIA: Se eliminaron {filas_originales - filas_limpias} filas por tener un formato de hora incorrecto.")

except FileNotFoundError:
    print("ERROR CRÍTICO: No se encontró 'rutas.xlsx'.")
    rutas_df = pd.DataFrame(columns=["Origen", "Destino", "Salida", "Llegada", "Precio", "Compañia"])
except Exception as e:
    print(f"ERROR CRÍTICO: Ocurrió un error al cargar 'rutas.xlsx': {e}")
    rutas_df = pd.DataFrame(columns=["Origen", "Destino", "Salida", "Llegada", "Precio", "Compañia"])

# Cargamos las frases motivadoras
try:
    with open("frases_motivadoras.json", "r", encoding="utf-8") as f:
        frases = json.load(f)
except FileNotFoundError:
    frases = ["El éxito es la suma de pequeños esfuerzos repetidos día tras día."]


@app.route("/")
def index():
    if not rutas_df.empty:
        # Aseguramos que los lugares no tengan espacios extra
        origenes = rutas_df["Origen"].str.strip()
        destinos = rutas_df["Destino"].str.strip()
        lugares = sorted(set(origenes).union(set(destinos)))
    else:
        lugares = [] 
    frase = random.choice(frases)
    return render_template("index.html", lugares=lugares, frase=frase)


@app.route("/buscar", methods=["POST"])
def buscar():
    origen = request.form["origen"]
    destino = request.form["destino"]
    rutas_validas = []

    # Búsqueda de rutas directas
    rutas_directas = rutas_df[(rutas_df["Origen"] == origen) & (rutas_df["Destino"] == destino)]
    for _, ruta in rutas_directas.iterrows():
        rutas_validas.append([ruta.to_dict()])

    # Búsqueda de rutas con 1 transbordo
    TIEMPO_MINIMO_TRANSBORDO = timedelta(minutes=15)
    posibles_primeros_tramos = rutas_df[rutas_df["Origen"] == origen]
    for _, tramo1 in posibles_primeros_tramos.iterrows():
        punto_intermedio = tramo1["Destino"]
        if punto_intermedio == destino: continue
        
        posibles_segundos_tramos = rutas_df[(rutas_df["Origen"] == punto_intermedio) & (rutas_df["Destino"] == destino)]
        for _, tramo2 in posibles_segundos_tramos.iterrows():
            hora_llegada_tramo1 = datetime.combine(datetime.today(), tramo1["Llegada"])
            hora_salida_tramo2 = datetime.combine(datetime.today(), tramo2["Salida"])
            if hora_salida_tramo2 >= (hora_llegada_tramo1 + TIEMPO_MINIMO_TRANSBORDO):
                rutas_validas.append([tramo1.to_dict(), tramo2.to_dict()])

    # Procesar y ordenar resultados
    resultados_finales = []
    for ruta in rutas_validas:
        precio_total = sum(pd.to_numeric(s.get("Precio", 0), errors='coerce') for s in ruta)
        
        # Preparamos los segmentos para mostrarlos en el HTML
        for segmento in ruta:
            segmento["Salida_str"] = segmento["Salida"].strftime('%H:%M')
            segmento["Llegada_str"] = segmento["Llegada"].strftime('%H:%M')
        
        hora_llegada_final = ruta[-1]["Llegada"]
        resultados_finales.append({
            "segmentos": ruta, "precio_total": round(precio_total, 2),
            "hora_llegada_final_str": hora_llegada_final.strftime('%H:%M'),
            "hora_llegada_final": hora_llegada_final,
            "tipo": "Directo" if len(ruta) == 1 else "Transbordo"
        })

    if resultados_finales:
        # Ordenamos por hora de llegada y luego por precio
        resultados_finales.sort(key=lambda x: (x["hora_llegada_final"], x["precio_total"]))

    return render_template("resultado.html", origen=origen, destino=destino, resultados=resultados_finales)

if __name__ == "__main__":
    app.run(debug=True)

