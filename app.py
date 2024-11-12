from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for,session
import pandas as pd
import datetime
from filelock import FileLock
from functools import lru_cache,wraps
from io import BytesIO
from zoneinfo import ZoneInfo
import os

app = Flask(__name__)

# รหัสผ่านสำหรับการเข้าถึงหน้า Export
app.secret_key = 'Tiger'  # เปลี่ยนเป็นค่าที่ปลอดภัย
EXPORT_PASSWORD = '935673'

# กำหนดชื่อไฟล์ CSV
EMPLOYEES_CSV = os.path.join('data', 'Employer.csv')
MILL_EXTRUDE_CSV = os.path.join('data', 'Mill&Extrude.csv')
SAMPLE_DATA_CSV = os.path.join('data', 'Sample_Shift_Data.csv')
AUTOCOMPLETE_CSV = os.path.join('data', 'Autocomplete.csv')
REMARK_CSV = os.path.join('data', 'Remark.csv')

LOCK_PATH = 'data.lock'

# ตั้งค่า Timezone ของประเทศไทย
TH_TZ = ZoneInfo('Asia/Bangkok')

AVAILABLE_DATA_TYPES = {
    'autocomplete': AUTOCOMPLETE_CSV,
    'employer': EMPLOYEES_CSV,
    'mill_extrude': MILL_EXTRUDE_CSV,
    'remark': REMARK_CSV,
    'sample_shift_data': SAMPLE_DATA_CSV  # เพิ่มข้อมูลนี้
}

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def load_data():
    with FileLock(LOCK_PATH):
        # กำหนดค่าเริ่มต้นให้กับตัวแปรทั้งหมด
        employees = []
        extrude_options = []
        mill_options = []
        sample_data_df = pd.DataFrame()
        autocomplete_df = pd.DataFrame()
        remark_options = []
        sample_shift_data = pd.DataFrame()  # เพิ่มตัวแปรนี้

        # โหลดข้อมูลจากไฟล์ CSV
        try:
            employees = pd.read_csv(EMPLOYEES_CSV).to_dict(orient='records')
        except Exception as e:
            print(f"Error loading {EMPLOYEES_CSV}: {e}")

        try:
            mill_options = pd.read_csv(MILL_EXTRUDE_CSV)['mill'].tolist()
        except Exception as e:
            print(f"Error loading {MILL_EXTRUDE_CSV}: {e}")

        try:
            extrude_options = pd.read_csv(MILL_EXTRUDE_CSV)['extrude'].tolist()
        except Exception as e:
            print(f"Error loading {MILL_EXTRUDE_CSV}: {e}")

        try:
            sample_data_df = pd.read_csv(SAMPLE_DATA_CSV)
            sample_shift_data = sample_data_df.to_dict(orient='records')
        except Exception as e:
            print(f"Error loading {SAMPLE_DATA_CSV}: {e}")

        try:
            autocomplete_df = pd.read_csv(AUTOCOMPLETE_CSV)
        except Exception as e:
            print(f"Error loading {AUTOCOMPLETE_CSV}: {e}")

        try:
            remark_options = pd.read_csv(REMARK_CSV)['remark'].tolist()
        except Exception as e:
            print(f"Error loading {REMARK_CSV}: {e}")

        return {
            'employees': employees,
            'extrude_options': extrude_options,
            'mill_options': mill_options,
            'sample_data': sample_shift_data,  # เพิ่มข้อมูลนี้
            'autocomplete_data': autocomplete_df,
            'remark_options': remark_options
        }

@app.route('/')
def index():
    data = load_data()
    return render_template('index.html', **data)

@lru_cache(maxsize=128)
def get_autocomplete_data():
    with FileLock(LOCK_PATH):
        sample_data_df = pd.DataFrame()
        autocomplete_df = pd.DataFrame()
        try:
            sample_data_df = pd.read_csv(SAMPLE_DATA_CSV, encoding='utf-8-sig')
        except Exception as e:
            print(f"Error loading {SAMPLE_DATA_CSV}: {e}")
        try:
            autocomplete_df = pd.read_csv(AUTOCOMPLETE_CSV, encoding='utf-8-sig')
        except Exception as e:
            print(f"Error loading {AUTOCOMPLETE_CSV}: {e}")
        return sample_data_df, autocomplete_df

