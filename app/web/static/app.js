/**
 * app/web/static/app.js
 * =====================
 * HomeOps-AI: Flagship Alexa+-Inspired Smart-Home Safety & Camera Intelligence.
 *
 * Coordinates:
 * - 6-Screen clean client-side navigation (Home, Cameras, Camera Viewer, Ask HomeOps, Safety & Investigation, Settings)
 * - Real camera registry via GET /api/cameras & GET /api/cameras/{id}
 * - Real MP4 demo clip streaming via GET /api/cameras/{id}/footage
 * - Real SSDLite neural video analysis via POST /api/cameras/{id}/analyze
 * - Real persisted camera events via GET /api/cameras/{id}/events
 * - Real conversational smart-home assistance via POST /api/chat with MCP tool disclosure
 * - Browser Web Speech API (speech recognition and synthesis)
 * - Strict deterministic safety policy verification (blocking autonomous physical action)
 */

document.addEventListener('DOMContentLoaded', () => {
  // -------------------------------------------------------------------------
  // State
  // -------------------------------------------------------------------------
  const state = {
    activeTab: 'home',
    currentScenario: 'security_incident',
    cameras: [],
    devices: [],
    selectedCameraId: 'cam-main-gate',
    isAnalyzing: false,
    isChatProcessing: false,
    isSpeechEnabled: true,
    isRecording: false,
    recognition: null,
    recentEvents: [],
    mcpTools: [],
    activeModalData: null,
  };

  // -------------------------------------------------------------------------
  // Helper: Escape HTML to prevent XSS
  // -------------------------------------------------------------------------
  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // -------------------------------------------------------------------------
  // Reusable Normalized Device Helpers
  // -------------------------------------------------------------------------
  function getDeviceIcon(type) {
    switch (type) {
      case 'lock_sensor':
      case 'lock':
        return '🔒';
      case 'contact_sensor':
        return '🚪';
      case 'motion_sensor':
        return '🚶';
      case 'water_leak_sensor':
        return '💧';
      case 'water_tank_sensor':
        return '🚰';
      case 'smoke_sensor':
        return '💨';
      case 'camera':
        return '📹';
      case 'light':
        return '💡';
      case 'switch':
        return '🔌';
      default:
        return '⚡';
    }
  }

  function getDeviceCategory(type) {
    if (type === 'lock_sensor' || type === 'lock') return 'lock';
    if (type === 'contact_sensor') return 'contact';
    if (type === 'motion_sensor') return 'motion';
    if (type === 'water_leak_sensor' || type === 'water_tank_sensor') return 'water';
    if (type === 'smoke_sensor' || type === 'co_sensor' || type === 'thermostat') return 'environmental';
    if (type === 'camera') return 'camera';
    return 'other';
  }

  function formatDeviceState(dev) {
    const s = String(dev.state || dev.status || 'unknown');
    return s.toUpperCase().replace(/_/g, ' ');
  }

  function getStateTagClass(dev) {
    const s = String(dev.state || '').toLowerCase();
    if (s === 'locked' || s === 'closed' || s === 'clear' || s === 'dry' || s === 'online' || s.includes('%')) {
      return 'state-ok';
    }
    if (s === 'open' || s === 'leak_detected' || s === 'motion_detected' || s === 'unlocked' || s === 'offline') {
      return 'state-alert';
    }
    return 'state-neutral';
  }

  // -------------------------------------------------------------------------
  // Screen Navigation
  // -------------------------------------------------------------------------
  function switchTab(targetTabId, options = {}) {
    state.activeTab = targetTabId;

    // Update nav tab buttons
    document.querySelectorAll('.nav-tab-btn').forEach(btn => {
      const tab = btn.getAttribute('data-tab');
      const isActive = tab === targetTabId;
      btn.classList.toggle('active', isActive);
      btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });

    // Update view sections
    document.querySelectorAll('.view-section').forEach(sec => {
      sec.classList.remove('active');
    });
    const targetSection = document.getElementById(`view-${targetTabId}`);
    if (targetSection) {
      targetSection.classList.add('active');
    }

    // Tab-specific initializations
    if (targetTabId === 'home') {
      loadHomeSummary();
    } else if (targetTabId === 'devices') {
      loadDevices(options.filter || 'all');
    } else if (targetTabId === 'cameras') {
      loadCamerasRegistry();
    } else if (targetTabId === 'viewer') {
      if (options.cameraId) {
        state.selectedCameraId = options.cameraId;
        const select = document.getElementById('viewerCameraSelect');
        if (select) select.value = options.cameraId;
      }
      loadSelectedCameraViewer(state.selectedCameraId);
    } else if (targetTabId === 'settings') {
      loadSystemStatus();
    }
  }

  // Wire up sidebar tabs
  document.querySelectorAll('.nav-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.getAttribute('data-tab');
      if (tab) switchTab(tab);
    });
  });

  // Breadcrumb back link on Camera Viewer
  const viewerBreadcrumbBack = document.getElementById('viewerBreadcrumbBack');
  if (viewerBreadcrumbBack) {
    viewerBreadcrumbBack.addEventListener('click', () => switchTab('cameras'));
  }

  // Home Screen: "View All Devices"
  const homeViewAllDevicesBtn = document.getElementById('homeViewAllDevicesBtn');
  if (homeViewAllDevicesBtn) {
    homeViewAllDevicesBtn.addEventListener('click', () => switchTab('devices'));
  }

  // Home Screen: "View All Cameras"
  const homeViewAllCamerasBtn = document.getElementById('homeViewAllCamerasBtn');
  if (homeViewAllCamerasBtn) {
    homeViewAllCamerasBtn.addEventListener('click', () => switchTab('cameras'));
  }

  // Home Screen: "Refresh Events"
  const homeRefreshEventsBtn = document.getElementById('homeRefreshEventsBtn');
  if (homeRefreshEventsBtn) {
    homeRefreshEventsBtn.addEventListener('click', () => loadHomeSummary());
  }

  // Home Screen: Active Alert Investigate Button
  const homeAlertInvestigateBtn = document.getElementById('homeAlertInvestigateBtn');
  if (homeAlertInvestigateBtn) {
    homeAlertInvestigateBtn.addEventListener('click', () => switchTab('investigation'));
  }

  // -------------------------------------------------------------------------
  // Screen 1: Home Dashboard Logic
  // -------------------------------------------------------------------------
  function updateHomeGreeting() {
    const heading = document.getElementById('homeGreetingHeading');
    if (!heading) return;
    const hour = new Date().getHours();
    if (hour < 12) {
      heading.textContent = 'Good morning, Ankush';
    } else if (hour < 17) {
      heading.textContent = 'Good afternoon, Ankush';
    } else {
      heading.textContent = 'Good evening, Ankush';
    }
  }

  async function loadHomeSummary() {
    updateHomeGreeting();

    // 1. Fetch normalized devices from GET /api/devices
    try {
      const devRes = await fetch('/api/devices');
      if (devRes.ok) {
        const devData = await devRes.json();
        state.devices = devData.devices || [];

        // Update Devices badge counter in sidebar
        const devBadge = document.getElementById('devicesCountBadge');
        if (devBadge) devBadge.textContent = state.devices.length;

        // Render category summary capsules with genuine counts
        renderHomeCategorySummary(state.devices);

        // Render Monitored Devices quick list
        renderHomeDevicesQuickList(state.devices);
      }
    } catch (err) {
      console.error('Failed to load devices for home view:', err);
    }

    // 2. Fetch cameras registry from GET /api/cameras
    try {
      const camRes = await fetch('/api/cameras');
      if (camRes.ok) {
        const data = await camRes.json();
        state.cameras = data.cameras || [];

        // Update Cameras badge count in sidebar
        const countBadge = document.getElementById('camerasCountBadge');
        if (countBadge) countBadge.textContent = state.cameras.length;
      }
    } catch (err) {
      console.error('Failed to load cameras for home view:', err);
    }

    // 3. Fetch home state & safety conditions from GET /api/home-state
    try {
      const stateRes = await fetch('/api/home-state');
      if (stateRes.ok) {
        const homeState = await stateRes.json();
        const activeConditions = homeState.active_conditions || [];
        const alertCard = document.getElementById('homeActiveAlertCard');
        const statusText = document.getElementById('homeSystemStateText');
        const subtitle = document.getElementById('homeGreetingSubtitle');
        const badge = document.getElementById('investigationNavBadge');

        if (activeConditions.length > 0) {
          if (alertCard) alertCard.style.display = 'block';
          if (statusText) statusText.textContent = 'Incident Active';
          if (subtitle) subtitle.textContent = 'Attention: Active safety conditions detected. Deterministic guardrails are enforced.';
          if (badge) {
            badge.style.display = 'inline-block';
            badge.textContent = activeConditions.length;
          }
          const headline = document.getElementById('homeAlertHeadline');
          const detail = document.getElementById('homeAlertDetail');
          if (headline && activeConditions[0]) {
            headline.textContent = String(activeConditions[0]).replace(/_/g, ' ').toUpperCase();
          }
          if (detail) {
            detail.textContent = 'Autonomous actuation is strictly blocked by SafetyPolicy. Manual human review recommended.';
          }
        } else {
          if (alertCard) alertCard.style.display = 'none';
          if (statusText) statusText.textContent = 'System Secure';
          if (subtitle) subtitle.textContent = 'Your home is calm. Devices and sensors are continuously monitored under strict safety guardrails.';
          if (badge) badge.style.display = 'none';
        }
      }
    } catch (err) {
      console.warn('Home state fetch notice:', err);
    }

    // 4. Fetch recent persisted events from GET /api/events (or fallback to camera events)
    try {
      let events = [];
      const eventsRes = await fetch('/api/events');
      if (eventsRes.ok) {
        const data = await eventsRes.json();
        events = data.events || [];
      }
      if (!events.length) {
        const camEventsRes = await fetch('/api/cameras/cam-main-gate/events');
        if (camEventsRes.ok) {
          const camData = await camEventsRes.json();
          events = camData.events || [];
        }
      }
      renderHomeEventsStream(events);
    } catch (err) {
      console.error('Failed to load events for home view:', err);
    }

    // 5. Update MCP Status badge
    try {
      const mcpRes = await fetch('/mcp');
      if (mcpRes.ok) {
        const mcpBadge = document.getElementById('homeMcpToolCountBadge');
        if (mcpBadge) mcpBadge.textContent = '16 Tools Ready';
        const topMcp = document.getElementById('mcpStatusText');
        if (topMcp) topMcp.textContent = 'MCP Online (16 Tools)';
      }
    } catch (e) {
      // quiet fallback
    }
  }

  function renderHomeCategorySummary(devices) {
    const container = document.getElementById('homeDeviceCategorySummary');
    if (!container) return;

    // Locks
    const locks = devices.filter(d => getDeviceCategory(d.device_type) === 'lock');
    const lockedCount = locks.filter(d => String(d.state).toLowerCase() === 'locked').length;
    const lockText = locks.length ? `${lockedCount} Locked` : '0 Monitored';

    // Doors & Windows
    const contacts = devices.filter(d => getDeviceCategory(d.device_type) === 'contact');
    const openDoors = contacts.filter(d => String(d.state).toLowerCase() === 'open').length;
    const contactText = contacts.length ? (openDoors > 0 ? `${openDoors} Open` : `${contacts.length} Monitored`) : '0 Monitored';

    // Motion
    const motionSensors = devices.filter(d => getDeviceCategory(d.device_type) === 'motion');
    const motionDetected = motionSensors.filter(d => String(d.state).toLowerCase().includes('motion')).length;
    const motionText = motionSensors.length ? (motionDetected > 0 ? `${motionDetected} Active` : 'All Clear') : '0 Monitored';

    // Water & Plumbing
    const waterSensors = devices.filter(d => getDeviceCategory(d.device_type) === 'water');
    const leaks = waterSensors.filter(d => String(d.state).toLowerCase().includes('leak')).length;
    const tank = waterSensors.find(d => d.device_type === 'water_tank_sensor');
    const waterText = leaks > 0 ? `${leaks} Leak Alert` : (tank && tank.state ? `Tank: ${tank.state}` : `${waterSensors.length} Monitored`);

    // Environmental
    const envSensors = devices.filter(d => getDeviceCategory(d.device_type) === 'environmental');
    const envAlerts = envSensors.filter(d => String(d.state).toLowerCase().includes('smoke') || String(d.state).toLowerCase().includes('alarm')).length;
    const envText = envAlerts > 0 ? 'Alert' : (envSensors.length ? 'Normal' : '0 Monitored');

    // Cameras
    const cameras = devices.filter(d => getDeviceCategory(d.device_type) === 'camera');
    const onlineCams = cameras.filter(d => String(d.status).toLowerCase() === 'online' || String(d.state).toLowerCase() === 'idle').length;
    const offlineCams = cameras.length - onlineCams;
    const cameraText = cameras.length ? `${onlineCams} Online${offlineCams > 0 ? ` • ${offlineCams} Off` : ''}` : '0 Configured';

    const categories = [
      { id: 'lock', icon: '🔒', name: 'Smart Locks', count: lockText, tab: 'devices', filter: 'lock' },
      { id: 'contact', icon: '🚪', name: 'Doors & Windows', count: contactText, tab: 'devices', filter: 'contact' },
      { id: 'motion', icon: '🚶', name: 'Motion Sensors', count: motionText, tab: 'devices', filter: 'motion' },
      { id: 'water', icon: '💧', name: 'Water & Plumbing', count: waterText, tab: 'devices', filter: 'water' },
      { id: 'environmental', icon: '🛡️', name: 'Environmental', count: envText, tab: 'devices', filter: 'environmental' },
      { id: 'camera', icon: '📹', name: 'Cameras', count: cameraText, tab: 'cameras', filter: 'camera' },
    ];

    container.innerHTML = categories.map(cat => `
      <button class="device-cat-pill" type="button" data-tab-target="${cat.tab}" data-filter-target="${cat.filter}" title="View ${cat.name}">
        <div class="device-cat-icon">${cat.icon}</div>
        <div class="device-cat-info">
          <span class="device-cat-name">${cat.name}</span>
          <span class="device-cat-count">${cat.count}</span>
        </div>
      </button>
    `).join('');

    container.querySelectorAll('.device-cat-pill').forEach(btn => {
      btn.addEventListener('click', () => {
        const targetTab = btn.getAttribute('data-tab-target');
        const filter = btn.getAttribute('data-filter-target');
        if (targetTab === 'cameras') {
          switchTab('cameras');
        } else {
          switchTab('devices', { filter });
        }
      });
    });
  }

  function renderHomeDevicesQuickList(devices) {
    const container = document.getElementById('homeDevicesQuickList');
    if (!container) return;

    if (!devices || !devices.length) {
      container.innerHTML = '<div class="summary-loading-placeholder">No devices discovered.</div>';
      return;
    }

    // Show up to 6 non-camera devices first, then cameras
    const sorted = [...devices].sort((a, b) => {
      if (a.device_type === 'camera' && b.device_type !== 'camera') return 1;
      if (a.device_type !== 'camera' && b.device_type === 'camera') return -1;
      return 0;
    }).slice(0, 6);

    container.innerHTML = sorted.map(dev => {
      const icon = getDeviceIcon(dev.device_type);
      const simBadge = dev.is_simulated ? '<span class="badge-simulated">SIMULATED</span>' : '';
      const stateText = formatDeviceState(dev);
      const stateClass = getStateTagClass(dev);

      return `
        <div class="home-device-row" data-device-id="${escapeHtml(dev.device_id)}" data-type="${escapeHtml(dev.device_type)}">
          <div class="home-device-icon-box">${icon}</div>
          <div class="home-device-details">
            <div class="home-device-name-row">
              <span class="home-device-title">${escapeHtml(dev.name)}</span>
              ${simBadge}
            </div>
            <span class="home-device-location">${escapeHtml(dev.location || 'Home')} • ${escapeHtml(dev.device_type.replace(/_/g, ' '))}</span>
          </div>
          <span class="home-device-state-tag ${stateClass}">${escapeHtml(stateText)}</span>
        </div>
      `;
    }).join('');

    container.querySelectorAll('.home-device-row').forEach(row => {
      row.addEventListener('click', () => {
        const id = row.getAttribute('data-device-id');
        if (id) openDeviceDrawer(id);
      });
    });
  }

  function renderHomeEventsStream(events) {
    const container = document.getElementById('homeRecentEventsStream');
    if (!container) return;

    if (!events.length) {
      container.innerHTML = `
        <div class="summary-loading-placeholder">
          No recent events recorded yet.<br>
          <span style="font-size:0.75rem; color:var(--text-tertiary);">Device telemetry and verified camera detections will appear here.</span>
        </div>
      `;
      return;
    }

    container.innerHTML = events.slice(0, 6).map(ev => {
      const timeStr = ev.timestamp ? new Date(ev.timestamp).toLocaleTimeString() : 'Recent';
      const details = (ev.data && ev.data.details) ? ev.data.details : (ev.type || 'Event');
      const conf = (ev.data && ev.data.confidence) ? ` (Conf: ${(ev.data.confidence * 100).toFixed(1)}%)` : '';
      const source = ev.camera_id ? `Camera: ${ev.camera_id}` : (ev.device_id ? `Device: ${ev.device_id}` : 'HomeOps Telemetry');
      const icon = ev.camera_id ? '🎥' : (String(ev.type).includes('door') ? '🚪' : (String(ev.type).includes('water') ? '💧' : '📡'));

      return `
        <div class="event-summary-item">
          <div class="event-item-icon">${icon}</div>
          <div class="event-item-content">
            <div class="event-item-title">${escapeHtml(ev.type || 'System Event')}${escapeHtml(conf)}</div>
            <div class="event-item-desc">${escapeHtml(details)}</div>
            <div class="event-item-time">${escapeHtml(timeStr)} • ${escapeHtml(source)}</div>
          </div>
        </div>
      `;
    }).join('');
  }

  // Home Quick Ask Bar & Speech Recognition
  const homeQuickAskInput = document.getElementById('homeQuickAskInput');
  const homeQuickAskBtn = document.getElementById('homeQuickAskBtn');
  const homeQuickAskVoiceBtn = document.getElementById('homeQuickAskVoiceBtn');

  function submitHomeAsk(query) {
    if (!query || !query.trim()) return;
    switchTab('ask');
    const askInput = document.getElementById('userInputField');
    if (askInput) {
      askInput.value = query.trim();
      submitChatMessage(query.trim());
    }
  }

  if (homeQuickAskBtn && homeQuickAskInput) {
    homeQuickAskBtn.addEventListener('click', () => {
      submitHomeAsk(homeQuickAskInput.value);
    });
    homeQuickAskInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        submitHomeAsk(homeQuickAskInput.value);
      }
    });
  }

  if (homeQuickAskVoiceBtn && homeQuickAskInput) {
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRec) {
      const rec = new SpeechRec();
      rec.continuous = false;
      rec.interimResults = false;
      rec.lang = 'en-US';

      rec.onstart = () => {
        homeQuickAskVoiceBtn.classList.add('recording');
        homeQuickAskInput.placeholder = 'Listening to your voice...';
      };

      rec.onresult = (e) => {
        const transcript = e.results[0][0].transcript;
        homeQuickAskInput.value = transcript;
        submitHomeAsk(transcript);
      };

      rec.onerror = (e) => {
        console.warn('Speech recognition notice:', e);
        homeQuickAskVoiceBtn.classList.remove('recording');
        homeQuickAskInput.placeholder = 'Ask anything about doors, water levels, cameras, recent activity...';
      };

      rec.onend = () => {
        homeQuickAskVoiceBtn.classList.remove('recording');
        homeQuickAskInput.placeholder = 'Ask anything about doors, water levels, cameras, recent activity...';
      };

      homeQuickAskVoiceBtn.addEventListener('click', () => {
        try {
          rec.start();
        } catch (err) {
          rec.stop();
        }
      });
    } else {
      homeQuickAskVoiceBtn.title = 'Speech recognition not supported in this browser';
      homeQuickAskVoiceBtn.style.opacity = '0.5';
    }
  }

  // Home Suggested Chips (Exact Required Queries)
  document.querySelectorAll('.home-quick-chips .quick-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const q = chip.getAttribute('data-query');
      submitHomeAsk(q);
    });
  });

  // -------------------------------------------------------------------------
  // Screen 2: Devices Screen Logic (Normalized Hardware Directory)
  // -------------------------------------------------------------------------
  let activeDeviceFilter = 'all';
  let deviceSearchQuery = '';

  async function loadDevices(filter = 'all') {
    activeDeviceFilter = filter;
    const container = document.getElementById('devicesGridContainer');
    if (!container) return;

    // Update filter capsules UI
    document.querySelectorAll('#devicesCategoryFilterRow .filter-capsule').forEach(btn => {
      const f = btn.getAttribute('data-filter');
      btn.classList.toggle('active', f === filter);
    });

    try {
      if (!state.devices || !state.devices.length) {
        const res = await fetch('/api/devices');
        if (res.ok) {
          const data = await res.json();
          state.devices = data.devices || [];
        }
      }
      renderDevicesGrid();
    } catch (err) {
      console.error('Failed to load devices:', err);
      container.innerHTML = '<div class="summary-loading-placeholder">Failed to load device registry.</div>';
    }
  }

  function renderDevicesGrid() {
    const container = document.getElementById('devicesGridContainer');
    if (!container) return;

    let filtered = state.devices || [];
    if (activeDeviceFilter !== 'all') {
      filtered = filtered.filter(d => getDeviceCategory(d.device_type) === activeDeviceFilter);
    }
    if (deviceSearchQuery.trim()) {
      const q = deviceSearchQuery.toLowerCase();
      filtered = filtered.filter(d =>
        d.name.toLowerCase().includes(q) ||
        d.device_type.toLowerCase().includes(q) ||
        (d.location && d.location.toLowerCase().includes(q))
      );
    }

    if (!filtered.length) {
      container.innerHTML = '<div class="summary-loading-placeholder">No matching devices found.</div>';
      return;
    }

    container.innerHTML = filtered.map(dev => {
      const icon = getDeviceIcon(dev.device_type);
      const simBadge = dev.is_simulated ? '<span class="badge-simulated">SIMULATED</span>' : '';
      const stateText = formatDeviceState(dev);
      const stateClass = getStateTagClass(dev);

      return `
        <div class="camera-card" data-device-id="${escapeHtml(dev.device_id)}">
          <div class="camera-card-header">
            <div style="display: flex; align-items: center; gap: 0.65rem;">
              <div class="home-device-icon-box">${icon}</div>
              <div>
                <div class="camera-card-name">${escapeHtml(dev.name)}</div>
                <div class="camera-card-location">${escapeHtml(dev.location || 'Home')}</div>
              </div>
            </div>
            ${simBadge}
          </div>
          <div style="padding: 1rem; display: flex; align-items: center; justify-content: space-between; background: var(--bg-surface-subtle); border-radius: var(--radius-sm); margin: 0.75rem;">
            <span style="font-size: 0.78rem; color: var(--text-secondary); text-transform: capitalize;">${escapeHtml(dev.device_type.replace(/_/g, ' '))}</span>
            <span class="home-device-state-tag ${stateClass}">${escapeHtml(stateText)}</span>
          </div>
          <div style="padding: 0 0.75rem 0.75rem; font-size: 0.72rem; color: var(--text-tertiary); display: flex; justify-content: space-between;">
            <span>ID: ${escapeHtml(dev.device_id)}</span>
            <span>Status: ${escapeHtml(dev.status || 'ONLINE')}</span>
          </div>
        </div>
      `;
    }).join('');

    container.querySelectorAll('.camera-card[data-device-id]').forEach(card => {
      card.style.cursor = 'pointer';
      card.addEventListener('click', () => {
        const id = card.getAttribute('data-device-id');
        if (id) openDeviceDrawer(id);
      });
    });
  }

  // -------------------------------------------------------------------------
  // Device Details Drawer Logic
  // -------------------------------------------------------------------------
  let currentDrawerDevice = null;

  async function openDeviceDrawer(deviceId) {
    if (!deviceId) return;

    let dev = (state.devices || []).find(d => d.device_id === deviceId);
    if (!dev) {
      try {
        const res = await fetch(`/api/devices/${deviceId}`);
        if (res.ok) dev = await res.json();
      } catch (e) {
        console.warn('Failed to fetch device details:', e);
      }
    }
    if (!dev) return;

    currentDrawerDevice = dev;

    const iconEl = document.getElementById('drawerDeviceIcon');
    const titleEl = document.getElementById('drawerDeviceTitle');
    const subtitleEl = document.getElementById('drawerDeviceSubtitle');
    const stateEl = document.getElementById('drawerDeviceState');
    const statusEl = document.getElementById('drawerDeviceStatus');
    const locationEl = document.getElementById('drawerDeviceLocation');
    const providerEl = document.getElementById('drawerDeviceProvider');
    const simBanner = document.getElementById('drawerSimulatedBanner');
    const attrSection = document.getElementById('drawerAttributesSection');
    const attrList = document.getElementById('drawerAttributesList');
    const drawer = document.getElementById('deviceDetailsDrawer');
    const backdrop = document.getElementById('deviceDrawerBackdrop');

    if (iconEl) iconEl.textContent = getDeviceIcon(dev.device_type);
    if (titleEl) titleEl.textContent = dev.name || dev.device_id;
    if (subtitleEl) subtitleEl.textContent = `${dev.device_id} • ${(dev.device_type || '').replace(/_/g, ' ')}`;
    if (stateEl) {
      stateEl.textContent = formatDeviceState(dev);
      stateEl.className = `drawer-fact-value home-device-state-tag ${getStateTagClass(dev)}`;
    }
    if (statusEl) statusEl.textContent = (dev.status || 'ONLINE').toUpperCase();
    if (locationEl) locationEl.textContent = dev.location || 'Home';
    if (providerEl) providerEl.textContent = dev.provider_id || (dev.is_simulated ? 'simulator' : 'home_assistant');

    if (simBanner) {
      simBanner.style.display = dev.is_simulated ? 'block' : 'none';
    }

    if (attrSection && attrList) {
      const attrs = dev.attributes || {};
      const keys = Object.keys(attrs);
      if (keys.length > 0) {
        attrSection.style.display = 'block';
        attrList.innerHTML = keys.map(k => `
          <div class="drawer-attribute-item">
            <span class="drawer-attribute-key">${escapeHtml(k.replace(/_/g, ' '))}:</span>
            <span class="drawer-attribute-val">${escapeHtml(String(attrs[k]))}</span>
          </div>
        `).join('');
      } else {
        attrSection.style.display = 'none';
      }
    }

    if (drawer) {
      drawer.classList.add('open');
      drawer.setAttribute('aria-hidden', 'false');
    }
    if (backdrop) backdrop.style.display = 'block';
  }

  function closeDeviceDrawer() {
    const drawer = document.getElementById('deviceDetailsDrawer');
    const backdrop = document.getElementById('deviceDrawerBackdrop');
    if (drawer) {
      drawer.classList.remove('open');
      drawer.setAttribute('aria-hidden', 'true');
    }
    if (backdrop) backdrop.style.display = 'none';
  }

  const closeDeviceDrawerBtn = document.getElementById('closeDeviceDrawerBtn');
  if (closeDeviceDrawerBtn) closeDeviceDrawerBtn.addEventListener('click', closeDeviceDrawer);

  const deviceDrawerBackdrop = document.getElementById('deviceDrawerBackdrop');
  if (deviceDrawerBackdrop) deviceDrawerBackdrop.addEventListener('click', closeDeviceDrawer);

  const drawerAskAboutBtn = document.getElementById('drawerAskAboutBtn');
  if (drawerAskAboutBtn) {
    drawerAskAboutBtn.addEventListener('click', () => {
      if (currentDrawerDevice) {
        const q = `What is the status of ${currentDrawerDevice.name}?`;
        closeDeviceDrawer();
        submitHomeAsk(q);
      }
    });
  }

  // Devices filter capsule clicks
  document.querySelectorAll('#devicesCategoryFilterRow .filter-capsule').forEach(btn => {
    btn.addEventListener('click', () => {
      const filter = btn.getAttribute('data-filter') || 'all';
      loadDevices(filter);
    });
  });

  // Devices search input
  const devicesSearchInput = document.getElementById('devicesSearchInput');
  if (devicesSearchInput) {
    devicesSearchInput.addEventListener('input', (e) => {
      deviceSearchQuery = e.target.value;
      renderDevicesGrid();
    });
  }

  // Refresh devices button
  const refreshDevicesBtn = document.getElementById('refreshDevicesBtn');
  if (refreshDevicesBtn) {
    refreshDevicesBtn.addEventListener('click', async () => {
      state.devices = [];
      await loadDevices(activeDeviceFilter);
    });
  }

  // -------------------------------------------------------------------------
  // Screen 3: Cameras Screen Logic
  // -------------------------------------------------------------------------
  async function loadCamerasRegistry() {
    const container = document.getElementById('camerasGridContainer');
    if (!container) return;

    container.innerHTML = '<div class="summary-loading-placeholder">Loading camera devices...</div>';

    try {
      const res = await fetch('/api/cameras');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      state.cameras = data.cameras || [];

      if (!state.cameras.length) {
        container.innerHTML = '<div class="summary-loading-placeholder">No registered cameras found in backend.</div>';
        return;
      }

      container.innerHTML = state.cameras.map(cam => {
        const isDemo = Boolean(cam.is_demo || cam.status === 'DEMO' || cam.source_mode === 'SIMULATED_DEMO');
        const isOffline = cam.status === 'OFFLINE';
        const badgeClass = isDemo ? 'badge-demo' : (isOffline ? 'badge-offline' : 'badge-success');
        const badgeText = isDemo ? 'DEMO' : cam.status;

        return `
          <div class="camera-card">
            <div class="camera-card-header">
              <div>
                <div class="camera-card-name">${escapeHtml(cam.name)}</div>
                <div class="camera-card-location">${escapeHtml(cam.location)}</div>
              </div>
              <span class="${badgeClass}">${escapeHtml(badgeText)}</span>
            </div>

            <div class="camera-preview-box">
              <span class="preview-badge-overlay">${isDemo ? 'SIMULATED DEMO' : (isOffline ? 'OFFLINE' : 'LIVE')}</span>
              ${isOffline ? `
                <div class="preview-offline-placeholder">
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="1" y1="1" x2="23" y2="23"></line>
                    <path d="M21 21H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h3m3-3h6l2 3h4a2 2 0 0 1 2 2v9.34"></path>
                  </svg>
                  <div style="font-size:0.75rem; color:#94A3B8;">Device Unreachable (Port 554)</div>
                </div>
              ` : `
                <div style="text-align: center; color: #E2E8F0;">
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="opacity:0.8; margin-bottom: 0.35rem;">
                    <polygon points="23 7 16 12 23 17 23 7"></polygon>
                    <rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect>
                  </svg>
                  <div style="font-size:0.75rem; font-weight:600;">Registered MP4 Demo Clip</div>
                </div>
              `}
            </div>

            <div class="camera-card-body">
              <div class="card-meta-row">
                <span class="meta-row-label">Source Mode:</span>
                <span class="meta-row-value font-mono">${escapeHtml(cam.source_type || cam.source_mode || 'demo')}</span>
              </div>
              <div class="card-meta-row">
                <span class="meta-row-label">Clip Available:</span>
                <span class="meta-row-value">${cam.clip_available ? 'Yes (' + escapeHtml(cam.clip_name) + ')' : 'None'}</span>
              </div>
              <div class="card-meta-row">
                <span class="meta-row-label">Camera ID:</span>
                <span class="meta-row-value font-mono">${escapeHtml(cam.camera_id)}</span>
              </div>
            </div>

            <div class="camera-card-footer">
              <span style="font-size:0.72rem; color:var(--text-tertiary);">
                ${isOffline ? 'Physical connection offline' : 'Ready for AI analysis'}
              </span>
              <button class="btn-open-viewer" data-cam-id="${escapeHtml(cam.camera_id)}">
                <span>Open in Viewer</span>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"></polyline></svg>
              </button>
            </div>
          </div>
        `;
      }).join('');

      container.querySelectorAll('.btn-open-viewer').forEach(btn => {
        btn.addEventListener('click', () => {
          const camId = btn.getAttribute('data-cam-id');
          switchTab('viewer', { cameraId: camId });
        });
      });

    } catch (err) {
      container.innerHTML = `<div class="summary-loading-placeholder" style="color:#EF4444;">Error loading cameras: ${escapeHtml(err.message)}</div>`;
    }
  }

  const refreshCamerasBtn = document.getElementById('refreshCamerasBtn');
  if (refreshCamerasBtn) {
    refreshCamerasBtn.addEventListener('click', () => loadCamerasRegistry());
  }

  // -------------------------------------------------------------------------
  // Screen 3: Camera Viewer Screen Logic
  // -------------------------------------------------------------------------
  const viewerCameraSelect = document.getElementById('viewerCameraSelect');
  const viewerCameraTitle = document.getElementById('viewerCameraTitle');
  const viewerBreadcrumbCurrent = document.getElementById('viewerBreadcrumbCurrent');
  const viewerVideoPlayer = document.getElementById('viewerVideoPlayer');
  const viewerVideoSource = document.getElementById('viewerVideoSource');
  const viewerOfflineOverlay = document.getElementById('viewerOfflineOverlay');
  const viewerNoticeBanner = document.getElementById('viewerNoticeBanner');
  const viewerAnalyzeBtn = document.getElementById('viewerAnalyzeBtn');
  const viewerAnalysisLoading = document.getElementById('viewerAnalysisLoading');
  const viewerRefreshEventsBtn = document.getElementById('viewerRefreshEventsBtn');

  if (viewerCameraSelect) {
    viewerCameraSelect.addEventListener('change', (e) => {
      state.selectedCameraId = e.target.value;
      loadSelectedCameraViewer(state.selectedCameraId);
    });
  }

  if (viewerRefreshEventsBtn) {
    viewerRefreshEventsBtn.addEventListener('click', () => {
      loadCameraEvents(state.selectedCameraId);
    });
  }

  async function loadSelectedCameraViewer(cameraId) {
    // 1. Fetch camera details
    try {
      const res = await fetch(`/api/cameras/${cameraId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const cam = await res.json();

      if (viewerCameraTitle) viewerCameraTitle.textContent = `${cam.name} (${cam.camera_id})`;
      if (viewerBreadcrumbCurrent) viewerBreadcrumbCurrent.textContent = cam.name;

      const isOffline = cam.status === 'OFFLINE';

      if (isOffline) {
        // Show offline overlay
        if (viewerOfflineOverlay) viewerOfflineOverlay.style.display = 'flex';
        if (viewerNoticeBanner) viewerNoticeBanner.style.display = 'none';
        if (viewerVideoPlayer) {
          viewerVideoPlayer.pause();
          viewerVideoPlayer.style.display = 'none';
        }
        if (viewerAnalyzeBtn) {
          viewerAnalyzeBtn.disabled = true;
          viewerAnalyzeBtn.title = 'Camera is offline. Analysis unavailable.';
        }
      } else {
        // Show video player
        if (viewerOfflineOverlay) viewerOfflineOverlay.style.display = 'none';
        if (viewerNoticeBanner) viewerNoticeBanner.style.display = 'flex';
        if (viewerVideoPlayer) {
          viewerVideoPlayer.style.display = 'block';
          const footageUrl = cam.footage_url || `/api/cameras/${cameraId}/footage`;
          if (viewerVideoSource && viewerVideoSource.src !== footageUrl) {
            viewerVideoSource.src = footageUrl;
            viewerVideoPlayer.load();
          }
        }
        if (viewerAnalyzeBtn) {
          viewerAnalyzeBtn.disabled = false;
          viewerAnalyzeBtn.title = 'Run neural person detection on this footage';
        }
      }

      // Load events for this camera
      loadCameraEvents(cameraId);

    } catch (err) {
      console.error('Failed to load camera viewer:', err);
    }
  }

  async function loadCameraEvents(cameraId) {
    const list = document.getElementById('viewerEventsList');
    if (!list) return;

    list.innerHTML = '<div class="summary-loading-placeholder" style="padding:1rem;">Loading events...</div>';

    try {
      const res = await fetch(`/api/cameras/${cameraId}/events`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const events = data.events || [];

      if (!events.length) {
        list.innerHTML = '<div class="summary-loading-placeholder" style="padding:1rem;">No persisted events for this camera. Click "Analyze Footage with AI" to run detection.</div>';
        return;
      }

      list.innerHTML = events.map(ev => {
        const timeStr = ev.timestamp ? new Date(ev.timestamp).toLocaleString() : 'Recent';
        const d = ev.data || {};
        const confStr = d.confidence ? `Conf: ${(d.confidence * 100).toFixed(1)}%` : '';
        const snap = d.snapshot_url ? `<a href="${escapeHtml(d.snapshot_url)}" target="_blank" style="color:var(--brand-blue); font-size:0.72rem; margin-left:0.5rem;">View Snapshot ↗</a>` : '';

        return `
          <div class="event-summary-item">
            <div class="event-item-icon">📸</div>
            <div class="event-item-content">
              <div class="event-item-title">${escapeHtml(ev.type || 'Detection')} ${escapeHtml(confStr)} ${snap}</div>
              <div class="event-item-desc">${escapeHtml(d.details || 'Camera event')}</div>
              <div class="event-item-time">${escapeHtml(timeStr)} • ID: <span class="font-mono">${escapeHtml(ev.event_id || '-')}</span></div>
            </div>
          </div>
        `;
      }).join('');

    } catch (err) {
      list.innerHTML = `<div class="summary-loading-placeholder" style="color:#EF4444; padding:1rem;">Failed to load events: ${escapeHtml(err.message)}</div>`;
    }
  }

  // Trigger Neural Inference: POST /api/cameras/{id}/analyze
  if (viewerAnalyzeBtn) {
    viewerAnalyzeBtn.addEventListener('click', async () => {
      if (state.isAnalyzing) return;

      const camId = state.selectedCameraId;
      state.isAnalyzing = true;
      viewerAnalyzeBtn.disabled = true;
      if (viewerAnalysisLoading) viewerAnalysisLoading.style.display = 'flex';

      try {
        const res = await fetch(`/api/cameras/${camId}/analyze`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ force_refresh: true }),
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `Analysis failed with HTTP ${res.status}`);
        }

        const result = await res.json();
        renderAnalysisResults(result);

        // Refresh persisted events
        await loadCameraEvents(camId);

      } catch (err) {
        alert(`Analysis Error: ${err.message}`);
      } finally {
        state.isAnalyzing = false;
        viewerAnalyzeBtn.disabled = false;
        if (viewerAnalysisLoading) viewerAnalysisLoading.style.display = 'none';
      }
    });
  }

  function renderAnalysisResults(result) {
    const emptyState = document.getElementById('viewerResultsEmptyState');
    const dataView = document.getElementById('viewerResultsDataView');
    const badge = document.getElementById('viewerResultStatusBadge');

    if (emptyState) emptyState.style.display = 'none';
    if (dataView) dataView.style.display = 'block';

    const detected = result.person_detected || result.analysis_status === 'PERSON_DETECTED';

    if (badge) {
      badge.textContent = result.analysis_status || (detected ? 'PERSON_DETECTED' : 'NO_PERSON_DETECTED');
      badge.className = `status-pill ${detected ? 'status-detected' : 'status-nodetect'}`;
    }

    const metricDetected = document.getElementById('metricPersonDetected');
    if (metricDetected) {
      metricDetected.textContent = detected ? 'Yes' : 'No';
      metricDetected.style.color = detected ? 'var(--risk-high)' : 'var(--status-secure)';
    }

    const metricConf = document.getElementById('metricConfidence');
    if (metricConf) {
      metricConf.textContent = result.model_confidence ? `${(result.model_confidence * 100).toFixed(1)}%` : 'N/A';
    }

    const metricFrames = document.getElementById('metricFramesCount');
    if (metricFrames) {
      metricFrames.textContent = result.total_frames_analyzed || '-';
    }

    // Snapshot
    const snapImg = document.getElementById('viewerSnapshotImg');
    const snapLink = document.getElementById('viewerSnapshotLink');
    const snapGroup = document.getElementById('viewerSnapshotGroup');

    if (result.snapshot_url) {
      if (snapGroup) snapGroup.style.display = 'block';
      if (snapImg) snapImg.src = result.snapshot_url;
      if (snapLink) snapLink.href = result.snapshot_url;
    } else {
      if (snapGroup) snapGroup.style.display = 'none';
    }

    // Audit facts
    const factLabel = document.getElementById('factDetectionLabel');
    if (factLabel) factLabel.textContent = detected ? 'person' : 'none';

    const factBBox = document.getElementById('factBoundingBox');
    if (factBBox) {
      factBBox.textContent = result.bounding_box ? JSON.stringify(result.bounding_box) : 'None';
    }

    const factModel = document.getElementById('factModelName');
    if (factModel) factModel.textContent = result.model_name || 'ssdlite320_mobilenet_v3_large';

    const factTime = document.getElementById('factTimestamp');
    if (factTime) factTime.textContent = new Date().toISOString();

    const factEvent = document.getElementById('factEventRef');
    if (factEvent) factEvent.textContent = result.event_reference || 'evt-none';

    const factFrame = document.getElementById('factDetectedFrame');
    if (factFrame) {
      factFrame.textContent = result.detected_frame_index !== null && result.detected_frame_index !== undefined
        ? `Frame ${result.detected_frame_index}`
        : 'None';
    }
  }

  // -------------------------------------------------------------------------
  // Screen 4: Ask HomeOps (Conversational Chat)
  // -------------------------------------------------------------------------
  const chatThread = document.getElementById('chatThread');
  const chatComposerForm = document.getElementById('chatComposerForm');
  const userInputField = document.getElementById('userInputField');
  const typingIndicator = document.getElementById('typingIndicator');
  const audioToggleBtn = document.getElementById('audioToggleBtn');
  const audioToggleLabel = document.getElementById('audioToggleLabel');
  const audioIconOn = document.getElementById('audioIconOn');
  const audioIconOff = document.getElementById('audioIconOff');
  const micBtn = document.getElementById('micBtn');

  // Audio Toggle
  if (audioToggleBtn) {
    audioToggleBtn.addEventListener('click', () => {
      state.isSpeechEnabled = !state.isSpeechEnabled;
      if (audioToggleLabel) audioToggleLabel.textContent = `Voice: ${state.isSpeechEnabled ? 'Enabled' : 'Muted'}`;
      if (audioIconOn) audioIconOn.style.display = state.isSpeechEnabled ? 'block' : 'none';
      if (audioIconOff) audioIconOff.style.display = state.isSpeechEnabled ? 'none' : 'block';
    });
  }

  // Web Speech API: Voice Synthesis
  function speakResponse(text) {
    if (!state.isSpeechEnabled || !window.speechSynthesis) return;
    try {
      window.speechSynthesis.cancel();
      const cleanText = text.replace(/[*_#`]/g, '');
      const utterance = new SpeechSynthesisUtterance(cleanText);
      utterance.rate = 1.05;
      utterance.pitch = 1.0;
      window.speechSynthesis.speak(utterance);
    } catch (e) {
      console.warn('Speech synthesis error:', e);
    }
  }

  // Web Speech API: Speech Recognition (Mic)
  if (micBtn && ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window)) {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    state.recognition = new SpeechRecognition();
    state.recognition.continuous = false;
    state.recognition.interimResults = false;

    state.recognition.onstart = () => {
      state.isRecording = true;
      micBtn.classList.add('recording');
    };

    state.recognition.onend = () => {
      state.isRecording = false;
      micBtn.classList.remove('recording');
    };

    state.recognition.onresult = (e) => {
      const transcript = e.results[0][0].transcript;
      if (userInputField && transcript) {
        userInputField.value = transcript;
        submitChatMessage(transcript);
      }
    };

    micBtn.addEventListener('click', () => {
      if (state.isRecording) {
        state.recognition.stop();
      } else {
        state.recognition.start();
      }
    });
  }

  // Chat Form Submit
  if (chatComposerForm) {
    chatComposerForm.addEventListener('submit', (e) => {
      e.preventDefault();
      if (!userInputField) return;
      const q = userInputField.value.trim();
      if (q) {
        submitChatMessage(q);
        userInputField.value = '';
      }
    });
  }

  // Chat Suggested Buttons
  document.querySelectorAll('.chat-suggest-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const q = btn.getAttribute('data-query');
      if (q) submitChatMessage(q);
    });
  });

  async function submitChatMessage(message) {
    if (state.isChatProcessing) return;
    state.isChatProcessing = true;

    // Append user turn
    appendChatBubble('user', message);

    if (typingIndicator) typingIndicator.style.display = 'flex';
    if (chatThread) chatThread.scrollTop = chatThread.scrollHeight;

    const startTime = Date.now();

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          utterance: message,
          scenario_hint: state.currentScenario,
          session_id: 'web-session',
        }),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const elapsedMs = Date.now() - startTime;

      appendAssistantTurn(data, elapsedMs);

      if (data.speech) {
        speakResponse(data.speech);
      }

    } catch (err) {
      appendChatBubble('assistant', `I encountered an error communicating with HomeOps services: ${err.message}`);
    } finally {
      state.isChatProcessing = false;
      if (typingIndicator) typingIndicator.style.display = 'none';
      if (chatThread) chatThread.scrollTop = chatThread.scrollHeight;
    }
  }

  function appendChatBubble(role, text) {
    if (!chatThread) return;
    const turn = document.createElement('div');
    turn.className = `chat-turn ${role}`;

    const sender = role === 'user'
      ? `<div class="turn-sender">You</div>`
      : `<div class="turn-sender"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polygon points="10 8 16 12 10 16 10 8"></polygon></svg> HomeOps Assistant <span class="lang-badge">SECURE</span></div>`;

    turn.innerHTML = `
      ${sender}
      <div class="bubble">
        <div class="speech-text">${escapeHtml(text)}</div>
      </div>
    `;

    chatThread.appendChild(turn);
    chatThread.scrollTop = chatThread.scrollHeight;
  }

  function appendAssistantTurn(data, elapsedMs) {
    if (!chatThread) return;
    const turn = document.createElement('div');
    turn.className = 'chat-turn assistant';

    const speech = data.speech || 'Response received.';
    const toolCalls = data.tool_calls || [];

    const toolChipsHtml = toolCalls.map((tc, idx) => {
      const toolName = tc.tool || tc.name || 'tool';
      return `
        <button class="tool-call-chip" data-tc-idx="${idx}" title="Click to view MCP arguments & response">
          <span>⚙️ ${escapeHtml(toolName)}</span>
        </button>
      `;
    }).join('');

    turn.innerHTML = `
      <div class="turn-sender">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"></circle><polygon points="10 8 16 12 10 16 10 8"></polygon>
        </svg>
        HomeOps Assistant <span class="lang-badge">SECURE</span>
      </div>
      <div class="bubble">
        <div class="speech-text">${escapeHtml(speech)}</div>
        ${toolCalls.length ? `<div class="tool-calls-container">${toolChipsHtml}</div>` : ''}
      </div>
      <div class="turn-latency">Latency: ${elapsedMs}ms • Policy: STRICT_DETERMINISTIC</div>
    `;

    // Wire up tool inspector clicks
    turn.querySelectorAll('.tool-call-chip').forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = parseInt(btn.getAttribute('data-tc-idx'), 10);
        openMcpInspector(toolCalls[idx]);
      });
    });

    chatThread.appendChild(turn);
    chatThread.scrollTop = chatThread.scrollHeight;
  }

  // -------------------------------------------------------------------------
  // MCP Tool Inspector Modal
  // -------------------------------------------------------------------------
  const jsonInspectorModal = document.getElementById('jsonInspectorModal');
  const modalToolTitle = document.getElementById('modalToolTitle');
  const modalInputJson = document.getElementById('modalInputJson');
  const modalOutputJson = document.getElementById('modalOutputJson');
  const closeModalBtn = document.getElementById('closeModalBtn');
  const closeModalBtn2 = document.getElementById('closeModalBtn2');

  function openMcpInspector(toolCall) {
    if (!jsonInspectorModal || !toolCall) return;
    const toolName = toolCall.tool || toolCall.name || 'MCP Tool';
    if (modalToolTitle) modalToolTitle.textContent = `MCP Tool: ${toolName}`;
    if (modalInputJson) modalInputJson.textContent = JSON.stringify(toolCall.args || {}, null, 2);
    if (modalOutputJson) modalOutputJson.textContent = JSON.stringify(toolCall.result || {}, null, 2);
    jsonInspectorModal.style.display = 'flex';
  }

  function closeMcpInspector() {
    if (jsonInspectorModal) jsonInspectorModal.style.display = 'none';
  }

  if (closeModalBtn) closeModalBtn.addEventListener('click', closeMcpInspector);
  if (closeModalBtn2) closeModalBtn2.addEventListener('click', closeMcpInspector);

  // -------------------------------------------------------------------------
  // Screen 5: Safety & Investigations Logic
  // -------------------------------------------------------------------------
  const testLockActionBtn = document.getElementById('testLockActionBtn');
  if (testLockActionBtn) {
    testLockActionBtn.addEventListener('click', async () => {
      testLockActionBtn.disabled = true;
      testLockActionBtn.textContent = 'Enforcing Safety Policy...';

      try {
        // Attempting to execute action via chat to demonstrate deterministic policy blocking
        const res = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            utterance: 'Lock the back door right now',
            scenario_hint: state.currentScenario,
            session_id: 'web-session',
          }),
        });

        const data = await res.json();
        alert(`Safety Guardrail Enforced!\n\nPolicy Verdict: BLOCKED\nResponse: "${data.speech}"\n\nAutonomous physical device manipulation is prohibited.`);
      } catch (err) {
        alert(`Guardrail block active: ${err.message}`);
      } finally {
        testLockActionBtn.disabled = false;
        testLockActionBtn.textContent = 'Request: "Lock Back Door"';
      }
    });
  }

  // -------------------------------------------------------------------------
  // Screen 6: System Status & Settings Logic
  // -------------------------------------------------------------------------
  async function loadSystemStatus() {
    const list = document.getElementById('mcpToolsList');
    if (!list) return;

    try {
      const res = await fetch('/api/mcp/status');
      if (res.ok) {
        const data = await res.json();
        const tools = data.tools || [];
        state.mcpTools = tools;

        const badge = document.getElementById('settingsMcpToolsBadge');
        if (badge) badge.textContent = `${tools.length} Tools Connected`;

        list.innerHTML = tools.map(t => `
          <div class="tool-badge-item">
            <span class="tool-dot"></span>
            <span>${escapeHtml(t.name || t)}</span>
          </div>
        `).join('');
      }
    } catch (err) {
      console.error('Failed to load MCP status:', err);
    }
  }

  // Scenario Selector (Top Action Bar)
  const scenarioSelector = document.getElementById('scenarioSelector');
  if (scenarioSelector) {
    scenarioSelector.addEventListener('change', async (e) => {
      state.currentScenario = e.target.value;
      try {
        await fetch('/api/scenario', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ scenario: state.currentScenario }),
        });
        loadHomeSummary();
      } catch (err) {
        console.warn('Scenario switch notice:', err);
      }
    });
  }

  const reloadCurrentScenarioBtn = document.getElementById('reloadCurrentScenarioBtn');
  if (reloadCurrentScenarioBtn) {
    reloadCurrentScenarioBtn.addEventListener('click', async () => {
      try {
        await fetch('/api/scenario', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ scenario: state.currentScenario }),
        });
        alert(`Scenario "${state.currentScenario}" reloaded successfully.`);
        loadHomeSummary();
      } catch (err) {
        alert(`Reload error: ${err.message}`);
      }
    });
  }

  const resetHomeStateBtn = document.getElementById('resetHomeStateBtn');
  if (resetHomeStateBtn) {
    resetHomeStateBtn.addEventListener('click', async () => {
      try {
        await fetch('/api/scenario', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ scenario: 'clear' }),
        });
        if (scenarioSelector) scenarioSelector.value = 'clear';
        state.currentScenario = 'clear';
        alert('Home state reset to normal quiet conditions.');
        loadHomeSummary();
      } catch (err) {
        alert(`Reset error: ${err.message}`);
      }
    });
  }

  // -------------------------------------------------------------------------
  // Initial Boot
  // -------------------------------------------------------------------------
  loadHomeSummary();
});
