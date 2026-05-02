#!/usr/bin/env python3
"""同步各官员统计数据 → data/officials_stats.json"""
import json, pathlib, datetime, logging
from file_lock import atomic_json_write
from sync_from_hermes_runtime import export_profile_sessions

log = logging.getLogger('officials')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s', datefmt='%H:%M:%S')

BASE = pathlib.Path(__file__).resolve().parent.parent
DATA = BASE / 'data'

# Anthropic 定价（每1M token，美元）
MODEL_PRICING = {
    'anthropic/claude-sonnet-4-6':  {'in':3.0, 'out':15.0, 'cr':0.30, 'cw':3.75},
    'anthropic/claude-opus-4-5':    {'in':15.0,'out':75.0, 'cr':1.50, 'cw':18.75},
    'anthropic/claude-haiku-3-5':   {'in':0.8, 'out':4.0,  'cr':0.08, 'cw':1.0},
    'openai/gpt-4o':                {'in':2.5, 'out':10.0, 'cr':1.25, 'cw':0},
    'openai/gpt-4o-mini':           {'in':0.15,'out':0.6,  'cr':0.075,'cw':0},
    'google/gemini-2.0-flash':      {'in':0.075,'out':0.3, 'cr':0,    'cw':0},
    'google/gemini-2.5-pro':        {'in':1.25,'out':10.0, 'cr':0,    'cw':0},
}

OFFICIALS = [
    {'id':'taizi',   'label':'太子',  'role':'太子',    'emoji':'🤴','rank':'储君'},
    {'id':'zhongshu','label':'中书省','role':'中书令',  'emoji':'📜','rank':'正一品'},
    {'id':'menxia',  'label':'门下省','role':'侍中',    'emoji':'🔍','rank':'正一品'},
    {'id':'shangshu','label':'尚书省','role':'尚书令',  'emoji':'📮','rank':'正一品'},
    {'id':'libu',    'label':'礼部',  'role':'礼部尚书','emoji':'📝','rank':'正二品'},
    {'id':'hubu',    'label':'户部',  'role':'户部尚书','emoji':'💰','rank':'正二品'},
    {'id':'bingbu',  'label':'兵部',  'role':'兵部尚书','emoji':'⚔️','rank':'正二品'},
    {'id':'xingbu',  'label':'刑部',  'role':'刑部尚书','emoji':'⚖️','rank':'正二品'},
    {'id':'gongbu',  'label':'工部',  'role':'工部尚书','emoji':'🔧','rank':'正二品'},
    {'id':'libu_hr', 'label':'吏部',  'role':'吏部尚书','emoji':'👔','rank':'正二品'},
    {'id':'zaochao', 'label':'钦天监','role':'朝报官',  'emoji':'📰','rank':'正三品'},
]

def rj(p, d):
    try:
        return json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
    except Exception:
        return d


def normalize_model(model_value, fallback='anthropic/claude-sonnet-4-6'):
    if isinstance(model_value, str) and model_value:
        return model_value
    if isinstance(model_value, dict):
        return model_value.get('primary') or model_value.get('id') or fallback
    return fallback

def get_model(agent_id):
    cfg = rj(DATA / 'agent_config.json', {})
    default = normalize_model(cfg.get('defaultModel'), 'anthropic/claude-sonnet-4-6')
    for agent in cfg.get('agents', []):
        if agent.get('id') == agent_id:
            return normalize_model(agent.get('model'), default)
    return default

def scan_agent(agent_id):
    """从 Hermes sessions export 读取 token 统计（累计所有 session）"""
    sessions = export_profile_sessions(agent_id)
    tin = tout = cr = cw = 0
    last_ts = None
    msg_count = 0

    for session in sessions:
        tin += session.get('input_tokens', 0) or 0
        tout += session.get('output_tokens', 0) or 0
        cr += session.get('cache_read_tokens', 0) or 0
        cw += session.get('cache_write_tokens', 0) or 0
        msg_count += session.get('message_count', 0) or len(session.get('messages', []) or [])
        ts = session.get('ended_at') or session.get('started_at')
        if ts:
            try:
                t = datetime.datetime.fromtimestamp(ts) if isinstance(ts, (int, float)) else datetime.datetime.fromisoformat(str(ts).replace('Z','+00:00'))
                if last_ts is None or t > last_ts: last_ts = t
            except Exception: pass

    return {
        'tokens_in': tin, 'tokens_out': tout,
        'cache_read': cr, 'cache_write': cw,
        'sessions': len(sessions),
        'last_active': last_ts.strftime('%Y-%m-%d %H:%M') if last_ts else None,
        'messages': msg_count,
    }

