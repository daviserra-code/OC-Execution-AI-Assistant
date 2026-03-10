// Teyra AI Assistant - Main JavaScript File

// Global variables
let isLoading = false;
let currentMessageIndex = 0;
let availableModes = {};

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    // Initialize Mermaid
    mermaid.initialize({
        startOnLoad: false,
        theme: 'default',
        securityLevel: 'loose',
        flowchart: {
            htmlLabels: true,
            useMaxWidth: true
        }
    });

    // Load modes first, then initialize dependent components
    fetch('/get_modes')
        .then(response => response.json())
        .then(data => {
            availableModes = data.modes;

            // Initialize theme
            initializeThemeSelector();

            // Populate mode buttons
            populateModeButtons();

            // Initialize admin login
            initializeAdminLogin();

            // Load chat history
            loadChatHistory();

            // Load session info
            loadSessionInfo();
        })
        .catch(error => {
            console.error('Error loading modes:', error);
            // Fallback for critical failure? 
            // We could hardcode a backup or show an error.
            addMessage('assistant', '❌ Critical Error: Failed to load assistant modes.');
        });

    // Auto-resize textarea
    const messageInput = document.getElementById('messageInput');
    if (messageInput) {
        messageInput.addEventListener('input', function () {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 150) + 'px';
        });

        // Send on Enter
        messageInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
    }

    // Mode selector
    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.addEventListener('click', function () {
            document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            const mode = this.getAttribute('data-mode');
            const modeInfo = availableModes[mode];
            document.getElementById('currentModeDisplay').textContent = `${modeInfo.icon} ${modeInfo.name}`;
        });
    });

    // File upload
    const fileInput = document.getElementById('fileInput');
    if (fileInput) {
        fileInput.addEventListener('change', handleFileUpload);
    }

    // Initialize Mobile Sidebar
    initializeMobileSidebar();
});

/**
 * Populate mode selector buttons dynamically
 */
function populateModeButtons() {
    const modeButtonsContainer = document.getElementById('modeButtons');
    if (!modeButtonsContainer) return;

    // Clear existing buttons
    modeButtonsContainer.innerHTML = '';

    // Create a button for each mode
    Object.keys(availableModes).forEach((modeKey, index) => {
        const mode = availableModes[modeKey];
        const button = document.createElement('button');
        button.className = 'mode-btn ripple';
        button.setAttribute('data-mode', modeKey);
        button.textContent = `${mode.icon} ${mode.name}`;

        // Set first mode as active by default
        if (index === 0) {
            button.classList.add('active');
            // Update the current mode display if it exists
            const currentModeDisplay = document.getElementById('currentModeDisplay');
            if (currentModeDisplay) {
                currentModeDisplay.textContent = `${mode.icon} ${mode.name}`;
            }
        }

        // Add click event listener
        button.addEventListener('click', function () {
            // Remove active class from all buttons
            document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
            // Add active class to clicked button
            this.classList.add('active');

            // Update current mode display
            const selectedMode = this.getAttribute('data-mode');
            const modeInfo = availableModes[selectedMode];
            const currentModeDisplay = document.getElementById('currentModeDisplay');
            if (currentModeDisplay) {
                currentModeDisplay.textContent = `${modeInfo.icon} ${modeInfo.name}`;
            }
        });

        modeButtonsContainer.appendChild(button);
    });
}

function sendMessage(regenerate = false) {
    if (isLoading) return;

    const input = document.getElementById('messageInput');
    const message = input.value.trim();

    if (!message && !regenerate) return;

    if (!regenerate) {
        addMessage('user', message);
        input.value = '';
        input.style.height = 'auto';
    }

    showStreamingIndicator();

    if (regenerate) {
        regularChat(message, true);
    } else {
        streamingChat(message);
    }
}

