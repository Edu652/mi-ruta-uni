from flask import Flask, render_template, request
import pandas as pd
import json
import random
from datetime import datetime, timedelta

app = Flask(__name__)

# --- Helper Functions ---
def get_icon_for_compania(compania):
    """Devuelve un emoji basado en el nombre de la compañía."""
    compania_lower = str(compania).lower()
    if 'urbano' in compania_lower:
        return '🚍'
    if 'damas' in compania_lower:
        return '🚌'
    if 'renfe' in compania_lower or 'tren' in compania_lower:
        return '🚆'
    return '➡️'

def format_timedelta(td):
    """Formatea un timedelta a un string legible como '1h 30min'."""
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}min"
    return f"{minutes}min"

# --- Carga de Datos y Limpieza ---
try:
    rutas_df_raw = pd.read_excel("rutas.xlsx", engine="openpyxl")
    # MEJORA: Limpiar nombres de columnas de espacios extra
    rutas_df_raw.columns = rutas_df_raw.columns.str.strip()

    # Separar los dataframes para procesarlos correctamente
    fijos_df = rutas_df_raw[rutas_df_raw['Tipo_Horario'] == 'Fijo'].copy()
    frecuencia_df = rutas_df_raw[rutas_df_raw['Tipo_Horario'] == 'Frecuencia'].copy()

    # --- Procesar Rutas de Horario FIJO ---
    if not fijos_df.empty:
        fijos_df['Salida_dt'] = pd.to_datetime(fijos_df['Salida'], format='%H:%M:%S', errors='coerce')
        fijos_df['Llegada_dt'] = pd.to_datetime(fijos_df['Llegada'], format='%H:%M:%S', errors='coerce')
        fijos_df.dropna(subset=['Salida_dt', 'Llegada_dt'], inplace=True)
        
        # MEJORA: Manejar viajes que cruzan la medianoche
        overnight_mask = fijos_df['Llegada_dt'] < fijos_df['Salida_dt']
        fijos_df.loc[overnight_mask, 'Llegada_dt'] += timedelta(days=1)

        fijos_df['Duracion_Tramo_Min'] = (fijos_df['Llegada_dt'] - fijos_df['Salida_dt']).dt.total_seconds() / 60
        fijos_df['Salida'] = fijos_df['Salida_dt'].dt.time
        fijos_df['Llegada'] = fijos_df['Llegada_dt'].dt.time
        fijos_df['Precio'] = pd.to_numeric(fijos_df['Precio'], errors='coerce').fillna(0)

    # --- Procesar Rutas de FRECUENCIA ---
    if not frecuencia_df.empty:
        frecuencia_df['Frecuencia_Min'] = pd.to_numeric(frecuencia_df['Frecuencia_Min'], errors='coerce').fillna(0)
        frecuencia_df['Duracion_Trayecto_Min'] = pd.to_numeric(frecuencia_df['Duracion_Trayecto_Min'], errors='coerce').fillna(0)
        frecuencia_df['Precio'] = pd.to_numeric(frecuencia_df['Precio'], errors='coerce').fillna(0)

    # Unir de nuevo los dataframes procesados
    rutas_df = pd.concat([fijos_df, frecuencia_df], ignore_index=True)

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
    try:
        if not rutas_df.empty and 'Origen' in rutas_df.columns and 'Destino' in rutas_df.columns:
            lugares = sorted(pd.concat([rutas_df["Origen"], rutas_df["Destino"]]).dropna().unique())
        else:
            print("ADVERTENCIA: No se pudieron cargar los lugares. Revisa el Excel y los nombres de las columnas.")
    except Exception as e:
        print(f"ERROR al procesar los lugares para los desplegables: {e}")
    
    frase = random.choice(frases)
    return render_template("index.html", lugares=lugares, frase=frase)

