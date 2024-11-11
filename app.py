from flask import Flask, render_template, request, jsonify
import pandas as pd
import xlwings as xw
import datetime
import os
from filelock import FileLock
from functools import lru_cache

app = Flask(__name__)

EXCEL_PATH = 'qc_testing_data.xlsx'
LOCK_PATH = 'qc_testing_data.xlsx.lock'

def load_data():
    with FileLock(LOCK_PATH):
        app_xw = xw.App(visible=False)
        wb = xw.Book(EXCEL_PATH)
        try:
            employees_df = wb.sheets['Employer'].range('A1').expand().options(pd.DataFrame, index=False).value
            employees = employees_df.to_dict('records')

            mill_extrude_df = wb.sheets['Mill&Extrude'].range('A1').expand().options(pd.DataFrame, index=False).value
            extrude_options = mill_extrude_df['Extrude'].dropna().astype(str).tolist()
            mill_options = mill_extrude_df['Mill'].dropna().astype(str).tolist()

            sample_data_sheet = wb.sheets['Sample_Shift_Data']
            sample_data_df = sample_data_sheet.range('A1').expand().options(pd.DataFrame, index=False).value
            sample_data_df['Batch'] = sample_data_df['Batch'].astype(str)

            autocomplete_df = wb.sheets['Autocomplete'].range('A1').expand().options(pd.DataFrame, index=False).value

            remark_df = wb.sheets['Remark'].range('A1').expand().options(pd.DataFrame, index=False).value
            remark_options = remark_df['Remark'].dropna().tolist()

            return {
                'employees': employees,
                'extrude_options': extrude_options,
                'mill_options': mill_options,
                'sample_data': sample_data_df,
                'autocomplete_data': autocomplete_df,
                'remark_options': remark_options
            }
        finally:
            wb.save()
            app_xw.quit()

@app.route('/')
def index():
    data = load_data()
    return render_template('index.html', **data)

@lru_cache(maxsize=128)
def get_autocomplete_data():
    with FileLock(LOCK_PATH):
        app_xw = xw.App(visible=False)
        wb = xw.Book(EXCEL_PATH)
        try:
            sample_data_df = wb.sheets['Sample_Shift_Data'].range('A1').expand().options(pd.DataFrame, index=False).value
            autocomplete_df = wb.sheets['Autocomplete'].range('A1').expand().options(pd.DataFrame, index=False).value
            return sample_data_df, autocomplete_df
        finally:
            app_xw.quit()

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
        app_xw = xw.App(visible=False)
        wb = xw.Book(EXCEL_PATH)
        try:
            sheet = wb.sheets['Sample_Shift_Data']
            df = sheet.range('A1').expand().options(pd.DataFrame, index=False).value

            # ตรวจสอบข้อมูลที่กรอก
            required_fields = ['employee', 'shift', 'sku', 'batch', 'box_no', 'quantity', 'remark', 'extrude', 'mill']
            if not all(data.get(field) for field in required_fields):
                return jsonify({'success': False, 'message': 'กรุณากรอกข้อมูลให้ครบทุกช่อง'})

            # ตรวจสอบ ongoing sample
            ongoing_sample = df[(df['Employee'] == data['employee']) & (df['Stop Time'].isna())]
            if not ongoing_sample.empty and not force_save:
                return jsonify({'success': False, 'message': 'คุณมีการทดสอบที่ยังไม่เสร็จสิ้น', 'confirm': True})

            # บันทึกข้อมูลใหม่
            start_time = datetime.datetime.now()
            shift_date = start_time.date() if 8 <= start_time.hour <= 23 else start_time.date() - datetime.timedelta(days=1)

            new_data = {
                'Start Time': start_time.strftime("%Y-%m-%d %H:%M:%S"),
                'Stop Time': pd.NaT,
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

            # ใช้ pd.concat() แทน df.append()
            df = pd.concat([df, pd.DataFrame([new_data])], ignore_index=True)

            sheet.clear_contents()
            sheet.range('A1').options(index=False).value = df
            wb.save()

            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
        finally:
            app_xw.quit()

@app.route('/get_ongoing_samples')
def get_ongoing_samples():
    with FileLock(LOCK_PATH):
        app_xw = xw.App(visible=False)
        wb = xw.Book(EXCEL_PATH)
        try:
            sheet = wb.sheets['Sample_Shift_Data']
            df = sheet.range('A1').expand().options(pd.DataFrame, index=False).value

            ongoing_samples = df[df['Stop Time'].isna()]

            samples_list = []
            for _, row in ongoing_samples.iterrows():
                start_time = pd.to_datetime(row['Start Time'])
                duration = datetime.datetime.now() - start_time
                duration_minutes = int(duration.total_seconds() / 60)

                samples_list.append({
                    'index': int(row.name),
                    'employee': row['Employee'],
                    'sku': row['SKU'],
                    'batch': row['Batch'],
                    'start_time': row['Start Time'],
                    'duration_minutes': duration_minutes
                })

            return jsonify({'success': True, 'samples': samples_list})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
        finally:
            app_xw.quit()

@app.route('/stop_sample', methods=['POST'])
def stop_sample():
    data = request.json
    row_index = data.get('index')

    with FileLock(LOCK_PATH):
        app_xw = xw.App(visible=False)
        wb = xw.Book(EXCEL_PATH)
        try:
            sheet = wb.sheets['Sample_Shift_Data']
            df = sheet.range('A1').expand().options(pd.DataFrame, index=False).value

            if row_index is None or row_index >= len(df):
                return jsonify({'success': False, 'message': 'ไม่พบข้อมูลตัวอย่างที่เลือก'})

            stop_time = datetime.datetime.now()
            df.at[row_index, 'Stop Time'] = stop_time.strftime("%Y-%m-%d %H:%M:%S")
            df.at[row_index, 'Stop_Worktime'] = stop_time.strftime("%H:%M:%S")

            start_time = pd.to_datetime(df.at[row_index, 'Start Time'])
            duration = stop_time - start_time
            total_seconds = int(duration.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            df.at[row_index, 'Duration'] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

            sheet.clear_contents()
            sheet.range('A1').options(index=False).value = df
            wb.save()

            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
        finally:
            app_xw.quit()

if __name__ == '__main__':
    app.run(debug=True)