from flask import Flask, render_template, request
import pandas as pd
import json
import random
from datetime import datetime, timedelta

app = Flask(__name__)

# --- Carga de Datos ---
# Leemos el archivo Excel. Asegúrate que las columnas de hora son de tipo datetime.
try:
    rutas_df = pd.read_excel("rutas.xlsx", engine="openpyxl")
    # Convertimos las columnas de hora a objetos de tiempo para poder compararlas
    rutas_df["Salida"] = pd.to_datetime(rutas_df["Salida"], format='%H:%M').dt.time
    rutas_df["Llegada"] = pd.to_datetime(rutas_df["Llegada"], format='%H:%M').dt.time
except FileNotFoundError:
    print("Error: El archivo 'rutas.xlsx' no se encontró. Asegúrate de que está en la misma carpeta.")
    # Creamos un DataFrame vacío para que la app no falle al iniciar
    rutas_df = pd.DataFrame(columns=["Origen", "Destino", "Salida", "Llegada", "Precio", "Compania"])

# Cargamos las frases motivadoras
try:
    with open("frases_motivadoras.json", "r", encoding="utf-8") as f:
        frases = json.load(f)
except FileNotFoundError:
    frases = [{"texto": "El éxito es la suma de pequeños esfuerzos repetidos día tras día.", "autor": "Robert Collier"}]


@app.route("/")
def index():
    # Obtenemos una lista única y ordenada de todos los lugares
    if not rutas_df.empty:
        lugares = sorted(set(rutas_df["Origen"]).union(set(rutas_df["Destino"])))
    else:
        lugares = ["No hay datos de rutas"]
        
    frase = random.choice(frases)
    return render_template("index.html", lugares=lugares, frase=frase)


@app.route("/buscar", methods=["POST"])
def buscar():
    origen = request.form["origen"]
    destino = request.form["destino"]

    rutas_validas = []

    # --- 1. BÚSQUEDA DE RUTAS DIRECTAS ---
    rutas_directas = rutas_df[(rutas_df["Origen"] == origen) & (rutas_df["Destino"] == destino)]
    for _, ruta in rutas_directas.iterrows():
        # Cada ruta válida es una lista de segmentos. Las directas tienen 1 segmento.
        rutas_validas.append([ruta.to_dict()])

    # --- 2. BÚSQUEDA DE RUTAS CON 1 TRANSBORDO ---
    # Tiempo mínimo de espera para un transbordo (ej. 15 minutos)
    TIEMPO_MINIMO_TRANSBORDO = timedelta(minutes=15)

    # Posibles puntos de transbordo desde el origen
    posibles_primeros_tramos = rutas_df[rutas_df["Origen"] == origen]

    for _, tramo1 in posibles_primeros_tramos.iterrows():
        punto_intermedio = tramo1["Destino"]
        
        # Si el punto intermedio es el destino final, ya es una ruta directa
        if punto_intermedio == destino:
            continue

        # Buscamos el segundo tramo: desde el punto intermedio hasta el destino final
        posibles_segundos_tramos = rutas_df[(rutas_df["Origen"] == punto_intermedio) & (rutas_df["Destino"] == destino)]

        for _, tramo2 in posibles_segundos_tramos.iterrows():
            # **LA LÓGICA CLAVE: Comprobar si el transbordo es posible en el tiempo**
            hora_llegada_tramo1 = datetime.combine(datetime.today(), tramo1["Llegada"])
            hora_salida_tramo2 = datetime.combine(datetime.today(), tramo2["Salida"])

            # Comprobamos que la salida del segundo tramo es POSTERIOR a la llegada del primero
            # y que además hay un margen de tiempo mínimo para el transbordo.
            if hora_salida_tramo2 >= (hora_llegada_tramo1 + TIEMPO_MINIMO_TRANSBORDO):
                # Si la conexión es válida, la añadimos como una opción de ruta
                rutas_validas.append([tramo1.to_dict(), tramo2.to_dict()])

    # --- 3. PROCESAR Y ORDENAR LAS RUTAS ENCONTRADAS ---
    resultados_finales = []
    for ruta in rutas_validas:
        precio_total = sum(segmento["Precio"] for segmento in ruta)
        
        # Formateamos las horas para mostrarlas correctamente
        for segmento in ruta:
            segmento["Salida_str"] = segmento["Salida"].strftime('%H:%M')
            segmento["Llegada_str"] = segmento["Llegada"].strftime('%H:%M')
        
        hora_llegada_final = ruta[-1]["Llegada"]

        resultados_finales.append({
            "segmentos": ruta,
            "precio_total": round(precio_total, 2),
            "hora_llegada_final": hora_llegada_final,
            "hora_llegada_final_str": hora_llegada_final.strftime('%H:%M'),
            "tipo": "Directo" if len(ruta) == 1 else "Transbordo"
        })

    # Ordenamos los resultados: primero por hora de llegada, y luego por precio
    if resultados_finales:
        resultados_finales.sort(key=lambda x: (x["hora_llegada_final"], x["precio_total"]))

    return render_template(
        "resultado.html",
        origen=origen,
        destino=destino,
        resultados=resultados_finales
    )

if __name__ == "__main__":
    app.run(debug=True)