function streamingChat(message) {
    isLoading = true;
    document.getElementById('sendBtn').disabled = true;

    const messageDiv = addMessage('assistant', '', true);
    const contentDiv = messageDiv.querySelector('.message-content');

    fetch('/chat_stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: message, language: currentLanguage })
    })
        .then(response => {
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let fullResponse = '';

            function readStream() {
                return reader.read().then(({ done, value }) => {
                    if (done) {
                        hideStreamingIndicator();
                        addMessageActions(messageDiv, fullResponse);
                        renderMermaidDiagrams();
                        if (fullResponse) {
                            saveChatToSession(message, fullResponse);
                        }
                        return;
                    }

                    const chunk = decoder.decode(value);
                    const lines = chunk.split('\n');

                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            try {
                                const data = JSON.parse(line.slice(6));
                                if (data.content) {
                                    fullResponse += data.content;
                                    contentDiv.innerHTML = formatMessage(fullResponse);
                                    scrollToBottom();
                                } else if (data.error) {
                                    contentDiv.innerHTML = `❌ Error: ${data.error}`;
                                    hideStreamingIndicator();
                                    return;
                                } else if (data.done) {
                                    hideStreamingIndicator();
                                    addMessageActions(messageDiv, fullResponse);
                                    setTimeout(() => renderMermaidDiagrams(), 500);
                                    if (fullResponse) {
                                        saveChatToSession(message, fullResponse);
                                    }
                                    return;
                                }
                            } catch (e) {
                                // Ignore parsing errors
                            }
                        }
                    }
                    return readStream();
                });
            }
            return readStream();
        })
        .catch(error => {
            hideStreamingIndicator();
            contentDiv.innerHTML = `❌ Network error: ${error.message}`;
        });
}

function regularChat(message, regenerate = false) {
    isLoading = true;
    document.getElementById('sendBtn').disabled = true;

    fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: message, regenerate: regenerate, language: currentLanguage })
    })
        .then(response => response.json())
        .then(data => {
            hideStreamingIndicator();
            if (data.error) {
                addMessage('assistant', `❌ Error: ${data.error}`);
            } else {
                const messageDiv = addMessage('assistant', data.response);
                addMessageActions(messageDiv, data.response);
                if (data.cached) {
                    addCachedIndicator(messageDiv);
                }
                renderMermaidDiagrams();
            }
        })
        .catch(error => {
            hideStreamingIndicator();
            addMessage('assistant', `❌ Network error: ${error.message}`);
        });
}

