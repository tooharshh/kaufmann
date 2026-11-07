(() => {
  const diagnostics = new URLSearchParams(location.search).get("voice_debug") === "1";
  const latencySamples = [];
  let meter = null;
  window.kaufmannVoiceMetrics = () => latencySamples.map(sample => ({...sample}));
  const createMeter = async () => {
    const Context = window.AudioContext || window.webkitAudioContext;
    if (!Context) return null;
    const context = new Context();
    context.resume().catch(() => {});
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
      return {source, analyser, data: new Float32Array(analyser.fftSize)};
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
        const sample = {metric:'browser_eou_to_playback_estimate_ms', value:Math.round(now + outputDelay - pendingEnd), sampling_resolution_ms:Math.round(tickInterval), recorded_at:Date.now()};
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

  let room = null;
  let epoch = 0;
  let connecting = false;
  let deadline = null;
  let pendingSelection = null;
  let agentReady = false;
  let lastSentSelection = null;
  const button = document.querySelector('#voice-button');
  const status = document.querySelector('#voice-status');
  const popover = document.querySelector('#voice-popover');
  const setButton = (label, active) => {
    button.setAttribute('aria-label', label);
    button.title = label;
    button.setAttribute('aria-pressed', String(active));
    button.classList.toggle('is-active', active);
  };
  const showStatus = message => { status.textContent = message; popover.hidden = false; };
  const stop = async () => {
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
    if (previous) await previous.disconnect();
    const previousMeter = meter;
    meter = null;
    if (previousMeter) await previousMeter.close();
    document.querySelectorAll('[data-voice-audio]').forEach(audio => audio.remove());
    document.querySelector('#voice-sound').hidden = true;
    setButton('Talk to Kaufmann', false);
    status.textContent = 'Talk in English or Telugu.'; popover.hidden = true;
  };
  window.kaufmannStopVoice = stop;
  const sendSelection = async () => {
    if (!room || !agentReady || !pendingSelection || lastSentSelection === pendingSelection.event_id || location.pathname !== '/product/' + encodeURIComponent(pendingSelection.product_id)) return;
    const client = room;
    const event = pendingSelection;
    const agents = [...client.remoteParticipants.values()].filter(participant => participant.isAgent).map(participant => participant.identity).filter(Boolean);
    if (!agents.length) return;
    try {
      await client.localParticipant.publishData(new TextEncoder().encode(JSON.stringify(event)), {reliable: true, topic: 'kaufmann.selection', destinationIdentities: agents});
      if (room === client) lastSentSelection = event.event_id;
    } catch { showStatus('Your selection is visible here. Tell the assistant which product you selected.'); }
  };
  window.kaufmannSelectProduct = productId => {
    pendingSelection = {type:'product_selected', product_id:productId, event_id:crypto.randomUUID()};
    sendSelection();
  };
  button.addEventListener('click', async () => {
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
      const client = new LivekitClient.Room({adaptiveStream: true, dynacast: true});
      room = client;
      client.on(LivekitClient.RoomEvent.DataReceived, (payload, participant, kind, topic) => {
        if (room !== client || generation !== ui.generation || !participant?.isAgent || topic !== 'kaufmann.navigation' || payload.byteLength > 4096) return;
        let event;
        try { event = JSON.parse(new TextDecoder('utf-8', {fatal:true}).decode(payload)); } catch { return; }
        if (!event || typeof event !== 'object' || Array.isArray(event)) return;
        if (event.type === 'ready') { agentReady = true; lastSentSelection = null; sendSelection(); return; }
        handleAgentNavigation(event).catch(() => showStatus('The screen could not update. You can still browse and open your cart.'));
      });
      client.on(LivekitClient.RoomEvent.TrackSubscribed, track => {
        if (track.kind !== LivekitClient.Track.Kind.Audio || room !== client) return;
        const audio = track.attach();
        audio.dataset.voiceAudio = '';
        try { meter?.output(audio, track); } catch {}
        document.body.append(audio);
        audio.play().catch(() => { showStatus('Tap “Enable sound” to hear your assistant.'); document.querySelector('#voice-sound').hidden = false; });
      });
      client.on(LivekitClient.RoomEvent.TrackUnsubscribed, track => track.detach().forEach(element => { meter?.remove(element); element.remove(); }));
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
      try { meter?.microphone(microphone?.track); } catch {}
      if (current !== epoch || generation !== ui.generation) { await client.disconnect(); return; }
      connecting = false;
      ui.voiceConnecting = false;
      ui.voiceActive = true;
      setButton('End voice', true);
      if (ui.focusedProduct && location.pathname.startsWith('/product/')) window.kaufmannSelectProduct(ui.focusedProduct.id);
      sendSelection();
      showStatus('Microphone on. Waiting for your assistant…');
      const present = [...client.remoteParticipants.values()].some(participant => participant.isAgent);
      if (present) { agentReady = true; sendSelection(); showStatus('Connected. What are you looking for?'); }
      else deadline = setTimeout(async () => {
        if (room !== client) return;
        await stop();
        showStatus('The assistant is unavailable. Please try again shortly.');
      }, 30000);
    } catch (error) {
      if (current !== epoch) return;
      await stop();
      showStatus(error.name === 'NotAllowedError' ? 'Allow microphone access, then try again.' : 'Voice couldn’t connect. You can keep shopping here.');
    }
  });
  document.querySelector('#voice-sound').addEventListener('click', async event => {
    try { await meter?.resume(); await room?.startAudio(); event.target.hidden = true; showStatus('Sound enabled.'); }
    catch { showStatus('Sound is blocked. Check your browser permissions.'); }
  });
  window.addEventListener('pagehide', stop);
})();
