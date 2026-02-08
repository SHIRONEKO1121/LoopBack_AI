import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { motion, AnimatePresence } from 'framer-motion';
import { ShieldCheck, Send, Trash2, Zap, Search, Bell, HelpCircle, User } from 'lucide-react';
import './App.css';
import DatabaseViewer from './DatabaseViewer';
import UserPortal from './UserPortal';

const API_URL = 'http://localhost:8000';

function App() {
  const [tickets, setTickets] = useState([]);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [categoryFilter, setCategoryFilter] = useState('All');
  const [subcategoryFilter, setSubcategoryFilter] = useState('All');
  const [showBroadcastAll, setShowBroadcastAll] = useState(false);
  const [broadcastAllText, setBroadcastAllText] = useState('');
  const [showDatabase, setShowDatabase] = useState(false);

  // View Toggle State
  const [viewMode, setViewMode] = useState('admin'); // 'admin' or 'user'

  // Custom UI State
  const [notification, setNotification] = useState(null);
  const [confirmPopup, setConfirmPopup] = useState(null);

  // Selection & Integrated Confirm State
  const [selectedTicketIds, setSelectedTicketIds] = useState([]);
  const [isConfirmingBroadcastAll, setIsConfirmingBroadcastAll] = useState(false);

  // Ask User state
  const [showAskModal, setShowAskModal] = useState(null); // ticket object
  const [askQuestionText, setAskQuestionText] = useState('');

  const showNotification = (message, type = 'success') => {
    setNotification({ message, type });
    setTimeout(() => setNotification(null), 4000);
  };

  // Dynamic Categories detection
  const getCategoryIcon = (category) => {
    const iconMap = {
      'Network': '🌐',
      'Hardware': '🛠️',
      'Software': '💻',
      'Account': '👤',
      'Facility': '🏢',
      'Password': '🔑',
      'VPN': '🔒',
      'Wi-Fi': '📡',
      'Printer': '🖨️',
      'Access': '🔓',
      'Email': '📧',
      'Laptop': '💻',
      'Desktop': '🖥️',
      'Monitor': '🖥️',
      'Keyboard': '⌨️',
      'Mouse': '🖱️',
      'License': '📜',
      'Permission': '🛡️',
      'Slack': '💬',
      'Zoom': '📹',
      'Azure': '☁️',
      'AWS': '☁️',
      'HR': '👥',
      'Finance': '💰',
      'Security': '🛡️',
      'Meeting': '🤝',
      'Audio': '🔊',
      'Video': '🎬'
    };
    for (const [key, icon] of Object.entries(iconMap)) {
      if (category.toLowerCase().includes(key.toLowerCase())) return icon;
    }
    return '📋';
  };

  const escalatedTickets = tickets.filter(t => {
    if (t.status !== "Pending" && t.status !== "Awaiting Info") return false;
    if (categoryFilter !== 'All' && t.category !== categoryFilter) return false;
    if (subcategoryFilter !== 'All' && t.subcategory !== subcategoryFilter) return false;
    return true;
  });

  // Dynamic Subcategories for the current category
  const activeSubcategories = ['All', ...new Set(
    tickets
      .filter(t => t.category === categoryFilter && (t.status === "Pending" || t.status === "Awaiting Info"))
      .map(t => t.subcategory)
      .filter(Boolean)
  )];

  const categories = [
    { name: 'All', icon: '📋' },
    { name: 'Network', icon: '🌐' },
    { name: 'Hardware', icon: '🛠️' },
    { name: 'Software', icon: '💻' },
    { name: 'Account', icon: '👤' },
    { name: 'Facility', icon: '🏢' },
    { name: 'Others', icon: '📦' }
  ];

  useEffect(() => {
    if (viewMode === 'admin') {
      fetchTickets();
      const interval = setInterval(fetchTickets, 5000);
      return () => clearInterval(interval);
    }
  }, [viewMode]);

  const fetchTickets = async () => {
    try {
      const response = await axios.get(`${API_URL}/tickets`);
      setTickets(response.data);
    } catch (error) {
      console.error("Fetch error:", error);
    }
  };

  const approveResolution = async (ticketId) => {
    const finalAnswer = document.getElementById(`draft-${ticketId}`)?.value;
    if (!finalAnswer) {
      showNotification("Please enter a solution", "error");
      return;
    }

    setConfirmPopup({
      title: "Confirm Broadcast",
      message: "Are you sure you want to broadcast this solution? This will resolve the ticket and update the knowledge base.",
      icon: "📢",
      onConfirm: async () => {
        try {
          await axios.post(`${API_URL}/broadcast`, { ticket_id: ticketId, final_answer: finalAnswer });
          showNotification("Solution broadcasted successfully!");
          fetchTickets();
          setConfirmPopup(null);
        } catch (err) {
          showNotification("Broadcast failed", "error");
        }
      }
    });
  };

  const handleDeleteClick = (ticketId, ticketQuery, e) => {
    if (e) {
      e.stopPropagation();
      e.preventDefault();
    }
    setConfirmDelete({ ticketId, ticketQuery });
  };

  const deleteTicket = async () => {
    if (!confirmDelete) return;

    try {
      await axios.delete(`${API_URL}/tickets/${confirmDelete.ticketId}`);
      await fetchTickets();
      showNotification("Ticket deleted successfully");
      setConfirmDelete(null);
    } catch (err) {
      console.error('Delete error:', err);
      showNotification("Delete failed!", "error");
    }
  };

  const openBroadcastModal = () => {
    if (selectedTicketIds.length === 0) {
      const allIds = escalatedTickets.map(t => t.id);
      setSelectedTicketIds(allIds);
    }
    setBroadcastAllText('');
    setIsConfirmingBroadcastAll(false);
    setShowBroadcastAll(true);
  };

  const toggleTicketSelection = (id) => {
    setSelectedTicketIds(prev =>
      prev.includes(id) ? prev.filter(tid => tid !== id) : [...prev, id]
    );
  };

  const handleBroadcastAll = async () => {
    if (selectedTicketIds.length === 0) {
      showNotification('Please select at least one ticket', 'error');
      return;
    }
    if (!broadcastAllText.trim()) {
      showNotification('Please enter a solution', 'error');
      return;
    }

    if (!isConfirmingBroadcastAll) {
      setIsConfirmingBroadcastAll(true);
      return;
    }

    try {
      const payload = {
        final_answer: broadcastAllText,
        ticket_ids: selectedTicketIds
      };

      const response = await axios.post(`${API_URL}/broadcast_all`, payload);
      showNotification(`Successfully resolved ${response.data.tickets_resolved} ticket(s)!`);
      setShowBroadcastAll(false);
      setBroadcastAllText('');
      setIsConfirmingBroadcastAll(false);
      setSelectedTicketIds([]); // Clear selection after success
      fetchTickets();
    } catch (err) {
      console.error('Broadcast all error:', err);
      showNotification('Failed to broadcast solution', 'error');
    }
  };

  const handleAskUser = async () => {
    if (!askQuestionText.trim()) return;
    try {
      await axios.post(`${API_URL}/tickets/${showAskModal.id}/ask`, { question: askQuestionText });
      showNotification("Question sent to user");
      setShowAskModal(null);
      setAskQuestionText('');
      fetchTickets();
    } catch (err) {
      showNotification("Failed to send question", "error");
    }
  };

  if (viewMode === 'user') {
    return <UserPortal onBack={() => setViewMode('admin')} />;
  }

  return (
    <div className="layout">
      <main className="main-content">
        <header>
          <div className="search-bar glass">
            <Search size={18} />
            <input type="text" placeholder="Search knowledge base..." />
          </div>
          <div className="header-actions">
            <button
              className="refresh-btn"
              onClick={() => setViewMode('user')}
              title="Switch to User Portal"
            >
              <User size={18} /> User View
            </button>
            <Bell size={20} />
            <div className="avatar"></div>
          </div>
        </header>

        <section className="dashboard-view">
          <div className="admin-grid">
            <div className="admin-header">
              <h1>Human-in-the-Loop <span className="badge-queue">Queue</span></h1>
              <button className="refresh-btn" onClick={() => setShowDatabase(true)}>
                <span>🗄️</span> Database
              </button>
              <button className="refresh-btn" onClick={fetchTickets}>
                <span>🔄</span> Refresh
              </button>
            </div>

            {/* Category Filter Tabs */}
            <div className="category-filters glass">
              {categories.map(cat => {
                const count = tickets.filter(t =>
                  (t.status === 'Pending' || t.status === 'Awaiting Info') &&
                  (cat.name === 'All' || t.category === cat.name)
                ).length;

                return (
                  <button
                    key={cat.name}
                    className={`category-tab ${categoryFilter === cat.name ? 'active' : ''}`}
                    onClick={() => {
                      setCategoryFilter(cat.name);
                      setSubcategoryFilter('All');
                      setSelectedTicketIds([]); // Clear selection when switching categories
                    }}
                  >
                    <span className="tab-icon">{cat.icon}</span>
                    <span className="tab-name">{cat.name}</span>
                    {count > 0 && <span className="tab-count">{count}</span>}
                  </button>
                );
              })}
            </div>

            {/* Subcategory Pills (Subfolders) */}
            {categoryFilter !== 'All' && activeSubcategories.length > 1 && (
              <div className="subcategory-pills-row">
                {activeSubcategories.map(sub => {
                  const subCount = tickets.filter(t =>
                    (t.status === 'Pending' || t.status === 'Awaiting Info') &&
                    t.category === categoryFilter &&
                    (sub === 'All' || t.subcategory === sub)
                  ).length;

                  return (
                    <button
                      key={sub}
                      className={`sub-pill ${subcategoryFilter === sub ? 'active' : ''}`}
                      onClick={() => {
                        setSubcategoryFilter(sub);
                        setSelectedTicketIds([]); // Clear selection when switching subcategories
                      }}
                    >
                      {sub} <span className="sub-count">{subCount}</span>
                    </button>
                  );
                })}
              </div>
            )}

            {/* Batch Broadcast Button */}
            {escalatedTickets.length > 0 && (
              <div className="batch-actions">
                <div className="selection-controls">
                  <button
                    className="select-all-btn glass"
                    onClick={() => {
                      if (selectedTicketIds.length === escalatedTickets.length) {
                        setSelectedTicketIds([]);
                      } else {
                        setSelectedTicketIds(escalatedTickets.map(t => t.id));
                      }
                    }}
                  >
                    {selectedTicketIds.length === escalatedTickets.length ? 'Deselect All' : 'Select All'}
                  </button>
                </div>
                <button
                  className="broadcast-all-btn glass"
                  onClick={openBroadcastModal}
                >
                  💬 Broadcast {selectedTicketIds.length > 0 ? `Selected (${selectedTicketIds.length})` : `to All ${categoryFilter !== 'All' ? categoryFilter : 'Pending'} (${escalatedTickets.length})`}
                </button>
              </div>
            )}

            {/* Tickets Grid */}
            <div className="escalated-grid">
              {escalatedTickets.length === 0 ? (
                <div className="empty-state glass">
                  <h3>✅ All Clear!</h3>
                  <p>No pending tickets {categoryFilter !== 'All' ? `in ${categoryFilter}` : ''}</p>
                </div>
              ) : (
                escalatedTickets.map((ticket) => {
                  const groupedTickets = tickets.filter(t =>
                    t.group_id === ticket.group_id && t.status === "Pending"
                  );
                  const isGrouped = groupedTickets.length > 1;
                  const otherCount = groupedTickets.length - 1;

                  const categoryStyles = {
                    Network: { bg: '#3B82F6', icon: '🌐' },
                    Hardware: { bg: '#F97316', icon: '🛠️' },
                    Software: { bg: '#8B5CF6', icon: '💻' },
                    Account: { bg: '#10B981', icon: '👤' },
                    Facility: { bg: '#6B7280', icon: '🏢' },
                    Security: { bg: '#EF4444', icon: '🛡️' }
                  };
                  const catStyle = categoryStyles[ticket.category] || { bg: '#6B7280', icon: '📋' };

                  return (
                    <motion.div
                      key={ticket.id}
                      className={`ticket-card glass ${selectedTicketIds.includes(ticket.id) ? 'selected' : ''}`}
                      initial={{ opacity: 0, y: 20 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, scale: 0.9 }}
                    >
                      <div
                        className="ticket-selection-indicator"
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleTicketSelection(ticket.id);
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={selectedTicketIds.includes(ticket.id)}
                          onChange={() => { }} // Click handled by parent div for larger hit area
                        />
                      </div>
                      <div className="ticket-header">
                        <div className="ticket-title-row">
                          {ticket.category && (
                            <span
                              className="category-badge"
                              style={{
                                backgroundColor: `${catStyle.bg}20`,
                                border: `1px solid ${catStyle.bg}`,
                                color: catStyle.bg
                              }}
                            >
                              {catStyle.icon} {ticket.category}
                            </span>
                          )}
                          {ticket.subcategory && (
                            <span className="subcategory-tag">
                              #{ticket.subcategory}
                            </span>
                          )}

                          <span className="ticket-id">{ticket.id}</span>
                        </div>
                        {/* NEW: Ticket Title */}
                        <h3 className="ticket-subject" style={{ margin: '8px 0', fontSize: '1.2rem' }}>
                          {ticket.title || "Support Request"}
                        </h3>
                        {/* Extracted Dialogue (Query) */}
                        <div className="ticket-query-box" style={{ background: 'rgba(255,255,255,0.05)', padding: '10px', borderRadius: '8px', marginBottom: '10px' }}>
                          <label style={{ fontSize: '0.75rem', color: '#888', textTransform: 'uppercase' }}>SUMMARY:</label>
                          <p className="ticket-query" style={{ fontStyle: 'italic', color: '#ddd' }}>{ticket.query}</p>
                        </div>
                      </div>
                      <div className="ticket-body">
                        {ticket.admin_draft && ticket.ai_draft && (
                          <div className="technical-context glass">
                            <label>⚙️ AI Technical Summary:</label>
                            <p>{ticket.ai_draft}</p>
                          </div>
                        )}
                        <div className="status-row">
                          <label>AI-Suggested Response (Draft):</label>
                          {ticket.status === 'Awaiting Info' && (
                            <span className="status-badge-awaiting">Awaiting Info</span>
                          )}
                        </div>
                        <textarea
                          id={`draft-${ticket.id}`}
                          defaultValue={ticket.admin_draft || ticket.ai_draft}
                          placeholder="Draft your response here..."
                        />

                        {ticket.history && ticket.history.length > 0 && (
                          <div className="ticket-history">
                            {ticket.history.map((h, i) => (
                              <div key={i} className="history-item">
                                <span className={`history-role ${h.role}`}>{h.role}</span>
                                <div className="history-msg">{h.message}</div>
                                <span className="history-time">{h.time}</span>
                              </div>
                            ))}
                          </div>
                        )}

                        <div className="ticket-actions">
                          <button
                            onClick={() => approveResolution(ticket.id)}
                            className="btn-approve"
                          >
                            <Send size={16} /> Broadcast Reply
                          </button>
                          <button
                            onClick={() => {
                              setShowAskModal(ticket);
                              // Suggest a question based on draft if empty or generic
                              setAskQuestionText("Could you please provide more details about this issue?");
                            }}
                            className="btn-ask"
                            title="Ask user for clarification"
                          >
                            <HelpCircle size={18} /> Ask User
                          </button>
                          <button
                            onClick={(e) => handleDeleteClick(ticket.id, ticket.query, e)}
                            className="btn-reject"
                          >
                            <Trash2 size={16} /> Reject
                          </button>
                        </div>
                      </div>
                    </motion.div>
                  );
                })
              )}
            </div>
          </div>
        </section>
      </main>

      {/* Notifications */}
      <AnimatePresence mode="wait">
        {notification && (
          <motion.div
            key="notification"
            className={`notification-toast ${notification.type}`}
            initial={{ opacity: 0, y: 50, x: 20 }}
            animate={{ opacity: 1, y: 0, x: 0 }}
            exit={{ opacity: 0, scale: 0.95 }}
          >
            <span className="notification-icon">
              {notification.type === 'success' ? '✅' : '❌'}
            </span>
            <span>{notification.message}</span>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Confirmation Modal */}
      <AnimatePresence>
        {confirmPopup && (
          <div className="modal-overlay" key="confirm-modal" onClick={() => setConfirmPopup(null)}>
            <motion.div
              className="modal-content confirm-modal glass"
              onClick={(e) => e.stopPropagation()}
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
            >
              <span className="confirm-modal-icon">{confirmPopup.icon}</span>
              <h3>{confirmPopup.title}</h3>
              <p>{confirmPopup.message}</p>
              <div className="modal-actions">
                <button onClick={confirmPopup.onConfirm} className="btn-confirm">Confirm</button>
                <button onClick={() => setConfirmPopup(null)} className="btn-cancel">Cancel</button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Delete Confirmation Modal */}
      <AnimatePresence>
        {confirmDelete && (
          <div className="modal-overlay" key="delete-modal" onClick={() => setConfirmDelete(null)}>
            <motion.div
              className="modal-content glass"
              onClick={(e) => e.stopPropagation()}
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
            >
              <h3>⚠️ Confirm Deletion</h3>
              <p>Are you sure you want to delete this ticket?</p>
              <p className="ticket-preview">{confirmDelete.ticketQuery}</p>
              <div className="modal-actions">
                <button onClick={deleteTicket} className="btn-danger">Delete</button>
                <button onClick={() => setConfirmDelete(null)} className="btn-cancel">Cancel</button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Broadcast All Modal */}
      <AnimatePresence>
        {showBroadcastAll && (
          <div className="modal-overlay" key="broadcast-modal" onClick={() => setShowBroadcastAll(false)}>
            <motion.div
              className="modal-content glass"
              style={{ position: 'relative', overflow: 'hidden' }}
              onClick={(e) => e.stopPropagation()}
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
            >
              {/* Integrated Confirmation Overlay */}
              <AnimatePresence>
                {isConfirmingBroadcastAll && (
                  <motion.div
                    className="integrated-confirm-overlay"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                  >
                    <h3>📢 Confirm Broadcast</h3>
                    <p>You are about to broadcast this solution to <strong>{selectedTicketIds.length}</strong> selected tickets. This will resolve all of them and update the knowledge base.</p>
                    <div className="modal-actions">
                      <button onClick={handleBroadcastAll} className="btn-confirm">Yes, Broadcast Now</button>
                      <button onClick={() => setIsConfirmingBroadcastAll(false)} className="btn-cancel">Wait, Go Back</button>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              <h3>📢 Broadcast Solution</h3>

              <div className="warning-box">
                <span className="warning-icon">⚠️</span>
                <div>
                  <strong>Warning!</strong> You are about to resolve{' '}
                  <strong>{selectedTicketIds.length}</strong> selected pending ticket{selectedTicketIds.length !== 1 ? 's' : ''}.
                  This action cannot be undone.
                </div>
              </div>

              <div className="affected-tickets-preview">
                <h4>Select tickets to include: ({selectedTicketIds.length}/{escalatedTickets.length})</h4>
                <ul>
                  {escalatedTickets.map(t => (
                    <li key={t.id} className="ticket-select-item" onClick={() => toggleTicketSelection(t.id)}>
                      <input
                        type="checkbox"
                        className="ticket-checkbox"
                        checked={selectedTicketIds.includes(t.id)}
                        onChange={() => { }} // Controlled by li click
                      />
                      <span><strong>{t.id}:</strong> {t.query}</span>
                    </li>
                  ))}
                </ul>
              </div>

              <p className="modal-description">
                Please enter the solution that resolves the selected issues:
              </p>

              <textarea
                className="broadcast-textarea"
                value={broadcastAllText}
                onChange={(e) => setBroadcastAllText(e.target.value)}
                placeholder="Enter the solution that resolves all these issues..."
                rows={4}
              />

              <div className="modal-actions">
                <button
                  className="btn-primary"
                  onClick={handleBroadcastAll}
                  disabled={selectedTicketIds.length === 0 || !broadcastAllText.trim()}
                >
                  Broadcast Solution
                </button>
                <button
                  className="btn-secondary"
                  onClick={() => {
                    setShowBroadcastAll(false);
                    setBroadcastAllText('');
                  }}
                >
                  Cancel
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Ask User Modal */}
      <AnimatePresence>
        {showAskModal && (
          <div className="modal-overlay" onClick={() => setShowAskModal(null)}>
            <motion.div
              className="modal-content glass"
              onClick={(e) => e.stopPropagation()}
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
            >
              <h3>❓ Ask User for Clarification</h3>
              <p className="ticket-preview">{showAskModal.query}</p>

              <label className="modal-label">AI-Suggested Question:</label>
              <textarea
                className="broadcast-textarea"
                value={askQuestionText}
                onChange={(e) => setAskQuestionText(e.target.value)}
                placeholder="Type your question here..."
                rows={4}
              />

              <div className="modal-actions">
                <button onClick={handleAskUser} className="btn-primary" disabled={!askQuestionText.trim()}>
                  Send Question
                </button>
                <button onClick={() => setShowAskModal(null)} className="btn-cancel">Cancel</button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
      <AnimatePresence>
        {showDatabase && (
          <DatabaseViewer onClose={() => setShowDatabase(false)} />
        )}
      </AnimatePresence>
    </div>
  );
}

export default App;
