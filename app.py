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
    return series.apply(to_minutes) if isinstance(series, pd.Series) else to_minutes(series)

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
    
    rutas_encontradas = []
    
    # --- CONSTANTES ---
    TIEMPO_TRANSBORDO = timedelta(minutes=10)

    # Pre-procesar rutas fijas
    rutas_fijas = rutas_df[rutas_df['Tipo_Horario'] == 'Fijo'].copy()
    if not rutas_fijas.empty:
        rutas_fijas['Salida_dt'] = pd.to_datetime(rutas_fijas['Salida'], format='%H:%M:%S', errors='coerce').dt.to_pydatetime()
        rutas_fijas['Llegada_dt'] = pd.to_datetime(rutas_fijas['Llegada'], format='%H:%M:%S', errors='coerce').dt.to_pydatetime()
        rutas_fijas.dropna(subset=['Salida_dt', 'Llegada_dt'], inplace=True)
        
        if desde_ahora_check:
            ahora = datetime.now()
            # Se compara solo la parte de la hora
            rutas_fijas = rutas_fijas[rutas_fijas['Salida_dt'].apply(lambda x: x.time()) > ahora.time()]

    # --- LÓGICA DE BÚSQUEDA SIMPLIFICADA ---

    # 1. Rutas Directas
    directas = rutas_df[(rutas_df['Origen'] == origen) & (rutas_df['Destino'] == destino)]
    for _, ruta in directas.iterrows():
        # Si es fija, asegurarse de que no ha sido filtrada por la hora
        if ruta['Tipo_Horario'] == 'Fijo' and ruta.name not in rutas_fijas.index:
            continue
        rutas_encontradas.append([ruta])

    # 2. Rutas de 2 Tramos
    tramos1 = rutas_df[rutas_df['Origen'] == origen]
    for _, tramo1 in tramos1.iterrows():
        punto_intermedio = tramo1['Destino']
        if punto_intermedio == destino: continue

        tramos2 = rutas_df[(rutas_df['Origen'] == punto_intermedio) & (rutas_df['Destino'] == destino)]
        for _, tramo2 in tramos2.iterrows():
            rutas_encontradas.append([tramo1, tramo2])

    # 3. Rutas de 3 Tramos
    tramos1_3 = rutas_df[rutas_df['Origen'] == origen]
    for _, tramo1 in tramos1_3.iterrows():
        pi1 = tramo1['Destino']
        if pi1 == destino: continue
        
        tramos2_3 = rutas_df[rutas_df['Origen'] == pi1]
        for _, tramo2 in tramos2_3.iterrows():
            pi2 = tramo2['Destino']
            if pi2 == destino or pi2 == origen: continue

            tramos3_3 = rutas_df[(rutas_df['Origen'] == pi2) & (rutas_df['Destino'] == destino)]
            for _, tramo3 in tramos3_3.iterrows():
                rutas_encontradas.append([tramo1, tramo2, tramo3])


    # --- PROCESAR Y FORMATEAR ---
    resultados_procesados = []
    rutas_procesadas_set = set()
    for ruta in rutas_encontradas:
        clave_ruta = tuple(s.name for s in ruta)
        if clave_ruta in rutas_procesadas_set: continue
        rutas_procesadas_set.add(clave_ruta)
        
        try:
            segmentos_calculados = []
            llegada_anterior_dt = None
            
            for i, seg in enumerate(ruta):
                seg_calc = seg.copy()
                
                if i == 0:
                    if seg['Tipo_Horario'] == 'Fijo':
                        if seg.name not in rutas_fijas.index: raise ValueError("Ruta fija no disponible")
                        llegada_anterior_dt = rutas_fijas.loc[seg.name]['Salida_dt'] - TIEMPO_TRANSBORDO
                    else: # Frecuencia
                        start_time = datetime.now() if desde_ahora_check else datetime.combine(datetime.today(), time(7,0))
                        llegada_anterior_dt = start_time
                
                if seg['Tipo_Horario'] == 'Fijo':
                    if seg.name not in rutas_fijas.index: raise ValueError("Ruta fija no disponible en transbordo")
                    tramo_fijo = rutas_fijas.loc[seg.name]
                    if llegada_anterior_dt and tramo_fijo['Salida_dt'] < llegada_anterior_dt + TIEMPO_TRANSBORDO:
                        raise ValueError("No hay tiempo para el transbordo")
                    seg_calc['Salida_dt'] = tramo_fijo['Salida_dt']
                    seg_calc['Llegada_dt'] = tramo_fijo['Llegada_dt']
                else: # Frecuencia
                    frecuencia = timedelta(minutes=seg['Frecuencia_Min'])
                    duracion = timedelta(minutes=seg['Duracion_Trayecto_Min'])
                    tiempo_extra = TIEMPO_TRANSBORDO if i > 0 else timedelta(0)
                    seg_calc['Salida_dt'] = llegada_anterior_dt + tiempo_extra + frecuencia
                    seg_calc['Llegada_dt'] = seg_calc['Salida_dt'] + duracion
                
                if llegada_anterior_dt and seg_calc['Salida_dt'] < llegada_anterior_dt:
                    seg_calc['Salida_dt'] += timedelta(days=1)
                    seg_calc['Llegada_dt'] += timedelta(days=1)
                
                llegada_anterior_dt = seg_calc['Llegada_dt']
                
                seg_calc['icono'] = get_icon_for_compania(seg.get('Compania'), seg.get('Transporte'))
                seg_calc['Salida_str'] = seg_calc['Salida_dt'].strftime('%H:%M')
                seg_calc['Llegada_str'] = seg_calc['Llegada_dt'].strftime('%H:%M')
                seg_calc['Duracion_Tramo_Min'] = (seg_calc['Llegada_dt'] - seg_calc['Salida_dt']).total_seconds() / 60
                segmentos_calculados.append(seg_calc.to_dict())

            if not segmentos_calculados: continue

            salida_inicial_dt = segmentos_calculados[0]['Salida_dt']
            llegada_final_dt = segmentos_calculados[-1]['Llegada_dt']
            duracion_total = llegada_final_dt - salida_inicial_dt
            
            resultados_procesados.append({
                "segmentos": segmentos_calculados,
                "precio_total": sum(s.get('Precio', 0) for s in ruta),
                "llegada_final_dt_obj": llegada_final_dt,
                "hora_llegada_final": llegada_final_dt.time(),
                "duracion_total_str": format_timedelta(duracion_total)
            })
        except Exception as e:
            # print(f"Ruta descartada: {e}") # Descomentar para depuración
            pass

    if resultados_procesados:
        resultados_procesados.sort(key=lambda x: x['llegada_final_dt_obj'])

    return render_template("resultado.html", origen=origen, destino=destino, resultados=resultados_procesados)

if __name__ == "__main__":
    app.run(debug=True)

