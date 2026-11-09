"""
患者监护系统 - Web 界面（零依赖，基于 Python 标准库 http.server）
在任意操作系统 / 浏览器中运行，彻底规避 WSLg 下 tkinter 窗口不可见的问题。
"""
import json
import os
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.db import init_database, METRIC_NAMES, METRIC_UNITS
from src.services.patient_service import PatientService
from src.services.monitor_service import MonitorService, AlarmService
from src.services.report_service import ReportService
from src.models.log_dao import LogDAO
from src.models.threshold_dao import ThresholdDAO

METRICS_JSON = json.dumps(
    {m: {'name': METRIC_NAMES[m], 'unit': METRIC_UNITS[m]}
     for m in ['pulse', 'temperature', 'systolic_bp', 'diastolic_bp', 'heart_rate']},
    ensure_ascii=False)

MONITOR = None  # 全局 MonitorService


# ═══════════════════════════ API 处理 ═══════════════════════════

class Handler(BaseHTTPRequestHandler):

    def log_message(self, *a):  # 静默访问日志
        pass

    def _send(self, body, code=200, ctype='application/json; charset=utf-8'):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b'{}')
        except json.JSONDecodeError:
            return {}

    # ---------- GET ----------
    def do_GET(self):
        u = urlparse(self.path)
        try:
            if u.path == '/':
                self._send(HTML.encode('utf-8'), ctype='text/html; charset=utf-8')
            elif u.path == '/api/state':
                self._send({
                    'now': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'patients': PatientService.list_active(),
                    'alarms': AlarmService.list_pending(),
                })
            elif u.path == '/api/detail':
                pid = int(parse_qs(u.query).get('pid', ['0'])[0])
                p = PatientService.get(pid)
                if not p:
                    self._send({'error': 'patient not found'}, 404)
                    return
                self._send({
                    'patient': p,
                    'thresholds': ThresholdDAO.get_by_patient(pid),
                    'latest': LogDAO.get_latest(pid, limit=10),
                    'history': LogDAO.get_range(pid)[-50:],
                })
            elif u.path.startswith('/api/report/'):
                pid = int(u.path.rsplit('/', 1)[-1])
                report = ReportService.generate(pid)
                self._send(report if report else {'error': '生成失败'},
                           ctype='text/plain; charset=utf-8')
            else:
                self._send({'error': 'not found'}, 404)
        except Exception as e:
            self._send({'error': str(e)}, 500)

    # ---------- POST ----------
    def do_POST(self):
        u = urlparse(self.path)
        body = self._body()
        try:
            if u.path == '/api/patient':
                if not body.get('name') or not body.get('gender'):
                    self._send({'ok': False, 'msg': '姓名和性别为必填'}, 400)
                    return
                age = body.get('age')
                pid = PatientService.add({
                    'name': body['name'].strip(),
                    'gender': body['gender'].strip(),
                    'age': int(age) if str(age).strip().isdigit() else None,
                    'ward_no': (body.get('ward_no') or '').strip() or None,
                    'bed_no': (body.get('bed_no') or '').strip() or None,
                    'doctor': (body.get('doctor') or '').strip() or None,
                    'diagnosis': (body.get('diagnosis') or '').strip() or None,
                })
                self._send({'ok': True, 'pid': pid, 'msg': f'新增患者成功 P{pid:03d}'})

            elif u.path.startswith('/api/patient/') and u.path.endswith('/discharge'):
                pid = int(u.path.split('/')[3])
                PatientService.discharge(pid)
                self._send({'ok': True, 'msg': '患者已出院'})

            elif u.path.startswith('/api/thresholds/'):
                pid = int(u.path.rsplit('/', 1)[-1])
                for metric, v in body.items():
                    lo, hi = float(v['lo']), float(v['hi'])
                    if lo >= hi:
                        self._send({'ok': False,
                                    'msg': f'{METRIC_NAMES.get(metric, metric)}: 下限必须小于上限'}, 400)
                        return
                for metric, v in body.items():
                    ThresholdDAO.upsert(pid, metric, float(v['lo']), float(v['hi']), setter='医生(Web)')
                self._send({'ok': True, 'msg': '阈值已保存'})

            elif u.path.startswith('/api/alarm/'):
                aid = int(u.path.split('/')[3])
                AlarmService.confirm(aid, handler=body.get('handler', '护士(Web)'),
                                     note=body.get('note', '网页确认处理'))
                self._send({'ok': True, 'msg': '报警已处理'})

            elif u.path == '/api/collect':
                MONITOR._tick()
                self._send({'ok': True, 'msg': '采集完成'})
            else:
                self._send({'error': 'not found'}, 404)
        except Exception as e:
            self._send({'ok': False, 'error': str(e)}, 500)


