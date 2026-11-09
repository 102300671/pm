"""
患者监护系统 - 自动化测试脚本
运行方式: python3 test/test_services.py
"""
import os
import sys

# 让测试脚本可以从任意目录运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 使用独立的测试数据库，避免污染正式数据
from src.utils.db import DB_PATH as PROD_DB_PATH
_TEST_DB_PATH = PROD_DB_PATH + '.test'

# 在导入 src.utils.db 之前覆盖 DB_PATH
import src.utils.db as db_module
db_module.DB_PATH = _TEST_DB_PATH
# 重新触发 makedirs
os.makedirs(os.path.dirname(_TEST_DB_PATH), exist_ok=True)


def cleanup_test_db():
    if os.path.exists(_TEST_DB_PATH):
        os.remove(_TEST_DB_PATH)


def run_tests():
    passed = 0
    failed = 0
    errors = []

    def check(name, condition, detail=''):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  ✅ {name}")
        else:
            failed += 1
            msg = f"  ❌ {name}"
            if detail:
                msg += f" — {detail}"
            print(msg)
            errors.append(name)

    print("=" * 60)
    print("  患者监护系统 — 自动化测试")
    print("=" * 60)

    # ── 1. 数据库初始化 ──
    print("\n【1. 数据库初始化】")
    cleanup_test_db()
    from src.utils.db import init_database, DB_PATH
    init_database()
    check("DB 文件创建", os.path.exists(DB_PATH))

    # ── 2. 患者 CRUD ──
    print("\n【2. 患者管理 (PatientService)】")
    from src.services.patient_service import PatientService

    patients = PatientService.list_active()
    check("查询在院患者 (初始应为 4 人)", len(patients) == 4, f"实际: {len(patients)}")

    new_id = PatientService.add({
        'name': '测试患者',
        'gender': '男',
        'age': 50,
        'ward_no': '999',
        'bed_no': 'Z1',
        'doctor': '测试医生',
        'diagnosis': '测试诊断',
    })
    check("新增患者", new_id is not None and new_id > 0)

    p = PatientService.get(new_id)
    check("查询单个患者", p is not None and p['name'] == '测试患者')

    patients2 = PatientService.list_active()
    check("新增后列表 +1", len(patients2) == 5, f"实际: {len(patients2)}")

    PatientService.discharge(new_id)
    p_after = PatientService.get(new_id)
    check("出院后 status=0", p_after['status'] == 0)

    # ── 3. 阈值管理 ──
    print("\n【3. 阈值管理 (ThresholdDAO)】")
    from src.models.threshold_dao import ThresholdDAO

    t_list = ThresholdDAO.get_by_patient(1)
    check("查询 P001 默认阈值 (应为 5 项)", len(t_list) == 5, f"实际: {len(t_list)}")

    ThresholdDAO.upsert(1, 'temperature', 35.5, 38.0, setter='测试')
    t = ThresholdDAO.get_one(1, 'temperature')
    check("修改阈值生效", t['lower_bound'] == 35.5 and t['upper_bound'] == 38.0)

    # ── 4. 日志 ──
    print("\n【4. 日志 (LogDAO)】")
    from src.models.log_dao import LogDAO

    signals = {
        'pulse': 80.0, 'temperature': 36.8,
        'systolic_bp': 120, 'diastolic_bp': 80,
        'heart_rate': 80.0, 'ecg_summary': '正常'
    }
    LogDAO.insert(1, signals)
    logs = LogDAO.get_latest(1, limit=1)
    check("写入并查询最新日志", len(logs) >= 1 and logs[0]['pulse'] == 80.0)

    # ── 5. 阈值检测 ──
    print("\n【5. 阈值检测 (ThresholdService)】")
    from src.services.monitor_service import ThresholdService

    # 人为给一个超范围的值
    bad_signals = {
        'pulse': 80, 'temperature': 39.5,  # 超上限 38.0
        'systolic_bp': 120, 'diastolic_bp': 80,
        'heart_rate': 40,  # 低于下限 60
    }
    violations = ThresholdService.check(1, bad_signals)
    violation_types = {v['metric_type']: v['violation_type'] for v in violations}
    check("检测出体温过高", violation_types.get('temperature') == 'high',
          f"violations: {violations}")
    check("检测出心率过低", violation_types.get('heart_rate') == 'low',
          f"violations: {violations}")

    # ── 6. 报警去重 ──
    print("\n【6. 报警去重 (AlarmDAO)】")
    from src.models.alarm_dao import AlarmDAO

    AlarmDAO.insert(1, 'temperature', 39.5, 35.5, 38.0)
    dup = AlarmDAO.exists_pending(1, 'temperature')
    check("pending 报警存在时返回 True", dup is True)
    AlarmDAO.confirm(AlarmDAO.get_pending()[0]['alarm_id'], handler='测试', note='已确认')
    dup2 = AlarmDAO.exists_pending(1, 'temperature')
    check("确认后 pending 报警清除", dup2 is False)

    # ── 7. 报告生成 ──
    print("\n【7. 报告生成 (ReportService)】")
    from src.services.report_service import ReportService

    report = ReportService.generate(1)
    check("报告不为 None", report is not None)
    check("报告包含患者姓名", '张三' in report)
    check("报告包含诊断", '高血压观察' not in report or '急性肺炎' in report)

    save_ok = ReportService.save_report(1, '/tmp/test_report.txt')
    check("报告保存到文件", save_ok and os.path.exists('/tmp/test_report.txt'))
    os.remove('/tmp/test_report.txt')

    # ── 汇总 ──
    print("\n" + "=" * 60)
    total = passed + failed
    print(f"  总计: {total} 项 | 通过: {passed} | 失败: {failed}")
    print("=" * 60)
    if errors:
        print(f"\n失败项: {errors}")
    cleanup_test_db()
    return failed == 0


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
