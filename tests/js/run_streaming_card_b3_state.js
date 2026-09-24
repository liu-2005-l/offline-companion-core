'use strict';

const stateApi = require('../../src/offline_companion/shell/ui_host/desktop/static/streaming_card_state.js');

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const normal = stateApi.create('goal');
stateApi.apply(normal, {type: 'card_delta', delta: '{"steps":['});
stateApi.apply(normal, {type: 'card_delta', delta: '{"title":"A"}]}' });
assert(normal.lifecycle === 'provisional', 'delta must remain provisional');
assert(normal.partial.closed[0] === 'steps[0]', 'closed card must be visible');
stateApi.apply(normal, {type: 'card_final', card: {id: 'plan_1', steps: []}});
assert(normal.lifecycle === 'accepted' && normal.card.id === 'plan_1', 'final must accept card');

const zeroDelta = stateApi.create('goal');
stateApi.apply(zeroDelta, {type: 'card_final', card: {id: 'plan_2', steps: []}});
assert(zeroDelta.lifecycle === 'accepted', 'zero delta final must be accepted');

const retry = stateApi.create('goal');
stateApi.apply(retry, {type: 'card_delta', delta: '{"steps":[{"title":"old"}]}' });
stateApi.apply(retry, {type: 'card_retry', attempt: 2});
assert(retry.buffer === '' && retry.partial.value === null, 'retry must clear prior attempt');

const degraded = stateApi.create('goal');
stateApi.apply(degraded, {type: 'card_delta', delta: 'plain'});
stateApi.apply(degraded, {type: 'card_delta', delta: ' text'});
assert(degraded.lifecycle === 'degraded', 'two parser failures must degrade');
stateApi.apply(degraded, {type: 'card_final', card: {id: 'plan_3'}});
assert(degraded.lifecycle === 'degraded', 'degraded stream must never switch back');

const failed = stateApi.create('goal');
stateApi.apply(failed, {type: 'error', code: 'card_validation_failed', done: true});
assert(failed.lifecycle === 'degraded' && failed.terminal, 'terminal error must retain degraded state');
stateApi.disconnect(failed);
assert(failed.cleared, 'disconnect must request UI cleanup');

const plainFallback = stateApi.create('goal');
stateApi.apply(plainFallback, {type: 'card_degrade', reason: 'generation_failed'});
stateApi.apply(plainFallback, {type: 'token', token: '请重试'});
assert(plainFallback.plainText === '请重试', 'degraded stream must keep plain text growth');

const prefixedFallback = stateApi.create('goal');
stateApi.apply(prefixedFallback, {type: 'card_delta', delta: '{"steps":[{"title":"half"'});
stateApi.apply(prefixedFallback, {type: 'not_decomposable', done: true, reason: 'model_none'});
assert(prefixedFallback.cleared && prefixedFallback.buffer === '', 'prefixed fallback must clear provisional data');
assert(prefixedFallback.partial.value === null, 'prefixed fallback must clear provisional parse');

const emptyFallback = stateApi.create('goal');
stateApi.apply(emptyFallback, {type: 'not_decomposable', done: true, reason: 'greeting'});
assert(emptyFallback.cleared && emptyFallback.buffer === '', 'zero-delta fallback must remain empty');

process.stdout.write(JSON.stringify({scenarios: 8}) + '\n');
