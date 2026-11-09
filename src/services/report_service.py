"""
报告生成服务
"""
from datetime import datetime

from src.models.patient_dao import PatientDAO
from src.models.log_dao import LogDAO
from src.models.threshold_dao import ThresholdDAO
from src.models.alarm_dao import AlarmDAO
from src.utils.db import METRIC_NAMES, METRIC_UNITS


class ReportService:
    """生成患者病情报告"""

    @staticmethod
    def generate(patient_id, start_time=None, end_time=None):
        """
        生成纯文本格式的病情报告
        """
        patient = PatientDAO.get_by_id(patient_id)
        if not patient:
            return None

        logs = LogDAO.get_range(patient_id, start_time, end_time)
        alarms = AlarmDAO.get_by_patient(patient_id, only_pending=False)
        thresholds = ThresholdDAO.get_by_patient(patient_id)

        # 统计指标
        stats = ReportService._calc_stats(logs)

        # 组装报警记录
        alarm_lines = []
        for a in alarms:
            name = METRIC_NAMES.get(a['metric_type'], a['metric_type'])
            direction = '过高' if a['current_value'] > a['threshold_upper'] else '过低'
            status_text = '已处理' if a['status'] == 'handled' else '待处理'
            alarm_lines.append(
                f"  {a['alarm_time']} | {name} {a['current_value']} "
                f"(范围 {a['threshold_lower']}~{a['threshold_upper']}) "
                f"→ {direction} [{status_text}]"
            )

        # 组装阈值信息
        th_lines = []
        for t in thresholds:
            name = METRIC_NAMES.get(t['metric_type'], t['metric_type'])
            unit = METRIC_UNITS.get(t['metric_type'], '')
            th_lines.append(f"  {name}: {t['lower_bound']} ~ {t['upper_bound']} {unit}")

        # 组装日志简表（最多展示最近 30 条）
        log_lines = []
        for l in logs[-30:]:
            log_lines.append(
                f"  {l['record_time']} | 脉{l['pulse']} 温{l['temperature']} "
                f"血{l['systolic_bp']}/{l['diastolic_bp']} 心{l['heart_rate']}"
            )

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        time_range = f"{start_time or '最早'} ~ {end_time or '最新'}"

        report = f"""
╔══════════════════════════════════════════════════════════╗
║               患 者 病 情 监 测 报 告                      ║
╚══════════════════════════════════════════════════════════╝

  生成时间: {now}
  数据范围: {time_range}

──────────────────────────────────────────────────────────
  【患者基本信息】
──────────────────────────────────────────────────────────
  姓名: {patient['name']}    患者编号: P{patient['patient_id']:03d}
  性别: {patient['gender']}  年龄: {patient['age']}
  病房/床位: {patient['ward_no']} 房 {patient['bed_no']} 床
  主治医生: {patient['doctor']}
  诊断: {patient['diagnosis']}
  入院时间: {patient['admit_time']}
  状态: {'在院' if patient['status'] else '已出院'}

──────────────────────────────────────────────────────────
  【安全阈值】
──────────────────────────────────────────────────────────
{chr(10).join(th_lines) if th_lines else '  (未设置)'}

──────────────────────────────────────────────────────────
  【指标统计】（时间范围内）
──────────────────────────────────────────────────────────
{ReportService._format_stats(stats)}

──────────────────────────────────────────────────────────
  【报警/异常记录】（共 {len(alarms)} 条）
──────────────────────────────────────────────────────────
{chr(10).join(alarm_lines) if alarm_lines else '  无异常报警'}

──────────────────────────────────────────────────────────
  【日志摘录】（最近 {min(30, len(logs))} / {len(logs)} 条）
──────────────────────────────────────────────────────────
{chr(10).join(log_lines) if log_lines else '  暂无数据'}

══════════════════════════════════════════════════════════
"""
        return report

    @staticmethod
    def _calc_stats(logs):
        if not logs:
            return {}
        stats = {}
        metrics = ['pulse', 'temperature', 'systolic_bp', 'diastolic_bp', 'heart_rate']
        for m in metrics:
            vals = [l[m] for l in logs if l.get(m) is not None]
            if vals:
                stats[m] = {
                    'min': round(min(vals), 1),
                    'max': round(max(vals), 1),
                    'avg': round(sum(vals) / len(vals), 1),
                    'count': len(vals),
                }
        return stats

    @staticmethod
    def _format_stats(stats):
        if not stats:
            return '  (无数据)'
        lines = []
        for m, s in stats.items():
            name = METRIC_NAMES.get(m, m)
            unit = METRIC_UNITS.get(m, '')
            lines.append(
                f"  {name}: 最低 {s['min']} / 最高 {s['max']} / "
                f"平均 {s['avg']} {unit}  (共 {s['count']} 次)"
            )
        return '\n'.join(lines)

    @staticmethod
    def save_report(patient_id, file_path, start_time=None, end_time=None):
        """将报告保存到文件"""
        report = ReportService.generate(patient_id, start_time, end_time)
        if report is None:
            return False
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(report)
        return True
