"""
患者服务 - 封装患者管理业务逻辑
"""
from src.models.patient_dao import PatientDAO
from src.models.threshold_dao import ThresholdDAO


DEFAULT_METRICS = ['pulse', 'temperature', 'systolic_bp', 'diastolic_bp', 'heart_rate']
DEFAULT_RANGES = {
    'pulse':        (60.0, 100.0),
    'temperature':  (36.0, 37.5),
    'systolic_bp':  (90.0, 140.0),
    'diastolic_bp': (60.0, 90.0),
    'heart_rate':   (60.0, 100.0),
}


class PatientService:
    @staticmethod
    def list_active():
        return PatientDAO.get_all(only_active=True)

    @staticmethod
    def get(patient_id):
        return PatientDAO.get_by_id(patient_id)

    @staticmethod
    def add(data):
        """新增患者并自动创建默认阈值"""
        pid = PatientDAO.insert(data)
        # 创建默认阈值
        for metric in DEFAULT_METRICS:
            lo, hi = DEFAULT_RANGES[metric]
            ThresholdDAO.upsert(pid, metric, lo, hi, setter='系统默认')
        return pid

    @staticmethod
    def update(patient_id, data):
        PatientDAO.update(patient_id, data)

    @staticmethod
    def discharge(patient_id):
        PatientDAO.discharge(patient_id)