function addMessage(sender, content, isPlaceholder = false) {
    const chatMessages = document.getElementById('chatMessages');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${sender}`;
    currentMessageIndex++;
    messageDiv.setAttribute('data-message-id', currentMessageIndex);

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';

    if (!isPlaceholder) {
        contentDiv.innerHTML = formatMessage(content);
    }

    messageDiv.appendChild(contentDiv);
    chatMessages.appendChild(messageDiv);

    scrollToBottom();
    return messageDiv;
}

function addMessageActions(messageDiv, content) {
    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'message-actions';

    if (messageDiv.classList.contains('assistant')) {
        actionsDiv.innerHTML = `
            <button class="action-btn regenerate" onclick="regenerateResponse(${messageDiv.getAttribute('data-message-id')})">
                <i class="fas fa-redo"></i> Regenerate
            </button>
            <button class="action-btn copy" onclick="copyToClipboard('${btoa(encodeURIComponent(content))}')">
                <i class="fas fa-copy"></i> Copy
            </button>
        `;
    } else {
        actionsDiv.innerHTML = `
            <button class="action-btn copy" onclick="copyToClipboard('${btoa(encodeURIComponent(content))}')">
                <i class="fas fa-copy"></i> Copy
            </button>
        `;
    }

    messageDiv.appendChild(actionsDiv);
}

function addCachedIndicator(messageDiv) {
    const indicator = document.createElement('div');
    indicator.style.cssText = 'font-size: 10px; color: #28a745; margin-top: 5px; opacity: 0.8;';
    indicator.innerHTML = '<i class="fas fa-bolt"></i> Cached response';
    messageDiv.appendChild(indicator);
}

function regenerateResponse(messageId) {
    const messageDiv = document.querySelector(`[data-message-id="${messageId}"]`);
    if (messageDiv) {
        let nextSibling = messageDiv.nextElementSibling;
        while (nextSibling) {
            const toRemove = nextSibling;
            nextSibling = nextSibling.nextElementSibling;
            toRemove.remove();
        }
        messageDiv.remove();
        sendMessage(true);
    }
}

function copyToClipboard(encodedContent) {
    const content = decodeURIComponent(atob(encodedContent));
    navigator.clipboard.writeText(content).then(() => {
        const feedback = document.createElement('div');
        feedback.style.cssText = 'position: fixed; top: 20px; right: 20px; background: #28a745; color: white; padding: 10px; border-radius: 5px; z-index: 1000;';
        feedback.textContent = 'Copied to clipboard!';
        document.body.appendChild(feedback);
        setTimeout(() => feedback.remove(), 2000);
    });
}

function formatMessage(content) {
    let formatted = content
        .replace(/```mermaid\n([\s\S]*?)```/g, function (match, diagram) {
            const cleanDiagram = diagram.trim();
            const diagramId = 'mermaid-' + Math.random().toString(36).substr(2, 9);
            return `<div class="mermaid" id="${diagramId}">${cleanDiagram}</div>`;
        })
        .replace(/```(\w+)?\n([\s\S]*?)```/g, '<pre><code class="language-$1">$2</code></pre>')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/^\s*[-*+]\s+(.+)$/gm, '<li>$1</li>')
        .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
        .replace(/^\s*(\d+)\.\s+(.+)$/gm, '<li>$2</li>')
        .replace(/(<li>.*<\/li>)/s, '<ol>$1</ol>')
        .replace(/\n/g, '<br>');

    setTimeout(() => renderMermaidDiagrams(), 100);
    return formatted;
}

function renderMermaidDiagrams() {
    try {
        const mermaidElements = document.querySelectorAll('.mermaid:not([data-processed])');
        if (mermaidElements.length > 0) {
            mermaid.init(undefined, mermaidElements);
        }
    } catch (error) {
        console.warn('Mermaid rendering error:', error);
    }
}

function showStreamingIndicator() {
    document.getElementById('streamingIndicator').style.display = 'inline-block';
}

function hideStreamingIndicator() {
    isLoading = false;
    document.getElementById('streamingIndicator').style.display = 'none';
    document.getElementById('sendBtn').disabled = false;
}

function scrollToBottom() {
    const chatMessages = document.getElementById('chatMessages');
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function saveChatToSession(userMessage, assistantResponse) {
    const activeMode = document.querySelector('.mode-btn.active');
    const mode = activeMode ? activeMode.getAttribute('data-mode') : 'general';

    fetch('/save_chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            user_message: userMessage,
            assistant_response: assistantResponse,
            mode: mode
        })
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                loadSessionInfo();
            }
        })
        .catch(error => console.error('Error saving chat:', error));
}

function loadChatHistory() {
    fetch('/get_history')
        .then(response => response.json())
        .then(data => {
            const chatMessages = document.getElementById('chatMessages');
            if (data.history && data.history.length > 0) {
                chatMessages.innerHTML = '';
                data.history.forEach(exchange => {
                    const userMessageDiv = addMessage('user', exchange.user);
                    addMessageActions(userMessageDiv, exchange.user);

                    const assistantMessageDiv = addMessage('assistant', exchange.assistant);
                    addMessageActions(assistantMessageDiv, exchange.assistant);

                    if (exchange.timestamp) {
                        const timestampDiv = document.createElement('div');
                        timestampDiv.style.cssText = 'font-size: 10px; color: #666; margin-top: 5px; text-align: center;';
                        timestampDiv.textContent = new Date(exchange.timestamp).toLocaleString();
                        assistantMessageDiv.appendChild(timestampDiv);
                    }
                });

                setTimeout(() => renderMermaidDiagrams(), 500);
            }
            scrollToBottom();
        })
        .catch(error => console.error('Error loading history:', error));
}

function loadSessionInfo() {
    fetch('/session_info')
        .then(response => response.json())
        .then(data => {
            // Update UI with session info if needed
        })
        .catch(error => console.error('Error loading session info:', error));
}

function handleFileUpload(event) {
    const files = event.target.files;
    const preview = document.getElementById('filePreview');
    preview.innerHTML = '';

    Array.from(files).forEach(file => {
        const formData = new FormData();
        formData.append('file', file);

        fetch('/upload_file', {
            method: 'POST',
            body: formData
        })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    const fileItem = document.createElement('div');
                    fileItem.className = 'file-item';
                    fileItem.innerHTML = `
                    <div class="file-name">✅ ${data.original_name}</div>
                    <div class="file-content">${data.content}</div>
                `;
                    preview.appendChild(fileItem);
                    setTimeout(() => loadVectorDbStatus(), 1000);
                } else {
                    const errorItem = document.createElement('div');
                    errorItem.className = 'error';
                    errorItem.innerHTML = `<strong>❌ ${data.original_name}</strong><br>${data.error}`;
                    preview.appendChild(errorItem);
                }
            })
            .catch(error => {
                const errorItem = document.createElement('div');
                errorItem.className = 'error';
                errorItem.innerHTML = `<strong>❌ ${file.name}</strong><br>Upload failed: ${error.message}`;
                preview.appendChild(errorItem);
            });
    });
}

function loadTemplate(templateType) {
    fetch(`/templates/${templateType}`)
        .then(response => response.json())
        .then(data => {
            if (data.content) {
                document.getElementById('messageInput').value = `Please help me create a ${data.name}:\n\n${data.content}`;
                document.getElementById('messageInput').style.height = 'auto';
                document.getElementById('messageInput').style.height = Math.min(document.getElementById('messageInput').scrollHeight, 150) + 'px';
            }
        })
        .catch(error => addMessage('assistant', `❌ Error loading template: ${error.message}`));
}

function clearHistory() {
    if (confirm('Are you sure you want to clear the chat history?')) {
        fetch('/clear_history', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    const chatMessages = document.getElementById('chatMessages');
                    chatMessages.innerHTML = `
                    <div class="message assistant">
                        <div class="message-content">
                            <strong>🔄 Chat history cleared!</strong><br><br>
                            How can I help you today?
                        </div>
                    </div>
                `;
                    document.getElementById('filePreview').innerHTML = '';
                    loadSessionInfo();
                }
            })
            .catch(error => console.error('Error clearing history:', error));
    }
}

function showPrompt() {
    fetch('/get_prompt')
        .then(response => response.json())
        .then(data => {
            if (data.prompt) {
                addMessage('assistant', `**🤖 System Prompt (${data.mode_info.name} Mode):**\n\n${data.prompt}`);
            } else {
                addMessage('assistant', `❌ Error: ${data.error}`);
            }
        });
}

function showChatHistory() {
    fetch('/get_history')
        .then(response => response.json())
        .then(data => {
            if (data.history) {
                let historyText = `**📜 Chat History (${data.count} exchanges):**\n\n`;

                if (data.count === 0) {
                    historyText += "No chat history found.";
                } else {
                    data.history.forEach((exchange, index) => {
                        const timestamp = exchange.timestamp ? new Date(exchange.timestamp).toLocaleString() : 'Unknown time';
                        const mode = exchange.mode || 'general';
                        const modeInfo = availableModes[mode] || { name: 'General' };

                        historyText += `**Exchange ${index + 1}** (${timestamp} - ${modeInfo.name}):\n`;
                        historyText += `**User:** ${exchange.user.substring(0, 150)}${exchange.user.length > 150 ? '...' : ''}\n`;
                        historyText += `**Assistant:** ${exchange.assistant.substring(0, 200)}${exchange.assistant.length > 200 ? '...' : ''}\n\n`;
                    });
                }

                addMessage('assistant', historyText);
            } else {
                addMessage('assistant', `❌ Error: ${data.error}`);
            }
        });
}

function showSessionInfo() {
    fetch('/session_info')
        .then(response => response.json())
        .then(data => {
            addMessage('assistant', `**📊 Session Info:**\n\nSession ID: ${data.session_id}\nMessages: ${data.message_count}`);
        });
}

function showExportOptions() {
    document.getElementById('exportModal').style.display = 'block';
}

function exportConversation(format) {
    window.location.href = `/export_conversation?format=${format || 'json'}`;
    closeModal('exportModal');
}

function closeModal(modalId) {
    document.getElementById(modalId).style.display = 'none';
}

// Admin functions
// ========================================
// AUTH & ADMIN FUNCTIONS
// ========================================

let currentUser = null;

document.addEventListener('DOMContentLoaded', () => {
    checkAuth();

    // Login Form Handler
    const loginForm = document.getElementById('loginForm');
    if (loginForm) {
        loginForm.addEventListener('submit', handleLogin);
    }

    // Add User Form Handler
    const addUserForm = document.getElementById('addUserForm');
    if (addUserForm) {
        addUserForm.addEventListener('submit', handleAddUser);
    }

    // Edit User Form Handler
    const editUserForm = document.getElementById('editUserForm');
    if (editUserForm) {
        editUserForm.addEventListener('submit', handleEditUser);
    }
});

function checkAuth() {
    fetch('/check_auth')
        .then(res => res.json())
        .then(data => {
            if (data.authenticated) {
                currentUser = data.user;
                updateAuthUI();
            }
        })
        .catch(err => console.error('Auth check failed', err));
}

function updateAuthUI() {
    const adminControls = document.getElementById('adminControls');
    const adminLoginBtn = document.getElementById('adminLoginBtn');

    if (currentUser && currentUser.role === 'admin') {
        if (adminControls) adminControls.style.display = 'block';
        if (adminLoginBtn) adminLoginBtn.style.display = 'none';
    } else {
        if (adminControls) adminControls.style.display = 'none';
        if (adminLoginBtn) adminLoginBtn.style.display = 'block';
    }
}

function handleLogin(e) {
    e.preventDefault();
    const username = document.getElementById('loginUsername').value;
    const password = document.getElementById('loginPassword').value;

    fetch('/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
    })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                currentUser = data.user;
                closeModal('loginModal');
                addMessage('assistant', `🔓 Welcome back, **${currentUser.username}**!`);

                // If admin login was triggered by a specific action, retry it?
                // For now just let them proceed manually.
                updateAuthUI();
            } else {
                alert('Login failed: ' + data.error);
            }
        })
        .catch(err => alert('Login error: ' + err.message));
}

function logout() {
    fetch('/logout', { method: 'POST' })
        .then(() => {
            currentUser = null;
            updateAuthUI();
            addMessage('assistant', '👋 Logged out successfully.');
            // Close admin panel if open
            const adminPanel = document.getElementById('adminPanel');
            if (adminPanel) adminPanel.style.display = 'none';
        });
}

// Admin Panel Logic
function showAdminPanel() {
    console.log('showAdminPanel called');
    if (!currentUser || currentUser.role !== 'admin') {
        console.log('Access denied', currentUser);
        alert('Access Denied: Admin privileges required.');
        return;
    }
    const panel = document.getElementById('adminPanel');
    if (panel) {
        console.log('Showing panel');
        panel.style.display = 'flex';
        loadUserList();
    } else {
        console.error('Admin Panel element not found!');
    }
}

function closeAdminPanel() {
    document.getElementById('adminPanel').style.display = 'none';
}

function switchAdminTab(tabName) {
    // Hide all tabs
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.admin-tabs .tab-btn').forEach(el => el.classList.remove('active'));

    // Show selected
    document.getElementById(`tab-${tabName}`).classList.add('active');
    // Highlight button (simple logic, assuming order or ID matching, here strictly by onclick)
    // Actually we need to find the button that called this. 
    // Simplified: just re-query buttons and add active class based on text or data attribute.
    // Ideally pass 'this' or use event.target. For now, rely on simpler CSS toggling if we render fully.
    // Let's just set the active class on buttons manually for now:
    const buttons = document.querySelectorAll('.admin-tabs .tab-btn');
    buttons.forEach(btn => {
        if (btn.textContent.toLowerCase().includes(tabName)) btn.classList.add('active');
    });
}

function loadUserList() {
    fetch('/admin/users')
        .then(res => res.json())
        .then(data => {
            const tbody = document.querySelector('#userTable tbody');
            tbody.innerHTML = '';

            if (data.users) {
                data.users.forEach(user => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                    <td>${user.username}</td>
                    <td><span class="mode-badge" style="background: ${user.role === 'admin' ? '#A78BFA' : '#667eea'}">${user.role}</span></td>
                    <td>${new Date(user.created_at).toLocaleDateString()}</td>
                    <td>
                        <button onclick="showEditUserModal(${user.id}, '${user.username}', '${user.role}')" class="control-btn warning small" style="margin-right: 5px;">
                            <i class="fas fa-edit"></i>
                        </button>
                        <button onclick="deleteUser(${user.id})" class="control-btn danger small" ${user.id === currentUser.id ? 'disabled' : ''}>
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                `;
                    tbody.appendChild(tr);
                });
            }
        })
        .catch(err => console.error('Failed to load users', err));
}

