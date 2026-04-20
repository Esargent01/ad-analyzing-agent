import { useState, type FormEvent } from "react";

import { ApiError } from "@/lib/api/client";
import { useSuggestGenome } from "@/lib/api/hooks";

interface SuggestGenomeFormProps {
  campaignId: string;
  allowedSlots: string[];
}

/**
 * "Suggest your own copy" form for the authed experiments page.
 *
 * Ported to the warm-editorial system — white card, mono eyebrow
 * labels, ``.ds-input`` fields, primary submit button, flash row
 * for success / error states. Contents feed the gene pool via the
 * existing ``useSuggestGenome`` mutation (slot_name + slot_value
 * + optional description) and are used by next week's generator.
 */
export function SuggestGenomeForm({
  campaignId,
  allowedSlots,
}: SuggestGenomeFormProps) {
  const suggest = useSuggestGenome(campaignId);

  const [slotName, setSlotName] = useState<string>(allowedSlots[0] ?? "");
  const [slotValue, setSlotValue] = useState("");
  const [description, setDescription] = useState("");
  const [flash, setFlash] = useState<
    | { kind: "success"; text: string }
    | { kind: "error"; text: string }
    | null
  >(null);

  if (allowedSlots.length === 0) {
    return null;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFlash(null);

    const value = slotValue.trim();
    if (!value) {
      setFlash({ kind: "error", text: "Your copy cannot be empty." });
      return;
    }

    try {
      await suggest.mutateAsync({
        slot_name: slotName,
        slot_value: value,
        description: description.trim() || undefined,
      });
      setFlash({
        kind: "success",
        text: "Added to gene pool — it will be used next week.",
      });
      setSlotValue("");
      setDescription("");
    } catch (err) {
      const message =
        err instanceof ApiError
          ? typeof err.detail === "object" &&
            err.detail !== null &&
            "detail" in (err.detail as Record<string, unknown>)
            ? String((err.detail as { detail: unknown }).detail)
            : err.message
          : "Something went wrong.";
      setFlash({ kind: "error", text: message });
    }
  }

  return (
    <div
      style={{
        padding: 22,
        border: "1px solid var(--border)",
        borderRadius: 12,
        background: "white",
      }}
    >
      <h3
        style={{
          fontSize: 15,
          fontWeight: 500,
          color: "var(--ink)",
          margin: 0,
          letterSpacing: "-0.01em",
        }}
      >
        Suggest your own copy
      </h3>
      <p
        style={{
          marginTop: 4,
          fontSize: 12.5,
          color: "var(--muted)",
          lineHeight: 1.5,
          maxWidth: 560,
        }}
      >
        Add your own headline, body, or CTA to the gene pool. The next
        weekly generator will consider it when proposing new variants.
      </p>

      <form
        onSubmit={(e) => void handleSubmit(e)}
        style={{
          marginTop: 18,
          display: "grid",
          gap: 14,
          maxWidth: 560,
        }}
      >
        <FormField label="Slot" htmlFor="suggest-slot">
          <select
            id="suggest-slot"
            value={slotName}
            onChange={(e) => setSlotName(e.target.value)}
            disabled={suggest.isPending}
            className="ds-input"
            style={{ background: "white" }}
          >
            {allowedSlots.map((slot) => (
              <option key={slot} value={slot}>
                {slot}
              </option>
            ))}
          </select>
        </FormField>

        <FormField label="Your copy" htmlFor="suggest-value">
          <input
            id="suggest-value"
            type="text"
            value={slotValue}
            onChange={(e) => setSlotValue(e.target.value)}
            maxLength={500}
            placeholder="e.g., Limited time — 40% off everything"
            disabled={suggest.isPending}
            className="ds-input"
            required
          />
        </FormField>

        <FormField label="Notes (optional)" htmlFor="suggest-description">
          <input
            id="suggest-description"
            type="text"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            maxLength={500}
            placeholder="What is this trying to do?"
            disabled={suggest.isPending}
            className="ds-input"
          />
        </FormField>

        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button
            type="submit"
            className="btn btn-primary btn-sm"
            disabled={suggest.isPending}
          >
            {suggest.isPending ? "Adding…" : "Add to gene pool"}
          </button>
          {flash && (
            <p
              role="status"
              style={{
                margin: 0,
                fontSize: 12.5,
                color:
                  flash.kind === "success"
                    ? "oklch(40% 0.14 145)"
                    : "oklch(48% 0.16 28)",
              }}
            >
              {flash.text}
            </p>
          )}
        </div>
      </form>
    </div>
  );
}

function FormField({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label
        htmlFor={htmlFor}
        className="eyebrow"
        style={{ display: "block", fontSize: 10, marginBottom: 6 }}
      >
        {label}
      </label>
      {children}
    </div>
  );
}
