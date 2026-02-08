import { useState, useRef, useEffect } from 'react';
import axios from 'axios';
import { Send, ArrowLeft, LifeBuoy, MessageSquare, AlertTriangle } from 'lucide-react';

function UserPortal({ onBack }) {
    const [input, setInput] = useState('');
    const [messages, setMessages] = useState([
        { role: 'ai', content: "Hi! I'm your IT Assistant. How can I help you today?" }
    ]);
    const [loading, setLoading] = useState(false);
    const [ticketCreated, setTicketCreated] = useState(null);
    const messagesEndRef = useRef(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(scrollToBottom, [messages]);

    const createTicket = async (currentMessages, summary = null) => {
        try {
            // Use the AI-generated summary if available, otherwise fallback to the last user message
            let queryText = summary;
            if (!queryText) {
                const lastUserMsg = [...currentMessages].reverse().find(m => m.role === 'user');
                queryText = lastUserMsg ? lastUserMsg.content : "Support Request";
            }

            const res = await axios.post('http://localhost:8000/tickets', {
                query: queryText,
                history: currentMessages,
                force_create: true
            });

            setTicketCreated(res.data.ticket_id);
            setMessages(prev => [...prev, { role: 'ai', content: `[System] Ticket ${res.data.ticket_id} has been created automatically based on our conversation. An agent will review it shortly.` }]);
        } catch (err) {
            console.error("Failed to create ticket automatically", err);
        }
    };

    const handleSend = async (e) => {
        e.preventDefault();
        if (!input.trim() || loading) return;

        const userMsg = input.trim();
        const newMessages = [...messages, { role: 'user', content: userMsg }];
        setMessages(newMessages);
        setInput('');
        setLoading(true);

        try {
            // 1. Send to Chat Analysis
            const res = await axios.post('http://localhost:8000/chat/analyze', {
                message: userMsg,
                history: newMessages.map(m => ({ role: m.role === 'ai' ? 'model' : 'user', content: m.content }))
            });

            const aiMsg = { role: 'ai', content: res.data.response };
            const updatedMessages = [...newMessages, aiMsg];
            setMessages(updatedMessages);

            // 2. Check for Escalation
            if (res.data.escalation_required) {
                await createTicket(updatedMessages, res.data.summary);
            }

        } catch (err) {
            setMessages(prev => [...prev, { role: 'ai', content: "I'm having trouble connecting. You can try asking again." }]);
        } finally {
            setLoading(false);
        }
    };

    const handleEscalate = async () => {
        setLoading(true);
        try {
            // Compile history into a single query block for the ticket
            const fullHistory = messages.map(m => `${m.role.toUpperCase()}: ${m.content}`).join('\n');

            const res = await axios.post('http://localhost:8000/tickets', {
                query: fullHistory,
                force_create: true
            });

            setTicketCreated(res.data.ticket_id);
            setMessages(prev => [...prev, { role: 'ai', content: `Checking... Ticket ${res.data.ticket_id} has been created. An agent will contact you shortly.` }]);
        } catch (err) {
            alert("Failed to create ticket.");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="layout">
            <header>
                <div className="brand">
                    <div className="logo"><LifeBuoy size={20} color="white" /></div>
                    <span>LoopBack Help Desk</span>
                </div>
                <button onClick={onBack} className="refresh-btn">
                    <ArrowLeft size={18} /> Switch to Admin View
                </button>
            </header>

            <div className="user-portal glass" style={{ maxWidth: '800px', margin: '20px auto', padding: '0', display: 'flex', flexDirection: 'column', height: '80vh', overflow: 'hidden' }}>

                {/* Chat Area */}
                <div className="chat-window" style={{ flex: 1, overflowY: 'auto', padding: '20px', display: 'flex', flexDirection: 'column', gap: '15px' }}>
                    {messages.map((msg, idx) => (
                        <div key={idx} style={{
                            alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                            maxWidth: '80%',
                            background: msg.role === 'user' ? '#646cff' : 'rgba(255,255,255,0.1)',
                            color: 'white',
                            padding: '12px 18px',
                            borderRadius: '12px',
                            borderBottomRightRadius: msg.role === 'user' ? '2px' : '12px',
                            borderBottomLeftRadius: msg.role === 'ai' ? '2px' : '12px',
                            lineHeight: '1.5'
                        }}>
                            {msg.content}
                        </div>
                    ))}
                    {loading && (
                        <div style={{ alignSelf: 'flex-start', color: '#aaa', fontStyle: 'italic', paddingLeft: '10px' }}>
                            Typing...
                        </div>
                    )}
                    <div ref={messagesEndRef} />
                </div>

                {/* Action Bar */}
                <div className="action-bar" style={{ padding: '20px', background: 'rgba(0,0,0,0.2)', borderTop: '1px solid rgba(255,255,255,0.1)' }}>
                    {ticketCreated && (
                        <div style={{ textAlign: 'center', color: '#2ecc71', marginBottom: '10px', fontSize: '0.9em' }}>
                            ✅ Ticket Active. Continuing conversation will be added to the ticket.
                        </div>
                    )}
                    <form onSubmit={handleSend} style={{ display: 'flex', gap: '10px', marginBottom: '10px' }}>
                        <input
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            placeholder={ticketCreated ? "Add more details..." : "Type your message..."}
                            disabled={loading}
                            style={{
                                flex: 1, padding: '12px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)',
                                background: 'rgba(0,0,0,0.3)', color: 'white'
                            }}
                        />
                        <button type="submit" disabled={!input.trim() || loading} style={{
                            background: '#646cff', color: 'white', border: 'none', padding: '0 20px', borderRadius: '8px', cursor: 'pointer'
                        }}>
                            <Send size={18} />
                        </button>
                    </form>
                </div>

            </div>
        </div>
    );
}

export default UserPortal;
