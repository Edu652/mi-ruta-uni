from flask import Flask, render_template, request
import pandas as pd
import json
import random
from datetime import datetime, timedelta

app = Flask(__name__)

# --- Carga de Datos ---
# Leemos el archivo Excel.
try:
    rutas_df = pd.read_excel("rutas.xlsx", engine="openpyxl")
    
    # Convertimos las columnas de hora a objetos de tiempo.
    # Usamos `errors='coerce'` para que cualquier valor que no se pueda convertir
    # se transforme en 'NaT' (Not a Time), en lugar de causar un error.
    rutas_df["Salida"] = pd.to_datetime(rutas_df["Salida"], format='%H:%M', errors='coerce').dt.time
    rutas_df["Llegada"] = pd.to_datetime(rutas_df["Llegada"], format='%H:%M', errors='coerce').dt.time

    # --- ¡NUEVO PASO IMPORTANTE! ---
    # Eliminamos cualquier fila donde la conversión de hora haya fallado.
    # Esto limpia los datos y evita que la app se detenga por un error en el Excel.
    filas_originales = len(rutas_df)
    rutas_df.dropna(subset=['Salida', 'Llegada'], inplace=True)
    filas_limpias = len(rutas_df)
    
    if filas_originales > filas_limpias:
        print(f"ADVERTENCIA: Se eliminaron {filas_originales - filas_limpias} filas de 'rutas.xlsx' por tener un formato de hora incorrecto.")

except FileNotFoundError:
    print("Error: El archivo 'rutas.xlsx' no se encontró. Asegúrate de que está en la misma carpeta.")
    rutas_df = pd.DataFrame(columns=["Origen", "Destino", "Salida", "Llegada", "Precio", "Compania"])
except Exception as e:
    print(f"Ocurrió un error inesperado al cargar 'rutas.xlsx': {e}")
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
        rutas_validas.append([ruta.to_dict()])

    # --- 2. BÚSQUEDA DE RUTAS CON 1 TRANSBORDO ---
    TIEMPO_MINIMO_TRANSBORDO = timedelta(minutes=15)
    posibles_primeros_tramos = rutas_df[rutas_df["Origen"] == origen]

    for _, tramo1 in posibles_primeros_tramos.iterrows():
        punto_intermedio = tramo1["Destino"]
        
        if punto_intermedio == destino:
            continue

        posibles_segundos_tramos = rutas_df[(rutas_df["Origen"] == punto_intermedio) & (rutas_df["Destino"] == destino)]

        for _, tramo2 in posibles_segundos_tramos.iterrows():
            hora_llegada_tramo1 = datetime.combine(datetime.today(), tramo1["Llegada"])
            hora_salida_tramo2 = datetime.combine(datetime.today(), tramo2["Salida"])

            if hora_salida_tramo2 >= (hora_llegada_tramo1 + TIEMPO_MINIMO_TRANSBORDO):
                rutas_validas.append([tramo1.to_dict(), tramo2.to_dict()])

    # --- 3. PROCESAR Y ORDENAR LAS RUTAS ENCONTRADAS ---
    resultados_finales = []
    for ruta in rutas_validas:
        precio_total = sum(segmento["Precio"] for segmento in ruta)
        
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
