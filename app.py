from flask import Flask, render_template, request
import pandas as pd
import json
import random
from datetime import datetime, timedelta

app = Flask(__name__)

# --- Funciones de Ayuda ---
def get_icon_for_compania(compania):
    compania_lower = str(compania).lower()
    if 'urbano' in compania_lower: return '🚍'
    if 'damas' in compania_lower: return '🚌'
    if 'renfe' in compania_lower or 'tren' in compania_lower: return '🚆'
    if 'coche' in compania_lower: return '🚗'
    return '➡️'

def format_timedelta(td):
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    if hours > 0: return f"{hours}h {minutes}min"
    return f"{minutes}min"

# --- Carga de Datos ---
try:
    rutas_df = pd.read_excel("rutas.xlsx", engine="openpyxl")
    
    # --- LÍNEA DE DEPURACIÓN ---
    # Imprimirá las columnas exactas que se leen del Excel en los logs de Render.
    print(f"COLUMNAS DETECTADAS EN EXCEL: {rutas_df.columns.tolist()}")

    rutas_df.columns = rutas_df.columns.str.strip()
    # Asegurar que las columnas clave existen
    # CORRECCIÓN: Cambiado 'Compania' por 'Compañía' para que coincida con el Excel
    required_cols = ['Origen', 'Destino', 'Tipo_Horario', 'Compañía', 'Precio']
    for col in required_cols:
        if col not in rutas_df.columns:
            raise ValueError(f"Falta la columna requerida: {col}")
            
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
    resultados_finales = []
    
    # --- LÓGICA DE BÚSQUEDA ---
    TIEMPO_TRANSBORDO = timedelta(minutes=10)
    TIEMPO_COCHE_A_ESTACION = timedelta(minutes=10)

    rutas_fijas = rutas_df[rutas_df['Tipo_Horario'] == 'Fijo'].copy()
    if not rutas_fijas.empty:
        # Usamos .loc para evitar SettingWithCopyWarning
        rutas_fijas.loc[:, 'Salida_dt'] = pd.to_datetime(rutas_fijas['Salida'], format='%H:%M:%S', errors='coerce').dt.to_pydatetime()
        rutas_fijas.loc[:, 'Llegada_dt'] = pd.to_datetime(rutas_fijas['Llegada'], format='%H:%M:%S', errors='coerce').dt.to_pydatetime()
        rutas_fijas.dropna(subset=['Salida_dt', 'Llegada_dt'], inplace=True)
    
    # 1. RUTAS DIRECTAS (1 TRAMO)
    directas = rutas_fijas[(rutas_fijas['Origen'] == origen) & (rutas_fijas['Destino'] == destino)]
    for _, ruta in directas.iterrows():
        resultados_finales.append([ruta.to_dict()])

    # 2. RUTAS DE 2 TRAMOS (Fijo -> Fijo/Frecuencia)
    tramos1 = rutas_fijas[rutas_fijas['Origen'] == origen]
    for _, tramo1 in tramos1.iterrows():
        punto_intermedio = tramo1['Destino']
        tramos2 = rutas_df[(rutas_df['Origen'] == punto_intermedio) & (rutas_df['Destino'] == destino)]
        for _, tramo2 in tramos2.iterrows():
            if tramo2['Tipo_Horario'] == 'Fijo' and pd.notna(tramo2.get('Salida')):
                tramo2_dt = datetime.combine(datetime.today(), pd.to_datetime(tramo2['Salida'], format='%H:%M:%S', errors='coerce').time())
                if tramo1['Llegada_dt'] + TIEMPO_TRANSBORDO <= tramo2_dt:
                    resultados_finales.append([tramo1.to_dict(), tramo2.to_dict()])
            elif tramo2['Tipo_Horario'] == 'Frecuencia':
                resultados_finales.append([tramo1.to_dict(), tramo2.to_dict()])
    
    # 3. RUTAS QUE EMPIEZAN CON COCHE (Flexible -> Fijo -> ...)
    tramos_coche = rutas_df[(rutas_df['Origen'] == origen) & (rutas_df['Tipo_Horario'] == 'Flexible')]
    for _, coche in tramos_coche.iterrows():
        estacion = coche['Destino']
        duracion_coche = timedelta(minutes=coche['Duracion_Trayecto_Min'])
        
        tramos_fijos_desde_estacion = rutas_fijas[rutas_fijas['Origen'] == estacion]
        for _, tramo_fijo in tramos_fijos_desde_estacion.iterrows():
            # A. Ruta de 2 tramos: Coche -> Fijo
            if tramo_fijo['Destino'] == destino:
                coche_calculado = coche.copy()
                coche_calculado['Llegada_dt'] = tramo_fijo['Salida_dt'] - TIEMPO_COCHE_A_ESTACION
                coche_calculado['Salida_dt'] = coche_calculado['Llegada_dt'] - duracion_coche
                resultados_finales.append([coche_calculado.to_dict(), tramo_fijo.to_dict()])
            
            # B. Ruta de 3 tramos: Coche -> Fijo -> Fijo/Frecuencia
            punto_intermedio_2 = tramo_fijo['Destino']
            tramos_finales = rutas_df[(rutas_df['Origen'] == punto_intermedio_2) & (rutas_df['Destino'] == destino)]
            for _, tramo_final in tramos_finales.iterrows():
                 if tramo_final['Tipo_Horario'] == 'Fijo' and pd.notna(tramo_final.get('Salida')):
                    tramo_final_dt = datetime.combine(datetime.today(), pd.to_datetime(tramo_final['Salida'], format='%H:%M:%S', errors='coerce').time())
                    if tramo_fijo['Llegada_dt'] + TIEMPO_TRANSBORDO <= tramo_final_dt:
                        coche_calculado = coche.copy()
                        coche_calculado['Llegada_dt'] = tramo_fijo['Salida_dt'] - TIEMPO_COCHE_A_ESTACION
                        coche_calculado['Salida_dt'] = coche_calculado['Llegada_dt'] - duracion_coche
                        resultados_finales.append([coche_calculado.to_dict(), tramo_fijo.to_dict(), tramo_final.to_dict()])
                 elif tramo_final['Tipo_Horario'] == 'Frecuencia':
                    coche_calculado = coche.copy()
                    coche_calculado['Llegada_dt'] = tramo_fijo['Salida_dt'] - TIEMPO_COCHE_A_ESTACION
                    coche_calculado['Salida_dt'] = coche_calculado['Llegada_dt'] - duracion_coche
                    resultados_finales.append([coche_calculado.to_dict(), tramo_fijo.to_dict(), tramo_final.to_dict()])

    # --- PROCESAR Y FORMATEAR RESULTADOS ---
    resultados_procesados = []
    for ruta in resultados_finales:
        try:
            segmentos_calculados = []
            llegada_anterior_dt = None
            salida_inicial_dt = None
            
            for i, seg_dict in enumerate(ruta):
                seg_calc = seg_dict.copy()
                
                if seg_calc['Tipo_Horario'] == 'Fijo':
                    seg_calc['Salida_dt'] = pd.to_datetime(seg_calc['Salida'], errors='coerce').to_pydatetime() if not isinstance(seg_calc.get('Salida_dt'), datetime) else seg_calc['Salida_dt']
                    seg_calc['Llegada_dt'] = pd.to_datetime(seg_calc['Llegada'], errors='coerce').to_pydatetime() if not isinstance(seg_calc.get('Llegada_dt'), datetime) else seg_calc['Llegada_dt']

                elif seg_calc['Tipo_Horario'] == 'Frecuencia':
                    seg_calc['Salida_dt'] = llegada_anterior_dt + TIEMPO_TRANSBORDO
                    duracion_viaje = timedelta(minutes=seg_calc['Duracion_Trayecto_Min'])
                    espera_maxima = timedelta(minutes=seg_calc['Frecuencia_Min'])
                    seg_calc['Llegada_dt'] = seg_calc['Salida_dt'] + duracion_viaje + espera_maxima

                elif seg_calc['Tipo_Horario'] == 'Flexible':
                    pass # Los tiempos ya vienen calculados

                if llegada_anterior_dt and seg_calc.get('Salida_dt') and seg_calc['Salida_dt'] < llegada_anterior_dt:
                    seg_calc['Salida_dt'] += timedelta(days=1)
                    seg_calc['Llegada_dt'] += timedelta(days=1)
                if seg_calc.get('Llegada_dt') and seg_calc.get('Salida_dt') and seg_calc.get('Llegada_dt') < seg_calc.get('Salida_dt'):
                    seg_calc['Llegada_dt'] += timedelta(days=1)

                llegada_anterior_dt = seg_calc.get('Llegada_dt')
                if i == 0: salida_inicial_dt = seg_calc.get('Salida_dt')
                
                seg_calc['icono'] = get_icon_for_compania(seg_calc['Compañía'])
                seg_calc['Salida_str'] = seg_calc['Salida_dt'].strftime('%H:%M') if seg_calc.get('Salida_dt') else ''
                seg_calc['Llegada_str'] = seg_calc['Llegada_dt'].strftime('%H:%M') if seg_calc.get('Llegada_dt') else ''
                if seg_calc.get('Llegada_dt') and seg_calc.get('Salida_dt'):
                    seg_calc['Duracion_Tramo_Min'] = (seg_calc['Llegada_dt'] - seg_calc['Salida_dt']).total_seconds() / 60
                segmentos_calculados.append(seg_calc)

            if salida_inicial_dt and llegada_anterior_dt:
                llegada_final_dt = llegada_anterior_dt
                duracion_total = llegada_final_dt - salida_inicial_dt
                
                resultados_procesados.append({
                    "segmentos": segmentos_calculados,
                    "precio_total": sum(s.get('Precio', 0) for s in ruta),
                    "hora_llegada_final": llegada_final_dt.time(),
                    "tipo": "Directo" if len(ruta) == 1 else "Transbordo",
                    "duracion_total_str": format_timedelta(duracion_total)
                })
        except Exception as e:
            print(f"Error procesando una ruta: {e}")
            print(f"Ruta con problemas: {ruta}")


    if resultados_procesados:
        resultados_procesados.sort(key=lambda x: x['hora_llegada_final'])

    return render_template("resultado.html", origen=origen, destino=destino, resultados=resultados_procesados)

if __name__ == "__main__":
    app.run(debug=True)

