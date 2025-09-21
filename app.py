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
    
    # --- CONSTANTES ---
    TIEMPO_TRANSBORDO = timedelta(minutes=10)

    # Preparar DataFrames por tipo de horario
    rutas_fijas = rutas_df[rutas_df['Tipo_Horario'] == 'Fijo'].copy()
    if not rutas_fijas.empty:
        rutas_fijas['Salida_dt'] = pd.to_datetime(rutas_fijas['Salida'], format='%H:%M:%S', errors='coerce').dt.to_pydatetime()
        rutas_fijas['Llegada_dt'] = pd.to_datetime(rutas_fijas['Llegada'], format='%H:%M:%S', errors='coerce').dt.to_pydatetime()
        rutas_fijas.dropna(subset=['Salida_dt', 'Llegada_dt'], inplace=True)
        
        # Filtra rutas fijas si el checkbox está marcado
        if desde_ahora_check:
            ahora = datetime.now()
            rutas_fijas = rutas_fijas[rutas_fijas['Salida_dt'].apply(lambda x: x.time()) > ahora.time()]
    
    # --- LÓGICA DE BÚSQUEDA Y PROCESAMIENTO REESTRUCTURADA ---
    resultados_procesados = []
    rutas_procesadas_set = set()

    def procesar_y_anadir_ruta(ruta_series):
        clave_ruta = tuple(s.name for s in ruta_series)
        if clave_ruta in rutas_procesadas_set:
            return
        rutas_procesadas_set.add(clave_ruta)

        try:
            segmentos = []
            llegada_anterior_dt = None

            for i, seg in enumerate(ruta_series):
                seg_calc = seg.copy()

                # --- Cálculo de Tiempos ---
                if i == 0 and seg['Tipo_Horario'] == 'Frecuencia':
                     llegada_anterior_dt = datetime.now() if desde_ahora_check else datetime.combine(datetime.today(), time(0,0))
                
                if seg['Tipo_Horario'] == 'Flexible':
                    duracion = timedelta(minutes=seg['Duracion_Trayecto_Min'])
                    if i > 0: # Tramo final
                        seg_calc['Salida_dt'] = llegada_anterior_dt
                        seg_calc['Llegada_dt'] = seg_calc['Salida_dt'] + duracion
                    else: # Tramo inicial
                        siguiente_tramo = rutas_fijas.loc[ruta_series[i+1].name]
                        seg_calc['Llegada_dt'] = siguiente_tramo['Salida_dt']
                        seg_calc['Salida_dt'] = seg_calc['Llegada_dt'] - duracion
                elif seg['Tipo_Horario'] == 'Fijo':
                    tramo_fijo = rutas_fijas.loc[seg.name]
                    seg_calc['Salida_dt'] = tramo_fijo['Salida_dt']
                    seg_calc['Llegada_dt'] = tramo_fijo['Llegada_dt']
                elif seg['Tipo_Horario'] == 'Frecuencia':
                    frecuencia = timedelta(minutes=seg['Frecuencia_Min'])
                    duracion = timedelta(minutes=seg['Duracion_Trayecto_Min'])
                    seg_calc['Salida_dt'] = llegada_anterior_dt + frecuencia
                    seg_calc['Llegada_dt'] = seg_calc['Salida_dt'] + duracion
                
                if llegada_anterior_dt and seg_calc['Salida_dt'] < llegada_anterior_dt:
                    seg_calc['Salida_dt'] += timedelta(days=1)
                    seg_calc['Llegada_dt'] += timedelta(days=1)
                
                llegada_anterior_dt = seg_calc['Llegada_dt']
                
                # --- Formateo ---
                seg_calc['icono'] = get_icon_for_compania(seg.get('Compania'), seg.get('Transporte'))
                seg_calc['Salida_str'] = seg_calc['Salida_dt'].strftime('%H:%M')
                seg_calc['Llegada_str'] = seg_calc['Llegada_dt'].strftime('%H:%M')
                seg_calc['Duracion_Tramo_Min'] = (seg_calc['Llegada_dt'] - seg_calc['Salida_dt']).total_seconds() / 60
                segmentos.append(seg_calc.to_dict())

            # --- Cálculo de Totales ---
            duracion_total = segmentos[-1]['Llegada_dt'] - segmentos[0]['Salida_dt']
            
            resultados_procesados.append({
                "segmentos": segmentos,
                "precio_total": sum(s.get('Precio', 0) for s in ruta_series),
                "llegada_final_dt_obj": segmentos[-1]['Llegada_dt'],
                "hora_llegada_final": segmentos[-1]['Llegada_dt'].time(),
                "duracion_total_str": format_timedelta(duracion_total)
            })
        except Exception as e:
            print(f"Error procesando una ruta: {ruta_series} -> {e}")

    # --- BÚSQUEDA ---

    # 1. Rutas Directas (Fijas)
    directas = rutas_fijas[(rutas_fijas['Origen'] == origen) & (rutas_fijas['Destino'] == destino)]
    for _, ruta in directas.iterrows():
        procesar_y_anadir_ruta([ruta])

    # 2. Rutas de 2 Tramos (Público -> Público)
    tramos1 = rutas_fijas[rutas_fijas['Origen'] == origen]
    for _, tramo1 in tramos1.iterrows():
        punto_intermedio = tramo1['Destino']
        if punto_intermedio == destino: continue
        tramos2 = rutas_df[(rutas_df['Origen'] == punto_intermedio) & (rutas_df['Destino'] == destino)]
        for _, tramo2 in tramos2.iterrows():
            if tramo2['Tipo_Horario'] == 'Fijo' and tramo2.name in rutas_fijas.index:
                tramo2_fijo = rutas_fijas.loc[tramo2.name]
                if tramo1['Llegada_dt'] + TIEMPO_TRANSBORDO <= tramo2_fijo['Salida_dt']:
                    procesar_y_anadir_ruta([tramo1, tramo2])
            elif tramo2['Tipo_Horario'] in ['Frecuencia', 'Flexible']:
                 procesar_y_anadir_ruta([tramo1, tramo2])
    
    # 3. Rutas que empiezan con Coche
    tramos_coche = rutas_df[(rutas_df['Origen'] == origen) & (rutas_df['Tipo_Horario'] == 'Flexible')]
    for _, coche in tramos_coche.iterrows():
        estacion = coche['Destino']
        if estacion == destino: procesar_y_anadir_ruta([coche]); continue
        tramos1_pub = rutas_fijas[rutas_fijas['Origen'] == estacion]
        for _, tramo1_pub in tramos1_pub.iterrows():
            if tramo1_pub['Destino'] == destino:
                procesar_y_anadir_ruta([coche, tramo1_pub])
            else:
                # Coche + 2 Tramos
                pass 

    # 4. Rutas de Vuelta (Frecuencia -> ...)
    tramos1_freq = rutas_df[(rutas_df['Origen'] == origen) & (rutas_df['Tipo_Horario'] == 'Frecuencia')]
    for _, tramo1_freq in tramos1_freq.iterrows():
        punto_intermedio = tramo1_freq['Destino']
        if punto_intermedio == destino: continue
        tramos2_fijos = rutas_fijas[rutas_fijas['Origen'] == punto_intermedio]
        for _, tramo2_fijo in tramos2_fijos.iterrows():
             if tramo2_fijo['Destino'] == destino:
                 procesar_y_anadir_ruta([tramo1_freq, tramo2_fijo])
             else:
                 # Frecuencia + Fijo + Flexible/Fijo
                 pass

    # --- FINAL ---
    if resultados_procesados:
        resultados_procesados.sort(key=lambda x: x['llegada_final_dt_obj'])

    return render_template("resultado.html", origen=origen, destino=destino, resultados=resultados_procesados)

if __name__ == "__main__":
    app.run(debug=True)

