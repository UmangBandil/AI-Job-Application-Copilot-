import { useState, useEffect } from 'react';
import api from '../services/api';
import { Send, Plus, ChevronRight, Calendar, StickyNote, X } from 'lucide-react';

const COLUMNS = [
  { key: 'saved', label: 'Saved', color: 'var(--info)' },
  { key: 'applied', label: 'Applied', color: 'var(--accent)' },
  { key: 'interview', label: 'Interview', color: 'var(--warning)' },
  { key: 'offer', label: 'Offer', color: 'var(--success)' },
  { key: 'rejected', label: 'Rejected', color: 'var(--danger)' },
];

export default function TrackerPage() {
  const [applications, setApplications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedApp, setSelectedApp] = useState(null);
  const [notes, setNotes] = useState('');
  const [followUpDate, setFollowUpDate] = useState('');

  useEffect(() => {
    api.get('/applications').then(({ data }) => setApplications(data)).finally(() => setLoading(false));
  }, []);

  const handleStatusChange = async (appId, newStatus) => {
    try {
      const { data } = await api.patch(`/applications/${appId}`, { status: newStatus });
      setApplications((prev) => prev.map((a) => (a.id === appId ? { ...a, status: newStatus } : a)));
    } catch (err) {
      alert('Failed to update status');
    }
  };

  const handleSaveNotes = async () => {
    if (!selectedApp) return;
    try {
      const { data } = await api.patch(`/applications/${selectedApp.id}`, {
        notes,
        follow_up_date: followUpDate || null,
      });
      setApplications((prev) => prev.map((a) => (a.id === selectedApp.id ? { ...a, notes, follow_up_date: data.follow_up_date } : a)));
      setSelectedApp(null);
    } catch (err) {
      alert('Failed to save');
    }
  };

  const handleDelete = async (appId) => {
    if (!confirm('Delete this application?')) return;
    await api.delete(`/applications/${appId}`);
    setApplications((prev) => prev.filter((a) => a.id !== appId));
    setSelectedApp(null);
  };

  const formatDate = (d) => {
    if (!d) return '—';
    return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  return (
    <div>
      <div className="page-header">
        <h2>Application Tracker</h2>
        <p>Track your applications across the pipeline</p>
      </div>

      {loading ? (
        <div className="loading-center"><div className="spinner" /></div>
      ) : (
        <div className="kanban">
          {COLUMNS.map((col) => {
            const apps = applications.filter((a) => a.status === col.key);
            return (
              <div key={col.key} className="kanban-column">
                <div className="kanban-column-header">
                  <h4 style={{ color: col.color }}>{col.label}</h4>
                  <span className="kanban-count">{apps.length}</span>
                </div>

                {apps.length === 0 ? (
                  <div style={{ textAlign: 'center', padding: 20, color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                    No applications
                  </div>
                ) : (
                  apps.map((app) => (
                    <div
                      key={app.id}
                      className="kanban-card"
                      onClick={() => { setSelectedApp(app); setNotes(app.notes || ''); setFollowUpDate(app.follow_up_date ? app.follow_up_date.split('T')[0] : ''); }}
                    >
                      <h5>{app.job_title || 'Untitled Position'}</h5>
                      <div className="company">{app.company || 'Unknown company'}</div>
                      <div className="meta">
                        <span>Score: {app.match_score != null ? `${app.match_score}%` : '—'}</span>
                        <span>{formatDate(app.created_at)}</span>
                      </div>
                      {app.follow_up_date && (
                        <div style={{ marginTop: 6, fontSize: '0.72rem', color: 'var(--warning)', display: 'flex', alignItems: 'center', gap: 4 }}>
                          <Calendar size={12} /> Follow up: {formatDate(app.follow_up_date)}
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Detail modal */}
      {selectedApp && (
        <div className="modal-overlay" onClick={() => setSelectedApp(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h3 style={{ margin: 0 }}>{selectedApp.job_title || 'Application'}</h3>
              <button style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }} onClick={() => setSelectedApp(null)}>
                <X size={20} />
              </button>
            </div>

            <div style={{ marginBottom: 16 }}>
              <strong style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>Company:</strong> {selectedApp.company || '—'}
            </div>
            <div style={{ marginBottom: 16 }}>
              <strong style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>Match Score:</strong> {selectedApp.match_score != null ? `${selectedApp.match_score}%` : '—'}
            </div>

            {/* Status change */}
            <div className="form-group">
              <label>Status</label>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {COLUMNS.map((col) => (
                  <button
                    key={col.key}
                    className={`btn btn-sm ${selectedApp.status === col.key ? 'btn-primary' : 'btn-secondary'}`}
                    onClick={() => handleStatusChange(selectedApp.id, col.key)}
                  >
                    {col.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Notes */}
            <div className="form-group">
              <label><StickyNote size={14} style={{ marginRight: 4, verticalAlign: 'middle' }} /> Notes</label>
              <textarea
                className="form-textarea"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Add notes about this application..."
                rows={4}
              />
            </div>

            {/* Follow-up date */}
            <div className="form-group">
              <label><Calendar size={14} style={{ marginRight: 4, verticalAlign: 'middle' }} /> Follow-up Date</label>
              <input
                type="date"
                className="form-input"
                value={followUpDate}
                onChange={(e) => setFollowUpDate(e.target.value)}
              />
            </div>

            <div className="btn-group" style={{ marginTop: 8 }}>
              <button className="btn btn-primary" onClick={handleSaveNotes}>Save</button>
              <button className="btn btn-danger btn-sm" onClick={() => handleDelete(selectedApp.id)}>Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
