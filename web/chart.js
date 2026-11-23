const ns = 'http://www.w3.org/2000/svg';
function mark(svg, tag, attrs, text) {
  const node = document.createElementNS(ns, tag);
  Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
  if (text !== undefined) node.textContent = text;
  svg.append(node);
  return node;
}
const line = (svg, x1, y1, x2, y2, cls = 'line') => mark(svg, 'line', { x1, y1, x2, y2, class: cls });
const rect = (svg, x, y, width, height, cls) => mark(svg, 'rect', { x, y, width, height, class: cls });
const dot = (svg, cx, cy, cls, r = 3) => mark(svg, 'circle', { cx, cy, r, class: cls });
const text = (svg, x, y, value) => mark(svg, 'text', { x, y }, value);
const path = (svg, points, cls) => mark(svg, 'polyline', { points: points.map((p) => p.join(',')).join(' '), class: cls });
function scale(lo, hi, a, b) { return (n) => a + (b - a) * (n - lo) / (hi - lo || 1); }
function range(values, fallback = [0, 1]) { return values.length ? [Math.min(...values), Math.max(...values)] : fallback; }
function grid(svg, a, b, unit) {
  for (let index = 0; index <= 5; index++) {
    const x = 58 + index * 122;
    line(svg, x, 30, x, 197);
    text(svg, x - 7, 217, Number((a + (b - a) * index / 5).toPrecision(4)));
  }
  text(svg, 686, 217, unit);
}

function render(svg, { source, outputs }) {
    if (!outputs.mass) {
      text(svg, 58, 120, '盲样验收结论见下方验收阶段明细');
      text(svg, 58, 150, `整批结论：${outputs.state ?? '—'}`);
      return;
    }
    const points = outputs.mass;
    const [a,b] = range(points.map((p) => p.time));
    const x = scale(a,b,58,668), y = scale(0,Math.max(source.threshold,...points.map((p) => p.hi ?? 0)),190,40);
    grid(svg,a,b,'分钟');
    line(svg,58,y(source.threshold),668,y(source.threshold),'series alert');
    for (const p of points) {
      if (p.lo === null) { dot(svg,x(p.time),190,'empty-mark',5); continue; }
      line(svg,x(p.time),y(p.lo),x(p.time),y(p.hi),'series');
      dot(svg,x(p.time),y(p.lo),'mark');dot(svg,x(p.time),y(p.hi),'mark');
    }
    text(svg,58,24,'累计质量（微克／平方厘米）');
}

export function draw(svg, packet, config) {
  svg.replaceChildren();
  mark(svg, 'title', {}, config.plot);
  render(svg, packet);
}