function showAddUserModal() {
    document.getElementById('addUserModal').style.display = 'block';
}

function handleAddUser(e) {
    e.preventDefault();
    const username = document.getElementById('newUsername').value;
    const password = document.getElementById('newPassword').value;
    const role = document.getElementById('newRole').value;

    fetch('/admin/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password, role })
    })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                closeModal('addUserModal');
                loadUserList(); // Refresh list
                alert('User created successfully!');
                e.target.reset();
            } else {
                alert('Error: ' + data.error);
            }
        })
        .catch(err => alert('Error creating user: ' + err.message));
}

function deleteUser(userId) {
    if (!confirm('Are you sure you want to delete this user? This cannot be undone.')) return;

    fetch(`/admin/users/${userId}`, { method: 'DELETE' })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                loadUserList();
            } else {
                alert('Error: ' + data.error);
            }
        })
        .catch(err => alert('Delete failed: ' + err.message));
}

// Override adminRequired to use new auth
function adminRequired(action) {
    if (!currentUser) {
        document.getElementById('loginModal').style.display = 'block';
    } else if (currentUser.role !== 'admin') {
        alert('Admin privileges required.');
    } else {
        if (action === 'showPrompt') showPrompt();
        if (action === 'showSystemPromptEditor') showSystemPromptEditor();
        if (action === 'showAdminPanel') showAdminPanel();
    }
}