# ═══════════════════════════ 前端页面 ═══════════════════════════

HTML = r'''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>患者监护系统</title>
<style>
*{box-sizing:border-box;margin:0;padding:0;font-family:"Segoe UI","Microsoft YaHei",sans-serif}
body{background:#f4f6f9;color:#222;height:100vh;display:flex;flex-direction:column;overflow:hidden}
header{background:#1976d2;color:#fff;padding:10px 18px;display:flex;justify-content:space-between;align-items:center;flex-shrink:0}
header h1{font-size:17px;font-weight:600}
header .hb button{margin-left:8px}
main{display:flex;gap:12px;padding:12px;flex:1;min-height:0}
.left{width:270px;flex-shrink:0;display:flex;flex-direction:column;gap:8px}
.right{flex:1;display:flex;flex-direction:column;min-width:0}
.card{background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.13);padding:10px}
.plist{flex:1;overflow:auto}
.pitem{padding:8px 10px;border-radius:6px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;font-size:14px}
.pitem:hover{background:#e3f2fd}
.pitem.active{background:#1976d2;color:#fff}
.tabs{display:flex;gap:4px;flex-shrink:0}
.tab{padding:7px 16px;border-radius:8px 8px 0 0;cursor:pointer;background:#dde3ea;font-size:14px}
.tab.active{background:#fff;font-weight:600}
.tab .badge{background:#d9534f;color:#fff;border-radius:10px;padding:0 7px;font-size:12px;margin-left:4px}
.pane{display:none;background:#fff;border-radius:0 8px 8px 8px;box-shadow:0 1px 3px rgba(0,0,0,.13);padding:12px;flex:1;overflow:auto}
.pane.show{display:block}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:6px 8px;border-bottom:1px solid #eee;text-align:center}
th{background:#f0f3f7;white-space:nowrap}
tr.warn td{background:#ffecec}
button{border:none;border-radius:5px;padding:6px 13px;cursor:pointer;background:#e4e8ee;font-size:13px}
button.primary{background:#1976d2;color:#fff}
button.danger{background:#d9534f;color:#fff}
button:hover{filter:brightness(.94)}
input{padding:6px 8px;border:1px solid #ccc;border-radius:4px;width:100%;font-size:13px}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.45);display:none;align-items:center;justify-content:center;z-index:10}
.modal.show{display:flex}
.modal .box{background:#fff;border-radius:10px;padding:18px;width:min(580px,94vw);max-height:88vh;overflow:auto}
.modal h3{margin-bottom:12px}
.frow{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.frow label{width:82px;text-align:right;font-size:13px;flex-shrink:0}
.frow input{flex:1}
.toast{position:fixed;top:58px;right:14px;background:#b71c1c;color:#fff;padding:10px 14px;border-radius:8px;display:none;z-index:20;max-width:380px;font-size:13px;line-height:1.5;box-shadow:0 4px 12px rgba(0,0,0,.3)}
pre{white-space:pre-wrap;font-family:Consolas,monospace;font-size:12px;background:#f7f7f7;padding:10px;border-radius:6px}
.muted{color:#888;font-size:12px}
.th-grid{display:flex;flex-wrap:wrap;gap:10px 22px;font-size:13px;margin-top:6px}
.info{display:flex;flex-wrap:wrap;gap:6px 26px;font-size:14px;margin-bottom:8px}
.info b{color:#555}
</style>
</head>
<body>
<header>
  <h1>🏥 患者监护系统 <span class="muted" style="color:#cfe3f7" id="now"></span></h1>
  <div class="hb">
    <button onclick="collect()" style="background:#42a5f5;color:#fff">⏱ 手动采集</button>
    <button onclick="openAdd()">＋ 新增患者</button>
  </div>
</header>
<main>
  <div class="left">
    <input id="kw" placeholder="搜索姓名 / 病房号..." oninput="renderPatients()">
    <div class="card plist" id="plist"></div>
    <button class="danger" id="disBtn" onclick="discharge()" disabled>办理出院</button>
  </div>
  <div class="right">
    <div class="tabs">
      <div class="tab active" data-t="t1" onclick="switchTab(this)">📊 实时监测</div>
      <div class="tab" data-t="t2" onclick="switchTab(this)">🔔 报警 <span class="badge" id="ab" style="display:none">0</span></div>
      <div class="tab" data-t="t3" onclick="switchTab(this)">📋 历史日志</div>
    </div>
    <div class="pane show" id="t1">
      <div class="info" id="pinfo"><span class="muted">← 请在左侧选择患者</span></div>
      <table id="dtab"><thead><tr><th>记录时间</th><th>脉搏</th><th>体温℃</th><th>收缩压</th><th>舒张压</th><th>心率</th><th>ECG</th><th>状态</th></tr></thead><tbody></tbody></table>
      <div class="card" style="margin-top:10px"><b>安全阈值</b>
        <div class="th-grid" id="thview"></div>
        <div style="margin-top:8px"><button class="primary" onclick="openTh()" id="thBtn" disabled>修改阈值</button></div>
      </div>
    </div>
    <div class="pane" id="t2">
      <table id="atab"><thead><tr><th>报警时间</th><th>患者</th><th>病房</th><th>指标</th><th>当前值</th><th>安全范围</th><th>操作</th></tr></thead><tbody></tbody></table>
    </div>
    <div class="pane" id="t3">
      <table id="htab"><thead><tr><th>记录时间</th><th>脉搏</th><th>体温</th><th>收缩压</th><th>舒张压</th><th>心率</th><th>ECG</th></tr></thead><tbody></tbody></table>
    </div>
  </div>
</main>

<div class="toast" id="toast"></div>

<div class="modal" id="mAdd"><div class="box">
  <h3>新增患者</h3>
  <div class="frow"><label>姓名 *</label><input id="a_name"></div>
  <div class="frow"><label>性别 *</label><input id="a_gender" placeholder="男 / 女"></div>
  <div class="frow"><label>年龄</label><input id="a_age" type="number"></div>
  <div class="frow"><label>病房号</label><input id="a_ward"></div>
  <div class="frow"><label>床位号</label><input id="a_bed"></div>
  <div class="frow"><label>主治医生</label><input id="a_doctor"></div>
  <div class="frow"><label>诊断</label><input id="a_diag"></div>
  <div style="text-align:right;margin-top:12px">
    <button onclick="hide('mAdd')">取消</button>
    <button class="primary" onclick="addPatient()">提交</button>
  </div>
</div></div>

<div class="modal" id="mTh"><div class="box">
  <h3>阈值设置 <span class="muted" id="thName"></span></h3>
  <div id="thForm"></div>
  <div style="text-align:right;margin-top:12px">
    <button onclick="hide('mTh')">取消</button>
    <button class="primary" onclick="saveTh()">保存</button>
  </div>
</div></div>

<div class="modal" id="mRep"><div class="box" style="width:min(760px,94vw)">
  <h3>病情报告 <button style="float:right" onclick="hide('mRep')">关闭</button></h3>
  <pre id="repBody"></pre>
</div></div>

<script>
const M = __METRICS__;
let state = null, cur = null, detail = null, known = null;

const $ = id => document.getElementById(id);
const hide = id => $(id).classList.remove('show');
const show = id => $(id).classList.add('show');

async function api(path, opts){ const r = await fetch(path, opts); return r.json(); }

function toast(msg, ms=6000){
  const t = $('toast'); t.innerHTML = msg; t.style.display='block';
  clearTimeout(t._h); t._h = setTimeout(()=>t.style.display='none', ms);
}

function switchTab(el){
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.pane').forEach(p=>p.classList.remove('show'));
  el.classList.add('active'); $(el.dataset.t).classList.add('show');
}

/* ---------- 患者列表 ---------- */
function renderPatients(){
  const kw = $('kw').value.trim();
  $('plist').innerHTML = (state.patients||[]).filter(p =>
      !kw || (p.name||'').includes(kw) || (p.ward_no||'').includes(kw)
    ).map(p =>
      `<div class="pitem ${cur===p.patient_id?'active':''}" onclick="selectPatient(${p.patient_id})">
         <span><b>${p.name}</b> ${p.gender}</span>
         <span>${p.ward_no||'-'}-${p.bed_no||'-'}</span>
       </div>`).join('') || '<div class="muted" style="padding:10px">暂无在院患者</div>';
}

async function selectPatient(pid){ cur = pid; $('disBtn').disabled=false; $('thBtn').disabled=false; renderPatients(); await loadDetail(); }

async function loadDetail(){
  if(!cur) return;
  detail = await api('/api/detail?pid='+cur);
  if(detail.error){ toast('加载失败: '+detail.error); return; }
  const p = detail.patient;
  $('pinfo').innerHTML =
    `<span><b>姓名:</b> ${p.name}</span><span><b>编号:</b> P${String(p.patient_id).padStart(3,'0')}</span>`+
    `<span><b>病房:</b> ${p.ward_no||'-'} ${p.bed_no||''}</span><span><b>医生:</b> ${p.doctor||'-'}</span>`+
    `<span><b>诊断:</b> ${p.diagnosis||'-'}</span>`;
  const tmap = {}; detail.thresholds.forEach(t=>tmap[t.metric_type]=t);
  const row = (l,warn)=>`<tr class="${warn?'warn':''}"><td>${l.record_time}</td><td>${l.pulse??''}</td><td>${l.temperature??''}</td>`+
    `<td>${l.systolic_bp??''}</td><td>${l.diastolic_bp??''}</td><td>${l.heart_rate??''}</td><td>${l.ecg_summary||''}</td>`+
    `<td>${warn?'⚠️ 超限':'✅ 正常'}</td></tr>`;
  $('dtab').tBodies[0].innerHTML = detail.latest.map(l=>{
    for(const m in M){ const t=tmap[m]; const v=l[m];
      if(t && v!=null && (v<t.lower_bound || v>t.upper_bound)) return row(l,true); }
    return row(l,false);
  }).join('') || '<tr><td colspan="8" class="muted">暂无数据，点击右上角「手动采集」</td></tr>';
  $('htab').tBodies[0].innerHTML = detail.history.map(l=>
    `<tr><td>${l.record_time}</td><td>${l.pulse??''}</td><td>${l.temperature??''}</td><td>${l.systolic_bp??''}</td>`+
    `<td>${l.diastolic_bp??''}</td><td>${l.heart_rate??''}</td><td>${l.ecg_summary||''}</td></tr>`).join('');
  $('thview').innerHTML = Object.keys(M).map(m=>{ const t=tmap[m];
    return `<span><b>${M[m].name}</b>: ${t?t.lower_bound+' ~ '+t.upper_bound+' '+M[m].unit:'未设置'}</span>`; }).join('');
}

/* ---------- 报警 ---------- */
function renderAlarms(){
  const al = state.alarms||[];
  const b = $('ab'); b.style.display = al.length?'inline':'none'; b.textContent = al.length;
  $('atab').tBodies[0].innerHTML = al.map(a=>{
    const m = M[a.metric_type]||{name:a.metric_type,unit:''};
    return `<tr class="warn"><td>${a.alarm_time}</td><td>${a.patient_name}</td><td>${a.ward_no||''}-${a.bed_no||''}</td>`+
      `<td>${m.name}</td><td>${a.current_value} ${m.unit}</td><td>${a.threshold_lower} ~ ${a.threshold_upper}</td>`+
      `<td><button class="danger" onclick="confirmAlarm(${a.alarm_id})">确认处理</button></td></tr>`;
  }).join('') || '<tr><td colspan="7" class="muted">✅ 暂无待处理报警</td></tr>';
}
function checkNewAlarms(){
  const ids = new Set((state.alarms||[]).map(a=>a.alarm_id));
  if(known === null){ known = ids; return; }
  const fresh = [...ids].filter(i=>!known.has(i));
  if(fresh.length){
    const items = (state.alarms||[]).filter(a=>fresh.includes(a.alarm_id)).map(a=>{
      const m = M[a.metric_type]||{name:a.metric_type,unit:''};
      return `🚨 <b>${a.patient_name}</b> ${m.name} ${a.current_value}${m.unit}（范围 ${a.threshold_lower}~${a.threshold_upper}）`;
    });
    toast(items.join('<br>'), 10000);
  }
  known = ids;
}
async function confirmAlarm(id){
  const r = await api('/api/alarm/'+id, {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
  toast(r.ok?'✅ '+r.msg:('❌ '+(r.msg||r.error||'失败')));
  refresh();
}

/* ---------- 操作 ---------- */
function openAdd(){ ['a_name','a_gender','a_age','a_ward','a_bed','a_doctor','a_diag'].forEach(i=>$(i).value=''); show('mAdd'); }
async function addPatient(){
  const body = JSON.stringify({name:$('a_name').value, gender:$('a_gender').value, age:$('a_age').value,
    ward_no:$('a_ward').value, bed_no:$('a_bed').value, doctor:$('a_doctor').value, diagnosis:$('a_diag').value});
  const r = await api('/api/patient', {method:'POST', headers:{'Content-Type':'application/json'}, body});
  toast(r.ok?'✅ '+r.msg:('❌ '+(r.msg||r.error))); if(r.ok){ hide('mAdd'); refresh(); }
}
async function discharge(){
  if(!cur) return;
  if(!confirm('确定让该患者办理出院？')) return;
  const r = await api(`/api/patient/${cur}/discharge`, {method:'POST'});
  toast(r.ok?'✅ '+r.msg:('❌ '+(r.error||'失败')));
  cur = null; $('disBtn').disabled = true; $('thBtn').disabled = true;
  $('pinfo').innerHTML = '<span class="muted">← 请在左侧选择患者</span>';
  refresh();
}
function openTh(){
  if(!cur) return;
  const tmap = {}; (detail.thresholds||[]).forEach(t=>tmap[t.metric_type]=t);
  $('thName').textContent = detail.patient.name;
  $('thForm').innerHTML = Object.keys(M).map(m=>{ const t=tmap[m]||{};
    return `<div class="frow"><label>${M[m].name}(${M[m].unit})</label>
      <input id="th_${m}_lo" value="${t.lower_bound??''}" placeholder="下限">
      <span>~</span><input id="th_${m}_hi" value="${t.upper_bound??''}" placeholder="上限"></div>`; }).join('');
  show('mTh');
}
async function saveTh(){
  const body = {};
  for(const m in M){ const lo=$('th_'+m+'_lo').value, hi=$('th_'+m+'_hi').value;
    if(lo!=='' && hi!=='') body[m] = {lo:parseFloat(lo), hi:parseFloat(hi)}; }
  const r = await api('/api/thresholds/'+cur, {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(body)});
  toast(r.ok?'✅ '+r.msg:('❌ '+(r.msg||r.error))); if(r.ok){ hide('mTh'); loadDetail(); }
}
async function report(){
  if(!cur) return;
  const r = await fetch('/api/report/'+cur); const text = await r.text();
  $('repBody').textContent = text; show('mRep');
}
async function collect(){
  toast('⏳ 正在采集...');
  const r = await api('/api/collect', {method:'POST'});
  toast(r.ok?'✅ 采集完成':('❌ '+(r.error||'失败')));
  refresh();
}
function downloadReport(){
  if(!cur) return;
  fetch('/api/report/'+cur).then(r=>r.text()).then(t=>{
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([t], {type:'text/plain;charset=utf-8'}));
    a.download = `report_P${String(cur).padStart(3,'0')}.txt`; a.click();
  });
}

/* ---------- 轮询 ---------- */
async function refresh(){
  try{
    state = await api('/api/state');
    $('now').textContent = '　'+state.now;
    renderPatients(); renderAlarms(); checkNewAlarms();
    if(cur) loadDetail();
  }catch(e){ /* 服务器未就绪时静默 */ }
}
refresh(); setInterval(refresh, 3000);
</script>
</body>
</html>
'''.replace('__METRICS__', METRICS_JSON)


