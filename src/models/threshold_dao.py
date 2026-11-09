"""
阈值 DAO
"""
from src.utils.db import get_connection


class ThresholdDAO:
    @staticmethod
    def get_by_patient(patient_id):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM threshold WHERE patient_id = ?", (patient_id,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    @staticmethod
    def get_one(patient_id, metric_type):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM threshold WHERE patient_id = ? AND metric_type = ?
        """, (patient_id, metric_type))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    def upsert(patient_id, metric_type, lower, upper, setter='系统'):
        """插入或更新阈值"""
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT threshold_id FROM threshold WHERE patient_id = ? AND metric_type = ?",
                    (patient_id, metric_type))
        row = cur.fetchone()
        if row:
            cur.execute("""
                UPDATE threshold SET lower_bound=?, upper_bound=?, setter=?, set_time=CURRENT_TIMESTAMP
                WHERE patient_id=? AND metric_type=?
            """, (lower, upper, setter, patient_id, metric_type))
        else:
            cur.execute("""
                INSERT INTO threshold (patient_id, metric_type, lower_bound, upper_bound, setter)
                VALUES (?, ?, ?, ?, ?)
            """, (patient_id, metric_type, lower, upper, setter))
        conn.commit()
        conn.close()
