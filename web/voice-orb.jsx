import React, {useLayoutEffect, useState} from 'react';

const h = React.createElement;

const labels = {
  connecting: 'Thinking',
  idle: 'Talk to Kaufmann',
  listening: 'Listening...',
  processing: 'Thinking...',
  searching: 'Thinking...',
  responding: 'Thinking...',
  speaking: 'Tap to interrupt',
  error: 'Try again',
};

export function VoiceOrb() {
  const [voice, setVoice] = useState({state: 'idle', message: ''});
  const [soundRequired, setSoundRequired] = useState(false);

  useLayoutEffect(() => {
    const onState = event => setVoice(event.detail);
    const onSoundRequired = () => setSoundRequired(true);
    const onSoundEnabled = () => setSoundRequired(false);
    const onClear = () => setSoundRequired(false);
    window.addEventListener('kaufmann:voice-state', onState);
    window.addEventListener('kaufmann:voice-sound-required', onSoundRequired);
    window.addEventListener('kaufmann:voice-sound-enabled', onSoundEnabled);
    window.addEventListener('kaufmann:voice-clear', onClear);
    return () => {
      window.removeEventListener('kaufmann:voice-state', onState);
      window.removeEventListener('kaufmann:voice-sound-required', onSoundRequired);
      window.removeEventListener('kaufmann:voice-sound-enabled', onSoundEnabled);
      window.removeEventListener('kaufmann:voice-clear', onClear);
    };
  }, []);

  const active = !['idle', 'error'].includes(voice.state);
  const label = labels[voice.state] || '';

  return h('aside', {
    className: 'voice-orb-widget',
    'data-state': voice.state,
    'data-active': String(active),
    'aria-label': 'Kaufmann voice assistant',
  },
  h('button', {
    id: 'voice-button',
    className: 'voice-orb-button',
    type: 'button',
    'aria-label': active ? 'End voice shopping' : voice.state === 'error' ? 'Try voice shopping again' : 'Talk to Kaufmann',
    'aria-pressed': String(active),
  },
  h('span', {className: 'voice-orb-sphere', 'aria-hidden': true},
    h('span', {className: 'orb-light orb-light-one'}),
    h('span', {className: 'orb-light orb-light-two'}),
    h('span', {className: 'orb-core'}),
    h('span', {className: 'orb-reflection'}))),
  h('div', {className: 'voice-orb-caption', 'aria-live': 'polite'},
    h('span', {id: 'voice-status', role: 'status', 'data-state': voice.state}, label || labels.idle)),
  h('button', {
    id: 'voice-sound',
    className: 'voice-sound-button',
    type: 'button',
    hidden: !soundRequired,
    onClick: () => window.dispatchEvent(new Event('kaufmann:voice-enable-sound')),
  }, 'Enable sound'));
}
