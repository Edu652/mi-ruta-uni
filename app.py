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
    
    rutas_encontradas = []
    
    # --- CONSTANTES ---
    TIEMPO_TRANSBORDO = timedelta(minutes=10)

    # Preparar DataFrames por tipo de horario
    rutas_fijas = rutas_df[rutas_df['Tipo_Horario'] == 'Fijo'].copy()
    if not rutas_fijas.empty:
        rutas_fijas['Salida_dt'] = pd.to_datetime(rutas_fijas['Salida'], format='%H:%M:%S', errors='coerce').dt.to_pydatetime()
        rutas_fijas['Llegada_dt'] = pd.to_datetime(rutas_fijas['Llegada'], format='%H:%M:%S', errors='coerce').dt.to_pydatetime()
        rutas_fijas.dropna(subset=['Salida_dt', 'Llegada_dt'], inplace=True)
        
        if desde_ahora_check:
            ahora = datetime.now()
            rutas_fijas = rutas_fijas[rutas_fijas['Salida_dt'].apply(lambda x: x.replace(year=ahora.year, month=ahora.month, day=ahora.day)) > ahora]

    # --- LÓGICA DE BÚSQUEDA CON SENTIDO COMÚN ---

    # 1. Rutas Directas (Fijas y Flexibles)
    directas = rutas_df[((rutas_df['Origen'] == origen) & (rutas_df['Destino'] == destino)) & ((rutas_df['Tipo_Horario'] == 'Fijo') | (rutas_df['Tipo_Horario'] == 'Flexible'))]
    for _, ruta in directas.iterrows():
        # Para que sea considerada, si es fija, debe estar en el dataframe filtrado por hora
        if ruta['Tipo_Horario'] == 'Fijo' and ruta.name not in rutas_fijas.index:
            continue
        rutas_encontradas.append([ruta])

    # 2. Rutas de 2 Tramos (Público -> Público)
    tramos1 = rutas_fijas[rutas_fijas['Origen'] == origen]
    for _, tramo1 in tramos1.iterrows():
        punto_intermedio = tramo1['Destino']
        if punto_intermedio == destino or punto_intermedio == origen: continue

        tramos2 = rutas_df[(rutas_df['Origen'] == punto_intermedio) & (rutas_df['Destino'] == destino)]
        for _, tramo2 in tramos2.iterrows():
            if tramo2['Tipo_Horario'] == 'Fijo' and tramo2.name in rutas_fijas.index:
                tramo2_fijo = rutas_fijas.loc[tramo2.name]
                if tramo1['Llegada_dt'] + TIEMPO_TRANSBORDO <= tramo2_fijo['Salida_dt']:
                    rutas_encontradas.append([tramo1, tramo2])
            elif tramo2['Tipo_Horario'] == 'Frecuencia':
                rutas_encontradas.append([tramo1, tramo2])

    # 3. Rutas que empiezan con Coche (Flexible -> Público -> ...)
    tramos_coche = rutas_df[(rutas_df['Origen'] == origen) & (rutas_df['Tipo_Horario'] == 'Flexible')]
    for _, coche in tramos_coche.iterrows():
        estacion = coche['Destino']
        if estacion == destino or estacion == origen: continue
        
        # A. Coche + 1 Tramo Público
        tramos_fijos_desde_estacion = rutas_fijas[(rutas_fijas['Origen'] == estacion) & (rutas_fijas['Destino'] == destino)]
        for _, tramo_fijo in tramos_fijos_desde_estacion.iterrows():
            rutas_encontradas.append([coche, tramo_fijo])
        
        # B. Coche + 2 Tramos Públicos
        tramos1_pub = rutas_fijas[rutas_fijas['Origen'] == estacion]
        for _, tramo1_pub in tramos1_pub.iterrows():
            punto_intermedio = tramo1_pub['Destino']
            if punto_intermedio == destino or punto_intermedio == estacion: continue

            tramos2_pub = rutas_df[(rutas_df['Origen'] == punto_intermedio) & (rutas_df['Destino'] == destino)]
            for _, tramo2_pub in tramos2_pub.iterrows():
                es_valido = False
                if tramo2_pub['Tipo_Horario'] == 'Fijo' and tramo2_pub.name in rutas_fijas.index:
                    tramo2_pub_fijo = rutas_fijas.loc[tramo2_pub.name]
                    if tramo1_pub['Llegada_dt'] + TIEMPO_TRANSBORDO <= tramo2_pub_fijo['Salida_dt']:
                        es_valido = True
                elif tramo2_pub['Tipo_Horario'] == 'Frecuencia':
                    es_valido = True
                if es_valido:
                    rutas_encontradas.append([coche, tramo1_pub, tramo2_pub])

    # --- PROCESAR Y FORMATEAR ---
    resultados_procesados = []
    for ruta in rutas_encontradas:
        try:
            segmentos_calculados = []
            llegada_anterior_dt = None
            
            for i, seg_series in enumerate(ruta):
                seg_calc = seg_series.copy()
                
                if seg_calc['Tipo_Horario'] == 'Flexible':
                    if len(ruta) > i + 1: # Si es parte de una ruta más larga
                        siguiente_tramo_fijo = rutas_fijas.loc[ruta[i+1].name]
                        salida_siguiente_dt = siguiente_tramo_fijo['Salida_dt']
                        duracion_coche = timedelta(minutes=seg_calc['Duracion_Trayecto_Min'])
                        seg_calc['Llegada_dt'] = salida_siguiente_dt
                        seg_calc['Salida_dt'] = seg_calc['Llegada_dt'] - duracion_coche
                    else: # Si es un viaje directo en coche
                        seg_calc['Salida_dt'] = datetime(1, 1, 1, 0, 0) 
                        seg_calc['Llegada_dt'] = datetime(2, 1, 1, 0, 0) # Para que no falle el cálculo de duración
                
                elif seg_calc['Tipo_Horario'] == 'Fijo':
                    tramo_fijo = rutas_fijas.loc[seg_series.name]
                    seg_calc['Salida_dt'] = tramo_fijo['Salida_dt']
                    seg_calc['Llegada_dt'] = tramo_fijo['Llegada_dt']

                elif seg_calc['Tipo_Horario'] == 'Frecuencia':
                    frecuencia = timedelta(minutes=seg_calc['Frecuencia_Min'])
                    duracion = timedelta(minutes=seg_calc['Duracion_Trayecto_Min'])
                    seg_calc['Salida_dt'] = llegada_anterior_dt + frecuencia
                    seg_calc['Llegada_dt'] = seg_calc['Salida_dt'] + duracion

                if llegada_anterior_dt and seg_calc.get('Salida_dt') < llegada_anterior_dt:
                     seg_calc['Salida_dt'] += timedelta(days=1)
                     seg_calc['Llegada_dt'] += timedelta(days=1)
                
                llegada_anterior_dt = seg_calc.get('Llegada_dt')
                
                seg_calc['icono'] = get_icon_for_compania(seg_calc.get('Compania'), seg_calc.get('Transporte'))

                if seg_calc['Tipo_Horario'] == 'Flexible' and len(ruta) == 1:
                    seg_calc['Salida_str'] = "A tu aire"
                    seg_calc['Llegada_str'] = ""
                    seg_calc['Duracion_Tramo_Min'] = seg_calc['Duracion_Trayecto_Min']
                else:
                    seg_calc['Salida_str'] = seg_calc['Salida_dt'].strftime('%H:%M')
                    seg_calc['Llegada_str'] = seg_calc['Llegada_dt'].strftime('%H:%M')
                    seg_calc['Duracion_Tramo_Min'] = (seg_calc['Llegada_dt'] - seg_calc['Salida_dt']).total_seconds() / 60
                
                segmentos_calculados.append(seg_calc.to_dict())

            salida_inicial_dt = segmentos_calculados[0]['Salida_dt']
            llegada_final_dt = segmentos_calculados[-1]['Llegada_dt']
            
            if salida_inicial_dt.year > 2000: # Si es una fecha real, no la de relleno
                llegada_final_dt = datetime(1, 1, 1, 0, 0)
                duracion_total_str = "Flexible"
            else:
                duracion_total = llegada_final_dt - salida_inicial_dt
                duracion_total_str = format_timedelta(duracion_total)

            resultados_procesados.append({
                "segmentos": segmentos_calculados,
                "precio_total": sum(s.get('Precio', 0) for s in ruta),
                "llegada_final_dt_obj": llegada_final_dt,
                "hora_llegada_final": llegada_final_dt.time(),
                "duracion_total_str": duracion_total_str
            })
        except Exception as e:
            print(f"Error procesando una ruta: {e}")

    if resultados_procesados:
        resultados_procesados.sort(key=lambda x: x['llegada_final_dt_obj'])

    return render_template("resultado.html", origen=origen, destino=destino, resultados=resultados_procesados)

if __name__ == "__main__":
    app.run(debug=True)

