import { motion, useReducedMotion } from "framer-motion";
import { viewportConfig } from "./animation-variants";

const SANS = "'Outfit', sans-serif";

const elements = [
  {
    label: "Headline",
    content: "Summer Sale — 50% Off",
    color: "#f5ebe0",
    target: { x: -40, y: -60, rotate: -3 },
  },
  {
    label: "Media",
    content: null, // image placeholder
    color: "#e0eaf5",
    target: { x: 50, y: -20, rotate: 2 },
  },
  {
    label: "CTA",
    content: "Shop Now",
    color: "#e8f0e8",
    target: { x: 40, y: 50, rotate: 3 },
  },
  {
    label: "Audience",
    content: "Women 25-34",
    color: "#f5e8f0",
    target: { x: -50, y: 40, rotate: -2 },
  },
];

const containerVariants = {
  hidden: {},
  visible: {
    transition: { staggerChildren: 0.15, delayChildren: 0.6 },
  },
};

const cardVariants = {
  hidden: { opacity: 0, scale: 0.95 },
  visible: {
    opacity: 1,
    scale: 1,
    transition: { duration: 0.5, ease: [0.16, 1, 0.3, 1] as const },
  },
};

export function DecomposeAnimation() {
  const reduced = useReducedMotion();

  return (
    <motion.div
      className="relative flex h-full items-center justify-center"
      initial="hidden"
      whileInView="visible"
      viewport={viewportConfig}
    >
      {/* Assembled card container */}
      <motion.div
        className="relative"
        variants={containerVariants}
      >
        {/* Ad card background */}
        <motion.div
          className="relative w-[260px] rounded-xl border border-[#e8e5e0] bg-white p-0 shadow-sm"
          variants={cardVariants}
        >
          {/* Headline element */}
          <motion.div
            className="relative border-b border-dashed border-[#d4d0ca] px-5 py-4"
            variants={{
              hidden: { x: 0, y: 0, rotate: 0 },
              visible: reduced
                ? {}
                : {
                    x: elements[0].target.x,
                    y: elements[0].target.y,
                    rotate: elements[0].target.rotate,
                    transition: { duration: 0.7, ease: [0.16, 1, 0.3, 1], delay: 0.3 },
                  },
            }}
          >
            <div
              className="rounded-lg px-3 py-2 text-[13px] font-medium text-[#1a1a1a]"
              style={{ backgroundColor: elements[0].color, fontFamily: SANS }}
            >
              {elements[0].content}
            </div>
            <motion.span
              className="absolute -right-2 -top-3 rounded-full bg-[#1a1a1a] px-2 py-0.5 text-[10px] font-medium text-white"
              variants={{
                hidden: { opacity: 0, scale: 0.8 },
                visible: {
                  opacity: 1,
                  scale: 1,
                  transition: { delay: 1.4, duration: 0.3 },
                },
              }}
            >
              {elements[0].label}
            </motion.span>
          </motion.div>

          {/* Media element */}
          <motion.div
            className="relative border-b border-dashed border-[#d4d0ca] px-5 py-4"
            variants={{
              hidden: { x: 0, y: 0, rotate: 0 },
              visible: reduced
                ? {}
                : {
                    x: elements[1].target.x,
                    y: elements[1].target.y,
                    rotate: elements[1].target.rotate,
                    transition: { duration: 0.7, ease: [0.16, 1, 0.3, 1], delay: 0.45 },
                  },
            }}
          >
            <div
              className="flex h-24 items-center justify-center rounded-lg text-[12px] text-[#999]"
              style={{ backgroundColor: elements[1].color }}
            >
              <svg
                className="mr-1.5 h-4 w-4 text-[#999]"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={1.5}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="m2.25 15.75 5.159-5.159a2.25 2.25 0 0 1 3.182 0l5.159 5.159m-1.5-1.5 1.409-1.409a2.25 2.25 0 0 1 3.182 0l2.909 2.909M3.75 21h16.5A2.25 2.25 0 0 0 22.5 18.75V5.25A2.25 2.25 0 0 0 20.25 3H3.75A2.25 2.25 0 0 0 1.5 5.25v13.5A2.25 2.25 0 0 0 3.75 21Z"
                />
              </svg>
              creative.mp4
            </div>
            <motion.span
              className="absolute -left-2 -top-3 rounded-full bg-[#1a1a1a] px-2 py-0.5 text-[10px] font-medium text-white"
              variants={{
                hidden: { opacity: 0, scale: 0.8 },
                visible: {
                  opacity: 1,
                  scale: 1,
                  transition: { delay: 1.55, duration: 0.3 },
                },
              }}
            >
              {elements[1].label}
            </motion.span>
          </motion.div>

          {/* CTA element */}
          <motion.div
            className="relative border-b border-dashed border-[#d4d0ca] px-5 py-4"
            variants={{
              hidden: { x: 0, y: 0, rotate: 0 },
              visible: reduced
                ? {}
                : {
                    x: elements[2].target.x,
                    y: elements[2].target.y,
                    rotate: elements[2].target.rotate,
                    transition: { duration: 0.7, ease: [0.16, 1, 0.3, 1], delay: 0.6 },
                  },
            }}
          >
            <div
              className="rounded-full px-4 py-2 text-center text-[13px] font-medium text-[#1a1a1a]"
              style={{ backgroundColor: elements[2].color, fontFamily: SANS }}
            >
              {elements[2].content}
            </div>
            <motion.span
              className="absolute -right-2 -bottom-3 rounded-full bg-[#1a1a1a] px-2 py-0.5 text-[10px] font-medium text-white"
              variants={{
                hidden: { opacity: 0, scale: 0.8 },
                visible: {
                  opacity: 1,
                  scale: 1,
                  transition: { delay: 1.7, duration: 0.3 },
                },
              }}
            >
              {elements[2].label}
            </motion.span>
          </motion.div>

          {/* Audience element */}
          <motion.div
            className="relative px-5 py-4"
            variants={{
              hidden: { x: 0, y: 0, rotate: 0 },
              visible: reduced
                ? {}
                : {
                    x: elements[3].target.x,
                    y: elements[3].target.y,
                    rotate: elements[3].target.rotate,
                    transition: { duration: 0.7, ease: [0.16, 1, 0.3, 1], delay: 0.75 },
                  },
            }}
          >
            <div
              className="rounded-lg px-3 py-2 text-[12px] text-[#666]"
              style={{ backgroundColor: elements[3].color, fontFamily: SANS }}
            >
              {elements[3].content}
            </div>
            <motion.span
              className="absolute -left-2 -bottom-3 rounded-full bg-[#1a1a1a] px-2 py-0.5 text-[10px] font-medium text-white"
              variants={{
                hidden: { opacity: 0, scale: 0.8 },
                visible: {
                  opacity: 1,
                  scale: 1,
                  transition: { delay: 1.85, duration: 0.3 },
                },
              }}
            >
              {elements[3].label}
            </motion.span>
          </motion.div>
        </motion.div>
      </motion.div>
    </motion.div>
  );
}
