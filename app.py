# Archivo: app.py | Versión: Final Estable 15.0 + Filtros Corregidos
from flask import Flask, render_template, request
import pandas as pd
import json
import random
from datetime import datetime, timedelta, time
import pytz

app = Flask(__name__)

# --- Funciones de Ayuda (sin cambios) ---
def get_icon_for_compania(compania, transporte=None):
    compania_str = str(compania).lower()
    if 'emtusa' in compania_str or 'urbano' in compania_str: return '🚍'
    if 'damas' in compania_str: return '🚌'
    if 'renfe' in compania_str: return '🚆'
    if 'coche' in compania_str or 'particular' in compania_str: return '🚗'
    transporte_str = str(transporte).lower()
    if 'tren' in transporte_str: return '🚆'
    if 'bus' in transporte_str: return '🚌'
    return '➡️'

def format_timedelta(td):
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    if hours > 0: return f"{hours}h {minutes}min"
    return f"{minutes}min"

def clean_minutes_column(series):
    def to_minutes(val):
        if pd.isna(val): return 0
        if isinstance(val, (int, float)): return val
        if isinstance(val, str):
            try:
                parts = list(map(int, val.split(':')))
                if len(parts) >= 2: return parts[0] * 60 + parts[1]
            except: return 0
        if isinstance(val, time): return val.hour * 60 + val.minute
        return 0
    return series.apply(to_minutes)

# --- Carga de Datos ---
try:
    rutas_df_global = pd.read_excel("rutas.xlsx", engine="openpyxl")
    rutas_df_global.columns = rutas_df_global.columns.str.strip()
    if 'Compañía' in rutas_df_global.columns:
        rutas_df_global.rename(columns={'Compañía': 'Compania'}, inplace=True)
    
    for col in ['Duracion_Trayecto_Min', 'Frecuencia_Min']:
        if col in rutas_df_global.columns:
            rutas_df_global[col] = clean_minutes_column(rutas_df_global[col])
    if 'Precio' in rutas_df_global.columns:
        rutas_df_global['Precio'] = pd.to_numeric(rutas_df_global['Precio'], errors='coerce').fillna(0)

except Exception as e:
    print(f"ERROR CRÍTICO al cargar 'rutas.xlsx': {e}")
    rutas_df_global = pd.DataFrame()

try:
    with open("frases_motivadoras.json", "r", encoding="utf-8") as f:
        frases = json.load(f)
except Exception:
    frases = ["El esfuerzo de hoy es el éxito de mañana."]

@app.route("/")
def index():
    lugares = []
    if not rutas_df_global.empty:
        lugares = sorted(pd.concat([rutas_df_global["Origen"], rutas_df_global["Destino"]]).dropna().unique())
    frase = random.choice(frases)
    return render_template("index.html", lugares=lugares, frase=frase, frases=frases)

@app.route("/buscar", methods=["POST"])
def buscar():
    origen = request.form["origen"]
    destino = request.form["destino"]
    desde_ahora_check = request.form.get('desde_ahora')
    evitar_sj_check = request.form.get('evitar_sj')
    evitar_pa_check = request.form.get('evitar_pa')

    # --- CORRECCIÓN: Usar los nombres abreviados correctos ---
    lugares_a_evitar = []
    if evitar_sj_check:
        lugares_a_evitar.append("Sta. Justa")
    if evitar_pa_check:
        lugares_a_evitar.append("Plz. Armas")

    # 1. Pre-procesar horarios de rutas fijas
    rutas_fijas = rutas_df_global[rutas_df_global['Tipo_Horario'] == 'Fijo'].copy()
    rutas_fijas.loc[:, 'Salida_dt'] = pd.to_datetime(rutas_fijas['Salida'], format='%H:%M:%S', errors='coerce').dt.to_pydatetime()
    rutas_fijas.loc[:, 'Llegada_dt'] = pd.to_datetime(rutas_fijas['Llegada'], format='%H:%M:%S', errors='coerce').dt.to_pydatetime()
    rutas_fijas.dropna(subset=['Salida_dt', 'Llegada_dt'], inplace=True)

    # 2. Encontrar rutas
    candidatos = find_all_routes_intelligently(origen, destino, rutas_df_global)
    
    # 3. Filtrar las rutas que pasan por lugares a evitar
    if lugares_a_evitar:
        rutas_filtradas = []
        for ruta in candidatos:
            es_ruta_valida = True
            # Revisamos solo los puntos intermedios (no el origen final ni el destino final)
            for i in range(len(ruta) - 1):
                punto_intermedio = ruta[i]['Destino']
                if punto_intermedio in lugares_a_evitar:
                    es_ruta_valida = False
                    break 
            if es_ruta_valida:
                rutas_filtradas.append(ruta)
        candidatos = rutas_filtradas

    # 4. Procesar las rutas válidas
    resultados_procesados = []
    for ruta in candidatos:
        resultado = calculate_route_times(ruta, rutas_fijas, desde_ahora_check)
        if resultado:
            resultados_procesados.append(resultado)
            
    if resultados_procesados:
        resultados_procesados.sort(key=lambda x: x['llegada_final_dt_obj'])

    return render_template("resultado.html", origen=origen, destino=destino, resultados=resultados_procesados)

