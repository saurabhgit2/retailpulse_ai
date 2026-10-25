import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Measure the element a chart draws into.
 *
 * An SVG chart needs pixel dimensions before it can place anything, and the
 * width is whatever the grid gives it. A `viewBox` with `preserveAspectRatio`
 * would avoid measuring, but it scales the text too, so labels end up at
 * different sizes in different cards.
 *
 * Height is fixed by the caller and includes the axis band. Sizing the
 * container to the plot alone is what produces a card with a tiny nested
 * scrollbar under the chart.
 */
export function useChartSize(height) {
  const [width, setWidth] = useState(0);
  const observed = useRef(null);

  // A callback ref rather than useRef + useEffect([]): the node can arrive
  // after the first paint (inside a conditional branch), and a ref object
  // does not re-run an effect when its .current changes.
  const ref = useCallback((node) => {
    observed.current = node;
    if (node) setWidth(node.clientWidth);
  }, []);

  useEffect(() => {
    const node = observed.current;
    if (!node || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const next = entry.contentRect.width;
        // Ignore sub-pixel jitter, which otherwise re-renders on every scroll
        // in browsers that report fractional widths.
        setWidth((current) => (Math.abs(current - next) < 1 ? current : next));
      }
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return { ref, width, height, ready: width > 0 };
}