# ═══════════════════════════ 启动 ═══════════════════════════

def _open_browser(url):
    """跨平台打开浏览器：webbrowser → WSL 下 explorer.exe 兜底"""
    try:
        if webbrowser.open(url):
            return
    except Exception:
        pass
    try:
        if sys.platform.startswith('linux') and 'microsoft' in open('/proc/version').read().lower():
            subprocess.Popen(['explorer.exe', url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass  # 打不开就把 URL 打印给用户


def run_web(host='127.0.0.1', port=8000):
    global MONITOR
    init_database()
    MONITOR = MonitorService(interval=30, on_alarm=lambda vs: None)  # 前端轮询报警表即可
    MONITOR.start()

    server = None
    for p in range(port, port + 20):
        try:
            server = ThreadingHTTPServer((host, p), Handler)
            break
        except OSError:
            continue
    if server is None:
        print(f"❌ 端口 {port}~{port+19} 均被占用")
        return

    url = f"http://{host}:{server.server_address[1]}"
    print("=" * 56)
    print("  🏥 患者监护系统 (Web 模式)")
    print("=" * 56)
    print(f"  访问地址: {url}")
    print(f"  如未自动打开浏览器，请手动复制上方地址到浏览器")
    print(f"  停止服务: Ctrl + C")
    print("=" * 56)
    _open_browser(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        MONITOR.stop()
        server.server_close()
        print("\n👋 Web 服务已停止")
