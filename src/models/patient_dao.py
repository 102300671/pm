"""
患者 DAO - 数据访问对象
"""
from src.utils.db import get_connection


class PatientDAO:
    @staticmethod
    def get_all(only_active=True):
        conn = get_connection()
        cur = conn.cursor()
        if only_active:
            cur.execute("SELECT * FROM patient WHERE status = 1 ORDER BY ward_no, bed_no")
        else:
            cur.execute("SELECT * FROM patient ORDER BY status DESC, ward_no")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    @staticmethod
    def get_by_id(patient_id):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM patient WHERE patient_id = ?", (patient_id,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    def insert(data):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO patient (name, gender, age, ward_no, bed_no, doctor, diagnosis)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (data['name'], data['gender'], data.get('age'),
              data.get('ward_no'), data.get('bed_no'),
              data.get('doctor'), data.get('diagnosis')))
        pid = cur.lastrowid
        conn.commit()
        conn.close()
        return pid

    @staticmethod
    def update(patient_id, data):
        conn = get_connection()
        cur = conn.cursor()
        fields = []
        values = []
        for k, v in data.items():
            if k in ('name', 'gender', 'age', 'ward_no', 'bed_no', 'doctor', 'diagnosis'):
                fields.append(f"{k} = ?")
                values.append(v)
        if not fields:
            conn.close()
            return
        values.append(patient_id)
        cur.execute(f"UPDATE patient SET {', '.join(fields)} WHERE patient_id = ?", values)
        conn.commit()
        conn.close()

    @staticmethod
    def discharge(patient_id):
        """出院"""
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE patient SET status = 0, discharge_time = CURRENT_TIMESTAMP
            WHERE patient_id = ?
        """, (patient_id,))
        conn.commit()
        conn.close()