// Update showAdminLogin to show new modal
function showAdminLogin() {
    document.getElementById('loginModal').style.display = 'block';
}

function hideAdminLogin() {
    closeModal('loginModal');
}


// Theme switching
function initializeThemeSelector() {
    const savedTheme = localStorage.getItem('selectedTheme') || 'classic';
    switchTheme(savedTheme);
}

function switchTheme(themeName) {
    const teyraTheme = document.getElementById('teyra-theme');
    const themeButtons = document.querySelectorAll('.theme-btn');

    themeButtons.forEach(btn => {
        btn.classList.remove('active');
        btn.style.background = 'white';
        btn.style.color = '#333';
        btn.style.borderColor = '#e9ecef';
    });

    const activeButton = document.querySelector(`[data-theme="${themeName}"]`);
    if (activeButton) {
        activeButton.classList.add('active');
        if (themeName === 'classic') {
            activeButton.style.background = 'linear-gradient(135deg, #667eea, #764ba2)';
            activeButton.style.color = 'white';
            activeButton.style.borderColor = '#667eea';
        } else {
            activeButton.style.background = 'linear-gradient(135deg, #22D3EE, #A78BFA)';
            activeButton.style.color = 'white';
            activeButton.style.borderColor = '#22D3EE';
        }
    }

    if (themeName === 'teyra') {
        teyraTheme.disabled = false;
        addMessage('assistant', '🌌 **Teyra Dark theme activated!**');
    } else {
        teyraTheme.disabled = true;
        addMessage('assistant', '🎨 **Classic theme activated!**');
    }

    localStorage.setItem('selectedTheme', themeName);

    const mermaidTheme = themeName === 'teyra' ? 'dark' : 'default';
    mermaid.initialize({
        startOnLoad: false,
        theme: mermaidTheme,
        securityLevel: 'loose',
        flowchart: {
            htmlLabels: true,
            useMaxWidth: true
        }
    });
}

