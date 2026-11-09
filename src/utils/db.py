"""
数据库工具模块 - SQLite 连接管理 & 表初始化
"""
import sqlite3
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _default_db_path():
    """按运行环境自动选择数据库目录：
    - Windows Python（含通过 \\wsl$ 路径运行本项目的情况）:
      SQLite 文件锁在 9P 网络文件系统上不可靠（会报 "database is locked"），
      因此使用 %LOCALAPPDATA% 下的本地 NTFS 路径。
    - Linux / WSL / macOS: 使用项目目录下的 data/。
    - 环境变量 PMS_DB_PATH 优先级最高，可覆盖以上两者。
    """
    if sys.platform == 'win32':
        base = (os.environ.get('LOCALAPPDATA') or os.environ.get('TEMP')
                or os.path.expanduser('~'))
        return os.path.join(base, 'patient-monitor', 'patient_monitor.db')
    return os.path.join(_PROJECT_ROOT, 'data', 'patient_monitor.db')


DB_PATH = os.environ.get('PMS_DB_PATH', _default_db_path())

# 确保 data 目录存在
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def get_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_database():
    """首次启动时创建所有表和示例数据"""
    conn = get_connection()
    cursor = conn.cursor()

    # ---- 创建患者表 ----
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patient (
            patient_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name         VARCHAR(50) NOT NULL,
            gender       VARCHAR(10) NOT NULL,
            age          INTEGER,
            ward_no      VARCHAR(20),
            bed_no       VARCHAR(10),
            doctor       VARCHAR(50),
            diagnosis    TEXT,
            admit_time   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            discharge_time DATETIME,
            status       INTEGER NOT NULL DEFAULT 1
        )
    """)

    # ---- 创建阈值设置表 ----
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS threshold (
            threshold_id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id   INTEGER NOT NULL,
            metric_type  VARCHAR(30) NOT NULL,
            lower_bound  FLOAT NOT NULL,
            upper_bound  FLOAT NOT NULL,
            setter       VARCHAR(50),
            set_time     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patient(patient_id),
            UNIQUE(patient_id, metric_type)
        )
    """)

    # ---- 创建日志表 ----
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS log (
            log_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id    INTEGER NOT NULL,
            record_time   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            pulse         FLOAT,
            temperature   FLOAT,
            systolic_bp   FLOAT,
            diastolic_bp  FLOAT,
            heart_rate    FLOAT,
            ecg_summary   VARCHAR(50),
            FOREIGN KEY (patient_id) REFERENCES patient(patient_id)
        )
    """)

    # ---- 创建报警记录表 ----
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alarm (
            alarm_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id       INTEGER NOT NULL,
            metric_type      VARCHAR(30) NOT NULL,
            current_value    FLOAT NOT NULL,
            threshold_lower  FLOAT,
            threshold_upper  FLOAT,
            alarm_time       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            status           VARCHAR(20) NOT NULL DEFAULT 'pending',
            handler          VARCHAR(50),
            handle_note      TEXT,
            handle_time      DATETIME,
            FOREIGN KEY (patient_id) REFERENCES patient(patient_id)
        )
    """)

    # ---- 创建索引 ----
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_patient_status ON patient(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_threshold_patient ON threshold(patient_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_log_patient_time ON log(patient_id, record_time DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_alarm_status ON alarm(status)")

    conn.commit()

    # ---- 检查是否已有数据，无则插入示例 ----
    cursor.execute("SELECT COUNT(*) FROM patient")
    if cursor.fetchone()[0] == 0:
        _insert_sample_data(conn)

    conn.close()
    print(f"[DB] 数据库初始化完成: {DB_PATH}")


def _insert_sample_data(conn):
    """插入示例患者 + 默认阈值"""
    cursor = conn.cursor()

    sample_patients = [
        ('张三', '男', 58, '301', 'A1', '李医生', '急性肺炎恢复期'),
        ('李四', '女', 72, '301', 'B2', '王医生', '高血压观察'),
        ('王五', '男', 45, '302', 'C1', '张医生', '术后恢复'),
        ('赵六', '女', 35, '302', 'D2', '李医生', '常规检查'),
    ]

    cursor.executemany("""
        INSERT INTO patient (name, gender, age, ward_no, bed_no, doctor, diagnosis)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, sample_patients)

    # 默认阈值 (min, max)
    default_thresholds = [
        ('pulse',        60.0, 100.0),
        ('temperature',  36.0, 37.5),
        ('systolic_bp',  90.0, 140.0),
        ('diastolic_bp', 60.0, 90.0),
        ('heart_rate',   60.0, 100.0),
    ]

    # 为每位患者创建默认阈值
    for pid in range(1, len(sample_patients) + 1):
        for metric, lo, hi in default_thresholds:
            cursor.execute("""
                INSERT INTO threshold (patient_id, metric_type, lower_bound, upper_bound, setter)
                VALUES (?, ?, ?, ?, '系统默认')
            """, (pid, metric, lo, hi))

    conn.commit()
    print(f"[DB] 已插入 {len(sample_patients)} 名示例患者")


# 指标类型中文名映射
METRIC_NAMES = {
    'pulse':        '脉搏',
    'temperature':  '体温',
    'systolic_bp':  '收缩压',
    'diastolic_bp': '舒张压',
    'heart_rate':   '心率',
}

METRIC_UNITS = {
    'pulse':        '次/分',
    'temperature':  '℃',
    'systolic_bp':  'mmHg',
    'diastolic_bp': 'mmHg',
    'heart_rate':   '次/分',
}
