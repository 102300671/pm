"""
患者监护系统 - 主程序入口
自动检测 tkinter：有 → 启动 GUI；无 → 启动 CLI 降级模式
"""
import sys
import os
import threading
import time
from datetime import datetime

# 确保 src 包可导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

GUI_AVAILABLE = True
try:
    import tkinter as tk
    from tkinter import ttk, messagebox, simpledialog, filedialog
except ImportError:
    GUI_AVAILABLE = False

from src.utils.db import init_database, METRIC_NAMES, METRIC_UNITS
from src.services.patient_service import PatientService
from src.services.monitor_service import MonitorService, AlarmService
from src.services.report_service import ReportService
from src.models.log_dao import LogDAO
from src.models.threshold_dao import ThresholdDAO


# ═══════════════════════════════════════════════════════════
#  CLI 降级模式 —— 当 tkinter 不可用时使用
# ═══════════════════════════════════════════════════════════

def _clear():
    os.system('cls' if os.name == 'nt' else 'clear')


def _cli_header():
    print("=" * 56)
    print("  🏥 患者监护系统 (CLI 模式)")
    print("=" * 56)
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  提示: 未检测到 tkinter，已进入命令行模式")
    print("=" * 56)


def cli_mode():
    init_database()

    monitor = MonitorService(
        interval=30,
        on_alarm=lambda vs: _cli_alarm(vs),
        on_data_update=lambda: None,
    )
    monitor.start()
    print("\n✅ 监控线程已启动（30 秒周期采集）\n")

    while True:
        _clear()
        _cli_header()
        print("""
  【主菜单】
   1. 查看所有在院患者
   2. 查看某患者最新生命体征
   3. 查看待处理报警
   4. 确认处理报警
   5. 设置/修改阈值
   6. 生成病情报告
   7. 新增患者
   8. 手动触发一次采集
   0. 退出
""")
        choice = input("  请选择 > ").strip()

        if choice == '1':
            patients = PatientService.list_active()
            print(f"\n  在院患者 ({len(patients)} 人):")
            print(f"  {'编号':<8}{'姓名':<10}{'性别':<6}{'病房':<8}{'诊断'}")
            print("  " + "-" * 50)
            for p in patients:
                print(f"  P{p['patient_id']:03d}   {p['name']:<10}{p['gender']:<6}"
                      f"{p['ward_no'] or '-':<8}{p['diagnosis'] or '-'}")
            input("\n  回车继续...")

        elif choice == '2':
            pid = _ask_pid()
            if pid:
                p = PatientService.get(pid)
                if not p:
                    print("  ❌ 未找到")
                else:
                    print(f"\n  📋 {p['name']} (P{pid:03d}) | {p['ward_no']} {p['bed_no']}床"
                          f" | {p['doctor']} | {p['diagnosis']}")
                    for l in LogDAO.get_latest(pid, limit=5):
                        print(f"  {l['record_time']} | 脉{l['pulse']} "
                              f"温{l['temperature']} 血{l['systolic_bp']}/{l['diastolic_bp']} "
                              f"心{l['heart_rate']} ECG:{l['ecg_summary']}")
                    if not LogDAO.get_latest(pid, limit=1):
                        print("  (暂无日志，选 8 手动采集)")
                    print("  ── 阈值 ──")
                    for t in ThresholdDAO.get_by_patient(pid):
                        print(f"    {METRIC_NAMES[t['metric_type']]}: "
                              f"{t['lower_bound']} ~ {t['upper_bound']}")
            input("\n  回车继续...")

        elif choice == '3':
            alarms = AlarmService.list_pending()
            print(f"\n  🔔 待处理报警 ({len(alarms)} 条):")
            for a in alarms:
                name = METRIC_NAMES.get(a['metric_type'], a['metric_type'])
                unit = METRIC_UNITS.get(a['metric_type'], '')
                print(f"  #{a['alarm_id']} | {a['alarm_time']} | "
                      f"{a['patient_name']}({a['ward_no']}-{a['bed_no']}) | "
                      f"{name} {a['current_value']}{unit} "
                      f"→ {a['threshold_lower']}~{a['threshold_upper']}")
            input("\n  回车继续...")

        elif choice == '4':
            alarms = AlarmService.list_pending()
            if not alarms:
                print("\n  ✅ 没有待处理报警")
            else:
                for a in alarms:
                    print(f"  #{a['alarm_id']} P{a['patient_id']:03d} "
                          f"{a['patient_name']} {METRIC_NAMES[a['metric_type']]}")
                ids = input("  输入要确认的报警编号 (空格分隔): ").strip()
                for sid in ids.split():
                    try:
                        AlarmService.confirm(int(sid), handler='CLI用户', note='命令行确认')
                        print(f"  ✅ 报警 #{sid} 已处理")
                    except ValueError:
                        print(f"  ❌ 无效: {sid}")
            input("\n  回车继续...")

        elif choice == '5':
            pid = _ask_pid()
            if pid:
                patient = PatientService.get(pid)
                print(f"\n  为 {patient['name']} 设置阈值 (直接回车保持不变)")
                for m in ['pulse', 'temperature', 'systolic_bp', 'diastolic_bp', 'heart_rate']:
                    cur = ThresholdDAO.get_one(pid, m)
                    cur_lo = cur['lower_bound'] if cur else ''
                    cur_hi = cur['upper_bound'] if cur else ''
                    print(f"\n  {METRIC_NAMES[m]} ({METRIC_UNITS[m]}) 当前: {cur_lo} ~ {cur_hi}")
                    lo_s = input("  下限: ").strip()
                    hi_s = input("  上限: ").strip()
                    if lo_s and hi_s:
                        try:
                            lo, hi = float(lo_s), float(hi_s)
                            if lo < hi:
                                ThresholdDAO.upsert(pid, m, lo, hi, setter='CLI医生')
                                print(f"  ✅ {METRIC_NAMES[m]}: {lo} ~ {hi}")
                            else:
                                print("  ❌ 下限必须小于上限")
                        except ValueError:
                            print("  ❌ 请输入数字")
            input("\n  回车继续...")

        elif choice == '6':
            pid = _ask_pid()
            if pid:
                report = ReportService.generate(pid)
                if report:
                    print(report)
                    if input("  保存到文件? (y/n): ").strip().lower() == 'y':
                        p = f"report_P{pid:03d}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                        ReportService.save_report(pid, p)
                        print(f"  ✅ 已保存: {p}")
            input("\n  回车继续...")

        elif choice == '7':
            print("\n  新增患者")
            data = {}
            data['name'] = input("  姓名 *: ").strip()
            if not data['name']:
                print("  ❌ 姓名必填"); input(); continue
            data['gender'] = input("  性别(男/女) *: ").strip() or '男'
            age = input("  年龄: ").strip()
            data['age'] = int(age) if age.isdigit() else None
            data['ward_no'] = input("  病房号: ").strip() or None
            data['bed_no'] = input("  床位号: ").strip() or None
            data['doctor'] = input("  主治医生: ").strip() or None
            data['diagnosis'] = input("  诊断: ").strip() or None
            pid = PatientService.add(data)
            print(f"  ✅ 新增成功！P{pid:03d}，已创建默认阈值")
            input("\n  回车继续...")

        elif choice == '8':
            print("\n  正在手动触发一次采集...")
            monitor._tick()
            print("  ✅ 采集完成")
            input("\n  回车继续...")

        elif choice == '0':
            monitor.stop()
            print("\n  👋 再见！")
            break
        else:
            print("\n  ⚠️ 无效选择"); time.sleep(0.5)