@app.route('/autocomplete_sku', methods=['GET'])
def autocomplete_sku():
    query = request.args.get('q', '').upper()
    try:
        sample_data_df, autocomplete_df = get_autocomplete_data()

        filtered_skus_sample = sample_data_df[sample_data_df['SKU'].str.startswith(query, na=False)]['SKU'].unique()
        filtered_skus_auto = autocomplete_df[autocomplete_df['SKU'].str.startswith(query, na=False)]['SKU'].unique()

        all_filtered_skus = set(filtered_skus_sample) | set(filtered_skus_auto)

        return jsonify({'skus': list(all_filtered_skus)})
    except Exception as e:
        return jsonify({'skus': [], 'error': str(e)})

@app.route('/start_sample', methods=['POST'])
def start_sample():
    data = request.form.to_dict()
    force_save = data.get('force_save', 'false').lower() == 'true'

    with FileLock(LOCK_PATH):
        try:
            sample_data_df = pd.read_csv(SAMPLE_DATA_CSV, encoding='utf-8-sig')

            required_fields = ['employee', 'shift', 'sku', 'batch', 'box_no', 'quantity', 'remark', 'extrude', 'mill']
            if not all(data.get(field) for field in required_fields):
                return jsonify({'success': False, 'message': 'กรุณากรอกข้อมูลให้ครบทุกช่อง'})

            ongoing_sample = sample_data_df[
                (sample_data_df['Employee'] == data['employee']) &
                (sample_data_df['Stop Time'].isna())
            ]
            if not ongoing_sample.empty and not force_save:
                return jsonify({'success': False, 'message': 'คุณมีการทดสอบที่ยังไม่เสร็จสิ้น', 'confirm': True})

            # ใช้เวลาใน Timezone ของประเทศไทย
            start_time = datetime.datetime.now(TH_TZ)
            shift_date = start_time.date() if 8 <= start_time.hour <= 23 else start_time.date() - datetime.timedelta(days=1)

            new_data = {
                'Start Time': start_time.strftime("%d/%m/%Y %H:%M:%S"),
                'Stop Time': '',
                'SKU': data['sku'].upper(),
                'Batch': data['batch'],
                'Box No.': data['box_no'],
                'Quantity': int(data['quantity']),
                'Remark': data['remark'],
                'Employee': data['employee'],
                'Shift': data['shift'],
                'Extrude': data['extrude'],
                'Mill': data['mill'],
                'ShiftDate': shift_date.strftime("%d/%m/%Y"),
                'Duration': '',
                'Start_Worktime': start_time.strftime("%H:%M:%S"),
                'Stop_Worktime': ''
            }

            sample_data_df = pd.concat([sample_data_df, pd.DataFrame([new_data])], ignore_index=True)

            # บันทึกด้วย encoding='utf-8-sig'
            sample_data_df.to_csv(SAMPLE_DATA_CSV, index=False, encoding='utf-8-sig')

            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})

@app.route('/get_ongoing_samples')
def get_ongoing_samples():
    with FileLock(LOCK_PATH):
        try:
            sample_data_df = pd.read_csv(SAMPLE_DATA_CSV, encoding='utf-8-sig')

            ongoing_samples = sample_data_df[sample_data_df['Stop Time'].isna() | (sample_data_df['Stop Time'] == '')]

            samples_list = []
            for index, row in ongoing_samples.iterrows():
                start_time = pd.to_datetime(row['Start Time'], dayfirst=True)
                # ตั้งค่า Timezone ของเวลาที่เริ่ม
                start_time = start_time.replace(tzinfo=TH_TZ)
                duration = datetime.datetime.now(TH_TZ) - start_time
                duration_minutes = int(duration.total_seconds() / 60)

                samples_list.append({
                    'index': int(index),
                    'employee': row['Employee'],
                    'sku': row['SKU'],
                    'batch': row['Batch'],
                    'start_time': start_time.strftime("%d/%m/%Y %H:%M:%S"),
                    'duration_minutes': duration_minutes
                })

            return jsonify({'success': True, 'samples': samples_list})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})

@app.route('/stop_sample', methods=['POST'])
def stop_sample():
    data = request.json
    row_index = data.get('index')

    with FileLock(LOCK_PATH):
        try:
            sample_data_df = pd.read_csv(SAMPLE_DATA_CSV, encoding='utf-8-sig')

            if row_index is None or row_index >= len(sample_data_df):
                return jsonify({'success': False, 'message': 'ไม่พบข้อมูลตัวอย่างที่เลือก'})

            # ใช้เวลาใน Timezone ของประเทศไทย
            stop_time = datetime.datetime.now(TH_TZ)
            sample_data_df.at[row_index, 'Stop Time'] = stop_time.strftime("%d/%m/%Y %H:%M:%S")
            sample_data_df.at[row_index, 'Stop_Worktime'] = stop_time.strftime("%H:%M:%S")

            start_time = pd.to_datetime(sample_data_df.at[row_index, 'Start Time'], dayfirst=True)
            # ตั้งค่า Timezone ของเวลาที่เริ่ม
            start_time = start_time.replace(tzinfo=TH_TZ)
            duration = stop_time - start_time
            total_seconds = int(duration.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            sample_data_df.at[row_index, 'Duration'] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

            # บันทึกด้วย encoding='utf-8-sig'
            sample_data_df.to_csv(SAMPLE_DATA_CSV, index=False, encoding='utf-8-sig')

            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})

