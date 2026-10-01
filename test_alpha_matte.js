const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const context = vm.createContext({Uint8Array, Uint32Array, Map, Math});
vm.runInContext(fs.readFileSync(path.join(__dirname, 'ctrlc', 'assets', 'alpha_matte.js'), 'utf8'), context);

test('removes a flat backdrop and recovers smooth dark edges without white halos', () => {
  const pixels = new Uint8ClampedArray([246,246,246,255, 123,123,123,255, 0,0,0,255]);
  const stats = context.mattePixels(pixels, 3, 1, [246,246,246], [[0,0,0]]);
  assert.equal(pixels[3], 0);
  assert.deepEqual([...pixels.slice(4,7)], [0,0,0]);
  assert.equal(pixels[7], 128);
  assert.equal(pixels[11], 255);
  assert.equal(stats.partial, 1);
});

test('preserves original color for an opaque brand pixel', () => {
  const pixels = new Uint8ClampedArray([66,133,244,255]);
  context.mattePixels(pixels, 1, 1, [246,246,246], [[66,133,244]]);
  assert.deepEqual([...pixels], [66,133,244,255]);
});

test('keeps an outlined button fill opaque while removing exterior background', () => {
  const pixels = new Uint8ClampedArray(5*5*4);
  for (let i = 0; i < 25; i++) pixels.set([246,246,246,255], i*4);
  for (let y = 1; y <= 3; y++) for (let x = 1; x <= 3; x++) {
    if (x === 1 || x === 3 || y === 1 || y === 3) pixels.set([198,198,198,255], (y*5+x)*4);
  }
  context.mattePixels(pixels, 5, 5, [246,246,246], [[198,198,198]], true);
  assert.equal(pixels[3], 0);
  assert.equal(pixels[(2*5+2)*4+3], 255);
  assert.deepEqual([...pixels.slice((2*5+2)*4,(2*5+2)*4+3)], [246,246,246]);
});

test('keeps a white glyph inside a gray icon', () => {
  const pixels = new Uint8ClampedArray([224,224,224,255, 170,170,170,255, 255,255,255,255]);
  context.mattePixels(pixels, 3, 1, [224,224,224], [[170,170,170],[255,255,255]]);
  assert.equal(pixels[3], 0);
  assert.deepEqual([...pixels.slice(4)], [170,170,170,255, 255,255,255,255]);
});

test('keeps internal antialiasing opaque while cleaning an icon exterior', () => {
  const pixels = new Uint8ClampedArray(5*5*4);
  for (let i = 0; i < 25; i++) pixels.set([224,224,224,255], i*4);
  for (let y = 1; y <= 3; y++) for (let x = 1; x <= 3; x++) {
    pixels.set([170,170,170,255], (y*5+x)*4);
  }
  pixels.set([201,201,201,255], (2*5+2)*4);
  context.mattePixels(pixels, 5, 5, [224,224,224], [[170,170,170],[255,255,255]], true);
  assert.equal(pixels[3], 0);
  assert.deepEqual([...pixels.slice((2*5+2)*4,(2*5+2)*4+4)], [201,201,201,255]);
});
