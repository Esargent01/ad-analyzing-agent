import { motion, useReducedMotion } from "framer-motion";
import { viewportConfig } from "./animation-variants";

const NODES = [
  { label: "Elements", angle: -90 },
  { label: "Genomes", angle: -18 },
  { label: "Variants", angle: 54 },
  { label: "Metrics", angle: 126 },
  { label: "Insights", angle: 198 },
];

const RADIUS = 120;
const CX = 160;
const CY = 160;

function polarToCart(angleDeg: number) {
  const rad = (angleDeg * Math.PI) / 180;
  return { x: CX + RADIUS * Math.cos(rad), y: CY + RADIUS * Math.sin(rad) };
}

function arcPath(from: { x: number; y: number }, to: { x: number; y: number }) {
  return `M ${from.x} ${from.y} A ${RADIUS} ${RADIUS} 0 0 1 ${to.x} ${to.y}`;
}

export function CompoundAnimation() {
  const reduced = useReducedMotion();
  const positions = NODES.map((n) => polarToCart(n.angle));

  return (
    <motion.div
      className="flex h-full items-center justify-center"
      initial="hidden"
      whileInView="visible"
      viewport={viewportConfig}
    >
      <svg
        viewBox="0 0 320 320"
        className="w-full max-w-[320px]"
        style={{ fontFamily: "'Outfit', sans-serif" }}
      >
        {/* Connecting arcs */}
        {positions.map((pos, i) => {
          const next = positions[(i + 1) % positions.length];
          return (
            <motion.path
              key={`arc-${i}`}
              d={arcPath(pos, next)}
              fill="none"
              stroke="#d4d0ca"
              strokeWidth={1.5}
              strokeLinecap="round"
              variants={{
                hidden: { pathLength: 0, opacity: 0 },
                visible: {
                  pathLength: 1,
                  opacity: 1,
                  transition: {
                    pathLength: {
                      delay: reduced ? 0 : 0.8 + i * 0.15,
                      duration: 0.5,
                      ease: [0.16, 1, 0.3, 1],
                    },
                    opacity: {
                      delay: reduced ? 0 : 0.8 + i * 0.15,
                      duration: 0.1,
                    },
                  },
                },
              }}
            />
          );
        })}

        {/* Arrow heads on arcs */}
        {positions.map((_, i) => {
          const next = positions[(i + 1) % positions.length];
          const prev = positions[i];
          const dx = next.x - prev.x;
          const dy = next.y - prev.y;
          const angle = (Math.atan2(dy, dx) * 180) / Math.PI;
          const midAngle = NODES[i].angle + (72 / 2);
          const mid = polarToCart(midAngle);
          return (
            <motion.polygon
              key={`arrow-${i}`}
              points="0,-3 6,0 0,3"
              fill="#d4d0ca"
              transform={`translate(${mid.x}, ${mid.y}) rotate(${angle})`}
              variants={{
                hidden: { opacity: 0 },
                visible: {
                  opacity: 1,
                  transition: { delay: reduced ? 0 : 1.2 + i * 0.15, duration: 0.2 },
                },
              }}
            />
          );
        })}

        {/* Nodes */}
        {NODES.map((node, i) => {
          const pos = positions[i];
          const colors = ["#f5ebe0", "#e0eaf5", "#e8f0e8", "#f5e8f0", "#faf3e0"];
          return (
            <motion.g
              key={node.label}
              variants={{
                hidden: { opacity: 0, scale: 0.7 },
                visible: {
                  opacity: 1,
                  scale: 1,
                  transition: {
                    delay: reduced ? 0 : 0.1 + i * 0.12,
                    duration: 0.4,
                    ease: [0.16, 1, 0.3, 1],
                  },
                },
              }}
              style={{ originX: `${pos.x}px`, originY: `${pos.y}px` }}
            >
              <circle
                cx={pos.x}
                cy={pos.y}
                r={28}
                fill={colors[i]}
                stroke="#e8e5e0"
                strokeWidth={1}
              />
              <text
                x={pos.x}
                y={pos.y + 1}
                textAnchor="middle"
                dominantBaseline="middle"
                fontSize={10}
                fontWeight={500}
                fill="#1a1a1a"
              >
                {node.label}
              </text>
            </motion.g>
          );
        })}

        {/* Traveling pulse dot */}
        {!reduced && (
          <motion.circle
            r={4}
            fill="#1a1a1a"
            variants={{
              hidden: { opacity: 0 },
              visible: {
                opacity: [0, 1, 1, 1, 1, 1, 0],
                cx: positions.map((p) => p.x).concat(positions[0].x),
                cy: positions.map((p) => p.y).concat(positions[0].y),
                transition: {
                  delay: 2.0,
                  duration: 3.0,
                  ease: "linear",
                  repeat: Infinity,
                  repeatDelay: 1.5,
                },
              },
            }}
          />
        )}

        {/* Center label */}
        <motion.text
          x={CX}
          y={CY}
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize={11}
          fontWeight={600}
          fill="#999"
          variants={{
            hidden: { opacity: 0 },
            visible: {
              opacity: 1,
              transition: { delay: reduced ? 0 : 1.8, duration: 0.4 },
            },
          }}
        >
          Cycle
        </motion.text>
      </svg>
    </motion.div>
  );
}