def _ask_pid():
    patients = PatientService.list_active()
    if not patients:
        print("\n  ❌ 没有在院患者"); input(); return None
    print(f"\n  在院患者:")
    for p in patients:
        print(f"    P{p['patient_id']:03d} {p['name']} ({p['ward_no']}-{p['bed_no']})")
    raw = input("  输入患者编号 (q 返回): ").strip()
    if raw.lower() == 'q': return None
    try:
        pid = int(raw)
        if any(p['patient_id'] == pid for p in patients):
            return pid
    except ValueError: pass
    print("  ❌ 无效编号")
    return None


def _cli_alarm(violations):
    print("\n" + "💥" * 20)
    print("  🚨 检测到生理信号超限！")
    for v in violations:
        unit = METRIC_UNITS.get(v['metric_type'], '')
        direction = '过低' if v['violation_type'] == 'low' else '过高'
        print(f"    → {v['patient_name']} P{v['patient_id']:03d} | "
              f"{v['metric_name']} {v['current_value']}{unit} ({direction}) | "
              f"范围 {v['lower_bound']}~{v['upper_bound']}{unit}")
    print("💥" * 20 + "\n")


# ═══════════════════════════════════════════════════════════
#  GUI 模式 —— 当 tkinter 可用时使用
# ═══════════════════════════════════════════════════════════