def calc_cost(s, model):
    p = MODEL_PRICING.get(model, MODEL_PRICING['anthropic/claude-sonnet-4-6'])
    usd = (s['tokens_in']/1e6*p['in'] + s['tokens_out']/1e6*p['out']
         + s['cache_read']/1e6*p['cr'] + s['cache_write']/1e6*p['cw'])
    return round(usd, 4)

def get_task_stats(org_label, tasks):
    done   = [t for t in tasks if t.get('state')=='Done' and t.get('org')==org_label]
    active = [t for t in tasks if t.get('state') in ('Doing','Review','Assigned') and t.get('org')==org_label]
    fl = sum(1 for t in tasks for f in t.get('flow_log',[])
             if f.get('from')==org_label or f.get('to')==org_label)
    # 参与的旨意（JJC）列表
    participated = []
    for t in tasks:
        if not t['id'].startswith('JJC'): continue
        for f in t.get('flow_log',[]):
            if f.get('from')==org_label or f.get('to')==org_label:
                if t['id'] not in [x['id'] for x in participated]:
                    participated.append({'id':t['id'],'title':t.get('title',''),'state':t.get('state','')})
                break
    return {'tasks_done':len(done),'tasks_active':len(active),
            'flow_participations':fl,'participated_edicts':participated}

def get_hb(agent_id, live_tasks):
    for t in live_tasks:
        if t.get('sourceMeta',{}).get('agentId')==agent_id and t.get('heartbeat'):
            return t['heartbeat']
    return {'status':'idle','label':'⚪ 待命','ageSec':None}

def main():
    tasks = rj(DATA/'tasks_source.json', [])
    live  = rj(DATA/'live_status.json', {})
    live_tasks = live.get('tasks', [])

    result = []
    for off in OFFICIALS:
        model   = get_model(off['id'])
        ss      = scan_agent(off['id'])
        ts      = get_task_stats(off['label'], tasks)
        hb      = get_hb(off['id'], live_tasks)
        cost_usd = calc_cost(ss, model)

        result.append({
            **off,
            'model': model,
            'model_short': model.split('/')[-1] if isinstance(model, str) and '/' in model else str(model),
            'sessions': ss['sessions'],
            'tokens_in': ss['tokens_in'],
            'tokens_out': ss['tokens_out'],
            'cache_read': ss['cache_read'],
            'cache_write': ss['cache_write'],
            'tokens_total': ss['tokens_in'] + ss['tokens_out'],
            'messages': ss['messages'],
            'cost_usd': cost_usd,
            'cost_cny': round(cost_usd * 7.25, 2),
            'last_active': ss['last_active'],
            'heartbeat': hb,
            'tasks_done': ts['tasks_done'],
            'tasks_active': ts['tasks_active'],
            'flow_participations': ts['flow_participations'],
            'participated_edicts': ts['participated_edicts'],
            'merit_score': ts['tasks_done']*10 + ts['flow_participations']*2 + min(ss['sessions'],20),
        })

    result.sort(key=lambda x: x['merit_score'], reverse=True)
    for i, r in enumerate(result): r['merit_rank'] = i+1

    totals = {
        'tokens_total': sum(r['tokens_total'] for r in result),
        'cache_total':  sum(r['cache_read']+r['cache_write'] for r in result),
        'cost_usd':     round(sum(r['cost_usd'] for r in result), 2),
        'cost_cny':     round(sum(r['cost_cny'] for r in result), 2),
        'tasks_done':   sum(r['tasks_done'] for r in result),
    }
    top = max(result, key=lambda x: x['merit_score'], default={})

    payload = {
        'generatedAt': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'officials': result,
        'totals': totals,
        'top_official': top.get('label',''),
    }
    atomic_json_write(DATA/'officials_stats.json', payload)
    log.info(f'{len(result)} officials | cost=¥{totals["cost_cny"]} | top={top.get("label","")}')

if __name__ == '__main__':
    main()
