(function(root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.StreamingCardParser = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function() {
  'use strict';

  function ParseFailure() {}

  function PartialJsonParser(source) {
    this.source = String(source);
    this.length = this.source.length;
    this.index = 0;
  }

  PartialJsonParser.prototype.parse = function() {
    this.skipWhitespace();
    if (this.peek() !== '{') throw new ParseFailure();
    var value = this.parseObject();
    this.skipWhitespace();
    if (this.index !== this.length) throw new ParseFailure();
    return value;
  };

  PartialJsonParser.prototype.parseObject = function() {
    this.consume('{');
    var value = {};
    this.skipWhitespace();
    if (this.atEnd()) return value;
    if (this.peek() === '}') {
      this.index += 1;
      return value;
    }
    while (true) {
      this.skipWhitespace();
      if (this.atEnd()) return value;
      if (this.peek() !== '"') throw new ParseFailure();
      var keyResult = this.parseString();
      if (!keyResult.complete) return value;
      this.skipWhitespace();
      if (this.atEnd()) return value;
      if (this.peek() !== ':') throw new ParseFailure();
      this.index += 1;
      this.skipWhitespace();
      if (this.atEnd()) {
        value[keyResult.value] = null;
        return value;
      }
      value[keyResult.value] = this.parseValue();
      this.skipWhitespace();
      if (this.atEnd()) return value;
      var marker = this.peek();
      if (marker === '}') {
        this.index += 1;
        return value;
      }
      if (marker !== ',') throw new ParseFailure();
      this.index += 1;
      this.skipWhitespace();
      if (this.atEnd()) return value;
    }
  };

  PartialJsonParser.prototype.parseArray = function() {
    this.consume('[');
    var value = [];
    this.skipWhitespace();
    if (this.atEnd()) return value;
    if (this.peek() === ']') {
      this.index += 1;
      return value;
    }
    while (true) {
      this.skipWhitespace();
      if (this.atEnd()) return value;
      value.push(this.parseValue());
      this.skipWhitespace();
      if (this.atEnd()) return value;
      var marker = this.peek();
      if (marker === ']') {
        this.index += 1;
        return value;
      }
      if (marker !== ',') throw new ParseFailure();
      this.index += 1;
      this.skipWhitespace();
      if (this.atEnd()) return value;
    }
  };

  PartialJsonParser.prototype.parseValue = function() {
    var marker = this.peek();
    if (marker === '{') return this.parseObject();
    if (marker === '[') return this.parseArray();
    if (marker === '"') return this.parseString().value;
    if ('tfn'.indexOf(marker) !== -1) return this.parseLiteral();
    if (marker === '-' || /[0-9]/.test(marker)) return this.parseNumber();
    throw new ParseFailure();
  };

  PartialJsonParser.prototype.parseString = function() {
    this.consume('"');
    var result = '';
    var escapes = {'"': '"', '\\': '\\', '/': '/', b: '\b', f: '\f', n: '\n', r: '\r', t: '\t'};
    while (!this.atEnd()) {
      var character = this.source[this.index++];
      if (character === '"') return {value: result, complete: true};
      if (character !== '\\') {
        if (character.charCodeAt(0) < 0x20) throw new ParseFailure();
        result += character;
        continue;
      }
      if (this.atEnd()) return {value: result, complete: false};
      var escaped = this.source[this.index];
      if (escaped === 'u') {
        var digits = this.source.slice(this.index + 1, this.index + 5);
        if (digits.length < 4) {
          this.index = this.length;
          return {value: result, complete: false};
        }
        if (!/^[0-9a-fA-F]{4}$/.test(digits)) throw new ParseFailure();
        result += String.fromCharCode(parseInt(digits, 16));
        this.index += 5;
        continue;
      }
      if (!Object.prototype.hasOwnProperty.call(escapes, escaped)) throw new ParseFailure();
      result += escapes[escaped];
      this.index += 1;
    }
    return {value: result, complete: false};
  };

  PartialJsonParser.prototype.parseLiteral = function() {
    var start = this.index;
    while (!this.atEnd() && /[A-Za-z]/.test(this.peek())) this.index += 1;
    var token = this.source.slice(start, this.index);
    var values = {true: true, false: false, null: null};
    if (Object.prototype.hasOwnProperty.call(values, token)) return values[token];
    if (['true', 'false', 'null'].some(function(item) { return item.indexOf(token) === 0; })) return null;
    throw new ParseFailure();
  };

  PartialJsonParser.prototype.parseNumber = function() {
    var start = this.index;
    while (!this.atEnd() && !/[ \t\r\n,\]}]/.test(this.peek())) this.index += 1;
    var token = this.source.slice(start, this.index);
    if (/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$/.test(token)) return Number(token);
    if (/^-?(?:(?:0|[1-9]\d*)?(?:\.)?|(?:0|[1-9]\d*)(?:\.\d+)?[eE][+-]?)$/.test(token)) return null;
    throw new ParseFailure();
  };

  PartialJsonParser.prototype.skipWhitespace = function() {
    while (!this.atEnd() && /[ \t\r\n]/.test(this.source[this.index])) this.index += 1;
  };

  PartialJsonParser.prototype.consume = function(expected) {
    if (this.peek() !== expected) throw new ParseFailure();
    this.index += 1;
  };

  PartialJsonParser.prototype.peek = function() {
    return this.atEnd() ? '' : this.source[this.index];
  };

  PartialJsonParser.prototype.atEnd = function() {
    return this.index >= this.length;
  };

  function childPath(frames) {
    if (!frames.length) return '';
    var parent = frames[frames.length - 1];
    if (parent.kind === 'array') return parent.path + '[' + parent.nextIndex + ']';
    var key = parent.pendingKey;
    parent.pendingKey = null;
    if (key === null) return parent.path;
    return parent.path ? parent.path + '.' + key : key;
  }

  function scanCardStructure(buffer) {
    var source = String(buffer);
    var frames = [];
    var closed = [];
    var index = 0;
    var inString = false;
    var escape = false;
    var stringStart = 0;
    var l0Active = false;
    var valid = true;
    while (index < source.length) {
      var character = source[index];
      if (inString) {
        if (escape) escape = false;
        else if (character === '\\') escape = true;
        else if (character === '"') {
          inString = false;
          var nextIndex = index + 1;
          while (nextIndex < source.length && /[ \t\r\n]/.test(source[nextIndex])) nextIndex += 1;
          if (frames.length && frames[frames.length - 1].kind === 'object' && source[nextIndex] === ':') {
            try {
              var parser = new PartialJsonParser(source.slice(stringStart, index + 1));
              var keyResult = parser.parseString();
              if (!keyResult.complete || !parser.atEnd()) throw new ParseFailure();
              frames[frames.length - 1].pendingKey = keyResult.value;
            } catch (_error) {
              valid = false;
              break;
            }
          }
        }
        index += 1;
        continue;
      }
      if (character === '"') {
        inString = true;
        stringStart = index;
        index += 1;
        continue;
      }
      if (character === '{' || character === '[') {
        var path = childPath(frames);
        if (character === '[' && path === 'steps' && frames.length === 1) l0Active = true;
        frames.push({kind: character === '{' ? 'object' : 'array', path: path, nextIndex: 0, pendingKey: null});
      } else if (character === '}' || character === ']') {
        var expected = character === '}' ? 'object' : 'array';
        if (!frames.length || frames[frames.length - 1].kind !== expected) {
          valid = false;
          break;
        }
        var frame = frames.pop();
        if (frame.kind === 'object' && /^steps\[\d+\]$/.test(frame.path)) closed.push(frame.path);
      } else if (character === ',' && frames.length) {
        var current = frames[frames.length - 1];
        if (current.kind === 'array') current.nextIndex += 1;
        else current.pendingKey = null;
      }
      index += 1;
    }
    return {
      closed: valid ? closed : [],
      openStack: valid ? frames.map(function(frame) { return frame.kind; }) : [],
      l0Active: valid ? l0Active : false,
      valid: valid,
      lexicalComplete: !inString && !escape
    };
  }

  function parsePartialCard(buffer) {
    var scan = scanCardStructure(buffer);
    if (!scan.valid) return {value: null, closed: [], complete: false};
    var value;
    try {
      value = new PartialJsonParser(buffer).parse();
    } catch (_error) {
      return {value: null, closed: [], complete: false};
    }
    return {
      value: value,
      closed: scan.closed,
      complete: scan.lexicalComplete && scan.openStack.length === 0
    };
  }

  return {parsePartialCard: parsePartialCard, scanCardStructure: scanCardStructure};
});