@app.route("/buscar", methods=["POST"])
def buscar():
    origen = request.form["origen"]
    destino = request.form["destino"]
    resultados_finales = []
    
    # 1. Rutas Directas (Fijo)
    directas = rutas_df[(rutas_df["Origen"] == origen) & (rutas_df["Destino"] == destino) & (rutas_df['Tipo_Horario'] == 'Fijo')]
    for _, ruta in directas.iterrows():
        ruta_dict = ruta.to_dict()
        ruta_dict['Salida_str'] = ruta['Salida'].strftime('%H:%M')
        ruta_dict['Llegada_str'] = ruta['Llegada'].strftime('%H:%M')
        ruta_dict['icono'] = get_icon_for_compania(ruta.get('Compania'))
        duracion_total = timedelta(minutes=ruta.get('Duracion_Tramo_Min', 0))
        
        resultados_finales.append({
            "segmentos": [ruta_dict],
            "precio_total": ruta['Precio'],
            "hora_llegada_final": ruta['Llegada'],
            "tipo": "Directo",
            "duracion_total_str": format_timedelta(duracion_total)
        })

    # 2. Rutas con Transbordo
    TIEMPO_MINIMO_TRANSBORDO = timedelta(minutes=10)
    posibles_primeros_tramos = rutas_df[(rutas_df["Origen"] == origen) & (rutas_df['Tipo_Horario'] == 'Fijo')]
    
    for _, tramo1 in posibles_primeros_tramos.iterrows():
        punto_intermedio = tramo1["Destino"]
        posibles_segundos_tramos = rutas_df[(rutas_df["Origen"] == punto_intermedio) & (rutas_df["Destino"] == destino)]
        
        for _, tramo2 in posibles_segundos_tramos.iterrows():
            hora_llegada_tramo1_dt = datetime.combine(datetime.today(), tramo1["Llegada"])
            hora_salida_inicial_dt = datetime.combine(datetime.today(), tramo1["Salida"])

            # --- NUEVA LÓGICA: Transbordo Fijo -> Fijo ---
            if tramo2["Tipo_Horario"] == 'Fijo':
                hora_salida_tramo2_dt = datetime.combine(datetime.today(), tramo2["Salida"])
                if hora_salida_tramo2_dt >= hora_llegada_tramo1_dt + TIEMPO_MINIMO_TRANSBORDO:
                    tramo1_dict = tramo1.to_dict()
                    tramo1_dict.update({'Salida_str': tramo1['Salida'].strftime('%H:%M'), 'Llegada_str': tramo1['Llegada'].strftime('%H:%M'), 'icono': get_icon_for_compania(tramo1.get('Compania'))})
                    
                    tramo2_dict = tramo2.to_dict()
                    tramo2_dict.update({'Salida_str': tramo2['Salida'].strftime('%H:%M'), 'Llegada_str': tramo2['Llegada'].strftime('%H:%M'), 'icono': get_icon_for_compania(tramo2.get('Compania'))})

                    hora_llegada_final_dt = datetime.combine(datetime.today(), tramo2["Llegada"])
                    if hora_llegada_final_dt < hora_salida_inicial_dt: hora_llegada_final_dt += timedelta(days=1)
                    duracion_total = hora_llegada_final_dt - hora_salida_inicial_dt

                    resultados_finales.append({
                        "segmentos": [tramo1_dict, tramo2_dict],
                        "precio_total": tramo1['Precio'] + tramo2['Precio'],
                        "hora_llegada_final": tramo2['Llegada'], "tipo": "Transbordo",
                        "duracion_total_str": format_timedelta(duracion_total)})

            # --- Lógica: Transbordo Fijo -> Frecuencia ---
            elif tramo2["Tipo_Horario"] == 'Frecuencia':
                espera = timedelta(minutes=tramo2.get('Frecuencia_Min', 0))
                duracion_tramo2 = timedelta(minutes=tramo2.get('Duracion_Trayecto_Min', 0))
                hora_llegada_final_dt = hora_llegada_tramo1_dt + TIEMPO_MINIMO_TRANSBORDO + espera + duracion_tramo2
                if hora_llegada_final_dt < hora_salida_inicial_dt: hora_llegada_final_dt += timedelta(days=1)
                
                tramo1_dict = tramo1.to_dict()
                tramo1_dict.update({'Salida_str': tramo1['Salida'].strftime('%H:%M'), 'Llegada_str': tramo1['Llegada'].strftime('%H:%M'), 'icono': get_icon_for_compania(tramo1.get('Compania'))})
                
                tramo2_dict = tramo2.to_dict()
                tramo2_dict.update({
                    'Salida_str': (hora_llegada_tramo1_dt + TIEMPO_MINIMO_TRANSBORDO).strftime('%H:%M'),
                    'Llegada_str': hora_llegada_final_dt.strftime('%H:%M'),
                    'icono': get_icon_for_compania(tramo2.get('Compania')),
                    'Duracion_Tramo_Min': tramo2.get('Duracion_Trayecto_Min', 0)})

                duracion_total = hora_llegada_final_dt - hora_salida_inicial_dt
                
                resultados_finales.append({
                    "segmentos": [tramo1_dict, tramo2_dict],
                    "precio_total": tramo1['Precio'] + tramo2['Precio'],
                    "hora_llegada_final": hora_llegada_final_dt.time(), "tipo": "Transbordo (Bus Urbano)",
                    "duracion_total_str": format_timedelta(duracion_total)})
    
    if resultados_finales:
        resultados_finales.sort(key=lambda x: x["hora_llegada_final"])

    return render_template("resultado.html", origen=origen, destino=destino, resultados=resultados_finales)

if __name__ == "__main__":
    app.run(debug=True)

