# Archivo app.py FINAL Y COMPLETO (01/10/2025) - Versión con Límite de Tiempo
from flask import Flask, render_template, request
import pandas as pd
import json
import random
from datetime import datetime, timedelta, time
import pytz
import requests
import io
from collections import defaultdict
import time as timer # Importamos la librería de tiempo

app = Flask(__name__)

# --- CONFIGURACIÓN DE LA FUENTE DE DATOS ---
GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1QConknaQ2O762EV3701kPtu2zsJBkYW6/export?format=csv&gid=151783393"

# --- Funciones de Ayuda ---
def get_icon_for_compania(compania, transporte=None):
    compania_str = str(compania).lower()
    if 'emtusa' in compania_str or 'urbano' in compania_str: return '🚍'
    if 'damas' in compania_str: return '🚌'
    if 'renfe' in compania_str: return '🚆'
    if 'consorcio' in compania_str: return 'LOGO_CONSORCIO'
    if 'coche' in compania_str or 'particular' in compania_str: return '🚗'
    transporte_str = str(transporte).lower()
    if 'tren' in transporte_str: return '🚆'
    if 'bus' in transporte_str: return '🚌'
    return '➡️'

def format_timedelta(td):
    if td is None or pd.isna(td): return "N/A"
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    if hours > 0: return f"{hours}h {minutes}min"
    return f"{minutes}min"

def clean_minutes_column(series):
    def to_minutes(val):
        if pd.isna(val) or val == '': return 0
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
    headers = {"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache"}
    response = requests.get(GOOGLE_SHEET_URL, headers=headers, timeout=15)
    response.raise_for_status()
    response.encoding = 'utf-8'
    csv_content = response.text
    csv_data_io = io.StringIO(csv_content)
    rutas_df_global = pd.read_csv(csv_data_io)

    column_mapping = {'Parada': 'Parada_Origen', 'Parada.1': 'Parada_Destino'}
    rutas_df_global.rename(columns=column_mapping, inplace=True)
    
    rutas_df_global.columns = rutas_df_global.columns.str.strip()
    if 'Compañía' in rutas_df_global.columns:
        rutas_df_global.rename(columns={'Compañía': 'Compania'}, inplace=True)
    
    for col in ['Duracion_Trayecto_Min', 'Frecuencia_Min']:
        if col in rutas_df_global.columns:
            rutas_df_global[col] = clean_minutes_column(rutas_df_global[col])
        else:
            rutas_df_global[col] = 0

    if 'Precio' in rutas_df_global.columns:
        rutas_df_global['Precio'] = pd.to_numeric(rutas_df_global['Precio'], errors='coerce').fillna(0)
    else:
        rutas_df_global['Precio'] = 0.0

except Exception as e:
    print(f"--- ERROR CRÍTICO EN CARGA DE DATOS: {e} ---")
    rutas_df_global = pd.DataFrame()

# --- Carga de frases motivadoras ---
try:
    with open("frases_motivadoras.json", "r", encoding="utf-8") as f:
        frases = json.load(f)
except Exception:
    frases = ["El esfuerzo de hoy es el éxito de mañana."]

# --- Rutas de la Aplicación ---
@app.route("/")
def index():
    lugares = []
    if not rutas_df_global.empty:
        lugares = sorted(pd.concat([rutas_df_global["Origen"], rutas_df_global["Destino"]]).dropna().unique())
    frase = random.choice(frases)
    return render_template("index.html", lugares=lugares, frase=frase, frases=frases)

