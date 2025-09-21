from flask import Flask, render_template, request
import pandas as pd
import json
import random
from datetime import datetime, timedelta, time

app = Flask(__name__)

# --- Funciones de Ayuda ---
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
            except (ValueError, AttributeError):
                try: return float(val)
                except ValueError: return 0
        if isinstance(val, time): return val.hour * 60 + val.minute
        return 0
    if isinstance(series, pd.Series): return series.apply(to_minutes)
    else: return to_minutes(series)

# --- Carga de Datos ---
try:
    rutas_df = pd.read_excel("rutas.xlsx", engine="openpyxl")
    rutas_df.columns = rutas_df.columns.str.strip()

    if 'Compañía' in rutas_df.columns:
        rutas_df.rename(columns={'Compañía': 'Compania'}, inplace=True)

    required_cols = ['Origen', 'Destino', 'Tipo_Horario', 'Compania']
    for col in required_cols:
        if col not in rutas_df.columns:
            raise ValueError(f"Falta la columna requerida: {col}")

    for col in ['Duracion_Trayecto_Min', 'Frecuencia_Min']:
        if col in rutas_df.columns:
            rutas_df[col] = clean_minutes_column(rutas_df[col])
    
    if 'Precio' in rutas_df.columns:
        rutas_df['Precio'] = pd.to_numeric(rutas_df['Precio'], errors='coerce').fillna(0)

except Exception as e:
    print(f"ERROR CRÍTICO al cargar 'rutas.xlsx': {e}")
    rutas_df = pd.DataFrame()

try:
    with open("frases_motivadoras.json", "r", encoding="utf-8") as f:
        frases = json.load(f)
except Exception:
    frases = ["El esfuerzo de hoy es el éxito de mañana."]

@app.route("/")
def index():
    lugares = []
    if not rutas_df.empty:
        lugares = sorted(pd.concat([rutas_df["Origen"], rutas_df["Destino"]]).dropna().unique())
    frase = random.choice(frases)
    return render_template("index.html", lugares=lugares, frase=frase)


