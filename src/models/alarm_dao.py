"""
报警 DAO
"""
from src.utils.db import get_connection


class AlarmDAO:
    @staticmethod
    def insert(patient_id, metric_type, current_value, threshold_lower, threshold_upper):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO alarm (patient_id, metric_type, current_value,
                              threshold_lower, threshold_upper, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
        """, (patient_id, metric_type, current_value, threshold_lower, threshold_upper))
        alarm_id = cur.lastrowid
        conn.commit()
        conn.close()
        return alarm_id

    @staticmethod
    def exists_pending(patient_id, metric_type):
        """检查是否存在同一病人同一指标的 pending 报警"""
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT alarm_id FROM alarm
            WHERE patient_id = ? AND metric_type = ? AND status = 'pending'
        """, (patient_id, metric_type))
        row = cur.fetchone()
        conn.close()
        return row is not None

    @staticmethod
    def get_pending():
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT a.*, p.name as patient_name, p.ward_no, p.bed_no
            FROM alarm a
            JOIN patient p ON a.patient_id = p.patient_id
            WHERE a.status = 'pending'
            ORDER BY a.alarm_time DESC
        """)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    @staticmethod
    def confirm(alarm_id, handler, note=''):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE alarm SET status='handled', handler=?, handle_note=?, handle_time=CURRENT_TIMESTAMP
            WHERE alarm_id = ?
        """, (handler, note, alarm_id))
        conn.commit()
        conn.close()

    @staticmethod
    def get_by_patient(patient_id, only_pending=False):
        conn = get_connection()
        cur = conn.cursor()
        if only_pending:
            cur.execute("""
                SELECT * FROM alarm WHERE patient_id = ? AND status = 'pending'
                ORDER BY alarm_time DESC
            """, (patient_id,))
        else:
            cur.execute("""
                SELECT * FROM alarm WHERE patient_id = ?
                ORDER BY alarm_time DESC
            """, (patient_id,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
