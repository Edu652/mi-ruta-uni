# Versión: 2.1 (Lógica de búsqueda reconstruida para corregir TypeError)
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
    if compania_str not in ['nan', 'none', '']: return '➡️'
    return ''

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
    return render_template("index.html", lugares=lugares, frase=frase)

@app.route("/buscar", methods=["POST"])
def buscar():
    origen = request.form["origen"]
    destino = request.form["destino"]
    desde_ahora_check = request.form.get('desde_ahora')

    # 1. Pre-procesar horarios de rutas fijas
    rutas_fijas = rutas_df_global[rutas_df_global['Tipo_Horario'] == 'Fijo'].copy()
    rutas_fijas.loc[:, 'Salida_dt'] = pd.to_datetime(rutas_fijas['Salida'], format='%H:%M:%S', errors='coerce').dt.to_pydatetime()
    rutas_fijas.loc[:, 'Llegada_dt'] = pd.to_datetime(rutas_fijas['Llegada'], format='%H:%M:%S', errors='coerce').dt.to_pydatetime()
    rutas_fijas.dropna(subset=['Salida_dt', 'Llegada_dt'], inplace=True)

    if desde_ahora_check:
        tz = pytz.timezone('Europe/Madrid')
        ahora = datetime.now(tz).time()
        rutas_fijas = rutas_fijas[rutas_fijas['Salida_dt'].apply(lambda x: x.time()) >= ahora]

    # 2. Encontrar todas las combinaciones posibles de rutas (candidatos)
    candidatos = []
    # 1 tramo
    for _, tramo in rutas_df_global[(rutas_df_global['Origen'] == origen) & (rutas_df_global['Destino'] == destino)].iterrows():
        candidatos.append([tramo])
    # 2 tramos
    for _, tramo1 in rutas_df_global[rutas_df_global['Origen'] == origen].iterrows():
        for _, tramo2 in rutas_df_global[(rutas_df_global['Origen'] == tramo1['Destino']) & (rutas_df_global['Destino'] == destino)].iterrows():
            candidatos.append([tramo1, tramo2])
    # 3 tramos
    for _, tramo1 in rutas_df_global[rutas_df_global['Origen'] == origen].iterrows():
        for _, tramo2 in rutas_df_global[rutas_df_global['Origen'] == tramo1['Destino']].iterrows():
            if tramo2['Destino'] in [origen, destino]: continue
            for _, tramo3 in rutas_df_global[(rutas_df_global['Origen'] == tramo2['Destino']) & (rutas_df_global['Destino'] == destino)].iterrows():
                candidatos.append([tramo1, tramo2, tramo3])
    # 4 tramos
    for _, tramo1 in rutas_df_global[rutas_df_global['Origen'] == origen].iterrows():
        for _, tramo2 in rutas_df_global[rutas_df_global['Origen'] == tramo1['Destino']].iterrows():
            if tramo2['Destino'] in [origen, destino]: continue
            for _, tramo3 in rutas_df_global[rutas_df_global['Origen'] == tramo2['Destino']].iterrows():
                if tramo3['Destino'] in [origen, destino]: continue
                for _, tramo4 in rutas_df_global[(rutas_df_global['Origen'] == tramo3['Destino']) & (rutas_df_global['Destino'] == destino)].iterrows():
                    candidatos.append([tramo1, tramo2, tramo3, tramo4])
    
    # 3. Validar y procesar cada candidato
    resultados_procesados = []
    for ruta in candidatos:
        try:
            segmentos, llegada_anterior_dt = [], None
            TIEMPO_TRANSBORDO = timedelta(minutes=10)
            
            for i, seg_raw in enumerate(ruta):
                seg = seg_raw.copy()
                
                # --- Lógica de cálculo reconstruida ---
                if 'coche' in str(seg['Compania']).lower() and i == 0 and len(ruta) > 1:
                    siguiente_tramo = ruta[i+1]
                    if siguiente_tramo['Tipo_Horario'] != 'Fijo' or siguiente_tramo.name not in rutas_fijas.index:
                        raise ValueError("Coche debe conectar con transporte de horario fijo.")
                    siguiente_tramo_fijo = rutas_fijas.loc[siguiente_tramo.name]
                    duracion_coche = timedelta(minutes=seg['Duracion_Trayecto_Min'])
                    seg['Llegada_dt'] = siguiente_tramo_fijo['Salida_dt']
                    seg['Salida_dt'] = seg['Llegada_dt'] - duracion_coche
                elif seg['Tipo_Horario'] == 'Fijo':
                    if seg.name not in rutas_fijas.index: raise ValueError("Horario fijo no disponible.")
                    tramo_fijo = rutas_fijas.loc[seg.name]
                    if i > 0 and tramo_fijo['Salida_dt'] < llegada_anterior_dt + TIEMPO_TRANSBORDO:
                        raise ValueError("No hay tiempo para transbordo a transporte fijo.")
                    seg['Salida_dt'], seg['Llegada_dt'] = tramo_fijo['Salida_dt'], tramo_fijo['Llegada_dt']
                else: # Bus Urbano o Coche al final
                    frecuencia = timedelta(minutes=seg['Frecuencia_Min'])
                    duracion = timedelta(minutes=seg['Duracion_Trayecto_Min'])
                    if i == 0:
                        start_time = datetime.now(pytz.timezone('Europe/Madrid')) if desde_ahora_check else datetime.combine(datetime.today(), time(7,0))
                        llegada_anterior_dt = start_time
                    
                    seg['Salida_dt'] = llegada_anterior_dt + frecuencia
                    seg['Llegada_dt'] = seg['Salida_dt'] + duracion

                if llegada_anterior_dt and seg['Salida_dt'] < llegada_anterior_dt:
                    seg['Salida_dt'] += timedelta(days=1); seg['Llegada_dt'] += timedelta(days=1)
                
                llegada_anterior_dt = seg['Llegada_dt']
                segmentos.append(seg)
            
            segmentos_formateados = []
            for seg in segmentos:
                seg_dict = seg.to_dict()
                seg_dict['icono'] = get_icon_for_compania(seg.get('Compania'))
                seg_dict['Salida_str'] = seg['Salida_dt'].strftime('%H:%M')
                seg_dict['Llegada_str'] = seg['Llegada_dt'].strftime('%H:%M')
                seg_dict['Duracion_Tramo_Min'] = (seg['Llegada_dt'] - seg['Salida_dt']).total_seconds() / 60
                segmentos_formateados.append(seg_dict)

            resultados_procesados.append({
                "segmentos": segmentos_formateados,
                "precio_total": sum(s.get('Precio', 0) for s in ruta),
                "llegada_final_dt_obj": segmentos[-1]['Llegada_dt'],
                "hora_llegada_final": segmentos[-1]['Llegada_dt'].time(),
                "duracion_total_str": format_timedelta(segmentos[-1]['Llegada_dt'] - segmentos[0]['Salida_dt'])
            })
        except Exception as e:
            # print(f"Ruta descartada: {[s['Origen'] for s in ruta]} -> {e}")
            pass
            
    if resultados_procesados:
        resultados_procesados.sort(key=lambda x: x['llegada_final_dt_obj'])

    return render_template("resultado.html", origen=origen, destino=destino, resultados=resultados_procesados)

if __name__ == "__main__":
    app.run(debug=True)

