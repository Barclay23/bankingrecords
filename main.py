from flask import Flask, request, jsonify, send_file, render_template
import pandas as pd
import numpy as np
import os
from datetime import datetime, date
import xml.etree.ElementTree as ET
from io import BytesIO

app = Flask(__name__)

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Helper: Validate date
def validate_date_range(start_date, end_date):
    today = date.today()
    return start_date <= today and end_date <= today

# Helper: Validate account
def validate_account(header_account, transactions):
    return all(tx['NrRachunku'] == header_account for tx in transactions)

# Helper: Validate saldo
def validate_saldo(transactions):
    saldo = None
    for tx in transactions:
        if saldo is not None and float(tx['SaldoKonta']) != saldo + float(tx['Kwota']):
            return False
        saldo = float(tx['SaldoKonta'])
    return True

def generate_jpk_xml(header, transactions, start_date, end_date, start_saldo, end_saldo, minus_sum, plus_sum):
    root = ET.Element('JPK')
    header_elem = ET.SubElement(root, 'Naglowek')
    ET.SubElement(header_elem, 'KodFormularza').text = 'JPK_WB(1) 1-0'
    ET.SubElement(header_elem, 'WariantFormularza').text = '1'
    ET.SubElement(header_elem, 'CelZlozenia').text = 'Złożenie JPK_WB po raz pierwszy'
    ET.SubElement(header_elem, 'DataWytworzeniaJPK').text = str(date.today())
    ET.SubElement(header_elem, 'DataOd').text = str(start_date)
    ET.SubElement(header_elem, 'DataDo').text = str(end_date)
    ET.SubElement(header_elem, 'DomyslnyKodWaluty').text = str(header['KodWaluty'])
    ET.SubElement(header_elem, 'KodUrzedu').text = str(header['KodUrzędu'])
    # for key, value in header.items():
    #     ET.SubElement(header_elem, key).text = str(value)
    podmi_elem = ET.SubElement(root, 'Podmiot1')

    ident_elem = ET.SubElement(podmi_elem, 'IdentyfikatorPodmiotu')

    ET.SubElement(ident_elem, 'NIP').text = str(header['NIP'])
    ET.SubElement(ident_elem, 'PelnaNazwa').text = str(header['NazwaFirmy'])
    ET.SubElement(ident_elem, 'REGON').text = str(header['REGON'])

    adres_elem = ET.SubElement(podmi_elem, 'AdresPodmiotu')

    ET.SubElement(adres_elem, 'KodKraju').text = str(header['KodKraju'])
    ET.SubElement(adres_elem, 'Wojewodztwo').text = str(header['Województwo'])
    ET.SubElement(adres_elem, 'Powiat').text = str(header['Powiat'])
    ET.SubElement(adres_elem, 'Gmina').text = str(header['Gmina'])
    ET.SubElement(adres_elem, 'Ulica').text = str(header['Ulica'])
    ET.SubElement(adres_elem, 'NrDomu').text = str(header['NrDomu'])
    ET.SubElement(adres_elem, 'NrLokalu').text = str(header['NrLokalu'])
    ET.SubElement(adres_elem, 'Miejscowosc').text = str(header['Miejscowość'])
    ET.SubElement(adres_elem, 'KodPocztowy').text = str(header['KodPocztowy'])
    ET.SubElement(adres_elem, 'Poczta').text = str(header['Poczta'])

    ET.SubElement(root, 'NumerRachunku').text = str(header['NumerRachunku'])

    salda_elem = ET.SubElement(root, 'Salda')
    ET.SubElement(salda_elem, 'SaldoPoczatkowe').text = str(start_saldo)
    ET.SubElement(salda_elem, 'SaldoKoncowe').text = str(end_saldo)

    num = 1

    wyciag_elem = ET.SubElement(root, 'WyciagWierszy')
    for tx in transactions:
        ET.SubElement(wyciag_elem, 'NumerWiersza').text = str(num)
        ET.SubElement(wyciag_elem, 'DataOperacji').text = str(tx['Data'])
        ET.SubElement(wyciag_elem, 'NazwaPodmiotu').text = str(tx['Kontrahent'])
        ET.SubElement(wyciag_elem, 'OpisOperacji').text = str(tx['Tytul'])
        ET.SubElement(wyciag_elem, 'KwotaOperacji').text = str(tx['Kwota'])
        ET.SubElement(wyciag_elem, 'SaldoOperacji').text = str(tx['SaldoKonta'])
        num=num+1

    ctrl_elem = ET.SubElement(root, 'WyciagCtrl')
    ET.SubElement(ctrl_elem, 'LiczbaWierszy').text = str(num)
    ET.SubElement(ctrl_elem, 'SumaObciazen').text = str(minus_sum)
    ET.SubElement(ctrl_elem, 'SumaUznan').text = str(plus_sum)

    xml_bytes = BytesIO()
    tree = ET.ElementTree(root)
    tree.write(xml_bytes, encoding='utf-8', xml_declaration=True)
    xml_bytes.seek(0)
    return xml_bytes

@app.route('/', methods = ["POST", "GET"])
def home():
    return render_template("index.html")

@app.route('/upload', methods=['POST'])
def upload_files():
    header_file = request.files.get('header')
    position_files = request.files.getlist('positions')
    start_date_str = request.form.get('start_date')
    end_date_str = request.form.get('end_date')

    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD.'}), 400

    if not validate_date_range(start_date, end_date):
        return jsonify({'error': 'Date range cannot include future dates.'}), 400

    header_df = pd.read_csv(header_file, encoding='utf-8')
    if header_df.empty or len(header_df) != 1:
        return jsonify({'error': 'Header file must contain exactly one record.'}), 400
    
    header = header_df.iloc[0].to_dict()
    header_account = header['NumerRachunku']

    min_date = end_date
    max_date = start_date

    start_saldo=0
    end_saldo=0


    minus_sum = 0
    plus_sum = 0


    all_transactions = []
    for f in position_files:
        df = pd.read_csv(f, encoding='utf-8')
        df = df[df['Data'].apply(lambda d: start_date <= datetime.strptime(d, '%Y-%m-%d').date() <= end_date)]
        min_data_w_df = datetime.strptime(df['Data'].min(), '%Y-%m-%d').date()
        if min_date>= min_data_w_df:
            min_date = min_data_w_df
            start_saldo = df.loc[df['Data'] == df['Data'].min(), 'SaldoKonta'].iloc[0]

        max_data_w_df = datetime.strptime(df['Data'].max(), '%Y-%m-%d').date()
        if max_date<=max_data_w_df:
            max_date = max_data_w_df
            end_saldo = df.loc[df['Data'] == df['Data'].max(), 'SaldoKonta'].iloc[0]

        minus_sum += df.loc[df['Kwota'] < 0, 'Kwota'].abs().sum()

        plus_sum += df.loc[df['Kwota'] > 0, 'Kwota'].abs().sum()

        all_transactions.extend(df.to_dict(orient='records'))

    if not validate_account(header_account, all_transactions):
        return jsonify({'error': 'One or more transactions do not match the account in the header.'}), 400

    if not validate_saldo(all_transactions):
        return jsonify({'error': 'Invalid saldo sequence in transactions.'}), 400

    xml_output = generate_jpk_xml(header, all_transactions, start_date, end_date, start_saldo, end_saldo,minus_sum, plus_sum)
    return send_file(xml_output, mimetype='application/xml', as_attachment=True, download_name='JPK_WB.xml')

if __name__ == '__main__':
    app.run(debug=True)
