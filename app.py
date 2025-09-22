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

    # Pre-procesar rutas fijas
    rutas_fijas = rutas_df_global[rutas_df_global['Tipo_Horario'] == 'Fijo'].copy()
    if not rutas_fijas.empty:
        rutas_fijas['Salida_dt'] = pd.to_datetime(rutas_fijas['Salida'], format='%H:%M:%S', errors='coerce').dt.to_pydatetime()
        rutas_fijas['Llegada_dt'] = pd.to_datetime(rutas_fijas['Llegada'], format='%H:%M:%S', errors='coerce').dt.to_pydatetime()
        rutas_fijas.dropna(subset=['Salida_dt', 'Llegada_dt'], inplace=True)

    # --- BÚSQUEDA DE CANDIDATOS ---
    candidatos = []
    # 1. Rutas Directas
    for _, ruta in rutas_df_global[(rutas_df_global['Origen'] == origen) & (rutas_df_global['Destino'] == destino)].iterrows():
        candidatos.append([ruta])
    # 2. Rutas de 2 tramos
    for _, tramo1 in rutas_df_global[rutas_df_global['Origen'] == origen].iterrows():
        for _, tramo2 in rutas_df_global[(rutas_df_global['Origen'] == tramo1['Destino']) & (rutas_df_global['Destino'] == destino)].iterrows():
            candidatos.append([tramo1, tramo2])
    # 3. Rutas de 3 tramos
    for _, tramo1 in rutas_df_global[rutas_df_global['Origen'] == origen].iterrows():
        pi1 = tramo1['Destino']
        if pi1 == destino: continue
        for _, tramo2 in rutas_df_global[rutas_df_global['Origen'] == pi1].iterrows():
            pi2 = tramo2['Destino']
            if pi2 == destino or pi2 == origen: continue
            for _, tramo3 in rutas_df_global[(rutas_df_global['Origen'] == pi2) & (rutas_df_global['Destino'] == destino)].iterrows():
                candidatos.append([tramo1, tramo2, tramo3])

    # --- PROCESAMIENTO Y VALIDACIÓN ---
    resultados_procesados = []
    for ruta in candidatos:
        try:
            segmentos, llegada_anterior_dt = [], None
            TIEMPO_TRANSBORDO = timedelta(minutes=10)
            filtro_hora = datetime.now().time() if desde_ahora_check else time(0, 0)

            # Bucle de cálculo de tiempos
            for i, seg in enumerate(ruta):
                seg_calc = seg.copy()
                
                # --- Lógica de cálculo para cada tipo ---
                if i == 0 and seg['Tipo_Horario'] == 'Frecuencia' and 'coche' in str(seg['Compania']).lower():
                    # Coche al inicio: se calcula hacia atrás
                    if len(ruta) == 1: # Viaje directo en coche
                        seg_calc['Salida_dt'] = datetime.now() # Hora simbólica
                        seg_calc['Llegada_dt'] = seg_calc['Salida_dt'] + timedelta(minutes=seg['Duracion_Trayecto_Min'])
                    else: # Coche + transbordo
                        siguiente_tramo_fijo = rutas_fijas.loc[ruta[i+1].name]
                        if siguiente_tramo_fijo['Salida_dt'].time() < filtro_hora: raise ValueError("El primer bus/tren ya ha salido")
                        duracion_coche = timedelta(minutes=seg['Duracion_Trayecto_Min'])
                        seg_calc['Llegada_dt'] = siguiente_tramo_fijo['Salida_dt']
                        seg_calc['Salida_dt'] = seg_calc['Llegada_dt'] - duracion_coche
                
                elif seg['Tipo_Horario'] == 'Fijo':
                    if seg.name not in rutas_fijas.index: raise ValueError("Ruta fija no disponible")
                    tramo_fijo = rutas_fijas.loc[seg.name]
                    if i == 0 and tramo_fijo['Salida_dt'].time() < filtro_hora: raise ValueError("El primer bus/tren ya ha salido")
                    if i > 0 and tramo_fijo['Salida_dt'] < llegada_anterior_dt + TIEMPO_TRANSBORDO: raise ValueError("No hay tiempo para el transbordo")
                    seg_calc['Salida_dt'], seg_calc['Llegada_dt'] = tramo_fijo['Salida_dt'], tramo_fijo['Llegada_dt']
                
                else: # Bus Urbano o Coche al final del trayecto
                    if i == 0: # Bus urbano al inicio
                        llegada_anterior_dt = datetime.combine(datetime.today(), filtro_hora)
                    
                    frecuencia = timedelta(minutes=seg['Frecuencia_Min'])
                    duracion = timedelta(minutes=seg['Duracion_Trayecto_Min'])
                    tiempo_extra = TIEMPO_TRANSBORDO if i > 0 else timedelta(0)
                    seg_calc['Salida_dt'] = llegada_anterior_dt + tiempo_extra + frecuencia
                    seg_calc['Llegada_dt'] = seg_calc['Salida_dt'] + duracion
                
                # Ajuste de medianoche
                if llegada_anterior_dt and seg_calc['Salida_dt'] < llegada_anterior_dt:
                    seg_calc['Salida_dt'] += timedelta(days=1); seg_calc['Llegada_dt'] += timedelta(days=1)
                
                llegada_anterior_dt = seg_calc['Llegada_dt']

                # Formateo para la vista
                seg_calc['icono'] = get_icon_for_compania(seg.get('Compania'))
                if len(ruta) == 1 and seg['Tipo_Horario'] == 'Frecuencia' and 'coche' in str(seg['Compania']).lower():
                    seg_calc['Salida_str'], seg_calc['Llegada_str'] = "A tu aire", ""
                else:
                    seg_calc['Salida_str'] = seg_calc['Salida_dt'].strftime('%H:%M')
                    seg_calc['Llegada_str'] = seg_calc['Llegada_dt'].strftime('%H:%M')
                seg_calc['Duracion_Tramo_Min'] = (seg_calc['Llegada_dt'] - seg_calc['Salida_dt']).total_seconds() / 60
                segmentos.append(seg_calc.to_dict())

            # Cálculo de totales
            salida_final = segmentos[0]['Salida_dt']
            llegada_final = segmentos[-1]['Llegada_dt']
            
            resultados_procesados.append({
                "segmentos": segmentos,
                "precio_total": sum(s.get('Precio', 0) for s in ruta),
                "llegada_final_dt_obj": llegada_final,
                "hora_llegada_final": llegada_final.time(),
                "duracion_total_str": format_timedelta(llegada_final - salida_final)
            })
        except Exception as e:
            # print(f"Ruta descartada: {clave_ruta} -> {e}")
            pass

    if resultados_procesados:
        resultados_procesados.sort(key=lambda x: x['llegada_final_dt_obj'])

    return render_template("resultado.html", origen=origen, destino=destino, resultados=resultados_procesados)

if __name__ == "__main__":
    app.run(debug=True)

