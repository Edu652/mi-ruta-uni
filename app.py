# Archivo: app.py | Versión: Estable con Lógica Corregida
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
    rutas_fijas_df.loc[:, 'Salida_dt'] = pd.to_datetime(rutas_fijas_df['Salida'], format='%H:%M:%S', errors='coerce').dt.to_pydatetime()
    rutas_fijas_df.loc[:, 'Llegada_dt'] = pd.to_datetime(rutas_fijas_df['Llegada'], format='%H:%M:%S', errors='coerce').dt.to_pydatetime()
    rutas_fijas_df.dropna(subset=['Salida_dt', 'Llegada_dt'], inplace=True)

    # 1. Encontrar plantillas de rutas
    candidatos_plantilla = find_all_routes_intelligently(origen, destino, rutas_df_global)

    # 2. Expandir rutas con horarios fijos
    candidatos_expandidos = []
    for ruta in candidatos_plantilla:
        indices_fijos = [i for i, seg in enumerate(ruta) if seg['Tipo_Horario'] == 'Fijo']
        if not indices_fijos:
            candidatos_expandidos.append(ruta)
            continue
        
        idx_ancla = indices_fijos[0]
        ancla_plantilla = ruta[idx_ancla]
        
        posibles_anclas = rutas_fijas_df[
            (rutas_fijas_df['Origen'] == ancla_plantilla['Origen']) &
            (rutas_fijas_df['Destino'] == ancla_plantilla['Destino']) &
            (rutas_fijas_df['Compania'] == ancla_plantilla['Compania'])
        ]
        
        for _, ancla_real in posibles_anclas.iterrows():
            nueva_ruta = ruta[:]
            nueva_ruta[idx_ancla] = ancla_real
            candidatos_expandidos.append(nueva_ruta)

    # 3. Aplicar filtros
    lugares_a_evitar = []
    if form_data.get('evitar_sj'): lugares_a_evitar.append('Sta. Justa')
    if form_data.get('evitar_pa'): lugares_a_evitar.append('Plz. Armas')
    if lugares_a_evitar:
        candidatos_expandidos = [r for r in candidatos_expandidos if not any(s['Destino'] in lugares_a_evitar for s in r[:-1])]

    def route_has_train(route):
        return any('renfe' in str(s.get('Compania', '')).lower() or 'tren' in str(s.get('Transporte', '')).lower() for s in route)
    def route_has_bus(route):
        return any(any(k in str(s.get('Compania', '')).lower() for k in ['damas', 'emtusa', 'urbano']) or 'bus' in str(s.get('Transporte', '')).lower() for s in route)

    solo_tren = form_data.get('solo_tren')
    solo_bus = form_data.get('solo_bus')
    
    if solo_tren or solo_bus:
        candidatos_filtrados = []
        for ruta in candidatos_expandidos:
            tiene_tren = route_has_train(ruta)
            tiene_bus = route_has_bus(ruta)
            es_solo_coche = not tiene_tren and not tiene_bus

            if es_solo_coche:
                candidatos_filtrados.append(ruta)
                continue
            
            if solo_tren and tiene_tren and not tiene_bus:
                candidatos_filtrados.append(ruta)
            elif solo_bus and tiene_bus and not tiene_tren:
                candidatos_filtrados.append(ruta)
        candidatos_expandidos = candidatos_filtrados

    # 4. Calcular tiempos y aplicar filtros de hora
    resultados_procesados = []
    for ruta in candidatos_expandidos:
        resultado = calculate_route_times(ruta, rutas_fijas_df, form_data.get('desde_ahora'))
        if resultado:
            resultados_procesados.append(resultado)
            
    if form_data.get('salir_despues_check'):
        try:
            hora_limite = time(int(form_data.get('salir_despues_hora')), int(form_data.get('salir_despues_minuto')))
            resultados_procesados = [r for r in resultados_procesados if r['hora_llegada_final'] == 'Flexible' or (r.get('segmentos') and r['segmentos'][0].get('Salida_dt') and r['segmentos'][0]['Salida_dt'].time() >= hora_limite)]
        except: pass 

    if form_data.get('llegar_antes_check'):
        try:
            hora_limite = time(int(form_data.get('llegar_antes_hora')), int(form_data.get('llegar_antes_minuto')))
            resultados_procesados = [r for r in resultados_procesados if r['hora_llegada_final'] != 'Flexible' and r['llegada_final_dt_obj'].time() < hora_limite]
        except: pass
            
    # 5. Eliminar duplicados y ordenar
    resultados_unicos = {r['duracion_total_str'] + r['segmentos'][0]['Salida_str']: r for r in resultados_procesados}.values()
    
    if resultados_unicos:
        resultados_procesados = sorted(list(resultados_unicos), key=lambda x: x['llegada_final_dt_obj'])

    return render_template("resultado.html", origen=origen, destino=destino, resultados=resultados_procesados, filtros=form_data)


