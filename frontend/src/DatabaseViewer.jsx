import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { motion } from 'framer-motion';
import { Database, FileJson, Table, RefreshCw, X } from 'lucide-react';
import './App.css'; // Reuse existing styles/vars

const API_URL = 'http://localhost:8000';

function DatabaseViewer({ onClose }) {
    const [data, setData] = useState([]);
    const [viewMode, setViewMode] = useState('table'); // 'table' or 'json'
    const [lastUpdated, setLastUpdated] = useState(new Date());

    const fetchData = async () => {
        try {
            const response = await axios.get(`${API_URL}/knowledge-base`);
            setData(response.data);
            setLastUpdated(new Date());
        } catch (error) {
            console.error("DB Fetch error:", error);
        }
    };

    useEffect(() => {
        fetchData();
        // No polling needed for static CSV, but kept for "live feel" or if file updates
        const interval = setInterval(fetchData, 5000);
        return () => clearInterval(interval);
    }, []);

    return (
        <motion.div
            className="database-overlay"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
        >
            <div className="database-modal glass">
                <header className="db-header">
                    <div className="db-title">
                        <Database size={24} className="icon-pulse" />
                        <h2>Knowledge Base Database</h2>
                        <span className="live-badge" style={{ background: 'rgba(16, 185, 129, 0.1)', color: '#10b981', borderColor: 'rgba(16, 185, 129, 0.2)' }}>● STATIC DB</span>
                    </div>

                    <div className="db-controls">
                        <div className="view-toggles">
                            <button
                                className={`toggle-btn ${viewMode === 'table' ? 'active' : ''}`}
                                onClick={() => setViewMode('table')}
                            >
                                <Table size={16} /> Table
                            </button>
                            <button
                                className={`toggle-btn ${viewMode === 'json' ? 'active' : ''}`}
                                onClick={() => setViewMode('json')}
                            >
                                <FileJson size={16} /> JSON
                            </button>
                        </div>

                        <span className="last-updated">
                            Loaded: {data.length} records
                        </span>

                        <button className="close-btn" onClick={onClose}>
                            <X size={20} />
                        </button>
                    </div>
                </header>

                <div className="db-content">
                    {viewMode === 'table' ? (
                        <div className="db-table-wrapper">
                            <table className="db-table">
                                <thead>
                                    <tr>
                                        <th>Category</th>
                                        <th>Issue</th>
                                        <th>Question</th>
                                        <th>Resolution</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {data.map((row, i) => (
                                        <tr key={i}>
                                            <td>
                                                <span className="cat-tag">{row.Category}</span>
                                            </td>
                                            <td className="font-mono" style={{ color: '#fff' }}>{row.Issue}</td>
                                            <td className="query-cell">{row.Question}</td>
                                            <td style={{ color: '#9ca3af', fontSize: '0.9em' }}>{row.Resolution}</td>
                                        </tr>
                                    ))}
                                    {data.length === 0 && (
                                        <tr>
                                            <td colSpan="6" className="empty-row">Database is empty waiting for tickets...</td>
                                        </tr>
                                    )}
                                </tbody>
                            </table>
                        </div>
                    ) : (
                        <div className="db-json-view">
                            <pre>{JSON.stringify(data, null, 2)}</pre>
                        </div>
                    )}
                </div>
            </div>
        </motion.div>
    );
}

export default DatabaseViewer;
