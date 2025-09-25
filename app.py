# Archivo: app.py | Versión: Final con Lógica de Filtros y Hora Corregida
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
    form_data = request.form.to_dict()
    origen = form_data.get("origen")
    destino = form_data.get("destino")
    
    rutas_fijas_df = rutas_df_global[rutas_df_global['Tipo_Horario'] == 'Fijo'].copy()
    rutas_fijas_df['Salida_dt'] = pd.to_datetime(rutas_fijas_df['Salida'], format='%H:%M:%S', errors='coerce').dt.to_pydatetime()
    rutas_fijas_df['Llegada_dt'] = pd.to_datetime(rutas_fijas_df['Llegada'], format='%H:%M:%S', errors='coerce').dt.to_pydatetime()
    rutas_fijas_df.dropna(subset=['Salida_dt', 'Llegada_dt'], inplace=True)

    # PASO 1: Encontrar todas las plantillas de ruta posibles
    candidatos_plantilla = find_all_routes_intelligently(origen, destino, rutas_df_global)

    # PASO 2: Expandir plantillas con todos los horarios fijos del día
    candidatos_expandidos = []
    for ruta_plantilla in candidatos_plantilla:
        if all(s['Tipo_Horario'] == 'Frecuencia' for s in ruta_plantilla):
            candidatos_expandidos.append(ruta_plantilla)
            continue
        
        indices_fijos = [i for i, seg in enumerate(ruta_plantilla) if seg['Tipo_Horario'] == 'Fijo']
        idx_ancla = indices_fijos[0]
        ancla_plantilla = ruta_plantilla[idx_ancla]
        
        posibles_anclas = rutas_fijas_df[
            (rutas_fijas_df['Origen'] == ancla_plantilla['Origen']) &
            (rutas_fijas_df['Destino'] == ancla_plantilla['Destino']) &
            (rutas_fijas_df['Compania'] == ancla_plantilla['Compania'])
        ]
        
        for _, ancla_real in posibles_anclas.iterrows():
            nueva_ruta = ruta_plantilla[:]
            nueva_ruta[idx_ancla] = ancla_real
            candidatos_expandidos.append(nueva_ruta)
    
    # PASO 3: Calcular los tiempos para todas las rutas posibles
    resultados_procesados = []
    for ruta in candidatos_expandidos:
        resultado = calculate_route_times(ruta, form_data.get('desde_ahora'))
        if resultado:
            resultados_procesados.append(resultado)

    # PASO 4: Aplicar TODOS los filtros a la lista completa
    
    # Filtro "Desde Ahora"
    if form_data.get('desde_ahora'):
        tz = pytz.timezone('Europe/Madrid')
        ahora = datetime.now(tz)
        resultados_procesados = [r for r in resultados_procesados if r['hora_llegada_final'] == 'Flexible' or r['segmentos'][0]['Salida_dt'].replace(tzinfo=None) >= ahora.replace(tzinfo=None)]

    # Filtros de tipo de transporte (LÓGICA CORREGIDA)
    def route_has_main_train(route):
        return any('renfe' in str(s.get('Compania', '')).lower() for s in route['segmentos'])
    
    def route_has_main_bus(route):
        return any('damas' in str(s.get('Compania', '')).lower() for s in route['segmentos'])

    def route_is_valid_for_transport_filter(route):
        solo_tren = form_data.get('solo_tren')
        solo_bus = form_data.get('solo_bus')
        
        if not solo_tren and not solo_bus:
            return True

        tiene_tren = route_has_main_train(route)
        tiene_bus = route_has_main_bus(route)
        
        if not tiene_tren and not tiene_bus: # Coche, Urbano solo, etc.
            return True 

        if solo_tren and tiene_tren:
            return True
        
        if solo_bus and tiene_bus:
            return True
        
        return False

    resultados_procesados = [r for r in resultados_procesados if route_is_valid_for_transport_filter(r)]

    # Filtro de estaciones
    lugares_a_evitar = []
    if form_data.get('evitar_sj'): lugares_a_evitar.append('Sta. Justa')
    if form_data.get('evitar_pa'): lugares_a_evitar.append('Plz. Armas')
    if lugares_a_evitar:
        resultados_procesados = [r for r in resultados_procesados if not any(s['Destino'] in lugares_a_evitar for s in r['segmentos'][:-1])]

    # Filtros de hora de llegada/salida
    if form_data.get('salir_despues_check'):
        try:
            hora_limite = time(int(form_data.get('salir_despues_hora')), int(form_data.get('salir_despues_minuto')))
            resultados_procesados = [r for r in resultados_procesados if r['hora_llegada_final'] == 'Flexible' or r['segmentos'][0]['Salida_dt'].time() >= hora_limite]
        except: pass 

    if form_data.get('llegar_antes_check'):
        try:
            hora_limite = time(int(form_data.get('llegar_antes_hora')), int(form_data.get('llegar_antes_minuto')))
            resultados_procesados = [r for r in resultados_procesados if r['hora_llegada_final'] != 'Flexible' and r['llegada_final_dt_obj'].time() < hora_limite]
        except: pass
            
    # PASO 5: Eliminar duplicados y ordenar
    resultados_unicos = {r['duracion_total_str'] + r['segmentos'][0]['Salida_str']: r for r in resultados_procesados}.values()
    
    if resultados_unicos:
        resultados_procesados = sorted(list(resultados_unicos), key=lambda x: x['llegada_final_dt_obj'])

    return render_template("resultado.html", origen=origen, destino=destino, resultados=resultados_procesados, filtros=form_data)