@app.route("/buscar", methods=["POST"])
def buscar():
    start_time = timer.time() 
    TIME_LIMIT = 25.0 

    form_data = request.form.to_dict()
    origen = form_data.get("origen")
    destino = form_data.get("destino")
    
    tz = pytz.timezone('Europe/Madrid')
    now = datetime.now(tz)
    dia_seleccionado = form_data.get('dia_semana_selector', 'hoy')

    if dia_seleccionado != 'hoy':
        try: target_weekday = int(dia_seleccionado)
        except: target_weekday = now.weekday()
    else:
        target_weekday = now.weekday()

    dias_semana_map = {0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves", 4: "Viernes", 5: "Sábado", 6: "Domingo"}
    nombre_dia = dias_semana_map[target_weekday]

    rutas_hoy_df = rutas_df_global.copy()
    if 'Dias' in rutas_hoy_df.columns:
        rutas_hoy_df['Dias'] = rutas_hoy_df['Dias'].fillna('L-D').str.strip()
        is_weekday = target_weekday < 5
        is_saturday = target_weekday == 5
        is_sunday = target_weekday == 6
        mask = (rutas_hoy_df['Dias'] == 'L-D') | (is_weekday & (rutas_hoy_df['Dias'] == 'L-V')) | ((is_saturday or is_sunday) & (rutas_hoy_df['Dias'] == 'S-D')) | (is_saturday & (rutas_hoy_df['Dias'] == 'S')) | (is_sunday & (rutas_hoy_df['Dias'] == 'D'))
        rutas_hoy_df = rutas_hoy_df[mask]
    
    rutas_fijas_df = rutas_hoy_df[rutas_hoy_df['Tipo_Horario'] == 'Fijo'].copy()
    if not rutas_fijas_df.empty:
        today_date = now.date()
        salida_times = pd.to_datetime(rutas_fijas_df['Salida'], format='%H:%M', errors='coerce').dt.time
        llegada_times = pd.to_datetime(rutas_fijas_df['Llegada'], format='%H:%M', errors='coerce').dt.time
        rutas_fijas_df['Salida_dt'] = salida_times.apply(lambda t: datetime.combine(today_date, t) if pd.notna(t) else pd.NaT)
        rutas_fijas_df['Llegada_dt'] = llegada_times.apply(lambda t: datetime.combine(today_date, t) if pd.notna(t) else pd.NaT)
        rutas_fijas_df.dropna(subset=['Salida_dt', 'Llegada_dt'], inplace=True)

    candidatos_plantilla = find_all_routes_intelligently(origen, destino, rutas_hoy_df)
    
    candidatos_expandidos = []
    search_incomplete = False 

    if candidatos_plantilla:
        for ruta_plantilla in candidatos_plantilla:
            if timer.time() - start_time > TIME_LIMIT:
                search_incomplete = True
                break 

            if all(s.get('Tipo_Horario') == 'Frecuencia' for s in ruta_plantilla):
                candidatos_expandidos.append(ruta_plantilla)
                continue
            indices_fijos = [i for i, seg in enumerate(ruta_plantilla) if seg.get('Tipo_Horario') == 'Fijo']
            if not indices_fijos: continue
            
            idx_ancla = indices_fijos[0]
            ancla_plantilla = ruta_plantilla[idx_ancla]
            
            mask = (rutas_fijas_df['Origen'] == ancla_plantilla.get('Origen')) & (rutas_fijas_df['Destino'] == ancla_plantilla.get('Destino'))
            if pd.notna(ancla_plantilla.get('Compania')): mask &= (rutas_fijas_df['Compania'] == ancla_plantilla.get('Compania'))
            if pd.notna(ancla_plantilla.get('Transporte')): mask &= (rutas_fijas_df['Transporte'] == ancla_plantilla.get('Transporte'))
            
            posibles_anclas = rutas_fijas_df[mask]
            for _, ancla_real in posibles_anclas.iterrows():
                nueva_ruta = list(ruta_plantilla)
                nueva_ruta[idx_ancla] = ancla_real
                candidatos_expandidos.append(nueva_ruta)
    
    resultados_procesados = []
    for ruta in candidatos_expandidos:
        if timer.time() - start_time > TIME_LIMIT:
            search_incomplete = True
            break

        is_desde_ahora = form_data.get('desde_ahora') and dia_seleccionado == 'hoy'
        resultado = calculate_route_times(ruta, is_desde_ahora)
        if resultado: resultados_procesados.append(resultado)
    
    if form_data.get('desde_ahora') and dia_seleccionado == 'hoy':
        ahora = datetime.now(tz)
        resultados_procesados = [r for r in resultados_procesados if r['hora_llegada_final'] == 'Flexible' or (r['segmentos'] and 'Salida_dt' in r['segmentos'][0] and r['segmentos'][0]['Salida_dt'].replace(tzinfo=None) >= ahora.replace(tzinfo=None))]

    def route_has_main_train(route): return any('renfe' in str(s.get('Compania', '')).lower() or 'tren' in str(s.get('Transporte', '')).lower() for s in route.get('segmentos', []))
    def route_has_main_bus(route): return any('damas' in str(s.get('Compania', '')).lower() or 'bus' in str(s.get('Transporte', '')).lower() for s in route.get('segmentos', []))
    def route_is_valid(route):
        st, sb = form_data.get('solo_tren'), form_data.get('solo_bus')
        if not st and not sb: return True
        tt, tb = route_has_main_train(route), route_has_main_bus(route)
        if not tt and not tb: return True
        if st and tt: return True
        if sb and tb: return True
        return False
    resultados_procesados = [r for r in resultados_procesados if route_is_valid(r)]

    lugares_a_evitar = []
    if form_data.get('evitar_sj'): lugares_a_evitar.append('Sta. Justa')
    if form_data.get('evitar_pa'): lugares_a_evitar.append('Plz. Armas')
    if lugares_a_evitar:
        resultados_procesados = [r for r in resultados_procesados if not any(s.get('Destino') in lugares_a_evitar for s in r.get('segmentos', [])[:-1])]

    if form_data.get('salir_despues_check'):
        try:
            hl = time(int(form_data.get('salir_despues_hora')), int(form_data.get('salir_despues_minuto')))
            resultados_procesados = [r for r in resultados_procesados if r.get('hora_llegada_final') == 'Flexible' or (r.get('segmentos') and 'Salida_dt' in r['segmentos'][0] and r['segmentos'][0]['Salida_dt'].time() >= hl)]
        except: pass 
    if form_data.get('llegar_antes_check'):
        try:
            hl = time(int(form_data.get('llegar_antes_hora')), int(form_data.get('llegar_antes_minuto')))
            resultados_procesados = [r for r in resultados_procesados if r.get('hora_llegada_final') != 'Flexible' and r.get('llegada_final_dt_obj') and r['llegada_final_dt_obj'].time() < hl]
        except: pass
            
    if resultados_procesados:
        resultados_unicos = {r['duracion_total_str'] + r['segmentos'][0]['Salida_str']: r for r in resultados_procesados}.values()
        resultados_procesados = sorted(list(resultados_unicos), key=lambda x: x.get('llegada_final_dt_obj', datetime.max))
    
    return render_template("resultado.html", origen=origen, destino=destino, resultados=resultados_procesados, filtros=form_data, dia_semana=nombre_dia, search_incomplete=search_incomplete)

# ===== FUNCIÓN DE BÚSQUEDA CORREGIDA Y OPTIMIZADA =====
def find_all_routes_intelligently(origen, destino, df):
    rutas = []
    rutas_por_origen = defaultdict(list)
    for _, row in df.iterrows():
        rutas_por_origen[row['Origen']].append(row)

    # 1. Rutas directas (1 tramo)
    for r1 in rutas_por_origen.get(origen, []):
        if r1['Destino'] == destino:
            rutas.append([r1])

    # 2. Rutas con 1 transbordo (2 tramos)
    for r1 in rutas_por_origen.get(origen, []):
        if r1['Destino'] == destino: continue
        
        origen_r2 = r1['Destino']
        for r2 in rutas_por_origen.get(origen_r2, []):
            if r2['Destino'] == destino:
                rutas.append([r1, r2])

    # 3. Rutas con 2 transbordos (3 tramos)
    for r1 in rutas_por_origen.get(origen, []):
        if r1['Destino'] == destino: continue
        
        origen_r2 = r1['Destino']
        for r2 in rutas_por_origen.get(origen_r2, []):
            if r2['Destino'] == destino or r2['Destino'] == origen: continue
            
            origen_r3 = r2['Destino']
            for r3 in rutas_por_origen.get(origen_r3, []):
                if r3['Destino'] == destino:
                    rutas.append([r1, r2, r3])
    
    return rutas
# =========================================================

def calculate_route_times(ruta_series_list, desde_ahora_check):
    try:
        segmentos = [s.copy() for s in ruta_series_list]
        TIEMPO_TRANSBORDO = timedelta(minutes=10)
        
        if len(segmentos) == 1 and segmentos[0].get('Tipo_Horario') == 'Frecuencia':
            dur_min = segmentos[0].get('Duracion_Trayecto_Min', 0)
            duracion = timedelta(minutes=dur_min)
            seg_dict = segmentos[0].to_dict()
            seg_dict.update({'icono': get_icon_for_compania(seg_dict.get('Compania')), 'Salida_str': "A tu aire", 'Llegada_str': "", 'Duracion_Tramo_Min': dur_min, 'Salida_dt': datetime.now(pytz.timezone('Europe/Madrid'))})
            return {"segmentos": [seg_dict], "precio_total": seg_dict.get('Precio', 0), "llegada_final_dt_obj": datetime.min, "hora_llegada_final": "Flexible", "duracion_total_str": format_timedelta(duracion)}

        anchor_index = next((i for i, s in enumerate(segmentos) if 'Salida_dt' in s and pd.notna(s['Salida_dt'])), -1)
        
        if anchor_index != -1:
            llegada_siguiente_dt = segmentos[anchor_index]['Salida_dt']
            for i in range(anchor_index - 1, -1, -1):
                dur_min = segmentos[i].get('Duracion_Trayecto_Min', 0)
                dur = timedelta(minutes=dur_min)
                segmentos[i]['Llegada_dt'] = llegada_siguiente_dt - TIEMPO_TRANSBORDO
                segmentos[i]['Salida_dt'] = segmentos[i]['Llegada_dt'] - dur
                llegada_siguiente_dt = segmentos[i]['Salida_dt']
                
            llegada_anterior_dt = segmentos[anchor_index].get('Llegada_dt')
            for i in range(anchor_index + 1, len(segmentos)):
                dur_min = segmentos[i].get('Duracion_Trayecto_Min', 0)
                dur = timedelta(minutes=dur_min)
                if pd.notna(llegada_anterior_dt):
                    segmentos[i]['Salida_dt'] = llegada_anterior_dt + TIEMPO_TRANSBORDO
                    segmentos[i]['Llegada_dt'] = segmentos[i]['Salida_dt'] + dur
                    llegada_anterior_dt = segmentos[i].get('Llegada_dt')
                else:
                    segmentos[i]['Salida_dt'] = pd.NaT
                    segmentos[i]['Llegada_dt'] = pd.NaT
                    llegada_anterior_dt = pd.NaT
        else: # Ruta solo de frecuencia
            llegada_anterior_dt = None
            start_time = datetime.now(pytz.timezone('Europe/Madrid')) if desde_ahora_check else datetime.combine(datetime.today(), time(7,0))
            for i, seg in enumerate(segmentos):
                dur_min = seg.get('Duracion_Trayecto_Min', 0)
                dur = timedelta(minutes=dur_min)
                if i == 0:
                    seg['Salida_dt'] = start_time
                elif pd.notna(llegada_anterior_dt):
                     seg['Salida_dt'] = llegada_anterior_dt + TIEMPO_TRANSBORDO
                else:
                    seg['Salida_dt'] = pd.NaT

                if pd.notna(seg.get('Salida_dt')):
                    seg['Llegada_dt'] = seg.get('Salida_dt') + dur
                else:
                    seg['Llegada_dt'] = pd.NaT
                llegada_anterior_dt = seg.get('Llegada_dt')
        
        if any(pd.isna(s.get('Salida_dt')) or pd.isna(s.get('Llegada_dt')) for s in segmentos):
            return None

        primera_salida_dt = segmentos[0]['Salida_dt']
        segmentos_formateados = []
        for seg in segmentos:
            seg_dict = seg.to_dict()
            seg_dict.update({'icono': get_icon_for_compania(seg_dict.get('Compania')), 'Salida_str': seg['Salida_dt'].strftime('%H:%M'), 'Llegada_str': seg['Llegada_dt'].strftime('%H:%M'), 'Duracion_Tramo_Min': (seg['Llegada_dt'] - seg['Salida_dt']).total_seconds() / 60})
            segmentos_formateados.append(seg_dict)
        segmentos_formateados[0]['Salida_dt'] = primera_salida_dt

        return {
            "segmentos": segmentos_formateados,
            "precio_total": sum(s.get('Precio', 0) for s in ruta_series_list),
            "llegada_final_dt_obj": segmentos[-1]['Llegada_dt'],
            "hora_llegada_final": segmentos[-1]['Llegada_dt'].time(),
            "duracion_total_str": format_timedelta(segmentos[-1]['Llegada_dt'] - segmentos[0]['Salida_dt'])
        }
    except Exception as e:
        print(f"Error inesperado en calculate_route_times: {e}")
        return None

if __name__ == "__main__":
    app.run(debug=True)