@app.route("/buscar", methods=["POST"])
def buscar():
    origen = request.form["origen"]
    destino = request.form["destino"]
    desde_ahora_check = request.form.get('desde_ahora')
    
    # Pre-procesar rutas fijas una sola vez
    rutas_fijas = rutas_df[rutas_df['Tipo_Horario'] == 'Fijo'].copy()
    if not rutas_fijas.empty:
        rutas_fijas['Salida_dt'] = pd.to_datetime(rutas_fijas['Salida'], format='%H:%M:%S', errors='coerce').dt.to_pydatetime()
        rutas_fijas['Llegada_dt'] = pd.to_datetime(rutas_fijas['Llegada'], format='%H:%M:%S', errors='coerce').dt.to_pydatetime()
        rutas_fijas.dropna(subset=['Salida_dt', 'Llegada_dt'], inplace=True)

    resultados_procesados = []
    rutas_procesadas_set = set()

    # --- MOTOR DE CÁLCULO Y VALIDACIÓN ---
    def procesar_y_validar_ruta(ruta_series_list):
        clave_ruta = tuple(s.name for s in ruta_series_list)
        if clave_ruta in rutas_procesadas_set: return
        rutas_procesadas_set.add(clave_ruta)
        
        # --- ¡NUEVO! Caso especial para rutas directas en coche ---
        if len(ruta_series_list) == 1 and ruta_series_list[0]['Tipo_Horario'] == 'Flexible':
            seg = ruta_series_list[0]
            duracion = timedelta(minutes=seg['Duracion_Trayecto_Min'])
            segmento_dict = seg.to_dict()
            segmento_dict['icono'] = get_icon_for_compania(seg.get('Compania'), seg.get('Transporte'))
            segmento_dict['Salida_str'] = "A tu aire"
            segmento_dict['Llegada_str'] = ""
            segmento_dict['Duracion_Tramo_Min'] = seg['Duracion_Trayecto_Min']
            resultados_procesados.append({
                "segmentos": [segmento_dict],
                "precio_total": seg.get('Precio', 0),
                "llegada_final_dt_obj": datetime(1, 1, 1, 0, 0),
                "hora_llegada_final": "Flexible",
                "duracion_total_str": format_timedelta(duracion)
            })
            return

        # --- Procesamiento normal para el resto de rutas ---
        segmentos, llegada_anterior_dt = [], None
        TIEMPO_TRANSBORDO = timedelta(minutes=10)
        
        for i, seg in enumerate(ruta_series_list):
            seg_calc = seg.copy()
            
            if i == 0:
                if seg['Tipo_Horario'] == 'Frecuencia':
                    start_time = datetime.now() if desde_ahora_check else datetime.combine(datetime.today(), time(7, 0))
                    llegada_anterior_dt = start_time
                elif seg['Tipo_Horario'] == 'Fijo':
                    tramo_fijo = rutas_fijas.loc[seg.name]
                    if desde_ahora_check and tramo_fijo['Salida_dt'].time() < datetime.now().time(): return
                    llegada_anterior_dt = tramo_fijo['Salida_dt'] - TIEMPO_TRANSBORDO
            
            if seg['Tipo_Horario'] == 'Flexible':
                duracion = timedelta(minutes=seg['Duracion_Trayecto_Min'])
                if i > 0:
                    seg_calc['Salida_dt'] = llegada_anterior_dt + TIEMPO_TRANSBORDO
                    seg_calc['Llegada_dt'] = seg_calc['Salida_dt'] + duracion
                else:
                    siguiente_tramo = rutas_fijas.loc[ruta_series_list[i+1].name]
                    if desde_ahora_check and siguiente_tramo['Salida_dt'].time() < datetime.now().time(): return
                    seg_calc['Llegada_dt'] = siguiente_tramo['Salida_dt']
                    seg_calc['Salida_dt'] = seg_calc['Llegada_dt'] - duracion
            
            elif seg['Tipo_Horario'] == 'Fijo':
                tramo_fijo = rutas_fijas.loc[seg.name]
                if llegada_anterior_dt and tramo_fijo['Salida_dt'] < llegada_anterior_dt + TIEMPO_TRANSBORDO: return
                seg_calc['Salida_dt'], seg_calc['Llegada_dt'] = tramo_fijo['Salida_dt'], tramo_fijo['Llegada_dt']
            
            elif seg['Tipo_Horario'] == 'Frecuencia':
                frecuencia = timedelta(minutes=seg['Frecuencia_Min'])
                duracion = timedelta(minutes=seg['Duracion_Trayecto_Min'])
                seg_calc['Salida_dt'] = llegada_anterior_dt + frecuencia
                seg_calc['Llegada_dt'] = seg_calc['Salida_dt'] + duracion
            
            if llegada_anterior_dt and seg_calc['Salida_dt'] < llegada_anterior_dt:
                seg_calc['Salida_dt'] += timedelta(days=1); seg_calc['Llegada_dt'] += timedelta(days=1)
            
            llegada_anterior_dt = seg_calc['Llegada_dt']
            
            seg_calc['icono'] = get_icon_for_compania(seg.get('Compania'), seg.get('Transporte'))
            seg_calc['Salida_str'] = seg_calc['Salida_dt'].strftime('%H:%M')
            seg_calc['Llegada_str'] = seg_calc['Llegada_dt'].strftime('%H:%M')
            seg_calc['Duracion_Tramo_Min'] = (seg_calc['Llegada_dt'] - seg_calc['Salida_dt']).total_seconds() / 60
            segmentos.append(seg_calc.to_dict())

        resultados_procesados.append({
            "segmentos": segmentos,
            "precio_total": sum(s.get('Precio', 0) for s in ruta_series_list),
            "llegada_final_dt_obj": segmentos[-1]['Llegada_dt'],
            "hora_llegada_final": segmentos[-1]['Llegada_dt'].time(),
            "duracion_total_str": format_timedelta(segmentos[-1]['Llegada_dt'] - segmentos[0]['Salida_dt'])
        })

    # --- BÚSQUEDA DE CANDIDATOS ---
    for _, ruta in rutas_df[(rutas_df['Origen'] == origen) & (rutas_df['Destino'] == destino)].iterrows():
        procesar_y_validar_ruta([ruta])
    for _, tramo1 in rutas_df[rutas_df['Origen'] == origen].iterrows():
        for _, tramo2 in rutas_df[(rutas_df['Origen'] == tramo1['Destino']) & (rutas_df['Destino'] == destino)].iterrows():
            procesar_y_validar_ruta([tramo1, tramo2])
    for _, tramo1 in rutas_df[rutas_df['Origen'] == origen].iterrows():
        for _, tramo2 in rutas_df[rutas_df['Origen'] == tramo1['Destino']].iterrows():
            if tramo2['Destino'] == destino or tramo2['Destino'] == origen: continue
            for _, tramo3 in rutas_df[(rutas_df['Origen'] == tramo2['Destino']) & (rutas_df['Destino'] == destino)].iterrows():
                procesar_y_validar_ruta([tramo1, tramo2, tramo3])

    if resultados_procesados:
        resultados_procesados.sort(key=lambda x: x['llegada_final_dt_obj'])

    return render_template("resultado.html", origen=origen, destino=destino, resultados=resultados_procesados)

if __name__ == "__main__":
    app.run(debug=True)

