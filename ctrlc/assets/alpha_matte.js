// Recover coverage for flat UI artwork composited over a known uniform background.
// Pixels that do not fit this model remain unchanged.
function foregroundPalette(data, background) {
  const counts = new Map();
  let maximumDistance = 0;
  for (let i = 0; i < data.length; i += 4) {
    const distance = Math.max(...background.map((b, channel) => Math.abs(data[i + channel] - b)));
    maximumDistance = Math.max(maximumDistance, distance);
    if (distance < 10) continue;
    const color = (data[i] << 16) | (data[i + 1] << 8) | data[i + 2];
    counts.set(color, (counts.get(color) || 0) + 1);
  }
  const sorted = [...counts].sort((a, b) => b[1] - a[1]);
  const minimumCount = Math.max(2, (sorted[0]?.[1] || 0) * .02);
  const palette = [];
  for (const [packed, count] of sorted) {
    if (count < minimumCount) break;
    const color = [(packed >> 16) & 255, (packed >> 8) & 255, packed & 255];
    const vector = color.map((v, i) => v - background[i]);
    const length = Math.hypot(...vector);
    if (Math.max(...vector.map(Math.abs)) < maximumDistance * .5) continue;
    let matched = false;
    for (let i = 0; i < palette.length; i++) {
      const other = palette[i].map((v, c) => v - background[c]);
      const otherLength = Math.hypot(...other);
      const cosine = vector.reduce((sum, v, c) => sum + v * other[c], 0) / (length * otherLength);
      if (cosine > .995) {
        if (length > otherLength) palette[i] = color;
        matched = true;
        break;
      }
    }
    if (!matched) palette.push(color);
    if (palette.length === 10) break;
  }
  return palette;
}

function exteriorBackground(data, width, height, background) {
  const count = width * height;
  const mask = new Uint8Array(count);
  const queue = new Uint32Array(count);
  let start = 0, end = 0;
  const visit = index => {
    if (index < 0 || index >= count || mask[index]) return;
    const offset = index * 4;
    if (Math.max(...background.map((b, c) => Math.abs(data[offset + c] - b))) > 8) return;
    mask[index] = 1;
    queue[end++] = index;
  };
  for (let x = 0; x < width; x++) { visit(x); visit((height - 1) * width + x); }
  for (let y = 0; y < height; y++) { visit(y * width); visit(y * width + width - 1); }
  while (start < end) {
    const index = queue[start++];
    const x = index % width;
    if (x > 0) visit(index - 1);
    if (x + 1 < width) visit(index + 1);
    visit(index - width);
    visit(index + width);
  }
  // Include one edge pixel for smooth coverage, without crossing the control rim.
  const edges = mask.slice();
  for (let index = 0; index < count; index++) {
    if (!mask[index]) continue;
    const x = index % width;
    if (x > 0) edges[index - 1] = 1;
    if (x + 1 < width) edges[index + 1] = 1;
    if (index >= width) edges[index - width] = 1;
    if (index + width < count) edges[index + width] = 1;
  }
  return edges;
}

function mattePixels(data, width, height, background, foreground = null, exteriorOnly = false) {
  const palette = foreground || foregroundPalette(data, background);
  const vectors = palette.map(color => {
    const vector = color.map((v, c) => v - background[c]);
    return {vector, squared: vector.reduce((sum, v) => sum + v * v, 0)};
  }).filter(candidate => candidate.squared > 0);
  const eligible = exteriorOnly ? exteriorBackground(data, width, height, background) : null;
  const statistics = {transparent: 0, partial: 0, opaque: 0};
  for (let index = 0; index < width * height; index++) {
    const offset = index * 4;
    if (!eligible || eligible[index]) {
      const difference = background.map((b, c) => data[offset + c] - b);
      if (Math.max(...difference.map(Math.abs)) <= 1) {
        data[offset + 3] = 0;
      } else {
        let best = null;
        for (const candidate of vectors) {
          const alpha = Math.max(0, Math.min(1, difference.reduce(
            (sum, value, c) => sum + value * candidate.vector[c], 0) / candidate.squared));
          const error = difference.reduce((sum, value, c) => sum + (value - alpha * candidate.vector[c]) ** 2, 0);
          if (!best || error < best.error) best = {alpha, error};
        }
        if (best && best.error <= 18.75) {
          if (best.alpha < .015) data[offset + 3] = 0;
          else {
            for (let channel = 0; channel < 3; channel++) {
              data[offset + channel] = Math.round((data[offset + channel]
                - (1 - best.alpha) * background[channel]) / best.alpha);
            }
            data[offset + 3] = Math.round(best.alpha * 255);
          }
        }
      }
    }
    const alpha = data[offset + 3];
    statistics[alpha === 0 ? 'transparent' : alpha === 255 ? 'opaque' : 'partial']++;
  }
  return statistics;
}
