import { useEffect, useState } from 'react';
import { useStore } from '../store';
import { api, type HermesProfileInfo, type HermesProfileTestResult } from '../api';

const CHANNELS = [
  { id: 'feishu', label: '飞书 Feishu' },
  { id: 'telegram', label: 'Telegram' },
  { id: 'wecom', label: '企业微信 WeCom' },
  { id: 'discord', label: 'Discord' },
  { id: 'slack', label: 'Slack' },
  { id: 'signal', label: 'Signal' },
  { id: 'tui', label: 'TUI (终端)' },
];

function Badge({ ok, text }: { ok: boolean; text: string }) {
  return (
    <span
      style={{
        fontSize: 11,
        padding: '3px 8px',
        borderRadius: 999,
        border: `1px solid ${ok ? '#2ecc8a44' : '#ff527044'}`,
        color: ok ? 'var(--ok)' : 'var(--danger)',
        background: ok ? '#0a2018' : '#200a10',
        whiteSpace: 'nowrap',
      }}
    >
      {ok ? '✓' : '×'} {text}
    </span>
  );
}

function ResultBox({ result }: { result?: HermesProfileTestResult }) {
  if (!result) return null;
  const text = result.ok
    ? result.stdout || result.message || 'Hermes profile 可用'
    : result.error || result.stderr || result.stdout || 'Hermes profile 测试失败';
  return (
    <div className={`mc-st ${result.ok ? 'ok' : 'err'}`}>
      <div>{result.ok ? '✅ 测试通过' : '❌ 测试失败'}{result.elapsedSec != null ? ` · ${result.elapsedSec}s` : ''}</div>
      <div style={{ marginTop: 4, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{text}</div>
    </div>
  );
}

export default function ModelConfig() {
  const agentConfig = useStore((s) => s.agentConfig);
  const loadAgentConfig = useStore((s) => s.loadAgentConfig);
  const toast = useStore((s) => s.toast);

  const [profiles, setProfiles] = useState<HermesProfileInfo[]>([]);
  const [hermesHome, setHermesHome] = useState('');
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState<Record<string, boolean>>({});
  const [results, setResults] = useState<Record<string, HermesProfileTestResult>>({});
  const [channelSel, setChannelSel] = useState('feishu');
  const [channelStatus, setChannelStatus] = useState('');

  const loadProfiles = async () => {
    setLoading(true);
    try {
      const data = await api.hermesProfileStatus();
      setProfiles(data.agents || []);
      setHermesHome(data.hermesHome || '');
    } catch {
      toast('无法读取 Hermes profile 状态', 'err');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAgentConfig();
    loadProfiles();
  }, [loadAgentConfig]);

  useEffect(() => {
    if (agentConfig?.dispatchChannel) setChannelSel(agentConfig.dispatchChannel);
  }, [agentConfig]);

  const testProfile = async (agentId: string) => {
    setTesting((prev) => ({ ...prev, [agentId]: true }));
    try {
      const result = await api.testHermesProfile(agentId);
      setResults((prev) => ({ ...prev, [agentId]: result }));
      toast(result.ok ? `${agentId} Hermes profile 测试通过` : `${agentId} Hermes profile 测试失败`, result.ok ? 'ok' : 'err');
    } catch {
      setResults((prev) => ({ ...prev, [agentId]: { ok: false, agentId, error: '无法连接后端测试接口' } }));
      toast('无法连接后端测试接口', 'err');
    } finally {
      setTesting((prev) => ({ ...prev, [agentId]: false }));
    }
  };

  if (loading && !profiles.length) {
    return <div className="empty" style={{ gridColumn: '1/-1' }}>正在读取 Hermes profile...</div>;
  }

  if (!profiles.length) {
    return <div className="empty" style={{ gridColumn: '1/-1' }}>⚠️ 未发现 Hermes profile，请先运行 bootstrap 或启动 Docker 轻量环境</div>;
  }

  return (
    <div>
      <div className="cl-wrap" style={{ marginBottom: 16 }}>
        <div className="cl-title">Hermes Profile 状态</div>
        <div style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.7 }}>
          当前页面只读取 Hermes profile/config.yaml 与 .env。模型真正由 Hermes 自己决定；这里不再写入旧 OpenClaw 模型配置。
        </div>
        <div style={{ marginTop: 8, fontSize: 11, color: 'var(--muted)', wordBreak: 'break-all' }}>
          HERMES_HOME: <b style={{ color: 'var(--text)' }}>{hermesHome || '未设置'}</b>
        </div>
      </div>

      <div className="model-grid">
        {profiles.map((ag) => {
          const canTest = ag.profileExists && ag.configExists;
          return (
            <div className="mc-card" key={ag.id}>
              <div className="mc-top">
                <span className="mc-emoji">{ag.emoji || '🏛️'}</span>
                <div>
                  <div className="mc-name">
                    {ag.label}{' '}
                    <span style={{ fontSize: 11, color: 'var(--muted)' }}>{ag.id}</span>
                  </div>
                  <div className="mc-role">{ag.role}</div>
                </div>
              </div>

              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
                <Badge ok={ag.profileExists} text="profile" />
                <Badge ok={ag.configExists} text="config.yaml" />
                <Badge ok={ag.envExists} text=".env" />
              </div>

              <div className="mc-cur">模型: <b>{ag.model || 'Hermes 默认配置'}</b></div>
              <div className="mc-cur">Provider: <b>{ag.provider || '由 Hermes 推断'}</b></div>
              <div className="mc-cur">技能: <b>{ag.skillsCount}</b> 个</div>
              <div className="mc-cur" style={{ wordBreak: 'break-all' }}>Profile: <b>{ag.profile}</b></div>

              <div className="mc-btns">
                <button className="btn btn-p" disabled={!canTest || testing[ag.id]} onClick={() => testProfile(ag.id)}>
                  {testing[ag.id] ? '测试中...' : '轻量测试'}
                </button>
                <button className="btn btn-g" onClick={loadProfiles}>刷新</button>
              </div>
              {!canTest && <div className="mc-st err">需要 profile 目录和 config.yaml，才能调用 Hermes 轻量测试。</div>}
              <ResultBox result={results[ag.id]} />
            </div>
          );
        })}
      </div>

      <div style={{ marginTop: 24, marginBottom: 8 }}>
        <div className="sec-title">派发渠道</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0', flexWrap: 'wrap' }}>
          <select className="msel" value={channelSel} onChange={(e) => setChannelSel(e.target.value)} style={{ maxWidth: 220 }}>
            {CHANNELS.map((ch) => <option key={ch.id} value={ch.id}>{ch.label}</option>)}
          </select>
          <button
            className="btn btn-p"
            disabled={channelSel === (agentConfig?.dispatchChannel || 'feishu')}
            onClick={async () => {
              try {
                const r = await api.setDispatchChannel(channelSel);
                if (r.ok) {
                  setChannelStatus('✅ 已保存');
                  toast('派发渠道已切换', 'ok');
                  loadAgentConfig();
                } else {
                  setChannelStatus('❌ ' + (r.error || '失败'));
                }
              } catch {
                setChannelStatus('❌ 无法连接');
              }
              setTimeout(() => setChannelStatus(''), 3000);
            }}
          >
            应用
          </button>
          {channelStatus && (
            <span style={{ fontSize: 12, color: channelStatus.startsWith('✅') ? 'var(--ok)' : 'var(--danger)' }}>
              {channelStatus}
            </span>
          )}
        </div>
        <div style={{ fontSize: 11, color: 'var(--muted)' }}>这里只记录 dashboard 的派发偏好；具体通知能力仍以 Hermes profile 配置为准。</div>
      </div>
    </div>
  );
}
