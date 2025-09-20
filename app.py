from flask import Flask, render_template, request
import pandas as pd
import json
import random
from datetime import datetime, timedelta

app = Flask(__name__)

# --- Carga y DEPURACIÓN de Datos ---
print("--- INICIANDO CARGA DE DATOS ---")
try:
    # Leemos el archivo Excel. Forzamos que todo se lea como texto para poder inspeccionarlo.
    rutas_df = pd.read_excel("rutas.xlsx", engine="openpyxl", dtype=str)
    
    print("\n[DEBUG] 1. PRIMERAS 5 FILAS DEL EXCEL (leídas como texto):")
    print(rutas_df.head().to_string())
    print("\n[DEBUG] 2. NOMBRES DE LAS COLUMNAS DETECTADAS:")
    print(rutas_df.columns.tolist())

    # Hacemos una copia de las columnas de hora originales para depurar
    rutas_df['Salida_original'] = rutas_df['Salida']
    rutas_df['Llegada_original'] = rutas_df['Llegada']

    # Convertimos las columnas de hora a objetos de tiempo.
    rutas_df["Salida"] = pd.to_datetime(rutas_df["Salida"], format='%H:%M', errors='coerce').dt.time
    rutas_df["Llegada"] = pd.to_datetime(rutas_df["Llegada"], format='%H:%M', errors='coerce').dt.time

    print("\n[DEBUG] 3. DATAFRAME DESPUÉS DEL INTENTO DE CONVERSIÓN DE HORA:")
    print(rutas_df[['Salida_original', 'Salida', 'Llegada_original', 'Llegada']].head().to_string())

    # Eliminamos cualquier fila donde la conversión de hora haya fallado.
    filas_originales = len(rutas_df)
    rutas_df.dropna(subset=['Salida', 'Llegada'], inplace=True)
    filas_limpias = len(rutas_df)
    
    print(f"\n[DEBUG] 4. RESULTADO DE LA LIMPIEZA:")
    print(f"   - Filas originales leídas: {filas_originales}")
    print(f"   - Filas válidas después de limpiar horas: {filas_limpias}")
    
    if filas_limpias > 0:
        print("\n[DEBUG] 5. PRIMERAS 5 FILAS VÁLIDAS (listas para usar):")
        print(rutas_df.head().to_string())
    else:
        print("\n[DEBUG] 5. ADVERTENCIA: No quedó ninguna fila válida después de la limpieza.")


except FileNotFoundError:
    print("ERROR CRÍTICO: El archivo 'rutas.xlsx' no se encontró. Asegúrate de que está en la raíz del proyecto.")
    rutas_df = pd.DataFrame(columns=["Origen", "Destino", "Salida", "Llegada", "Precio", "Compania"])
except KeyError as e:
    print(f"ERROR CRÍTICO: No se encontró una columna necesaria. ¿Falta la columna {e} en tu archivo Excel?")
    rutas_df = pd.DataFrame(columns=["Origen", "Destino", "Salida", "Llegada", "Precio", "Compania"])
except Exception as e:
    print(f"ERROR CRÍTICO: Ocurrió un error inesperado al cargar 'rutas.xlsx': {e}")
    rutas_df = pd.DataFrame(columns=["Origen", "Destino", "Salida", "Llegada", "Precio", "Compania"])

print("\n--- CARGA DE DATOS FINALIZADA ---\n")


# Cargamos las frases motivadoras
try:
    with open("frases_motivadoras.json", "r", encoding="utf-8") as f:
        frases = json.load(f)
except FileNotFoundError:
    frases = ["El éxito es la suma de pequeños esfuerzos repetidos día tras día."]


@app.route("/")
def index():
    if not rutas_df.empty:
        lugares = sorted(set(rutas_df["Origen"]).union(set(rutas_df["Destino"])))
    else:
        lugares = [] 
    frase = random.choice(frases)
    # No cambies el index.html, el que tienes ya funciona con esta lista de frases.
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
        precio_total = sum(pd.to_numeric(s["Precio"], errors='coerce') for s in ruta)
        
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
        resultados_finales.sort(key=lambda x: (x["hora_llegada_final"], x["precio_total"]))

    return render_template("resultado.html", origen=origen, destino=destino, resultados=resultados_finales)

if __name__ == "__main__":
    app.run(debug=True)

