import { motion } from "framer-motion";
import { roadmapItems } from "../data/roadmapContent";
import { Panel, SectionTitle } from "../components/ui";

export default function Roadmap() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
      className="max-w-4xl mx-auto space-y-6"
    >
      <SectionTitle
        eyebrow="Beyond this build"
        title="What's real today, and what's next"
        description="Everything shown elsewhere in this prototype — detection, fingerprinting, the evidence locker, the attribution gap, and the incident report — is real, working functionality. The items below are not built yet, and this prototype does not pretend otherwise."
      />

      <div className="space-y-3">
        {roadmapItems.map((item, i) => (
          <Panel key={i} className="p-5 sm:p-6 flex flex-col sm:flex-row sm:items-start justify-between gap-3 sm:gap-6">
            <div>
              <p className="text-[13.5px] font-semibold text-ink mb-1">{item.title}</p>
              <p className="text-[12.5px] text-muted leading-relaxed max-w-xl">
                {item.detail}
              </p>
            </div>
            <span className="shrink-0 font-mono text-[11px] text-brand border border-brand/30 bg-soft px-2.5 py-1 rounded-lg self-start">
              {item.status}
            </span>
          </Panel>
        ))}
      </div>
    </motion.div>
  );
}
