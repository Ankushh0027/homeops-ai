/**
 * app/web/static/app.js
 * =====================
 * HomeOps-AI: Alexa+-inspired conversational smart-home safety assistant.
 *
 * Coordinates:
 * - Real conversational turns with HomeOps MCP backend
 * - Progressive disclosure (natural voice chat -> deep deterministic investigation)
 * - Live sensor telemetry and device state
 * - Event timeline rendering with correlated anomaly indicators
 * - Deterministic safety policy & physical action block demonstrations
 * - Real-time MCP tool call inspection (Streamable HTTP /mcp)
 * - Browser Web Speech API (transcription & speech synthesis)
 */

document.addEventListener('DOMContentLoaded', () => {
  // -------------------------------------------------------------------------
  // State
  // -------------------------------------------------------------------------
  const state = {
    currentScenario: 'security_incident',
    homeState: null,
    events: [],
    currentIncident: null,
    currentRisk: null,
    currentRecommendation: null,
    currentEvidence: [],
    history: [],
    mcpStats: null,
    activeTab: 'chat',
    isProcessing: false,
    recognition: null,
    isRecording: false,
  };

  // -------------------------------------------------------------------------
  // DOM Elements
  // -------------------------------------------------------------------------
  const elements = {
    // Nav tabs
    tabButtons: document.querySelectorAll('.nav-tab-btn'),
    viewSections: document.querySelectorAll('.view-section'),
    investigationNavBadge: document.getElementById('investigationNavBadge'),

    // Chat elements
    chatThread: document.getElementById('chatThread'),
    chatComposerForm: document.getElementById('chatComposerForm'),
    userInputField: document.getElementById('userInputField'),
    sendBtn: document.getElementById('sendBtn'),
    micBtn: document.getElementById('micBtn'),
    typingIndicator: document.getElementById('typingIndicator'),
    speechIndicatorLabel: document.getElementById('speechIndicatorLabel'),
    scenarioSelector: document.getElementById('scenarioSelector'),

    // Quick Glance elements
    glanceRiskBadge: document.getElementById('glanceRiskBadge'),
    glanceIncidentSummary: document.getElementById('glanceIncidentSummary'),
    glanceConfidenceFill: document.getElementById('glanceConfidenceFill'),
    glanceConfidenceText: document.getElementById('glanceConfidenceText'),
    glanceDeviceCount: document.getElementById('glanceDeviceCount'),
    glanceDeviceList: document.getElementById('glanceDeviceList'),
    quickViewInvestigationBtn: document.getElementById('quickViewInvestigationBtn'),
    quickViewDevicesBtn: document.getElementById('quickViewDevicesBtn'),

    // Devices View
    fullDevicesGrid: document.getElementById('fullDevicesGrid'),
    refreshDevicesBtn: document.getElementById('refreshDevicesBtn'),

    // Investigation View
    invTypeTag: document.getElementById('invTypeTag'),
    invTitle: document.getElementById('invTitle'),
    invConfidenceFill: document.getElementById('invConfidenceFill'),
    invConfidenceVal: document.getElementById('invConfidenceVal'),
    invSummaryText: document.getElementById('invSummaryText'),
    invEvidenceList: document.getElementById('invEvidenceList'),
    invRecommendedActionBox: document.getElementById('invRecommendedActionBox'),
    invRiskLevelBadge: document.getElementById('invRiskLevelBadge'),
    invPolicyRationale: document.getElementById('invPolicyRationale'),
    invActionPerm: document.getElementById('invActionPerm'),
    testLockActionBtn: document.getElementById('testLockActionBtn'),
    testWasherActionBtn: document.getElementById('testWasherActionBtn'),

    // Timeline View
    fullTimelineStream: document.getElementById('fullTimelineStream'),
    refreshTimelineBtn: document.getElementById('refreshTimelineBtn'),

    // History View
    historyTableBody: document.getElementById('historyTableBody'),
    refreshHistoryBtn: document.getElementById('refreshHistoryBtn'),

    // MCP Settings & Diagnostics
    mcpStatusText: document.getElementById('mcpStatusText'),
    statToolsCount: document.getElementById('statToolsCount'),
    statInvocationsCount: document.getElementById('statInvocationsCount'),
    mcpToolsList: document.getElementById('mcpToolsList'),
    settingsActiveScenario: document.getElementById('settingsActiveScenario'),
    reloadCurrentScenarioBtn: document.getElementById('reloadCurrentScenarioBtn'),
    resetHomeStateBtn: document.getElementById('resetHomeStateBtn'),

    // Modal
    jsonInspectorModal: document.getElementById('jsonInspectorModal'),
    modalToolTitle: document.getElementById('modalToolTitle'),
    modalInputJson: document.getElementById('modalInputJson'),
    modalOutputJson: document.getElementById('modalOutputJson'),
    closeModalBtn: document.getElementById('closeModalBtn'),
    closeModalBtn2: document.getElementById('closeModalBtn2'),
  };

  // -------------------------------------------------------------------------
  // Speech Recognition (Web Speech API)
  // -------------------------------------------------------------------------
  function setupSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
      state.recognition = new SpeechRecognition();
      state.recognition.continuous = false;
      state.recognition.interimResults = false;
      state.recognition.lang = 'en-US';

      state.recognition.onstart = () => {
        state.isRecording = true;
        elements.micBtn.classList.add('recording');
        elements.speechIndicatorLabel.textContent = 'Listening... Speak naturally.';
      };

      state.recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        elements.userInputField.value = transcript;
        elements.speechIndicatorLabel.textContent = `Captured: "${transcript}"`;
      };

      state.recognition.onerror = (event) => {
        console.warn('Speech recognition error:', event.error);
        state.isRecording = false;
        elements.micBtn.classList.remove('recording');
        elements.speechIndicatorLabel.textContent = `Voice error: ${event.error}. You can type directly.`;
      };

      state.recognition.onend = () => {
        state.isRecording = false;
        elements.micBtn.classList.remove('recording');
      };
    } else {
      elements.speechIndicatorLabel.textContent = 'Speech dictation: Click prompt chips or type.';
    }
  }

  // -------------------------------------------------------------------------
  // Speech Synthesis (Alexa+-inspired voice playback)
  // -------------------------------------------------------------------------
  function speakText(text) {
    if (!('speechSynthesis' in window)) return;
    window.speechSynthesis.cancel(); // stop any ongoing speech
    const cleanText = text.replace(/<[^>]*>/g, '');
    const utterance = new SpeechSynthesisUtterance(cleanText);
    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    utterance.lang = 'en-US';
    window.speechSynthesis.speak(utterance);
  }

  // -------------------------------------------------------------------------
  // Navigation & View Switching
  // -------------------------------------------------------------------------
  function switchTab(tabId) {
    state.activeTab = tabId;
    elements.tabButtons.forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tabId);
    });
    elements.viewSections.forEach(sec => {
      sec.classList.toggle('active', sec.id === `view-${tabId}`);
    });

    if (tabId === 'devices') fetchHomeState();
    if (tabId === 'timeline') fetchEvents();
    if (tabId === 'history') fetchHistory();
    if (tabId === 'settings') fetchMcpStatus();
  }

  // -------------------------------------------------------------------------
  // API Calls
  // -------------------------------------------------------------------------

  async function fetchHomeState() {
    try {
      const res = await fetch('/api/home-state');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      state.homeState = await res.json();
      renderHomeState();
    } catch (err) {
      console.error('Failed to fetch home state:', err);
    }
  }

  async function fetchEvents() {
    try {
      const res = await fetch('/api/events?limit=50');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      state.events = data.events || [];
      renderTimeline();
    } catch (err) {
      console.error('Failed to fetch events:', err);
    }
  }

  async function fetchHistory() {
    try {
      const res = await fetch('/api/history?limit=50');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      state.history = await res.json();
      renderHistory();
    } catch (err) {
      console.error('Failed to fetch history:', err);
    }
  }

  async function fetchMcpStatus() {
    try {
      const res = await fetch('/api/mcp/status');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      state.mcpStats = await res.json();
      renderMcpStatus();
    } catch (err) {
      console.error('Failed to fetch MCP status:', err);
    }
  }

  async function setScenario(scenarioName) {
    try {
      elements.mcpStatusText.textContent = 'Switching scenario...';
      const res = await fetch('/api/scenario', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario: scenarioName }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      state.currentScenario = scenarioName;
      elements.scenarioSelector.value = scenarioName;

      // Refresh data
      await fetchHomeState();
      await fetchEvents();
      await fetchMcpStatus();

      // Trigger automatic prompt to investigate new scenario
      if (scenarioName === 'security_incident') {
        elements.userInputField.value = 'Something happened at my back door. Should I be worried?';
      } else if (scenarioName === 'water_hazard') {
        elements.userInputField.value = 'Check for water hazards in the laundry room';
      } else if (scenarioName === 'leaving_home') {
        elements.userInputField.value = 'Is the house secure for leaving?';
      } else {
        elements.userInputField.value = "What's happening at home?";
      }

      elements.mcpStatusText.textContent = 'MCP Online (7 Tools)';
    } catch (err) {
      console.error('Failed to set scenario:', err);
      elements.mcpStatusText.textContent = 'Scenario switch error';
    }
  }

  async function sendChatMessage(utterance) {
    if (!utterance || !utterance.trim() || state.isProcessing) return;

    state.isProcessing = true;
    elements.sendBtn.disabled = true;
    elements.userInputField.disabled = true;
    elements.typingIndicator.style.display = 'flex';

    // Append User Message Bubble
    appendMessageBubble('user', utterance.trim());
    elements.userInputField.value = '';

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          utterance: utterance.trim(),
          scenario_hint: state.currentScenario,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${res.status}`);
      }

      const data = await res.json();

      // Update state with investigation findings
      state.currentIncident = data.incident || null;
      state.currentRisk = data.risk || null;
      state.currentRecommendation = data.recommendation || null;
      state.currentEvidence = data.evidence || [];
      if (data.home_state) state.homeState = data.home_state;

      // Render Assistant Response with Progressive Disclosure
      appendMessageBubble('assistant', data.speech, data);

      // Speak text with calm voice
      speakText(data.speech);

      // Update Quick Glance and Investigation Views
      renderGlancePanel(data);
      renderInvestigationView(data);
      fetchMcpStatus();
    } catch (err) {
      console.error('Chat error:', err);
      appendMessageBubble(
        'assistant',
        `I encountered an error communicating with the HomeOps MCP server: ${err.message}. Please verify the Streamable HTTP server is online.`
      );
    } finally {
      state.isProcessing = false;
      elements.sendBtn.disabled = false;
      elements.userInputField.disabled = false;
      elements.typingIndicator.style.display = 'none';
      elements.userInputField.focus();
    }
  }

  async function testActionBoundary(actionName, deviceId = null) {
    try {
      const res = await fetch('/api/execute-action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action_name: actionName, device_id: deviceId }),
      });
      const data = await res.json();

      // Show user in conversation
      appendMessageBubble('user', `Request: Execute physical action "${actionName.replace(/_/g, ' ')}"`);

      const speech = `HomeOps Safety Policy Response: Autonomous execution of '${actionName.replace(/_/g, ' ')}' is strictly BLOCKED. ${data.reason || 'All physical device actions require explicit manual human confirmation in MVP.'}`;
      appendMessageBubble('assistant', speech, {
        safety_block: {
          is_blocked: true,
          action_name: actionName,
          reason: data.reason,
          status: data.status,
          guardrail: 'Deterministic Safety Guardrail: Autonomous Actuation Prohibited',
        },
        tool_calls: [{
          tool: 'execute_safe_action',
          arguments: { action_name: actionName, device_id: deviceId },
          result: data,
          transport: 'Streamable HTTP (mcp 2.2.0)',
          latency_ms: 12.0,
        }],
      });

      speakText(speech);
    } catch (err) {
      console.error('Action boundary test error:', err);
    }
  }

  // -------------------------------------------------------------------------
  // Rendering Helpers
  // -------------------------------------------------------------------------

  function appendMessageBubble(sender, text, meta = null) {
    const turnEl = document.createElement('div');
    turnEl.className = `chat-turn ${sender}`;

    const senderLabel = sender === 'user' ? 'You' : 'HomeOps Assistant';
    const senderIcon = sender === 'user'
      ? '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>'
      : '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polygon points="10 8 16 12 10 16 10 8"></polygon></svg>';

    let innerHtml = `
      <div class="turn-sender">${senderIcon} ${senderLabel}</div>
      <div class="bubble">
        <div class="speech-text">${escapeHtml(text)}</div>
    `;

    // If Assistant message with progressive disclosure payload
    if (sender === 'assistant' && meta) {
      const toolCount = (meta.tool_calls && meta.tool_calls.length) || 0;
      const riskLevel = (meta.risk && meta.risk.risk_level) || (meta.incident && meta.incident.severity) || 'INFO';
      const isBlocked = meta.safety_block && meta.safety_block.is_blocked;

      innerHtml += `
        <div class="bubble-actions-row">
          <button class="speech-synth-btn" title="Listen to response voice">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"></path></svg>
            Speak
          </button>

          <button class="investigation-toggle-btn">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
            <span>View Investigation</span>
            <span class="badge-count">${toolCount} MCP Tools</span>
            <span class="nav-badge" style="background:${getRiskColor(riskLevel)}">${riskLevel}</span>
          </button>
        </div>

        <!-- Expandable Progressive Disclosure Drawer -->
        <div class="inline-investigation-drawer">
          ${meta.incident ? `
            <div style="padding-bottom: 0.5rem; border-bottom: 1px solid var(--border-subtle);">
              <div style="display:flex; justify-content:space-between; align-items:center;">
                <span class="incident-type-tag ${meta.incident.incident_type ? meta.incident.incident_type.toLowerCase() : 'security'}">${meta.incident.incident_type || 'INCIDENT'}</span>
                <span style="font-size:0.78rem; color:var(--text-tertiary);">Confidence: <strong>${Math.round((meta.incident.confidence || 0.8) * 100)}%</strong></span>
              </div>
              <h4 style="margin-top:0.35rem; font-size:0.95rem;">${escapeHtml(meta.incident.title || 'Correlated Incident')}</h4>
              <p style="font-size:0.85rem; color:var(--text-secondary); margin-top:0.2rem;">${escapeHtml(meta.incident.summary || '')}</p>
            </div>
          ` : ''}

          ${meta.evidence && meta.evidence.length > 0 ? `
            <div>
              <div style="font-size:0.75rem; font-weight:600; text-transform:uppercase; color:var(--text-tertiary); margin-bottom:0.35rem;">Correlated Evidence:</div>
              <ul style="list-style:none; display:flex; flex-direction:column; gap:0.25rem;">
                ${meta.evidence.map(e => `<li style="font-size:0.8rem; color:var(--text-secondary); display:flex; gap:0.4rem;"><span style="color:var(--brand-teal);">✓</span> ${escapeHtml(e)}</li>`).join('')}
              </ul>
            </div>
          ` : ''}

          ${isBlocked ? `
            <div class="safety-guardrail-card" style="padding:0.75rem;">
              <div class="safety-header" style="font-size:0.825rem;">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"></line></svg>
                Autonomous Physical Action Blocked by Policy
              </div>
              <div class="safety-body" style="font-size:0.8rem;">
                ${escapeHtml(meta.safety_block.reason || 'Safety guardrail blocks autonomous actuation.')}
              </div>
            </div>
          ` : ''}

          <!-- MCP Tool Invocations List -->
          ${meta.tool_calls && meta.tool_calls.length > 0 ? `
            <div>
              <div style="font-size:0.75rem; font-weight:600; text-transform:uppercase; color:var(--text-tertiary); margin-bottom:0.4rem;">Real Streamable HTTP MCP Invocations:</div>
              <div style="display:flex; flex-direction:column; gap:0.35rem;">
                ${meta.tool_calls.map((t, idx) => `
                  <div class="mcp-tool-pill" style="display:flex; align-items:center; justify-content:space-between; background:var(--bg-surface-subtle); padding:0.35rem 0.65rem; border-radius:var(--radius-sm); font-size:0.78rem;">
                    <span style="font-family:'JetBrains Mono'; font-weight:600; color:var(--brand-teal);">tool: ${escapeHtml(t.tool)}</span>
                    <button class="inspect-tool-btn" data-tool-index="${idx}" style="background:transparent; border:none; color:var(--brand-blue); cursor:pointer; font-size:0.75rem; font-weight:500;">
                      Inspect JSON ↗
                    </button>
                  </div>
                `).join('')}
              </div>
            </div>
          ` : ''}
        </div>
      `;
    }

    innerHtml += '</div>';
    turnEl.innerHTML = innerHtml;

    // Attach event listeners to speech synth and toggle button
    const speakBtn = turnEl.querySelector('.speech-synth-btn');
    if (speakBtn) {
      speakBtn.addEventListener('click', () => speakText(text));
    }

    const toggleBtn = turnEl.querySelector('.investigation-toggle-btn');
    const drawerEl = turnEl.querySelector('.inline-investigation-drawer');
    if (toggleBtn && drawerEl) {
      toggleBtn.addEventListener('click', () => {
        drawerEl.classList.toggle('open');
        toggleBtn.querySelector('span').textContent = drawerEl.classList.contains('open') ? 'Hide Details' : 'View Investigation';
      });
    }

    // Attach inspect buttons
    const inspectBtns = turnEl.querySelectorAll('.inspect-tool-btn');
    inspectBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = parseInt(btn.dataset.toolIndex, 10);
        if (meta && meta.tool_calls && meta.tool_calls[idx]) {
          openJsonInspector(meta.tool_calls[idx]);
        }
      });
    });

    elements.chatThread.appendChild(turnEl);
    elements.chatThread.scrollTop = elements.chatThread.scrollHeight;
  }

  function renderGlancePanel(data) {
    if (!data) return;
    const incident = data.incident;
    const risk = data.risk;

    if (incident) {
      elements.glanceIncidentSummary.textContent = incident.summary || incident.title;
      const confPct = Math.round((incident.confidence || 0.85) * 100);
      elements.glanceConfidenceFill.style.width = `${confPct}%`;
      elements.glanceConfidenceText.textContent = `${confPct}%`;
      const sev = (risk && risk.risk_level) || incident.severity || 'MEDIUM';
      elements.glanceRiskBadge.textContent = `${sev} RISK`;
      elements.glanceRiskBadge.className = `risk-level-badge ${sev}`;
      elements.investigationNavBadge.style.display = 'inline-block';
    } else {
      elements.glanceIncidentSummary.textContent = 'All monitored sensors reporting normal conditions.';
      elements.glanceConfidenceFill.style.width = '0%';
      elements.glanceConfidenceText.textContent = 'N/A';
      elements.glanceRiskBadge.textContent = 'NORMAL';
      elements.glanceRiskBadge.className = 'risk-level-badge LOW';
      elements.investigationNavBadge.style.display = 'none';
    }
  }

  function renderHomeState() {
    if (!state.homeState) return;
    const devices = state.homeState.devices || [];
    const activeConditions = state.homeState.active_conditions || [];

    elements.glanceDeviceCount.textContent = `${devices.length} Monitored`;

    // Render Quick Glance Device List (up to 4)
    elements.glanceDeviceList.innerHTML = devices.slice(0, 4).map(d => {
      const isAnomaly = activeConditions.some(c => c.device_id === d.device_id);
      return `
        <div class="device-mini-item">
          <div class="device-mini-info">
            <span>${getDeviceIcon(d.device_type)}</span>
            <strong>${escapeHtml(formatLocation(d.location))}</strong>
          </div>
          <span class="device-status-badge ${isAnomaly ? 'alert' : 'normal'}">
            ${isAnomaly ? 'Active Alert' : 'Normal'}
          </span>
        </div>
      `;
    }).join('');

    // Render Full Devices Grid
    elements.fullDevicesGrid.innerHTML = devices.map(d => {
      const isAnomaly = activeConditions.some(c => c.device_id === d.device_id);
      const condition = activeConditions.find(c => c.device_id === d.device_id);
      return `
        <div class="device-card ${isAnomaly ? 'anomaly' : ''}">
          <div class="device-header">
            <div class="device-icon-box">
              ${getDeviceIcon(d.device_type)}
            </div>
            <span class="device-status-badge ${isAnomaly ? 'alert' : 'normal'}">
              ${isAnomaly ? 'Alert Detected' : 'Quiet'}
            </span>
          </div>
          <div class="device-details">
            <h4>${escapeHtml(formatDeviceName(d.device_type, d.location))}</h4>
            <div class="device-location">${escapeHtml(formatLocation(d.location))} • <code>${escapeHtml(d.device_id)}</code></div>
          </div>
          <div class="device-readings">
            <span>Status: <strong>${escapeHtml(d.last_event_type || 'idle')}</strong></span>
            <span>Signal: <strong>98%</strong></span>
          </div>
          ${isAnomaly ? `
            <div style="font-size: 0.78rem; color: var(--risk-high); font-weight: 500;">
              ⚠️ Condition: ${escapeHtml(condition.condition.replace(/_/g, ' '))}
            </div>
          ` : ''}
        </div>
      `;
    }).join('');
  }

  function renderTimeline() {
    if (!state.events || state.events.length === 0) {
      elements.fullTimelineStream.innerHTML = '<div style="color:var(--text-tertiary);">No sensor events recorded.</div>';
      return;
    }

    elements.fullTimelineStream.innerHTML = state.events.map(ev => {
      const isCorrelated = ev.location === 'back_door' || ev.event_type === 'moisture_detected' || ev.event_type === 'detected';
      const timeStr = ev.timestamp ? new Date(ev.timestamp).toLocaleTimeString() : 'Recent';
      return `
        <div class="timeline-event-node ${isCorrelated ? 'correlated' : ''}">
          <div class="event-node-header">
            <div class="event-device-badge">
              <span>${getDeviceIcon(ev.device_type)}</span>
              <span>${escapeHtml(formatDeviceName(ev.device_type, ev.location))}</span>
            </div>
            <span class="event-timestamp">${timeStr}</span>
          </div>
          <div class="event-action-desc">
            Sensor event: <strong>${escapeHtml(ev.event_type)}</strong> at <code>${escapeHtml(ev.location)}</code>
            ${ev.metadata && ev.metadata.note ? `<span style="color:var(--text-tertiary); font-size:0.75rem;">(${escapeHtml(ev.metadata.note)})</span>` : ''}
          </div>
        </div>
      `;
    }).join('');
  }

  function renderInvestigationView(data) {
    if (!data) return;
    const incident = data.incident || state.currentIncident;
    const risk = data.risk || state.currentRisk;
    const evidence = (data.evidence && data.evidence.length > 0) ? data.evidence : state.currentEvidence;
    const recommendation = data.recommendation || state.currentRecommendation;

    if (incident) {
      elements.invTypeTag.textContent = `${incident.incident_type} INCIDENT`;
      elements.invTypeTag.className = `incident-type-tag ${incident.incident_type ? incident.incident_type.toLowerCase() : 'security'}`;
      elements.invTitle.textContent = incident.title || 'Correlated Incident';
      const conf = Math.round((incident.confidence || 0.85) * 100);
      elements.invConfidenceFill.style.width = `${conf}%`;
      elements.invConfidenceVal.textContent = `${conf}%`;
      elements.invSummaryText.textContent = incident.summary || 'Incident correlation details.';
      elements.investigationNavBadge.style.display = 'inline-block';
    }

    if (evidence && evidence.length > 0) {
      elements.invEvidenceList.innerHTML = evidence.map(e => `
        <div class="evidence-item">
          <span class="evidence-check-icon">✓</span>
          <span>${escapeHtml(e)}</span>
        </div>
      `).join('');
    }

    if (recommendation) {
      elements.invRecommendedActionBox.textContent =
        recommendation.recommended_action || (incident && incident.recommended_next_step) || 'Review camera feeds.';
    }

    if (risk) {
      elements.invRiskLevelBadge.textContent = `${risk.risk_level} RISK`;
      elements.invRiskLevelBadge.className = `risk-level-badge ${risk.risk_level}`;
      elements.invPolicyRationale.textContent = risk.policy_rationale || 'High-risk incident requires explicit human confirmation.';
      elements.invActionPerm.textContent = (risk.action_permission || 'BLOCKED_UNTIL_EXPLICIT_APPROVAL').toUpperCase();
    }
  }

  function renderHistory() {
    if (!state.history || state.history.length === 0) {
      elements.historyTableBody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding:1.5rem; color:var(--text-tertiary);">No incident records in SQLite history yet.</td></tr>';
      return;
    }

    elements.historyTableBody.innerHTML = state.history.map(row => {
      const created = row.created_at ? new Date(row.created_at).toLocaleString() : 'Just now';
      const conf = Math.round((row.confidence || 0.8) * 100);
      return `
        <tr>
          <td><span style="font-family:'JetBrains Mono'; font-size:0.78rem;">${created}</span></td>
          <td><span class="incident-type-tag ${row.incident_type.toLowerCase()}">${escapeHtml(row.incident_type)}</span></td>
          <td><span class="risk-level-badge ${row.severity}" style="font-size:0.75rem; padding:0.15rem 0.5rem;">${escapeHtml(row.severity)}</span></td>
          <td><strong>${conf}%</strong></td>
          <td><strong>${escapeHtml(row.title)}</strong></td>
          <td><span style="color:#DC2626; font-size:0.78rem; font-weight:600;">Autonomous Actuation Blocked</span></td>
        </tr>
      `;
    }).join('');
  }

  function renderMcpStatus() {
    if (!state.mcpStats) return;
    const server = state.mcpStats.mcp_server || {};
    const stats = state.mcpStats.mcp_client_stats || {};
    const sim = state.mcpStats.simulation || {};

    elements.statToolsCount.textContent = `${server.tools_registered || 7} / 7`;
    elements.statInvocationsCount.textContent = stats.total_tool_calls_executed || 0;
    elements.settingsActiveScenario.textContent = sim.current_scenario || state.currentScenario;

    if (server.tool_names) {
      elements.mcpToolsList.innerHTML = server.tool_names.map(t => `
        <div style="background:var(--bg-surface-subtle); padding:0.4rem 0.65rem; border-radius:var(--radius-sm); font-size:0.8rem; display:flex; justify-content:space-between; align-items:center;">
          <code style="color:var(--brand-teal); font-weight:600;">${escapeHtml(t)}</code>
          <span style="font-size:0.72rem; color:var(--brand-teal); font-weight:500;">Online (Streamable HTTP)</span>
        </div>
      `).join('');
    }
  }

  function openJsonInspector(toolCall) {
    if (!toolCall) return;
    elements.modalToolTitle.textContent = `MCP Tool: ${toolCall.tool} (${toolCall.transport || 'Streamable HTTP'})`;
    elements.modalInputJson.textContent = JSON.stringify(toolCall.arguments || {}, null, 2);
    elements.modalOutputJson.textContent = JSON.stringify(toolCall.result || {}, null, 2);
    elements.jsonInspectorModal.classList.add('open');
  }

  function closeJsonInspector() {
    elements.jsonInspectorModal.classList.remove('open');
  }

  // -------------------------------------------------------------------------
  // Utility formatters
  // -------------------------------------------------------------------------
  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function formatLocation(loc) {
    if (!loc) return 'House';
    return loc.replace(/_/g, ' ');
  }

  function formatDeviceName(devType, loc) {
    const locName = formatLocation(loc);
    const typeName = devType.replace(/_/g, ' ');
    return `${locName.charAt(0).toUpperCase() + locName.slice(1)} ${typeName}`;
  }

  function getDeviceIcon(devType) {
    if (devType.includes('door') || devType.includes('contact')) return '🚪';
    if (devType.includes('motion')) return '🚶';
    if (devType.includes('water') || devType.includes('moisture')) return '💧';
    if (devType.includes('appliance') || devType.includes('washer')) return '🧺';
    if (devType.includes('lock')) return '🔒';
    return '📡';
  }

  function getRiskColor(level) {
    switch (level) {
      case 'CRITICAL': return '#DC2626';
      case 'HIGH': return '#EA580C';
      case 'MEDIUM': return '#D97706';
      case 'LOW': return '#059669';
      default: return '#0D9488';
    }
  }

  // -------------------------------------------------------------------------
  // Event Listeners
  // -------------------------------------------------------------------------

  // Nav Tab clicks
  elements.tabButtons.forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  // Chat Form Submission
  elements.chatComposerForm.addEventListener('submit', (e) => {
    e.preventDefault();
    sendChatMessage(elements.userInputField.value);
  });

  // Prompt Chips clicks
  document.querySelectorAll('.prompt-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const prompt = chip.dataset.prompt;
      elements.userInputField.value = prompt;
      sendChatMessage(prompt);
    });
  });

  // Microphone Affordance Button
  elements.micBtn.addEventListener('click', () => {
    if (!state.recognition) {
      // If Web Speech API not supported in this browser, provide friendly voice phrase prompt
      elements.userInputField.value = 'Something happened at my back door. Should I be worried?';
      elements.speechIndicatorLabel.textContent = 'Voice phrase inserted. Press Enter or Send.';
      elements.userInputField.focus();
      return;
    }

    if (state.isRecording) {
      state.recognition.stop();
    } else {
      try {
        state.recognition.start();
      } catch (err) {
        console.warn('Speech start error:', err);
      }
    }
  });

  // Scenario Selector Change
  elements.scenarioSelector.addEventListener('change', (e) => {
    setScenario(e.target.value);
  });

  // Quick Action View Buttons
  elements.quickViewInvestigationBtn.addEventListener('click', () => switchTab('investigation'));
  elements.quickViewDevicesBtn.addEventListener('click', () => switchTab('devices'));

  // Refresh Buttons
  elements.refreshDevicesBtn.addEventListener('click', fetchHomeState);
  elements.refreshTimelineBtn.addEventListener('click', fetchEvents);
  elements.refreshHistoryBtn.addEventListener('click', fetchHistory);

  // Settings Buttons
  elements.reloadCurrentScenarioBtn.addEventListener('click', () => setScenario(state.currentScenario));
  elements.resetHomeStateBtn.addEventListener('click', () => setScenario('clear'));

  // Physical Action Safety Tests
  elements.testLockActionBtn.addEventListener('click', () => testActionBoundary('lock_door', 'door-back-01'));
  elements.testWasherActionBtn.addEventListener('click', () => testActionBoundary('turn_off_configured_appliance', 'washer-01'));

  // Modal Close
  elements.closeModalBtn.addEventListener('click', closeJsonInspector);
  elements.closeModalBtn2.addEventListener('click', closeJsonInspector);
  elements.jsonInspectorModal.addEventListener('click', (e) => {
    if (e.target === elements.jsonInspectorModal) closeJsonInspector();
  });

  // Automated Demo Walkthrough
  const runDemoBtn = document.getElementById('runDemoBtn');
  if (runDemoBtn) {
    runDemoBtn.addEventListener('click', async () => {
      if (state.isProcessing) return;
      runDemoBtn.disabled = true;
      runDemoBtn.innerHTML = '<span>Running Demo...</span>';

      // 1. Ensure security_incident scenario is active
      await setScenario('security_incident');
      switchTab('chat');

      // Step 1: Inquire about the back door
      await sendChatMessage("Something happened at my back door. Should I be worried?");

      // Step 2: Attempt physical device action
      await new Promise(r => setTimeout(r, 1200));
      await sendChatMessage("Lock the back door");

      // Step 3: Check incident history
      await new Promise(r => setTimeout(r, 1200));
      await sendChatMessage("Has this happened before?");

      runDemoBtn.disabled = false;
      runDemoBtn.innerHTML = `
        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
        <span>Run Demo</span>
      `;
    });
  }

  // -------------------------------------------------------------------------
  // Initialization
  // -------------------------------------------------------------------------
  setupSpeechRecognition();
  fetchHomeState();
  fetchEvents();
  fetchHistory();
  fetchMcpStatus();
});