def find_all_routes_intelligently(origen, destino, df):
    rutas = []
    # 1 tramo
    rutas.extend([[r] for _, r in df[(df['Origen'] == origen) & (df['Destino'] == destino)].iterrows()])
    # 2 tramos
    if not rutas:
        for _, t1 in df[df['Origen'] == origen].iterrows():
            for _, t2 in df[(df['Origen'] == t1['Destino']) & (df['Destino'] == destino)].iterrows():
                rutas.append([t1, t2])
    # 3 tramos
    if not rutas:
        for _, t1 in df[df['Origen'] == origen].iterrows():
            for _, t2 in df[df['Origen'] == t1['Destino']].iterrows():
                if t2['Destino'] in [origen, destino]: continue
                for _, t3 in df[(df['Origen'] == t2['Destino']) & (df['Destino'] == destino)].iterrows():
                    rutas.append([t1, t2, t3])
    return rutas

def calculate_route_times(ruta_series_list, rutas_fijas, desde_ahora_check):
    try:
        segmentos = [s.copy() for s in ruta_series_list]
        TIEMPO_TRANSBORDO = timedelta(minutes=10)
        
        # --- CASO ESPECIAL: RUTA DIRECTA DE FRECUENCIA (COCHE O BUS) ---
        if len(segmentos) == 1 and segmentos[0]['Tipo_Horario'] == 'Frecuencia':
            # Si se marca "desde ahora", no tiene sentido mostrar una ruta sin horario.
            if desde_ahora_check: return None
            seg = segmentos[0]
            duracion = timedelta(minutes=seg['Duracion_Trayecto_Min'])
            seg_dict = seg.to_dict()
            seg_dict['icono'] = get_icon_for_compania(seg.get('Compania'))
            seg_dict['Salida_str'] = "A tu aire"
            seg_dict['Llegada_str'] = ""
            seg_dict['Duracion_Tramo_Min'] = seg['Duracion_Trayecto_Min']
            return {
                "segmentos": [seg_dict], "precio_total": seg.get('Precio', 0),
                "llegada_final_dt_obj": datetime.min, # Para que aparezca siempre primero
                "hora_llegada_final": "Flexible",
                "duracion_total_str": format_timedelta(duracion)
            }

        # --- MOTOR DE CÁLCULO RECONSTRUIDO ---
        anchor_index = -1
        for i, seg in enumerate(segmentos):
            if seg['Tipo_Horario'] == 'Fijo':
                if seg.name in rutas_fijas.index:
                    anchor_index = i
                    break
        
        if anchor_index != -1: # La ruta SÍ tiene un transporte fijo ("ancla")
            anchor_seg = segmentos[anchor_index]
            tramo_fijo_ancla = rutas_fijas.loc[anchor_seg.name]
            
            # Aplicar filtro de hora AHORA, en el ancla
            tz = pytz.timezone('Europe/Madrid')
            ahora = datetime.now(tz).time()
            if desde_ahora_check and tramo_fijo_ancla['Salida_dt'].time() < ahora:
                raise ValueError("La ruta ya ha salido.")

            anchor_seg['Salida_dt'], anchor_seg['Llegada_dt'] = tramo_fijo_ancla['Salida_dt'], tramo_fijo_ancla['Llegada_dt']

            # Calcular hacia atrás desde el ancla
            llegada_siguiente_dt = anchor_seg['Salida_dt']
            for i in range(anchor_index - 1, -1, -1):
                seg = segmentos[i]
                duracion = timedelta(minutes=seg['Duracion_Trayecto_Min'])
                frecuencia = timedelta(minutes=seg['Frecuencia_Min'])
                seg['Llegada_dt'] = llegada_siguiente_dt - TIEMPO_TRANSBORDO - frecuencia
                seg['Salida_dt'] = seg['Llegada_dt'] - duracion
                llegada_siguiente_dt = seg['Salida_dt']

            # Calcular hacia adelante desde el ancla
            llegada_anterior_dt = anchor_seg['Llegada_dt']
            for i in range(anchor_index + 1, len(segmentos)):
                seg = segmentos[i]
                if seg['Tipo_Horario'] == 'Fijo':
                    if seg.name not in rutas_fijas.index: raise ValueError("Fijo no disponible")
                    tramo_fijo = rutas_fijas.loc[seg.name]
                    if tramo_fijo['Salida_dt'] < llegada_anterior_dt + TIEMPO_TRANSBORDO: raise ValueError("Sin tiempo de transbordo")
                    seg['Salida_dt'], seg['Llegada_dt'] = tramo_fijo['Salida_dt'], tramo_fijo['Llegada_dt']
                else: # Frecuencia
                    frecuencia = timedelta(minutes=seg['Frecuencia_Min'])
                    duracion = timedelta(minutes=seg['Duracion_Trayecto_Min'])
                    seg['Salida_dt'] = llegada_anterior_dt + frecuencia
                    seg['Llegada_dt'] = seg['Salida_dt'] + duracion
                llegada_anterior_dt = seg['Llegada_dt']

        else: # La ruta solo tiene transportes de frecuencia
            llegada_anterior_dt = None
            for i, seg in enumerate(segmentos):
                frecuencia = timedelta(minutes=seg['Frecuencia_Min'])
                duracion = timedelta(minutes=seg['Duracion_Trayecto_Min'])
                if i == 0:
                    start_time = datetime.now(pytz.timezone('Europe/Madrid')) if desde_ahora_check else datetime.combine(datetime.today(), time(7,0))
                    llegada_anterior_dt = start_time
                seg['Salida_dt'] = llegada_anterior_dt + frecuencia
                seg['Llegada_dt'] = seg['Salida_dt'] + duracion
                llegada_anterior_dt = seg['Llegada_dt']

        # Formatear y devolver
        segmentos_formateados = []
        for seg in segmentos:
            seg_dict = seg.to_dict()
            seg_dict['icono'] = get_icon_for_compania(seg.get('Compania'))
            seg_dict['Salida_str'] = seg['Salida_dt'].strftime('%H:%M')
            seg_dict['Llegada_str'] = seg['Llegada_dt'].strftime('%H:%M')
            seg_dict['Duracion_Tramo_Min'] = (seg['Llegada_dt'] - seg['Salida_dt']).total_seconds() / 60
            segmentos_formateados.append(seg_dict)

        return {
            "segmentos": segmentos_formateados,
            "precio_total": sum(s.get('Precio', 0) for s in ruta_series_list),
            "llegada_final_dt_obj": segmentos[-1]['Llegada_dt'],
            "hora_llegada_final": segmentos[-1]['Llegada_dt'].time(),
            "duracion_total_str": format_timedelta(segmentos[-1]['Llegada_dt'] - segmentos[0]['Salida_dt'])
        }
    except Exception as e:
        return None

if __name__ == "__main__":
    app.run(debug=True)

