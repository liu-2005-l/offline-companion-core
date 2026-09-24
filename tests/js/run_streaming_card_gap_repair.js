'use strict';

const fs = require('fs');
const path = require('path');
const stateApi = require('../../src/offline_companion/shell/ui_host/desktop/static/streaming_card_state.js');

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const apiPath = path.resolve(
  __dirname,
  '../../src/offline_companion/shell/ui_host/desktop/static/shell_api.js'
);
const source = fs.readFileSync(apiPath, 'utf8');
const start = source.indexOf('async function apiReadSseStream');
const end = source.indexOf('async function apiLatestSseSeq');
const apiJson = async function() {
  return {
    events: [
      {type: 'card_delta', seq: 10, delta: '{"steps":['},
      {type: 'card_delta', seq: 11, delta: '{"title":"x"}]'}
    ],
    latest_seq: 12
  };
};
const functions = new Function(
  'apiJson',
  source.slice(start, end) + '\nreturn {apiReadSseStream, apiRepairSseGap};'
)(apiJson);

const state = stateApi.create('goal');
stateApi.apply(state, {type: 'card_delta', seq: 10, delta: '{"steps":['});
const seen = [];
const onEvent = function(event) {
  seen.push(event.seq);
  stateApi.apply(state, event);
};
const encoded = new TextEncoder().encode(
  'data: {"type":"card_delta","seq":12,"delta":"}"}\n\n'
);
let readCount = 0;
const response = {
  body: {
    getReader: function() {
      return {
        read: async function() {
          readCount += 1;
          return readCount === 1 ? {done: false, value: encoded} : {done: true};
        }
      };
    }
  }
};

(async function() {
  const result = await functions.apiReadSseStream(response, onEvent, {
    initialSeq: 10,
    onGap: function(fromSeq, untilSeq) {
      return functions.apiRepairSseGap('h1', fromSeq, onEvent, untilSeq);
    }
  });
  assert(JSON.stringify(seen) === JSON.stringify([11, 12]), 'repair must skip seq equal to latestSeq');
  assert(state.buffer === '{"steps":[{"title":"x"}]}', 'card buffer must accumulate each seq once');
  assert(state.partial.complete === true, 'repaired card must finish as complete JSON');
  assert(result.latestSeq === 12, 'latest seq must advance monotonically');
  process.stdout.write(JSON.stringify({seen: seen, complete: state.partial.complete}) + '\n');
})().catch(function(error) {
  process.stderr.write(String(error.stack || error) + '\n');
  process.exitCode = 1;
});
