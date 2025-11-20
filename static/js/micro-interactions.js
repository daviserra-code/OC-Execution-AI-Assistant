// ========================================
// PHASE 3: ENHANCED MICRO-INTERACTIONS
// ========================================

/**
 * Micro-interactions enhancement module
 * Adds ripple effects, enhanced notifications, and smooth animations
 */

// Initialize micro-interactions on page load
document.addEventListener('DOMContentLoaded', () => {
    initializeRippleEffects();
    initializeScrollToTop();
    initializeSidebarScrollShadow();
    initializeDragAndDrop();
    enhanceNotifications();
    enhanceCopyFeedback();
});

/**
 * Add ripple effect to buttons
 */
function initializeRippleEffects() {
    const buttons = document.querySelectorAll('.control-btn, .mode-btn, .template-btn, .send-btn');

    buttons.forEach(button => {
        button.classList.add('ripple');
    });
}

/**
 * Scroll to top button functionality
 */
function initializeScrollToTop() {
    // Create scroll to top button
    const scrollBtn = document.createElement('button');
    scrollBtn.className = 'scroll-to-top';
    scrollBtn.innerHTML = '<i class="fas fa-arrow-up"></i>';
    scrollBtn.setAttribute('aria-label', 'Scroll to top');
    document.body.appendChild(scrollBtn);

    const chatMessages = document.getElementById('chatMessages');

    // Show/hide based on scroll position
    if (chatMessages) {
        chatMessages.addEventListener('scroll', () => {
            if (chatMessages.scrollTop > 300) {
                scrollBtn.classList.add('visible');
            } else {
                scrollBtn.classList.remove('visible');
            }
        });

        // Scroll to top on click
        scrollBtn.addEventListener('click', () => {
            chatMessages.scrollTo({
                top: 0,
                behavior: 'smooth'
            });
        });
    }
}

/**
 * Add scroll shadow to sidebar
 */
function initializeSidebarScrollShadow() {
    const sidebar = document.querySelector('.sidebar');

    if (sidebar) {
        sidebar.addEventListener('scroll', () => {
            if (sidebar.scrollTop > 10) {
                sidebar.classList.add('scrolled');
            } else {
                sidebar.classList.remove('scrolled');
            }
        });
    }
}

/**
 * Enhanced drag and drop for file uploads
 */
function initializeDragAndDrop() {
    const uploadSection = document.querySelector('.upload-section');

    if (uploadSection) {
        uploadSection.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadSection.classList.add('drag-over');
        });

        uploadSection.addEventListener('dragleave', () => {
            uploadSection.classList.remove('drag-over');
        });

        uploadSection.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadSection.classList.remove('drag-over');
            // File handling is done by existing code
        });
    }
}

/**
 * Enhanced notification system
 */
function enhanceNotifications() {
    // Override existing notification creation
    window.showNotification = function (message, type = 'info', duration = 3000) {
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;

        // Add icon based on type
        let icon = '';
        switch (type) {
            case 'success':
                icon = '<i class="fas fa-check-circle"></i>';
                break;
            case 'error':
                icon = '<i class="fas fa-exclamation-circle"></i>';
                break;
            case 'warning':
                icon = '<i class="fas fa-exclamation-triangle"></i>';
                break;
            default:
                icon = '<i class="fas fa-info-circle"></i>';
        }

        notification.innerHTML = `
            ${icon}
            <span>${message}</span>
            <div class="notification-progress">
                <div class="notification-progress-bar"></div>
            </div>
        `;

        document.body.appendChild(notification);

        // Auto-dismiss
        setTimeout(() => {
            notification.style.animation = 'slideInRight 0.4s reverse';
            setTimeout(() => notification.remove(), 400);
        }, duration);
    };
}

/**
 * Enhanced copy to clipboard feedback
 */
function enhanceCopyFeedback() {
    // Intercept the existing copyToClipboard function
    const originalCopyToClipboard = window.copyToClipboard;

    window.copyToClipboard = function (encodedContent) {
        const content = decodeURIComponent(atob(encodedContent));
        navigator.clipboard.writeText(content).then(() => {
            // Find the button that was clicked
            const copyButtons = document.querySelectorAll('.action-btn.copy');
            copyButtons.forEach(btn => {
                if (btn.onclick && btn.onclick.toString().includes(encodedContent)) {
                    btn.classList.add('copied');
                    setTimeout(() => btn.classList.remove('copied'), 600);
                }
            });

            // Show enhanced notification
            if (window.showNotification) {
                window.showNotification('Copied to clipboard!', 'success', 2000);
            }
        });
    };
}

/**
 * Add new message class for pulse animation
 */
function markAsNewMessage(messageElement) {
    messageElement.classList.add('new-message');
    setTimeout(() => {
        messageElement.classList.remove('new-message');
    }, 1000);
}

/**
 * Enhance mode switching with animation
 */
document.addEventListener('DOMContentLoaded', () => {
    const modeButtons = document.querySelectorAll('.mode-btn');

    modeButtons.forEach(btn => {
        btn.addEventListener('click', function () {
            // Trigger mode badge animation
            const modeBadge = document.querySelector('.mode-badge');
            if (modeBadge) {
                modeBadge.style.animation = 'none';
                setTimeout(() => {
                    modeBadge.style.animation = 'badgeSlide 0.4s ease-out';
                }, 10);
            }
        });
    });
});

/**
 * Enhance message input focus
 */
document.addEventListener('DOMContentLoaded', () => {
    const messageInput = document.getElementById('messageInput');

    if (messageInput) {
        messageInput.addEventListener('focus', () => {
            messageInput.parentElement.classList.add('input-focused');
        });

        messageInput.addEventListener('blur', () => {
            messageInput.parentElement.classList.remove('input-focused');
        });
    }
});

/**
 * Export functions for use in other modules
 */
window.microInteractions = {
    markAsNewMessage,
    showNotification: window.showNotification
};

console.log('✨ Phase 3 Micro-Interactions loaded successfully!');
