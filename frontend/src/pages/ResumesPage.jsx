import { useState, useEffect, useRef } from 'react';
import api from '../services/api';
import { Upload, FileText, Trash2, ChevronDown, ChevronUp, Brain } from 'lucide-react';

export default function ResumesPage() {
  const [resumes, setResumes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [title, setTitle] = useState('');
  const [expandedId, setExpandedId] = useState(null);
  const [parsedChunks, setParsedChunks] = useState({});
  const fileRef = useRef();

  useEffect(() => {
    api.get('/resumes').then(({ data }) => setResumes(data)).finally(() => setLoading(false));
  }, []);

  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      if (title) formData.append('title', title);

      const { data } = await api.post('/resumes', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setResumes((prev) => [data, ...prev]);
      setTitle('');
      fileRef.current.value = '';
    } catch (err) {
      alert(err.response?.data?.detail || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (id) => {
    if (!confirm('Delete this resume and all its chunks?')) return;
    await api.delete(`/resumes/${id}`);
    setResumes((prev) => prev.filter((r) => r.id !== id));
  };

  const toggleExpand = async (id) => {
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(id);
    if (!parsedChunks[id]) {
      try {
        const { data } = await api.get(`/resumes/${id}`);
        setParsedChunks((prev) => ({ ...prev, [id]: data.parsed_data }));
      } catch {}
    }
  };

  const formatFileSize = (text) => {
    const bytes = new TextEncoder().encode(text).length;
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div>
      <div className="page-header">
        <h2>Resume Manager</h2>
        <p>Upload and manage your resume corpus for RAG-powered generation</p>
      </div>

      {/* Upload area */}
      <div className="card" style={{ marginBottom: 24 }}>
        <div className="card-header">
          <h3>Upload Resume</h3>
        </div>
        <div className="grid-2" style={{ alignItems: 'end' }}>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Title (optional)</label>
            <input
              className="form-input"
              placeholder="e.g. Software Engineer Resume v2"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>
          <div>
            <label className="btn btn-primary" style={{ cursor: 'pointer' }}>
              <Upload size={16} />
              {uploading ? 'Uploading...' : 'Choose File'}
              <input
                ref={fileRef}
                type="file"
                accept=".pdf,.docx,.txt"
                style={{ display: 'none' }}
                onChange={handleUpload}
                disabled={uploading}
              />
            </label>
            <span style={{ marginLeft: 12, fontSize: '0.8rem', color: 'var(--text-muted)' }}>
              PDF, DOCX, or TXT — max 10MB
            </span>
          </div>
        </div>
      </div>

      {/* Resume list */}
      {loading ? (
        <div className="loading-center"><div className="spinner" /></div>
      ) : resumes.length === 0 ? (
        <div className="empty-state">
          <FileText size={48} />
          <h3>No resumes uploaded</h3>
          <p>Upload your resume to get started with AI-powered job matching</p>
        </div>
      ) : (
        <div>
          {resumes.map((resume) => (
            <div key={resume.id} className="card" style={{ marginBottom: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <FileText size={20} color="var(--accent)" />
                  <div>
                    <div style={{ fontWeight: 600 }}>{resume.title}</div>
                    <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                      {resume.file_name} · {formatFileSize(resume.raw_text)} · {resume.chunk_count} chunks
                    </div>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button className="btn btn-secondary btn-sm" onClick={() => toggleExpand(resume.id)}>
                    <Brain size={14} />
                    {expandedId === resume.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    Parsed Data
                  </button>
                  <button className="btn btn-danger btn-sm" onClick={() => handleDelete(resume.id)}>
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>

              {/* Expanded parsed data */}
              {expandedId === resume.id && (
                <div style={{ marginTop: 16, padding: 16, background: 'var(--bg-primary)', borderRadius: 'var(--radius-sm)' }}>
                  {parsedChunks[resume.id] ? (
                    <div>
                      {parsedChunks[resume.id].skills?.length > 0 && (
                        <div style={{ marginBottom: 12 }}>
                          <strong style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>Skills:</strong>
                          <div style={{ marginTop: 4 }}>
                            {parsedChunks[resume.id].skills.map((s) => (
                              <span key={s} className="skill-tag">{s}</span>
                            ))}
                          </div>
                        </div>
                      )}
                      {parsedChunks[resume.id].summary && (
                        <div style={{ marginBottom: 12 }}>
                          <strong style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>Summary:</strong>
                          <p style={{ fontSize: '0.85rem', marginTop: 4, lineHeight: 1.5 }}>
                            {parsedChunks[resume.id].summary}
                          </p>
                        </div>
                      )}
                      {parsedChunks[resume.id].experience?.length > 0 && (
                        <div style={{ marginBottom: 12 }}>
                          <strong style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>Experience:</strong>
                          {parsedChunks[resume.id].experience.map((line, i) => (
                            <p key={i} style={{ fontSize: '0.85rem', marginTop: 2 }}>{line}</p>
                          ))}
                        </div>
                      )}
                      {parsedChunks[resume.id].education && (
                        <div>
                          <strong style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>Education:</strong>
                          <p style={{ fontSize: '0.85rem', marginTop: 4 }}>{parsedChunks[resume.id].education}</p>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="loading-center" style={{ padding: 16 }}><div className="spinner" /></div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
