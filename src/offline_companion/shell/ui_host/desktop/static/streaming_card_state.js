(function(root, factory) {
  var parser = root && root.StreamingCardParser;
  if (typeof module === 'object' && module.exports) {
    parser = require('./streaming_card_parser.js');
    module.exports = factory(parser);
    return;
  }
  root.StreamingCardState = factory(parser);
})(typeof globalThis !== 'undefined' ? globalThis : this, function(parser) {
  'use strict';

  function create(goal) {
    return {
      goal: String(goal || ''),
      lifecycle: 'provisional',
      buffer: '',
      partial: {value: null, closed: [], complete: false},
      consecutiveFailures: 0,
      attempt: 1,
      notice: '',
      plainText: '',
      card: null,
      fallback: null,
      terminal: false,
      cleared: false
    };
  }

  function apply(state, event) {
    var type = String(event && event.type || '');
    if (type === 'card_delta') {
      if (state.lifecycle === 'degraded') return state;
      state.buffer += String(event.delta || '');
      var partial = parser.parsePartialCard(state.buffer);
      if (partial.value === null) {
        state.consecutiveFailures += 1;
        if (state.consecutiveFailures >= 2) {
          state.lifecycle = 'degraded';
          state.notice = '结构化生成已降级，后续内容按纯文本处理';
        }
      } else {
        state.partial = partial;
        state.consecutiveFailures = 0;
      }
      return state;
    }
    if (type === 'card_retry') {
      state.lifecycle = 'provisional';
      state.buffer = '';
      state.partial = {value: null, closed: [], complete: false};
      state.consecutiveFailures = 0;
      state.attempt = Number(event.attempt) || state.attempt + 1;
      state.notice = '重新生成中（第 ' + state.attempt + ' 次）';
      return state;
    }
    if (type === 'card_final') {
      state.card = event.card || null;
      state.terminal = true;
      if (state.lifecycle !== 'degraded') {
        state.lifecycle = 'accepted';
        state.notice = '';
      }
      return state;
    }
    if (type === 'card_degrade') {
      state.lifecycle = 'degraded';
      state.notice = String(event.reason || '结构化生成已降级');
      return state;
    }
    if (type === 'token' && state.lifecycle === 'degraded') {
      state.plainText += String(event.token || '');
      return state;
    }
    if (type === 'error') {
      state.lifecycle = 'degraded';
      state.terminal = Boolean(event.done);
      state.notice = event.code === 'card_validation_failed' ?
        '校验未通过，内容可能不准确' : '任务拆解失败';
      return state;
    }
    if (type === 'not_decomposable') {
      state.fallback = event;
      state.terminal = true;
      state.buffer = '';
      state.partial = {value: null, closed: [], complete: false};
      state.cleared = true;
      return state;
    }
    if (type === 'done') state.terminal = true;
    return state;
  }

  function disconnect(state) {
    state.cleared = true;
    state.terminal = true;
    return state;
  }

  return {create: create, apply: apply, disconnect: disconnect};
});
