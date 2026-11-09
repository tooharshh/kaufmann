(() => {
  const diagnostics = new URLSearchParams(location.search).get("voice_debug") === "1";
  const latencySamples = [];
  let meter = null;
  window.kaufmannVoiceMetrics = () => latencySamples.map(sample => ({ ...sample }));
  const createMeter = async () => {
    const Context = window.AudioContext || window.webkitAudioContext;
    if (!Context) return null;
    const context = new Context();
    context.resume().catch(() => { });
    let mic = null;
    let frame = null;
    let previousTick = performance.now();
    let speechStart = null;
    let speechEnd = null;
    let pendingEnd = null;
    let remoteQuiet = true;
    const remotes = new Map();
    const analyse = source => {
      const analyser = context.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      return { source, analyser, data: new Float32Array(analyser.fftSize) };
    };
    const energy = input => {
      input.analyser.getFloatTimeDomainData(input.data);
      return Math.sqrt(input.data.reduce((sum, value) => sum + value * value, 0) / input.data.length);
    };
    const tick = () => {
      const now = performance.now();
      if (now - previousTick > 250) { pendingEnd = null; speechStart = null; speechEnd = null; }
      const tickInterval = now - previousTick;
      previousTick = now;
      const speaking = mic && energy(mic) > 0.02;
      if (speaking) {
        if (speechStart === null) speechStart = now;
        speechEnd = now;
        pendingEnd = null;
      } else if (speechStart !== null && now - speechEnd >= 120) {
        if (speechEnd - speechStart >= 100) pendingEnd = speechEnd;
        speechStart = null;
      }
      const audible = [...remotes.entries()].some(([audio, input]) => !audio.paused && !audio.muted && audio.volume > 0 && energy(input) > 0.005);
      if (audible && remoteQuiet && pendingEnd !== null && !speaking && context.state === 'running') {
        const outputDelay = 1000 * (context.outputLatency || context.baseLatency || 0);
        const sample = { metric: 'browser_eou_to_playback_estimate_ms', value: Math.round(now + outputDelay - pendingEnd), sampling_resolution_ms: Math.round(tickInterval), recorded_at: Date.now() };
        latencySamples.push(sample);
        if (latencySamples.length > 100) latencySamples.shift();
        console.info('voice_browser_latency', sample);
        pendingEnd = null;
      }
      remoteQuiet = !audible;
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return {
      resume() { return context.resume(); },
      microphone(track) {
        if (track?.mediaStreamTrack) mic = analyse(context.createMediaStreamSource(new MediaStream([track.mediaStreamTrack])));
      },
      output(audio, track) {
        if (!track?.mediaStreamTrack) return;
        const input = analyse(context.createMediaStreamSource(new MediaStream([track.mediaStreamTrack])));
        remotes.set(audio, input);
      },
      remove(audio) {
        const input = remotes.get(audio);
        if (input) { input.source.disconnect(); input.analyser.disconnect(); remotes.delete(audio); }
      },
      async close() {
        cancelAnimationFrame(frame);
        if (mic) { mic.source.disconnect(); mic.analyser.disconnect(); }
        for (const input of remotes.values()) { input.source.disconnect(); input.analyser.disconnect(); }
        remotes.clear();
        await context.close();
      }
    };
  };

  const initializeVoice = () => {
    let room = null;
    let epoch = 0;
    let connecting = false;
    let stopping = false;
    let deadline = null;
    let pendingSelection = null;
    let agentReady = false;
    let lastSentSelection = null;
    let orbMonitor = null;
    let microphoneTrack = null;
    const button = document.querySelector('#voice-button');
    const setVoiceState = (state, message = '') => {
      button.dataset.state = state;
      window.dispatchEvent(new CustomEvent('kaufmann:voice-state', { detail: { state, message } }));
    };
    const addTranscript = (speaker, text, final) => window.dispatchEvent(new CustomEvent('kaufmann:voice-transcript', { detail: { speaker, text, final } }));
    const isStopCommand = text => /^(?:please\s+)?(?:stop(?:\s+(?:talking|speaking|it))?|shut\s+up|that(?:'|’)s\s+enough|that\s+is\s+enough|enough|be\s+quiet|ఆపు|చాలు|ఇక\s+చాలు)(?:\s+(?:please|now))?[.!?\s]*$/iu.test(text.normalize('NFKC').trim());
    window.kaufmannShowAssistantProducts = products => window.dispatchEvent(new CustomEvent('kaufmann:voice-products', { detail: { products } }));
    const setButton = (label, active) => {
      button.setAttribute('aria-label', label);
      button.title = label;
      button.setAttribute('aria-pressed', String(active));
    };
    const showStatus = message => {
      const normalized = message.toLowerCase();
      const state = /connect|reconnect|wake up/.test(normalized) ? 'connecting' : /search|finding|look through/.test(normalized) ? 'searching' : /putting that together|thinking|processing/.test(normalized) ? 'processing' : /respond|speaking|answer/.test(normalized) ? 'responding' : /error|blocked|unavailable|couldn|allow microphone/.test(normalized) ? 'error' : room || connecting ? 'listening' : 'idle';
      setVoiceState(state, message);
    };
    const monitorOrbTrack = track => {
      const previous = orbMonitor;
      orbMonitor = null;
      if (previous) {
        cancelAnimationFrame(previous.frame);
        previous.source.disconnect();
        previous.analyser.disconnect();
        previous.context.close().catch(() => { });
      }
      const Context = window.AudioContext || window.webkitAudioContext;
      if (!Context || !track?.mediaStreamTrack) return;
      try {
        const context = new Context();
        const source = context.createMediaStreamSource(new MediaStream([track.mediaStreamTrack]));
        const analyser = context.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);
        context.resume().catch(() => { });
        const data = new Float32Array(analyser.fftSize);
        const monitor = { context, source, analyser, frame: 0 };
        let lastSample = 0;
        let smoothed = 0;
        const sample = timestamp => {
          if (orbMonitor !== monitor) return;
          if (timestamp - lastSample >= 40 && context.state === 'running') {
            lastSample = timestamp;
            analyser.getFloatTimeDomainData(data);
            const rms = Math.sqrt(data.reduce((sum, value) => sum + value * value, 0) / data.length);
            smoothed = smoothed * 0.68 + rms * 0.32;
            const energy = Math.min(1, smoothed * 7);
            document.querySelector('#voice-orb-mount')?.style.setProperty('--orb-scale', (1 + energy * 0.035).toFixed(3));
            document.querySelector('#voice-orb-mount')?.style.setProperty('--orb-glow', `${18 + energy * 12}px`);
          }
          monitor.frame = requestAnimationFrame(sample);
        };
        orbMonitor = monitor;
        monitor.frame = requestAnimationFrame(sample);
      } catch { orbMonitor = null; }
    };
    const stop = async () => {
      if (stopping) return;
      stopping = true;
      epoch++;
      connecting = false;
      ui.voiceConnecting = false;
      agentReady = false;
      lastSentSelection = null;
      ui.voiceActive = false;
      pendingSelection = null;
      clearTimeout(deadline);
      const previous = room;
      room = null;
      for (const audio of document.querySelectorAll('[data-voice-audio]')) { audio.pause(); audio.remove(); }
      setButton('Talk to Kaufmann', false);
      setVoiceState('idle', '');
      document.querySelector('#voice-orb-mount')?.style.setProperty('--orb-scale', '1');
      document.querySelector('#voice-orb-mount')?.style.setProperty('--orb-glow', '18px');
      if (previous) {
        try { previous.localParticipant.setMicrophoneEnabled(false).catch(() => { }); } catch { }
        try { previous.disconnect().catch(() => { }); } catch { }
      }
      microphoneTrack = null;
      if (orbMonitor) {
        cancelAnimationFrame(orbMonitor.frame);
        try { orbMonitor.source.disconnect(); orbMonitor.analyser.disconnect(); } catch { }
        await orbMonitor.context.close().catch(() => { });
        orbMonitor = null;
      }
      const previousMeter = meter;
      meter = null;
      if (previousMeter) await previousMeter.close().catch(() => { });
      window.dispatchEvent(new Event('kaufmann:voice-clear'));
      stopping = false;
    };
    window.kaufmannStopVoice = stop;
    const sendSelection = async () => {
      if (!room || !agentReady || !pendingSelection || lastSentSelection === pendingSelection.event_id || location.pathname !== '/product/' + encodeURIComponent(pendingSelection.product_id)) return;
      const client = room;
      const event = pendingSelection;
      const agents = [...client.remoteParticipants.values()].filter(participant => participant.isAgent).map(participant => participant.identity).filter(Boolean);
      if (!agents.length) return;
      try {
        await client.localParticipant.publishData(new TextEncoder().encode(JSON.stringify(event)), { reliable: true, topic: 'kaufmann.selection', destinationIdentities: agents });
        if (room === client) lastSentSelection = event.event_id;
      } catch { showStatus('Your selection is visible here. Tell the assistant which product you selected.'); }
    };
    window.kaufmannSelectProduct = productId => {
      pendingSelection = { type: 'product_selected', product_id: productId, event_id: crypto.randomUUID() };
      sendSelection();
    };
    button.addEventListener('click', async () => {
      if (stopping) return;
      if (room || connecting) { await stop(); return; }
      if (!ui.auth) { openAuth(); return; }
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        showStatus('Use localhost or HTTPS to enable your microphone.');
        return;
      }
      const current = ++epoch;
      const generation = ui.generation;
      connecting = true;
      ui.voiceConnecting = true;
      setButton('Cancel voice', true);
      showStatus('Connecting to your shopping assistant…');
      try {
        try {
          const nextMeter = diagnostics ? await createMeter() : null;
          if (current !== epoch || generation !== ui.generation) { await nextMeter?.close(); return; }
          meter = nextMeter;
        } catch { meter = null; }
        const config = assertOk(await api('/api/voice/session', {}));
        if (current !== epoch || generation !== ui.generation) return;
        const client = new LivekitClient.Room({ adaptiveStream: true, dynacast: true });
        room = client;
        client.registerTextStreamHandler('lk.transcription', async (reader, participantInfo) => {
          if (room !== client || generation !== ui.generation) return;
          let message;
          try { message = await reader.readAll(); } catch { return; }
          if (room !== client || generation !== ui.generation || !message.trim()) return;
          const attributes = reader.info?.attributes || {};
          const identity = participantInfo?.identity;
          const speaker = identity && identity === client.localParticipant.identity ? 'You' : 'Kaufmann';
          const final = attributes['lk.transcription_final'] !== 'false';
          if (speaker === 'You' && final && isStopCommand(message)) { addTranscript(speaker, message, final); void stop(); return; }
          addTranscript(speaker, message, final);
          if (speaker === 'You' && final) setVoiceState('processing', '');
          else if (speaker === 'Kaufmann') setVoiceState('processing', '');
        });
        client.on(LivekitClient.RoomEvent.DataReceived, (payload, participant, kind, topic) => {
          if (room !== client || generation !== ui.generation || !participant?.isAgent || topic !== 'kaufmann.navigation' || payload.byteLength > 4096) return;
          let event;
          try { event = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(payload)); } catch { return; }
          if (!event || typeof event !== 'object' || Array.isArray(event)) return;
          if (event.type === 'ready') { agentReady = true; lastSentSelection = null; sendSelection(); return; }
          showStatus(event.type === 'catalog' ? 'Looking through the collection…' : 'I’m putting that together…');
          handleAgentNavigation(event).catch(() => showStatus('The screen could not update. You can still browse and open your cart.'));
        });
        client.on(LivekitClient.RoomEvent.TrackSubscribed, track => {
          if (track.kind !== LivekitClient.Track.Kind.Audio || room !== client) return;
          const audio = track.attach();
          audio.dataset.voiceAudio = '';
          try { meter?.output(audio, track); } catch { }
          monitorOrbTrack(track);
          audio.addEventListener('playing', () => { if (room === client) setVoiceState('speaking', ''); });
          audio.addEventListener('waiting', () => { if (room === client && ui.voiceActive) setVoiceState('processing', ''); });
          audio.addEventListener('pause', () => { if (room === client && ui.voiceActive) { monitorOrbTrack(microphoneTrack); setVoiceState('listening', ''); } });
          document.body.append(audio);
          audio.play().catch(() => { showStatus('Tap Enable sound to hear Kaufmann.'); window.dispatchEvent(new Event('kaufmann:voice-sound-required')); });
        });
        client.on(LivekitClient.RoomEvent.TrackUnsubscribed, track => { track.detach().forEach(element => { meter?.remove(element); element.remove(); }); if (room === client && ui.voiceActive) { monitorOrbTrack(microphoneTrack); setVoiceState('listening', ''); } });
        client.on(LivekitClient.RoomEvent.ParticipantConnected, participant => {
          if (participant.isAgent && room === client) {
            clearTimeout(deadline);
            agentReady = true;
            sendSelection();
            showStatus('Connected. What are you looking for?');
          }
        });
        client.on(LivekitClient.RoomEvent.Disconnected, () => { if (room === client) stop(); });
        client.on(LivekitClient.RoomEvent.Reconnecting, () => { showStatus('Reconnecting your conversation…'); });
        client.on(LivekitClient.RoomEvent.Reconnected, () => { showStatus('Connected. You can keep talking.'); lastSentSelection = null; sendSelection(); });
        await client.connect(config.url, config.token);
        if (current !== epoch || generation !== ui.generation) { await client.disconnect(); return; }
        await client.startAudio();
        const microphone = await client.localParticipant.setMicrophoneEnabled(true);
        microphoneTrack = microphone?.track;
        try { meter?.microphone(microphoneTrack); } catch { }
        monitorOrbTrack(microphoneTrack);
        if (current !== epoch || generation !== ui.generation) { await client.disconnect(); return; }
        connecting = false;
        ui.voiceConnecting = false;
        ui.voiceActive = true;
        setButton('End voice', true);
        if (ui.focusedProduct && location.pathname.startsWith('/product/')) window.kaufmannSelectProduct(ui.focusedProduct.id);
        sendSelection();
        showStatus('Microphone on. The assistant may take a moment to wake up…');
        const present = [...client.remoteParticipants.values()].some(participant => participant.isAgent);
        if (present) { agentReady = true; sendSelection(); showStatus('Connected. What are you looking for?'); }
        else deadline = setTimeout(async () => {
          if (room !== client) return;
          await stop();
          showStatus('The assistant is unavailable. Please try again shortly.');
        }, 90000);
      } catch (error) {
        if (current !== epoch) return;
        await stop();
        showStatus(error.name === 'NotAllowedError' ? 'Allow microphone access, then try again.' : 'Voice couldn’t connect. You can keep shopping here.');
      }
    });
    window.addEventListener('kaufmann:voice-enable-sound', async () => {
      try { await meter?.resume(); await room?.startAudio(); window.dispatchEvent(new Event('kaufmann:voice-sound-enabled')); showStatus('Sound enabled.'); }
      catch { showStatus('Sound is blocked. Check your browser permissions.'); }
    });
    window.addEventListener('pagehide', stop);
  };
  if (document.querySelector('#voice-button')) initializeVoice();
  else window.addEventListener('kaufmann:voice-orb-ready', initializeVoice, { once: true });
})();
