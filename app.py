from flask import Flask, render_template, request, jsonify
import pandas as pd
import datetime
from filelock import FileLock
from functools import lru_cache

app = Flask(__name__)

# กำหนดชื่อไฟล์ CSV
EMPLOYEES_CSV = 'Employer.csv'
MILL_EXTRUDE_CSV = 'Mill&Extrude.csv'
SAMPLE_DATA_CSV = 'Sample_Shift_Data.csv'
AUTOCOMPLETE_CSV = 'Autocomplete.csv'
REMARK_CSV = 'Remark.csv'

LOCK_PATH = 'data.lock'

def load_data():
    with FileLock(LOCK_PATH):
        # กำหนดค่าเริ่มต้นให้กับตัวแปรทั้งหมด
        employees = []
        extrude_options = []
        mill_options = []
        sample_data_df = pd.DataFrame()
        autocomplete_df = pd.DataFrame()
        remark_options = []

        # โหลดข้อมูลจากไฟล์ CSV
        try:
            employees_df = pd.read_csv(EMPLOYEES_CSV)
            employees = employees_df.to_dict('records')
        except Exception as e:
            print(f"Error loading {EMPLOYEES_CSV}: {e}")

        try:
            mill_extrude_df = pd.read_csv(MILL_EXTRUDE_CSV)
            extrude_options = mill_extrude_df['Extrude'].dropna().astype(str).tolist()
            mill_options = mill_extrude_df['Mill'].dropna().astype(str).tolist()
        except Exception as e:
            print(f"Error loading {MILL_EXTRUDE_CSV}: {e}")

        try:
            sample_data_df = pd.read_csv(SAMPLE_DATA_CSV)
            sample_data_df['Batch'] = sample_data_df['Batch'].astype(str)
        except Exception as e:
            print(f"Error loading {SAMPLE_DATA_CSV}: {e}")

        try:
            autocomplete_df = pd.read_csv(AUTOCOMPLETE_CSV)
        except Exception as e:
            print(f"Error loading {AUTOCOMPLETE_CSV}: {e}")

        try:
            remark_df = pd.read_csv(REMARK_CSV)
            remark_options = remark_df['Remark'].dropna().tolist()
        except Exception as e:
            print(f"Error loading {REMARK_CSV}: {e}")

        return {
            'employees': employees,
            'extrude_options': extrude_options,
            'mill_options': mill_options,
            'sample_data': sample_data_df,
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
            sample_data_df = pd.read_csv(SAMPLE_DATA_CSV)
        except Exception as e:
            print(f"Error loading {SAMPLE_DATA_CSV}: {e}")
        try:
            autocomplete_df = pd.read_csv(AUTOCOMPLETE_CSV)
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
            sample_data_df = pd.read_csv(SAMPLE_DATA_CSV)

            required_fields = ['employee', 'shift', 'sku', 'batch', 'box_no', 'quantity', 'remark', 'extrude', 'mill']
            if not all(data.get(field) for field in required_fields):
                return jsonify({'success': False, 'message': 'กรุณากรอกข้อมูลให้ครบทุกช่อง'})

            ongoing_sample = sample_data_df[
                (sample_data_df['Employee'] == data['employee']) &
                (sample_data_df['Stop Time'].isna())
            ]
            if not ongoing_sample.empty and not force_save:
                return jsonify({'success': False, 'message': 'คุณมีการทดสอบที่ยังไม่เสร็จสิ้น', 'confirm': True})

            start_time = datetime.datetime.now()
            shift_date = start_time.date() if 8 <= start_time.hour <= 23 else start_time.date() - datetime.timedelta(days=1)

            new_data = {
                'Start Time': start_time.strftime("%Y-%m-%d %H:%M:%S"),
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

            sample_data_df.to_csv(SAMPLE_DATA_CSV, index=False)

            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})

@app.route('/get_ongoing_samples')
def get_ongoing_samples():
    with FileLock(LOCK_PATH):
        try:
            sample_data_df = pd.read_csv(SAMPLE_DATA_CSV)

            ongoing_samples = sample_data_df[sample_data_df['Stop Time'].isna() | (sample_data_df['Stop Time'] == '')]

            samples_list = []
            for index, row in ongoing_samples.iterrows():
                start_time = pd.to_datetime(row['Start Time'])
                duration = datetime.datetime.now() - start_time
                duration_minutes = int(duration.total_seconds() / 60)

                samples_list.append({
                    'index': int(index),
                    'employee': row['Employee'],
                    'sku': row['SKU'],
                    'batch': row['Batch'],
                    'start_time': row['Start Time'],
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
            sample_data_df = pd.read_csv(SAMPLE_DATA_CSV)

            if row_index is None or row_index >= len(sample_data_df):
                return jsonify({'success': False, 'message': 'ไม่พบข้อมูลตัวอย่างที่เลือก'})

            stop_time = datetime.datetime.now()
            sample_data_df.at[row_index, 'Stop Time'] = stop_time.strftime("%Y-%m-%d %H:%M:%S")
            sample_data_df.at[row_index, 'Stop_Worktime'] = stop_time.strftime("%H:%M:%S")

            start_time = pd.to_datetime(sample_data_df.at[row_index, 'Start Time'])
            duration = stop_time - start_time
            total_seconds = int(duration.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            sample_data_df.at[row_index, 'Duration'] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

            sample_data_df.to_csv(SAMPLE_DATA_CSV, index=False)

            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})

if __name__ == '__main__':
    app.run(debug=True)