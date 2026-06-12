/**
 * GuestCheckInWidget — Embeddable chat widget (vanilla JS)
 *
 * Usage:
 *   GuestCheckInWidget.init({ sessionId, token, wsUrl, apiUrl });
 */
(function (root) {
  'use strict';

  /* ── Step definitions ──────────────────────────────────────────── */
  var STEPS = [
    { state: 'PRIVACY_POLICY_PENDING', label: 'Privacy', idx: 0 },
    { state: 'HOUSE_RULES_PENDING',    label: 'Rules',  idx: 1 },
    { state: 'RENTAL_AGREEMENT_PENDING',label: 'Rental', idx: 2 },
    { state: 'INFO_VERIFY_PENDING',    label: 'Info',   idx: 3 },
    { state: 'ID_VERIFY_PENDING',      label: 'ID',     idx: 4 },
    { state: 'INCIDENTAL_PROTECTION_PENDING', label: 'Incidental', idx: 5 }
  ];

  var STEP_MAP = {};
  STEPS.forEach(function (s) { STEP_MAP[s.state] = s.idx; });

  /* ── URL detection regex ───────────────────────────────────────── */
  var URL_RE = /(?:https?:\/\/[^\s<>"']+|\/api\/v1\/[^\s<>"']+)/g;

  /* ── Constructor ───────────────────────────────────────────────── */
  function GuestCheckInWidget(config) {
    this.sessionId = config.sessionId || '';
    this.token     = config.token || '';
    this.wsUrl     = config.wsUrl || '';
    this.apiUrl    = config.apiUrl || '';
    this.theme     = config.theme || 'light';

    this.ws            = null;
    this.reconnectMs   = 1000;
    this.maxReconnectMs= 30000;
    this.reconnectTimer= null;
    this.typingTimer   = null;
    this.callbacks     = { message: [] };
    this.messages      = [];
    this.currentState  = 'INIT';
    this.requiredAction= '';
    this.sessionStatus = '';
    this.connected     = false;
    this.container     = null;
  }

  /* ── init() ────────────────────────────────────────────────────── */
  GuestCheckInWidget.init = function (config) {
    var w = new GuestCheckInWidget(config);
    w.init();
    return w;
  };

  var proto = GuestCheckInWidget.prototype;

  proto.init = function () {
    this._buildDOM();
    this._applyTheme();
    this._bindEvents();
    this._connectWS();
  };

  /* ── DOM Construction ──────────────────────────────────────────── */
  proto._buildDOM = function () {
    // FAB
    var fab = document.createElement('button');
    fab.className = 'gci-fab';
    fab.id = 'gci-fab';
    fab.innerHTML = '&#128172;';
    fab.title = 'Open Check-In Chat';
    document.body.appendChild(fab);

    // Widget
    var w = document.createElement('div');
    w.className = 'gci-widget gci-closed';
    w.id = 'gci-widget';
    w.innerHTML =
      '<div class="gci-header">' +
        '<div>' +
          '<div class="gci-header-title">Guest Check-In</div>' +
          '<div class="gci-header-status" id="gci-conn-text">Connecting...</div>' +
        '</div>' +
        '<button class="gci-close-btn" id="gci-close">&times;</button>' +
      '</div>' +
      '<div class="gci-progress" id="gci-progress">' +
        '<div class="gci-progress-steps">' +
          '<div class="gci-progress-line" id="gci-progress-line"></div>' +
          STEPS.map(function (s) {
            return '<div class="gci-step" data-state="' + s.state + '">' +
              '<div class="gci-step-icon" id="gci-step-' + s.idx + '"></div>' +
              '<div class="gci-step-label">' + s.label + '</div>' +
            '</div>';
          }).join('') +
        '</div>' +
      '</div>' +
      '<div class="gci-state-bar" id="gci-state-bar">Initializing...</div>' +
      '<div class="gci-conn-bar" id="gci-conn-bar">Connection lost. Reconnecting...</div>' +
      '<div class="gci-messages" id="gci-messages"></div>' +
      '<div class="gci-input-area">' +
        '<input class="gci-input" id="gci-input" type="text" placeholder="Type a message..." autocomplete="off">' +
        '<button class="gci-send-btn" id="gci-send" title="Send">&#10148;</button>' +
      '</div>';

    document.body.appendChild(w);
    this.container = w;
  };

  proto._applyTheme = function () {
    if (this.theme === 'dark') {
      this.container.setAttribute('data-theme', 'dark');
    }
  };

  /* ── Event Binding ─────────────────────────────────────────────── */
  proto._bindEvents = function () {
    var self = this;
    var fab = document.getElementById('gci-fab');
    var closeBtn = document.getElementById('gci-close');
    var sendBtn  = document.getElementById('gci-send');
    var input    = document.getElementById('gci-input');

    fab.addEventListener('click', function () {
      self.container.classList.remove('gci-closed');
      fab.classList.add('gci-hidden');
    });

    closeBtn.addEventListener('click', function () {
      self.container.classList.add('gci-closed');
      fab.classList.remove('gci-hidden');
    });

    sendBtn.addEventListener('click', function () { self._handleSend(); });

    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        self._handleSend();
      }
    });
  };

  /* ── WebSocket ─────────────────────────────────────────────────── */
  proto._connectWS = function () {
    var self = this;
    var url  = this.wsUrl;
    if (!url) {
      url = 'ws' + (location.protocol === 'https:' ? 's' : '') + '://' +
            location.host + '/api/v1/ws/' + this.sessionId + '?token=' +
            encodeURIComponent(this.token);
    }
    this.ws = new WebSocket(url);

    this.ws.onopen = function () {
      self.connected = true;
      self.reconnectMs = 1000;
      self._hideConnBar();
      self._setConnText('Connected');
      self._setInputEnabled(true);
      // Sync state on (re)connect — the state may have changed while
      // the guest was on an external page (ID upload, payment, etc.)
      self._syncState();
    };

    this.ws.onmessage = function (evt) {
      self._onMessage(evt.data);
    };

    this.ws.onclose = function () {
      self.connected = false;
      self._setConnText('Disconnected');
      self._showConnBar('reconnecting');
      self._scheduleReconnect();
    };

    this.ws.onerror = function () {
      self._setConnText('Error');
    };
  };

  proto._scheduleReconnect = function () {
    var self = this;
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(function () {
      self.reconnectTimer = null;
      self._connectWS();
    }, this.reconnectMs);
    this.reconnectMs = Math.min(this.reconnectMs * 2, this.maxReconnectMs);
  };

  proto._hideConnBar = function () {
    var bar = document.getElementById('gci-conn-bar');
    bar.classList.remove('gci-visible', 'gci-reconnecting');
  };

  proto._showConnBar = function (type) {
    var bar = document.getElementById('gci-conn-bar');
    bar.textContent = type === 'reconnecting'
      ? 'Connection lost. Reconnecting...'
      : 'Unable to connect. Retrying...';
    bar.className = 'gci-conn-bar gci-visible' +
      (type === 'reconnecting' ? ' gci-reconnecting' : '');
  };

  proto._setConnText = function (txt) {
    document.getElementById('gci-conn-text').textContent = txt;
  };

  proto._setInputEnabled = function (enabled) {
    document.getElementById('gci-input').disabled = !enabled;
    document.getElementById('gci-send').disabled  = !enabled;
  };

  /* ── Incoming Message Handling ─────────────────────────────────── */
  proto._onMessage = function (raw) {
    var data;
    try { data = JSON.parse(raw); } catch (e) { return; }

    var type = data.type;
    var payload = data.data || {};

    if (type === 'welcome') {
      this.currentState   = payload.current_state || 'INIT';
      this.requiredAction = payload.required_action || '';
      this.sessionStatus  = payload.session_status || '';
      this._updateProgress(this.currentState);
      this._updateStateBar(this.requiredAction);
      this._addSystemMessage('Check-in session started.');
      return;
    }

    if (type === 'agent') {
      this._hideTyping();
      var msg = payload.message || {};
      var content = msg.content || '';
      var instructionsHtml = payload.instructions_html || null;
      this.currentState   = payload.current_state || this.currentState;
      this.requiredAction = payload.required_action || '';
      this.sessionStatus  = payload.session_status || this.sessionStatus;
      this._addMessage('agent', content, instructionsHtml);
      this._updateProgress(this.currentState);
      this._updateStateBar(this.requiredAction);

      if (this.sessionStatus === 'completed' || this.currentState === 'COMPLETED') {
        this._addSystemMessage('Check-in complete! You may close this window.');
      }
      return;
    }

    if (type === 'error') {
      this._hideTyping();
      this._addSystemMessage('Error: ' + (payload.detail || 'Unknown error'));
      return;
    }

    if (type === 'state_update') {
      this.currentState   = payload.current_state || this.currentState;
      this.requiredAction = payload.required_action || this.requiredAction;
      this._updateProgress(this.currentState);
      this._updateStateBar(this.requiredAction);
    }
  };

  /* ── Send Message ──────────────────────────────────────────────── */
  proto.sendMessage = function (text) {
    if (!text || !text.trim()) return;
    if (!this.connected) {
      this._addSystemMessage('Not connected. Please wait...');
      return;
    }

    var payload = JSON.stringify({ content: text.trim() });
    try {
      this.ws.send(payload);
    } catch (e) {
      this._addSystemMessage('Failed to send message. Please try again.');
      return;
    }

    this._addMessage('guest', text.trim());
    this._showTyping();
  };

  proto._handleSend = function () {
    var input = document.getElementById('gci-input');
    var text  = input.value;
    if (!text.trim()) return;
    this.sendMessage(text);
    input.value = '';
    input.focus();
  };

  /* ── State Sync (reconnect) ─────────────────────────────────────── */
  proto._syncState = function () {
    var self = this;
    var url = this.apiUrl + '/sessions/' + this.sessionId + '/state';
    var xhr = new XMLHttpRequest();
    xhr.open('GET', url, true);
    xhr.setRequestHeader('Authorization', 'Bearer ' + this.token);
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      if (xhr.status === 401 || xhr.status === 403) {
        // Token auth not supported on this endpoint, skip sync
        return;
      }
      if (xhr.status !== 200) return;
      try {
        var data = JSON.parse(xhr.responseText);
        var newState = data.current_state || 'INIT';
        if (newState !== self.currentState) {
          // State changed while we were disconnected
          self.currentState = newState;
          self.requiredAction = data.required_action || '';
          self._updateProgress(newState);
          self._updateStateBar(data.required_action || '');

          // Tell the user what step they're on now
          var stepMsg = self._stepMessage(newState, data.required_action);
          self._addSystemMessage(stepMsg);

          if (newState === 'COMPLETED') {
            self._addSystemMessage('Check-in complete! You may close this window.');
            // Fetch arrival instructions via WebSocket
            self._fetchArrivalInstructions();
          }
        }
      } catch (e) { /* ignore parse errors */ }
    };
    xhr.send();
  };

  proto._fetchArrivalInstructions = function () {
    // Ask the agent for arrival instructions (triggers COMPLETED enrichment)
    this.sendMessage('show me my arrival instructions');
  };

  proto._stepMessage = function (state, action) {
    var msgs = {
      'PRIVACY_POLICY_PENDING': 'Welcome back! You\'re on the Privacy Policy step.',
      'HOUSE_RULES_PENDING': 'Welcome back! You\'re on the House Rules step.',
      'RENTAL_AGREEMENT_PENDING': 'Welcome back! You\'re on the Rental Agreement step.',
      'INFO_VERIFY_PENDING': 'Welcome back! Please verify your information.',
      'ID_VERIFY_PENDING': 'Welcome back! Please upload your ID using the secure link.',
      'INCIDENTAL_PROTECTION_PENDING': 'Welcome back! Please select your incidental protection option.',
      'COMPLETED': 'Your check-in is complete!',
      'REFUSED': 'Your check-in was declined.'
    };
    return msgs[state] || ('Welcome back! Current step: ' + (action || state));
  };

  /* ── Typing Indicator ──────────────────────────────────────────── */
  proto._showTyping = function () {
    if (document.getElementById('gci-typing')) return;
    var el = document.createElement('div');
    el.className = 'gci-typing';
    el.id = 'gci-typing';
    el.innerHTML = '<div class="gci-typing-dot"></div>' +
                   '<div class="gci-typing-dot"></div>' +
                   '<div class="gci-typing-dot"></div>';
    var box = document.getElementById('gci-messages');
    box.appendChild(el);
    box.scrollTop = box.scrollHeight;

    var self = this;
    this.typingTimer = setTimeout(function () { self._hideTyping(); }, 30000);
  };

  proto._hideTyping = function () {
    if (this.typingTimer) { clearTimeout(this.typingTimer); this.typingTimer = null; }
    var el = document.getElementById('gci-typing');
    if (el) el.parentNode.removeChild(el);
  };

  /* ── Message Rendering ─────────────────────────────────────────── */
  proto._addMessage = function (role, content, instructionsHtml) {
    var box = document.getElementById('gci-messages');
    var div = document.createElement('div');
    div.className = 'gci-msg gci-msg-' + role;

    // Check for secure links (ID upload, incidental)
    if (role === 'agent') {
      div.innerHTML = this._renderAgentContent(content);
    } else {
      div.textContent = content;
    }

    // Append safe-HTML instructions block if provided
    if (role === 'agent' && instructionsHtml) {
      var instrDiv = document.createElement('div');
      instrDiv.className = 'gci-instructions';
      instrDiv.innerHTML = this._sanitizeHtml(instructionsHtml);
      div.appendChild(instrDiv);
    }

    box.appendChild(div);
    box.scrollTop = box.scrollHeight;

    this.messages.push({ role: role, content: content });
    this._fireCallbacks({ role: role, content: content });
  };

  proto._addSystemMessage = function (text) {
    var box = document.getElementById('gci-messages');
    var div = document.createElement('div');
    div.className = 'gci-msg gci-msg-system';
    div.textContent = text;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
    this.messages.push({ role: 'system', content: text });
  };

  proto._renderAgentContent = function (content) {
    var self = this;
    var html = this._escapeHtml(content);

    // Replace URLs with secure link cards if they look like upload/payment links
    html = html.replace(URL_RE, function (url) {
      // Make relative URLs absolute
      var fullUrl = url;
      if (url.indexOf('/') === 0) {
        fullUrl = location.origin + url;
      }

      var isSecure = url.indexOf('/id-upload/') !== -1 ||
                     url.indexOf('/incidental/') !== -1 ||
                     url.indexOf('token=') !== -1;
      if (isSecure) {
        var desc = 'Open secure page';
        if (url.indexOf('/id-upload/') !== -1) desc = 'Upload your government-issued ID';
        if (url.indexOf('/incidental/') !== -1) desc = 'Select incidental protection & pay';
        return '<a class="gci-secure-link" href="' + self._escapeHtml(fullUrl) +
               '" target="_blank" rel="noopener noreferrer">' +
               '<div class="gci-secure-link-header">' +
                 '<span class="gci-secure-link-icon">&#128274;</span>' +
                 '<span>Secure Link</span>' +
                 '<span class="gci-secure-link-label">Secure</span>' +
               '</div>' +
               '<div class="gci-secure-link-desc">' + desc + '</div>' +
             '</a>';
      }
      return '<a href="' + self._escapeHtml(fullUrl) +
             '" target="_blank" rel="noopener noreferrer">' +
             self._escapeHtml(url) + '</a>';
    });

    return html;
  };

  proto._escapeHtml = function (s) {
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  };

  proto._sanitizeHtml = function (html) {
    var parser = new DOMParser();
    var doc = parser.parseFromString(html, 'text/html');
    // Remove dangerous elements
    var dangerous = doc.querySelectorAll('script, iframe, object, embed');
    dangerous.forEach(function (el) { el.remove(); });
    // Remove on* event attributes and javascript: URLs
    var allElements = doc.querySelectorAll('*');
    allElements.forEach(function (el) {
      var attrs = Array.from(el.attributes);
      attrs.forEach(function (attr) {
        if (attr.name.startsWith('on') || attr.value.toLowerCase().indexOf('javascript:') === 0) {
          el.removeAttribute(attr.name);
        }
      });
    });
    return doc.body.innerHTML;
  };

  /* ── Progress Bar ──────────────────────────────────────────────── */
  proto._updateProgress = function (state) {
    var currentIdx = STEP_MAP[state];
    var isCompleted = (state === 'COMPLETED');

    STEPS.forEach(function (s, i) {
      var icon = document.getElementById('gci-step-' + i);
      var stepEl = icon ? icon.parentElement : null;
      if (!icon) return;

      icon.className = 'gci-step-icon';
      if (stepEl) stepEl.className = 'gci-step';

      if (isCompleted || (currentIdx !== undefined && i < currentIdx)) {
        icon.classList.add('gci-done');
        if (stepEl) stepEl.classList.add('gci-done');
        icon.innerHTML = '&#10003;'; // checkmark
      } else if (currentIdx !== undefined && i === currentIdx) {
        icon.classList.add('gci-current');
        if (stepEl) stepEl.classList.add('gci-current');
        icon.innerHTML = (i + 1);
      } else {
        icon.innerHTML = '&#8226;'; // dot
      }
    });

    // Progress line
    var line = document.getElementById('gci-progress-line');
    if (line) {
      var pct = 0;
      if (isCompleted) {
        pct = 100;
      } else if (currentIdx !== undefined) {
        pct = (currentIdx / STEPS.length) * 100;
      }
      line.style.width = pct + '%';
    }
  };

  /* ── State Bar ─────────────────────────────────────────────────── */
  proto._updateStateBar = function (action) {
    var bar = document.getElementById('gci-state-bar');
    if (bar) bar.textContent = action || 'Ready';
  };

  /* ── Callbacks ─────────────────────────────────────────────────── */
  proto.onMessage = function (cb) {
    if (typeof cb === 'function') this.callbacks.message.push(cb);
  };

  proto._fireCallbacks = function (msg) {
    this.callbacks.message.forEach(function (cb) { cb(msg); });
  };

  /* ── Disconnect ────────────────────────────────────────────────── */
  proto.disconnect = function () {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
    this.connected = false;
    this._setConnText('Disconnected');
  };

  /* ── Expose ────────────────────────────────────────────────────── */
  root.GuestCheckInWidget = GuestCheckInWidget;

})(typeof window !== 'undefined' ? window : this);
