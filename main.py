from flask import Flask, request, jsonify, send_file, render_template
import pandas as pd
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

def generate_jpk_xml(header, transactions, start_date, end_date):
    root = ET.Element('JPK')
    header_elem = ET.SubElement(root, 'Naglowek')
    ET.SubElement(header_elem, 'KodFormularza').text = 'JPK_WB'
    ET.SubElement(header_elem, 'WariantFormularza').text = '1'
    ET.SubElement(header_elem, 'CelZlozenia').text = 'Złożenie JPK_WB po raz pierwszy'
    ET.SubElement(header_elem, 'DataWytworzeniaJPK').text = str(date.today())
    ET.SubElement(header_elem, 'DataOd').text = str(start_date)
    ET.SubElement(header_elem, 'DataDo').text = str(end_date)
    for key, value in header.items():
        ET.SubElement(header_elem, key).text = str(value)

    trans_elem = ET.SubElement(root, 'Transakcje')
    for tx in transactions:
        tx_elem = ET.SubElement(trans_elem, 'Transakcja')
        for key, value in tx.items():
            ET.SubElement(tx_elem, key).text = str(value)

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

    all_transactions = []
    for f in position_files:
        df = pd.read_csv(f, encoding='utf-8')
        df = df[df['Data'].apply(lambda d: start_date <= datetime.strptime(d, '%Y-%m-%d').date() <= end_date)]
        all_transactions.extend(df.to_dict(orient='records'))

    if not validate_account(header_account, all_transactions):
        return jsonify({'error': 'One or more transactions do not match the account in the header.'}), 400

    if not validate_saldo(all_transactions):
        return jsonify({'error': 'Invalid saldo sequence in transactions.'}), 400

    xml_output = generate_jpk_xml(header, all_transactions, start_date, end_date)
    return send_file(xml_output, mimetype='application/xml', as_attachment=True, download_name='JPK_WB.xml')

if __name__ == '__main__':
    app.run(debug=True)