def find_all_routes_intelligently(origen, destino, df):
    rutas, indices_unicos = [], set()
    for i, r in df[(df['Origen'] == origen) & (df['Destino'] == destino)].iterrows():
        if (i,) not in indices_unicos: rutas.append([r]); indices_unicos.add((i,))
    for i1, t1 in df[df['Origen'] == origen].iterrows():
        for i2, t2 in df[(df['Origen'] == t1['Destino']) & (df['Destino'] == destino)].iterrows():
            if (i1, i2) not in indices_unicos: rutas.append([t1, t2]); indices_unicos.add((i1, i2))
    if not rutas:
        for i1, t1 in df[df['Origen'] == origen].iterrows():
            for i2, t2 in df[df['Origen'] == t1['Destino']].iterrows():
                if t2['Destino'] in [origen, destino]: continue
                for i3, t3 in df[(df['Origen'] == t2['Destino']) & (df['Destino'] == destino)].iterrows():
                    if (i1, i2, i3) not in indices_unicos: rutas.append([t1, t2, t3]); indices_unicos.add((i1, i2, i3))
    return rutas

def calculate_route_times(ruta_series_list, desde_ahora_check):
    try:
        segmentos = [s.copy() for s in ruta_series_list]
        TIEMPO_TRANSBORDO = timedelta(minutes=10)
        
        if len(segmentos) == 1 and segmentos[0]['Tipo_Horario'] == 'Frecuencia':
            seg = segmentos[0]
            duracion = timedelta(minutes=seg['Duracion_Trayecto_Min'])
            seg_dict = seg.to_dict()
            seg_dict['icono'] = get_icon_for_compania(seg.get('Compania'))
            seg_dict['Salida_str'] = "A tu aire"
            seg_dict['Llegada_str'] = ""
            seg_dict['Duracion_Tramo_Min'] = seg['Duracion_Trayecto_Min']
            seg_dict['Salida_dt'] = datetime.now(pytz.timezone('Europe/Madrid'))
            return {
                "segmentos": [seg_dict], "precio_total": seg.get('Precio', 0),
                "llegada_final_dt_obj": datetime.min, "hora_llegada_final": "Flexible",
                "duracion_total_str": format_timedelta(duracion)
            }

        anchor_index = -1
        for i, seg in enumerate(segmentos):
            if 'Salida_dt' in seg and pd.notna(seg['Salida_dt']):
                anchor_index = i
                break
        
        if anchor_index != -1:
            anchor_seg = segmentos[anchor_index]
            llegada_siguiente_dt = anchor_seg['Salida_dt']
            for i in range(anchor_index - 1, -1, -1):
                seg = segmentos[i]
                duracion = timedelta(minutes=seg['Duracion_Trayecto_Min'])
                seg['Llegada_dt'] = llegada_siguiente_dt - TIEMPO_TRANSBORDO
                seg['Salida_dt'] = seg['Llegada_dt'] - duracion
                llegada_siguiente_dt = seg['Salida_dt']
            
            llegada_anterior_dt = anchor_seg['Llegada_dt']
            for i in range(anchor_index + 1, len(segmentos)):
                seg = segmentos[i]
                duracion = timedelta(minutes=seg['Duracion_Trayecto_Min'])
                seg['Salida_dt'] = llegada_anterior_dt + TIEMPO_TRANSBORDO
                seg['Llegada_dt'] = seg['Salida_dt'] + duracion
                llegada_anterior_dt = seg['Llegada_dt']
        else: # Rutas solo de frecuencia
            llegada_anterior_dt = None
            start_time = datetime.now(pytz.timezone('Europe/Madrid')) if desde_ahora_check else datetime.combine(datetime.today(), time(7,0))
            for i, seg in enumerate(segmentos):
                duracion = timedelta(minutes=seg['Duracion_Trayecto_Min'])
                if i == 0:
                    seg['Salida_dt'] = start_time
                else:
                    seg['Salida_dt'] = llegada_anterior_dt + TIEMPO_TRANSBORDO
                seg['Llegada_dt'] = seg['Salida_dt'] + duracion
                llegada_anterior_dt = seg['Llegada_dt']
        
        primera_salida_dt = segmentos[0]['Salida_dt']

        segmentos_formateados = []
        for seg in segmentos:
            seg_dict = seg.to_dict()
            seg_dict['icono'] = get_icon_for_compania(seg.get('Compania'))
            seg_dict['Salida_str'] = seg['Salida_dt'].strftime('%H:%M')
            seg_dict['Llegada_str'] = seg['Llegada_dt'].strftime('%H:%M')
            seg_dict['Duracion_Tramo_Min'] = (seg['Llegada_dt'] - seg['Salida_dt']).total_seconds() / 60
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
        return None

if __name__ == "__main__":
    app.run(debug=True)

