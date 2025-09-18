from flask import Flask, render_template, request
import pandas as pd
import random
import json
from datetime import datetime, timedelta

app = Flask(__name__)

# Cargar datos
rutas = pd.read_excel('rutas.xlsx', engine='openpyxl')
with open('frases_motivadoras.json', 'r', encoding='utf-8') as f:
    frases = f.read().splitlines()

@app.route('/', methods=['GET', 'POST'])
def index():
    origenes = sorted(rutas['Origen'].dropna().unique())
    destinos = sorted(rutas['Destino'].dropna().unique())
    frase = random.choice(frases)
    resultados = []

    if request.method == 'POST':
        origen = request.form['origen']
        destino = request.form['destino']

        rutas['Salida'] = pd.to_datetime(rutas['Salida'], errors='coerce')
        rutas['Llegada'] = pd.to_datetime(rutas['Llegada'], errors='coerce')

        directas = rutas[(rutas['Origen'] == origen) & (rutas['Destino'] == destino)].copy()

        transbordos = []
        intermedios = rutas[rutas['Origen'] == origen]
        for _, r1 in intermedios.iterrows():
            siguientes = rutas[(rutas['Origen'] == r1['Destino']) & (rutas['Destino'] == destino)]
            for _, r2 in siguientes.iterrows():
                if pd.notnull(r1['Llegada']) and pd.notnull(r2['Salida']) and r1['Llegada'] + timedelta(minutes=5) <= r2['Salida']:
                    total_tiempo = r2['Llegada'] - r1['Salida']
                    transbordos.append({
                        'Origen': r1['Origen'],
                        'Destino': r2['Destino'],
                        'Transbordo': r1['Destino'],
                        'Salida': r1['Salida'].strftime('%H:%M'),
                        'Llegada': r2['Llegada'].strftime('%H:%M'),
                        'Tiempo': str(total_tiempo)
                    })

        directas['Transbordo'] = 'No'
        directas['Tiempo'] = directas['Llegada'] - directas['Salida']
        directas['Salida'] = directas['Salida'].dt.strftime('%H:%M')
        directas['Llegada'] = directas['Llegada'].dt.strftime('%H:%M')

        resultados = directas[['Origen','Destino','Transbordo','Salida','Llegada','Tiempo']].to_dict('records') + transbordos
        resultados = sorted(resultados, key=lambda x: x['Llegada'])

    return render_template('index.html', origenes=origenes, destinos=destinos, frase=frase, resultados=resultados)

if __name__ == '__main__':
    app.run(debug=True)