# เพิ่มเส้นทางสำหรับหน้า Export ที่ป้องกันด้วยรหัสผ่าน
@app.route('/export', methods=['GET', 'POST'])
def export():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == EXPORT_PASSWORD:
            return redirect(url_for('download_data'))
        else:
            error = 'รหัสผ่านไม่ถูกต้อง'
            return render_template('export.html', error=error)
    return render_template('export.html')

# เส้นทางสำหรับดาวน์โหลดไฟล์ Sample_Shift_Data.csv
@app.route('/download_data')
def download_data():
    try:
        return send_file(
            SAMPLE_DATA_CSV,
            mimetype='text/csv',
            as_attachment=True,
            download_name='Sample_Shift_Data.csv'
        )
    except Exception as e:
        return f"เกิดข้อผิดพลาดในการดาวน์โหลดไฟล์: {e}"

# เส้นทางสำหรับเลือกและแก้ไขข้อมูล
@app.route('/edit_data', methods=['GET', 'POST'])
@login_required
def edit_data():
    if request.method == 'POST':
        selected_type = request.form.get('data_type')
        if selected_type in AVAILABLE_DATA_TYPES:
            return redirect(url_for('edit_specific_data', data_type=selected_type))
        else:
            return redirect(url_for('edit_data'))
    return render_template('select_data.html', data_types=AVAILABLE_DATA_TYPES.keys())

@app.route('/edit/<data_type>', methods=['GET', 'POST'])
@login_required
def edit_specific_data(data_type):
    if data_type not in AVAILABLE_DATA_TYPES:
        return redirect(url_for('edit_data'))

    csv_path = AVAILABLE_DATA_TYPES[data_type]
    with FileLock(LOCK_PATH):
        if request.method == 'POST':
            action = request.json.get('action')
            record = request.json.get('record')

            try:
                df = pd.read_csv(csv_path)
                if action == 'add':
                    df = df.append(record, ignore_index=True)
                elif action == 'edit':
                    index = record.pop('index')
                    for key, value in record.items():
                        df.at[index, key] = value
                elif action == 'delete':
                    index = record.get('index')
                    df = df.drop(index).reset_index(drop=True)
                df.to_csv(csv_path, index=False)
                return jsonify({'success': True})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})

        # GET request
        try:
            df = pd.read_csv(csv_path)
            # ตรวจสอบถ้าเป็น sample_shift_data ให้กรองตาม ShiftDate
            shift_date = request.args.get('shift_date')
            if data_type == 'sample_shift_data' and shift_date:
                df['ShiftDate'] = pd.to_datetime(df['ShiftDate'], format='%d/%m/%Y').dt.date
                filter_date = pd.to_datetime(shift_date, format='%Y-%m-%d').date()
                df = df[df['ShiftDate'] == filter_date]
            records = df.to_dict(orient='records')
            columns = list(df.columns)
            # สำหรับ sample_shift_data ซ่อนคอลัมน์ที่ไม่ต้องการ
            if data_type == 'sample_shift_data':
                hidden_columns = ['Start_Worktime', 'Stop_Worktime', 'Duration']
                columns = [col for col in columns if col not in hidden_columns]
        except Exception as e:
            records = []
            columns = []
        return render_template('edit_data.html', data_type=data_type, records=records, columns=columns, shift_date=shift_date if data_type == 'sample_shift_data' else None)
    
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == EXPORT_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('edit_data'))
        else:
            return render_template('login.html', error='รหัสผ่านไม่ถูกต้อง')
    return render_template('login.html')

if __name__ == '__main__':
    # ตรวจสอบว่าไฟล์ CSV ทั้งหมดมีอยู่ ถ้าไม่ให้สร้างไฟล์ว่าง
    for file in AVAILABLE_DATA_TYPES.values():
        if not os.path.exists(file):
            df_empty = pd.DataFrame()
            df_empty.to_csv(file, index=False, encoding='utf-8-sig')
    app.run(debug=True)