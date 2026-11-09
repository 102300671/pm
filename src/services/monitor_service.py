"""
阈值检测服务 + 报警服务 + 定时采集服务
"""
import random
import threading
import time
from datetime import datetime

from src.models.log_dao import LogDAO
from src.models.threshold_dao import ThresholdDAO
from src.models.alarm_dao import AlarmDAO
from src.models.patient_dao import PatientDAO
from src.utils.db import METRIC_NAMES


class MonitorService:
    """定时采集生理信号并触发检测"""

    def __init__(self, interval=30, on_alarm=None, on_data_update=None):
        """
        :param interval: 采集间隔（秒）
        :param on_alarm: 报警回调函数，接收 violation 列表
        :param on_data_update: 数据更新回调（刷新界面用）
        """
        self.interval = interval
        self.on_alarm = on_alarm
        self.on_data_update = on_data_update
        self._running = False
        self._thread = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print(f"[Monitor] 定时采集已启动，间隔 {self.interval} 秒")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        print("[Monitor] 定时采集已停止")

    def _loop(self):
        # 启动后立即采集一次，然后按间隔执行
        self._tick()
        while self._running:
            time.sleep(self.interval)
            if self._running:
                self._tick()

    def _tick(self):
        """一次完整采集周期"""
        try:
            patients = PatientDAO.get_all(only_active=True)
            violations_this_round = []

            for p in patients:
                pid = p['patient_id']
                signals = self._generate_signals(pid)
                # 写入日志
                LogDAO.insert(pid, signals)
                # 阈值检测
                violations = ThresholdService.check(pid, signals)
                for v in violations:
                    v['patient_name'] = p['name']
                    v['ward_no'] = p['ward_no']
                    v['bed_no'] = p['bed_no']
                    # 触发报警（去重）
                    if not AlarmDAO.exists_pending(pid, v['metric_type']):
                        AlarmDAO.insert(pid, v['metric_type'],
                                        v['current_value'],
                                        v['lower_bound'], v['upper_bound'])
                        violations_this_round.append(v)

            if violations_this_round and self.on_alarm:
                self.on_alarm(violations_this_round)

            if self.on_data_update:
                self.on_data_update()

        except Exception as e:
            print(f"[Monitor] 采集周期异常: {e}")

    @staticmethod
    def _generate_signals(patient_id):
        """模拟生理信号生成"""
        # 用 patient_id + 当前时间做种子，保证同一病人信号相对稳定但有波动
        base = patient_id * 17
        now = time.time()
        rng = random.Random(base + int(now / 10))

        # 体温偶尔冲高模拟发烧
        temp = round(rng.gauss(36.8, 0.6), 1)
        if rng.random() < 0.1:  # 10% 概率突然发烧
            temp = round(rng.uniform(37.8, 39.2), 1)

        # 心率
        hr = round(rng.gauss(75, 8), 1)
        if rng.random() < 0.05:  # 5% 概率心率过低
            hr = round(rng.uniform(45, 58), 1)

        # 脉搏
        pulse = round(hr + rng.uniform(-2, 2), 1)

        # 血压
        sbp = round(rng.gauss(120, 10), 1)
        dbp = round(rng.gauss(78, 7), 1)

        # ECG 摘要
        ecg_rand = rng.random()
        if ecg_rand < 0.7:
            ecg = '窦性心律'
        elif ecg_rand < 0.9:
            ecg = '偶发早搏'
        else:
            ecg = 'ST段轻度异常'

        return {
            'pulse':        pulse,
            'temperature':  temp,
            'systolic_bp':  sbp,
            'diastolic_bp': dbp,
            'heart_rate':   hr,
            'ecg_summary':  ecg,
        }


class ThresholdService:
    """阈值检测"""

    @staticmethod
    def check(patient_id, signals):
        """
        检查所有指标是否超限
        :return: 违规事件列表，每项 {metric_type, current_value, lower_bound, upper_bound, violation_type}
        """
        thresholds = ThresholdDAO.get_by_patient(patient_id)
        if not thresholds:
            return []

        t_map = {t['metric_type']: t for t in thresholds}
        violations = []

        for metric_type, value in signals.items():
            if metric_type not in t_map or value is None:
                continue
            t = t_map[metric_type]
            lo = t['lower_bound']
            hi = t['upper_bound']

            if value < lo:
                violations.append({
                    'patient_id': patient_id,
                    'metric_type': metric_type,
                    'metric_name': METRIC_NAMES.get(metric_type, metric_type),
                    'current_value': value,
                    'lower_bound': lo,
                    'upper_bound': hi,
                    'violation_type': 'low',
                    'record_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                })
            elif value > hi:
                violations.append({
                    'patient_id': patient_id,
                    'metric_type': metric_type,
                    'metric_name': METRIC_NAMES.get(metric_type, metric_type),
                    'current_value': value,
                    'lower_bound': lo,
                    'upper_bound': hi,
                    'violation_type': 'high',
                    'record_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                })

        return violations


class AlarmService:
    """报警管理"""

    @staticmethod
    def list_pending():
        return AlarmDAO.get_pending()

    @staticmethod
    def confirm(alarm_id, handler='护士', note='已处理'):
        AlarmDAO.confirm(alarm_id, handler, note)

    @staticmethod
    def list_by_patient(patient_id, only_pending=False):
        return AlarmDAO.get_by_patient(patient_id, only_pending)