def find_all_routes_intelligently(origen, destino, df):
    rutas = []
    rutas_indices_unicos = set()
    for index, r in df[(df['Origen'] == origen) & (df['Destino'] == destino)].iterrows():
        indices = (index,); rutas.append([r]); rutas_indices_unicos.add(indices)
    for t1_index, t1 in df[df['Origen'] == origen].iterrows():
        for t2_index, t2 in df[(df['Origen'] == t1['Destino']) & (df['Destino'] == destino)].iterrows():
            indices = (t1_index, t2_index)
            if indices not in rutas_indices_unicos:
                rutas.append([t1, t2]); rutas_indices_unicos.add(indices)
    if not rutas:
        for t1_index, t1 in df[df['Origen'] == origen].iterrows():
            for t2_index, t2 in df[df['Origen'] == t1['Destino']].iterrows():
                if t2['Destino'] in [origen, destino]: continue
                for t3_index, t3 in df[(df['Origen'] == t2['Destino']) & (df['Destino'] == destino)].iterrows():
                    indices = (t1_index, t2_index, t3_index)
                    if indices not in rutas_indices_unicos:
                        rutas.append([t1, t2, t3]); rutas_indices_unicos.add(indices)
    return rutas

def calculate_route_times(ruta_series_list, rutas_fijas_df, desde_ahora_check):
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
            return {
                "segmentos": [seg_dict], "precio_total": seg.get('Precio', 0),
                "llegada_final_dt_obj": datetime.min, "hora_llegada_final": "Flexible",
                "duracion_total_str": format_timedelta(duracion)
            }

        anchor_index = -1
        for i, seg in enumerate(segmentos):
            if seg['Tipo_Horario'] == 'Fijo':
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
                if seg['Tipo_Horario'] == 'Fijo':
                    if seg.name not in rutas_fijas_df.index: raise ValueError("Fijo no disponible")
                    if seg['Salida_dt'] < llegada_anterior_dt + TIEMPO_TRANSBORDO: raise ValueError("Sin tiempo de transbordo")
                else:
                    frecuencia = timedelta(minutes=seg['Frecuencia_Min'])
                    seg['Salida_dt'] = llegada_anterior_dt + TIEMPO_TRANSBORDO + frecuencia
                    seg['Llegada_dt'] = seg['Salida_dt'] + duracion
                llegada_anterior_dt = seg['Llegada_dt']
        else:
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
        
        if desde_ahora_check:
            tz = pytz.timezone('Europe/Madrid')
            ahora = datetime.now(tz)
            # Comparamos sin timezone para evitar errores de offset-naive vs offset-aware
            if segmentos and segmentos[0].get('Salida_dt') and segmentos[0]['Salida_dt'].replace(tzinfo=None) < ahora.replace(tzinfo=None):
                 raise ValueError("La hora de salida ya ha pasado.")

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

