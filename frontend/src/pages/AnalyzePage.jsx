import { useState, useEffect } from 'react';
import api from '../services/api';
import { Target, Sparkles, FileText, Copy, Check } from 'lucide-react';

export default function AnalyzePage() {
  const [resumes, setResumes] = useState([]);
  const [jds, setJds] = useState([]);
  const [selectedResume, setSelectedResume] = useState('');
  const [selectedJD, setSelectedJD] = useState('');

  // Match
  const [matchResult, setMatchResult] = useState(null);
  const [matching, setMatching] = useState(false);

  // Generation
  const [contentType, setContentType] = useState('cover_letter');
  const [tone, setTone] = useState('formal');
  const [length, setLength] = useState('concise');
  const [generated, setGenerated] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    Promise.all([
      api.get('/resumes'),
      api.get('/job-descriptions'),
    ]).then(([r, j]) => {
      setResumes(r.data);
      setJds(j.data);
    });
  }, []);

  const handleMatch = async () => {
    if (!selectedResume || !selectedJD) return alert('Select both a resume and a JD');
    setMatching(true);
    setMatchResult(null);
    try {
      const { data } = await api.post('/job-descriptions/match', {
        resume_id: selectedResume,
        job_description_id: selectedJD,
      });
      setMatchResult(data);
    } catch (err) {
      alert(err.response?.data?.detail || 'Match failed');
    } finally {
      setMatching(false);
    }
  };

  const handleGenerate = async () => {
    if (!selectedResume || !selectedJD) return alert('Select both a resume and a JD');
    setGenerating(true);
    setGenerated(null);
    try {
      const { data } = await api.post('/generate', {
        resume_id: selectedResume,
        job_description_id: selectedJD,
        content_type: contentType,
        tone,
        length,
      });
      setGenerated(data);
    } catch (err) {
      alert(err.response?.data?.detail || 'Generation failed');
    } finally {
      setGenerating(false);
    }
  };

  const handleCopy = () => {
    if (generated?.content) {
      navigator.clipboard.writeText(generated.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const scoreClass = (score) => {
    if (score >= 70) return 'high';
    if (score >= 40) return 'medium';
    return 'low';
  };

  return (
    <div>
      <div className="page-header">
        <h2>Analyze & Generate</h2>
        <p>Match your resume against a JD, then generate tailored content</p>
      </div>

      {/* Selection */}
      <div className="card" style={{ marginBottom: 20 }}>
        <div className="grid-2" style={{ gap: 16 }}>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Select Resume</label>
            <select className="form-select" style={{ width: '100%' }} value={selectedResume} onChange={(e) => setSelectedResume(e.target.value)}>
              <option value="">— Choose a resume —</option>
              {resumes.map((r) => (
                <option key={r.id} value={r.id}>{r.title} ({r.chunk_count} chunks)</option>
              ))}
            </select>
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Select Job Description</label>
            <select className="form-select" style={{ width: '100%' }} value={selectedJD} onChange={(e) => setSelectedJD(e.target.value)}>
              <option value="">— Choose a JD —</option>
              {jds.map((j) => (
                <option key={j.id} value={j.id}>{j.title}{j.company ? ` @ ${j.company}` : ''}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="btn-group" style={{ marginTop: 16 }}>
          <button className="btn btn-primary" onClick={handleMatch} disabled={matching || !selectedResume || !selectedJD}>
            <Target size={16} /> {matching ? 'Analyzing...' : 'Run Match Score'}
          </button>
          <button className="btn btn-primary" onClick={handleGenerate} disabled={generating || !selectedResume || !selectedJD}>
            <Sparkles size={16} /> {generating ? 'Generating...' : 'Generate Content'}
          </button>
        </div>
      </div>

      {/* Match Result */}
      {matchResult && (
        <div className="card" style={{ marginBottom: 20 }}>
          <div className="card-header">
            <h3><Target size={18} style={{ marginRight: 8 }} />Match Score</h3>
            <span style={{ fontSize: '1.8rem', fontWeight: 800, color: scoreClass(matchResult.overall_score) === 'high' ? 'var(--success)' : scoreClass(matchResult.overall_score) === 'medium' ? 'var(--warning)' : 'var(--danger)' }}>
              {matchResult.overall_score}%
            </span>
          </div>

          <div className="score-bar" style={{ marginBottom: 20 }}>
            <div
              className={`score-bar-fill ${scoreClass(matchResult.overall_score)}`}
              style={{ width: `${matchResult.overall_score}%` }}
            />
          </div>

          <div className="grid-2">
            <div>
              <h4 style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: 8, textTransform: 'uppercase' }}>Matched Skills</h4>
              {matchResult.matched_skills.length > 0 ? (
                matchResult.matched_skills.map((s) => <span key={s} className="skill-tag">{s}</span>)
              ) : (
                <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>No skills matched</p>
              )}
            </div>
            <div>
              <h4 style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: 8, textTransform: 'uppercase' }}>Missing Skills</h4>
              {matchResult.missing_skills.length > 0 ? (
                matchResult.missing_skills.map((s) => <span key={s} className="skill-tag missing">{s}</span>)
              ) : (
                <p style={{ color: 'var(--success)', fontSize: '0.85rem' }}>All required skills covered! 🎉</p>
              )}
            </div>
          </div>

          {matchResult.suggested_bullets?.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <h4 style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: 8, textTransform: 'uppercase' }}>Suggested Resume Emphasis</h4>
              {matchResult.suggested_bullets.map((b, i) => (
                <div key={i} style={{ padding: '6px 10px', background: 'var(--bg-primary)', borderRadius: 4, marginBottom: 4, fontSize: '0.85rem' }}>
                  {b}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Generation Controls */}
      <div className="card" style={{ marginBottom: 20 }}>
        <div className="card-header">
          <h3><Sparkles size={18} style={{ marginRight: 8 }} />Generation Options</h3>
        </div>
        <div className="grid-3" style={{ gap: 16 }}>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Content Type</label>
            <select className="form-select" style={{ width: '100%' }} value={contentType} onChange={(e) => setContentType(e.target.value)}>
              <option value="cover_letter">Cover Letter</option>
              <option value="resume_summary">Resume Summary</option>
              <option value="resume_bullets">Resume Bullets</option>
            </select>
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Tone</label>
            <select className="form-select" style={{ width: '100%' }} value={tone} onChange={(e) => setTone(e.target.value)}>
              <option value="formal">Formal</option>
              <option value="casual">Casual</option>
            </select>
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Length</label>
            <select className="form-select" style={{ width: '100%' }} value={length} onChange={(e) => setLength(e.target.value)}>
              <option value="concise">Concise</option>
              <option value="detailed">Detailed</option>
            </select>
          </div>
        </div>
      </div>

      {/* Generated content */}
      {generated && (
        <div className="card">
          <div className="card-header">
            <h3><FileText size={18} style={{ marginRight: 8 }} />Generated {generated.content_type.replace('_', ' ')}</h3>
            <button className="btn btn-secondary btn-sm" onClick={handleCopy}>
              {copied ? <><Check size={14} /> Copied</> : <><Copy size={14} /> Copy</>}
            </button>
          </div>

          <div style={{
            padding: 20,
            background: 'var(--bg-primary)',
            borderRadius: 'var(--radius-sm)',
            fontSize: '0.9rem',
            lineHeight: 1.7,
            whiteSpace: 'pre-wrap',
            fontFamily: 'var(--font)',
          }}>
            {generated.content}
          </div>

          {/* Citations */}
          {generated.citations?.length > 0 && (
            <div className="citation-list" style={{ marginTop: 16 }}>
              <h4>Sources Used ({generated.citations.length})</h4>
              {generated.citations.map((c, i) => (
                <div key={i} className="citation-item">
                  <strong>[SOURCE: {c.source_number}]</strong> ({c.chunk_type}) — {c.chunk_text}...
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
