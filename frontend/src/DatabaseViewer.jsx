import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { motion, AnimatePresence } from 'framer-motion';
import { Database, FileJson, Table, RefreshCw, X, Plus, Edit2, Trash2, Save } from 'lucide-react';
import './App.css'; // Reuse existing styles/vars

const API_URL = 'http://localhost:8000';

function DatabaseViewer({ onClose }) {
    const [data, setData] = useState([]);
    const [viewMode, setViewMode] = useState('table'); // 'table' or 'json'
    const [lastUpdated, setLastUpdated] = useState(new Date());

    // CRUD State
    const [showModal, setShowModal] = useState(false);
    const [editingEntry, setEditingEntry] = useState(null);
    const [formData, setFormData] = useState({
        Category: '',
        Question: '',
        Resolution: ''
    });

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
        const interval = setInterval(fetchData, 5000);
        return () => clearInterval(interval);
    }, []);

    const resetForm = () => {
        setFormData({ Category: '', Question: '', Resolution: '' });
        setEditingEntry(null);
        setShowModal(false);
    };

    const handleEdit = (entry) => {
        setEditingEntry(entry);
        setFormData({
            Category: entry.Category,
            Question: entry.Question,
            Resolution: entry.Resolution
        });
        setShowModal(true);
    };

    const handleDelete = async (id) => {
        if (!window.confirm("Are you sure you want to delete this entry?")) return;
        try {
            await axios.delete(`${API_URL}/knowledge-base/${id}`);
            fetchData();
        } catch (error) {
            alert("Failed to delete entry: " + error.message);
        }
    };

    const handleSave = async (e) => {
        e.preventDefault();
        try {
            const payload = {
                category: formData.Category,
                question: formData.Question,
                resolution: formData.Resolution,
                issue: "" // Deprecated
            };

            if (editingEntry) {
                await axios.put(`${API_URL}/knowledge-base/${editingEntry.ID}`, payload);
            } else {
                await axios.post(`${API_URL}/knowledge-base`, payload);
            }
            fetchData();
            resetForm();
        } catch (error) {
            alert("Failed to save: " + error.message);
        }
    };

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
                        <h2>Knowledge Base</h2>
                        <span className="live-badge" style={{ background: 'rgba(16, 185, 129, 0.1)', color: '#10b981' }}>● LIVE</span>
                    </div>

                    <div className="db-controls">
                        <button className="create-btn" onClick={() => setShowModal(true)} style={{ background: '#10b981', color: 'white', border: 'none', padding: '8px 12px', borderRadius: '6px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <Plus size={16} /> Add Entry
                        </button>

                        <div className="view-toggles">
                            <button
                                className={`toggle-btn ${viewMode === 'table' ? 'active' : ''}`}
                                onClick={() => setViewMode('table')}
                            >
                                <Table size={16} />
                            </button>
                            <button
                                className={`toggle-btn ${viewMode === 'json' ? 'active' : ''}`}
                                onClick={() => setViewMode('json')}
                            >
                                <FileJson size={16} />
                            </button>
                        </div>

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
                                        <th>Question</th>
                                        <th>Resolution</th>
                                        <th style={{ width: '80px' }}>Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {data.map((row, i) => (
                                        <tr key={i}>
                                            <td>
                                                <span className="cat-tag">{row.Category}</span>
                                            </td>
                                            <td className="query-cell">{row.Question}</td>
                                            <td style={{ color: '#9ca3af', fontSize: '0.9em' }}>{row.Resolution}</td>
                                            <td>
                                                <div style={{ display: 'flex', gap: '8px' }}>
                                                    <button onClick={() => handleEdit(row)} style={{ background: 'none', border: 'none', color: '#60a5fa', cursor: 'pointer' }}>
                                                        <Edit2 size={16} />
                                                    </button>
                                                    <button onClick={() => handleDelete(row.ID)} style={{ background: 'none', border: 'none', color: '#ef4444', cursor: 'pointer' }}>
                                                        <Trash2 size={16} />
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    ) : (
                        <div className="db-json-view">
                            <pre>{JSON.stringify(data, null, 2)}</pre>
                        </div>
                    )}
                </div>

                {/* Edit/Create Modal */}
                <AnimatePresence>
                    {showModal && (
                        <motion.div
                            className="modal-overlay"
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            exit={{ opacity: 0 }}
                            style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 100 }}
                        >
                            <motion.div
                                className="modal-content glass"
                                initial={{ scale: 0.9, opacity: 0 }}
                                animate={{ scale: 1, opacity: 1 }}
                                exit={{ scale: 0.9, opacity: 0 }}
                                style={{ width: '500px', padding: '24px', background: '#1e293b', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.1)' }}
                            >
                                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '20px' }}>
                                    <h3 style={{ margin: 0, color: 'white' }}>{editingEntry ? 'Edit Entry' : 'New Entry'}</h3>
                                    <button onClick={resetForm} style={{ background: 'none', border: 'none', color: '#9ca3af', cursor: 'pointer' }}><X size={20} /></button>
                                </div>

                                <form onSubmit={handleSave}>
                                    <div style={{ marginBottom: '16px' }}>
                                        <label style={{ display: 'block', color: '#9ca3af', marginBottom: '8px', fontSize: '0.9rem' }}>Category</label>
                                        <input
                                            value={formData.Category}
                                            onChange={e => setFormData({ ...formData, Category: e.target.value })}
                                            style={{ width: '100%', padding: '10px', background: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '6px', color: 'white' }}
                                            required
                                        />
                                    </div>

                                    <div style={{ marginBottom: '16px' }}>
                                        <label style={{ display: 'block', color: '#9ca3af', marginBottom: '8px', fontSize: '0.9rem' }}>Question (User Query)</label>
                                        <input
                                            value={formData.Question}
                                            onChange={e => setFormData({ ...formData, Question: e.target.value })}
                                            style={{ width: '100%', padding: '10px', background: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '6px', color: 'white' }}
                                            required
                                        />
                                    </div>
                                    <div style={{ marginBottom: '24px' }}>
                                        <label style={{ display: 'block', color: '#9ca3af', marginBottom: '8px', fontSize: '0.9rem' }}>Resolution (Admin Response)</label>
                                        <textarea
                                            value={formData.Resolution}
                                            onChange={e => setFormData({ ...formData, Resolution: e.target.value })}
                                            style={{ width: '100%', padding: '10px', background: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '6px', color: 'white', minHeight: '100px', resize: 'vertical' }}
                                            required
                                        />
                                    </div>

                                    <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
                                        <button type="button" onClick={resetForm} style={{ padding: '10px 16px', borderRadius: '8px', background: 'rgba(255,255,255,0.1)', color: 'white', border: 'none', cursor: 'pointer' }}>Cancel</button>
                                        <button type="submit" style={{ padding: '10px 16px', borderRadius: '8px', background: '#3b82f6', color: 'white', border: 'none', cursor: 'pointer', display: 'flex', gap: '8px', alignItems: 'center' }}>
                                            <Save size={16} /> Save
                                        </button>
                                    </div>
                                </form>
                            </motion.div>
                        </motion.div>
                    )}
                </AnimatePresence>
            </div>
        </motion.div>
    );
}

export default DatabaseViewer;
