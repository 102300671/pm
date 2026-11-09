"""
日志 DAO
"""
from src.utils.db import get_connection


class LogDAO:
    @staticmethod
    def insert(patient_id, signals):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO log (patient_id, pulse, temperature, systolic_bp, diastolic_bp, heart_rate, ecg_summary)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (patient_id,
              signals.get('pulse'),
              signals.get('temperature'),
              signals.get('systolic_bp'),
              signals.get('diastolic_bp'),
              signals.get('heart_rate'),
              signals.get('ecg_summary', '正常')))
        conn.commit()
        conn.close()

    @staticmethod
    def get_latest(patient_id, limit=1):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM log WHERE patient_id = ?
            ORDER BY record_time DESC LIMIT ?
        """, (patient_id, limit))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    @staticmethod
    def get_range(patient_id, start_time=None, end_time=None):
        """查询指定时间范围内的日志"""
        conn = get_connection()
        cur = conn.cursor()
        sql = "SELECT * FROM log WHERE patient_id = ?"
        params = [patient_id]
        if start_time:
            sql += " AND record_time >= ?"
            params.append(start_time)
        if end_time:
            sql += " AND record_time <= ?"
            params.append(end_time)
        sql += " ORDER BY record_time ASC"
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    @staticmethod
    def get_latest_all_active(patient_ids):
        """批量获取多位患者最新一条日志"""
        if not patient_ids:
            return {}
        conn = get_connection()
        cur = conn.cursor()
        # SQLite 没有 DISTINCT ON，用子查询实现
        placeholders = ','.join('?' * len(patient_ids))
        cur.execute(f"""
            SELECT l.* FROM log l
            INNER JOIN (
                SELECT patient_id, MAX(record_time) as max_time
                FROM log WHERE patient_id IN ({placeholders})
                GROUP BY patient_id
            ) sub ON l.patient_id = sub.patient_id AND l.record_time = sub.max_time
        """, patient_ids)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {r['patient_id']: r for r in rows}