function loadVectorDbStatus() {
    console.log('Refreshing Vector DB Status...');
}

function showVectorDbStats() {
    addMessage('assistant', '📊 Vector DB stats feature coming soon!');
}

// ========================================
// DARK MODE TOGGLE (NEW)
// ========================================

// Initialize dark mode on page load
document.addEventListener('DOMContentLoaded', () => {
    const themeToggle = document.getElementById('themeToggle');
    const savedDarkMode = localStorage.getItem('darkMode') === 'true';

    // Apply saved theme
    if (savedDarkMode) {
        document.body.classList.add('dark-theme');
        if (themeToggle) {
            themeToggle.innerHTML = '<i class="fas fa-sun"></i>';
        }
    }

    // Add click handler
    if (themeToggle) {
        themeToggle.addEventListener('click', () => {
            const isDark = document.body.classList.toggle('dark-theme');
            localStorage.setItem('darkMode', isDark);
            themeToggle.innerHTML = isDark ? '<i class="fas fa-sun"></i>' : '<i class="fas fa-moon"></i>';

            // Optional: Show notification
            const notification = document.createElement('div');
            notification.style.cssText = 'position: fixed; top: 80px; right: 20px; background: linear-gradient(135deg, #667eea, #764ba2); color: white; padding: 12px 20px; border-radius: 10px; z-index: 1000; box-shadow: 0 4px 15px rgba(0,0,0,0.2); animation: slideIn 0.3s ease;';
            notification.textContent = isDark ? '🌙 Dark mode enabled' : '☀️ Light mode enabled';
            document.body.appendChild(notification);
            setTimeout(() => notification.remove(), 2000);
        });
    }
});