REFRESH_MS = 3000

if GUI_AVAILABLE:
    class PatientMonitorApp:
        """主应用"""
        def __init__(self, root):
            self.root = root
            self.root.title("🏥 患者监护系统 - Patient Monitoring System")
            self.root.geometry("1100x700")
            self.root.minsize(950, 600)
            init_database()
            self.monitor = MonitorService(
                interval=30,
                on_alarm=self._handle_alarm,
                on_data_update=self._schedule_refresh)
            self.selected_patient_id = None
            self._build_ui()
            self._refresh()
            self.monitor.start()

        def _build_ui(self):
            menubar = tk.Menu(self.root)
            file_menu = tk.Menu(menubar, tearoff=0)
            file_menu.add_command(label="新增患者", command=self._on_add_patient)
            file_menu.add_command(label="阈值设置", command=self._on_set_thresholds)
            file_menu.add_command(label="生成报告", command=self._on_generate_report)
            file_menu.add_separator()
            file_menu.add_command(label="退出", command=self._on_quit)
            menubar.add_cascade(label="操作", menu=file_menu)
            help_menu = tk.Menu(menubar, tearoff=0)
            help_menu.add_command(label="关于", command=self._on_about)
            menubar.add_cascade(label="帮助", menu=help_menu)
            self.root.config(menu=menubar)

            self.status_var = tk.StringVar(value="系统启动中...")
            tk.Label(self.root, textvariable=self.status_var, anchor='w',
                     relief=tk.SUNKEN, bd=1).pack(side=tk.BOTTOM, fill=tk.X)

            paned = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
            paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

            left = ttk.LabelFrame(paned, text=" 患者列表（在院） ")
            paned.add(left, weight=1)
            sf = ttk.Frame(left); sf.pack(fill=tk.X, padx=5, pady=(5, 2))
            ttk.Label(sf, text="搜索:").pack(side=tk.LEFT)
            self.search_var = tk.StringVar()
            self.search_var.trace_add('write', lambda *_: self._refresh_patient_list())
            ttk.Entry(sf, textvariable=self.search_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
            cols = ('id', 'name', 'gender', 'ward', 'bed')
            self.patient_tree = ttk.Treeview(left, columns=cols, show='headings', height=20)
            for c, t, w in [('id','编号',50),('name','姓名',70),('gender','性别',45),('ward','病房',55),('bed','床位',50)]:
                self.patient_tree.heading(c, text=t); self.patient_tree.column(c, width=w, anchor='center')
            self.patient_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            self.patient_tree.bind('<<TreeviewSelect>>', self._on_patient_select)
            bf = ttk.Frame(left); bf.pack(fill=tk.X, padx=5, pady=5)
            ttk.Button(bf, text="新增", command=self._on_add_patient).pack(side=tk.LEFT, padx=2)
            ttk.Button(bf, text="出院", command=self._on_discharge).pack(side=tk.LEFT, padx=2)

            right = ttk.Frame(paned)
            paned.add(right, weight=3)
            self.notebook = ttk.Notebook(right)
            self.notebook.pack(fill=tk.BOTH, expand=True)

            # Tab 1: 实时监测
            t1 = ttk.Frame(self.notebook); self.notebook.add(t1, text="📊 实时监测")
            info_frame = ttk.LabelFrame(t1, text=" 患者基本信息 ")
            info_frame.pack(fill=tk.X, padx=8, pady=8)
            self.info_labels = {}
            for i, key in enumerate(['姓名','编号','病房','医生','诊断']):
                ttk.Label(info_frame, text=f"{key}:", font=("",10,"bold")).grid(
                    row=0, column=i*2, sticky='w', padx=(8,4), pady=4)
                lbl = ttk.Label(info_frame, text="—"); lbl.grid(row=0, column=i*2+1, sticky='w', padx=(0,16), pady=4)
                self.info_labels[key] = lbl
            dlg = ttk.LabelFrame(t1, text=" 生命体征 "); dlg.pack(fill=tk.X, padx=8, pady=4)
            dcols = ('time','pulse','temp','sbp','dbp','hr','ecg','status')
            self.data_tree = ttk.Treeview(dlg, columns=dcols, show='headings', height=6)
            for c, t in zip(dcols, ['时间','脉搏','体温','收缩压','舒张压','心率','ECG','状态']):
                self.data_tree.heading(c, text=t); self.data_tree.column(c, width=90, anchor='center')
            self.data_tree.column('ecg', width=140); self.data_tree.column('status', width=70)
            self.data_tree.pack(fill=tk.X, padx=5, pady=5)
            thf = ttk.LabelFrame(t1, text=" 安全阈值 "); thf.pack(fill=tk.X, padx=8, pady=4)
            self.threshold_labels = {}
            for i, m in enumerate(['pulse','temperature','systolic_bp','diastolic_bp','heart_rate']):
                ttk.Label(thf, text=METRIC_NAMES[m]+":", font=("",9,"bold")).grid(
                    row=0, column=i, padx=10, pady=6, sticky='w')
                lbl = ttk.Label(thf, text="—"); lbl.grid(row=0, column=i, padx=(80,10), pady=6, sticky='w')
                self.threshold_labels[m] = lbl

            # Tab 2: 报警
            t2 = ttk.Frame(self.notebook); self.notebook.add(t2, text="🔔 待处理报警")
            tb = ttk.Frame(t2); tb.pack(fill=tk.X, padx=8, pady=8)
            ttk.Button(tb, text="确认选中报警", command=self._on_confirm_alarm).pack(side=tk.LEFT)
            ttk.Button(tb, text="刷新", command=self._refresh_alarm).pack(side=tk.LEFT, padx=5)
            self.alarm_count_var = tk.StringVar(value="")
            ttk.Label(tb, textvariable=self.alarm_count_var, foreground='red',
                      font=("",10,"bold")).pack(side=tk.RIGHT)
            acols = ('time','patient','ward','metric','value','range')
            self.alarm_tree = ttk.Treeview(t2, columns=acols, show='headings')
            for c, t in zip(acols, ['报警时间','患者','病房','指标','当前值','安全范围']):
                self.alarm_tree.heading(c, text=t); self.alarm_tree.column(c, width=110, anchor='center')
            self.alarm_tree.column('metric', width=140)
            self.alarm_tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0,8))

            # Tab 3: 历史日志
            t3 = ttk.Frame(self.notebook); self.notebook.add(t3, text="📋 历史日志")
            hcols = ('time','pulse','temp','sbp','dbp','hr','ecg')
            self.history_tree = ttk.Treeview(t3, columns=hcols, show='headings')
            for c, t in zip(hcols, ['时间','脉搏','体温','收缩压','舒张压','心率','ECG']):
                self.history_tree.heading(c, text=t)
                self.history_tree.column(c, width=110 if c!='ecg' else 140, anchor='center')
            self.history_tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        def _schedule_refresh(self): self.root.after(0, self._refresh)

        def _refresh(self):
            self._refresh_patient_list()
            self._refresh_selected_patient()
            self._refresh_alarm()
            self.status_var.set(
                f"最后更新: {datetime.now().strftime('%H:%M:%S')}  |  定时采集运行中 (间隔 30 秒)")
            self.root.after(REFRESH_MS, self._refresh)

        def _refresh_patient_list(self):
            for item in self.patient_tree.get_children():
                self.patient_tree.delete(item)
            kw = self.search_var.get().strip()
            for p in PatientService.list_active():
                if kw and kw not in (p['name'] or '') and kw not in (p['ward_no'] or ''):
                    continue
                self.patient_tree.insert('', tk.END, iid=str(p['patient_id']),
                    values=(p['patient_id'], p['name'], p['gender'], p['ward_no'], p['bed_no']))

        def _on_patient_select(self, _e):
            sel = self.patient_tree.selection()
            if sel:
                self.selected_patient_id = int(sel[0])
                self._refresh_selected_patient()

        def _refresh_selected_patient(self):
            pid = self.selected_patient_id
            p = PatientService.get(pid) if pid else None
            if not p:
                for k in self.info_labels: self.info_labels[k].config(text="—")
                for m in self.threshold_labels: self.threshold_labels[m].config(text="—")
                for tree in (self.data_tree, self.history_tree):
                    for it in tree.get_children(): tree.delete(it)
                return
            self.info_labels['姓名'].config(text=p['name'])
            self.info_labels['编号'].config(text=f"P{p['patient_id']:03d}")
            self.info_labels['病房'].config(text=f"{p['ward_no']} 房 {p['bed_no']} 床")
            self.info_labels['医生'].config(text=p['doctor'] or '—')
            self.info_labels['诊断'].config(text=p['diagnosis'] or '—')
            t_map = {t['metric_type']: t for t in ThresholdDAO.get_by_patient(pid)}
            for m in ['pulse','temperature','systolic_bp','diastolic_bp','heart_rate']:
                t = t_map.get(m)
                self.threshold_labels[m].config(
                    text=f"{t['lower_bound']} ~ {t['upper_bound']} {METRIC_UNITS[m]}" if t else "—")
            for it in self.data_tree.get_children(): self.data_tree.delete(it)
            for l in LogDAO.get_latest(pid, limit=10):
                st = self._judge(pid, l)
                stxt = {'ok':'✅ 正常','warn':'⚠️ 超限'}.get(st,'—')
                self.data_tree.insert('', tk.END, values=(
                    l['record_time'], l['pulse'], l['temperature'],
                    l['systolic_bp'], l['diastolic_bp'], l['heart_rate'],
                    l['ecg_summary'], stxt), tags=('warn' if st=='warn' else '',))
            self.data_tree.tag_configure('warn', background='#ffdddd')
            for it in self.history_tree.get_children(): self.history_tree.delete(it)
            for l in LogDAO.get_range(pid)[-50:]:
                self.history_tree.insert('', tk.END, values=(
                    l['record_time'], l['pulse'], l['temperature'],
                    l['systolic_bp'], l['diastolic_bp'], l['heart_rate'], l['ecg_summary']))

        def _judge(self, pid, log):
            t_map = {t['metric_type']: t for t in ThresholdDAO.get_by_patient(pid)}
            for m in ['pulse','temperature','systolic_bp','diastolic_bp','heart_rate']:
                v = log.get(m)
                if v is None or m not in t_map: continue
                t = t_map[m]
                if v < t['lower_bound'] or v > t['upper_bound']: return 'warn'
            return 'ok'

        def _refresh_alarm(self):
            for it in self.alarm_tree.get_children(): self.alarm_tree.delete(it)
            alarms = AlarmService.list_pending()
            for a in alarms:
                mt = a['metric_type']
                self.alarm_tree.insert('', tk.END, iid=str(a['alarm_id']), values=(
                    a['alarm_time'], a['patient_name'], f"{a['ward_no']}-{a['bed_no']}",
                    METRIC_NAMES.get(mt, mt), a['current_value'],
                    f"{a['threshold_lower']} ~ {a['threshold_upper']}"))
            self.alarm_count_var.set(f"待处理: {len(alarms)}")

        def _handle_alarm(self, vs): self.root.after(0, lambda: self._alarm_dialog(vs))

        def _alarm_dialog(self, vs):
            top = tk.Toplevel(self.root)
            top.title("⚠️ 生理信号超限报警")
            top.geometry("560x280")
            top.configure(bg='#fff3cd'); top.attributes('-topmost', True)
            tk.Label(top, text="🚨 检测到以下患者生理信号超出安全范围！",
                     font=("",12,"bold"), bg='#fff3cd', fg='#d9534f').pack(pady=10)
            frame = ttk.Frame(top); frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)
            tree = ttk.Treeview(frame, columns=('name','metric','value','range'), show='headings', height=6)
            for c,t,w in [('name','患者',100),('metric','指标',100),('value','当前值',100),('range','安全范围',150)]:
                tree.heading(c, text=t); tree.column(c, width=w, anchor='center')
            tree.pack(fill=tk.BOTH, expand=True)
            for v in vs:
                unit = METRIC_UNITS.get(v['metric_type'], '')
                dir = '过低' if v['violation_type']=='low' else '过高'
                tree.insert('', tk.END, values=(
                    v['patient_name'], v['metric_name'],
                    f"{v['current_value']} {unit} ({dir})",
                    f"{v['lower_bound']} ~ {v['upper_bound']} {unit}"))
            tk.Button(top, text="我知道了", command=top.destroy,
                      bg='#d9534f', fg='white', width=15).pack(pady=10)

        def _on_confirm_alarm(self):
            sel = self.alarm_tree.selection()
            if not sel:
                messagebox.showinfo("提示", "请先选择一条报警记录"); return
            if not messagebox.askyesno("确认", "确定已处理该报警？"): return
            for iid in sel: AlarmService.confirm(int(iid), handler='护士', note='GUI 确认处理')
            self._refresh_alarm(); messagebox.showinfo("成功", "报警已标记为已处理")

        def _on_add_patient(self):
            dlg = tk.Toplevel(self.root); dlg.title("新增患者"); dlg.geometry("400x380")
            dlg.transient(self.root); dlg.grab_set()
            entries = {}
            for i,(k,l) in enumerate([('name','姓名 *'),('gender','性别(男/女) *'),('age','年龄'),
                    ('ward_no','病房号'),('bed_no','床位号'),('doctor','主治医生'),('diagnosis','诊断')]):
                ttk.Label(dlg, text=l).grid(row=i, column=0, sticky='e', padx=8, pady=4)
                v = tk.StringVar(); ttk.Entry(dlg, textvariable=v, width=25).grid(row=i, column=1, padx=4, pady=4)
                entries[k] = v
            def submit():
                data = {k: v.get().strip() for k,v in entries.items()}
                if not data['name'] or not data['gender']:
                    messagebox.showerror("错误", "姓名和性别必填", parent=dlg); return
                data['age'] = int(data['age']) if data['age'].isdigit() else None
                pid = PatientService.add(data)
                messagebox.showinfo("成功", f"新增 P{pid:03d}", parent=dlg)
                dlg.destroy(); self._refresh()
            ttk.Button(dlg, text="提交", command=submit).grid(row=7, column=0, columnspan=2, pady=15)

        def _on_discharge(self):
            if not self.selected_patient_id:
                messagebox.showinfo("提示", "请先在左侧选择患者"); return
            p = PatientService.get(self.selected_patient_id)
            if messagebox.askyesno("出院确认", f"确定让 {p['name']} (P{p['patient_id']:03d}) 出院？"):
                PatientService.discharge(p['patient_id'])
                self.selected_patient_id = None; self._refresh()

        def _on_set_thresholds(self):
            if not self.selected_patient_id:
                messagebox.showinfo("提示", "请先在左侧选择患者"); return
            pid = self.selected_patient_id
            p = PatientService.get(pid)
            t_map = {t['metric_type']: t for t in ThresholdDAO.get_by_patient(pid)}
            dlg = tk.Toplevel(self.root); dlg.title(f"阈值设置 - {p['name']}"); dlg.geometry("450x380")
            dlg.transient(self.root); dlg.grab_set()
            ttk.Label(dlg, text="指标", font=("",10,"bold")).grid(row=0, column=0, padx=10, pady=8)
            ttk.Label(dlg, text="下限", font=("",10,"bold")).grid(row=0, column=1, padx=10, pady=8)
            ttk.Label(dlg, text="上限", font=("",10,"bold")).grid(row=0, column=2, padx=10, pady=8)
            ttk.Label(dlg, text="单位", font=("",10,"bold")).grid(row=0, column=3, padx=10, pady=8)
            entries = {}
            for i, m in enumerate(['pulse','temperature','systolic_bp','diastolic_bp','heart_rate']):
                row = i+1
                ttk.Label(dlg, text=METRIC_NAMES[m]).grid(row=row, column=0, sticky='e', padx=8, pady=4)
                cur = t_map.get(m, {})
                lv = tk.StringVar(value=str(cur.get('lower_bound','')))
                hv = tk.StringVar(value=str(cur.get('upper_bound','')))
                ttk.Entry(dlg, textvariable=lv, width=10).grid(row=row, column=1, padx=8, pady=4)
                ttk.Entry(dlg, textvariable=hv, width=10).grid(row=row, column=2, padx=8, pady=4)
                ttk.Label(dlg, text=METRIC_UNITS[m]).grid(row=row, column=3, padx=8, pady=4)
                entries[m] = (lv, hv)
            def save():
                for m,(lv,hv) in entries.items():
                    try:
                        lo, hi = float(lv.get()), float(hv.get())
                        if lo >= hi:
                            messagebox.showerror("错误", f"{METRIC_NAMES[m]}: 下限<上限", parent=dlg); return
                        ThresholdDAO.upsert(pid, m, lo, hi, setter='医生')
                    except ValueError:
                        messagebox.showerror("错误", f"{METRIC_NAMES[m]}: 请输入数字", parent=dlg); return
                messagebox.showinfo("成功", "阈值已保存", parent=dlg)
                dlg.destroy(); self._refresh_selected_patient()
            ttk.Button(dlg, text="保存", command=save).grid(row=6, column=1, columnspan=2, pady=20)

        def _on_generate_report(self):
            if not self.selected_patient_id:
                messagebox.showinfo("提示", "请先在左侧选择患者"); return
            report = ReportService.generate(self.selected_patient_id)
            if report is None: messagebox.showerror("错误", "无法生成报告"); return
            dlg = tk.Toplevel(self.root); dlg.title("病情报告"); dlg.geometry("720x600")
            text = tk.Text(dlg, font=("Consolas",10), wrap='none'); text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            text.insert('1.0', report); text.config(state='disabled')
            def save():
                path = filedialog.asksaveasfilename(
                    defaultextension=".txt",
                    initialfile=f"report_P{self.selected_patient_id:03d}.txt",
                    filetypes=[("文本文件","*.txt"),("所有文件","*.*")])
                if path:
                    open(path,'w',encoding='utf-8').write(report)
                    messagebox.showinfo("成功", f"已保存:\n{path}")
            bf = ttk.Frame(dlg); bf.pack(fill=tk.X, pady=5)
            ttk.Button(bf, text="💾 保存报告", command=save).pack(side=tk.LEFT, padx=10)
            ttk.Button(bf, text="关闭", command=dlg.destroy).pack(side=tk.RIGHT, padx=10)

        def _on_about(self):
            messagebox.showinfo("关于",
                "患者监护系统 (Patient Monitoring System)\n"
                "──────────────────────────────────\n"
                "《软件工程》综合实验\n"
                "技术栈: Python 3 + SQLite + tkinter")

        def _on_quit(self): self.monitor.stop(); self.root.destroy()


