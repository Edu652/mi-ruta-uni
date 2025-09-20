from flask import Flask, render_template, request
import pandas as pd
import json
import random
from datetime import datetime, timedelta

app = Flask(__name__)

# --- Carga de Datos Inteligente ---
try:
    rutas_df = pd.read_excel("rutas.xlsx", engine="openpyxl")

    # Procesamos solo las filas con horario FIJO
    fijos_mask = rutas_df['Tipo_Horario'] == 'Fijo'
    rutas_df.loc[fijos_mask, "Salida"] = pd.to_datetime(rutas_df.loc[fijos_mask, "Salida"], format='%H:%M:%S', errors='coerce').dt.time
    rutas_df.loc[fijos_mask, "Llegada"] = pd.to_datetime(rutas_df.loc[fijos_mask, "Llegada"], format='%H:%M:%S', errors='coerce').dt.time
    
    # Nos aseguramos de que las columnas numéricas sean números, tratando errores.
    rutas_df['Frecuencia_Min'] = pd.to_numeric(rutas_df['Frecuencia_Min'], errors='coerce')
    rutas_df['Duracion_Trayecto_Min'] = pd.to_numeric(rutas_df['Duracion_Trayecto_Min'], errors='coerce')
    rutas_df['Precio'] = pd.to_numeric(rutas_df['Precio'], errors='coerce').fillna(0)


except Exception as e:
    print(f"ERROR CRÍTICO al cargar 'rutas.xlsx': {e}")
    rutas_df = pd.DataFrame()

# Cargamos las frases
try:
    with open("frases_motivadoras.json", "r", encoding="utf-8") as f:
        frases = json.load(f)
except:
    frases = ["El esfuerzo de hoy es el éxito de mañana."]

@app.route("/")
def index():
    lugares = []
    # ----> ¡NUEVO BLOQUE A PRUEBA DE ERRORES! <----
    try:
        if not rutas_df.empty:
            # Comprobamos que las columnas 'Origen' y 'Destino' existen
            if 'Origen' in rutas_df.columns and 'Destino' in rutas_df.columns:
                lugares = sorted(pd.concat([rutas_df["Origen"], rutas_df["Destino"]]).dropna().unique())
            else:
                print("ERROR: Faltan las columnas 'Origen' y/o 'Destino' en el Excel.")
    except Exception as e:
        print(f"ERROR al procesar los lugares para los desplegables: {e}")

    frase = random.choice(frases)
    return render_template("index.html", lugares=lugares, frase=frase)


@app.route("/buscar", methods=["POST"])
def buscar():
    origen = request.form["origen"]
    destino = request.form["destino"]
    resultados_finales = []
    
    # --- Lógica de Búsqueda Mejorada ---
    
    # 1. Rutas Directas (solo pueden ser de tipo 'Fijo')
    directas = rutas_df[(rutas_df["Origen"] == origen) & (rutas_df["Destino"] == destino) & (rutas_df['Tipo_Horario'] == 'Fijo')]
    for _, ruta in directas.iterrows():
        ruta_dict = ruta.to_dict()
        ruta_dict['Salida_str'] = ruta['Salida'].strftime('%H:%M')
        ruta_dict['Llegada_str'] = ruta['Llegada'].strftime('%H:%M')
        resultados_finales.append({
            "segmentos": [ruta_dict],
            "precio_total": ruta['Precio'],
            "hora_llegada_final": ruta['Llegada'],
            "tipo": "Directo"
        })

    # 2. Rutas con Transbordo (A -> B (Fijo) -> C (Frecuencia))
    TIEMPO_MINIMO_TRANSBORDO = timedelta(minutes=10)
    posibles_primeros_tramos = rutas_df[(rutas_df["Origen"] == origen) & (rutas_df['Tipo_Horario'] == 'Fijo')]
    
    for _, tramo1 in posibles_primeros_tramos.iterrows():
        punto_intermedio = tramo1["Destino"]
        posibles_segundos_tramos = rutas_df[(rutas_df["Origen"] == punto_intermedio) & (rutas_df["Destino"] == destino)]
        
        for _, tramo2 in posibles_segundos_tramos.iterrows():
            hora_llegada_tramo1 = datetime.combine(datetime.today(), tramo1["Llegada"])
            
            # Si el segundo tramo es de frecuencia, aplicamos la nueva lógica
            if tramo2["Tipo_Horario"] == 'Frecuencia':
                # Estimamos el tiempo de espera + viaje
                # Llegada_bus_anterior + tiempo_caminar + espera_maxima + duracion_viaje
                espera_estimada = timedelta(minutes=tramo2['Frecuencia_Min'])
                duracion_viaje = timedelta(minutes=tramo2['Duracion_Trayecto_Min'])
                hora_llegada_final_dt = hora_llegada_tramo1 + TIEMPO_MINIMO_TRANSBORDO + espera_estimada + duracion_viaje
                
                tramo1_dict = tramo1.to_dict()
                tramo1_dict['Salida_str'] = tramo1['Salida'].strftime('%H:%M')
                tramo1_dict['Llegada_str'] = tramo1['Llegada'].strftime('%H:%M')
                
                tramo2_dict = tramo2.to_dict()
                # Para la vista, podemos estimar una hora de "salida"
                tramo2_dict['Salida_str'] = (hora_llegada_tramo1 + TIEMPO_MINIMO_TRANSBORDO).strftime('%H:%M')
                tramo2_dict['Llegada_str'] = hora_llegada_final_dt.strftime('%H:%M')

                resultados_finales.append({
                    "segmentos": [tramo1_dict, tramo2_dict],
                    "precio_total": tramo1['Precio'] + tramo2['Precio'],
                    "hora_llegada_final": hora_llegada_final_dt.time(),
                    "tipo": "Transbordo (Bus Urbano)"
                })
    
    if resultados_finales:
        resultados_finales.sort(key=lambda x: x["hora_llegada_final"])

    return render_template("resultado.html", origen=origen, destino=destino, resultados=resultados_finales)

if __name__ == "__main__":
    app.run(debug=True)
