'use strict';

const fs = require('fs');
const path = require('path');
const parser = require('../../src/offline_companion/shell/ui_host/desktop/static/streaming_card_parser.js');

const fixturePath = path.resolve(__dirname, '../../fixtures/streaming_cards/b1_partial_parse_golden.json');
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
let checked = 0;

function assertDeepEqual(actual, expected, label) {
  const actualJson = JSON.stringify(actual);
  const expectedJson = JSON.stringify(expected);
  if (actualJson !== expectedJson) {
    throw new Error(label + '\nexpected: ' + expectedJson + '\nactual:   ' + actualJson);
  }
}

function verify(entry, label) {
  const result = parser.parsePartialCard(entry.buffer);
  const scan = parser.scanCardStructure(entry.buffer);
  assertDeepEqual(result, entry.expected, label + ' PartialParse');
  assertDeepEqual(scan.l0Active, entry.l0_active, label + ' L0');
  checked += 1;
}

fixture.cases.forEach((entry) => verify(entry, entry.id));
fixture.chains.forEach((chain) => {
  chain.entries.forEach((entry, index) => verify(entry, chain.id + '[' + index + ']'));
});

process.stdout.write(JSON.stringify({checked: checked}) + '\n');