# ═══════════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════════

def run_gui():
    """tkinter GUI 模式 —— 修复 WSLg / Windows 高 DPI 下窗口不可见/越界问题"""
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # 修复 Windows 高 DPI 模糊/偏移
        except Exception:
            pass
    root = tk.Tk()
    app = PatientMonitorApp(root)
    root.update_idletasks()
    # 屏幕可能报告物理像素（如 WSLg 2520x1680），用 85% 比例+固定左上偏移，避免窗口超出可视区
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    ww, wh = min(1100, int(sw * 0.85)), min(700, int(sh * 0.85))
    root.geometry(f"{ww}x{wh}+60+40")
    root.deiconify()
    root.state('normal')
    root.lift()
    root.focus_force()
    print(f"✅ GUI 已启动 — {ww}x{wh}（屏幕 {sw}x{sh}）。若仍不可见请用 Web 模式: python3 main.py")
    try:
        root.mainloop()
    finally:
        app.monitor.stop()


def main():
    argv = sys.argv[1:]
    if '--gui' in argv:
        run_gui()
    elif '--cli' in argv:
        cli_mode()
    else:
        # 默认 Web 模式：浏览器界面，WSL / Windows / Linux 全平台可见
        from src.webapp import run_web
        run_web()


if __name__ == '__main__':
    main()
