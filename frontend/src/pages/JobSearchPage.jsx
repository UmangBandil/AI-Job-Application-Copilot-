import { useState } from 'react';
import api from '../services/api';
import { Search, MapPin, ExternalLink, Download, CheckCircle } from 'lucide-react';

export default function JobSearchPage() {
  const [query, setQuery] = useState('');
  const [location, setLocation] = useState('');
  const [source, setSource] = useState('all');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [importedIds, setImportedIds] = useState(new Set());
  const [importingId, setImportingId] = useState(null);

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    try {
      const { data } = await api.post('/job-search', { query, location, source });
      setResults(data);
    } catch (err) {
      alert(err.response?.data?.detail || 'Search failed. Make sure API keys are configured.');
    } finally {
      setSearching(false);
    }
  };

  const handleImport = async (resultId) => {
    setImportingId(resultId);
    try {
      await api.post(`/job-search/${resultId}/import`);
      setImportedIds((prev) => new Set([...prev, resultId]));
    } catch (err) {
      alert(err.response?.data?.detail || 'Import failed');
    } finally {
      setImportingId(null);
    }
  };

  return (
    <div>
      <div className="page-header">
        <h2>Job Search</h2>
        <p>Search external job boards and import listings into your tracker</p>
      </div>

      {/* Search form */}
      <div className="card" style={{ marginBottom: 24 }}>
        <form onSubmit={handleSearch}>
          <div style={{ display: 'flex', gap: 12, alignItems: 'end' }}>
            <div className="form-group" style={{ marginBottom: 0, flex: 2 }}>
              <label>Job Title / Keywords</label>
              <input
                className="form-input"
                placeholder="e.g. Backend Engineer, Python, Machine Learning"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                autoFocus
              />
            </div>
            <div className="form-group" style={{ marginBottom: 0, flex: 1 }}>
              <label>Location</label>
              <input
                className="form-input"
                placeholder="e.g. Pune, Bangalore"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
              />
            </div>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label>Source</label>
              <select className="form-select" value={source} onChange={(e) => setSource(e.target.value)}>
                <option value="all">All Sources</option>
                <option value="adzuna">Adzuna</option>
                <option value="remoteok">RemoteOK</option>
              </select>
            </div>
            <button className="btn btn-primary" type="submit" disabled={searching} style={{ height: 42 }}>
              <Search size={16} /> {searching ? 'Searching...' : 'Search'}
            </button>
          </div>
        </form>
      </div>

      {/* Results */}
      {results.length > 0 && (
        <div>
          <h3 style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginBottom: 12 }}>
            {results.length} results found
          </h3>
          {results.map((r) => (
            <div key={r.id} className="card" style={{ marginBottom: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: '0.95rem' }}>{r.title}</div>
                  <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginTop: 2 }}>
                    {r.company && <span>{r.company}</span>}
                    {r.location && <span> · <MapPin size={12} style={{ verticalAlign: 'middle' }} /> {r.location}</span>}
                    <span> · <span style={{ textTransform: 'uppercase', fontSize: '0.7rem', fontWeight: 700 }}>{r.source}</span></span>
                  </div>
                  {r.description && (
                    <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginTop: 6, lineHeight: 1.4, maxHeight: 60, overflow: 'hidden' }}>
                      {r.description.replace(/<[^>]*>/g, '').slice(0, 200)}...
                    </p>
                  )}
                </div>
                <div style={{ display: 'flex', gap: 8, marginLeft: 16 }}>
                  {r.url && (
                    <a href={r.url} target="_blank" rel="noopener" className="btn btn-secondary btn-sm">
                      <ExternalLink size={14} /> View
                    </a>
                  )}
                  <button
                    className={`btn btn-sm ${importedIds.has(r.id) ? 'btn-success' : 'btn-primary'}`}
                    onClick={() => handleImport(r.id)}
                    disabled={importedIds.has(r.id) || importingId === r.id}
                  >
                    {importedIds.has(r.id) ? (
                      <><CheckCircle size={14} /> Imported</>
                    ) : importingId === r.id ? (
                      'Importing...'
                    ) : (
                      <><Download size={14} /> Import</>
                    )}
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {!searching && results.length === 0 && query && (
        <div className="empty-state">
          <Search size={48} />
          <h3>No results found</h3>
          <p>Try different keywords or check your API configuration</p>
        </div>
      )}

      {!query && results.length === 0 && (
        <div className="empty-state">
          <Search size={48} />
          <h3>Search for jobs</h3>
          <p>Enter keywords to search Adzuna and RemoteOK job boards</p>
        </div>
      )}
    </div>
  );
}