// ========================================
// LANGUAGE TOGGLE
// ========================================

const translations = {
    'en': {
        'placeholder': 'Type your message here... (Shift+Enter for new line)',
        'lang_switched': 'Language switched to English'
    },
    'it': {
        'placeholder': 'Scrivi il tuo messaggio qui... (Shift+Invio per nuova riga)',
        'lang_switched': 'Lingua cambiata in Italiano'
    }
};

let currentLanguage = localStorage.getItem('language') || 'en';

document.addEventListener('DOMContentLoaded', () => {
    const langToggle = document.getElementById('langToggle');
    if (langToggle) {
        updateLanguageUI();

        langToggle.addEventListener('click', () => {
            currentLanguage = currentLanguage === 'en' ? 'it' : 'en';
            localStorage.setItem('language', currentLanguage);
            updateLanguageUI();

            // Show notification
            const notification = document.createElement('div');
            notification.style.cssText = 'position: fixed; top: 80px; right: 20px; background: linear-gradient(135deg, #22D3EE, #A78BFA); color: white; padding: 12px 20px; border-radius: 10px; z-index: 1000; box-shadow: 0 4px 15px rgba(0,0,0,0.2); animation: slideIn 0.3s ease;';
            notification.textContent = translations[currentLanguage]['lang_switched'];
            document.body.appendChild(notification);
            setTimeout(() => notification.remove(), 2000);
        });
    }
});

function updateLanguageUI() {
    const langToggle = document.getElementById('langToggle');
    if (langToggle) {
        langToggle.querySelector('span').textContent = currentLanguage.toUpperCase();
    }

    // Update placeholder
    const messageInput = document.getElementById('messageInput');
    if (messageInput) {
        messageInput.placeholder = translations[currentLanguage]['placeholder'];
    }
}

// ========================================
// KNOWLEDGE GRAPH
// ========================================

document.addEventListener('DOMContentLoaded', () => {
    const graphToggle = document.getElementById('graphToggle');
    if (graphToggle) {
        graphToggle.addEventListener('click', () => {
            document.getElementById('graphModal').style.display = 'block';
            loadKnowledgeGraph();
        });
    }
});

