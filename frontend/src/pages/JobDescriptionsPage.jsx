import { useState, useEffect } from 'react';
import api from '../services/api';
import { Plus, Trash2, ExternalLink, Briefcase, ChevronDown, ChevronUp } from 'lucide-react';

export default function JobDescriptionsPage() {
  const [jds, setJds] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [rawText, setRawText] = useState('');
  const [title, setTitle] = useState('');
  const [company, setCompany] = useState('');
  const [sourceUrl, setSourceUrl] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [expandedId, setExpandedId] = useState(null);

  useEffect(() => {
    api.get('/job-descriptions').then(({ data }) => setJds(data)).finally(() => setLoading(false));
  }, []);

  const handleCreate = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const { data } = await api.post('/job-descriptions', {
        raw_text: rawText,
        title,
        company,
        source_url: sourceUrl,
      });
      setJds((prev) => [data, ...prev]);
      setRawText('');
      setTitle('');
      setCompany('');
      setSourceUrl('');
      setShowForm(false);
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to create JD');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id) => {
    if (!confirm('Delete this job description?')) return;
    await api.delete(`/job-descriptions/${id}`);
    setJds((prev) => prev.filter((j) => j.id !== id));
  };

  return (
    <div>
      <div className="page-header">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <h2>Job Descriptions</h2>
            <p>Paste or import JDs for matching and analysis</p>
          </div>
          <button className="btn btn-primary" onClick={() => setShowForm(!showForm)}>
            <Plus size={16} /> Add JD
          </button>
        </div>
      </div>

      {/* Create form */}
      {showForm && (
        <div className="card" style={{ marginBottom: 24 }}>
          <div className="card-header">
            <h3>New Job Description</h3>
          </div>
          <form onSubmit={handleCreate}>
            <div className="grid-2">
              <div className="form-group">
                <label>Title (auto-detected if left empty)</label>
                <input className="form-input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Backend Engineer" />
              </div>
              <div className="form-group">
                <label>Company</label>
                <input className="form-input" value={company} onChange={(e) => setCompany(e.target.value)} placeholder="e.g. Acme Inc" />
              </div>
            </div>
            <div className="form-group">
              <label>Source URL (optional)</label>
              <input className="form-input" value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} placeholder="https://..." />
            </div>
            <div className="form-group">
              <label>Job Description Text</label>
              <textarea
                className="form-textarea"
                value={rawText}
                onChange={(e) => setRawText(e.target.value)}
                placeholder="Paste the full job description here..."
                rows={12}
                required
              />
            </div>
            <div className="btn-group">
              <button className="btn btn-primary" type="submit" disabled={submitting}>
                {submitting ? 'Creating...' : 'Parse & Save'}
              </button>
              <button className="btn btn-secondary" type="button" onClick={() => setShowForm(false)}>
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {/* JD list */}
      {loading ? (
        <div className="loading-center"><div className="spinner" /></div>
      ) : jds.length === 0 ? (
        <div className="empty-state">
          <Briefcase size={48} />
          <h3>No job descriptions yet</h3>
          <p>Add a JD to start matching and generating tailored content</p>
        </div>
      ) : (
        jds.map((jd) => (
          <div key={jd.id} className="card" style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <Briefcase size={20} color="var(--accent)" />
                <div>
                  <div style={{ fontWeight: 600 }}>{jd.title}</div>
                  <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                    {jd.company && `${jd.company} · `}
                    {jd.parsed_data?.seniority !== 'not specified' && `${jd.parsed_data.seniority} · `}
                    {jd.parsed_data?.must_have_skills?.length || 0} required skills
                  </div>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                {jd.source_url && (
                  <a href={jd.source_url} target="_blank" rel="noopener" className="btn btn-secondary btn-sm">
                    <ExternalLink size={14} /> View
                  </a>
                )}
                <button className="btn btn-secondary btn-sm" onClick={() => setExpandedId(expandedId === jd.id ? null : jd.id)}>
                  {expandedId === jd.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                </button>
                <button className="btn btn-danger btn-sm" onClick={() => handleDelete(jd.id)}>
                  <Trash2 size={14} />
                </button>
              </div>
            </div>

            {/* Expanded details */}
            {expandedId === jd.id && (
              <div style={{ marginTop: 16, padding: 16, background: 'var(--bg-primary)', borderRadius: 'var(--radius-sm)' }}>
                {jd.parsed_data?.must_have_skills?.length > 0 && (
                  <div style={{ marginBottom: 10 }}>
                    <strong style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>Must-Have Skills:</strong>
                    <div style={{ marginTop: 4 }}>
                      {jd.parsed_data.must_have_skills.map((s) => <span key={s} className="skill-tag">{s}</span>)}
                    </div>
                  </div>
                )}
                {jd.parsed_data?.nice_to_have_skills?.length > 0 && (
                  <div style={{ marginBottom: 10 }}>
                    <strong style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>Nice-to-Have:</strong>
                    <div style={{ marginTop: 4 }}>
                      {jd.parsed_data.nice_to_have_skills.map((s) => <span key={s} className="skill-tag" style={{ background: 'var(--success-dim)', color: 'var(--success)' }}>{s}</span>)}
                    </div>
                  </div>
                )}
                {jd.parsed_data?.responsibilities?.length > 0 && (
                  <div style={{ marginTop: 10 }}>
                    <strong style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>Responsibilities:</strong>
                    <ul style={{ marginTop: 4, paddingLeft: 20, fontSize: '0.85rem' }}>
                      {jd.parsed_data.responsibilities.slice(0, 8).map((r, i) => <li key={i} style={{ marginBottom: 2 }}>{r}</li>)}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}
