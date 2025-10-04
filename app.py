def calculate_route_times(ruta_series_list, desde_ahora_check, now):
    try:
        segmentos = []
        for s in ruta_series_list:
            if isinstance(s, dict):
                segmentos.append(s.copy())
            elif hasattr(s, 'to_dict'):
                segmentos.append(s.to_dict())
            else:
                segmentos.append(dict(s))
        
        TIEMPO_TRANSBORDO = timedelta(minutes=10)
        
        # Caso especial: ruta de un solo segmento con frecuencia
        if len(segmentos) == 1 and segmentos[0].get('Tipo_Horario') == 'Frecuencia':
            dur_min = float(segmentos[0].get('Duracion_Trayecto_Min', 0))
            duracion = timedelta(minutes=dur_min)
            seg_dict = segmentos[0].copy()
            seg_dict.update({
                'icono': get_icon_for_compania(seg_dict.get('Compania')), 
                'Salida_str': "A tu aire", 
                'Llegada_str': "", 
                'Duracion_Tramo_Min': dur_min, 
                'Salida_dt': now
            })
            h_primer_str = seg_dict.get('H_Primer', '')
            h_ultim_str = seg_dict.get('H_Ultim', '')
            if h_primer_str and h_ultim_str:
                try:
                    h_primer = datetime.strptime(h_primer_str, '%H:%M').time()
                    h_ultim = datetime.strptime(h_ultim_str, '%H:%M').time()
                    hora_actual = now.time()
                    if h_primer > h_ultim:
                        if not (hora_actual >= h_primer or hora_actual <= h_ultim):
                            seg_dict['aviso_horario'] = 'FUERA DE HORARIO'
                    else:
                        if not (h_primer <= hora_actual <= h_ultim):
                            seg_dict['aviso_horario'] = 'FUERA DE HORARIO'
                except: 
                    pass
            return {
                "segmentos": [seg_dict], 
                "precio_total": float(seg_dict.get('Precio', 0)), 
                "llegada_final_dt_obj": now, 
                "hora_llegada_final": "Flexible", 
                "duracion_total_str": format_timedelta(duracion)
            }

        # Encontrar índice ancla (primer segmento con horario fijo)
        anchor_index = next((i for i, s in enumerate(segmentos) if 'Salida_dt' in s and pd.notna(s.get('Salida_dt'))), -1)
        
        if anchor_index != -1:
            # CORREGIDO: Calcular hacia atrás desde el ancla
            llegada_siguiente_dt = segmentos[anchor_index]['Salida_dt']
            for i in range(anchor_index - 1, -1, -1):
                dur_min = float(segmentos[i].get('Duracion_Trayecto_Min', 0))
                dur = timedelta(minutes=dur_min)
                segmentos[i]['Llegada_dt'] = llegada_siguiente_dt - TIEMPO_TRANSBORDO
                segmentos[i]['Salida_dt'] = segmentos[i]['Llegada_dt'] - dur
                llegada_siguiente_dt = segmentos[i]['Salida_dt']
            
            # CORREGIDO: Calcular hacia adelante desde el ancla
            # Asegurarse de que el ancla tenga Llegada_dt calculada
            if 'Llegada_dt' not in segmentos[anchor_index] or pd.isna(segmentos[anchor_index].get('Llegada_dt')):
                dur_min = float(segmentos[anchor_index].get('Duracion_Trayecto_Min', 0))
                dur = timedelta(minutes=dur_min)
                segmentos[anchor_index]['Llegada_dt'] = segmentos[anchor_index]['Salida_dt'] + dur
            
            llegada_anterior_dt = segmentos[anchor_index]['Llegada_dt']
            
            for i in range(anchor_index + 1, len(segmentos)):
                dur_min = float(segmentos[i].get('Duracion_Trayecto_Min', 0))
                dur = timedelta(minutes=dur_min)
                
                if pd.notna(llegada_anterior_dt):
                    segmentos[i]['Salida_dt'] = llegada_anterior_dt + TIEMPO_TRANSBORDO
                    segmentos[i]['Llegada_dt'] = segmentos[i]['Salida_dt'] + dur
                    llegada_anterior_dt = segmentos[i]['Llegada_dt']
                else:
                    segmentos[i]['Salida_dt'] = pd.NaT
                    segmentos[i]['Llegada_dt'] = pd.NaT
                    llegada_anterior_dt = pd.NaT
        else: 
            # Sin ancla: calcular desde el inicio
            llegada_anterior_dt = None
            start_time = now if desde_ahora_check else datetime.combine(now.date(), time(7, 0))
            
            for i, seg in enumerate(segmentos):
                dur_min = float(seg.get('Duracion_Trayecto_Min', 0))
                dur = timedelta(minutes=dur_min)
                
                if i == 0:
                    seg['Salida_dt'] = start_time
                elif pd.notna(llegada_anterior_dt):
                    seg['Salida_dt'] = llegada_anterior_dt + TIEMPO_TRANSBORDO
                else:
                    seg['Salida_dt'] = pd.NaT
                
                if pd.notna(seg.get('Salida_dt')):
                    seg['Llegada_dt'] = seg['Salida_dt'] + dur
                else:
                    seg['Llegada_dt'] = pd.NaT
                
                llegada_anterior_dt = seg.get('Llegada_dt')
        
        # Validar que todos los segmentos tienen tiempos
        if any(pd.isna(s.get('Salida_dt')) or pd.isna(s.get('Llegada_dt')) for s in segmentos):
            return None

        primera_salida_dt = segmentos[0]['Salida_dt']
        segmentos_formateados = []
        
        for seg in segmentos:
            seg_dict = seg.copy()
            salida_dt = seg['Salida_dt']
            
            # Validar horarios de frecuencia MEJORADO
            if seg.get('Tipo_Horario') == 'Frecuencia':
                hora_salida = salida_dt.time()
                
                # Buscar filas coincidentes en la BD original
                rutas_coincidentes = rutas_df_global[
                    (rutas_df_global['Origen'] == seg.get('Origen')) &
                    (rutas_df_global['Destino'] == seg.get('Destino')) &
                    (rutas_df_global['Tipo_Horario'] == 'Frecuencia')
                ]
                
                # Si hay compañía específica, filtrar también
                if pd.notna(seg.get('Compania')) and str(seg.get('Compania')).strip() != '':
                    rutas_coincidentes = rutas_coincidentes[
                        rutas_df_global['Compania'] == seg.get('Compania')
                    ]
                
                dentro_de_horario = False
                
                # Validar contra todos los rangos encontrados
                for _, ruta in rutas_coincidentes.iterrows():
                    h_primer_str = ruta.get('H_Primer', '')
                    h_ultim_str = ruta.get('H_Ultim', '')
                    
                    if h_primer_str and h_ultim_str:
                        try:
                            h_primer = datetime.strptime(str(h_primer_str), '%H:%M').time()
                            h_ultim = datetime.strptime(str(h_ultim_str), '%H:%M').time()
                            
                            # Rango que cruza medianoche
                            if h_primer > h_ultim:
                                if hora_salida >= h_primer or hora_salida <= h_ultim:
                                    dentro_de_horario = True
                                    break
                            # Rango normal
                            else:
                                if h_primer <= hora_salida <= h_ultim:
                                    dentro_de_horario = True
                                    break
                        except:
                            pass
                
                # Solo marcar si encontramos rutas coincidentes pero ninguna cubre la hora
                if not dentro_de_horario and rutas_coincidentes.shape[0] > 0:
                    seg_dict['aviso_horario'] = 'FUERA DE HORARIO'
            
            seg_dict.update({
                'icono': get_icon_for_compania(seg_dict.get('Compania')), 
                'Salida_str': salida_dt.strftime('%H:%M'), 
                'Llegada_str': seg['Llegada_dt'].strftime('%H:%M'), 
                'Duracion_Tramo_Min': (seg['Llegada_dt'] - salida_dt).total_seconds() / 60,
                'Salida_dt': salida_dt
            })
            segmentos_formateados.append(seg_dict)
        
        llegada_final_dt_obj = segmentos[-1]['Llegada_dt']
        precio_total = sum(float(s.get('Precio', 0)) for s in segmentos)

        return {
            "segmentos": segmentos_formateados,
            "precio_total": precio_total,
            "llegada_final_dt_obj": llegada_final_dt_obj,
            "hora_llegada_final": llegada_final_dt_obj.time(),
            "duracion_total_str": format_timedelta(llegada_final_dt_obj - primera_salida_dt)
        }
    except Exception as e:
        print(f"ERROR en calculate_route_times: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)# Fichero: app.py (Versión corregida completa)
from flask import Flask, render_template, request
import pandas as pd
import json
import random
from datetime import datetime, timedelta, time
import pytz
import requests
import io
from collections import defaultdict
import os

app = Flask(__name__)

# --- CONFIGURACIÓN ---
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
    rutas_df_global = pd.read_csv(csv_data_io, dtype=str).fillna('')
    column_mapping = {'Parada': 'Parada_Origen', 'Parada.1': 'Parada_Destino'}
    rutas_df_global.rename(columns=column_mapping, inplace=True)
    rutas_df_global.columns = rutas_df_global.columns.str.strip()
    if 'Compañía' in rutas_df_global.columns:
        rutas_df_global.rename(columns={'Compañía': 'Compania'}, inplace=True)
    for col in ['Duracion_Trayecto_Min', 'Frecuencia_Min']:
        if col in rutas_df_global.columns:
            rutas_df_global[col] = clean_minutes_column(rutas_df_global[col])
    if 'Precio' in rutas_df_global.columns:
        rutas_df_global['Precio'] = rutas_df_global['Precio'].astype(str).str.replace(',', '.').str.replace('€', '').str.strip()
    rutas_df_global['Precio'] = pd.to_numeric(rutas_df_global['Precio'], errors='coerce').fillna(0)
    print(f"✓ Datos cargados correctamente: {len(rutas_df_global)} rutas")
except Exception as e:
    print(f"--- ERROR CRÍTICO EN CARGA DE DATOS: {e} ---")
    rutas_df_global = pd.DataFrame()

# --- Carga de frases motivadoras ---
try:
    with open("frases_motivadoras.json", "r", encoding="utf-8") as f:
        frases = json.load(f)
    print(f"✓ Frases motivadoras cargadas: {len(frases)} frases")
except Exception as e:
    print(f"⚠ No se pudieron cargar frases motivadoras: {e}")
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
    try:
        form_data = request.form.to_dict()
        origen = form_data.get("origen")
        destino = form_data.get("destino")
        
        print(f"\n{'='*60}")
        print(f"→ BÚSQUEDA: {origen} → {destino}")
        print(f"  Filtros recibidos: {form_data}")
        
        origenes_disponibles = rutas_df_global['Origen'].unique()
        destinos_disponibles = rutas_df_global['Destino'].unique()
        print(f"  ¿'{origen}' existe como origen? {origen in origenes_disponibles}")
        print(f"  ¿'{destino}' existe como destino? {destino in destinos_disponibles}")
        
        if origen not in origenes_disponibles:
            print(f"  ⚠️ PROBLEMA: '{origen}' no encontrado en orígenes")
            print(f"  Orígenes similares: {[o for o in origenes_disponibles if origen.lower() in o.lower() or o.lower() in origen.lower()]}")
        if destino not in destinos_disponibles:
            print(f"  ⚠️ PROBLEMA: '{destino}' no encontrado en destinos")
            print(f"  Destinos similares: {[d for d in destinos_disponibles if destino.lower() in d.lower() or d.lower() in destino.lower()]}")
        
        tz = pytz.timezone('Europe/Madrid')
        now_aware = datetime.now(tz)
        now = now_aware.replace(tzinfo=None)

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
            is_weekday = target_weekday < 5; is_saturday = target_weekday == 5; is_sunday = target_weekday == 6
            mask = (rutas_hoy_df['Dias'] == 'L-D') | (is_weekday & (rutas_hoy_df['Dias'] == 'L-V')) | ((is_saturday or is_sunday) & (rutas_hoy_df['Dias'] == 'S-D')) | (is_saturday & (rutas_hoy_df['Dias'] == 'S')) | (is_sunday & (rutas_hoy_df['Dias'] == 'D'))
            rutas_hoy_df = rutas_hoy_df[mask]
        
        lugares_a_evitar = []
        if form_data.get('evitar_sj'): lugares_a_evitar.append('Sta. Justa')
        if form_data.get('evitar_pa'): lugares_a_evitar.append('Plz. Armas')
        print(f"  Lugares a evitar: {lugares_a_evitar}")

        candidatos_plantilla = find_all_routes_intelligently(origen, destino, rutas_hoy_df, lugares_a_evitar)
        print(f"  Candidatos encontrados: {len(candidatos_plantilla)}")
        
        rutas_fijas_df = rutas_hoy_df[rutas_hoy_df['Tipo_Horario'] == 'Fijo'].copy()
        if not rutas_fijas_df.empty:
            today_date = now.date()
            salida_times = pd.to_datetime(rutas_fijas_df['Salida'], format='%H:%M', errors='coerce').dt.time
            llegada_times = pd.to_datetime(rutas_fijas_df['Llegada'], format='%H:%M', errors='coerce').dt.time
            rutas_fijas_df['Salida_dt'] = salida_times.apply(lambda t: datetime.combine(today_date, t) if pd.notna(t) else pd.NaT)
            rutas_fijas_df['Llegada_dt'] = llegada_times.apply(lambda t: datetime.combine(today_date, t) if pd.notna(t) else pd.NaT)
            rutas_fijas_df.dropna(subset=['Salida_dt', 'Llegada_dt'], inplace=True)
        
        candidatos_expandidos = []
        if candidatos_plantilla:
            for ruta_plantilla in candidatos_plantilla:
                ruta_plantilla = [seg if isinstance(seg, dict) else seg.to_dict() if hasattr(seg, 'to_dict') else dict(seg) for seg in ruta_plantilla]
                
                if all(s.get('Tipo_Horario') == 'Frecuencia' for s in ruta_plantilla):
                    candidatos_expandidos.append(ruta_plantilla)
                    continue
                indices_fijos = [i for i, seg in enumerate(ruta_plantilla) if seg.get('Tipo_Horario') == 'Fijo']
                if not indices_fijos: continue
                
                idx_ancla = indices_fijos[0]
                ancla_plantilla = ruta_plantilla[idx_ancla]
                
                mask = (rutas_fijas_df['Origen'] == ancla_plantilla.get('Origen')) & (rutas_fijas_df['Destino'] == ancla_plantilla.get('Destino'))
                if pd.notna(ancla_plantilla.get('Compania')) and ancla_plantilla.get('Compania') != '': mask &= (rutas_fijas_df['Compania'] == ancla_plantilla.get('Compania'))
                if pd.notna(ancla_plantilla.get('Transporte')) and ancla_plantilla.get('Transporte') != '': mask &= (rutas_fijas_df['Transporte'] == ancla_plantilla.get('Transporte'))
                
                posibles_anclas = rutas_fijas_df[mask]
                for _, ancla_real in posibles_anclas.iterrows():
                    nueva_ruta = list(ruta_plantilla)
                    nueva_ruta[idx_ancla] = ancla_real.to_dict()
                    candidatos_expandidos.append(nueva_ruta)
        
        print(f"  Candidatos expandidos: {len(candidatos_expandidos)}")
        
        resultados_procesados = []
        for ruta in candidatos_expandidos:
            is_desde_ahora = form_data.get('desde_ahora') and dia_seleccionado == 'hoy'
            resultado = calculate_route_times(ruta, is_desde_ahora, now)
            if resultado: resultados_procesados.append(resultado)
        
        print(f"  Resultados procesados: {len(resultados_procesados)}")
        
        if len(resultados_procesados) > 10:
            companias_encontradas = set()
            for r in resultados_procesados:
                ruta_companias = " → ".join([seg.get('Compania', 'N/A') for seg in r['segmentos']])
                companias_encontradas.add(ruta_companias)
            print(f"  Combinaciones de compañías encontradas: {len(companias_encontradas)}")
            for combo in list(companias_encontradas)[:5]:
                print(f"    - {combo}")
        
        if form_data.get('desde_ahora') and dia_seleccionado == 'hoy':
            ahora_naive = now.replace(tzinfo=None)
            resultados_procesados = [r for r in resultados_procesados if r['hora_llegada_final'] == 'Flexible' or (r.get('segmentos') and 'Salida_dt' in r['segmentos'][0] and r['segmentos'][0]['Salida_dt'] >= ahora_naive)]
        
        if form_data.get('salir_despues_check'):
            try:
                hora_salida = int(form_data.get('salir_despues_hora', 7))
                minuto_salida = int(form_data.get('salir_despues_minuto', 0))
                hora_minima = time(hora_salida, minuto_salida)
                print(f"  Filtro salir después de: {hora_minima}")
                resultados_procesados = [r for r in resultados_procesados if r['hora_llegada_final'] == 'Flexible' or (isinstance(r.get('hora_llegada_final'), time) and r['segmentos'][0]['Salida_dt'].time() >= hora_minima)]
            except Exception as e:
                print(f"  Error aplicando filtro salir_despues: {e}")
        
        if form_data.get('llegar_antes_check'):
            try:
                hora_llegada = int(form_data.get('llegar_antes_hora', 9))
                minuto_llegada = int(form_data.get('llegar_antes_minuto', 0))
                hora_maxima = time(hora_llegada, minuto_llegada)
                print(f"  Filtro llegar antes de: {hora_maxima}")
                resultados_procesados = [r for r in resultados_procesados if r['hora_llegada_final'] == 'Flexible' or (isinstance(r.get('hora_llegada_final'), time) and r['hora_llegada_final'] <= hora_maxima)]
            except Exception as e:
                print(f"  Error aplicando filtro llegar_antes: {e}")

        if resultados_procesados:
            resultados_unicos = {}
            for r in resultados_procesados:
                companias = "-".join([seg.get('Compania', '') for seg in r['segmentos']])
                clave = f"{r['segmentos'][0]['Salida_str']}-{r['duracion_total_str']}-{companias}"
                if clave not in resultados_unicos:
                    resultados_unicos[clave] = r
            print(f"  Antes de deduplicar: {len(resultados_procesados)}, después: {len(resultados_unicos)}")
            resultados_procesados = sorted(list(resultados_unicos.values()), key=lambda x: x.get('llegada_final_dt_obj', datetime.max))
        
        print(f"  ✓ Resultados finales: {len(resultados_procesados)}")
        
        return render_template("resultado.html", origen=origen, destino=destino, resultados=resultados_procesados, filtros=form_data, dia_semana=nombre_dia)

    except Exception as e:
        print(f"ERROR INESPERADO EN LA RUTA /buscar: {e}")
        import traceback
        traceback.print_exc()
        return f"Ha ocurrido un error interno en el servidor: {e}", 500

def find_all_routes_intelligently(origen, destino, df, lugares_a_evitar):
    rutas_por_origen = defaultdict(list)
    for _, row in df.iterrows():
        rutas_por_origen[row['Origen']].append(row.to_dict())
    
    print(f"\n  🔍 Iniciando búsqueda BFS:")
    print(f"     Lugares disponibles desde '{origen}': {len(rutas_por_origen.get(origen, []))}")
    if origen in rutas_por_origen:
        destinos_unicos = list(set([r['Destino'] for r in rutas_por_origen[origen]]))
        print(f"     Destinos únicos desde '{origen}': {destinos_unicos}")
    else:
        print(f"     ⚠️ No hay rutas que salgan de '{origen}'")
    
    lugares_con_destino = [lugar for lugar, rutas in rutas_por_origen.items() 
                          if any(r['Destino'] == destino for r in rutas)]
    print(f"     Lugares desde donde se puede llegar a '{destino}': {lugares_con_destino}")
    
    rutas_encontradas = []
    cola = [([r], {origen, r['Destino']}) for r in rutas_por_origen.get(origen, [])]
    
    print(f"     Cola inicial: {len(cola)} rutas")
    
    primeros_destinos = list(set([r['Destino'] for r in rutas_por_origen.get(origen, [])]))[:5]
    print(f"     Explorando desde: {primeros_destinos}...")
    
    iteraciones = 0
    max_iteraciones = 1000
    
    while cola and iteraciones < max_iteraciones:
        iteraciones += 1
        ruta_actual, lugares_visitados = cola.pop(0)
        ultimo_tramo = ruta_actual[-1]
        lugar_actual = ultimo_tramo['Destino']
        
        if lugar_actual == destino:
            rutas_encontradas.append(ruta_actual)
            continue
            
        if len(ruta_actual) >= 3:
            continue
            
        if lugar_actual in lugares_a_evitar:
            continue

        for siguiente_tramo in rutas_por_origen.get(lugar_actual, []):
            proximo_destino = siguiente_tramo['Destino']
            
            if proximo_destino in lugares_visitados:
                continue
            
            nueva_ruta = ruta_actual + [siguiente_tramo]
            nuevos_visitados = lugares_visitados | {proximo_destino}
            cola.append((nueva_ruta, nuevos_visitados))
    
    print(f"     🎯 Total de rutas encontradas: {len(rutas_encontradas)}")
    print(f"{'='*60}\n")
    return rutas_encontradas

def calculate_route_times(ruta_series_list, desde_ahora_check, now):
    try:
        segmentos = []
        for s in ruta_series_list:
            if isinstance(s, dict):
                segmentos.append(s.copy())
            elif hasattr(s, 'to_dict'):
                segmentos.append(s.to_dict())
            else:
                segmentos.append(dict(s))
        
        TIEMPO_TRANSBORDO = timedelta(minutes=10)
        
        # Caso especial: ruta de un solo segmento con frecuencia
        if len(segmentos) == 1 and segmentos[0].get('Tipo_Horario') == 'Frecuencia':
            dur_min = float(segmentos[0].get('Duracion_Trayecto_Min', 0))
            duracion = timedelta(minutes=dur_min)
            seg_dict = segmentos[0].copy()
            seg_dict.update({
                'icono': get_icon_for_compania(seg_dict.get('Compania')), 
                'Salida_str': "A tu aire", 
                'Llegada_str': "", 
                'Duracion_Tramo_Min': dur_min, 
                'Salida_dt': now
            })
            h_primer_str = seg_dict.get('H_Primer', '')
            h_ultim_str = seg_dict.get('H_Ultim', '')
            if h_primer_str and h_ultim_str:
                try:
                    h_primer = datetime.strptime(h_primer_str, '%H:%M').time()
                    h_ultim = datetime.strptime(h_ultim_str, '%H:%M').time()
                    hora_actual = now.time()
                    if h_primer > h_ultim:
                        if not (hora_actual >= h_primer or hora_actual <= h_ultim):
                            seg_dict['aviso_horario'] = 'FUERA DE HORARIO'
                    else:
                        if not (h_primer <= hora_actual <= h_ultim):
                            seg_dict['aviso_horario'] = 'FUERA DE HORARIO'
                except: 
                    pass
            return {
                "segmentos": [seg_dict], 
                "precio_total": float(seg_dict.get('Precio', 0)), 
                "llegada_final_dt_obj": now, 
                "hora_llegada_final": "Flexible", 
                "duracion_total_str": format_timedelta(duracion)
            }

        # Encontrar índice ancla (primer segmento con horario fijo)
        anchor_index = next((i for i, s in enumerate(segmentos) if 'Salida_dt' in s and pd.notna(s.get('Salida_dt'))), -1)
        
        if anchor_index != -1:
            # CORREGIDO: Calcular hacia atrás desde el ancla
            llegada_siguiente_dt = segmentos[anchor_index]['Salida_dt']
            for i in range(anchor_index - 1, -1, -1):
                dur_min = float(segmentos[i].get('Duracion_Trayecto_Min', 0))
                dur = timedelta(minutes=dur_min)
                segmentos[i]['Llegada_dt'] = llegada_siguiente_dt - TIEMPO_TRANSBORDO
                segmentos[i]['Salida_dt'] = segmentos[i]['Llegada_dt'] - dur
                llegada_siguiente_dt = segmentos[i]['Salida_dt']
            
            # CORREGIDO: Calcular hacia adelante desde el ancla
            # Asegurarse de que el ancla tenga Llegada_dt calculada
            if 'Llegada_dt' not in segmentos[anchor_index] or pd.isna(segmentos[anchor_index].get('Llegada_dt')):
                dur_min = float(segmentos[anchor_index].get('Duracion_Trayecto_Min', 0))
                dur = timedelta(minutes=dur_min)
                segmentos[anchor_index]['Llegada_dt'] = segmentos[anchor_index]['Salida_dt'] + dur
            
            llegada_anterior_dt = segmentos[anchor_index]['Llegada_dt']
            
            for i in range(anchor_index + 1, len(segmentos)):
                dur_min = float(segmentos[i].get('Duracion_Trayecto_Min', 0))
                dur = timedelta(minutes=dur_min)
                
                if pd.notna(llegada_anterior_dt):
                    segmentos[i]['Salida_dt'] = llegada_anterior_dt + TIEMPO_TRANSBORDO
                    segmentos[i]['Llegada_dt'] = segmentos[i]['Salida_dt'] + dur
                    llegada_anterior_dt = segmentos[i]['Llegada_dt']
                else:
                    segmentos[i]['Salida_dt'] = pd.NaT
                    segmentos[i]['Llegada_dt'] = pd.NaT
                    llegada_anterior_dt = pd.NaT
        else: 
            # Sin ancla: calcular desde el inicio
            llegada_anterior_dt = None
            start_time = now if desde_ahora_check else datetime.combine(now.date(), time(7, 0))
            
            for i, seg in enumerate(segmentos):
                dur_min = float(seg.get('Duracion_Trayecto_Min', 0))
                dur = timedelta(minutes=dur_min)
                
                if i == 0:
                    seg['Salida_dt'] = start_time
                elif pd.notna(llegada_anterior_dt):
                    seg['Salida_dt'] = llegada_anterior_dt + TIEMPO_TRANSBORDO
                else:
                    seg['Salida_dt'] = pd.NaT
                
                if pd.notna(seg.get('Salida_dt')):
                    seg['Llegada_dt'] = seg['Salida_dt'] + dur
                else:
                    seg['Llegada_dt'] = pd.NaT
                
                llegada_anterior_dt = seg.get('Llegada_dt')
        
        # Validar que todos los segmentos tienen tiempos
        if any(pd.isna(s.get('Salida_dt')) or pd.isna(s.get('Llegada_dt')) for s in segmentos):
            return None

        primera_salida_dt = segmentos[0]['Salida_dt']
        segmentos_formateados = []
        
        for seg in segmentos:
            seg_dict = seg.copy()
            salida_dt = seg['Salida_dt']
            
            # Validar horarios de frecuencia MEJORADO
            if seg.get('Tipo_Horario') == 'Frecuencia':
                hora_salida = salida_dt.time()
                
                # Buscar filas coincidentes en la BD original
                rutas_coincidentes = rutas_df_global[
                    (rutas_df_global['Origen'] == seg.get('Origen')) &
                    (rutas_df_global['Destino'] == seg.get('Destino')) &
                    (rutas_df_global['Tipo_Horario'] == 'Frecuencia')
                ]
                
                # Si hay compañía específica, filtrar también
                if pd.notna(seg.get('Compania')) and str(seg.get('Compania')).strip() != '':
                    rutas_coincidentes = rutas_coincidentes[
                        rutas_df_global['Compania'] == seg.get('Compania')
                    ]
                
                dentro_de_horario = False
                
                # Validar contra todos los rangos encontrados
                for _, ruta in rutas_coincidentes.iterrows():
                    h_primer_str = ruta.get('H_Primer', '')
                    h_ultim_str = ruta.get('H_Ultim', '')
                    
                    if h_primer_str and h_ultim_str:
                        try:
                            h_primer = datetime.strptime(str(h_primer_str), '%H:%M').time()
                            h_ultim = datetime.strptime(str(h_ultim_str), '%H:%M').time()
                            
                            # Rango que cruza medianoche
                            if h_primer > h_ultim:
                                if hora_salida >= h_primer or hora_salida <= h_ultim:
                                    dentro_de_horario = True
                                    break
                            # Rango normal
                            else:
                                if h_primer <= hora_salida <= h_ultim:
                                    dentro_de_horario = True
                                    break
                        except:
                            pass
                
                # Solo marcar si encontramos rutas coincidentes pero ninguna cubre la hora
                if not dentro_de_horario and rutas_coincidentes.shape[0] > 0:
                    seg_dict['aviso_horario'] = 'FUERA DE HORARIO'
            
            seg_dict.update({
                'icono': get_icon_for_compania(seg_dict.get('Compania')), 
                'Salida_str': salida_dt.strftime('%H:%M'), 
                'Llegada_str': seg['Llegada_dt'].strftime('%H:%M'), 
                'Duracion_Tramo_Min': (seg['Llegada_dt'] - salida_dt).total_seconds() / 60,
                'Salida_dt': salida_dt
            })
            segmentos_formateados.append(seg_dict)
        
        llegada_final_dt_obj = segmentos[-1]['Llegada_dt']
        precio_total = sum(float(s.get('Precio', 0)) for s in segmentos)

        return {
            "segmentos": segmentos_formateados,
            "precio_total": precio_total,
            "llegada_final_dt_obj": llegada_final_dt_obj,
            "hora_llegada_final": llegada_final_dt_obj.time(),
            "duracion_total_str": format_timedelta(llegada_final_dt_obj - primera_salida_dt)
        }
    except Exception as e:
        print(f"ERROR en calculate_route_times: {e}")
        import traceback
        traceback.print_exc()
        return None