function loadKnowledgeGraph() {
    fetch('/graph_data')
        .then(response => response.json())
        .then(data => {
            const container = document.getElementById('network-graph');

            if (!data.nodes || data.nodes.length === 0) {
                container.innerHTML = '<div style="color: var(--text-1); text-align: center; padding-top: 50px;">No documents found. Upload some files to see them here!</div>';
                return;
            }

            const nodes = new vis.DataSet(data.nodes);
            const edges = new vis.DataSet(data.edges);

            const options = {
                nodes: {
                    shape: 'dot',
                    size: 20,
                    font: {
                        size: 14,
                        color: '#ffffff'
                    },
                    borderWidth: 2,
                    color: {
                        background: '#22D3EE',
                        border: '#ffffff',
                        highlight: {
                            background: '#A78BFA',
                            border: '#ffffff'
                        }
                    }
                },
                edges: {
                    width: 2,
                    color: { color: 'rgba(255, 255, 255, 0.3)' },
                    smooth: {
                        type: 'continuous'
                    }
                },
                physics: {
                    stabilization: false,
                    barnesHut: {
                        gravitationalConstant: -8000,
                        springConstant: 0.04,
                        springLength: 95
                    }
                },
                interaction: {
                    tooltipDelay: 200,
                    hideEdgesOnDrag: true
                }
            };

            const network = new vis.Network(container, { nodes, edges }, options);

            network.on("click", function (params) {
                if (params.nodes.length > 0) {
                    const nodeId = params.nodes[0];
                    const node = nodes.get(nodeId);
                    // Optional: Open document on click
                    console.log('Clicked node:', node.label);
                }
            });
        })
        .catch(error => console.error('Error loading graph:', error));
}


// ========================================
// MOBILE SIDEBAR LOGIC
// ========================================

function initializeMobileSidebar() {
    const sidebarToggle = document.getElementById('sidebar-toggle');
    const sidebar = document.querySelector('.sidebar');

    if (!sidebarToggle || !sidebar) return;

    // Create overlay
    const overlay = document.createElement('div');
    overlay.className = 'sidebar-overlay';
    document.body.appendChild(overlay);

    function toggleSidebar() {
        sidebar.classList.toggle('active');
        overlay.classList.toggle('active');
    }

    function closeSidebar() {
        sidebar.classList.remove('active');
        overlay.classList.remove('active');
    }

    // Toggle button click
    sidebarToggle.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleSidebar();
    });

    // Overlay click (close)
    overlay.addEventListener('click', closeSidebar);

    // Close when clicking a mode button (on mobile)
    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            if (window.innerWidth <= 768) {
                closeSidebar();
            }
        });
    });
}

// ========================================
// EDIT USER FUNCTIONS
// ========================================

function showEditUserModal(id, username, role) {
    document.getElementById('editUserId').value = id;
    document.getElementById('editUsername').value = username;
    document.getElementById('editRole').value = role;
    document.getElementById('editPassword').value = '';
    document.getElementById('editConfirmPassword').value = '';
    document.getElementById('editUserModal').style.display = 'block';
}

function handleEditUser(e) {
    e.preventDefault();
    const id = document.getElementById('editUserId').value;
    const username = document.getElementById('editUsername').value;
    const role = document.getElementById('editRole').value;
    const password = document.getElementById('editPassword').value;
    const confirmPassword = document.getElementById('editConfirmPassword').value;

    const data = { username, role };

    if (password) {
        if (password !== confirmPassword) {
            alert('Passwords do not match!');
            return;
        }
        data.password = password;
    }

    fetch(`/admin/users/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                closeModal('editUserModal');
                loadUserList();
                alert('User updated successfully!');
            } else {
                alert('Error: ' + data.error);
            }
        })
        .catch(err => alert('Error updating user: ' + err.message));
}

function togglePasswordVisibility(fieldId) {
    const field = document.getElementById(fieldId);
    const type = field.getAttribute('type') === 'password' ? 'text' : 'password';
    field.setAttribute('type', type);

    // Update icon
    const btn = field.nextElementSibling;
    const icon = btn.querySelector('i');
    if (type === 'text') {
        icon.classList.remove('fa-eye');
        icon.classList.add('fa-eye-slash');
    } else {
        icon.classList.remove('fa-eye-slash');
        icon.classList.add('fa-eye');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    // Edit User Form Handler
    const editUserForm = document.getElementById('editUserForm');
    if (editUserForm) {
        editUserForm.addEventListener('submit', handleEditUser);
    }
});
