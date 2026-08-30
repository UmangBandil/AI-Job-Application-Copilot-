import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import api from '../services/api';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell,
} from 'recharts';
import {
  Send, Briefcase, Target, TrendingUp, AlertTriangle, Plus,
} from 'lucide-react';

const COLORS = ['#6366f1', '#22c55e', '#f59e0b', '#3b82f6', '#ef4444'];

export default function DashboardPage() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/dashboard/stats')
      .then(({ data }) => setStats(data))
      .catch(() => setStats(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <div className="loading-center"><div className="spinner" /></div>;
  }

  if (!stats) {
    return (
      <div>
        <div className="page-header">
          <h2>Dashboard</h2>
          <p>Your job application overview</p>
        </div>
        <div className="empty-state">
          <Briefcase size={48} />
          <h3>Welcome to Job Copilot</h3>
          <p>Upload your resume and start analyzing job descriptions to get started.</p>
          <div style={{ marginTop: 16 }}>
            <Link to="/resumes" className="btn btn-primary"><Plus size={16} /> Upload Resume</Link>
          </div>
        </div>
      </div>
    );
  }

  const pieData = Object.entries(stats.applications_by_status)
    .filter(([, v]) => v > 0)
    .map(([key, val]) => ({ name: key.charAt(0).toUpperCase() + key.slice(1), value: val }));

  const skillData = stats.skill_gap_trends.slice(0, 10).map((s) => ({
    name: s.skill,
    count: s.frequency,
  }));

  return (
    <div>
      <div className="page-header">
        <h2>Dashboard</h2>
        <p>Your job application overview</p>
      </div>

      {/* Stat cards */}
      <div className="grid-4" style={{ marginBottom: 28 }}>
        <div className="card" style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div style={{ background: 'var(--accent-dim)', padding: 10, borderRadius: 10 }}>
            <Send size={20} color="var(--accent)" />
          </div>
          <div>
            <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>{stats.total_applications}</div>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>Total Applications</div>
          </div>
        </div>
        <div className="card" style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div style={{ background: 'var(--success-dim)', padding: 10, borderRadius: 10 }}>
            <Target size={20} color="var(--success)" />
          </div>
          <div>
            <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>{stats.average_match_score}%</div>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>Avg Match Score</div>
          </div>
        </div>
        <div className="card" style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div style={{ background: 'var(--warning-dim)', padding: 10, borderRadius: 10 }}>
            <TrendingUp size={20} color="var(--warning)" />
          </div>
          <div>
            <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>{stats.response_rate}%</div>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>Response Rate</div>
          </div>
        </div>
        <div className="card" style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div style={{ background: 'var(--info-dim)', padding: 10, borderRadius: 10 }}>
            <Briefcase size={20} color="var(--info)" />
          </div>
          <div>
            <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>{stats.applications_this_week}</div>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>This Week</div>
          </div>
        </div>
      </div>

      {/* Charts */}
      <div className="grid-2">
        <div className="card">
          <div className="card-header">
            <h3>Applications by Status</h3>
          </div>
          {pieData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie data={pieData} dataKey="value" cx="50%" cy="50%" outerRadius={80} label={({ name, value }) => `${name}: ${value}`}>
                  {pieData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                </Pie>
                <Tooltip contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8 }} />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: 40 }}>No applications yet</p>
          )}
        </div>

        <div className="card">
          <div className="card-header">
            <h3><AlertTriangle size={16} style={{ marginRight: 6 }} />Top Skill Gaps</h3>
          </div>
          {skillData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={skillData} layout="vertical" margin={{ left: 60 }}>
                <XAxis type="number" />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 12 }} width={100} />
                <Tooltip contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8 }} />
                <Bar dataKey="count" fill="var(--accent)" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: 40 }}>Analyze some JDs to see skill gaps</p>
          )}
        </div>
      </div>
    </div>
  );
}
